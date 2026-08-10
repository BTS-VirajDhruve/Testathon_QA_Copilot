"""Mongo-backed user repository with soft-delete support."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from app.db.mongo import get_users_collection
from app.models.schemas import new_id


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRepository:
    def __init__(self) -> None:
        self._collection = get_users_collection()

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    def create(
        self,
        *,
        name: str,
        email: str,
        password_hash: str,
        role: str,
        is_active: bool,
    ) -> dict[str, Any]:
        now = utc_now()
        doc = {
            "_id": new_id("usr"),
            "name": name.strip(),
            "email": self.normalize_email(email),
            "password": password_hash,
            "forgotPasswordToken": None,
            "forgotPasswordTokenExpiresAt": None,
            "isActive": is_active,
            "role": role,
            "createdAt": now,
            "updatedAt": now,
            "deletedAt": None,
        }
        self._collection.insert_one(doc)
        doc["id"] = doc["_id"]
        return doc

    def get_by_email(self, email: str, include_deleted: bool = False) -> dict[str, Any] | None:
        query: dict[str, Any] = {"email": self.normalize_email(email)}
        if not include_deleted:
            query["deletedAt"] = None
        doc = self._collection.find_one(query)
        return self._with_public_id(doc)

    def get_by_id(self, user_id: str, include_deleted: bool = False) -> dict[str, Any] | None:
        query: dict[str, Any] = {"_id": user_id}
        if not include_deleted:
            query["deletedAt"] = None
        doc = self._collection.find_one(query)
        return self._with_public_id(doc)

    def list_users(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if not include_deleted:
            query["deletedAt"] = None
        return [self._with_public_id(doc) for doc in self._collection.find(query).sort("createdAt", 1)]

    def update(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        update_payload = {**updates, "updatedAt": utc_now()}
        doc = self._collection.find_one_and_update(
            {"_id": user_id, "deletedAt": None},
            {"$set": update_payload},
            return_document=ReturnDocument.AFTER,
        )
        return self._with_public_id(doc)

    def set_forgot_password_token(self, user_id: str, token_hash: str, expires_at: datetime) -> bool:
        result = self._collection.update_one(
            {"_id": user_id, "deletedAt": None, "isActive": True},
            {
                "$set": {
                    "forgotPasswordToken": token_hash,
                    "forgotPasswordTokenExpiresAt": expires_at,
                    "updatedAt": utc_now(),
                }
            },
        )
        return result.modified_count > 0

    def consume_forgot_password_token(self, token_hash: str, password_hash: str) -> dict[str, Any] | None:
        now = utc_now()
        doc = self._collection.find_one_and_update(
            {
                "forgotPasswordToken": token_hash,
                "forgotPasswordTokenExpiresAt": {"$gt": now},
                "deletedAt": None,
                "isActive": True,
            },
            {
                "$set": {
                    "password": password_hash,
                    "forgotPasswordToken": None,
                    "forgotPasswordTokenExpiresAt": None,
                    "updatedAt": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._with_public_id(doc)

    def soft_delete(self, user_id: str) -> bool:
        now = utc_now()
        result = self._collection.update_one(
            {"_id": user_id, "deletedAt": None},
            {"$set": {"deletedAt": now, "isActive": False, "updatedAt": now}},
        )
        return result.modified_count > 0

    @staticmethod
    def _with_public_id(doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if doc is None:
            return None
        return {**doc, "id": str(doc["_id"])}
