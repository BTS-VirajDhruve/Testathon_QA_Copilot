"""Document parsing and chunking for Vector RAG."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.models.schemas import DocumentChunk, DocumentRecord, new_id

logger = get_logger(__name__)


def chunk_text(text: str, *, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= chunk_size:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            if len(para) <= chunk_size:
                current = para
            else:
                start = 0
                while start < len(para):
                    end = start + chunk_size
                    chunks.append(para[start:end])
                    start = max(end - overlap, end)
                current = ""
    if current:
        chunks.append(current)
    return chunks


def parse_file(filename: str, raw: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf_parse_failed", error=str(exc))
            return raw.decode("utf-8", errors="ignore")
    if lower.endswith(".docx"):
        try:
            import io

            from docx import Document

            doc = Document(io.BytesIO(raw))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("docx_parse_failed", error=str(exc))
            return raw.decode("utf-8", errors="ignore")
    return raw.decode("utf-8", errors="ignore")


class DocumentIngester:
    def __init__(self) -> None:
        self.store = get_graph_store()

    def ingest_text(
        self,
        project_id: str,
        filename: str,
        text: str,
        *,
        content_type: str = "text/plain",
    ) -> DocumentRecord:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # Idempotent: skip if same hash already stored for project+filename
        for doc in self.store.documents.values():
            if (
                doc.get("project_id") == project_id
                and doc.get("filename") == filename
                and doc.get("content_hash") == content_hash
            ):
                logger.info("document_ingest_idempotent_skip", document_id=doc["id"])
                return DocumentRecord.model_validate(doc)

        doc_id = new_id("doc")
        chunks_text = chunk_text(text)
        chunk_ids: list[str] = []
        chunk_payloads: list[DocumentChunk] = []
        for idx, content in enumerate(chunks_text):
            chunk = DocumentChunk(
                id=new_id("chunk"),
                document_id=doc_id,
                project_id=project_id,
                content=content,
                metadata={"filename": filename, "chunk_index": idx},
                source_reference=f"{filename}#chunk-{idx}",
            )
            chunk_ids.append(chunk.id)
            chunk_payloads.append(chunk)

        record = DocumentRecord(
            id=doc_id,
            project_id=project_id,
            filename=filename,
            content_type=content_type,
            text=text,
            chunk_ids=chunk_ids,
        )
        payload = record.model_dump(mode="json")
        payload["content_hash"] = content_hash
        payload["chunks"] = [c.model_dump(mode="json") for c in chunk_payloads]
        self.store.documents[doc_id] = payload
        self.store.persist()
        logger.info("document_ingested", document_id=doc_id, chunks=len(chunk_ids))
        return record

    def ingest_bytes(
        self, project_id: str, filename: str, raw: bytes, content_type: str = ""
    ) -> DocumentRecord:
        text = parse_file(filename, raw)
        return self.ingest_text(
            project_id,
            filename,
            text,
            content_type=content_type or "application/octet-stream",
        )

    def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        return [
            d
            for d in self.store.documents.values()
            if d.get("project_id") == project_id
        ]

    def get_chunks(self, project_id: str) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for doc in self.list_documents(project_id):
            for c in doc.get("chunks", []):
                chunks.append(DocumentChunk.model_validate(c))
        return chunks


def get_document_ingester() -> DocumentIngester:
    return DocumentIngester()
