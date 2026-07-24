import type { Edge, Node } from "@xyflow/react";
import type { GraphEdge, GraphNode, SystemFlowGraph } from "./types";

export function layoutTree(graph: SystemFlowGraph): { nodes: Node[]; edges: Edge[] } {
  const children = new Map<string, string[]>();
  for (const e of graph.edges) {
    const list = children.get(e.source) || [];
    list.push(e.target);
    children.set(e.source, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  const rootId = graph.root_node_id || graph.nodes[0]?.id;
  const visited = new Set<string>();

  function place(id: string, depth: number, index: number, siblings: number) {
    if (visited.has(id)) return;
    visited.add(id);
    const x = depth * 260;
    const spread = Math.max(siblings, 1);
    const y = index * 120 - ((spread - 1) * 120) / 2;
    positions.set(id, { x, y: depth === 0 ? 0 : y });
    const kids = children.get(id) || [];
    kids.forEach((kid, i) => place(kid, depth + 1, i, kids.length));
  }

  if (rootId) {
    place(rootId, 0, 0, 1);
    // Second pass: center children under parent
    const recompute = (id: string, depth: number) => {
      const kids = children.get(id) || [];
      kids.forEach((kid, i) => {
        const parentPos = positions.get(id) || { x: 0, y: 0 };
        const total = kids.length;
        const y = parentPos.y + (i - (total - 1) / 2) * 130;
        positions.set(kid, { x: (depth + 1) * 280, y });
        recompute(kid, depth + 1);
      });
    };
    recompute(rootId, 0);
  }

  // Place orphans
  graph.nodes.forEach((n, i) => {
    if (!positions.has(n.id)) {
      positions.set(n.id, { x: 0, y: 200 + i * 100 });
    }
  });

  const nodes: Node[] = graph.nodes.map((n) => ({
    id: n.id,
    type: "flowNode",
    position: positions.get(n.id) || { x: 0, y: 0 },
    data: { ...n },
  }));

  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: humanRel(e.relationship),
    animated: Boolean(
      graph.nodes.find((n) => n.id === e.target)?.is_failure_path
    ),
    style: {
      stroke: graph.nodes.find((n) => n.id === e.target)?.is_failure_path
        ? "#b54a3c"
        : "#33463c",
    },
  }));

  return { nodes, edges };
}

export function humanRel(rel: string): string {
  return rel.replace(/_/g, " ").toLowerCase();
}

export function emptyGraph(projectId: string, rootName = "Root Feature"): SystemFlowGraph {
  const id = `feature_${Math.random().toString(16).slice(2, 10)}`;
  return {
    project_id: projectId,
    root_node_id: id,
    version: 1,
    nodes: [
      {
        id,
        type: "Feature",
        name: rootName,
        description: "Root feature / user journey entry",
        is_critical: true,
        provenance: {
          source_type: "user_input",
          confidence: 1,
          inferred: false,
        },
      },
    ],
    edges: [],
  };
}

export function newNode(
  partial: Partial<GraphNode> & { name: string }
): GraphNode {
  return {
    id: `node_${Math.random().toString(16).slice(2, 10)}`,
    type: partial.type || "SubFeature",
    name: partial.name,
    description: partial.description || "",
    metadata: partial.metadata || {},
    is_failure_path: partial.is_failure_path || false,
    is_external_dependency: partial.is_external_dependency || false,
    is_critical: partial.is_critical || false,
    provenance: {
      source_type: "user_input",
      confidence: 1,
      inferred: false,
    },
  };
}

export function newEdge(source: string, target: string, relationship = "HAS_CHILD"): GraphEdge {
  return {
    id: `edge_${Math.random().toString(16).slice(2, 10)}`,
    source,
    target,
    relationship,
    provenance: { source_type: "user_input", confidence: 1, inferred: false },
  };
}

export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}