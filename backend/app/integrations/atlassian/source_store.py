"""Project-scoped external knowledge source registry (Atlassian imports)."""

from __future__ import annotations

from app.graph.store import get_graph_store
from app.integrations.atlassian.schemas import ExternalKnowledgeSource


def list_sources(qa_project_id: str) -> list[ExternalKnowledgeSource]:
    store = get_graph_store()
    out = [
        ExternalKnowledgeSource.model_validate(raw)
        for raw in store.external_knowledge_sources.values()
        if raw.get("qa_project_id") == qa_project_id
    ]
    return sorted(out, key=lambda s: s.imported_at or "", reverse=True)


def get_source(source_id: str) -> ExternalKnowledgeSource | None:
    raw = get_graph_store().external_knowledge_sources.get(source_id)
    return ExternalKnowledgeSource.model_validate(raw) if raw else None


def upsert_source(source: ExternalKnowledgeSource) -> ExternalKnowledgeSource:
    store = get_graph_store()
    store.external_knowledge_sources[source.source_id] = source.model_dump(mode="json")
    store.persist()
    return source


def delete_source(source_id: str) -> ExternalKnowledgeSource | None:
    store = get_graph_store()
    raw = store.external_knowledge_sources.pop(source_id, None)
    if raw is not None:
        store.persist()
        return ExternalKnowledgeSource.model_validate(raw)
    return None


def find_by_identity(
    *,
    qa_project_id: str,
    cloud_id: str,
    source_type: str,
    external_id: str,
) -> ExternalKnowledgeSource | None:
    for src in list_sources(qa_project_id):
        if (
            src.cloud_id == cloud_id
            and src.source_type == source_type
            and src.external_id == external_id
        ):
            return src
    return None
