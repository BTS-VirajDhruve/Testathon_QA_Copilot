"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { QACopilotResponse } from "@/lib/types";

export function CoveragePanel({
  projectId,
  result,
}: {
  projectId: string;
  result: QACopilotResponse | null;
}) {
  const [coverage, setCoverage] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    api
      .coverage(projectId)
      .then((c) => setCoverage(c as unknown as Record<string, unknown>))
      .catch(() => setCoverage(null));
  }, [projectId, result]);

  const data = result?.coverage_after
    ? {
        overall_coverage: result.coverage_after.overall_coverage,
        branch_coverage: result.coverage_after.branch_coverage,
        uncovered_branches: result.coverage_after.uncovered_branches,
        critical_gaps: result.coverage_after.critical_gaps,
        calculation_notes: result.coverage_after.calculation_notes,
      }
    : result?.coverage || coverage;

  return (
    <section className="panel p-6">
      <div className="label">Coverage Analysis</div>
      <h2 className="mt-2 font-display text-2xl">Graph-based coverage gaps</h2>

      {result?.coverage_before || result?.coverage_after ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="text-xs uppercase tracking-[0.14em] text-ink-600/60">Before regeneration</div>
            <div className="mt-1 font-display text-3xl">
              {result.coverage_before?.coverage_percentage ?? "—"}%
            </div>
            <div className="mt-1 text-sm text-ink-700/70">
              {result.coverage_before
                ? `${result.coverage_before.covered_paths}/${result.coverage_before.total_paths} paths`
                : "—"}
            </div>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="text-xs uppercase tracking-[0.14em] text-ink-600/60">After regeneration</div>
            <div className="mt-1 font-display text-3xl">
              {result.coverage_after?.coverage_percentage ?? "—"}%
            </div>
            <div className="mt-1 text-sm text-ink-700/70">
              {result.coverage_after
                ? `${result.coverage_after.covered_paths}/${result.coverage_after.total_paths} paths`
                : "—"}
            </div>
          </div>
        </div>
      ) : null}

      {!data ? (
        <p className="mt-4 text-sm text-ink-600/70">No coverage data yet.</p>
      ) : (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <div className="rounded-2xl bg-ink-900 p-5 text-mist-50">
            <div className="text-xs uppercase tracking-[0.14em] text-brass-400">Overall</div>
            <div className="mt-2 font-display text-4xl">
              {String((data as { overall_coverage?: number }).overall_coverage ?? "—")}%
            </div>
            <div className="mt-2 text-sm text-mist-200">
              Branch {(data as { branch_coverage?: number }).branch_coverage}%
            </div>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">Uncovered branches</div>
            <ul className="space-y-1 text-sm">
              {((data as { uncovered_branches?: string[] }).uncovered_branches || []).map((b) => (
                <li key={b}>• {b}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">Critical gaps</div>
            <ul className="space-y-1 text-sm">
              {((data as { critical_gaps?: string[] }).critical_gaps || []).map((g) => (
                <li key={g}>• {g}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">How the score was calculated</div>
            <ul className="space-y-1 text-xs leading-relaxed text-ink-700/80">
              {((data as { calculation_notes?: string[] }).calculation_notes || []).map((n) => (
                <li key={n}>• {n}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}