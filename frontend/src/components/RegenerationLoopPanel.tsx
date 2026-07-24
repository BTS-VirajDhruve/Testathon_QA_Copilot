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
            <div>Gaps listed {snap.gaps?.length ?? 0}</div>
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
              {g.gap_type} · {g.priority} · risk {g.risk}
              {g.selected_for_regeneration ? " · selected" : ""}
            </div>
            {g.graph_path?.length ? (
              <div className="mt-1 font-mono text-xs text-pine-700">{g.graph_path.join(" → ")}</div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RegenerationLoopPanel({ result }: { result: QACopilotResponse }) {
  const initialCount = result.initial_test_cases?.length ?? 0;
  const targeted = result.targeted_test_cases || [];
  const selected = result.selected_coverage_gaps || [];
  const unresolved = result.unresolved_gaps || [];
  const gapsFound =
    result.coverage_before?.gaps?.length ??
    selected.length + unresolved.length;

  return (
    <section className="panel p-6">
      <div className="label">Critic → Coverage Gap → Targeted Regeneration</div>
      <h2 className="mt-2 font-display text-2xl">Bounded improvement loop</h2>
      <p className="mt-2 text-sm text-ink-700/75">
        Initial generation is reviewed by the critic, high-priority gaps are selected
        deterministically, and only missing tests are regenerated — never the full suite.
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-700/70">
        <span className="rounded-full bg-mist-100 px-3 py-1">Initial coverage</span>
        <span aria-hidden>↓</span>
        <span className="rounded-full bg-mist-100 px-3 py-1">Critic found gaps</span>
        <span aria-hidden>↓</span>
        <span className="rounded-full bg-mist-100 px-3 py-1">AI targeted tests</span>
        <span aria-hidden>↓</span>
        <span className="rounded-full bg-mist-100 px-3 py-1">Final coverage</span>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">Initial tests</div>
          <div className="mt-1 font-display text-3xl">{initialCount}</div>
        </div>
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">Gaps found</div>
          <div className="mt-1 font-display text-3xl">{gapsFound}</div>
        </div>
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">High-priority selected</div>
          <div className="mt-1 font-display text-3xl">{selected.length}</div>
        </div>
        <div className="rounded-2xl bg-ink-900 p-4 text-mist-50">
          <div className="text-xs uppercase tracking-[0.14em] text-brass-400">Targeted tests</div>
          <div className="mt-1 font-display text-3xl">{targeted.length}</div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <SnapshotCard
          label="Initial coverage"
          snap={result.coverage_before}
          testCount={initialCount}
        />
        <SnapshotCard
          label="Final coverage"
          snap={result.coverage_after}
          testCount={result.test_cases?.length}
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-sm text-ink-700/80">
        <div>
          Regeneration rounds: <strong>{result.regeneration_rounds ?? 0}</strong>
        </div>
        <div>
          Final test count: <strong>{result.test_cases?.length ?? 0}</strong>
        </div>
        <div>
          Unresolved gaps: <strong>{unresolved.length}</strong>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <GapList title="Selected coverage gaps" gaps={selected} />
        <GapList title="Remaining unresolved gaps" gaps={unresolved} />
      </div>

      {targeted.length > 0 ? (
        <div className="mt-6">
          <div className="label mb-3">Critic-targeted tests</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {targeted.map((tc: TestCase) => (
              <TestCaseEvidenceCard key={tc.test_case_id} tc={tc} />
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-6 text-sm text-ink-600/70">
          No targeted regeneration ran (no high-priority gaps, regeneration disabled, or
          duplicates only).
        </p>
      )}
    </section>
  );
}
