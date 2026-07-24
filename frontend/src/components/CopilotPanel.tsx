"use client";

import { useState } from "react";
import { Loader2, Send } from "lucide-react";
import type { QACopilotResponse } from "@/lib/types";

const SUGGESTIONS = [
  "Generate comprehensive QA coverage for Sign In.",
  "Generate exploratory testing scenarios for Google OAuth.",
  "What components are impacted if Google OAuth changes?",
  "Analyze coverage gaps for Sign In.",
  "Recommend regression tests after Enterprise SSO changes.",
];

export function CopilotPanel({
  busy,
  result,
  onQuery,
  projectReady,
}: {
  busy: boolean;
  result: QACopilotResponse | null;
  onQuery: (query: string, changedNode?: string) => void;
  projectReady: boolean;
}) {
  const [query, setQuery] = useState(SUGGESTIONS[0]);
  const [changedNode, setChangedNode] = useState("");

  return (
    <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="panel p-6">
        <div className="label">QA Copilot</div>
        <h2 className="mt-2 font-display text-2xl">Ask with system flow context</h2>
        <p className="mt-2 text-sm text-ink-700/75">
          The orchestrator loads your user-provided flow graph first, then fuses Graph RAG,
          Vector RAG, existing tests, and historical bugs.
        </p>

        {!projectReady && (
          <div className="mt-4 rounded-xl border border-brass-500/30 bg-brass-500/10 px-4 py-3 text-sm">
            Define or load a system flow graph before generating QA artifacts.
          </div>
        )}

        <textarea
          className="mt-5 min-h-28 w-full rounded-2xl border border-ink-700/15 bg-white/80 p-4 text-sm outline-none focus:border-pine-500"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <input
          className="mt-3 w-full rounded-xl border border-ink-700/15 bg-white/80 px-3 py-2 text-sm outline-none focus:border-pine-500"
          placeholder="Optional changed node (e.g. Google OAuth)"
          value={changedNode}
          onChange={(e) => setChangedNode(e.target.value)}
        />

        <div className="mt-4 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className="rounded-full border border-ink-700/10 bg-mist-100 px-3 py-1.5 text-xs text-ink-800 hover:bg-mist-200"
              onClick={() => setQuery(s)}
            >
              {s}
            </button>
          ))}
        </div>

        <button
          className="btn-primary mt-5"
          disabled={busy || !projectReady || !query.trim()}
          onClick={() => onQuery(query, changedNode || undefined)}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          Run agentic analysis
        </button>
      </div>

      <div className="panel p-6">
        <div className="label">Latest analysis</div>
        {!result ? (
          <p className="mt-3 text-sm text-ink-600/70">No analysis yet. Run a query to populate this panel.</p>
        ) : (
          <div className="mt-3 space-y-4">
            <div className="rounded-2xl bg-ink-900 px-4 py-4 text-mist-50">
              <div className="text-xs uppercase tracking-[0.14em] text-brass-400">QA Risk</div>
              <div className="mt-1 font-display text-3xl">{result.risk_level.toUpperCase()}</div>
              <div className="mt-2 text-sm text-mist-200">
                {result.root_feature} · {result.discovered_branches.length} branches ·{" "}
                {result.discovered_graph_paths.length} paths
                {result.graph_coverage != null ? ` · ${result.graph_coverage}% coverage` : ""}
              </div>
            </div>
            <pre className="overflow-auto rounded-2xl bg-mist-100 p-4 text-xs leading-relaxed text-ink-800">
              {result.narrative}
            </pre>
            {result.retrieval_plan && (
              <div className="text-sm text-ink-700/80">
                <div className="label mb-2">Retrieval plan</div>
                <p>{result.retrieval_plan.reason}</p>
              </div>
            )}
            {result.critical_gaps.length > 0 && (
              <div>
                <div className="label mb-2">Critical gaps</div>
                <ul className="space-y-1 text-sm">
                  {result.critical_gaps.map((g) => (
                    <li key={g}>• {g}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {result && (
        <div className="panel col-span-full p-6">
          <div className="label">Recommended tests with graph paths</div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {result.test_cases.slice(0, 8).map((tc) => (
              <article key={tc.test_case_id} className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-medium text-ink-900">{tc.title}</h3>
                  <span className="rounded-full bg-mist-100 px-2 py-0.5 text-[11px] uppercase tracking-wide">
                    {tc.priority}
                  </span>
                </div>
                <div className="mt-2 font-mono text-xs text-pine-700">
                  {tc.graph_path.join(" → ")}
                </div>
                <p className="mt-2 text-sm text-ink-700/75">{tc.graph_reasoning}</p>
                <div className="mt-3 text-xs text-ink-600/70">
                  Sources: {tc.source_references.join(" · ")} · Confidence: {tc.confidence}
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}