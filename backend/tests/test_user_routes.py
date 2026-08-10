"""User management API route tests."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.models.auth import UserPublic


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_user_routes_require_admin_role(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> None:
    qa_user = seed_user(role="qa")
    tokens = login_and_get_tokens(email=qa_user.email, password="SecurePass123!")
    response = auth_client.get("/api/users", headers=_auth_headers(tokens["access_token"]))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


def test_admin_user_crud_endpoints_and_aliases(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> None:
    admin_user = seed_user(role="admin")
    tokens = login_and_get_tokens(email=admin_user.email, password="SecurePass123!")
    headers = _auth_headers(tokens["access_token"])

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
    assert any(item["email"] == "managed-qa@example.com" for item in listed_primary.json())

    listed_alias = auth_client.get("/api/auth/users", headers=headers)
    assert listed_alias.status_code == 200
    assert any(item["email"] == "managed-qa@example.com" for item in listed_alias.json())

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

    soft_deleted = auth_client.post(f"/api/auth/users/{user_id}/soft-delete", headers=headers)
    assert soft_deleted.status_code == 200
    assert soft_deleted.json()["success"] is True

    deleted_again = auth_client.delete(f"/api/users/{user_id}", headers=headers)
    assert deleted_again.status_code == 404
    assert deleted_again.json()["detail"]["code"] == "USER_NOT_FOUND"
