"""User service for CRUD operations and response-safe shaping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.models.auth import UserCreateInput, UserPublic, UserUpdateInput
from app.repositories.user_repository import UserRepository
from app.services.security import hash_password, hash_token, verify_password


class UserAlreadyExistsError(ValueError):
    """Raised when a duplicate email is created."""


class UserNotFoundError(ValueError):
    """Raised when a user cannot be found."""


class UserPasswordMismatchError(ValueError):
    """Raised when provided current password is invalid."""


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self._repository = repository or UserRepository()

    async def create_user(self, body: UserCreateInput) -> UserPublic:
        try:
            doc = await self._repository.create(
                name=body.name,
                email=body.email,
                password_hash=hash_password(body.password),
                role=body.role,
                is_active=body.isActive,
            )
        except DuplicateKeyError as exc:
            raise UserAlreadyExistsError("User email already exists") from exc
        return self._to_public_user(doc)

    async def get_user_by_id(self, user_id: str) -> UserPublic:
        doc = await self._repository.get_by_id(user_id)
        if not doc:
            raise UserNotFoundError("User not found")
        return self._to_public_user(doc)

    async def get_user_document_by_email(
        self,
        email: str,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        return await self._repository.get_by_email(
            email, include_deleted=include_deleted
        )

    async def get_user_document_by_id(
        self,
        user_id: str,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        return await self._repository.get_by_id(
            user_id, include_deleted=include_deleted
        )

    async def list_users(self, include_deleted: bool = False) -> list[UserPublic]:
        docs = await self._repository.list_users(include_deleted=include_deleted)
        return [self._to_public_user(doc) for doc in docs]

    async def update_user(self, user_id: str, body: UserUpdateInput) -> UserPublic:
        updates: dict[str, Any] = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.role is not None:
            updates["role"] = body.role
        if body.isActive is not None:
            updates["isActive"] = body.isActive
        if body.password is not None:
            updates["password"] = hash_password(body.password)
        if body.forgotPasswordToken is not None:
            updates["forgotPasswordToken"] = hash_token(body.forgotPasswordToken)
        doc = await self._repository.update(user_id, updates)
        if not doc:
            raise UserNotFoundError("User not found")
        return self._to_public_user(doc)

    async def soft_delete_user(self, user_id: str) -> bool:
        return await self._repository.soft_delete(user_id)

    async def set_forgot_password_token(
        self, user_id: str, token: str, expires_in_minutes: int
    ) -> bool:
        expires_at = datetime.now(UTC) + timedelta(minutes=expires_in_minutes)
        return await self._repository.set_forgot_password_token(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )

    async def reset_password_with_forgot_token(
        self, token: str, new_password: str
    ) -> UserPublic | None:
        doc = await self._repository.consume_forgot_password_token(
            token_hash=hash_token(token),
            password_hash=hash_password(new_password),
        )
        if not doc:
            return None
        return self._to_public_user(doc)

    async def set_invite_token(
        self, user_id: str, token: str, expires_in_minutes: int
    ) -> bool:
        expires_at = datetime.now(UTC) + timedelta(minutes=expires_in_minutes)
        return await self._repository.set_invite_token(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )

    async def accept_invite_with_token(
        self, token: str, new_password: str
    ) -> UserPublic | None:
        doc = await self._repository.consume_invite_token(
            token_hash=hash_token(token),
            password_hash=hash_password(new_password),
        )
        if not doc:
            return None
        return self._to_public_user(doc)

    async def reactivate_deleted_user_for_invite(
        self,
        *,
        user_id: str,
        name: str,
        role: str,
        temporary_password: str,
    ) -> UserPublic:
        doc = await self._repository.reactivate_for_invite(
            user_id=user_id,
            name=name,
            role=role,
            password_hash=hash_password(temporary_password),
        )
        if not doc:
            raise UserNotFoundError("User not found")
        return self._to_public_user(doc)

    async def update_self_profile(
        self, user_id: str, *, name: str | None, email: str | None
    ) -> UserPublic:
        existing = await self._repository.get_by_id(user_id, include_deleted=True)
        if (
            not existing
            or existing.get("deletedAt") is not None
            or not existing.get("isActive", False)
        ):
            raise UserNotFoundError("User not found")

        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name.strip()
        if email is not None:
            updates["email"] = self._repository.normalize_email(email)
        if not updates:
            return self._to_public_user(existing)

        try:
            doc = await self._repository.update(user_id, updates)
        except DuplicateKeyError as exc:
            raise UserAlreadyExistsError("User email already exists") from exc
        if not doc:
            raise UserNotFoundError("User not found")
        return self._to_public_user(doc)

    async def change_self_password(
        self,
        user_id: str,
        *,
        current_password: str,
        new_password: str,
    ) -> UserPublic:
        existing = await self._repository.get_by_id(user_id, include_deleted=True)
        if (
            not existing
            or existing.get("deletedAt") is not None
            or not existing.get("isActive", False)
        ):
            raise UserNotFoundError("User not found")
        if not verify_password(str(existing.get("password") or ""), current_password):
            raise UserPasswordMismatchError("Current password is incorrect")
        doc = await self._repository.update(
            user_id, {"password": hash_password(new_password)}
        )
        if not doc:
            raise UserNotFoundError("User not found")
        return self._to_public_user(doc)

    @staticmethod
    def _to_public_user(doc: dict[str, Any]) -> UserPublic:
        return UserPublic.model_validate(
            {
                "id": doc.get("id") or doc.get("_id"),
                "name": doc["name"],
                "email": doc["email"],
                "role": doc["role"],
                "isActive": doc["isActive"],
                "createdAt": doc["createdAt"],
                "updatedAt": doc["updatedAt"],
                "deletedAt": doc.get("deletedAt"),
            }
        )


_user_service: UserService | None = None


def get_user_service() -> UserService:
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service
