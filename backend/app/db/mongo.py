"""MongoDB connection lifecycle and collection access helpers."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.core.logging import get_logger

try:
    import mongomock
except ImportError:  # pragma: no cover - runtime safety
    mongomock = None

logger = get_logger(__name__)


@dataclass
class MongoHealth:
    status: str = "not_initialized"
    connected: bool = False
    error: str | None = None


_client: AsyncIOMotorClient | Any | None = None
_database: Any | None = None
_health = MongoHealth()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _build_client() -> AsyncIOMotorClient | Any:
    settings = get_settings()
    uri = settings.mongo_uri.strip()
    if uri.startswith("mongomock://"):
        if mongomock is None:
            raise RuntimeError("mongomock is required for mongomock:// Mongo URI")
        return mongomock.MongoClient()
    return AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=settings.mongo_connect_timeout_ms,
    )


async def _ensure_indexes(db: Any) -> None:
    users = db["users"]
    refresh_tokens = db["refresh_tokens"]
    await _maybe_await(users.create_index("email", unique=True, name="ux_users_email"))
    await _maybe_await(
        users.create_index(
            [("forgotPasswordToken", 1), ("forgotPasswordTokenExpiresAt", 1)],
            name="ix_users_forgot_password_token_lookup",
        )
    )
    await _maybe_await(
        users.create_index(
            [("inviteToken", 1), ("inviteTokenExpiresAt", 1)],
            name="ix_users_invite_token_lookup",
        )
    )
    await _maybe_await(
        refresh_tokens.create_index(
            "tokenHash",
            unique=True,
            name="ux_refresh_tokens_token_hash",
        )
    )
    await _maybe_await(
        refresh_tokens.create_index("userId", name="ix_refresh_tokens_user_id")
    )
    await _maybe_await(
        refresh_tokens.create_index(
            "expiresAt",
            expireAfterSeconds=0,
            name="ix_refresh_tokens_expires_at",
        )
    )


async def init_mongo() -> None:
    """Initialize Mongo client once and pre-create required indexes."""
    global _client, _database, _health
    settings = get_settings()
    if not settings.mongo_enabled:
        _health = MongoHealth(status="disabled", connected=False, error=None)
        _client = None
        _database = None
        return
    if _client is not None and _database is not None:
        return

    try:
        logger.info("mongo_connecting", db_name=settings.mongo_db_name)
        _client = _build_client()
        _database = _client[settings.mongo_db_name]
        if not settings.mongo_uri.strip().startswith("mongomock://"):
            await _client.admin.command("ping")
        await _ensure_indexes(_database)
        _health = MongoHealth(status="connected", connected=True, error=None)
        logger.info(
            "mongo_connected", db_name=settings.mongo_db_name, status=_health.status
        )
    except Exception as exc:  # noqa: BLE001
        _health = MongoHealth(
            status="error",
            connected=False,
            error=str(exc)[:200],
        )
        logger.warning(
            "mongo_connection_failed",
            error=_health.error,
            required=settings.mongo_required,
        )
        _client = None
        _database = None
        if settings.mongo_required:
            raise RuntimeError(
                "MongoDB is required but not reachable",
            ) from exc


async def close_mongo() -> None:
    """Close Mongo client and reset state."""
    global _client, _database, _health
    try:
        if _client is not None and hasattr(_client, "close"):
            await _maybe_await(_client.close())
    except Exception as exc:  # noqa: BLE001
        logger.warning("mongo_close_failed", error=str(exc)[:200])
    finally:
        _client = None
        _database = None
        if _health.status != "disabled":
            _health = MongoHealth(status="closed", connected=False, error=None)
        logger.info("mongo_disconnected", status=_health.status)


def get_database() -> Any:
    if _database is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(init_mongo())
    if _database is None:
        raise RuntimeError("MongoDB is not initialized")
    return _database


def get_users_collection() -> Any:
    return get_database()["users"]


def get_refresh_tokens_collection() -> Any:
    return get_database()["refresh_tokens"]


def mongo_health_signal() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.mongo_enabled,
        "required": settings.mongo_required,
        "status": _health.status,
        "connected": _health.connected,
        "database": settings.mongo_db_name,
        "error": _health.error,
    }
