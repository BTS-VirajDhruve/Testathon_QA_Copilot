"""Entity and relationship extraction from documents into the QA graph."""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger
from app.graph.ingestion import get_flow_ingester
from app.graph.store import get_graph_store
from app.models.enums import NodeType, RelationshipType, SourceType
from app.models.schemas import GraphEdge, GraphNode, Provenance, new_id
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)

ENTITY_PATTERNS: list[tuple[re.Pattern[str], NodeType]] = [
    (re.compile(r"\bGoogle OAuth\b", re.I), NodeType.AUTHENTICATION_METHOD),
    (re.compile(r"\bEnterprise SSO\b", re.I), NodeType.AUTHENTICATION_METHOD),
    (re.compile(r"\bMFA\b", re.I), NodeType.SUB_FEATURE),
    (re.compile(r"\bAccount lockout\b", re.I), NodeType.FAILURE_PATH),
    (re.compile(r"\bForgot Password\b", re.I), NodeType.ALTERNATE_FLOW),
    (re.compile(r"\bSAML\b", re.I), NodeType.USER_FLOW),
    (re.compile(r"\bOIDC\b", re.I), NodeType.USER_FLOW),
    (re.compile(r"\bSession(?: Creation)?\b", re.I), NodeType.STATE),
]


class EntityExtractor:
    """Extract graph entities from document text without inventing unsupported behavior."""

    def __init__(self) -> None:
        self.store = get_graph_store()
        self.ingester = get_flow_ingester()
        self.openai = get_openai_service()

    def extract_from_text(
        self,
        project_id: str,
        text: str,
        *,
        source_reference: str,
    ) -> dict[str, Any]:
        found: list[GraphNode] = []
        seen: set[str] = set()

        for pattern, ntype in ENTITY_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(0)
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                existing = self.store.find_node_by_name(project_id, name)
                if existing:
                    found.append(existing)
                    continue
                node = GraphNode(
                    id=new_id("ext"),
                    type=ntype,
                    name=name,
                    description=f"Extracted from document: {source_reference}",
                    project_id=project_id,
                    is_failure_path=ntype == NodeType.FAILURE_PATH,
                    provenance=Provenance(
                        source_type=SourceType.DOCUMENT,
                        source_reference=source_reference,
                        confidence=0.8,
                        inferred=False,
                    ),
                )
                self.ingester.merge_artifact_node(node)
                found.append(node)

        # Optionally enrich with LLM — mark as inferred
        if self.openai.available and len(found) < 3:
            try:
                data = self.openai.chat_json(
                    "Extract explicit software entities mentioned in the text. "
                    "Return JSON {entities:[{name,type}]}. Do not invent.",
                    text[:4000],
                )
                for ent in data.get("entities", [])[:10]:
                    name = ent.get("name")
                    if not name or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    node = GraphNode(
                        id=new_id("ext"),
                        type=NodeType.COMPONENT,
                        name=name,
                        project_id=project_id,
                        provenance=Provenance(
                            source_type=SourceType.LLM_INFERENCE,
                            source_reference=source_reference,
                            confidence=0.55,
                            inferred=True,
                        ),
                    )
                    self.ingester.merge_artifact_node(node)
                    found.append(node)
            except Exception as exc:  # noqa: BLE001
                logger.warning("entity_llm_extract_failed", error=str(exc))

        # Link extracted entities to root feature when present
        root_id = (self.store.get_project(project_id) or {}).get("root_feature_id")
        edges_created = 0
        if root_id:
            for node in found:
                if node.id == root_id:
                    continue
                edge = GraphEdge(
                    source=root_id,
                    target=node.id,
                    relationship=RelationshipType.RELATED_TO,
                    provenance=Provenance(
                        source_type=SourceType.DOCUMENT,
                        source_reference=source_reference,
                        confidence=0.6,
                        inferred=True,
                    ),
                )
                self.store.upsert_edge(edge)
                edges_created += 1

        logger.info(
            "entities_extracted",
            project_id=project_id,
            entities=len(found),
            edges=edges_created,
        )
        return {
            "entities": [n.model_dump(mode="json") for n in found],
            "edges_created": edges_created,
        }


def get_entity_extractor() -> EntityExtractor:
    return EntityExtractor()