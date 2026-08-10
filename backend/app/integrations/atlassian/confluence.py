"""Confluence Cloud adapter (REST API v2 via Atlassian gateway)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.integrations.atlassian import token_store
from app.integrations.atlassian.adf import adf_to_text
from app.integrations.atlassian.client import get_atlassian_client
from app.integrations.atlassian.html_sanitize import html_to_text
from app.integrations.atlassian.oauth import require_selected_cloud_id
from app.integrations.atlassian.schemas import (
    ConfluencePagePreview,
    ConfluencePageSummary,
    ConfluenceSpaceSummary,
)


def _site_url() -> str:
    conn = token_store.load_connection() or {}
    return str(conn.get("selected_site_url") or "").rstrip("/")


def _web_url_for_page(page_id: str, links: dict[str, Any] | None = None) -> str | None:
    if links and isinstance(links.get("webui"), str):
        webui = links["webui"]
        site = _site_url()
        if webui.startswith("http"):
            return webui
        if site:
            return (
                f"{site}/wiki{webui}"
                if not webui.startswith("/wiki")
                else f"{site}{webui}"
            )
    site = _site_url()
    return f"{site}/wiki/pages/{page_id}" if site else None


class ConfluenceAdapter:
    def __init__(self) -> None:
        self.client = get_atlassian_client()
        self.settings = get_settings()

    def list_spaces(
        self,
        *,
        query: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[ConfluenceSpaceSummary], str | None]:
        cloud_id = require_selected_cloud_id()
        limit = min(limit or self.settings.atlassian_default_page_size, 100)
        params: dict[str, Any] = {"limit": limit, "status": "current"}
        if cursor:
            params["cursor"] = cursor
        resp = self.client.request(
            "GET",
            self.client.confluence_url(cloud_id, "/wiki/api/v2/spaces"),
            product="confluence",
            params=params,
        )
        data = resp.json() or {}
        results = data.get("results") or []
        next_cursor = None
        links = data.get("_links") or {}
        if isinstance(links.get("next"), str):
            parsed = urlparse(links["next"])
            from urllib.parse import parse_qs

            qs = parse_qs(parsed.query)
            next_cursor = (qs.get("cursor") or [None])[0]
        out: list[ConfluenceSpaceSummary] = []
        q = (query or "").strip().lower()
        for sp in results:
            name = str(sp.get("name") or "")
            key = str(sp.get("key") or "")
            if q and q not in name.lower() and q not in key.lower():
                continue
            desc = None
            description = sp.get("description") or {}
            if isinstance(description, dict):
                plain = description.get("plain") or {}
                if isinstance(plain, dict):
                    desc = plain.get("value")
            out.append(
                ConfluenceSpaceSummary(
                    id=str(sp.get("id") or key),
                    key=key,
                    name=name or key,
                    type=sp.get("type"),
                    status=sp.get("status"),
                    description=desc,
                    web_url=_web_url_for_page(
                        str(sp.get("id") or ""), sp.get("_links")
                    ),
                )
            )
        return out, next_cursor

    def list_pages(
        self,
        space_id: str,
        *,
        title: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[ConfluencePageSummary], str | None]:
        cloud_id = require_selected_cloud_id()
        limit = min(limit or self.settings.atlassian_default_page_size, 100)
        params: dict[str, Any] = {"limit": limit, "status": "current"}
        if cursor:
            params["cursor"] = cursor
        if title:
            params["title"] = title
        resp = self.client.request(
            "GET",
            self.client.confluence_url(
                cloud_id, f"/wiki/api/v2/spaces/{space_id}/pages"
            ),
            product="confluence",
            params=params,
        )
        data = resp.json() or {}
        results = data.get("results") or []
        next_cursor = None
        links = data.get("_links") or {}
        if isinstance(links.get("next"), str):
            from urllib.parse import parse_qs
            from urllib.parse import urlparse as _urlparse

            qs = parse_qs(_urlparse(links["next"]).query)
            next_cursor = (qs.get("cursor") or [None])[0]
        out: list[ConfluencePageSummary] = []
        for page in results:
            pid = str(page.get("id") or "")
            version = page.get("version") or {}
            out.append(
                ConfluencePageSummary(
                    id=pid,
                    space_id=str(page.get("spaceId") or space_id),
                    parent_id=str(page.get("parentId"))
                    if page.get("parentId")
                    else None,
                    title=str(page.get("title") or pid),
                    status=page.get("status"),
                    created_at=page.get("createdAt"),
                    updated_at=(
                        version.get("createdAt") if isinstance(version, dict) else None
                    )
                    or page.get("createdAt"),
                    version_number=version.get("number")
                    if isinstance(version, dict)
                    else None,
                    web_url=_web_url_for_page(pid, page.get("_links")),
                    has_children=bool(page.get("childPosition") is not None),
                )
            )
        return out, next_cursor

    def get_page_preview(self, page_id: str) -> ConfluencePagePreview:
        cloud_id = require_selected_cloud_id()
        resp = self.client.request(
            "GET",
            self.client.confluence_url(cloud_id, f"/wiki/api/v2/pages/{page_id}"),
            product="confluence",
            params={"body-format": "storage"},
        )
        data = resp.json() or {}
        body = data.get("body") or {}
        storage = body.get("storage") or {}
        atlas_doc = body.get("atlas_doc_format") or body.get("atlas_doc") or {}
        body_text = ""
        if isinstance(storage, dict) and storage.get("value"):
            body_text = html_to_text(str(storage.get("value") or ""))
        elif isinstance(atlas_doc, dict) and atlas_doc.get("value"):
            import json

            try:
                adf = (
                    json.loads(atlas_doc["value"])
                    if isinstance(atlas_doc["value"], str)
                    else atlas_doc["value"]
                )
                body_text = adf_to_text(adf)
            except Exception:  # noqa: BLE001
                body_text = str(atlas_doc.get("value") or "")
        version = data.get("version") or {}
        return ConfluencePagePreview(
            id=str(data.get("id") or page_id),
            space_id=str(data.get("spaceId")) if data.get("spaceId") else None,
            parent_id=str(data.get("parentId")) if data.get("parentId") else None,
            title=str(data.get("title") or page_id),
            status=data.get("status"),
            created_at=data.get("createdAt"),
            updated_at=(
                version.get("createdAt") if isinstance(version, dict) else None
            ),
            version_number=version.get("number") if isinstance(version, dict) else None,
            web_url=_web_url_for_page(
                str(data.get("id") or page_id), data.get("_links")
            ),
            body_text=body_text,
            breadcrumb=[],
            labels=[],
        )

    def normalize_page(self, page_id: str) -> tuple[str, ConfluencePagePreview]:
        preview = self.get_page_preview(page_id)
        parts = [f"# {preview.title}"]
        if preview.breadcrumb:
            parts.append("Path: " + " > ".join(preview.breadcrumb))
        if preview.labels:
            parts.append("Labels: " + ", ".join(preview.labels))
        if preview.body_text:
            parts.append("\n" + preview.body_text)
        if preview.web_url:
            parts.append(f"\nSource: {preview.web_url}")
        return "\n".join(parts).strip(), preview


def get_confluence_adapter() -> ConfluenceAdapter:
    return ConfluenceAdapter()
