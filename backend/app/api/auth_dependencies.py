"""Reusable API auth/authorization dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.db.mongo import mongo_health_signal
from app.models.auth import RoleType, UserPublic
from app.services.auth_service import AuthService, get_auth_service

_PUBLIC_ENDPOINTS: set[tuple[str, str]] = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("POST", "/api/auth/accept-invite"),
}
_REQUEST_USER_STATE_KEY = "_auth_user"


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    if path != "/" and path.endswith("/"):
        return path.rstrip("/")
    return path


def _is_public_endpoint(method: str, path: str) -> bool:
    return (method.upper(), _normalize_path(path)) in _PUBLIC_ENDPOINTS


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise _auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTHENTICATION_REQUIRED",
            "Missing Authorization bearer token",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise _auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_AUTHORIZATION_HEADER",
            "Authorization header must be in 'Bearer <token>' format",
        )
    return parts[1].strip()


async def _require_auth_service() -> AuthService:
    settings = get_settings()
    mongo = mongo_health_signal()
    if not settings.mongo_enabled or not mongo.get("connected"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication requires MongoDB connectivity",
        )
    return get_auth_service()


def _set_request_user(request: Request, user: UserPublic | None) -> None:
    setattr(request.state, _REQUEST_USER_STATE_KEY, user)


def _get_request_user(request: Request) -> UserPublic | None:
    return getattr(request.state, _REQUEST_USER_STATE_KEY, None)


async def _authenticate_request(
    request: Request, allow_public: bool
) -> UserPublic | None:
    if allow_public and _is_public_endpoint(request.method, request.url.path):
        return None

    token = _extract_bearer_token(request)
    service = await _require_auth_service()
    try:
        user = await service.get_user_from_access_token(token)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise _auth_error(
                status.HTTP_401_UNAUTHORIZED,
                "INVALID_OR_EXPIRED_TOKEN",
                "Invalid or expired access token",
            ) from exc
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            raise _auth_error(
                status.HTTP_403_FORBIDDEN,
                "ACCOUNT_INACTIVE",
                "User account is inactive",
            ) from exc
        raise
    _set_request_user(request, user)
    return user


async def require_request_authentication(request: Request) -> UserPublic | None:
    """Default router-level guard: public allowlist bypass, JWT for all others."""
    existing_user = _get_request_user(request)
    if existing_user is not None:
        return existing_user
    return await _authenticate_request(request, allow_public=True)


async def get_current_authenticated_user(request: Request) -> UserPublic:
    """Route-level guard that always requires a valid authenticated user."""
    existing_user = _get_request_user(request)
    if existing_user is not None:
        return existing_user
    user = await _authenticate_request(request, allow_public=False)
    if user is None:
        raise _auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTHENTICATION_REQUIRED",
            "Missing Authorization bearer token",
        )
    return user


def require_roles(
    *allowed_roles: RoleType,
) -> Callable[[Request], Awaitable[UserPublic]]:
    """Create a reusable role guard for route dependencies."""
    allowed: set[str] = set(allowed_roles)

    async def _role_dependency(request: Request) -> UserPublic:
        user = await get_current_authenticated_user(request)
        if user.role not in allowed:
            raise _auth_error(
                status.HTTP_403_FORBIDDEN,
                "INSUFFICIENT_ROLE",
                "User does not have permission for this action",
            )
        return user

    return _role_dependency


require_admin_user = require_roles("systemadmin", "admin")


def get_public_auth_endpoints() -> set[tuple[str, str]]:
    """Expose public auth endpoints for docs/tests."""
    return set(_PUBLIC_ENDPOINTS)
