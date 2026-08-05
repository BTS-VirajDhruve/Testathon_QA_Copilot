"""Vector store using Chroma when available, otherwise numpy cosine search."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import DocumentChunk
from app.rag.document_ingestion import get_document_ingester
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.openai = get_openai_service()
        self.docs = get_document_ingester()
        self._chroma = None
        self._collection = None
        self._fallback_path = Path(self.settings.data_dir) / "vector_index.json"
        self._fallback: dict[str, Any] = {"items": []}
        self._init_chroma()
        self._load_fallback()

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            Path(self.settings.chroma_dir).mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(
                path=self.settings.chroma_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._chroma.get_or_create_collection(
                name="qa_copilot_docs",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("chroma_initialized", path=self.settings.chroma_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("chroma_unavailable_using_json_index", error=str(exc))
            self._chroma = None
            self._collection = None

    @property
    def backend_mode(self) -> str:
        return "chroma" if self._collection is not None else "json_fallback"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "vector_store_mode": self.backend_mode,
            "chroma_dir": self.settings.chroma_dir,
            "fallback_index": str(self._fallback_path),
        }

    def _load_fallback(self) -> None:
        if self._fallback_path.exists():
            try:
                self._fallback = json.loads(self._fallback_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self._fallback = {"items": []}

    def _save_fallback(self) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        self._fallback_path.write_text(json.dumps(self._fallback), encoding="utf-8")

    def index_project(self, project_id: str) -> int:
        chunks = self.docs.get_chunks(project_id)
        if not chunks:
            return 0
        return self.upsert_chunks(chunks)

    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        if not chunks:
            return 0
        embeddings = self.openai.embed([c.content for c in chunks])
        count = 0
        if self._collection is not None:
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
        else:
            existing_ids = {item["id"] for item in self._fallback["items"]}
            for chunk, emb in zip(chunks, embeddings, strict=True):
                item = {
                    "id": chunk.id,
                    "project_id": chunk.project_id,
                    "document_id": chunk.document_id,
                    "content": chunk.content,
                    "embedding": emb,
                    "source_reference": chunk.source_reference,
                    "metadata": chunk.metadata,
                }
                if chunk.id in existing_ids:
                    self._fallback["items"] = [
                        item if i["id"] == chunk.id else i for i in self._fallback["items"]
                    ]
                else:
                    self._fallback["items"].append(item)
                count += 1
            self._save_fallback()
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

        if self._collection is not None:
            try:
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
                    if (meta or {}).get("project_id") and (meta or {}).get("project_id") != project_id:
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("chroma_query_failed", error=str(exc))

        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._fallback["items"]:
            if item.get("project_id") != project_id:
                continue
            meta = item.get("metadata") or {}
            if document_type and str(meta.get("document_type", "")) != document_type:
                continue
            if feature and str(meta.get("feature", "")) != feature:
                continue
            if source_type and str(meta.get("source_type", item.get("source_type", ""))) != source_type:
                continue
            score = self.openai.cosine_similarity(query_emb, item.get("embedding") or [])
            scored.append(
                (
                    score,
                    {
                        "id": item["id"],
                        "content": item["content"],
                        "metadata": meta,
                        "score": round(score, 4),
                        "source_reference": item.get("source_reference"),
                        "document_id": item.get("document_id")
                        or meta.get("document_id"),
                        "project_id": project_id,
                        "source_type": meta.get("source_type") or "requirement",
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored[:top_k]]

    def delete_by_project(self, project_id: str) -> int:
        """Delete all embeddings whose metadata project_id matches. Returns count removed."""
        removed = 0
        if self._collection is not None:
            try:
                existing = self._collection.get(where={"project_id": project_id})
                ids = list(existing.get("ids") or [])
                if ids:
                    self._collection.delete(ids=ids)
                    removed = len(ids)
                else:
                    try:
                        self._collection.delete(where={"project_id": project_id})
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                logger.warning("chroma_project_delete_failed", project_id=project_id, error=str(exc))
                try:
                    self._collection.delete(where={"project_id": project_id})
                except Exception as exc2:  # noqa: BLE001
                    logger.warning("chroma_project_delete_where_failed", error=str(exc2))

        before = len(self._fallback.get("items") or [])
        self._fallback["items"] = [
            item
            for item in (self._fallback.get("items") or [])
            if item.get("project_id") != project_id
        ]
        fallback_removed = before - len(self._fallback["items"])
        if fallback_removed:
            self._save_fallback()
            if self._collection is None:
                removed = fallback_removed
            else:
                removed = max(removed, fallback_removed)

        logger.info("vector_project_deleted", project_id=project_id, removed=removed)
        return removed

    def delete_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        removed = 0
        if self._collection is not None:
            try:
                self._collection.delete(ids=list(ids))
                removed = len(ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("chroma_delete_ids_failed", error=str(exc))
        before = len(self._fallback.get("items") or [])
        id_set = set(ids)
        self._fallback["items"] = [
            item for item in (self._fallback.get("items") or []) if item.get("id") not in id_set
        ]
        fallback_removed = before - len(self._fallback["items"])
        if fallback_removed:
            self._save_fallback()
            if self._collection is None:
                removed = fallback_removed
        return removed


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store