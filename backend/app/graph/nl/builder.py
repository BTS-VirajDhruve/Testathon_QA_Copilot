"""Phase 5–6 — deterministic NestedFlowImport builder + graph validation/repair."""

from __future__ import annotations

from typing import Any

from app.graph.nl.models import IntermediateNode, IntermediateTree
from app.models.enums import NodeType
from app.models.schemas import NestedBranch, NestedFlowImport, SystemFlowGraph


def tree_to_nested_import(tree: IntermediateTree) -> NestedFlowImport:
    """Convert IntermediateTree → NestedFlowImport (no IDs). Deterministic."""

    def convert(node: IntermediateNode) -> NestedBranch:
        return NestedBranch(
            name=node.name,
            type=node.type,
            description=node.description or "",
            children=[convert(c) for c in node.children],
            metadata={
                **dict(node.metadata),
                "type_confidence": node.type_confidence,
                "nl_pipeline": True,
            },
            is_failure_path=node.is_failure_path or node.type == NodeType.FAILURE_PATH,
            is_external_dependency=node.is_external_dependency
            or node.type
            in (NodeType.EXTERNAL_DEPENDENCY, NodeType.THIRD_PARTY_PROVIDER),
            is_critical=node.is_critical,
            criticality=node.criticality,
        )

    branches = [convert(c) for c in tree.root.children]
    return NestedFlowImport(
        root=tree.root.name,
        description=tree.description or tree.root.description or "",
        branches=branches,
    )


def validate_and_repair_graph(graph: SystemFlowGraph) -> tuple[SystemFlowGraph, list[str]]:
    """
    Validate canonical graph and repair in-place:
    - exactly one logical root (graph.root_node_id)
    - unique IDs
    - edges reference existing nodes
    - drop self-loops / dangling edges
    - coerce unknown types to SubFeature
    """
    repairs: list[str] = []
    if not graph.nodes:
        repairs.append("empty_graph")
        return graph, repairs

    # Unique IDs
    seen: set[str] = set()
    unique_nodes = []
    for node in graph.nodes:
        if node.id in seen:
            repairs.append(f"duplicate_id:{node.id}")
            continue
        seen.add(node.id)
        # Valid type
        try:
            NodeType(node.type if isinstance(node.type, str) else node.type.value)
        except Exception:  # noqa: BLE001
            repairs.append(f"invalid_type:{node.id}:{node.type}")
            node.type = NodeType.SUB_FEATURE
        unique_nodes.append(node)
    graph.nodes = unique_nodes
    id_set = {n.id for n in graph.nodes}

    # Root
    if not graph.root_node_id or graph.root_node_id not in id_set:
        # Prefer Feature-typed node, else first node
        feature = next((n for n in graph.nodes if n.type == NodeType.FEATURE), None)
        graph.root_node_id = feature.id if feature else graph.nodes[0].id
        repairs.append(f"root_repaired:{graph.root_node_id}")

    # Edges
    valid_edges = []
    edge_ids: set[str] = set()
    for edge in graph.edges:
        if edge.id in edge_ids:
            repairs.append(f"duplicate_edge:{edge.id}")
            continue
        if edge.source not in id_set or edge.target not in id_set:
            repairs.append(f"dangling_edge:{edge.id}")
            continue
        if edge.source == edge.target:
            repairs.append(f"self_loop:{edge.id}")
            continue
        edge_ids.add(edge.id)
        valid_edges.append(edge)
    graph.edges = valid_edges

    # Ensure every non-root node has at least one parent edge; else attach to root
    children = {e.target for e in graph.edges}
    for node in graph.nodes:
        if node.id == graph.root_node_id:
            continue
        if node.id not in children:
            from app.models.schemas import GraphEdge, Provenance

            graph.edges.append(
                GraphEdge(
                    source=graph.root_node_id,
                    target=node.id,
                    relationship="HAS_CHILD",
                    provenance=Provenance(
                        source_type=node.provenance.source_type,
                        source_reference="nl_validation_repair",
                        confidence=0.5,
                        inferred=True,
                    ),
                )
            )
            repairs.append(f"orphaned_attached:{node.id}")

    return graph, repairs


def nested_import_stats(payload: NestedFlowImport) -> dict[str, Any]:
    def walk(branches: list) -> int:
        n = 0
        for b in branches:
            n += 1
            children = getattr(b, "children", []) or []
            normalized = []
            for c in children:
                if isinstance(c, str):
                    from app.models.schemas import NestedBranch

                    normalized.append(NestedBranch(name=c))
                else:
                    normalized.append(c)
            n += walk(normalized)
        return n

    return {
        "root": payload.root,
        "branch_nodes": walk(payload.branches),
        "top_level_branches": len(payload.branches),
    }
