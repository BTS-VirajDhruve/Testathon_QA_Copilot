"""User management API route tests."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable

from app.models.auth import UserPublic
from app.services.user_service import get_user_service
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_user_routes_require_admin_role(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> None:
    qa_user = seed_user(role="qa")
    tokens = login_and_get_tokens(email=qa_user.email, password="SecurePass123!")
    response = auth_client.get(
        "/api/users", headers=_auth_headers(tokens["access_token"])
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


def test_admin_user_crud_endpoints_and_aliases(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.email_service.EmailService.send_invite_email",
        lambda *_args, **_kwargs: True,
    )
    admin_user = seed_user(role="admin")
    tokens = login_and_get_tokens(email=admin_user.email, password="SecurePass123!")
    headers = _auth_headers(tokens["access_token"])

    invited = auth_client.post(
        "/api/users/invite",
        headers=headers,
        json={
            "name": "Invited QA",
            "email": "invited-qa@example.com",
            "role": "qa",
        },
    )
    assert invited.status_code == 201
    assert invited.json()["success"] is True

    created = auth_client.post(
        "/api/users",
        headers=headers,
        json={
            "name": "Managed QA",
            "email": "managed-qa@example.com",
            "password": "ManagedPass123!",
            "role": "qa",
            "isActive": True,
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    user_id = created_body["id"]
    assert created_body["email"] == "managed-qa@example.com"

    duplicate = auth_client.post(
        "/api/users",
        headers=headers,
        json={
            "name": "Managed QA Two",
            "email": "managed-qa@example.com",
            "password": "ManagedPass123!",
            "role": "qa",
            "isActive": True,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "USER_ALREADY_EXISTS"

    listed_primary = auth_client.get("/api/users", headers=headers)
    assert listed_primary.status_code == 200
    assert any(
        item["email"] == "managed-qa@example.com" for item in listed_primary.json()
    )

    listed_alias = auth_client.get("/api/auth/users", headers=headers)
    assert listed_alias.status_code == 200
    assert any(
        item["email"] == "managed-qa@example.com" for item in listed_alias.json()
    )

    patched = auth_client.patch(
        f"/api/users/{user_id}",
        headers=headers,
        json={"name": "Managed QA Updated"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Managed QA Updated"

    put_alias = auth_client.put(
        f"/api/auth/users/{user_id}",
        headers=headers,
        json={"role": "admin"},
    )
    assert put_alias.status_code == 200
    assert put_alias.json()["role"] == "admin"

    deactivated = auth_client.post(f"/api/users/{user_id}/deactivate", headers=headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["isActive"] is False

    soft_deleted = auth_client.post(
        f"/api/auth/users/{user_id}/soft-delete", headers=headers
    )
    assert soft_deleted.status_code == 200
    assert soft_deleted.json()["success"] is True

    deleted_again = auth_client.delete(f"/api/users/{user_id}", headers=headers)
    assert deleted_again.status_code == 404
    assert deleted_again.json()["detail"]["code"] == "USER_NOT_FOUND"


def test_invite_and_accept_onboarding_flow_end_to_end(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.email_service.EmailService.send_invite_email",
        lambda *_args, **_kwargs: True,
    )
    admin_user = seed_user(role="admin")
    tokens = login_and_get_tokens(email=admin_user.email, password="SecurePass123!")
    headers = _auth_headers(tokens["access_token"])

    invite_token_issued = False
    real_token_urlsafe = secrets.token_urlsafe

    def _fake_token_urlsafe(size: int) -> str:
        nonlocal invite_token_issued
        if size == 24:
            return "temp-pass-token-value"
        if size == 32 and not invite_token_issued:
            invite_token_issued = True
            return "invite-onboarding-token-1234567890"
        return real_token_urlsafe(size)

    monkeypatch.setattr(
        "app.services.auth_service.secrets.token_urlsafe",
        _fake_token_urlsafe,
    )

    invited = auth_client.post(
        "/api/users/invite",
        headers=headers,
        json={
            "name": "Onboarded QA",
            "email": "onboarded-qa@example.com",
            "role": "qa",
        },
    )
    assert invited.status_code == 201
    assert invited.json()["success"] is True

    accepted = auth_client.post(
        "/api/auth/accept-invite",
        json={
            "token": "invite-onboarding-token-1234567890",
            "newPassword": "WelcomePass123!",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["success"] is True

    login = auth_client.post(
        "/api/auth/login",
        json={"email": "onboarded-qa@example.com", "password": "WelcomePass123!"},
    )
    assert login.status_code == 200
    onboarded_doc = _run(
        get_user_service().get_user_document_by_email(
            "onboarded-qa@example.com",
            include_deleted=True,
        )
    )
    assert onboarded_doc is not None
    assert onboarded_doc["isActive"] is True


def test_invite_reactivates_deleted_user(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.email_service.EmailService.send_invite_email",
        lambda *_args, **_kwargs: True,
    )
    deleted_user = seed_user(
        role="qa",
        deleted=True,
        email="reactivate-invite@example.com",
    )
    assert deleted_user.deletedAt is not None

    admin_user = seed_user(role="admin")
    tokens = login_and_get_tokens(email=admin_user.email, password="SecurePass123!")
    headers = _auth_headers(tokens["access_token"])

    invited = auth_client.post(
        "/api/users/invite",
        headers=headers,
        json={
            "name": "Reactivated User",
            "email": "reactivate-invite@example.com",
            "role": "qa",
        },
    )
    assert invited.status_code == 201
    assert invited.json()["success"] is True

    reactivated_doc = _run(
        get_user_service().get_user_document_by_email(
            "reactivate-invite@example.com",
            include_deleted=True,
        )
    )
    assert reactivated_doc is not None
    assert reactivated_doc["deletedAt"] is None
    assert reactivated_doc["isActive"] is False
