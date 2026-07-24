"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";
import { layoutTree } from "@/lib/graph";
import type { NodeInsight, SystemFlowGraph } from "@/lib/types";

function ExplorerInner({
  projectId,
  graph,
}: {
  projectId: string;
  graph: SystemFlowGraph;
}) {
  const laid = useMemo(() => layoutTree(graph), [graph]);
  const [selectedId, setSelectedId] = useState(graph.root_node_id || graph.nodes[0]?.id || "");
  const [insight, setInsight] = useState<NodeInsight | null>(null);

  useEffect(() => {
    if (!selectedId) return;
    api.nodeInsight(projectId, selectedId).then(setInsight).catch(() => setInsight(null));
  }, [projectId, selectedId]);

  const highlight = useMemo(() => {
    const connected = new Set<string>([selectedId]);
    for (const e of graph.edges) {
      if (e.source === selectedId) connected.add(e.target);
      if (e.target === selectedId) connected.add(e.source);
    }
    return connected;
  }, [graph.edges, selectedId]);

  const nodes = laid.nodes.map((n) => ({
    ...n,
    style: {
      opacity: highlight.has(n.id) ? 1 : 0.35,
      border: n.id === selectedId ? "2px solid #2f6b57" : undefined,
      borderRadius: 16,
      padding: 0,
      background: "transparent",
      width: 180,
    },
    data: {
      label: (
        <div className="rounded-2xl border border-ink-700/15 bg-white px-3 py-2 text-left shadow-sm">
          <div className="text-[10px] uppercase tracking-[0.12em] text-ink-600/60">
            {(n.data as { type?: string }).type}
          </div>
          <div className="text-sm font-medium">{(n.data as { name?: string }).name}</div>
        </div>
      ),
    },
    type: "default",
  }));

  const edges = laid.edges.map((e) => ({
    ...e,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: {
      stroke:
        highlight.has(e.source) && highlight.has(e.target) ? "#2f6b57" : "rgba(36,51,44,0.2)",
      strokeWidth: highlight.has(e.source) && highlight.has(e.target) ? 2.5 : 1,
    },
  }));

  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-ink-700/10 px-5 py-4">
        <div className="label">Graph Explorer</div>
        <h2 className="font-display text-2xl">Inspect relationships & evidence</h2>
      </div>
      <div className="grid min-h-[580px] lg:grid-cols-[1fr_340px]">
        <div className="h-[580px] border-r border-ink-700/10">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            onNodeClick={(_, n) => setSelectedId(n.id)}
          >
            <Background gap={20} color="rgba(36,51,44,0.07)" />
            <Controls />
          </ReactFlow>
        </div>
        <aside className="space-y-4 overflow-auto p-5">
          {!insight ? (
            <p className="text-sm text-ink-600/70">Select a node to inspect.</p>
          ) : (
            <>
              <div>
                <div className="label">Node</div>
                <h3 className="mt-1 font-display text-xl">{insight.node.name}</h3>
                <p className="mt-1 text-sm text-ink-700/75">{insight.node.description || insight.node.type}</p>
              </div>
              <Metric title="Risk" value={insight.risk.toUpperCase()} />
              <Metric
                title="Coverage"
                value={insight.coverage != null ? `${Math.round(insight.coverage * 100)}%` : "n/a"}
              />
              <List title="Connected features" items={insight.connected_features} />
              <List title="Dependencies" items={insight.dependencies} />
              <List title="Flows" items={insight.flows} />
              <List title="Existing tests" items={insight.existing_tests} />
              <List title="Historical bugs" items={insight.historical_bugs} />
              <div>
                <div className="label mb-2">Relationships</div>
                <div className="space-y-1 text-xs text-ink-700/80">
                  {insight.incoming.map((i) => (
                    <div key={`in-${i.node_id}`}>← {i.from} [{i.relationship}]</div>
                  ))}
                  {insight.outgoing.map((o) => (
                    <div key={`out-${o.node_id}`}>→ {o.to} [{o.relationship}]</div>
                  ))}
                </div>
              </div>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-xl bg-mist-100 px-3 py-2">
      <div className="label">{title}</div>
      <div className="mt-1 font-medium">{value}</div>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="label mb-1">{title}</div>
      {items.length === 0 ? (
        <div className="text-sm text-ink-600/60">None</div>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.map((i) => (
            <li key={i}>• {i}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function GraphExplorer(props: { projectId: string; graph: SystemFlowGraph }) {
  return (
    <ReactFlowProvider>
      <ExplorerInner {...props} />
    </ReactFlowProvider>
  );
}