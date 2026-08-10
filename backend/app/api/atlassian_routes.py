"""Atlassian integration API routes (OAuth + browse + import)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.integrations.atlassian import field_mapping as field_mapping_mod
from app.integrations.atlassian import oauth, source_store
from app.integrations.atlassian.confluence import get_confluence_adapter
from app.integrations.atlassian.errors import AtlassianIntegrationError
from app.integrations.atlassian.import_service import (
    import_sources,
    remove_source,
    sync_source,
)
from app.integrations.atlassian.jira import get_jira_adapter
from app.integrations.atlassian.schemas import (
    AtlassianImportRequest,
    JiraFieldMapping,
    JiraIssueSearchBody,
    SelectSiteBody,
    SyncSelectedBody,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/integrations/atlassian", tags=["atlassian"])


def _http_error(exc: AtlassianIntegrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.to_dict())


@router.get("/status")
def atlassian_status() -> dict[str, Any]:
    return oauth.connection_status().model_dump(mode="json")


@router.get("/connect")
def atlassian_connect(
    qa_project_id: str = Query(...),
    return_view: str = Query("knowledge"),
) -> RedirectResponse:
    try:
        if not get_graph_store().get_project(qa_project_id):
            raise AtlassianIntegrationError(
                "PROJECT_MISMATCH", "QA project not found", status_code=404
            )
        url = oauth.build_authorize_url(
            qa_project_id=qa_project_id, return_view=return_view
        )
        return RedirectResponse(url=url, status_code=302)
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/callback")
def atlassian_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    settings = get_settings()
    front = settings.atlassian_frontend_base_url.rstrip("/")
    try:
        if error:
            oauth.handle_consent_denied(state, error_description or error)
        if not code or not state:
            raise AtlassianIntegrationError(
                "OAUTH_STATE_INVALID", "Missing OAuth code/state"
            )
        payload = oauth.exchange_code(code, state)
        qa_project_id = payload.get("qa_project_id") or ""
        return_view = payload.get("return_view") or "knowledge"
        qs = urlencode(
            {"view": return_view, "atlassian": "connected", "project": qa_project_id}
        )
        return RedirectResponse(url=f"{front}/?{qs}", status_code=302)
    except AtlassianIntegrationError as exc:
        qs = urlencode(
            {"view": "knowledge", "atlassian": "error", "message": exc.message[:180]}
        )
        return RedirectResponse(url=f"{front}/?{qs}", status_code=302)


@router.get("/sites")
def atlassian_sites() -> list[dict[str, Any]]:
    try:
        oauth.assert_configured()
        return [s.model_dump(mode="json") for s in oauth.fetch_accessible_resources()]
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/select-site")
def atlassian_select_site(body: SelectSiteBody) -> dict[str, Any]:
    try:
        site = oauth.select_site(body.cloud_id)
        return site.model_dump(mode="json")
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/disconnect")
def atlassian_disconnect() -> dict[str, str]:
    oauth.disconnect()
    return {"status": "disconnected"}


@router.get("/jira/projects")
def jira_projects(
    query: str | None = None,
    start_at: int = 0,
    max_results: int = 50,
) -> dict[str, Any]:
    try:
        items, total = get_jira_adapter().list_projects(
            query=query, start_at=start_at, max_results=max_results
        )
        return {"items": [i.model_dump(mode="json") for i in items], "total": total}
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/jira/issues/search")
def jira_issue_search(body: JiraIssueSearchBody) -> dict[str, Any]:
    try:
        items, next_token = get_jira_adapter().search_issues(body.model_dump())
        return {
            "items": [i.model_dump(mode="json") for i in items],
            "next_page_token": next_token,
        }
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/jira/issues/{issue_key}/preview")
def jira_issue_preview(issue_key: str) -> dict[str, Any]:
    try:
        return get_jira_adapter().get_issue_preview(issue_key).model_dump(mode="json")
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/jira/fields")
def jira_fields() -> list[dict[str, Any]]:
    try:
        return [f.model_dump(mode="json") for f in get_jira_adapter().list_fields()]
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/jira/field-mapping")
def get_jira_field_mapping() -> dict[str, Any]:
    try:
        cloud_id = oauth.require_selected_cloud_id()
        return field_mapping_mod.load_mapping(cloud_id).model_dump(mode="json")
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.put("/jira/field-mapping")
def put_jira_field_mapping(body: JiraFieldMapping) -> dict[str, Any]:
    try:
        cloud_id = oauth.require_selected_cloud_id()
        body.cloud_id = cloud_id
        return field_mapping_mod.save_mapping(body).model_dump(mode="json")
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/confluence/spaces")
def confluence_spaces(
    query: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        items, next_cursor = get_confluence_adapter().list_spaces(
            query=query, cursor=cursor, limit=limit
        )
        return {
            "items": [i.model_dump(mode="json") for i in items],
            "next_cursor": next_cursor,
        }
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/confluence/spaces/{space_id}/pages")
def confluence_pages(
    space_id: str,
    title: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        items, next_cursor = get_confluence_adapter().list_pages(
            space_id, title=title, cursor=cursor, limit=limit
        )
        return {
            "items": [i.model_dump(mode="json") for i in items],
            "next_cursor": next_cursor,
        }
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/confluence/pages/{page_id}/preview")
def confluence_page_preview(page_id: str) -> dict[str, Any]:
    try:
        return (
            get_confluence_adapter().get_page_preview(page_id).model_dump(mode="json")
        )
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/import")
def atlassian_import(body: AtlassianImportRequest) -> dict[str, Any]:
    try:
        return import_sources(body).model_dump(mode="json")
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.get("/imports")
def list_imports(qa_project_id: str = Query(...)) -> list[dict[str, Any]]:
    if not get_graph_store().get_project(qa_project_id):
        raise HTTPException(404, "Project not found")
    return [s.model_dump(mode="json") for s in source_store.list_sources(qa_project_id)]


@router.post("/imports/{source_id}/sync")
def sync_import(source_id: str, qa_project_id: str = Query(...)) -> dict[str, Any]:
    try:
        return sync_source(source_id, qa_project_id).model_dump(mode="json")
    except AtlassianIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/sync-selected")
def sync_selected(body: SyncSelectedBody) -> dict[str, Any]:
    results = []
    failures = []
    for sid in body.source_ids:
        try:
            results.append(sync_source(sid, body.qa_project_id).model_dump(mode="json"))
        except AtlassianIntegrationError as exc:
            failures.append({"source_id": sid, "error": exc.message, "code": exc.code})
    return {"synced": results, "failures": failures}


@router.delete("/imports/{source_id}")
def delete_import(source_id: str, qa_project_id: str = Query(...)) -> dict[str, Any]:
    ok = remove_source(source_id, qa_project_id)
    if not ok:
        raise HTTPException(404, "Source not found")
    return {"deleted": True, "source_id": source_id}
