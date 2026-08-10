"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth_dependencies import get_current_authenticated_user
from app.core.config import get_settings
from app.db.mongo import mongo_health_signal
from app.models.auth import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SelfProfileUpdateRequest,
    TokenPairResponse,
    UserPublic,
)
from app.services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_auth_service() -> AuthService:
    settings = get_settings()
    mongo = mongo_health_signal()
    if not settings.mongo_enabled or not mongo.get("connected"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication requires MongoDB connectivity",
        )
    return get_auth_service()


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest, service: AuthService = Depends(_require_auth_service)
) -> TokenPairResponse:
    return await service.login(body)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    body: RefreshRequest, service: AuthService = Depends(_require_auth_service)
) -> TokenPairResponse:
    return await service.refresh(body.refreshToken)


@router.post("/logout")
async def logout(
    body: LogoutRequest, service: AuthService = Depends(_require_auth_service)
) -> dict[str, bool]:
    return {"success": await service.logout(body.refreshToken)}


@router.get("/me", response_model=MeResponse)
async def me(user: UserPublic = Depends(get_current_authenticated_user)) -> MeResponse:
    return MeResponse(user=user)


@router.patch("/me", response_model=MeResponse)
async def update_me(
    body: SelfProfileUpdateRequest,
    user: UserPublic = Depends(get_current_authenticated_user),
    service: AuthService = Depends(_require_auth_service),
) -> MeResponse:
    updated = await service.update_my_profile(user_id=user.id, body=body)
    return MeResponse(user=updated)


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: UserPublic = Depends(get_current_authenticated_user),
    service: AuthService = Depends(_require_auth_service),
) -> ChangePasswordResponse:
    return await service.change_my_password(user_id=user.id, body=body)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    body: ForgotPasswordRequest, service: AuthService = Depends(_require_auth_service)
) -> ForgotPasswordResponse:
    return await service.forgot_password(body.email)


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    body: ResetPasswordRequest, service: AuthService = Depends(_require_auth_service)
) -> ResetPasswordResponse:
    return await service.reset_password(token=body.token, new_password=body.newPassword)


@router.post("/accept-invite", response_model=AcceptInviteResponse)
async def accept_invite(
    body: AcceptInviteRequest, service: AuthService = Depends(_require_auth_service)
) -> AcceptInviteResponse:
    return await service.accept_invite(token=body.token, new_password=body.newPassword)
