"""Token encryption helpers (Fernet). Local-dev adapter — never log plaintext tokens."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.integrations.atlassian.errors import (
    ATLASSIAN_NOT_CONFIGURED,
    AtlassianIntegrationError,
)


def _fernet() -> Fernet:
    settings = get_settings()
    raw = (settings.atlassian_token_encryption_key or "").strip()
    if not raw:
        # Deterministic local-dev key derived from client secret (not for production)
        seed = (
            settings.atlassian_oauth_client_secret
            or settings.atlassian_oauth_client_id
            or "qa-copilot-local-dev-atlassian"
        )
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    else:
        # Accept raw Fernet key or any passphrase (hashed to 32 bytes)
        try:
            if len(raw) == 44 and raw.endswith("="):
                key = raw.encode("utf-8")
                Fernet(key)  # validate
            else:
                key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
        except Exception as exc:  # noqa: BLE001
            raise AtlassianIntegrationError(
                ATLASSIAN_NOT_CONFIGURED,
                "Invalid ATLASSIAN_TOKEN_ENCRYPTION_KEY",
                status_code=500,
            ) from exc
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise AtlassianIntegrationError(
            ATLASSIAN_NOT_CONFIGURED,
            "Unable to decrypt Atlassian token — check encryption key",
            status_code=500,
        ) from exc
