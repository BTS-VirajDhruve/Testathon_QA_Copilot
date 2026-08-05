"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { QACopilotResponse } from "@/lib/types";

type CoverageView = {
  overall_coverage?: number;
  branch_coverage?: number;
  uncovered_branches?: string[];
  critical_gaps?: string[];
  calculation_notes?: string[];
};

function normalizeGap(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function uniqueStrings(values: string[] | undefined | null): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values || []) {
    const key = normalizeGap(value);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(value.trim());
  }
  return out;
}

export function CoveragePanel({
  projectId,
  result,
}: {
  projectId: string;
  result: QACopilotResponse | null;
}) {
  const [coverage, setCoverage] = useState<CoverageView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setCoverage(null);
    try {
      const c = await api.coverage(projectId);
      setCoverage(c);
    } catch (err) {
      setCoverage(null);
      setError(err instanceof Error ? err.message : "Failed to load coverage");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, result]);

  const resultForProject =
    result && (!result.project_id || result.project_id === projectId) ? result : null;

  const data: CoverageView | null = resultForProject?.coverage_after
    ? {
        overall_coverage: resultForProject.coverage_after.overall_coverage,
        branch_coverage: resultForProject.coverage_after.branch_coverage,
        uncovered_branches: uniqueStrings(resultForProject.coverage_after.uncovered_branches),
        critical_gaps: uniqueStrings(resultForProject.coverage_after.critical_gaps),
        calculation_notes: uniqueStrings(resultForProject.coverage_after.calculation_notes),
      }
    : resultForProject?.coverage
      ? {
          ...resultForProject.coverage,
          uncovered_branches: uniqueStrings(resultForProject.coverage.uncovered_branches),
          critical_gaps: uniqueStrings(resultForProject.coverage.critical_gaps),
          calculation_notes: uniqueStrings(resultForProject.coverage.calculation_notes),
        }
      : coverage
        ? {
            ...coverage,
            uncovered_branches: uniqueStrings(coverage.uncovered_branches),
            critical_gaps: uniqueStrings(coverage.critical_gaps),
            calculation_notes: uniqueStrings(coverage.calculation_notes),
          }
        : null;

  return (
    <section className="panel p-6">
      <div className="label">Coverage Analysis</div>
      <h2 className="mt-2 font-display text-2xl">Graph-based coverage gaps</h2>

      {error ? (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-signal-high/30 bg-signal-high/10 px-3 py-2 text-sm text-signal-high">
          <span>{error}</span>
          <button className="btn-secondary" onClick={load}>
            Retry
          </button>
        </div>
      ) : null}

      {resultForProject?.coverage_before || resultForProject?.coverage_after ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="text-xs uppercase tracking-[0.14em] text-ink-600/60">Before regeneration</div>
            <div className="mt-1 font-display text-3xl">
              {resultForProject.coverage_before?.coverage_percentage ?? "—"}%
            </div>
            <div className="mt-1 text-sm text-ink-700/70">
              {resultForProject.coverage_before
                ? `${resultForProject.coverage_before.covered_paths}/${resultForProject.coverage_before.total_paths} paths`
                : "—"}
            </div>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="text-xs uppercase tracking-[0.14em] text-ink-600/60">After regeneration</div>
            <div className="mt-1 font-display text-3xl">
              {resultForProject.coverage_after?.coverage_percentage ?? "—"}%
            </div>
            <div className="mt-1 text-sm text-ink-700/70">
              {resultForProject.coverage_after
                ? `${resultForProject.coverage_after.covered_paths}/${resultForProject.coverage_after.total_paths} paths`
                : "—"}
            </div>
          </div>
        </div>
      ) : null}

      {loading && !data ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-ink-600/70">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading coverage…
        </div>
      ) : null}

      {!data && !loading ? (
        <p className="mt-4 text-sm text-ink-600/70">
          Coverage unavailable until a graph and tests exist for this project.
        </p>
      ) : data ? (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <div className="rounded-2xl bg-ink-900 p-5 text-mist-50">
            <div className="text-xs uppercase tracking-[0.14em] text-brass-400">Overall</div>
            <div className="mt-2 font-display text-4xl">{String(data.overall_coverage ?? "—")}%</div>
            <div className="mt-2 text-sm text-mist-200">Branch {data.branch_coverage}%</div>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">Uncovered branches</div>
            <ul className="space-y-1 text-sm">
              {(data.uncovered_branches || []).map((b, index) => (
                <li key={`${normalizeGap(b)}-${index}`}>• {b}</li>
              ))}
              {(data.uncovered_branches || []).length === 0 ? (
                <li className="text-ink-600/70">None reported</li>
              ) : null}
            </ul>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">Critical gaps</div>
            <ul className="space-y-1 text-sm">
              {(data.critical_gaps || []).map((g, index) => (
                <li key={`${normalizeGap(g)}-${index}`}>• {g}</li>
              ))}
              {(data.critical_gaps || []).length === 0 ? (
                <li className="text-ink-600/70">None reported</li>
              ) : null}
            </ul>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">How the score was calculated</div>
            <ul className="space-y-1 text-xs leading-relaxed text-ink-700/80">
              {(data.calculation_notes || []).map((n, index) => (
                <li key={`${normalizeGap(n)}-${index}`}>• {n}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </section>
  );
}
