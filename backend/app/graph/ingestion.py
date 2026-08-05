"""Convert nested / NL / visual flow inputs into canonical SystemFlowGraph."""

from __future__ import annotations

from typing import Any, Callable

from app.core.logging import get_logger
from app.graph.node_typing import infer_node_type, rel_for_child
from app.graph.store import get_graph_store, get_neo4j_store
from app.models.enums import NodeType, Priority, SourceType
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

# Re-export for backward compatibility with imports of TYPE_HINTS / infer_node_type
from app.graph.node_typing import TYPE_HINTS  # noqa: E402,F401

ProgressCallback = Callable[[str, str, dict[str, Any]], None]


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
                    relationship=rel_for_child(parent, child),
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

    def from_natural_language(
        self,
        project_id: str,
        text: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> SystemFlowGraph:
        """
        Deterministic NL → Intermediate Tree → NestedFlowImport → canonical graph.

        LLM is used only for low-confidence node type classification (never for JSON).
        """
        from app.graph.nl.builder import validate_and_repair_graph
        from app.graph.nl.pipeline import ProgressEvent, run_nl_to_nested_import

        def _bridge(event: ProgressEvent) -> None:
            if on_progress:
                on_progress(event.stage, event.message, event.meta)

        result = run_nl_to_nested_import(
            text,
            project_id=project_id,
            on_progress=_bridge if on_progress else None,
        )

        if on_progress:
            on_progress("generating", "Persisting graph...", result.stats)

        graph = self.from_nested_import(
            project_id,
            result.nested,
            source_type=SourceType.LLM_INFERENCE if result.inferred else SourceType.USER_INPUT,
            inferred=result.inferred,
            confidence=result.confidence,
        )

        graph, repairs = validate_and_repair_graph(graph)
        if repairs:
            logger.info("nl_graph_repairs", project_id=project_id, repairs=repairs)
            graph = self.persist(graph)

        if on_progress:
            on_progress(
                "rendering",
                "Rendering graph...",
                {
                    "nodes": len(graph.nodes),
                    "edges": len(graph.edges),
                    "llm_calls": result.stats.get("llm_calls", 0),
                    "repairs": repairs,
                },
            )

        logger.info(
            "nl_graph_built",
            project_id=project_id,
            nodes=len(graph.nodes),
            edges=len(graph.edges),
            llm_calls=result.stats.get("llm_calls", 0),
            parser=result.stats.get("parser", {}).get("parser"),
        )
        # Attach pipeline stats on root metadata for diagnostics (non-breaking)
        if graph.nodes:
            root = next((n for n in graph.nodes if n.id == graph.root_node_id), graph.nodes[0])
            root.metadata = {
                **dict(root.metadata or {}),
                "nl_pipeline_stats": {
                    "llm_calls": result.stats.get("llm_calls", 0),
                    "classification": result.stats.get("classification"),
                    "parser": result.stats.get("parser", {}).get("parser"),
                },
            }
            self.store.upsert_node(root)
        return graph

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
