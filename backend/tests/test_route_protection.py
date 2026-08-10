"""Protected route matrix tests for MT-B5."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.models.auth import RoleType, UserCreateInput
from app.services.user_service import get_user_service


def _create_user(email: str, role: RoleType = "qa", password: str = "SecurePass123!") -> None:
    get_user_service().create_user(
        UserCreateInput(
            name=f"{role.title()} User",
            email=email,
            password=password,
            role=role,
            isActive=True,
        )
    )


def _login_and_get_access_token(
    client: TestClient,
    *,
    role: RoleType = "qa",
    password: str = "SecurePass123!",
) -> tuple[str, dict[str, str]]:
    email = f"{role}-{uuid4().hex[:8]}@example.com"
    _create_user(email=email, role=role, password=password)
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    payload = login.json()
    token = payload["accessToken"]
    return token, payload


def test_protected_route_rejects_missing_token() -> None:
    client = TestClient(create_app())
    res = client.get("/api/projects")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


def test_protected_route_rejects_invalid_token() -> None:
    client = TestClient(create_app())
    res = client.get("/api/projects", headers={"Authorization": "Bearer invalid-token"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


def test_protected_route_allows_valid_token() -> None:
    client = TestClient(create_app())
    token, _ = _login_and_get_access_token(client, role="qa")
    res = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_admin_seed_route_rejects_insufficient_role() -> None:
    client = TestClient(create_app())
    token, _ = _login_and_get_access_token(client, role="qa")
    res = client.post("/api/demo/seed", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


def test_admin_seed_route_allows_admin_role() -> None:
    client = TestClient(create_app())
    token, _ = _login_and_get_access_token(client, role="admin")
    res = client.post("/api/demo/seed", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert "project_id" in body


def test_public_endpoint_allowlist_remains_unauthenticated() -> None:
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.status_code == 200

    # Logout stays public because it revokes refresh token from request body.
    logout = client.post("/api/auth/logout", json={"refreshToken": "invalid-refresh-token-value-12345"})
    assert logout.status_code == 200
    assert logout.json()["success"] is True

    forgot = client.post("/api/auth/forgot-password", json={"email": "qa@example.com"})
    reset = client.post(
        "/api/auth/reset-password",
        json={"token": "placeholder-token-value-12345", "newPassword": "SecurePass123!"},
    )
    assert forgot.status_code != 401
    assert reset.status_code != 401
