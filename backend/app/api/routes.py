"""FastAPI route modules."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.agents.bdd import render_feature_file, safe_feature_filename
from app.agents.bdd_export import (
    BDDExportError,
    BDDExportRequest,
    build_export_package,
    build_export_preview,
)
from app.agents.orchestrator import get_orchestrator
from app.api.auth_dependencies import require_admin_user
from app.core.config import get_settings
from app.db.mongo import mongo_health_signal
from app.graph.ingestion import get_flow_ingester
from app.graph.store import get_graph_store, get_neo4j_store
from app.graph.traversal import get_coverage_engine, get_traversal
from app.models.enums import Priority
from app.models.schemas import (
    AutomationCapabilityProfile,
    AutomationReviewOverrideRequest,
    BDDScenario,
    NestedFlowImport,
    QACopilotRequest,
    QACopilotResponse,
    SystemFlowGraph,
    utc_now,
)
from app.rag.document_ingestion import get_document_ingester
from app.rag.vector_store import get_vector_store
from app.services.openai_service import get_openai_service

router = APIRouter()


class ProjectCreateBody(BaseModel):
    name: str
    description: str = ""
    root_feature: str | None = None


class NLGraphBody(BaseModel):
    text: str


class NodeCreateBody(BaseModel):
    name: str
    type: str | None = None
    description: str = ""
    parent_id: str | None = None
    relationship: str | None = None
    is_failure_path: bool = False
    is_external_dependency: bool = False
    is_critical: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    openai = get_openai_service()
    vectors = get_vector_store()
    neo4j = get_neo4j_store()
    graph_mode = (
        "neo4j+mongo"
        if settings.neo4j_enabled and getattr(neo4j, "_driver", None) is not None
        else "mongo"
    )
    store = get_graph_store()
    atl_count = sum(
        1
        for s in getattr(store, "external_knowledge_sources", {}).values()
        if s.get("provider") == "atlassian"
    )
    atl_status = "disconnected"
    atl_site = None
    try:
        from app.integrations.atlassian import oauth as atl_oauth

        st = atl_oauth.connection_status()
        atl_status = st.status
        atl_site = st.selected_site_name
    except Exception:  # noqa: BLE001
        pass
    mongo = mongo_health_signal()
    return {
        "status": "ok",
        "openai": settings.has_openai,
        "openai_configured": openai.configured,
        "openai_client_ready": openai.available,
        "openai_model": settings.openai_model if settings.has_openai else None,
        "neo4j_enabled": settings.neo4j_enabled,
        "demo_fallback": settings.enable_demo_fallback,
        "vector_store_mode": vectors.backend_mode,
        "graph_store_mode": graph_mode,
        "projects": len(store.list_projects()),
        "data_dir": settings.data_dir,
        "graph_store_path": None,
        "api_base_hint": "Use NEXT_PUBLIC_API_URL on the frontend",
        "atlassian_integration_enabled": settings.atlassian_integration_enabled,
        "atlassian_oauth_configured": settings.atlassian_oauth_configured,
        "atlassian_connection_status": atl_status,
        "atlassian_selected_site": atl_site,
        "imported_atlassian_source_count": atl_count,
        "mongo_enabled": mongo["enabled"],
        "mongo_connected": mongo["connected"],
        "mongo_status": mongo["status"],
        "mongo_database": mongo["database"],
    }


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    return get_graph_store().list_projects()


@router.post("/projects")
def create_project(body: ProjectCreateBody) -> dict[str, Any]:
    return get_graph_store().create_project(
        body.name, body.description, body.root_feature
    )


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = get_graph_store().get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    graph = get_graph_store().get_project_graph(project_id)
    return {**project, "node_count": len(graph.nodes), "edge_count": len(graph.edges)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    """Permanently delete a project and every resource scoped to it."""
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")

    vectors_removed = 0
    try:
        vectors_removed = get_vector_store().delete_by_project(project_id)
    except Exception as exc:  # noqa: BLE001
        # Still delete graph/store data; surface vector failure in counts as 0
        from app.core.logging import get_logger

        get_logger(__name__).warning(
            "vector_delete_failed", project_id=project_id, error=str(exc)
        )

    counts = store.delete_project(project_id)
    if counts is None:
        raise HTTPException(404, "Project not found")

    deleted_resources = {
        "nodes": counts.get("nodes", 0),
        "edges": counts.get("edges", 0),
        "documents": counts.get("documents", 0),
        "vectors": vectors_removed,
        "tests": counts.get("tests", 0),
        "bugs": counts.get("bugs", 0),
        "coverage": counts.get("coverage", 0),
    }
    return {
        "success": True,
        "deleted_project_id": project_id,
        "deleted_resources": deleted_resources,
    }


@router.get("/projects/{project_id}/flow")
def get_flow(project_id: str) -> SystemFlowGraph:
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")
    return get_graph_store().get_project_graph(project_id)


@router.put("/projects/{project_id}/flow")
def save_flow(project_id: str, graph: SystemFlowGraph) -> SystemFlowGraph:
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")
    graph.project_id = project_id
    return get_flow_ingester().persist(graph)


@router.post("/projects/{project_id}/flow/import")
def import_flow(project_id: str, body: NestedFlowImport) -> SystemFlowGraph:
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")
    return get_flow_ingester().from_nested_import(project_id, body)


@router.post("/projects/{project_id}/flow/from-text")
def flow_from_text(project_id: str, body: NLGraphBody) -> SystemFlowGraph:
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")
    return get_flow_ingester().from_natural_language(project_id, body.text)


@router.post("/projects/{project_id}/flow/from-text/stream")
def flow_from_text_stream(project_id: str, body: NLGraphBody) -> StreamingResponse:
    """SSE progress stream for NL → graph (deterministic builder + optional classify)."""
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")

    def event_stream() -> Iterator[str]:
        from queue import Empty, Queue
        from threading import Thread

        q: Queue[tuple[str, dict[str, Any]] | None] = Queue()

        def on_progress(stage: str, message: str, meta: dict[str, Any]) -> None:
            q.put(
                ("progress", {"stage": stage, "message": message, "meta": meta or {}})
            )

        def worker() -> None:
            try:
                graph = get_flow_ingester().from_natural_language(
                    project_id,
                    body.text,
                    on_progress=on_progress,
                )
                q.put(("complete", graph.model_dump(mode="json")))
            except Exception as exc:  # noqa: BLE001
                q.put(("error", {"message": str(exc), "stage": "error"}))
            finally:
                q.put(None)

        Thread(target=worker, daemon=True).start()
        while True:
            try:
                item = q.get(timeout=120)
            except Empty:
                yield f"event: error\ndata: {json.dumps({'message': 'Timed out', 'stage': 'error'})}\n\n"
                break
            if item is None:
                break
            event_name, payload = item
            yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{project_id}/flow/export")
def export_flow(project_id: str) -> dict[str, Any]:
    graph = get_graph_store().get_project_graph(project_id)
    return graph.model_dump(mode="json")


@router.get("/projects/{project_id}/paths")
def discover_paths(project_id: str, root: str | None = None) -> dict[str, Any]:
    traversal = get_traversal()
    node = traversal.resolve_root(project_id, root)
    if not node:
        raise HTTPException(404, "Root feature not found")
    paths = traversal.discover_paths(project_id, node.id)
    return {
        "root": node.name,
        "path_count": len(paths),
        "paths": [p.model_dump(mode="json") for p in paths],
    }


@router.get("/projects/{project_id}/nodes/{node_id}/insight")
def node_insight(project_id: str, node_id: str) -> dict[str, Any]:
    insight = get_traversal().node_insight(project_id, node_id)
    if not insight:
        raise HTTPException(404, "Node not found")
    return insight.model_dump(mode="json")


@router.get("/projects/{project_id}/coverage")
def coverage(project_id: str, root: str | None = None) -> dict[str, Any]:
    return get_coverage_engine().analyze(project_id, root).model_dump(mode="json")


@router.get("/projects/{project_id}/impact")
def impact(project_id: str, node: str) -> dict[str, Any]:
    return get_traversal().impact_analysis(project_id, node).model_dump(mode="json")


@router.post("/projects/{project_id}/documents/upload")
async def upload_document(
    project_id: str, file: UploadFile = File(...)
) -> dict[str, Any]:
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")
    raw = await file.read()
    record = get_document_ingester().ingest_bytes(
        project_id,
        file.filename or "upload.txt",
        raw,
        content_type=file.content_type or "",
    )
    # Index vectors
    chunks = [
        c
        for c in get_document_ingester().get_chunks(project_id)
        if c.document_id == record.id
    ]
    indexed = get_vector_store().upsert_chunks(chunks)
    from app.graph.extraction import get_entity_extractor

    extracted = get_entity_extractor().extract_from_text(
        project_id,
        record.text,
        source_reference=record.filename,
    )
    return {
        "document": record.model_dump(mode="json"),
        "indexed_chunks": indexed,
        "extracted_entities": len(extracted.get("entities") or []),
    }


@router.post("/projects/{project_id}/documents/text")
def ingest_text_document(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not get_graph_store().get_project(project_id):
        raise HTTPException(404, "Project not found")
    filename = body.get("filename") or "notes.txt"
    text = body.get("text") or ""
    record = get_document_ingester().ingest_text(project_id, filename, text)
    chunks = [
        c
        for c in get_document_ingester().get_chunks(project_id)
        if c.document_id == record.id
    ]
    indexed = get_vector_store().upsert_chunks(chunks)
    from app.graph.extraction import get_entity_extractor

    extracted = get_entity_extractor().extract_from_text(
        project_id,
        text,
        source_reference=filename,
    )
    return {
        "document": record.model_dump(mode="json"),
        "indexed_chunks": indexed,
        "extracted_entities": len(extracted.get("entities") or []),
    }


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: str) -> list[dict[str, Any]]:
    docs = get_document_ingester().list_documents(project_id)
    return [
        {
            "id": d["id"],
            "filename": d["filename"],
            "chunk_count": len(d.get("chunk_ids") or d.get("chunks") or []),
            "created_at": d.get("created_at"),
        }
        for d in docs
    ]


@router.get("/projects/{project_id}/search")
def vector_search(project_id: str, q: str, top_k: int = 8) -> list[dict[str, Any]]:
    return get_vector_store().search(project_id, q, top_k=top_k)


@router.get("/projects/{project_id}/tests")
def list_tests(project_id: str) -> list[dict[str, Any]]:
    store = get_graph_store()
    return [
        tc for tc in store.test_cases.values() if tc.get("project_id") == project_id
    ]


@router.post("/projects/{project_id}/tests")
def create_manual_tests(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Create one Feature story with one or more manual scenarios."""
    from app.agents.manual_tests import (
        ManualFeatureCreateRequest,
        create_manual_feature_tests,
    )

    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    try:
        req = ManualFeatureCreateRequest.model_validate(body)
        return create_manual_feature_tests(project_id, req, store)
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "MANUAL_TEST_INVALID", "message": str(exc)}
        ) from exc


@router.put("/projects/{project_id}/tests/{test_case_id}")
def update_manual_test(
    project_id: str, test_case_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    from app.agents.manual_tests import (
        ManualScenarioInput,
        ManualTestUpdateRequest,
        scenario_to_test_case,
    )
    from app.agents.taxonomy import build_user_story

    store = get_graph_store()
    existing = store.get_test_case(project_id, test_case_id)
    if not existing:
        raise HTTPException(404, "Test case not found")
    req = ManualTestUpdateRequest.model_validate(body)
    is_manual = (
        existing.get("human_edited") or existing.get("generation_method") == "manual"
    )
    if not is_manual and not req.force_overwrite_generated:
        raise HTTPException(
            409,
            detail={
                "code": "REFUSE_OVERWRITE_GENERATED",
                "message": "Generated tests are not overwritten without force_overwrite_generated.",
            },
        )
    sc = req.scenario or ManualScenarioInput(
        scenario_id=test_case_id,
        name=req.title or existing.get("title") or "Untitled",
        standard_steps=list(existing.get("steps") or []),
        preconditions=list(existing.get("preconditions") or []),
        expected_results=[existing.get("expected_result") or "Outcome confirmed"],
        graph_path=list(existing.get("graph_path") or []),
    )
    sc.scenario_id = test_case_id
    feature_name = req.feature_name or (existing.get("graph_path") or ["Feature"])[0]
    story = build_user_story(
        feature_name,
        actor=req.as_a,
        goal=req.i_want,
        business_value=req.so_that,
    )
    try:
        _, payload = scenario_to_test_case(
            sc,
            project_id=project_id,
            feature_name=feature_name,
            feature_reference=req.feature_reference,
            user_story=story,
            default_priority=Priority.MEDIUM,
        )
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "MANUAL_TEST_INVALID", "message": str(exc)}
        ) from exc
    return store.upsert_test_case(project_id, payload)


@router.delete("/projects/{project_id}/tests/{test_case_id}")
def delete_manual_test(
    project_id: str, test_case_id: str, force: bool = False
) -> dict[str, Any]:
    store = get_graph_store()
    existing = store.get_test_case(project_id, test_case_id)
    if not existing:
        raise HTTPException(404, "Test case not found")
    is_manual = (
        existing.get("human_edited") or existing.get("generation_method") == "manual"
    )
    if not is_manual and not force:
        raise HTTPException(
            409,
            detail={
                "code": "REFUSE_DELETE_GENERATED",
                "message": "Only manual tests can be deleted unless force=true.",
            },
        )
    ok = store.delete_test_case(project_id, test_case_id)
    return {"deleted": ok, "test_case_id": test_case_id}


@router.get("/projects/{project_id}/tests/export.feature")
def export_bdd_feature(
    project_id: str, feature: str | None = None
) -> PlainTextResponse:
    store = get_graph_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    scenarios: list[BDDScenario] = []
    analysis = store.get_latest_analysis(project_id)
    if (
        analysis
        and isinstance(analysis.get("bdd_scenarios"), list)
        and analysis["bdd_scenarios"]
    ):
        for row in analysis["bdd_scenarios"]:
            try:
                scenarios.append(BDDScenario.model_validate(row))
            except Exception:  # noqa: BLE001
                continue
    if not scenarios:
        for tc in store.test_cases.values():
            if tc.get("project_id") != project_id:
                continue
            raw = tc.get("bdd_scenario")
            if not raw:
                continue
            try:
                scenarios.append(BDDScenario.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue
    if not scenarios:
        raise HTTPException(
            404, "No BDD scenarios available to export for this project"
        )

    feature_name = (
        feature or scenarios[0].feature or project.get("name") or "Generated Feature"
    )
    body = render_feature_file(scenarios, feature_name=feature_name)
    filename = safe_feature_filename(feature_name, project.get("name"))
    return PlainTextResponse(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _bdd_export_http_error(exc: BDDExportError) -> HTTPException:
    status = 400
    if exc.code in {"ANALYSIS_NOT_FOUND"}:
        status = 404
    elif exc.code in {"PROJECT_MISMATCH"}:
        status = 409
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": exc.message, "details": exc.details},
    )


@router.post("/projects/{project_id}/analyses/latest/exports/bdd/preview")
def preview_bdd_export(
    project_id: str, body: BDDExportRequest | None = None
) -> dict[str, Any]:
    """Preview Cucumber-compliant BDD export for the latest analysis."""
    try:
        preview = build_export_preview(project_id, body or BDDExportRequest())
    except BDDExportError as exc:
        raise _bdd_export_http_error(exc) from exc
    return preview.model_dump(mode="json")


@router.post("/projects/{project_id}/analyses/latest/exports/bdd")
def export_bdd_from_analysis(
    project_id: str, body: BDDExportRequest | None = None
) -> Response:
    """Export all final generated tests as CSV (default) or .feature/ZIP from the latest analysis."""
    try:
        package = build_export_package(project_id, body or BDDExportRequest())
    except BDDExportError as exc:
        raise _bdd_export_http_error(exc) from exc

    headers = {
        "Content-Disposition": f'attachment; filename="{package.filename}"',
        "X-QA-Exported-Scenarios": str(package.preview.scenario_count),
        "X-QA-Exported-Files": str(package.preview.file_count),
        "X-QA-Analysis-Id": package.analysis_id,
    }
    return Response(
        content=package.content, media_type=package.content_type, headers=headers
    )


@router.post("/projects/{project_id}/analyses/{analysis_id}/exports/bdd/preview")
def preview_bdd_export_by_id(
    project_id: str, analysis_id: str, body: BDDExportRequest | None = None
) -> dict[str, Any]:
    """Preview export; analysis_id may be 'latest' or the synthetic latest-* id."""
    store = get_graph_store()
    analysis = store.get_latest_analysis(project_id)
    if not analysis:
        raise HTTPException(
            404,
            detail={
                "code": "ANALYSIS_NOT_FOUND",
                "message": "No persisted analysis found.",
            },
        )
    if analysis_id not in {"latest", "current"}:
        expected = None
        try:
            from app.agents.bdd_export import _analysis_id_for

            expected = _analysis_id_for(analysis, project_id)
        except Exception:  # noqa: BLE001
            expected = None
        if expected and analysis_id != expected:
            raise HTTPException(
                404,
                detail={
                    "code": "ANALYSIS_NOT_FOUND",
                    "message": "Only the latest analysis is available for export.",
                    "details": {"requested": analysis_id, "latest": expected},
                },
            )
    try:
        preview = build_export_preview(
            project_id, body or BDDExportRequest(), analysis=analysis
        )
    except BDDExportError as exc:
        raise _bdd_export_http_error(exc) from exc
    return preview.model_dump(mode="json")


@router.post("/projects/{project_id}/analyses/{analysis_id}/exports/bdd")
def export_bdd_by_id(
    project_id: str, analysis_id: str, body: BDDExportRequest | None = None
) -> Response:
    store = get_graph_store()
    analysis = store.get_latest_analysis(project_id)
    if not analysis:
        raise HTTPException(
            404,
            detail={
                "code": "ANALYSIS_NOT_FOUND",
                "message": "No persisted analysis found.",
            },
        )
    if analysis_id not in {"latest", "current"}:
        from app.agents.bdd_export import _analysis_id_for

        expected = _analysis_id_for(analysis, project_id)
        if analysis_id != expected:
            raise HTTPException(
                404,
                detail={
                    "code": "ANALYSIS_NOT_FOUND",
                    "message": "Only the latest analysis is available for export.",
                    "details": {"requested": analysis_id, "latest": expected},
                },
            )
    return export_bdd_from_analysis(project_id, body)


@router.get("/projects/{project_id}/automation-profile")
def get_automation_profile(project_id: str) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    profile = store.get_automation_capability_profile(project_id)
    return {"project_id": project_id, "profile": profile}


@router.put("/projects/{project_id}/automation-profile")
def put_automation_profile(
    project_id: str, body: AutomationCapabilityProfile
) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    profile = store.set_automation_capability_profile(
        project_id, body.model_dump(mode="json")
    )
    return {"project_id": project_id, "profile": profile}


@router.patch("/projects/{project_id}/tests/{test_case_id}/automation-review")
def override_automation_review(
    project_id: str, test_case_id: str, body: AutomationReviewOverrideRequest
) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    existing = store.get_test_review_override(project_id, test_case_id) or {}
    original = existing.get("original_agent_recommendation") or {
        k: existing.get(k)
        for k in (
            "validity",
            "automation_suitability",
            "recommended_layer",
            "automation_priority",
            "estimated_effort",
            "final_review_status",
        )
        if existing.get(k)
    }
    payload = {
        **existing,
        "human_override": True,
        "original_agent_recommendation": original
        or existing.get("original_agent_recommendation")
        or {},
        "override_reason": body.override_reason
        or existing.get("override_reason")
        or "",
        "override_timestamp": utc_now().isoformat(),
    }
    for field in (
        "validity",
        "automation_suitability",
        "automation_layer",
        "automation_priority",
        "automation_effort",
        "review_status",
    ):
        value = getattr(body, field)
        if value:
            if field not in payload.get(
                "original_agent_recommendation", {}
            ) and existing.get(field):
                payload.setdefault("original_agent_recommendation", {})[field] = (
                    existing.get(field)
                )
            payload[field] = value
    saved = store.set_test_review_override(project_id, test_case_id, payload)

    # Patch latest analysis reviewed_test_cases if present so UI sees override immediately
    analysis = store.get_latest_analysis(project_id)
    if analysis and isinstance(analysis.get("reviewed_test_cases"), list):
        updated = False
        for item in analysis["reviewed_test_cases"]:
            tc = item.get("test_case") or item.get("original_test_case") or {}
            if str(tc.get("test_case_id")) != test_case_id:
                continue
            validity_review = item.setdefault("validity_review", {})
            automation_review = item.setdefault("automation_review", {})
            if not item.get("human_override"):
                item["human_override"] = True
            if payload.get("validity"):
                validity_review["validity"] = payload["validity"]
                item["final_review_status"] = payload["validity"]
            if not automation_review.get("original_agent_recommendation"):
                automation_review["original_agent_recommendation"] = {
                    k: automation_review.get(k)
                    for k in (
                        "automation_suitability",
                        "recommended_layer",
                        "automation_priority",
                        "estimated_effort",
                    )
                    if automation_review.get(k)
                }
            if payload.get("automation_suitability"):
                automation_review["automation_suitability"] = payload[
                    "automation_suitability"
                ]
            if payload.get("automation_layer"):
                automation_review["recommended_layer"] = payload["automation_layer"]
            if payload.get("automation_priority"):
                automation_review["automation_priority"] = payload[
                    "automation_priority"
                ]
            if payload.get("automation_effort"):
                automation_review["estimated_effort"] = payload["automation_effort"]
            item["override_reason"] = payload.get("override_reason")
            item["override_timestamp"] = payload.get("override_timestamp")
            item["human_override"] = True
            saved_review = store.get_test_review(project_id, test_case_id) or {}
            if saved_review:
                validity_payload = saved_review.get("validity_review") or {}
                automation_payload = saved_review.get("automation_review") or {}
                if payload.get("validity"):
                    validity_payload["validity"] = payload["validity"]
                if payload.get("automation_suitability"):
                    automation_payload["automation_suitability"] = payload[
                        "automation_suitability"
                    ]
                if payload.get("automation_layer"):
                    automation_payload["recommended_layer"] = payload[
                        "automation_layer"
                    ]
                if payload.get("automation_priority"):
                    automation_payload["automation_priority"] = payload[
                        "automation_priority"
                    ]
                if payload.get("automation_effort"):
                    automation_payload["estimated_effort"] = payload[
                        "automation_effort"
                    ]
                saved_review["validity_review"] = validity_payload
                saved_review["automation_review"] = automation_payload
                saved_review["human_override"] = True
                saved_review["override_reason"] = payload.get("override_reason")
                saved_review["override_timestamp"] = payload.get("override_timestamp")
                store.set_test_review(project_id, test_case_id, saved_review)
            updated = True
            break
        if updated:
            store.set_latest_analysis(project_id, analysis)

    return {"project_id": project_id, "test_case_id": test_case_id, "override": saved}


@router.get("/projects/{project_id}/bugs")
def list_bugs(project_id: str) -> list[dict[str, Any]]:
    store = get_graph_store()
    return [b for b in store.bugs.values() if b.get("project_id") == project_id]


@router.get("/projects/{project_id}/dashboard")
def dashboard(project_id: str) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    graph = store.get_project_graph(project_id)
    coverage = get_coverage_engine().analyze(project_id)
    tests = [
        tc for tc in store.test_cases.values() if tc.get("project_id") == project_id
    ]
    bugs = [b for b in store.bugs.values() if b.get("project_id") == project_id]
    critical_tests = [
        tc
        for tc in tests
        if str(tc.get("priority", "")).lower() in {"critical", "high"}
    ]
    return {
        "risk_level": "high" if coverage.critical_gaps or bugs else "medium",
        "graph_coverage": coverage.overall_coverage,
        "branch_coverage": coverage.branch_coverage,
        "test_case_count": len(tests),
        "critical_test_count": len(critical_tests),
        "historical_bugs": len(bugs),
        "impacted_components": len(coverage.uncovered_dependencies),
        "coverage_gaps": coverage.critical_gaps,
        "confidence": "high" if graph.nodes else "low",
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "uncovered_branches": coverage.uncovered_branches,
        "calculation_notes": coverage.calculation_notes,
    }


@router.post("/copilot/query")
def copilot_query(body: QACopilotRequest) -> dict[str, Any]:
    result = get_orchestrator().run(body)
    return result.model_dump(mode="json")


@router.post("/copilot/query/stream")
def copilot_query_stream(body: QACopilotRequest) -> StreamingResponse:
    """SSE progress stream for agentic analysis (mirrors NL→graph stream pattern)."""

    def event_stream() -> Iterator[str]:
        from queue import Empty, Queue
        from threading import Thread

        q: Queue[tuple[str, dict[str, Any]] | None] = Queue()

        def on_progress(stage: str, message: str, meta: dict[str, Any]) -> None:
            q.put(
                (
                    "progress",
                    {
                        "stage": stage,
                        "message": message,
                        "meta": meta or {},
                    },
                )
            )

        def worker() -> None:
            try:
                result = get_orchestrator().run(body, on_progress=on_progress)
                q.put(("complete", result.model_dump(mode="json")))
            except Exception as exc:  # noqa: BLE001
                q.put(("error", {"message": str(exc), "stage": "error"}))
            finally:
                q.put(None)

        Thread(target=worker, daemon=True).start()
        while True:
            try:
                item = q.get(timeout=300)
            except Empty:
                yield f"event: error\ndata: {json.dumps({'message': 'Timed out', 'stage': 'error'})}\n\n"
                break
            if item is None:
                break
            event_name, payload = item
            yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{project_id}/test-review")
def get_test_review(project_id: str) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    analysis = store.get_latest_analysis(project_id)
    if analysis:
        validated = QACopilotResponse.model_validate(analysis)
        if validated.reviewed_test_cases:
            return {
                "project_id": project_id,
                "analysis": validated.model_dump(mode="json"),
            }
    reviews = list(store.list_test_reviews(project_id).values())
    tests = [
        tc for tc in store.test_cases.values() if tc.get("project_id") == project_id
    ]
    return {
        "project_id": project_id,
        "analysis": {
            "project_id": project_id,
            "reviewed_test_cases": reviews,
            "test_cases": tests,
        },
    }


@router.post("/projects/{project_id}/test-review")
def run_test_review(project_id: str) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    result = get_orchestrator().run(
        QACopilotRequest(
            project_id=project_id,
            query="Review existing persisted tests for validity and automation feasibility.",
            requested_outputs=["test_validity_review", "automation_feasibility_review"],
            include_critic=False,
            enable_targeted_regeneration=False,
            include_test_review=True,
        )
    )
    return {"project_id": project_id, "analysis": result.model_dump(mode="json")}


@router.post("/demo/seed", dependencies=[Depends(require_admin_user)])
def seed_demo(force: bool = False) -> dict[str, Any]:
    # TODO(auth MT-B5): apply role guards to user CRUD/admin endpoints once introduced.
    from seed.demo_seed import seed_signin_demo

    return seed_signin_demo(force=force)


@router.get("/projects/{project_id}/latest-analysis")
def latest_analysis(project_id: str) -> dict[str, Any]:
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    analysis = store.get_latest_analysis(project_id)
    if not analysis:
        return {"project_id": project_id, "analysis": None}
    validated = QACopilotResponse.model_validate(analysis)
    return {"project_id": project_id, "analysis": validated.model_dump(mode="json")}


@router.post("/projects/{project_id}/coverage-closure/resume")
def resume_coverage_closure(
    project_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resume an incomplete refinement loop using persisted tests + obligations."""
    store = get_graph_store()
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    prev = store.get_latest_analysis(project_id)
    if not prev:
        raise HTTPException(400, "No analysis to resume")
    body = body or {}
    req = QACopilotRequest(
        project_id=project_id,
        query=str(body.get("query") or prev.get("query") or "Resume coverage closure"),
        root_feature=body.get("root_feature") or prev.get("root_feature"),
        include_critic=True,
        enable_targeted_regeneration=False,
        include_test_review=True,
        enable_test_refinement=True,
        resume_refinement=True,
        test_refinement_max_iterations=body.get("test_refinement_max_iterations"),
        test_output_format=prev.get("test_output_format") or "standard",
        requested_outputs=list(
            body.get("requested_outputs") or ["test_cases", "coverage", "evidence"]
        ),
    )
    result = get_orchestrator().run(req)
    return {"project_id": project_id, "analysis": result.model_dump(mode="json")}
