"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth_dependencies import get_current_authenticated_user
from app.core.config import get_settings
from app.db.mongo import init_mongo, mongo_health_signal
from app.models.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    SelfProfileUpdateRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    TokenPairResponse,
    UserPublic,
)
from app.services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_auth_service() -> AuthService:
    settings = get_settings()
    init_mongo()
    mongo = mongo_health_signal()
    if not settings.mongo_enabled or not mongo.get("connected"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication requires MongoDB connectivity",
        )
    return get_auth_service()


@router.post("/login", response_model=TokenPairResponse)
def login(body: LoginRequest, service: AuthService = Depends(_require_auth_service)) -> TokenPairResponse:
    return service.login(body)


@router.post("/refresh", response_model=TokenPairResponse)
def refresh(body: RefreshRequest, service: AuthService = Depends(_require_auth_service)) -> TokenPairResponse:
    return service.refresh(body.refreshToken)


@router.post("/logout")
def logout(body: LogoutRequest, service: AuthService = Depends(_require_auth_service)) -> dict[str, bool]:
    return {"success": service.logout(body.refreshToken)}


@router.get("/me", response_model=MeResponse)
def me(user: UserPublic = Depends(get_current_authenticated_user)) -> MeResponse:
    return MeResponse(user=user)


@router.patch("/me", response_model=MeResponse)
def update_me(
    body: SelfProfileUpdateRequest,
    user: UserPublic = Depends(get_current_authenticated_user),
    service: AuthService = Depends(_require_auth_service),
) -> MeResponse:
    updated = service.update_my_profile(user_id=user.id, body=body)
    return MeResponse(user=updated)


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    body: ChangePasswordRequest,
    user: UserPublic = Depends(get_current_authenticated_user),
    service: AuthService = Depends(_require_auth_service),
) -> ChangePasswordResponse:
    return service.change_my_password(user_id=user.id, body=body)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    body: ForgotPasswordRequest, service: AuthService = Depends(_require_auth_service)
) -> ForgotPasswordResponse:
    return service.forgot_password(body.email)


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    body: ResetPasswordRequest, service: AuthService = Depends(_require_auth_service)
) -> ResetPasswordResponse:
    return service.reset_password(token=body.token, new_password=body.newPassword)
