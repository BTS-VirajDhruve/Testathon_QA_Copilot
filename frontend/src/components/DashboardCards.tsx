"use client";

import type { DashboardStats, Project } from "@/lib/types";

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-2xl border border-ink-700/10 bg-gradient-to-br from-white to-mist-100/80 p-4">
      <div className="label">{label}</div>
      <div className="mt-2 font-display text-2xl tracking-tight text-ink-900">{value}</div>
      {hint ? <div className="mt-1 text-xs text-ink-600/65">{hint}</div> : null}
    </div>
  );
}

export function DashboardCards({
  stats,
  project,
  onStatClick,
}: {
  stats: DashboardStats | null;
  project: Project | null;
  onStatClick?: (key: "tests" | "critical" | "gaps" | "bugs") => void;
}) {
  if (!stats) {
    return (
      <div className="text-sm text-ink-600/70">
        Load or create a project to see risk, coverage, and graph metrics.
      </div>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Risk level" value={stats.risk_level.toUpperCase()} hint={project?.name} />
      <Stat label="Graph coverage" value={`${stats.graph_coverage}%`} hint="Weighted path score" />
      <Stat label="Branch coverage" value={`${stats.branch_coverage}%`} />
      <button
        type="button"
        className="text-left disabled:cursor-default"
        onClick={() => onStatClick?.("tests")}
        disabled={!onStatClick}
      >
        <Stat
          label="Test cases"
          value={stats.test_case_count}
          hint={`${stats.critical_test_count} high/critical`}
        />
      </button>
      <button
        type="button"
        className="text-left disabled:cursor-default"
        onClick={() => onStatClick?.("bugs")}
        disabled={!onStatClick}
      >
        <Stat label="Historical bugs" value={stats.historical_bugs} />
      </button>
      <button
        type="button"
        className="text-left disabled:cursor-default"
        onClick={() => onStatClick?.("gaps")}
        disabled={!onStatClick}
      >
        <Stat
          label="Coverage gaps"
          value={stats.coverage_gaps.length}
          hint={stats.uncovered_branches.slice(0, 2).join(", ")}
        />
      </button>
      <Stat label="Graph nodes" value={stats.node_count} hint={`${stats.edge_count} edges`} />
      <Stat label="Confidence" value={stats.confidence.toUpperCase()} />
    </div>
  );
}
