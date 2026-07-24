"use client";

import type { CoverageGap, CoverageSnapshot, QACopilotResponse, TestCase } from "@/lib/types";
import { TestCaseEvidenceCard } from "@/components/TestCaseEvidenceCard";

function pct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n}%`;
}

function SnapshotCard({
  label,
  snap,
  testCount,
}: {
  label: string;
  snap?: CoverageSnapshot | null;
  testCount?: number;
}) {
  return (
    <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
      <div className="text-xs uppercase tracking-[0.14em] text-ink-600/60">{label}</div>
      <div className="mt-2 font-display text-3xl text-ink-900">
        {snap ? pct(snap.coverage_percentage) : "—"}
      </div>
      <div className="mt-2 space-y-1 text-sm text-ink-700/75">
        {snap ? (
          <>
            <div>
              Paths {snap.covered_paths}/{snap.total_paths}
            </div>
            <div>Overall graph {pct(snap.overall_coverage)}</div>
            <div>Important gaps {snap.gaps?.length ?? 0}</div>
          </>
        ) : (
          <div>No snapshot</div>
        )}
        {typeof testCount === "number" ? <div>Tests {testCount}</div> : null}
      </div>
    </div>
  );
}

function GapList({ title, gaps }: { title: string; gaps: CoverageGap[] }) {
  if (!gaps.length) {
    return (
      <div>
        <div className="label mb-2">{title}</div>
        <p className="text-sm text-ink-600/70">None</p>
      </div>
    );
  }
  return (
    <div>
      <div className="label mb-2">{title}</div>
      <ul className="space-y-2 text-sm">
        {gaps.map((g) => (
          <li key={g.gap_id} className="rounded-xl bg-mist-100/80 px-3 py-2">
            <div className="font-medium text-ink-900">{g.title}</div>
            <div className="mt-1 text-xs uppercase tracking-wide text-ink-600/65">
              {g.gap_type} · priority {g.priority} · risk {g.risk}
              {g.selected_for_regeneration ? " · selected" : ""}
            </div>
            {g.reason ? <div className="mt-1 text-xs text-ink-700/70">{g.reason}</div> : null}
            {g.graph_path?.length ? (
              <div className="mt-1 font-mono text-xs text-pine-700">{g.graph_path.join(" → ")}</div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

const STORY_STEPS = [
  "Initial analysis",
  "Critic review",
  "Coverage gaps",
  "Targeted tests",
  "Final coverage",
] as const;

export function RegenerationLoopPanel({ result }: { result: QACopilotResponse }) {
  const initialCount = result.initial_test_cases?.length ?? 0;
  const targeted = result.targeted_test_cases || [];
  const selected = result.selected_coverage_gaps || [];
  const unresolved = result.unresolved_gaps || [];
  const gapsFound = result.coverage_before?.gaps?.length ?? selected.length + unresolved.length;
  const duplicatesRemoved = result.duplicates_removed ?? 0;
  const remaining = unresolved.length;

  return (
    <section className="panel p-6">
      <div className="label">Agentic coverage loop</div>
      <h2 className="mt-2 font-display text-2xl">Initial → Critic → Gaps → Targeted → Final</h2>
      <p className="mt-2 text-sm text-ink-700/75">
        All metrics below are live API values from this run — nothing is hardcoded for the demo.
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-800">
        {STORY_STEPS.map((label, i) => (
          <span key={label} className="flex items-center gap-2">
            <span className="rounded-full bg-ink-900 px-3 py-1.5 text-mist-50">{label}</span>
            {i < STORY_STEPS.length - 1 ? <span aria-hidden className="text-ink-600/50">↓</span> : null}
          </span>
        ))}
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">1 · Initial</div>
          <div className="mt-1 font-display text-3xl">{initialCount}</div>
          <div className="text-sm text-mist-200">tests generated</div>
          <div className="mt-2 text-sm text-mist-200">
            Coverage {result.coverage_before ? pct(result.coverage_before.coverage_percentage) : "—"}
            {result.coverage_before
              ? ` · ${result.coverage_before.covered_paths}/${result.coverage_before.total_paths} paths`
              : ""}
          </div>
        </div>
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">2 · Critic / gaps</div>
          <div className="mt-1 font-display text-3xl">{gapsFound}</div>
          <div className="text-sm text-mist-200">gaps found</div>
          <div className="mt-2 text-sm text-mist-200">
            {selected.length} high-priority selected · {result.critic_notes?.length ?? 0} critic notes
          </div>
        </div>
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">3 · Targeted</div>
          <div className="mt-1 font-display text-3xl">{targeted.length}</div>
          <div className="text-sm text-mist-200">targeted tests</div>
          <div className="mt-2 text-sm text-mist-200">{duplicatesRemoved} duplicates removed</div>
        </div>
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">4 · Final</div>
          <div className="mt-1 font-display text-3xl">
            {result.coverage_after ? pct(result.coverage_after.coverage_percentage) : "—"}
          </div>
          <div className="text-sm text-mist-200">
            {result.test_cases?.length ?? 0} tests · {remaining} remaining gaps
          </div>
          <div className="mt-2 text-sm text-mist-200">
            {result.coverage_after
              ? `${result.coverage_after.covered_paths}/${result.coverage_after.total_paths} paths`
              : "—"}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <SnapshotCard label="Coverage before" snap={result.coverage_before} testCount={initialCount} />
        <SnapshotCard
          label="Coverage after"
          snap={result.coverage_after}
          testCount={result.test_cases?.length}
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-sm text-ink-700/80">
        <div>
          Regeneration rounds: <strong>{result.regeneration_rounds ?? 0}</strong>
        </div>
        <div>
          Remaining unresolved gaps: <strong>{remaining}</strong>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <GapList title="Selected high-priority gaps" gaps={selected} />
        <GapList title="Remaining unresolved gaps" gaps={unresolved} />
      </div>

      {targeted.length > 0 ? (
        <div className="mt-6">
          <div className="label mb-3">Critic-targeted tests · why they exist</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {targeted.map((tc: TestCase) => (
              <TestCaseEvidenceCard key={tc.test_case_id} tc={tc} emphasizeWhy />
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-6 text-sm text-ink-600/70">
          No targeted regeneration ran (no high-priority gaps, regeneration disabled, or duplicates
          only).
        </p>
      )}
    </section>
  );
}
