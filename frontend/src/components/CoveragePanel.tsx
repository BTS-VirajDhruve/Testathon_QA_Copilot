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

  const data = result?.coverage || coverage;

  return (
    <section className="panel p-6">
      <div className="label">Coverage Analysis</div>
      <h2 className="mt-2 font-display text-2xl">Graph-based coverage gaps</h2>
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