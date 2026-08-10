"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import uuid4

import app.core.config as config
import app.db.mongo as mongo_mod
import app.services.auth_service as auth_mod
import app.services.email_service as email_mod
import app.services.model_router as model_router_mod
import app.services.user_service as user_mod
import pytest
from app.main import create_app
from app.models.auth import RoleType, UserCreateInput, UserPublic
from app.services.user_service import get_user_service
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_singletons_and_config(monkeypatch):
    monkeypatch.setenv("MONGO_ENABLED", "true")
    monkeypatch.setenv("MONGO_URI", "mongomock://localhost")
    monkeypatch.setenv("MONGO_DB_NAME", "qa_copilot_test")
    monkeypatch.setenv("JWT_ACCESS_SECRET", "test-access-secret")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "test-refresh-secret")
    monkeypatch.setenv("JWT_ISSUER", "qa-copilot-tests")

    config.get_settings.cache_clear()
    _run(mongo_mod.close_mongo())
    _run(mongo_mod.init_mongo())
    auth_mod._auth_service = None
    email_mod._email_service = None
    user_mod._user_service = None
    model_router_mod.reset_model_router()
    yield
    config.get_settings.cache_clear()
    _run(mongo_mod.close_mongo())
    auth_mod._auth_service = None
    email_mod._email_service = None
    user_mod._user_service = None
    model_router_mod.reset_model_router()


@pytest.fixture
def auth_client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def seed_user() -> Callable[..., UserPublic]:
    def _seed_user(
        *,
        role: RoleType = "qa",
        is_active: bool = True,
        deleted: bool = False,
        email: str | None = None,
        password: str = "SecurePass123!",
    ) -> UserPublic:
        service = get_user_service()
        user = _run(
            service.create_user(
                UserCreateInput(
                    name=f"{role.title()} User",
                    email=email or f"{role}-{uuid4().hex[:8]}@example.com",
                    password=password,
                    role=role,
                    isActive=is_active,
                )
            )
        )
        if deleted:
            _run(service.soft_delete_user(user.id))
            deleted_user = _run(
                service.get_user_document_by_id(user.id, include_deleted=True)
            )
            if not deleted_user:
                raise RuntimeError("Seeded user missing after soft delete")
            return UserPublic.model_validate(deleted_user)
        return user

    return _seed_user


@pytest.fixture
def login_and_get_tokens(auth_client: TestClient) -> Callable[..., dict[str, str]]:
    def _login_and_get_tokens(*, email: str, password: str) -> dict[str, str]:
        response = auth_client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200
        payload = response.json()
        return {
            "access_token": payload["accessToken"],
            "refresh_token": payload["refreshToken"],
        }

    return _login_and_get_tokens


@pytest.fixture
def authenticated_client(
    auth_client: TestClient,
    seed_user: Callable[..., UserPublic],
    login_and_get_tokens: Callable[..., dict[str, str]],
) -> TestClient:
    email = f"test-admin-{uuid4().hex[:8]}@example.com"
    password = "SecurePass123!"
    seed_user(role="admin", email=email, password=password)
    tokens = login_and_get_tokens(email=email, password=password)
    auth_client.headers.update({"Authorization": f"Bearer {tokens['access_token']}"})
    return auth_client
