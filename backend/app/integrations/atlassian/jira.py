"""Jira Cloud adapter (REST API v3 via Atlassian gateway)."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.atlassian import token_store
from app.integrations.atlassian.adf import adf_to_text
from app.integrations.atlassian.client import get_atlassian_client
from app.integrations.atlassian.field_mapping import load_mapping
from app.integrations.atlassian.jql import build_issue_jql
from app.integrations.atlassian.oauth import require_selected_cloud_id
from app.integrations.atlassian.schemas import (
    JiraFieldInfo,
    JiraIssuePreview,
    JiraIssueSummary,
    JiraProjectSummary,
)


def _site_url() -> str:
    conn = token_store.load_connection() or {}
    return str(conn.get("selected_site_url") or "").rstrip("/")


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("type") == "doc":
        return adf_to_text(value)
    if isinstance(value, dict):
        return str(
            value.get("value") or value.get("name") or value.get("displayName") or ""
        )
    if isinstance(value, list):
        return ", ".join(_field_text(v) for v in value if v is not None)
    return str(value)


class JiraAdapter:
    def __init__(self) -> None:
        self.client = get_atlassian_client()
        self.settings = get_settings()

    def list_projects(
        self,
        *,
        query: str | None = None,
        start_at: int = 0,
        max_results: int | None = None,
    ) -> tuple[list[JiraProjectSummary], int]:
        cloud_id = require_selected_cloud_id()
        max_results = max_results or self.settings.atlassian_default_page_size
        params: dict[str, Any] = {
            "startAt": max(0, start_at),
            "maxResults": min(max_results, 100),
            "orderBy": "name",
        }
        if query:
            params["query"] = query
        resp = self.client.request(
            "GET",
            self.client.jira_url(cloud_id, "/rest/api/3/project/search"),
            product="jira",
            params=params,
        )
        if resp.status_code >= 400:
            return [], 0
        data = resp.json() or {}
        values = data.get("values") or data.get("projects") or []
        total = int(data.get("total") or len(values))
        site = _site_url()
        out: list[JiraProjectSummary] = []
        for p in values:
            key = str(p.get("key") or "")
            avatar = None
            urls = p.get("avatarUrls") or {}
            if isinstance(urls, dict):
                avatar = urls.get("48x48") or urls.get("24x24")
            category = None
            if isinstance(p.get("projectCategory"), dict):
                category = p["projectCategory"].get("name")
            out.append(
                JiraProjectSummary(
                    id=str(p.get("id") or key),
                    key=key,
                    name=str(p.get("name") or key),
                    project_type=p.get("projectTypeKey"),
                    simplified=p.get("simplified"),
                    style=p.get("style"),
                    avatar_url=avatar,
                    category=category,
                    url=f"{site}/browse/{key}" if site and key else None,
                )
            )
        return out, total

    def search_issues(
        self, body: dict[str, Any]
    ) -> tuple[list[JiraIssueSummary], str | None]:
        cloud_id = require_selected_cloud_id()
        jql = build_issue_jql(
            project_key=body.get("project_key"),
            text=body.get("text"),
            issue_types=body.get("issue_types") or [],
            statuses=body.get("statuses") or [],
            priorities=body.get("priorities") or [],
            labels=body.get("labels") or [],
            advanced_jql=body.get("jql"),
        )
        max_results = min(
            int(body.get("max_results") or self.settings.atlassian_default_page_size),
            100,
        )
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": [
                "summary",
                "issuetype",
                "status",
                "priority",
                "labels",
                "components",
                "updated",
                "created",
                "parent",
            ],
        }
        if body.get("next_page_token"):
            payload["nextPageToken"] = body["next_page_token"]
        resp = self.client.request(
            "POST",
            self.client.jira_url(cloud_id, "/rest/api/3/search/jql"),
            product="jira",
            json_body=payload,
        )
        if resp.status_code >= 400:
            # Fallback to classic search for older tenants
            classic = {
                "jql": jql,
                "startAt": 0,
                "maxResults": max_results,
                "fields": payload["fields"],
            }
            resp = self.client.request(
                "POST",
                self.client.jira_url(cloud_id, "/rest/api/3/search"),
                product="jira",
                json_body=classic,
            )
        data = resp.json() or {}
        issues = data.get("issues") or []
        next_token = data.get("nextPageToken")
        site = _site_url()
        out: list[JiraIssueSummary] = []
        for issue in issues:
            fields = issue.get("fields") or {}
            key = str(issue.get("key") or "")
            out.append(
                JiraIssueSummary(
                    id=str(issue.get("id") or key),
                    key=key,
                    summary=str(fields.get("summary") or key),
                    issue_type=(fields.get("issuetype") or {}).get("name"),
                    status=(fields.get("status") or {}).get("name"),
                    priority=(fields.get("priority") or {}).get("name"),
                    labels=list(fields.get("labels") or []),
                    components=[
                        c.get("name")
                        for c in (fields.get("components") or [])
                        if isinstance(c, dict) and c.get("name")
                    ],
                    updated_at=fields.get("updated"),
                    created_at=fields.get("created"),
                    parent_key=(fields.get("parent") or {}).get("key"),
                    url=f"{site}/browse/{key}" if site and key else None,
                )
            )
        return out, next_token

    def list_fields(self) -> list[JiraFieldInfo]:
        cloud_id = require_selected_cloud_id()
        resp = self.client.request(
            "GET",
            self.client.jira_url(cloud_id, "/rest/api/3/field"),
            product="jira",
        )
        if resp.status_code >= 400:
            return []
        out: list[JiraFieldInfo] = []
        for f in resp.json() or []:
            schema = f.get("schema") or {}
            out.append(
                JiraFieldInfo(
                    id=str(f.get("id") or ""),
                    name=str(f.get("name") or f.get("id") or ""),
                    custom=bool(f.get("custom")),
                    schema_type=schema.get("type"),
                )
            )
        return out

    def get_issue_preview(self, issue_key: str) -> JiraIssuePreview:
        cloud_id = require_selected_cloud_id()
        mapping = load_mapping(cloud_id)
        resp = self.client.request(
            "GET",
            self.client.jira_url(cloud_id, f"/rest/api/3/issue/{issue_key}"),
            product="jira",
            params={"expand": "renderedFields"},
        )
        data = resp.json() or {}
        fields = data.get("fields") or {}
        site = _site_url()
        key = str(data.get("key") or issue_key)
        description = _field_text(
            fields.get(mapping.description_field) or fields.get("description")
        )
        ac_parts = [
            _field_text(fields.get(fid))
            for fid in mapping.acceptance_criteria_fields
            if fields.get(fid) is not None
        ]
        extra: dict[str, str] = {}
        for label, ids in (
            ("Business rules", mapping.business_rules_fields),
            ("QA notes", mapping.test_notes_fields),
            ("Risk", mapping.risk_fields),
            ("Environment", mapping.environment_fields),
        ):
            parts = [
                _field_text(fields.get(fid))
                for fid in ids
                if fields.get(fid) is not None
            ]
            if any(parts):
                extra[label] = "\n".join(p for p in parts if p)

        return JiraIssuePreview(
            id=str(data.get("id") or key),
            key=key,
            summary=str(fields.get("summary") or key),
            issue_type=(fields.get("issuetype") or {}).get("name"),
            status=(fields.get("status") or {}).get("name"),
            priority=(fields.get("priority") or {}).get("name"),
            labels=list(fields.get("labels") or []),
            components=[
                c.get("name")
                for c in (fields.get("components") or [])
                if isinstance(c, dict) and c.get("name")
            ],
            updated_at=fields.get("updated"),
            created_at=fields.get("created"),
            parent_key=(fields.get("parent") or {}).get("key"),
            url=f"{site}/browse/{key}" if site and key else None,
            description_text=description,
            acceptance_criteria_text="\n".join(p for p in ac_parts if p),
            extra_fields=extra,
        )

    def normalize_issue(self, issue_key: str) -> tuple[str, JiraIssuePreview]:
        preview = self.get_issue_preview(issue_key)
        parts = [
            f"# {preview.key}: {preview.summary}",
            f"Type: {preview.issue_type or '—'}",
            f"Status: {preview.status or '—'}",
            f"Priority: {preview.priority or '—'}",
        ]
        if preview.labels:
            parts.append("Labels: " + ", ".join(preview.labels))
        if preview.components:
            parts.append("Components: " + ", ".join(preview.components))
        if preview.parent_key:
            parts.append(f"Parent: {preview.parent_key}")
        if preview.description_text:
            parts.append("\n## Description\n" + preview.description_text)
        if preview.acceptance_criteria_text:
            parts.append(
                "\n## Acceptance Criteria\n" + preview.acceptance_criteria_text
            )
        for name, value in preview.extra_fields.items():
            parts.append(f"\n## {name}\n{value}")
        if preview.url:
            parts.append(f"\nSource: {preview.url}")
        return "\n".join(parts).strip(), preview


def get_jira_adapter() -> JiraAdapter:
    return JiraAdapter()
