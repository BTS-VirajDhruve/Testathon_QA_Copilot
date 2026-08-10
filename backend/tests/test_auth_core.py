"""Auth and user-domain tests for Mongo-backed identity flow."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from app.db.mongo import get_users_collection
from app.main import create_app
from app.models.auth import UserCreateInput, UserUpdateInput
from app.services.security import hash_token
from app.services.user_service import UserAlreadyExistsError, get_user_service


def _create_test_user(email: str = "qa@example.com", password: str = "SecurePass123!") -> None:
    get_user_service().create_user(
        UserCreateInput(
            name="QA User",
            email=email,
            password=password,
            role="qa",
            isActive=True,
        )
    )


def test_user_crud_soft_delete_and_secret_safety():
    service = get_user_service()
    created = service.create_user(
        UserCreateInput(
            name="Admin One",
            email="admin@example.com",
            password="AnotherPass123!",
            role="admin",
            isActive=True,
        )
    )
    assert created.email == "admin@example.com"

    updated = service.update_user(
        created.id,
        body=UserUpdateInput(name="Admin One Updated", forgotPasswordToken="raw-reset-token"),
    )
    assert updated.name == "Admin One Updated"
    internal = service.get_user_document_by_email("admin@example.com", include_deleted=True)
    assert internal is not None
    assert internal.get("forgotPasswordToken") != "raw-reset-token"
    assert "password" in internal

    deleted = service.soft_delete_user(created.id)
    assert deleted is True
    assert service.get_user_document_by_id(created.id) is None


def test_duplicate_email_rejected():
    _create_test_user(email="dup@example.com")
    with pytest.raises(UserAlreadyExistsError):
        _create_test_user(email="dup@example.com")


def test_auth_login_refresh_logout_and_me():
    _create_test_user()
    client = TestClient(create_app())

    login = client.post(
        "/api/auth/login",
        json={"email": "qa@example.com", "password": "SecurePass123!"},
    )
    assert login.status_code == 200
    payload = login.json()
    assert payload["tokenType"] == "bearer"
    assert payload["user"]["email"] == "qa@example.com"
    assert "password" not in payload["user"]
    assert "forgotPasswordToken" not in payload["user"]

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['accessToken']}"},
    )
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "qa@example.com"

    refreshed = client.post("/api/auth/refresh", json={"refreshToken": payload["refreshToken"]})
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload["refreshToken"] != payload["refreshToken"]

    old_refresh = client.post("/api/auth/refresh", json={"refreshToken": payload["refreshToken"]})
    assert old_refresh.status_code == 401

    logout = client.post("/api/auth/logout", json={"refreshToken": refreshed_payload["refreshToken"]})
    assert logout.status_code == 200
    assert logout.json()["success"] is True

    revoked_refresh = client.post(
        "/api/auth/refresh",
        json={"refreshToken": refreshed_payload["refreshToken"]},
    )
    assert revoked_refresh.status_code == 401


def test_inactive_and_soft_deleted_user_cannot_login():
    service = get_user_service()
    inactive = service.create_user(
        UserCreateInput(
            name="Inactive User",
            email="inactive@example.com",
            password="SecurePass123!",
            role="qa",
            isActive=False,
        )
    )
    client = TestClient(create_app())
    inactive_login = client.post(
        "/api/auth/login",
        json={"email": "inactive@example.com", "password": "SecurePass123!"},
    )
    assert inactive_login.status_code == 403

    active = service.create_user(
        UserCreateInput(
            name="Active User",
            email="active@example.com",
            password="SecurePass123!",
            role="qa",
            isActive=True,
        )
    )
    assert service.soft_delete_user(active.id) is True
    deleted_login = client.post(
        "/api/auth/login",
        json={"email": "active@example.com", "password": "SecurePass123!"},
    )
    assert deleted_login.status_code == 403


def test_forgot_password_unknown_email_returns_neutral_response():
    client = TestClient(create_app())
    response = client.post("/api/auth/forgot-password", json={"email": "missing@example.com"})
    assert response.status_code == 200
    assert response.json() == {
        "message": "If an account exists for this email, a reset link has been sent."
    }


def test_forgot_password_inactive_or_deleted_user_remains_neutral_and_safe():
    service = get_user_service()
    inactive = service.create_user(
        UserCreateInput(
            name="Inactive Forgot",
            email="inactive-forgot@example.com",
            password="SecurePass123!",
            role="qa",
            isActive=False,
        )
    )
    active = service.create_user(
        UserCreateInput(
            name="Deleted Forgot",
            email="deleted-forgot@example.com",
            password="SecurePass123!",
            role="qa",
            isActive=True,
        )
    )
    assert service.soft_delete_user(active.id) is True

    client = TestClient(create_app())
    inactive_response = client.post(
        "/api/auth/forgot-password",
        json={"email": "inactive-forgot@example.com"},
    )
    deleted_response = client.post(
        "/api/auth/forgot-password",
        json={"email": "deleted-forgot@example.com"},
    )
    assert inactive_response.status_code == 200
    assert deleted_response.status_code == 200
    assert inactive_response.json() == deleted_response.json()

    inactive_doc = service.get_user_document_by_email("inactive-forgot@example.com", include_deleted=True)
    deleted_doc = service.get_user_document_by_email("deleted-forgot@example.com", include_deleted=True)
    assert inactive_doc is not None
    assert deleted_doc is not None
    assert inactive_doc.get("forgotPasswordToken") is None
    assert inactive_doc.get("forgotPasswordTokenExpiresAt") is None
    assert deleted_doc.get("forgotPasswordToken") is None
    assert deleted_doc.get("forgotPasswordTokenExpiresAt") is None


def test_forgot_and_reset_password_happy_path_revokes_existing_refresh_tokens(monkeypatch):
    _create_test_user(email="forgot@example.com", password="OldPass123!")
    client = TestClient(create_app())

    login = client.post(
        "/api/auth/login",
        json={"email": "forgot@example.com", "password": "OldPass123!"},
    )
    assert login.status_code == 200
    old_refresh_token = login.json()["refreshToken"]

    raw_reset_token = "reset-token-for-tests-1234567890"
    monkeypatch.setattr("app.services.auth_service.secrets.token_urlsafe", lambda _: raw_reset_token)
    forgot = client.post("/api/auth/forgot-password", json={"email": "forgot@example.com"})
    assert forgot.status_code == 200
    assert forgot.json() == {
        "message": "If an account exists for this email, a reset link has been sent."
    }

    user_doc = get_user_service().get_user_document_by_email("forgot@example.com", include_deleted=True)
    assert user_doc is not None
    assert user_doc["forgotPasswordToken"] == hash_token(raw_reset_token)
    assert user_doc["forgotPasswordToken"] != raw_reset_token
    assert user_doc.get("forgotPasswordTokenExpiresAt") is not None

    reset = client.post(
        "/api/auth/reset-password",
        json={"token": raw_reset_token, "newPassword": "NewPass123!"},
    )
    assert reset.status_code == 200
    assert reset.json() == {"success": True}

    reused = client.post(
        "/api/auth/reset-password",
        json={"token": raw_reset_token, "newPassword": "AnotherPass123!"},
    )
    assert reused.status_code == 400

    old_password_login = client.post(
        "/api/auth/login",
        json={"email": "forgot@example.com", "password": "OldPass123!"},
    )
    assert old_password_login.status_code == 401

    revoked_refresh = client.post("/api/auth/refresh", json={"refreshToken": old_refresh_token})
    assert revoked_refresh.status_code == 401

    new_password_login = client.post(
        "/api/auth/login",
        json={"email": "forgot@example.com", "password": "NewPass123!"},
    )
    assert new_password_login.status_code == 200


def test_reset_password_rejects_invalid_and_expired_tokens(monkeypatch):
    _create_test_user(email="reset-invalid@example.com", password="SecurePass123!")
    client = TestClient(create_app())

    invalid = client.post(
        "/api/auth/reset-password",
        json={"token": "bad-token-value-1234567890", "newPassword": "NextPass123!"},
    )
    assert invalid.status_code == 400

    raw_reset_token = "reset-token-expired-1234567890"
    monkeypatch.setattr("app.services.auth_service.secrets.token_urlsafe", lambda _: raw_reset_token)
    forgot = client.post("/api/auth/forgot-password", json={"email": "reset-invalid@example.com"})
    assert forgot.status_code == 200

    users = get_users_collection()
    users.update_one(
        {"email": "reset-invalid@example.com"},
        {"$set": {"forgotPasswordTokenExpiresAt": datetime(2000, 1, 1, tzinfo=timezone.utc)}},
    )

    expired = client.post(
        "/api/auth/reset-password",
        json={"token": raw_reset_token, "newPassword": "NextPass123!"},
    )
    assert expired.status_code == 400


def test_self_profile_update_and_duplicate_email_constraints():
    service = get_user_service()
    me_user = service.create_user(
        UserCreateInput(
            name="My Profile",
            email="profile@example.com",
            password="SecurePass123!",
            role="qa",
            isActive=True,
        )
    )
    service.create_user(
        UserCreateInput(
            name="Existing",
            email="existing@example.com",
            password="SecurePass123!",
            role="qa",
            isActive=True,
        )
    )
    client = TestClient(create_app())
    login = client.post(
        "/api/auth/login",
        json={"email": "profile@example.com", "password": "SecurePass123!"},
    )
    assert login.status_code == 200
    token = login.json()["accessToken"]

    update_name = client.patch(
        "/api/auth/me",
        json={"name": "Updated Profile Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_name.status_code == 200
    assert update_name.json()["user"]["name"] == "Updated Profile Name"

    duplicate_email = client.patch(
        "/api/auth/me",
        json={"email": "existing@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert duplicate_email.status_code == 409


def test_change_password_requires_current_password_and_revokes_refresh_tokens():
    _create_test_user(email="change-pass@example.com", password="OldPass123!")
    client = TestClient(create_app())
    login = client.post(
        "/api/auth/login",
        json={"email": "change-pass@example.com", "password": "OldPass123!"},
    )
    assert login.status_code == 200
    payload = login.json()
    token = payload["accessToken"]
    refresh_token = payload["refreshToken"]

    wrong_current = client.post(
        "/api/auth/change-password",
        json={"currentPassword": "WrongPass123!", "newPassword": "NewPass123!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert wrong_current.status_code == 400

    success = client.post(
        "/api/auth/change-password",
        json={"currentPassword": "OldPass123!", "newPassword": "NewPass123!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert success.status_code == 200
    assert success.json() == {"success": True}

    old_login = client.post(
        "/api/auth/login",
        json={"email": "change-pass@example.com", "password": "OldPass123!"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login",
        json={"email": "change-pass@example.com", "password": "NewPass123!"},
    )
    assert new_login.status_code == 200

    old_refresh = client.post("/api/auth/refresh", json={"refreshToken": refresh_token})
    assert old_refresh.status_code == 401
