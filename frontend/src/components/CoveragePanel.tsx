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
  }, [projectId, result]);

  const data: CoverageView | null = result?.coverage_after
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

      {error ? (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-signal-high/30 bg-signal-high/10 px-3 py-2 text-sm text-signal-high">
          <span>{error}</span>
          <button className="btn-secondary" onClick={load}>
            Retry
          </button>
        </div>
      ) : null}

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

      {loading && !data ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-ink-600/70">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading coverage…
        </div>
      ) : null}

      {!data && !loading ? (
        <p className="mt-4 text-sm text-ink-600/70">No coverage data yet. Run the Copilot or retry.</p>
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
              {(data.uncovered_branches || []).map((b) => (
                <li key={b}>• {b}</li>
              ))}
              {(data.uncovered_branches || []).length === 0 ? (
                <li className="text-ink-600/70">None reported</li>
              ) : null}
            </ul>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">Critical gaps</div>
            <ul className="space-y-1 text-sm">
              {(data.critical_gaps || []).map((g) => (
                <li key={g}>• {g}</li>
              ))}
              {(data.critical_gaps || []).length === 0 ? (
                <li className="text-ink-600/70">None reported</li>
              ) : null}
            </ul>
          </div>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label mb-2">How the score was calculated</div>
            <ul className="space-y-1 text-xs leading-relaxed text-ink-700/80">
              {(data.calculation_notes || []).map((n) => (
                <li key={n}>• {n}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </section>
  );
}
