"""Authentication service with JWT access/refresh lifecycle."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordResponse,
    LoginRequest,
    SelfProfileUpdateRequest,
    ResetPasswordResponse,
    TokenPairResponse,
    UserPublic,
)
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.services.security import hash_token, verify_password
from app.services.user_service import (
    UserAlreadyExistsError,
    UserNotFoundError,
    UserPasswordMismatchError,
    UserService,
    get_user_service,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(
        self,
        user_service: UserService | None = None,
        refresh_tokens: RefreshTokenRepository | None = None,
    ) -> None:
        self._settings = get_settings()
        self._user_service = user_service or get_user_service()
        self._refresh_tokens = refresh_tokens or RefreshTokenRepository()

    def login(self, body: LoginRequest) -> TokenPairResponse:
        user_doc = self._user_service.get_user_document_by_email(body.email, include_deleted=True)
        if not user_doc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if user_doc.get("deletedAt") is not None or not user_doc.get("isActive", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        if not verify_password(str(user_doc.get("password") or ""), body.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        return self._issue_token_pair(user_doc)

    def refresh(self, refresh_token: str) -> TokenPairResponse:
        payload = self._decode_token(
            token=refresh_token,
            secret=self._settings.jwt_refresh_secret,
            expected_type="refresh",
        )
        token_hash = hash_token(refresh_token)
        stored = self._refresh_tokens.get_active_by_hash(token_hash)
        if not stored:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")
        if stored.get("_id") != payload.get("jti") or stored.get("userId") != payload.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
        user = self._user_service.get_user_document_by_id(str(payload.get("sub") or ""), include_deleted=True)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        if user.get("deletedAt") is not None or not user.get("isActive", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
        return self._issue_token_pair(user, replaced_token_id=str(stored["_id"]))

    def logout(self, refresh_token: str) -> bool:
        try:
            self._decode_token(
                token=refresh_token,
                secret=self._settings.jwt_refresh_secret,
                expected_type="refresh",
            )
        except HTTPException:
            return True
        token_hash = hash_token(refresh_token)
        self._refresh_tokens.revoke_by_hash(token_hash)
        return True

    def get_user_from_access_token(self, access_token: str) -> UserPublic:
        payload = self._decode_token(
            token=access_token,
            secret=self._settings.jwt_access_secret,
            expected_type="access",
        )
        user_id = str(payload.get("sub") or "")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
        user = self._user_service.get_user_document_by_id(user_id, include_deleted=True)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        if user.get("deletedAt") is not None or not user.get("isActive", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
        return UserService._to_public_user(user)

    def forgot_password(self, email: str) -> ForgotPasswordResponse:
        user_doc = self._user_service.get_user_document_by_email(email, include_deleted=True)
        if not user_doc:
            return ForgotPasswordResponse(
                message="If an account exists for this email, a reset link has been sent."
            )
        if user_doc.get("deletedAt") is not None or not user_doc.get("isActive", False):
            return ForgotPasswordResponse(
                message="If an account exists for this email, a reset link has been sent."
            )
        reset_token = secrets.token_urlsafe(32)
        self._user_service.set_forgot_password_token(
            user_id=str(user_doc["id"]),
            token=reset_token,
            expires_in_minutes=self._settings.forgot_password_token_expire_minutes,
        )
        return ForgotPasswordResponse(
            message="If an account exists for this email, a reset link has been sent."
        )

    def reset_password(self, token: str, new_password: str) -> ResetPasswordResponse:
        updated_user = self._user_service.reset_password_with_forgot_token(
            token=token,
            new_password=new_password,
        )
        if not updated_user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")
        self._refresh_tokens.revoke_by_user_id(updated_user.id)
        return ResetPasswordResponse(success=True)

    def update_my_profile(self, user_id: str, body: SelfProfileUpdateRequest) -> UserPublic:
        try:
            return self._user_service.update_self_profile(
                user_id=user_id,
                name=body.name,
                email=body.email,
            )
        except UserAlreadyExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except UserNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def change_my_password(self, user_id: str, body: ChangePasswordRequest) -> ChangePasswordResponse:
        if body.currentPassword == body.newPassword:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password",
            )
        try:
            self._user_service.change_self_password(
                user_id=user_id,
                current_password=body.currentPassword,
                new_password=body.newPassword,
            )
        except UserPasswordMismatchError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        self._refresh_tokens.revoke_by_user_id(user_id)
        return ChangePasswordResponse(success=True)

    def _issue_token_pair(
        self, user_doc: dict[str, Any], replaced_token_id: str | None = None
    ) -> TokenPairResponse:
        now = utc_now()
        access_exp = now + timedelta(minutes=self._settings.jwt_access_token_minutes)
        refresh_exp = now + timedelta(days=self._settings.jwt_refresh_token_days)
        refresh_token_id = secrets.token_urlsafe(18)
        access_payload = {
            "sub": user_doc["id"],
            "email": user_doc["email"],
            "role": user_doc["role"],
            "type": "access",
            "iss": self._settings.jwt_issuer,
            "iat": int(now.timestamp()),
            "exp": int(access_exp.timestamp()),
        }
        refresh_payload = {
            "sub": user_doc["id"],
            "email": user_doc["email"],
            "type": "refresh",
            "iss": self._settings.jwt_issuer,
            "jti": refresh_token_id,
            "iat": int(now.timestamp()),
            "exp": int(refresh_exp.timestamp()),
        }
        access_token = jwt.encode(access_payload, self._settings.jwt_access_secret, algorithm="HS256")
        refresh_token = jwt.encode(refresh_payload, self._settings.jwt_refresh_secret, algorithm="HS256")
        saved = self._refresh_tokens.create(
            token_id=refresh_token_id,
            user_id=user_doc["id"],
            token_hash=hash_token(refresh_token),
            expires_at=refresh_exp,
        )
        if replaced_token_id:
            self._refresh_tokens.revoke_by_id(replaced_token_id, replaced_by_token_id=str(saved["_id"]))
        public_user = UserService._to_public_user(user_doc)
        return TokenPairResponse(accessToken=access_token, refreshToken=refresh_token, user=public_user)

    @staticmethod
    def _decode_token(*, token: str, secret: str, expected_type: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
