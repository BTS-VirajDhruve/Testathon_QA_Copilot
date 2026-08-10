"""Encrypted local-development Atlassian connection token store.

Replaceable with a production DB adapter; tokens never appear in API responses.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.integrations.atlassian.crypto import decrypt_secret, encrypt_secret
from app.models.schemas import new_id, utc_now

_lock = threading.RLock()


def _store_path() -> Path:
    return get_settings().atlassian_data_dir / "connection.json"


def _state_path() -> Path:
    return get_settings().atlassian_data_dir / "oauth_states.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_connection() -> dict[str, Any] | None:
    with _lock:
        data = _read_json(_store_path())
        return data or None


def save_connection(payload: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        payload = {**payload, "updated_at": utc_now().isoformat()}
        if "connection_id" not in payload:
            payload["connection_id"] = new_id("atl")
        if "created_at" not in payload:
            payload["created_at"] = payload["updated_at"]
        _write_json(_store_path(), payload)
        return payload


def delete_connection() -> None:
    with _lock:
        path = _store_path()
        if path.exists():
            path.unlink()


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
        data = _read_json(_state_path())
        data[state] = {**payload, "created_at": utc_now().isoformat()}
        # prune old
        if len(data) > 50:
            items = sorted(data.items(), key=lambda x: x[1].get("created_at") or "")
            data = dict(items[-30:])
        _write_json(_state_path(), data)


def pop_oauth_state(state: str) -> dict[str, Any] | None:
    with _lock:
        data = _read_json(_state_path())
        payload = data.pop(state, None)
        _write_json(_state_path(), data)
        return payload
