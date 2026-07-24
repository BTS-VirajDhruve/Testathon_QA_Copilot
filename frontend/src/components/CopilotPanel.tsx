"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Loader2, Send } from "lucide-react";
import type { QACopilotResponse } from "@/lib/types";
import { TestCaseEvidenceCard } from "@/components/TestCaseEvidenceCard";
import { RegenerationLoopPanel } from "@/components/RegenerationLoopPanel";

const DEMO_QUERY =
  "Analyze the Sign In flow. Generate comprehensive tests focused on security, negative scenarios, historical bugs, and uncovered branches. Then identify coverage gaps and generate targeted tests for the highest-risk gaps.";

const SUGGESTIONS = [
  DEMO_QUERY,
  "Generate comprehensive QA coverage for Sign In.",
  "Generate exploratory testing scenarios for Google OAuth.",
  "What components are impacted if Google OAuth changes?",
  "Analyze coverage gaps for Sign In.",
  "Recommend regression tests after Microsoft Enterprise SSO changes.",
];

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
    <div className="rounded-2xl border border-ink-700/10 bg-white/70">
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

export function CopilotPanel({
  busy,
  result,
  onQuery,
  projectReady,
  initialQuery,
}: {
  busy: boolean;
  result: QACopilotResponse | null;
  onQuery: (query: string, changedNode?: string) => void;
  projectReady: boolean;
  initialQuery?: string | null;
}) {
  const [query, setQuery] = useState(initialQuery || SUGGESTIONS[0]);
  const [changedNode, setChangedNode] = useState("");

  useEffect(() => {
    if (initialQuery) setQuery(initialQuery);
  }, [initialQuery]);

  const summary = useMemo(() => {
    if (!result) return null;
    const before = result.coverage_before?.coverage_percentage;
    const after = result.coverage_after?.coverage_percentage;
    return {
      tests: result.test_cases?.length ?? 0,
      initial: result.initial_test_cases?.length ?? 0,
      targeted: result.targeted_test_cases?.length ?? 0,
      gaps: result.selected_coverage_gaps?.length ?? 0,
      unresolved: result.unresolved_gaps?.length ?? 0,
      before,
      after,
      backend: result.generation_backend,
      criticNotes: result.critic_notes?.length ?? 0,
      fused: result.fused_context_summary,
    };
  }, [result]);

  function applySuggestion(s: string) {
    setQuery(s);
    if (s.toLowerCase().includes("google oauth changes")) {
      setChangedNode("Google OAuth");
    } else if (s.toLowerCase().includes("microsoft enterprise sso")) {
      setChangedNode("Microsoft Enterprise SSO");
    }
  }

  return (
    <section className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
      <div className="panel p-6">
        <div className="label">QA Copilot</div>
        <h2 className="mt-2 font-display text-2xl">Ask with system flow context</h2>
        <p className="mt-2 text-sm text-ink-700/75">
          One action runs the real pipeline: Graph RAG + Vector RAG → initial tests → critic →
          coverage gaps → targeted regeneration → final coverage.
        </p>

        {!projectReady && (
          <div className="mt-4 rounded-xl border border-brass-500/30 bg-brass-500/10 px-4 py-3 text-sm">
            Load the Demo Project or define a system flow graph before running the copilot.
          </div>
        )}

        {busy ? (
          <div className="mt-5 flex items-center gap-3 rounded-2xl border border-pine-700/20 bg-pine-700/5 px-4 py-3 text-sm text-pine-800">
            <Loader2 className="h-4 w-4 animate-spin" />
            Running agentic analysis — retrieval, generation, critic, and coverage loop…
          </div>
        ) : null}

        <textarea
          className="mt-5 min-h-32 w-full rounded-2xl border border-ink-700/15 bg-white/80 p-4 text-sm outline-none focus:border-pine-500"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={busy}
        />
        <input
          className="mt-3 w-full rounded-xl border border-ink-700/15 bg-white/80 px-3 py-2 text-sm outline-none focus:border-pine-500"
          placeholder="Optional changed node (e.g. Google OAuth)"
          value={changedNode}
          onChange={(e) => setChangedNode(e.target.value)}
          disabled={busy}
        />

        <div className="mt-4 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className="rounded-full border border-ink-700/10 bg-mist-100 px-3 py-1.5 text-left text-xs text-ink-800 hover:bg-mist-200"
              onClick={() => applySuggestion(s)}
              disabled={busy}
            >
              {s.length > 72 ? `${s.slice(0, 72)}…` : s}
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
          <p className="mt-3 text-sm text-ink-600/70">
            No analysis yet. Load the demo and run the suggested Sign In query.
          </p>
        ) : (
          <div className="mt-3 space-y-4">
            <div className="rounded-2xl bg-ink-900 px-4 py-4 text-mist-50">
              <div className="text-xs uppercase tracking-[0.14em] text-brass-400">QA Risk</div>
              <div className="mt-1 font-display text-3xl">{result.risk_level.toUpperCase()}</div>
              <div className="mt-2 text-sm text-mist-200">
                {result.root_feature} · {result.discovered_branches?.length ?? 0} branches ·{" "}
                {result.discovered_graph_paths?.length ?? 0} paths
                {result.graph_coverage != null ? ` · ${result.graph_coverage}% coverage` : ""}
              </div>
              {summary?.backend ? (
                <div className="mt-3 inline-flex rounded-full bg-white/10 px-2.5 py-1 text-[11px] uppercase tracking-wide">
                  Generation: {summary.backend === "openai" ? "OpenAI" : summary.backend.replaceAll("_", " ")}
                </div>
              ) : null}
            </div>

            {summary ? (
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-xl bg-mist-100/80 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Tests</div>
                  <div className="font-display text-xl">{summary.tests}</div>
                  <div className="text-xs text-ink-600/70">
                    {summary.initial} initial · {summary.targeted} targeted
                  </div>
                </div>
                <div className="rounded-xl bg-mist-100/80 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Coverage</div>
                  <div className="font-display text-xl">
                    {summary.before ?? "—"}% → {summary.after ?? "—"}%
                  </div>
                  <div className="text-xs text-ink-600/70">
                    {summary.gaps} high-priority gaps selected
                  </div>
                </div>
              </div>
            ) : null}

            <Expand title="Context used (Graph + Vector RAG)" defaultOpen>
              <ul className="space-y-1 text-sm text-ink-700/80">
                <li>• Feature: {result.fused_context_summary?.feature || result.root_feature || "—"}</li>
                <li>• Graph paths: {result.fused_context_summary?.flow_paths ?? result.discovered_graph_paths?.length ?? 0}</li>
                <li>• Vector hits: {result.fused_context_summary?.semantic_hits ?? 0}</li>
                <li>• Existing tests: {result.fused_context_summary?.existing_tests ?? 0}</li>
                <li>• Historical bugs: {result.fused_context_summary?.historical_bugs ?? 0}</li>
              </ul>
              {result.retrieval_plan?.reason ? (
                <p className="mt-2 text-xs text-ink-600/70">{result.retrieval_plan.reason}</p>
              ) : null}
            </Expand>

            <Expand title={`Critic findings (${result.critic_notes?.length ?? 0})`}>
              {(result.critic_notes || []).length ? (
                <ul className="space-y-1 text-sm">
                  {result.critic_notes.slice(0, 8).map((n) => (
                    <li key={n}>• {n}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-ink-600/70">No critic notes for this run.</p>
              )}
            </Expand>

            <Expand title="Narrative summary">
              <pre className="overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-ink-800">
                {result.narrative}
              </pre>
            </Expand>
          </div>
        )}
      </div>

      {result && (result.coverage_before || result.targeted_test_cases?.length || result.selected_coverage_gaps?.length) ? (
        <div className="col-span-full">
          <RegenerationLoopPanel result={result} />
        </div>
      ) : null}

      {result ? (
        <div className="panel col-span-full p-6">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <div className="label">Generated tests with evidence</div>
              <p className="mt-1 text-sm text-ink-700/70">
                Showing up to 8 cases. Open Test Cases for the full set.
              </p>
            </div>
            <div className="text-xs text-ink-600/70">
              {(result.test_cases || []).filter((t) => t.generation_method === "critic").length} critic-targeted
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {(result.test_cases || []).slice(0, 8).map((tc) => (
              <TestCaseEvidenceCard key={tc.test_case_id} tc={tc} />
            ))}
            {(result.test_cases || []).length === 0 ? (
              <p className="text-sm text-ink-600/70">No tests were generated for this query.</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
