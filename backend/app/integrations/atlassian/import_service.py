"""Import / sync Atlassian sources into project-scoped Knowledge Base + Vector RAG."""

from __future__ import annotations

import hashlib
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.integrations.atlassian import source_store
from app.integrations.atlassian.confluence import get_confluence_adapter
from app.integrations.atlassian.errors import (
    IMPORT_LIMIT_EXCEEDED,
    PROJECT_MISMATCH,
    VECTOR_INGESTION_FAILED,
    AtlassianIntegrationError,
)
from app.integrations.atlassian.jira import get_jira_adapter
from app.integrations.atlassian.oauth import require_selected_cloud_id
from app.integrations.atlassian.schemas import (
    AtlassianImportReport,
    AtlassianImportRequest,
    ExternalKnowledgeSource,
    ImportFailure,
    ImportSourceItem,
)
from app.models.schemas import DocumentChunk, new_id, utc_now
from app.rag.document_ingestion import chunk_text
from app.rag.vector_store import get_vector_store

logger = get_logger(__name__)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _delete_document_vectors(document_id: str, project_id: str) -> None:
    store = get_graph_store()
    doc = store.documents.get(document_id)
    chunk_ids = list((doc or {}).get("chunk_ids") or [])
    vs = get_vector_store()
    if hasattr(vs, "delete_ids") and chunk_ids:
        vs.delete_ids(chunk_ids)
    # Also remove from store documents
    if (
        document_id in store.documents
        and store.documents[document_id].get("project_id") == project_id
    ):
        del store.documents[document_id]
        store.persist()


def _ingest_normalized(
    *,
    qa_project_id: str,
    filename: str,
    text: str,
    metadata: dict[str, Any],
    replace_document_id: str | None = None,
) -> tuple[str, int, list[DocumentChunk]]:
    if replace_document_id:
        _delete_document_vectors(replace_document_id, qa_project_id)

    content_hash = _hash(text)
    doc_id = new_id("doc")
    chunks_text = chunk_text(text)
    chunk_payloads: list[DocumentChunk] = []
    chunk_ids: list[str] = []
    for idx, content in enumerate(chunks_text):
        meta = {
            **{k: str(v) for k, v in metadata.items() if v is not None},
            "filename": filename,
            "chunk_index": str(idx),
            "provider": "atlassian",
            "content_hash": content_hash,
        }
        chunk = DocumentChunk(
            id=new_id("chunk"),
            document_id=doc_id,
            project_id=qa_project_id,
            content=content,
            metadata=meta,
            source_reference=f"{filename}#chunk-{idx}",
        )
        chunk_ids.append(chunk.id)
        chunk_payloads.append(chunk)

    store = get_graph_store()
    record = {
        "id": doc_id,
        "project_id": qa_project_id,
        "filename": filename,
        "content_type": "text/markdown",
        "text": text,
        "chunk_ids": chunk_ids,
        "content_hash": content_hash,
        "chunks": [c.model_dump(mode="json") for c in chunk_payloads],
        "provider": "atlassian",
        "source_type": metadata.get("source_type"),
        "external_id": metadata.get("external_id"),
        "created_at": utc_now().isoformat(),
    }
    store.documents[doc_id] = record
    store.persist()
    try:
        get_vector_store().upsert_chunks(chunk_payloads)
    except Exception as exc:  # noqa: BLE001
        raise AtlassianIntegrationError(
            VECTOR_INGESTION_FAILED,
            f"Failed to embed imported source: {exc}",
            status_code=500,
        ) from exc
    return doc_id, len(chunk_payloads), chunk_payloads


def import_sources(request: AtlassianImportRequest) -> AtlassianImportReport:
    settings = get_settings()
    store = get_graph_store()
    if not store.get_project(request.qa_project_id):
        raise AtlassianIntegrationError(
            PROJECT_MISMATCH, "QA project not found", status_code=404
        )

    if len(request.sources) > settings.atlassian_import_max_items:
        raise AtlassianIntegrationError(
            IMPORT_LIMIT_EXCEEDED,
            f"Import limited to {settings.atlassian_import_max_items} items",
            status_code=400,
        )

    cloud_id = require_selected_cloud_id()
    jira = get_jira_adapter()
    confluence = get_confluence_adapter()
    report = AtlassianImportReport(requested=len(request.sources))

    for item in request.sources:
        try:
            source = _import_one(
                qa_project_id=request.qa_project_id,
                cloud_id=cloud_id,
                item=item,
                include_comments=request.options.include_comments
                and settings.atlassian_comments_import_enabled,
                replace_existing=request.options.replace_existing,
                jira=jira,
                confluence=confluence,
            )
            if source.sync_status == "unchanged":
                report.unchanged += 1
            elif source.sync_status == "updated":
                report.updated += 1
            else:
                report.imported += 1
            report.sources.append(source)
        except AtlassianIntegrationError as exc:
            report.failed += 1
            report.failures.append(
                ImportFailure(
                    external_id=item.external_id,
                    source_type=item.source_type,
                    error=exc.message,
                    code=exc.code,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("atlassian_import_item_failed", error=str(exc))
            report.failed += 1
            report.failures.append(
                ImportFailure(
                    external_id=item.external_id,
                    source_type=item.source_type,
                    error=str(exc)[:240],
                    code="IMPORT_FAILED",
                )
            )
    return report


def _import_one(
    *,
    qa_project_id: str,
    cloud_id: str,
    item: ImportSourceItem,
    include_comments: bool,
    replace_existing: bool,
    jira: Any,
    confluence: Any,
) -> ExternalKnowledgeSource:
    _ = include_comments  # reserved; comments disabled by default
    existing = source_store.find_by_identity(
        qa_project_id=qa_project_id,
        cloud_id=cloud_id,
        source_type=item.source_type,
        external_id=item.external_id,
    )

    if item.source_type == "jira_issue":
        key = item.external_key or item.external_id
        text, preview = jira.normalize_issue(key)
        filename = f"JIRA:{preview.key}"
        meta = {
            "source_type": "jira_issue",
            "external_id": preview.id,
            "external_key": preview.key,
            "source_url": preview.url or "",
            "container_id": item.container_id or "",
            "container_key": item.container_key or "",
            "title": f"{preview.key} — {preview.summary}",
            "version": preview.updated_at or "",
            "remote_updated_at": preview.updated_at or "",
        }
        title = meta["title"]
        external_key = preview.key
        external_id = preview.id
        source_url = preview.url
        remote_updated = preview.updated_at
        remote_created = preview.created_at
        version = preview.updated_at
        container_id = item.container_id
        container_key = item.container_key
    else:
        text, preview = confluence.normalize_page(item.external_id)
        filename = f"CONF:{preview.title}"
        meta = {
            "source_type": "confluence_page",
            "external_id": preview.id,
            "external_key": preview.id,
            "source_url": preview.web_url or "",
            "container_id": preview.space_id or item.container_id or "",
            "container_key": item.container_key or "",
            "title": preview.title,
            "version": str(preview.version_number or ""),
            "remote_updated_at": preview.updated_at or "",
        }
        title = preview.title
        external_key = preview.id
        external_id = preview.id
        source_url = preview.web_url
        remote_updated = preview.updated_at
        remote_created = preview.created_at
        version = str(preview.version_number or "")
        container_id = preview.space_id or item.container_id
        container_key = item.container_key

    content_hash = _hash(text)
    now = utc_now().isoformat()

    if existing and existing.content_hash == content_hash:
        existing.sync_status = "unchanged"
        existing.last_synced_at = now
        return source_store.upsert_source(existing)

    replace_id = existing.document_id if (existing and replace_existing) else None
    if existing and not replace_existing and existing.content_hash != content_hash:
        replace_id = existing.document_id

    doc_id, chunk_count, _ = _ingest_normalized(
        qa_project_id=qa_project_id,
        filename=filename,
        text=text,
        metadata=meta,
        replace_document_id=replace_id,
    )

    source = ExternalKnowledgeSource(
        source_id=existing.source_id if existing else new_id("eks"),
        qa_project_id=qa_project_id,
        source_type=item.source_type,
        cloud_id=cloud_id,
        container_id=container_id,
        container_key=container_key,
        external_id=external_id,
        external_key=external_key,
        title=title,
        normalized_content=text[:2000],
        source_url=source_url,
        version=version,
        remote_created_at=remote_created,
        remote_updated_at=remote_updated,
        imported_at=existing.imported_at if existing else now,
        last_synced_at=now,
        content_hash=content_hash,
        metadata=meta,
        sync_status="updated" if existing else "imported",
        document_id=doc_id,
        chunk_count=chunk_count,
    )
    return source_store.upsert_source(source)


def sync_source(source_id: str, qa_project_id: str) -> ExternalKnowledgeSource:
    src = source_store.get_source(source_id)
    if not src or src.qa_project_id != qa_project_id:
        raise AtlassianIntegrationError(
            PROJECT_MISMATCH, "Source not found in project", status_code=404
        )
    try:
        report = import_sources(
            AtlassianImportRequest(
                qa_project_id=qa_project_id,
                sources=[
                    ImportSourceItem(
                        source_type=src.source_type,
                        external_id=src.external_id,
                        external_key=src.external_key,
                        container_id=src.container_id,
                        container_key=src.container_key,
                    )
                ],
            )
        )
        if report.sources:
            return report.sources[0]
        if report.failures:
            fail = report.failures[0]
            src.sync_status = (
                "permission_lost"
                if fail.code
                in {"JIRA_PERMISSION_DENIED", "CONFLUENCE_PERMISSION_DENIED"}
                else "remote_missing"
                if fail.code == "RESOURCE_NOT_FOUND"
                else "failed"
            )
            src.error = fail.error
            return source_store.upsert_source(src)
    except AtlassianIntegrationError as exc:
        if exc.code in {"JIRA_PERMISSION_DENIED", "CONFLUENCE_PERMISSION_DENIED"}:
            src.sync_status = "permission_lost"
        elif exc.code == "RESOURCE_NOT_FOUND":
            src.sync_status = "remote_missing"
        else:
            src.sync_status = "failed"
        src.error = exc.message
        return source_store.upsert_source(src)
    return src


def remove_source(source_id: str, qa_project_id: str) -> bool:
    src = source_store.get_source(source_id)
    if not src or src.qa_project_id != qa_project_id:
        return False
    if src.document_id:
        _delete_document_vectors(src.document_id, qa_project_id)
    source_store.delete_source(source_id)
    return True
