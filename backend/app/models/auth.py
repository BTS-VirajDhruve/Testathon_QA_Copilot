"""Auth and user domain schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleType = Literal["systemadmin", "admin", "qa"]


class UserCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    role: RoleType = "qa"
    isActive: bool = True


class UserUpdateInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: RoleType | None = None
    isActive: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
    forgotPasswordToken: str | None = None


class UserPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    email: str
    role: RoleType
    isActive: bool
    createdAt: datetime
    updatedAt: datetime
    deletedAt: datetime | None = None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


class RefreshRequest(BaseModel):
    refreshToken: str = Field(min_length=20)


class LogoutRequest(BaseModel):
    refreshToken: str = Field(min_length=20)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    newPassword: str = Field(min_length=8, max_length=256)


class ResetPasswordResponse(BaseModel):
    success: bool = True


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    newPassword: str = Field(min_length=8, max_length=256)


class AcceptInviteResponse(BaseModel):
    success: bool = True


class TokenPairResponse(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "bearer"
    user: UserPublic


class MeResponse(BaseModel):
    user: UserPublic


class SelfProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=254)


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(min_length=8, max_length=256)
    newPassword: str = Field(min_length=8, max_length=256)


class ChangePasswordResponse(BaseModel):
    success: bool = True


class InviteUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    role: RoleType = "qa"


class InviteUserResponse(BaseModel):
    success: bool = True
    message: str
    email: str
