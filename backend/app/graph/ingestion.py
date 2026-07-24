"""Convert nested / NL / visual flow inputs into canonical SystemFlowGraph."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.graph.store import get_graph_store, get_neo4j_store
from app.models.enums import NodeType, Priority, RelationshipType, SourceType
from app.models.schemas import (
    GraphEdge,
    GraphNode,
    NestedBranch,
    NestedFlowImport,
    Provenance,
    SystemFlowGraph,
    new_id,
)
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)

TYPE_HINTS: dict[str, NodeType] = {
    "email": NodeType.AUTHENTICATION_METHOD,
    "password": NodeType.AUTHENTICATION_METHOD,
    "oauth": NodeType.AUTHENTICATION_METHOD,
    "google": NodeType.AUTHENTICATION_METHOD,
    "sso": NodeType.AUTHENTICATION_METHOD,
    "saml": NodeType.AUTHENTICATION_METHOD,
    "oidc": NodeType.AUTHENTICATION_METHOD,
    "mfa": NodeType.SUB_FEATURE,
    "forgot": NodeType.ALTERNATE_FLOW,
    "lockout": NodeType.FAILURE_PATH,
    "failure": NodeType.FAILURE_PATH,
    "callback": NodeType.USER_FLOW,
    "consent": NodeType.USER_FLOW,
    "session": NodeType.STATE,
    "provider": NodeType.THIRD_PARTY_PROVIDER,
    "api": NodeType.API,
    "database": NodeType.DATABASE,
    "db": NodeType.DATABASE,
    "service": NodeType.SERVICE,
    "validation": NodeType.VALIDATION,
    "rule": NodeType.BUSINESS_RULE,
}


def infer_node_type(name: str, explicit: NodeType | None = None, *, is_failure: bool = False) -> NodeType:
    if explicit:
        return explicit
    if is_failure:
        return NodeType.FAILURE_PATH
    lower = name.lower()
    for needle, ntype in TYPE_HINTS.items():
        if needle in lower:
            return ntype
    return NodeType.SUB_FEATURE


def _rel_for_child(parent: GraphNode, child: GraphNode) -> RelationshipType:
    if child.type == NodeType.AUTHENTICATION_METHOD:
        return RelationshipType.HAS_AUTHENTICATION_METHOD
    if child.type == NodeType.FAILURE_PATH or child.is_failure_path:
        return RelationshipType.HAS_FAILURE_PATH
    if child.type == NodeType.ALTERNATE_FLOW:
        return RelationshipType.HAS_ALTERNATE_FLOW
    if child.type == NodeType.SUB_FEATURE:
        return RelationshipType.HAS_SUBFEATURE
    if child.type == NodeType.USER_FLOW:
        return RelationshipType.HAS_FLOW
    if child.type == NodeType.STATE:
        return RelationshipType.HAS_STATE
    if child.type == NodeType.BUSINESS_RULE:
        return RelationshipType.HAS_BUSINESS_RULE
    if child.type == NodeType.VALIDATION:
        return RelationshipType.HAS_VALIDATION
    if child.type in (NodeType.EXTERNAL_DEPENDENCY, NodeType.THIRD_PARTY_PROVIDER):
        return RelationshipType.DEPENDS_ON
    if child.type == NodeType.COMPONENT:
        return RelationshipType.IMPLEMENTED_BY
    if child.type == NodeType.SERVICE:
        return RelationshipType.CALLS
    if child.type == NodeType.API:
        return RelationshipType.EXPOSES
    return RelationshipType.HAS_CHILD


class FlowGraphIngester:
    def __init__(self) -> None:
        self.store = get_graph_store()
        self.neo4j = get_neo4j_store()
        self.openai = get_openai_service()

    def from_nested_import(
        self,
        project_id: str,
        payload: NestedFlowImport | dict[str, Any],
        *,
        source_type: SourceType = SourceType.USER_INPUT,
        inferred: bool = False,
        confidence: float = 1.0,
    ) -> SystemFlowGraph:
        if isinstance(payload, dict):
            payload = NestedFlowImport.model_validate(payload)

        provenance = Provenance(
            source_type=source_type,
            source_reference="json_import" if source_type == SourceType.USER_INPUT else "nl_extraction",
            confidence=confidence,
            inferred=inferred,
        )

        root = GraphNode(
            id=new_id("feature"),
            type=NodeType.FEATURE,
            name=payload.root,
            description=payload.description or f"Root feature: {payload.root}",
            project_id=project_id,
            is_critical=True,
            provenance=provenance,
        )
        nodes: list[GraphNode] = [root]
        edges: list[GraphEdge] = []

        def add_branch(parent: GraphNode, branch: NestedBranch | str) -> None:
            if isinstance(branch, str):
                branch = NestedBranch(name=branch)
            is_failure = branch.is_failure_path or "failure" in branch.name.lower() or "lockout" in branch.name.lower()
            is_external = branch.is_external_dependency or branch.type == NodeType.EXTERNAL_DEPENDENCY
            is_critical = bool(branch.is_critical) or branch.criticality is not None
            child = GraphNode(
                id=new_id("node"),
                type=infer_node_type(branch.name, branch.type, is_failure=is_failure),
                name=branch.name,
                description=branch.description,
                metadata=branch.metadata,
                project_id=project_id,
                is_failure_path=is_failure,
                is_external_dependency=is_external,
                is_critical=is_critical,
                criticality=branch.criticality
                or (Priority.HIGH if is_critical else None),
                provenance=Provenance(
                    source_type=source_type,
                    source_reference=provenance.source_reference,
                    confidence=confidence,
                    inferred=inferred or bool(branch.metadata.get("inferred")),
                ),
            )
            nodes.append(child)
            edges.append(
                GraphEdge(
                    source=parent.id,
                    target=child.id,
                    relationship=_rel_for_child(parent, child),
                    provenance=child.provenance,
                )
            )
            for grandchild in branch.children:
                add_branch(child, grandchild)

        for branch in payload.branches:
            add_branch(root, branch)

        graph = SystemFlowGraph(
            project_id=project_id,
            root_node_id=root.id,
            nodes=nodes,
            edges=edges,
        )
        return self.persist(graph)

    def from_natural_language(self, project_id: str, text: str) -> SystemFlowGraph:
        system = (
            "You extract software system flow graphs for QA. "
            "Return JSON with keys: root, description, branches. "
            "Each branch: name, type (optional), is_failure_path, children[], inferred. "
            "Do NOT invent unsupported system behavior. Mark inferred=true when guessing."
        )
        user = f"Extract a system flow graph from this description:\n\n{text}"
        data = self.openai.chat_json(system, user)
        inferred = bool(data.get("inferred", True))
        confidence = float(data.get("confidence", 0.6))
        payload = {
            "root": data.get("root") or "Feature",
            "description": data.get("description") or text[:240],
            "branches": data.get("branches") or [],
        }
        return self.from_nested_import(
            project_id,
            payload,
            source_type=SourceType.LLM_INFERENCE if inferred else SourceType.USER_INPUT,
            inferred=inferred,
            confidence=confidence,
        )

    def persist(self, graph: SystemFlowGraph) -> SystemFlowGraph:
        saved = self.store.save_project_graph(graph)
        # Best-effort Neo4j sync
        for node in saved.nodes:
            try:
                self.neo4j.sync_node(node)
            except Exception as exc:  # noqa: BLE001
                logger.warning("neo4j_node_sync_failed", error=str(exc))
        for edge in saved.edges:
            try:
                self.neo4j.sync_edge(edge)
            except Exception as exc:  # noqa: BLE001
                logger.warning("neo4j_edge_sync_failed", error=str(exc))
        logger.info(
            "flow_graph_persisted",
            project_id=saved.project_id,
            nodes=len(saved.nodes),
            edges=len(saved.edges),
            version=saved.version,
        )
        return saved

    def merge_artifact_node(self, node: GraphNode, edges: list[GraphEdge] | None = None) -> GraphNode:
        """Add QA artifacts without destroying user flow graph."""
        saved = self.store.upsert_node(node)
        try:
            self.neo4j.sync_node(saved)
        except Exception:  # noqa: BLE001
            pass
        for edge in edges or []:
            self.store.upsert_edge(edge)
            try:
                self.neo4j.sync_edge(edge)
            except Exception:  # noqa: BLE001
                pass
        return saved


def get_flow_ingester() -> FlowGraphIngester:
    return FlowGraphIngester()