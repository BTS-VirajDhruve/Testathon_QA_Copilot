"""MT-B6 auth hardening unit/integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from app.api.auth_dependencies import (
    _extract_bearer_token,
    _is_public_endpoint,
    _normalize_path,
)
from app.models.auth import UserPublic, UserUpdateInput
from app.services.security import (
    hash_password,
    hash_token,
    safe_compare,
    verify_password,
)
from app.services.user_service import get_user_service
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request


def _run(coro):
    return asyncio.run(coro)


def _make_request(*, authorization: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
            "scheme": "http",
            "http_version": "1.1",
            "client": ("testclient", 123),
            "server": ("testserver", 80),
        }
    )


def test_password_and_token_primitives_are_deterministic() -> None:
    password = "StrongPass123!"
    password_hash = hash_password(password)
    assert password_hash != password
    assert verify_password(password_hash, password) is True
    assert verify_password(password_hash, "wrong-pass") is False

    token = "reset-token-value-12345"
    token_hash = hash_token(token)
    assert token_hash == hash_token(token)
    assert len(token_hash) == 64
    assert safe_compare(token_hash, hash_token(token)) is True
    assert safe_compare(token_hash, hash_token("different-token-value")) is False


def test_extract_bearer_token_enforces_contract() -> None:
    request = _make_request(authorization="Bearer valid-token-123")
    assert _extract_bearer_token(request) == "valid-token-123"

    with pytest.raises(HTTPException) as missing_header:
        _extract_bearer_token(_make_request())
    assert missing_header.value.status_code == 401
    assert missing_header.value.detail["code"] == "AUTHENTICATION_REQUIRED"

    with pytest.raises(HTTPException) as invalid_header:
        _extract_bearer_token(_make_request(authorization="Token invalid"))
    assert invalid_header.value.status_code == 401
    assert invalid_header.value.detail["code"] == "INVALID_AUTHORIZATION_HEADER"


def test_public_endpoint_allowlist_handles_path_normalization() -> None:
    assert _normalize_path("/api/health/") == "/api/health"
    assert _is_public_endpoint("GET", "/api/health/")
    assert _is_public_endpoint("post", "/api/auth/forgot-password/")
    assert _is_public_endpoint("POST", "/api/auth/reset-password")
    assert _is_public_endpoint("POST", "/api/auth/accept-invite")
    assert _is_public_endpoint("GET", "/api/projects") is False


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("qa", 403), ("admin", 200), ("systemadmin", 200)],
)
def test_role_guard_matrix_for_admin_seed_route(
    role: str,
    expected_status: int,
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> None:
    user = seed_user(role=role)
    tokens = login_and_get_tokens(email=user.email, password="SecurePass123!")
    response = auth_client.post(
        "/api/demo/seed",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize("state_change", ["inactive", "deleted"])
def test_protected_route_rejects_inactive_or_deleted_users_after_login(
    state_change: str,
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> None:
    user = seed_user(role="qa")
    tokens = login_and_get_tokens(email=user.email, password="SecurePass123!")
    service = get_user_service()
    if state_change == "inactive":
        _run(service.update_user(user.id, UserUpdateInput(isActive=False)))
    else:
        _run(service.soft_delete_user(user.id))

    response = auth_client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCOUNT_INACTIVE"


@pytest.mark.parametrize("state_change", ["inactive", "deleted"])
def test_refresh_token_rejected_after_user_is_deactivated_or_deleted(
    state_change: str,
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> None:
    user = seed_user(role="qa")
    tokens = login_and_get_tokens(email=user.email, password="SecurePass123!")
    service = get_user_service()
    if state_change == "inactive":
        _run(service.update_user(user.id, UserUpdateInput(isActive=False)))
    else:
        _run(service.soft_delete_user(user.id))

    refreshed = auth_client.post(
        "/api/auth/refresh",
        json={"refreshToken": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 403
