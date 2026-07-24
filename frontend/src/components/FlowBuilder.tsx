"use client";

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  Handle,
  Position,
  type NodeProps,
  type Node,
  type Edge,
  addEdge,
  useEdgesState,
  useNodesState,
  Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Download,
  Import,
  Plus,
  Save,
  Trash2,
  Wand2,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  downloadJson,
  emptyGraph,
  layoutTree,
  newEdge,
  newNode,
} from "@/lib/graph";
import type { GraphNode, SystemFlowGraph } from "@/lib/types";

const NODE_TYPES_LIST = [
  "Feature",
  "SubFeature",
  "AuthenticationMethod",
  "UserFlow",
  "FailurePath",
  "AlternateFlow",
  "State",
  "ExternalDependency",
  "ThirdPartyProvider",
  "Component",
  "Service",
  "API",
  "BusinessRule",
  "Validation",
];

const FlowNode = memo(function FlowNode({ data, selected }: NodeProps) {
  const n = data as unknown as GraphNode;
  const tone = n.is_failure_path
    ? "border-signal-high/40 bg-[#fff6f4]"
    : n.is_external_dependency
      ? "border-brass-500/40 bg-[#fffaf2]"
      : n.is_critical
        ? "border-pine-500/40 bg-[#f3faf6]"
        : "border-ink-700/15 bg-white";
  return (
    <div
      className={`min-w-[170px] rounded-2xl border px-3 py-2 shadow-sm ${tone} ${
        selected ? "ring-2 ring-pine-500/40" : ""
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-ink-700" />
      <div className="text-[10px] uppercase tracking-[0.14em] text-ink-600/60">{n.type}</div>
      <div className="mt-1 text-sm font-medium text-ink-900">{n.name}</div>
      {n.provenance?.inferred ? (
        <div className="mt-1 text-[10px] text-brass-600">inferred</div>
      ) : null}
      <Handle type="source" position={Position.Right} className="!bg-ink-700" />
    </div>
  );
});

const nodeTypes = { flowNode: FlowNode };

function FlowBuilderInner({
  graph,
  projectId,
  busy,
  onChange,
  onSave,
  onImported,
}: {
  graph: SystemFlowGraph;
  projectId: string;
  busy: boolean;
  onChange: (g: SystemFlowGraph) => void;
  onSave: (g: SystemFlowGraph) => void;
  onImported: () => Promise<void>;
}) {
  const initial = useMemo(() => layoutTree(graph), [graph.project_id, graph.version, graph.nodes.length, graph.edges.length]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [selectedId, setSelectedId] = useState<string | null>(graph.root_node_id || null);
  const [history, setHistory] = useState<SystemFlowGraph[]>([graph]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [nlText, setNlText] = useState(
    "Sign in supports email password, Google OAuth, enterprise SSO, and self-registration. Email login supports MFA and forgot password."
  );
  const [importJson, setImportJson] = useState("");

  useEffect(() => {
    const laid = layoutTree(graph);
    setNodes(laid.nodes);
    setEdges(laid.edges);
  }, [graph, setNodes, setEdges]);

  const selected = useMemo(
    () => graph.nodes.find((n) => n.id === selectedId) || null,
    [graph.nodes, selectedId]
  );

  const pushHistory = useCallback(
    (next: SystemFlowGraph) => {
      const sliced = history.slice(0, historyIndex + 1);
      const updated = [...sliced, next].slice(-40);
      setHistory(updated);
      setHistoryIndex(updated.length - 1);
      onChange(next);
    },
    [history, historyIndex, onChange]
  );

  const syncFromFlow = useCallback(
    (nextNodes: Node[], nextEdges: Edge[]) => {
      const g: SystemFlowGraph = {
        ...graph,
        nodes: nextNodes.map((n) => {
          const data = n.data as unknown as GraphNode;
          return { ...data, id: n.id };
        }),
        edges: nextEdges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          relationship: String(e.label || "HAS_CHILD").toUpperCase().replace(/\s+/g, "_"),
          provenance: { source_type: "user_input", confidence: 1, inferred: false },
        })),
      };
      pushHistory(g);
    },
    [graph, pushHistory]
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => {
        const next = addEdge(
          {
            ...connection,
            id: `edge_${Math.random().toString(16).slice(2, 8)}`,
            label: "has child",
          },
          eds
        );
        syncFromFlow(nodes, next);
        return next;
      });
    },
    [nodes, setEdges, syncFromFlow]
  );

  function updateSelected(patch: Partial<GraphNode>) {
    if (!selected) return;
    const nextNodes = graph.nodes.map((n) => (n.id === selected.id ? { ...n, ...patch } : n));
    pushHistory({ ...graph, nodes: nextNodes });
  }

  function addChild(kind: "child" | "sibling" = "child") {
    const parentId =
      kind === "child"
        ? selected?.id || graph.root_node_id
        : graph.edges.find((e) => e.target === selected?.id)?.source || graph.root_node_id;
    if (!parentId) return;
    const node = newNode({
      name: kind === "child" ? "New branch" : "New sibling",
      type: "SubFeature",
    });
    const edge = newEdge(parentId, node.id, "HAS_CHILD");
    pushHistory({
      ...graph,
      nodes: [...graph.nodes, node],
      edges: [...graph.edges, edge],
    });
    setSelectedId(node.id);
  }

  function deleteSelected() {
    if (!selected || selected.id === graph.root_node_id) return;
    pushHistory({
      ...graph,
      nodes: graph.nodes.filter((n) => n.id !== selected.id),
      edges: graph.edges.filter((e) => e.source !== selected.id && e.target !== selected.id),
    });
    setSelectedId(graph.root_node_id || null);
  }

  function undo() {
    if (historyIndex <= 0) return;
    const prev = history[historyIndex - 1];
    setHistoryIndex(historyIndex - 1);
    onChange(prev);
  }

  function redo() {
    if (historyIndex >= history.length - 1) return;
    const next = history[historyIndex + 1];
    setHistoryIndex(historyIndex + 1);
    onChange(next);
  }

  async function handleImportJson() {
    try {
      const payload = JSON.parse(importJson || "{}");
      await api.importFlow(projectId, payload);
      await onImported();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Import failed");
    }
  }

  async function handleNl() {
    try {
      await api.flowFromText(projectId, nlText);
      await onImported();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Natural-language graph generation failed");
    }
  }

  async function handleExport() {
    try {
      const exported = await api.exportFlow(projectId);
      downloadJson(`${projectId}-flow.json`, exported);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Export failed");
    }
  }

  function resetRoot() {
    pushHistory(emptyGraph(projectId, "Sign In"));
  }

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/10 px-5 py-4">
        <div>
          <div className="label">System Flow Builder</div>
          <h2 className="font-display text-2xl">Visual system context</h2>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => addChild("child")}>
            <Plus className="h-4 w-4" /> Child
          </button>
          <button className="btn-secondary" onClick={() => addChild("sibling")}>
            <Plus className="h-4 w-4" /> Sibling
          </button>
          <button className="btn-secondary" onClick={deleteSelected}>
            <Trash2 className="h-4 w-4" /> Delete
          </button>
          <button className="btn-secondary" onClick={undo}>
            Undo
          </button>
          <button className="btn-secondary" onClick={redo}>
            Redo
          </button>
          <button className="btn-secondary" onClick={handleExport}>
            <Download className="h-4 w-4" /> Export
          </button>
          <button className="btn-primary" disabled={busy} onClick={() => onSave(graph)}>
            <Save className="h-4 w-4" /> Save graph
          </button>
        </div>
      </div>

      <div className="grid min-h-[640px] lg:grid-cols-[1fr_320px]">
        <div className="relative h-[640px] border-r border-ink-700/10 bg-[radial-gradient(circle_at_top_left,rgba(232,239,235,0.9),#f7faf8)]">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            fitView
            onSelectionChange={({ nodes: sel }) => {
              if (sel[0]) setSelectedId(sel[0].id);
            }}
          >
            <Background gap={22} color="rgba(36,51,44,0.08)" />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const d = n.data as unknown as GraphNode;
                if (d.is_failure_path) return "#b54a3c";
                if (d.is_external_dependency) return "#b08d55";
                return "#2f6b57";
              }}
            />
          </ReactFlow>
        </div>

        <aside className="space-y-4 overflow-auto p-4">
          <div>
            <div className="label">Selected node</div>
            {selected ? (
              <div className="mt-2 space-y-3">
                <input
                  className="w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                  value={selected.name}
                  onChange={(e) => updateSelected({ name: e.target.value })}
                />
                <select
                  className="w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                  value={selected.type}
                  onChange={(e) => updateSelected({ type: e.target.value })}
                >
                  {NODE_TYPES_LIST.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <textarea
                  className="min-h-20 w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                  value={selected.description || ""}
                  onChange={(e) => updateSelected({ description: e.target.value })}
                  placeholder="Description"
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!selected.is_critical}
                    onChange={(e) => updateSelected({ is_critical: e.target.checked })}
                  />
                  Critical
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!selected.is_failure_path}
                    onChange={(e) =>
                      updateSelected({
                        is_failure_path: e.target.checked,
                        type: e.target.checked ? "FailurePath" : selected.type,
                      })
                    }
                  />
                  Failure path
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!selected.is_external_dependency}
                    onChange={(e) =>
                      updateSelected({ is_external_dependency: e.target.checked })
                    }
                  />
                  External dependency
                </label>
                <div className="rounded-xl bg-mist-100 p-3 text-xs text-ink-700/75">
                  Incoming: {graph.edges.filter((e) => e.target === selected.id).length} ·
                  Outgoing: {graph.edges.filter((e) => e.source === selected.id).length}
                  <div className="mt-1">
                    Source: {selected.provenance?.source_type || "user_input"}
                    {selected.provenance?.inferred ? " (inferred)" : ""}
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-2 text-sm text-ink-600/70">Select a node to edit details.</p>
            )}
          </div>

          <div>
            <div className="label mb-2">JSON import</div>
            <textarea
              className="min-h-24 w-full rounded-xl border border-ink-700/15 px-3 py-2 font-mono text-xs"
              placeholder='{"root":"Sign In","branches":[...]}'
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
            />
            <button className="btn-secondary mt-2 w-full" onClick={handleImportJson}>
              <Import className="h-4 w-4" /> Import JSON
            </button>
          </div>

          <div>
            <div className="label mb-2">Natural language → graph</div>
            <textarea
              className="min-h-24 w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
              value={nlText}
              onChange={(e) => setNlText(e.target.value)}
            />
            <button className="btn-brass mt-2 w-full" onClick={handleNl}>
              <Wand2 className="h-4 w-4" /> Extract graph
            </button>
          </div>

          <button className="btn-secondary w-full" onClick={resetRoot}>
            Reset to root feature
          </button>
        </aside>
      </div>
    </section>
  );
}

export function FlowBuilder(props: {
  graph: SystemFlowGraph;
  projectId: string;
  busy: boolean;
  onChange: (g: SystemFlowGraph) => void;
  onSave: (g: SystemFlowGraph) => void;
  onImported: () => Promise<void>;
}) {
  return (
    <ReactFlowProvider>
      <FlowBuilderInner {...props} />
    </ReactFlowProvider>
  );
}