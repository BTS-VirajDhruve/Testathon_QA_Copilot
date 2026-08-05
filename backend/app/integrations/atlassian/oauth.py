"""Atlassian OAuth 2.0 (3LO) helpers."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.atlassian import token_store
from app.integrations.atlassian.errors import (
    ATLASSIAN_NOT_CONFIGURED,
    INTEGRATION_DISABLED,
    OAUTH_CONSENT_DENIED,
    OAUTH_STATE_INVALID,
    TOKEN_REFRESH_FAILED,
    AtlassianIntegrationError,
)
from app.integrations.atlassian.schemas import AtlassianConnectionStatus, AtlassianSite

logger = get_logger(__name__)

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"


def assert_enabled() -> None:
    settings = get_settings()
    if not settings.atlassian_integration_enabled:
        raise AtlassianIntegrationError(
            INTEGRATION_DISABLED,
            "Atlassian integration is disabled",
            status_code=503,
        )


def assert_configured() -> None:
    assert_enabled()
    settings = get_settings()
    if not settings.atlassian_oauth_configured:
        raise AtlassianIntegrationError(
            ATLASSIAN_NOT_CONFIGURED,
            "Atlassian OAuth client id/secret are not configured",
            status_code=503,
        )


def connection_status() -> AtlassianConnectionStatus:
    settings = get_settings()
    if not settings.atlassian_integration_enabled:
        return AtlassianConnectionStatus(
            enabled=False,
            configured=False,
            connected=False,
            status="disconnected",
            error="Integration disabled",
        )
    if not settings.atlassian_oauth_configured:
        return AtlassianConnectionStatus(
            enabled=True,
            configured=False,
            connected=False,
            status="configuration_missing",
            error="OAuth client credentials missing",
        )
    conn = token_store.load_connection()
    if not conn or not conn.get("encrypted_access_token"):
        return AtlassianConnectionStatus(
            enabled=True,
            configured=True,
            connected=False,
            status="disconnected",
        )
    status = conn.get("status") or "connected"
    if token_store.token_expired() and not conn.get("encrypted_refresh_token"):
        status = "expired"
    return AtlassianConnectionStatus(
        enabled=True,
        configured=True,
        connected=status == "connected",
        status=status,  # type: ignore[arg-type]
        selected_cloud_id=conn.get("selected_cloud_id"),
        selected_site_name=conn.get("selected_site_name"),
        selected_site_url=conn.get("selected_site_url"),
        granted_scopes=list(conn.get("granted_scopes") or []),
        products=list(conn.get("products") or []),
        token_expiry=conn.get("token_expiry"),
        error=conn.get("error"),
    )


def build_authorize_url(*, qa_project_id: str, return_view: str = "knowledge") -> str:
    assert_configured()
    settings = get_settings()
    state = secrets.token_urlsafe(32)
    token_store.save_oauth_state(
        state,
        {"qa_project_id": qa_project_id, "return_view": return_view},
    )
    params = {
        "audience": "api.atlassian.com",
        "client_id": settings.atlassian_oauth_client_id,
        "scope": " ".join(settings.atlassian_scope_list),
        "redirect_uri": settings.atlassian_oauth_redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str, state: str) -> dict[str, Any]:
    assert_configured()
    payload = token_store.pop_oauth_state(state)
    if not payload:
        raise AtlassianIntegrationError(OAUTH_STATE_INVALID, "Invalid or expired OAuth state")
    settings = get_settings()
    with httpx.Client(timeout=settings.atlassian_request_timeout_seconds) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.atlassian_oauth_client_id,
                "client_secret": settings.atlassian_oauth_client_secret,
                "code": code,
                "redirect_uri": settings.atlassian_oauth_redirect_uri,
            },
        )
    if resp.status_code >= 400:
        logger.warning("atlassian_token_exchange_failed", status=resp.status_code)
        raise AtlassianIntegrationError(
            TOKEN_REFRESH_FAILED,
            "Failed to exchange authorization code",
            status_code=502,
        )
    data = resp.json()
    scopes = str(data.get("scope") or "").split()
    token_store.set_tokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_in=data.get("expires_in"),
        scopes=scopes,
    )
    sites = fetch_accessible_resources()
    products: list[str] = []
    for site in sites:
        products.extend(site.products)
    conn = token_store.load_connection() or {}
    conn["products"] = sorted(set(products))
    if sites and not conn.get("selected_cloud_id"):
        conn["selected_cloud_id"] = sites[0].cloud_id
        conn["selected_site_name"] = sites[0].name
        conn["selected_site_url"] = sites[0].url
    token_store.save_connection(conn)
    return payload


def handle_consent_denied(state: str | None, error: str | None) -> dict[str, Any]:
    payload = token_store.pop_oauth_state(state) if state else {}
    raise AtlassianIntegrationError(
        OAUTH_CONSENT_DENIED,
        error or "Atlassian consent was denied",
        status_code=400,
        details={"return": payload},
    )


def refresh_access_token() -> str:
    assert_configured()
    refresh = token_store.get_refresh_token()
    if not refresh:
        raise AtlassianIntegrationError(
            TOKEN_REFRESH_FAILED,
            "No refresh token available — reconnect Atlassian",
            status_code=401,
        )
    settings = get_settings()
    with httpx.Client(timeout=settings.atlassian_request_timeout_seconds) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.atlassian_oauth_client_id,
                "client_secret": settings.atlassian_oauth_client_secret,
                "refresh_token": refresh,
            },
        )
    if resp.status_code >= 400:
        conn = token_store.load_connection() or {}
        conn["status"] = "revoked"
        conn["error"] = "Token refresh failed"
        token_store.save_connection(conn)
        raise AtlassianIntegrationError(
            TOKEN_REFRESH_FAILED,
            "Atlassian token refresh failed — reconnect",
            status_code=401,
        )
    data = resp.json()
    token_store.set_tokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or refresh,
        expires_in=data.get("expires_in"),
        scopes=str(data.get("scope") or "").split() or None,
    )
    return data["access_token"]


def fetch_accessible_resources() -> list[AtlassianSite]:
    token = token_store.get_access_token()
    if not token:
        return []
    settings = get_settings()
    with httpx.Client(timeout=settings.atlassian_request_timeout_seconds) as client:
        resp = client.get(
            RESOURCES_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    if resp.status_code == 401:
        token = refresh_access_token()
        with httpx.Client(timeout=settings.atlassian_request_timeout_seconds) as client:
            resp = client.get(
                RESOURCES_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
    if resp.status_code >= 400:
        logger.warning("accessible_resources_failed", status=resp.status_code)
        return []
    sites: list[AtlassianSite] = []
    for item in resp.json() or []:
        sites.append(
            AtlassianSite(
                cloud_id=str(item.get("id") or ""),
                name=str(item.get("name") or item.get("url") or "Atlassian site"),
                url=str(item.get("url") or ""),
                avatar_url=(item.get("avatarUrl") if isinstance(item.get("avatarUrl"), str) else None),
                scopes=list(item.get("scopes") or []),
                products=list(item.get("scopes") or []),
            )
        )
    return [s for s in sites if s.cloud_id]


def select_site(cloud_id: str) -> AtlassianSite:
    sites = fetch_accessible_resources()
    match = next((s for s in sites if s.cloud_id == cloud_id), None)
    if not match:
        from app.integrations.atlassian.errors import SITE_NOT_ACCESSIBLE

        raise AtlassianIntegrationError(
            SITE_NOT_ACCESSIBLE,
            "Selected Atlassian site is not accessible",
            status_code=403,
        )
    conn = token_store.load_connection() or {}
    conn["selected_cloud_id"] = match.cloud_id
    conn["selected_site_name"] = match.name
    conn["selected_site_url"] = match.url
    conn["products"] = match.products
    token_store.save_connection(conn)
    return match


def disconnect() -> None:
    token_store.delete_connection()


def require_selected_cloud_id() -> str:
    conn = token_store.load_connection()
    if not conn or not conn.get("encrypted_access_token"):
        from app.integrations.atlassian.errors import ATLASSIAN_NOT_CONNECTED

        raise AtlassianIntegrationError(
            ATLASSIAN_NOT_CONNECTED,
            "Connect Atlassian before browsing sources",
            status_code=401,
        )
    cloud_id = conn.get("selected_cloud_id")
    if not cloud_id:
        from app.integrations.atlassian.errors import SITE_NOT_SELECTED

        raise AtlassianIntegrationError(
            SITE_NOT_SELECTED,
            "Select an Atlassian site first",
            status_code=400,
        )
    return str(cloud_id)
