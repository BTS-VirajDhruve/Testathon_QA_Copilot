"""Vector store using Chroma only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import DocumentChunk
from app.rag.document_ingestion import get_document_ingester
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)
CHROMA_TELEMETRY_IMPL = "app.rag.chroma_telemetry.NoOpTelemetry"


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.openai = get_openai_service()
        self.docs = get_document_ingester()
        self._chroma = None
        self._collection = None
        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import DEFAULT_DATABASE, DEFAULT_TENANT
            from chromadb.config import Settings as ChromaSettings

            chroma_settings = ChromaSettings(
                anonymized_telemetry=False,
                chroma_product_telemetry_impl=CHROMA_TELEMETRY_IMPL,
                chroma_telemetry_impl=CHROMA_TELEMETRY_IMPL,
            )
            if self.settings.chroma_use_http:
                self._chroma = chromadb.HttpClient(
                    host=self.settings.chroma_host,
                    port=self.settings.chroma_port,
                    ssl=self.settings.chroma_ssl,
                    tenant=DEFAULT_TENANT,
                    database=DEFAULT_DATABASE,
                    settings=chroma_settings,
                )
            else:
                Path(self.settings.chroma_dir).mkdir(
                    parents=True,
                    exist_ok=True,
                )
                self._chroma = chromadb.PersistentClient(
                    path=self.settings.chroma_dir,
                    tenant=DEFAULT_TENANT,
                    database=DEFAULT_DATABASE,
                    settings=chroma_settings,
                )
            self._ensure_chroma_namespace()
            self._collection = self._chroma.get_or_create_collection(
                name=self.settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "chroma_initialized",
                mode="http" if self.settings.chroma_use_http else "persistent",
                path=self.settings.chroma_dir,
                host=self.settings.chroma_host,
                port=self.settings.chroma_port,
                tenant=self.settings.chroma_tenant,
                database=self.settings.chroma_database,
                collection=self.settings.chroma_collection,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "chroma_initialization_failed",
                error=str(exc)[:240],
            )
            raise RuntimeError("Chroma is required for vector storage") from exc

    @property
    def backend_mode(self) -> str:
        return "chroma"

    def _ensure_chroma_namespace(self) -> None:
        if self._chroma is None:
            return
        target_tenant = self.settings.chroma_tenant
        target_database = self.settings.chroma_database
        admin = getattr(self._chroma, "_admin_client", None)
        if admin is not None:
            try:
                admin.get_tenant(name=target_tenant)
            except Exception:  # noqa: BLE001
                admin.create_tenant(name=target_tenant)
            try:
                admin.get_database(name=target_database, tenant=target_tenant)
            except Exception:  # noqa: BLE001
                admin.create_database(name=target_database, tenant=target_tenant)
        self._chroma.set_tenant(target_tenant)
        self._chroma.set_database(target_database)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "vector_store_mode": self.backend_mode,
            "chroma_mode": (
                "http"
                if self.settings.chroma_use_http
                else "persistent"
            ),
            "chroma_dir": self.settings.chroma_dir,
            "chroma_host": self.settings.chroma_host,
            "chroma_port": self.settings.chroma_port,
            "chroma_tenant": self.settings.chroma_tenant,
            "chroma_database": self.settings.chroma_database,
            "chroma_collection": self.settings.chroma_collection,
        }

    def index_project(self, project_id: str) -> int:
        chunks = self.docs.get_chunks(project_id)
        if not chunks:
            return 0
        return self.upsert_chunks(chunks)

    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        if not chunks:
            return 0
        embeddings = self.openai.embed([c.content for c in chunks])
        ids = [c.id for c in chunks]
        # Idempotent upsert
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=[c.content for c in chunks],
            metadatas=[
                {
                    "project_id": c.project_id,
                    "document_id": c.document_id,
                    "source_reference": c.source_reference or "",
                    **{k: str(v) for k, v in c.metadata.items()},
                }
                for c in chunks
            ],
        )
        count = len(chunks)
        logger.info("vector_upserted", count=count)
        return count

    def search(
        self,
        project_id: str,
        query: str,
        *,
        top_k: int = 8,
        document_type: str | None = None,
        feature: str | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        query_emb = self.openai.embed_one(query)
        where: dict[str, Any] = {"project_id": project_id}
        extra_filters: list[dict[str, Any]] = []
        if document_type:
            extra_filters.append({"document_type": document_type})
        if feature:
            extra_filters.append({"feature": feature})
        if source_type:
            extra_filters.append({"source_type": source_type})
        if extra_filters:
            where = {"$and": [{"project_id": project_id}, *extra_filters]}

        result = self._collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            where=where,
        )
        hits: list[dict[str, Any]] = []
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        for i, doc in enumerate(docs):
            dist = dists[i] if i < len(dists) else 1.0
            meta = metas[i] if i < len(metas) else {}
            if (meta or {}).get("project_id") and (meta or {}).get(
                "project_id"
            ) != project_id:
                continue
            hits.append(
                {
                    "id": ids[i] if i < len(ids) else "",
                    "content": doc,
                    "metadata": meta,
                    "score": round(1.0 - float(dist), 4),
                    "source_reference": (meta or {}).get("source_reference"),
                    "document_id": (meta or {}).get("document_id"),
                    "project_id": (meta or {}).get("project_id") or project_id,
                    "source_type": (meta or {}).get("source_type") or "requirement",
                }
            )
        return hits

    def delete_by_project(self, project_id: str) -> int:
        """Delete all embeddings whose metadata project_id matches. Returns count removed."""
        removed = 0
        existing = self._collection.get(where={"project_id": project_id})
        ids = list(existing.get("ids") or [])
        if ids:
            self._collection.delete(ids=ids)
            removed = len(ids)
        else:
            self._collection.delete(where={"project_id": project_id})
        logger.info("vector_project_deleted", project_id=project_id, removed=removed)
        return removed

    def delete_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        self._collection.delete(ids=list(ids))
        return len(ids)


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
