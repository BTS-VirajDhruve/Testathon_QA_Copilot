"""FastAPI route modules."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.agents.orchestrator import get_orchestrator
from app.graph.ingestion import get_flow_ingester
from app.graph.store import get_graph_store
from app.graph.traversal import get_coverage_engine, get_traversal
from app.models.schemas import (
    NestedFlowImport,
    QACopilotRequest,
    SystemFlowGraph,
)
from app.rag.document_ingestion import get_document_ingester
from app.rag.vector_store import get_vector_store

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
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "status": "ok",
        "openai": settings.has_openai,
        "neo4j_enabled": settings.neo4j_enabled,
        "demo_fallback": settings.enable_demo_fallback,
    }


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    return get_graph_store().list_projects()


@router.post("/projects")
def create_project(body: ProjectCreateBody) -> dict[str, Any]:
    return get_graph_store().create_project(body.name, body.description, body.root_feature)


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = get_graph_store().get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    graph = get_graph_store().get_project_graph(project_id)
    return {**project, "node_count": len(graph.nodes), "edge_count": len(graph.edges)}


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
async def upload_document(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
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
    return [tc for tc in store.test_cases.values() if tc.get("project_id") == project_id]


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
    tests = [tc for tc in store.test_cases.values() if tc.get("project_id") == project_id]
    bugs = [b for b in store.bugs.values() if b.get("project_id") == project_id]
    critical_tests = [
        tc for tc in tests if str(tc.get("priority", "")).lower() in {"critical", "high"}
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


@router.post("/demo/seed")
def seed_demo() -> dict[str, Any]:
    from seed.demo_seed import seed_signin_demo

    return seed_signin_demo()