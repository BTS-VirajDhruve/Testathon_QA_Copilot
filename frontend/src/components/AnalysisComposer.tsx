"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Loader2, Send } from "lucide-react";
import { AnalysisProgressPanel } from "@/components/AnalysisProgressPanel";
import type { AnalysisProgressState } from "@/lib/workflow";

function buildSuggestions(rootFeature?: string | null) {
  const feature = rootFeature?.trim() || "the selected feature";
  return [
    `Analyze the ${feature} flow. Generate comprehensive tests focused on negative scenarios, historical bugs, and uncovered branches. Then identify coverage gaps and generate targeted tests for the highest-risk gaps.`,
    `Generate comprehensive QA coverage for ${feature}.`,
    `Generate exploratory testing scenarios for ${feature}.`,
    `What components are impacted if ${feature} changes?`,
    `Analyze coverage gaps for ${feature}.`,
    `Recommend regression tests after ${feature} changes.`,
  ];
}

function Expand({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-4 rounded-2xl border border-ink-700/10 bg-white/70">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-ink-900"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {title}
      </button>
      {open ? <div className="border-t border-ink-700/10 px-4 py-3">{children}</div> : null}
    </div>
  );
}

export function AnalysisComposer({
  busy,
  projectReady,
  emptyGraph,
  initialQuery,
  projectName,
  rootFeature,
  testOutputFormat,
  onTestOutputFormatChange,
  readiness,
  progress,
  onQuery,
  onOpenResults,
  onOpenTrace,
  hasResult,
}: {
  busy: boolean;
  projectReady: boolean;
  emptyGraph?: boolean;
  initialQuery?: string | null;
  projectName?: string | null;
  rootFeature?: string | null;
  testOutputFormat?: "standard" | "bdd" | "both";
  onTestOutputFormatChange?: (format: "standard" | "bdd" | "both") => void;
  readiness?: {
    flowReady: boolean;
    nodeCount: number;
    edgeCount: number;
    documentCount: number;
    featureName?: string | null;
  };
  progress?: AnalysisProgressState | null;
  onQuery: (query: string, changedNode?: string) => void;
  onOpenResults?: () => void;
  onOpenTrace?: () => void;
  hasResult?: boolean;
}) {
  const suggestions = useMemo(() => buildSuggestions(rootFeature), [rootFeature]);
  const [query, setQuery] = useState(initialQuery || suggestions[0]);
  const [changedNode, setChangedNode] = useState("");
  const format = testOutputFormat || "bdd";

  useEffect(() => {
    if (initialQuery) setQuery(initialQuery);
    else setQuery(suggestions[0]);
  }, [initialQuery, suggestions]);

  useEffect(() => {
    setChangedNode("");
  }, [rootFeature, projectName]);

  const testedLabel = projectReady
    ? `${projectName || "Project"} → ${rootFeature || "selected feature"}`
    : emptyGraph
      ? "Select or create a system-flow feature before analysis"
      : "Create a project and define a system flow to begin";

  function applySuggestion(s: string) {
    setQuery(s);
    if (rootFeature && s.toLowerCase().includes("changes")) {
      setChangedNode(rootFeature);
    }
  }

  return (
    <div className="panel p-6">
      <div className="label">Analysis composer</div>
      <h2 className="mt-1 font-display text-2xl text-ink-900">Run Agentic Analysis</h2>
      <p className="mt-1 text-sm text-ink-600/75">{testedLabel}</p>

      <textarea
        className="mt-5 min-h-36 w-full rounded-2xl border border-ink-700/15 bg-white/80 p-4 text-sm outline-none focus:border-pine-500"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        disabled={busy}
        aria-label="Analysis prompt"
        placeholder="Describe the QA analysis you want…"
      />

      <div className="mt-3 flex flex-wrap gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            className="rounded-full border border-ink-700/10 bg-mist-100 px-3 py-1.5 text-left text-xs text-ink-800 hover:bg-mist-200"
            onClick={() => applySuggestion(s)}
            disabled={busy}
          >
            {s.length > 64 ? `${s.slice(0, 64)}…` : s}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-2xl border border-ink-700/10 bg-white/70 p-3">
        <div className="label">Test case format</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {(
            [
              ["standard", "Standard"],
              ["bdd", "BDD / Gherkin"],
              ["both", "Both"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`rounded-full px-3 py-1 text-xs ${
                format === value ? "bg-pine-700 text-white" : "bg-mist-100 text-ink-700"
              }`}
              onClick={() => onTestOutputFormatChange?.(value)}
              disabled={busy}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <Expand title="Advanced options">
        <label className="block text-xs text-ink-600/70" htmlFor="changed-node">
          Changed node
        </label>
        <input
          id="changed-node"
          className="mt-1 w-full rounded-xl border border-ink-700/15 bg-white/80 px-3 py-2 text-sm outline-none focus:border-pine-500"
          placeholder="Optional changed node (e.g. Payment Service)"
          value={changedNode}
          onChange={(e) => setChangedNode(e.target.value)}
          disabled={busy}
        />
      </Expand>

      <button
        className="btn-primary mt-5"
        disabled={busy || !projectReady || !query.trim()}
        onClick={() => onQuery(query, changedNode || undefined)}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        Run Agentic Analysis
      </button>

      {progress && progress.status !== "idle" ? (
        <div className="mt-5">
          <AnalysisProgressPanel
            progress={progress}
            onOpenResults={onOpenResults}
            onOpenTrace={onOpenTrace}
          />
        </div>
      ) : busy ? (
        <div className="mt-5 flex items-center gap-3 rounded-2xl border border-pine-700/20 bg-pine-700/5 px-4 py-3 text-sm text-pine-800">
          <Loader2 className="h-4 w-4 animate-spin" />
          Starting agentic analysis…
        </div>
      ) : null}

      {readiness ? (
        <div className="mt-5 rounded-2xl border border-ink-700/10 bg-white/70 p-4 text-sm">
          <div className="text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
            Workflow readiness
          </div>
          <ul className="mt-2 space-y-1 text-ink-700/85">
            <li>
              System Flow: <strong>{readiness.flowReady ? "Ready" : "Missing"}</strong>
            </li>
            <li>
              Graph:{" "}
              <strong>
                {readiness.nodeCount} nodes, {readiness.edgeCount} edges
              </strong>
            </li>
            <li>
              Knowledge: <strong>{readiness.documentCount} documents indexed</strong>
            </li>
            <li>
              Selected feature: <strong>{readiness.featureName || "Not selected"}</strong>
            </li>
          </ul>
        </div>
      ) : null}

      {!projectReady && (
        <div className="mt-4 rounded-xl border border-brass-500/30 bg-brass-500/10 px-4 py-3 text-sm">
          {emptyGraph
            ? "No system flow defined yet. Open System Flow to add a root feature first."
            : "Create a project and define a feature in System Flow before running analysis."}
        </div>
      )}

      {hasResult && onOpenResults ? (
        <div className="mt-4">
          <button type="button" className="btn-secondary text-xs" onClick={onOpenResults}>
            Open Analysis Results
          </button>
        </div>
      ) : null}
    </div>
  );
}
