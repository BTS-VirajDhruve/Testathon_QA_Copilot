"""Mongo-backed refresh token persistence for rotation and revocation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.mongo import _maybe_await, get_refresh_tokens_collection
from app.models.schemas import new_id


def utc_now() -> datetime:
    return datetime.now(UTC)


class RefreshTokenRepository:
    def __init__(self) -> None:
        self._collection = get_refresh_tokens_collection()

    async def create(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        now = utc_now()
        doc = {
            "_id": token_id or new_id("rt"),
            "userId": user_id,
            "tokenHash": token_hash,
            "expiresAt": expires_at,
            "createdAt": now,
            "updatedAt": now,
            "revokedAt": None,
            "replacedByTokenId": None,
        }
        await _maybe_await(self._collection.insert_one(doc))
        return {**doc, "id": doc["_id"]}

    async def get_active_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        now = utc_now()
        doc = await _maybe_await(
            self._collection.find_one(
                {
                    "tokenHash": token_hash,
                    "revokedAt": None,
                    "expiresAt": {"$gt": now},
                }
            )
        )
        if not doc:
            return None
        return {**doc, "id": doc["_id"]}

    async def revoke_by_id(
        self, token_id: str, replaced_by_token_id: str | None = None
    ) -> bool:
        now = utc_now()
        payload: dict[str, Any] = {"revokedAt": now, "updatedAt": now}
        if replaced_by_token_id:
            payload["replacedByTokenId"] = replaced_by_token_id
        result = await _maybe_await(
            self._collection.update_one(
                {"_id": token_id, "revokedAt": None}, {"$set": payload}
            )
        )
        return result.modified_count > 0

    async def revoke_by_hash(self, token_hash: str) -> bool:
        now = utc_now()
        result = await _maybe_await(
            self._collection.update_one(
                {"tokenHash": token_hash, "revokedAt": None},
                {"$set": {"revokedAt": now, "updatedAt": now}},
            )
        )
        return result.modified_count > 0

    async def revoke_by_user_id(self, user_id: str) -> int:
        now = utc_now()
        result = await _maybe_await(
            self._collection.update_many(
                {"userId": user_id, "revokedAt": None},
                {"$set": {"revokedAt": now, "updatedAt": now}},
            )
        )
        return int(result.modified_count)
