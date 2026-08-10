"""Shared Atlassian HTTP client with refresh, retries, and rate-limit handling."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.atlassian import oauth, token_store
from app.integrations.atlassian.errors import (
    CONFLUENCE_PERMISSION_DENIED,
    JIRA_PERMISSION_DENIED,
    RATE_LIMITED,
    RESOURCE_NOT_FOUND,
    AtlassianIntegrationError,
)

logger = get_logger(__name__)


class AtlassianHttpClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _access_token(self) -> str:
        if token_store.token_expired():
            return oauth.refresh_access_token()
        token = token_store.get_access_token()
        if not token:
            return oauth.refresh_access_token()
        return token

    def request(
        self,
        method: str,
        url: str,
        *,
        product: str = "jira",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        retries = max(0, int(self.settings.atlassian_max_retries))
        refreshed = False
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            token = self._access_token()
            hdrs = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                **(headers or {}),
            }
            try:
                with httpx.Client(
                    timeout=self.settings.atlassian_request_timeout_seconds
                ) as client:
                    resp = client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=hdrs,
                    )
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(min(2**attempt, 8))
                continue

            if resp.status_code == 401 and not refreshed:
                oauth.refresh_access_token()
                refreshed = True
                continue
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else min(2**attempt, 16)
                )
                if attempt < retries:
                    time.sleep(delay)
                    continue
                raise AtlassianIntegrationError(
                    RATE_LIMITED,
                    "Atlassian rate limit exceeded — retry later",
                    status_code=429,
                )
            if resp.status_code in {403}:
                code = (
                    JIRA_PERMISSION_DENIED
                    if product == "jira"
                    else CONFLUENCE_PERMISSION_DENIED
                )
                raise AtlassianIntegrationError(
                    code,
                    f"Permission denied for {product} resource",
                    status_code=403,
                )
            if resp.status_code == 404:
                raise AtlassianIntegrationError(
                    RESOURCE_NOT_FOUND,
                    "Atlassian resource not found",
                    status_code=404,
                )
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            return resp

        raise AtlassianIntegrationError(
            RATE_LIMITED if last_exc else "ATLASSIAN_REQUEST_FAILED",
            "Atlassian request failed after retries",
            status_code=502,
        )

    def jira_url(self, cloud_id: str, path: str) -> str:
        return f"https://api.atlassian.com/ex/jira/{cloud_id}{path}"

    def confluence_url(self, cloud_id: str, path: str) -> str:
        return f"https://api.atlassian.com/ex/confluence/{cloud_id}{path}"


def get_atlassian_client() -> AtlassianHttpClient:
    return AtlassianHttpClient()
