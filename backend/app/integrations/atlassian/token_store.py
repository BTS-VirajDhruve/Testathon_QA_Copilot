"""Encrypted Atlassian connection token store backed by MongoDB."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from app.db.mongo import (
    get_atlassian_connections_collection_sync,
    get_atlassian_oauth_states_collection_sync,
)
from app.integrations.atlassian.crypto import decrypt_secret, encrypt_secret
from app.models.schemas import new_id, utc_now

_lock = threading.RLock()


def _connection_scope(payload: dict[str, Any]) -> str:
    return str(payload.get("user_scope_id") or "local")


def load_connection() -> dict[str, Any] | None:
    with _lock:
        row = get_atlassian_connections_collection_sync().find_one(
            {"scope_key": "local"}
        )
        return dict(row.get("connection") or {}) if row else None


def save_connection(payload: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        payload = {**payload, "updated_at": utc_now().isoformat()}
        if "connection_id" not in payload:
            payload["connection_id"] = new_id("atl")
        if "created_at" not in payload:
            payload["created_at"] = payload["updated_at"]
        scope_key = _connection_scope(payload)
        get_atlassian_connections_collection_sync().replace_one(
            {"scope_key": scope_key},
            {
                "_id": scope_key,
                "scope_key": scope_key,
                "updated_at": payload["updated_at"],
                "connection": payload,
            },
            upsert=True,
        )
        return payload


def delete_connection() -> None:
    with _lock:
        get_atlassian_connections_collection_sync().delete_one({"scope_key": "local"})


def set_tokens(
    *,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    conn = load_connection() or {
        "user_scope_id": "local",
        "status": "connected",
    }
    conn["encrypted_access_token"] = encrypt_secret(access_token)
    if refresh_token:
        conn["encrypted_refresh_token"] = encrypt_secret(refresh_token)
    if expires_in is not None:
        expiry = datetime.now(UTC).timestamp() + max(0, int(expires_in) - 60)
        conn["token_expiry"] = datetime.fromtimestamp(expiry, tz=UTC).isoformat()
    if scopes is not None:
        conn["granted_scopes"] = scopes
    conn["status"] = "connected"
    return save_connection(conn)


def get_access_token() -> str | None:
    conn = load_connection()
    if not conn:
        return None
    enc = conn.get("encrypted_access_token") or ""
    if not enc:
        return None
    return decrypt_secret(enc)


def get_refresh_token() -> str | None:
    conn = load_connection()
    if not conn:
        return None
    enc = conn.get("encrypted_refresh_token") or ""
    if not enc:
        return None
    return decrypt_secret(enc)


def token_expired() -> bool:
    conn = load_connection()
    if not conn or not conn.get("token_expiry"):
        return False
    try:
        expiry = datetime.fromisoformat(
            str(conn["token_expiry"]).replace("Z", "+00:00")
        )
        return datetime.now(UTC) >= expiry
    except Exception:  # noqa: BLE001
        return False


def save_oauth_state(state: str, payload: dict[str, Any]) -> None:
    with _lock:
        created_at = utc_now().isoformat()
        get_atlassian_oauth_states_collection_sync().replace_one(
            {"state": state},
            {
                "_id": state,
                "state": state,
                "created_at": created_at,
                "payload": {**payload, "created_at": created_at},
            },
            upsert=True,
        )


def pop_oauth_state(state: str) -> dict[str, Any] | None:
    with _lock:
        row = get_atlassian_oauth_states_collection_sync().find_one_and_delete(
            {"state": state}
        )
        return dict(row.get("payload") or {}) if row else None
