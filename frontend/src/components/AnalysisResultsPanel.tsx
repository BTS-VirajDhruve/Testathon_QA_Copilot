"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Bug,
  Compass,
  FileWarning,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TestTubes,
} from "lucide-react";
import clsx from "clsx";
import type { QACopilotResponse } from "@/lib/types";
import { primaryValidTests } from "@/lib/validTests";
import {
  RESULT_TABS,
  resultTabCounts,
  sectionToQueryParam,
  type ResultSection,
} from "@/lib/workflow";
import { ArtifactLists } from "@/components/ArtifactLists";
import { AutomationReviewPanel } from "@/components/AutomationReviewPanel";
import { CoveragePanel } from "@/components/CoveragePanel";
import { CoverageClosurePanel } from "@/components/CoverageClosurePanel";
import { AnalysisProgressPanel } from "@/components/AnalysisProgressPanel";
import type { AnalysisProgressState } from "@/lib/workflow";
import {
  BddExportOverlays,
  BddExportTrigger,
  useBddExport,
} from "@/components/BddExportControls";

const SECTION_ICONS: Partial<Record<ResultSection, typeof TestTubes>> = {
  overview: Sparkles,
  tests: TestTubes,
  automation: Bot,
  exploratory: Compass,
  bugs: Bug,
  regression: RefreshCw,
  coverage: ShieldAlert,
  evidence: FileWarning,
};

function sectionStatusLabel(
  result: QACopilotResponse | null,
  key: string,
  count: number
): string {
  const st = result?.section_status?.[key]?.status;
  if (st === "failed") return "Failed";
  if (st === "skipped") return "Skipped";
  if (st === "empty") return "Empty";
  if (st === "running") return "Running";
  if (count > 0 || st === "success") return "Ready";
  return "Pending";
}

export function AnalysisResultsPanel({
  projectId,
  projectName,
  result,
  section,
  onSectionChange,
  progress,
  busy,
  onOpenCopilot,
  onOpenTrace,
  onRerun,
  onRefresh,
}: {
  projectId: string;
  projectName?: string | null;
  result: QACopilotResponse | null;
  section: ResultSection;
  onSectionChange: (section: ResultSection) => void;
  progress?: AnalysisProgressState | null;
  busy?: boolean;
  onOpenCopilot?: () => void;
  onOpenTrace?: () => void;
  onRerun?: () => void;
  onRefresh?: () => void;
}) {
  const counts = useMemo(() => resultTabCounts(result), [result]);
  const [mobileSection, setMobileSection] = useState(section);
  const bddExport = useBddExport(projectId, result);

  useEffect(() => {
    setMobileSection(section);
  }, [section]);

  const completedAt = result?.execution_trace?.length
    ? result.execution_trace[result.execution_trace.length - 1]?.timestamp
    : null;

  const overviewCards = [
    {
      id: "tests" as const,
      label: "Test Cases",
      value: primaryValidTests(result).length,
      hint: "Valid suite",
    },
    {
      id: "automation" as const,
      label: "Automatable",
      value: result?.automation_summary?.automate ?? result?.reviewed_test_cases?.length ?? 0,
      hint: "Automation review",
    },
    {
      id: "exploratory" as const,
      label: "Exploratory",
      value: result?.exploratory_missions?.length ?? 0,
      hint: sectionStatusLabel(result, "exploratory_scenarios", result?.exploratory_missions?.length ?? 0),
    },
    {
      id: "bugs" as const,
      label: "Bug Reports",
      value: result?.bug_reports?.length ?? 0,
      hint: sectionStatusLabel(result, "bug_reports", result?.bug_reports?.length ?? 0),
    },
    {
      id: "regression" as const,
      label: "Regression",
      value: result?.regression_recommendations?.length ?? 0,
      hint: sectionStatusLabel(
        result,
        "regression_recommendations",
        result?.regression_recommendations?.length ?? 0
      ),
    },
    {
      id: "evidence" as const,
      label: "Evidence",
      value: result?.evidence?.length ?? 0,
      hint: "Sources",
    },
  ];

  return (
    <section className="space-y-4">
      <div className="panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="label">Analysis Results</div>
            <h2 className="mt-2 font-display text-2xl text-ink-900">
              {projectName || "Project"}
              {result?.root_feature ? ` · ${result.root_feature}` : ""}
            </h2>
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-600/75">
              <span className="rounded-full bg-mist-100 px-2.5 py-1">
                Status:{" "}
                <strong className="text-ink-900">
                  {busy || progress?.status === "running"
                    ? "Running"
                    : result
                      ? "Completed"
                      : "No analysis"}
                </strong>
              </span>
              {completedAt ? (
                <span className="rounded-full bg-mist-100 px-2.5 py-1">
                  Updated:{" "}
                  {new Date(completedAt).toLocaleString("en-US", {
                    timeZone: "UTC",
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  })}{" "}
                  UTC
                </span>
              ) : null}
              {result?.confidence ? (
                <span className="rounded-full bg-mist-100 px-2.5 py-1">
                  Confidence: {result.confidence}
                </span>
              ) : null}
              {result?.generation_backend ? (
                <span className="rounded-full bg-mist-100 px-2.5 py-1">
                  Backend: {result.generation_backend.replaceAll("_", " ")}
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <BddExportTrigger exportApi={bddExport} />
            {onOpenCopilot ? (
              <button type="button" className="btn-secondary" onClick={onOpenCopilot}>
                Back to QA Copilot
              </button>
            ) : null}
            {onOpenTrace ? (
              <button type="button" className="btn-secondary" onClick={onOpenTrace}>
                <Activity className="h-4 w-4" /> Agent Trace
              </button>
            ) : null}
            {onRefresh ? (
              <button type="button" className="btn-secondary" onClick={onRefresh} disabled={busy}>
                <RefreshCw className="h-4 w-4" /> Refresh
              </button>
            ) : null}
            {onRerun ? (
              <button type="button" className="btn-primary" onClick={onRerun} disabled={busy}>
                <Sparkles className="h-4 w-4" /> Rerun
              </button>
            ) : null}
          </div>
        </div>

        {progress && progress.status !== "idle" ? (
          <div className="mt-4">
            <AnalysisProgressPanel
              progress={progress}
              onOpenTrace={onOpenTrace}
            />
          </div>
        ) : null}
      </div>

      <BddExportOverlays exportApi={bddExport} />

      <div className="panel sticky top-[4.5rem] z-20 overflow-hidden p-2 backdrop-blur-sm">
        <div
          className="hidden gap-1 overflow-x-auto md:flex"
          role="tablist"
          aria-label="Analysis result sections"
        >
          {RESULT_TABS.map((tab) => {
            const count = counts[tab.id];
            const selected = section === tab.id;
            const Icon = SECTION_ICONS[tab.id];
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                id={`results-tab-${tab.id}`}
                aria-controls={`results-panel-${tab.id}`}
                className={clsx(
                  "flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm transition",
                  selected ? "bg-ink-900 text-mist-50" : "text-ink-800 hover:bg-mist-100"
                )}
                onClick={() => onSectionChange(tab.id)}
              >
                {Icon ? <Icon className="h-3.5 w-3.5 opacity-80" aria-hidden /> : null}
                <span>{tab.shortLabel}</span>
                {count != null ? (
                  <span
                    className={clsx(
                      "rounded-full px-1.5 py-0.5 text-[10px]",
                      selected ? "bg-white/15" : "bg-mist-200 text-ink-700"
                    )}
                  >
                    {count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <div className="md:hidden">
          <label className="sr-only" htmlFor="results-section-select">
            Result section
          </label>
          <select
            id="results-section-select"
            className="w-full rounded-xl border border-ink-700/15 bg-white px-3 py-2 text-sm"
            value={mobileSection}
            onChange={(e) => {
              const next = e.target.value as ResultSection;
              setMobileSection(next);
              onSectionChange(next);
            }}
          >
            {RESULT_TABS.map((tab) => {
              const count = counts[tab.id];
              return (
                <option key={tab.id} value={tab.id}>
                  {tab.label}
                  {count != null ? ` (${count})` : ""}
                </option>
              );
            })}
          </select>
        </div>
      </div>

      <div
        role="tabpanel"
        id={`results-panel-${section}`}
        aria-labelledby={`results-tab-${section}`}
        data-section={sectionToQueryParam(section)}
      >
        {section === "overview" && (
          <div className="panel space-y-4 p-6">
            <div>
              <div className="label">Overview</div>
              <p className="mt-2 text-sm text-ink-700/80">
                {result
                  ? result.narrative || "Latest analysis summary for this project."
                  : "No analysis yet. Run QA Copilot to generate results."}
              </p>
            </div>

            {result ? (
              <>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {overviewCards.map((card) => (
                    <button
                      key={card.id}
                      type="button"
                      className="rounded-2xl border border-ink-700/10 bg-white/70 p-4 text-left transition hover:border-pine-700/30"
                      onClick={() => onSectionChange(card.id)}
                    >
                      <div className="text-[11px] uppercase tracking-wide text-ink-600/60">
                        {card.label}
                      </div>
                      <div className="mt-1 font-display text-2xl">{card.value}</div>
                      <div className="mt-1 text-xs text-ink-600/70">{card.hint}</div>
                    </button>
                  ))}
                </div>

                <CoverageClosurePanel
                  result={result}
                  projectId={projectId}
                  onResumed={onRefresh}
                />

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl bg-mist-100/80 px-4 py-3 text-sm">
                    <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Coverage</div>
                    <div className="mt-1 font-display text-xl">
                      {result.coverage_after?.coverage_percentage ??
                        result.coverage?.overall_coverage ??
                        result.graph_coverage ??
                        "—"}
                      {(result.coverage_after?.coverage_percentage != null ||
                        result.coverage?.overall_coverage != null ||
                        result.graph_coverage != null) &&
                        "%"}
                    </div>
                    <button
                      type="button"
                      className="mt-2 text-xs text-pine-700 underline"
                      onClick={() => onSectionChange("coverage")}
                    >
                      View Coverage
                    </button>
                  </div>
                  <div className="rounded-2xl bg-mist-100/80 px-4 py-3 text-sm">
                    <div className="text-[11px] uppercase tracking-wide text-ink-600/60">
                      Model routing
                    </div>
                    {result.model_routing ? (
                      <div className="mt-1 space-y-1 text-xs text-ink-700/80">
                        <div>Model: {result.model_routing.actual_model_used || result.model_routing.selected_model || "—"}</div>
                        <div>Complexity: {result.model_routing.complexity || "—"}</div>
                        <div>
                          Fallback: {result.model_routing.fallback_used ? "yes" : "no"}
                          {result.generation_backend === "deterministic_fallback" ? " · demo fallback" : ""}
                        </div>
                      </div>
                    ) : (
                      <div className="mt-1 text-xs text-ink-600/70">Unavailable for this analysis.</div>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {(
                    [
                      ["tests", "View Test Cases"],
                      ["automation", "View Automation Review"],
                      ["bugs", "View Bugs"],
                      ["regression", "View Regression"],
                      ["coverage", "View Coverage"],
                      ["evidence", "View Evidence"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className="btn-secondary text-xs"
                      onClick={() => onSectionChange(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-ink-600/70">
                Run agentic analysis from QA Copilot. Partial sections appear here as they complete.
              </p>
            )}
          </div>
        )}

        {section === "tests" && (
          <ArtifactLists
            view="tests"
            result={result}
            projectId={projectId}
            bddExport={bddExport}
            onRefresh={onRefresh}
          />
        )}
        {section === "automation" && projectId && (
          <AutomationReviewPanel result={result} projectId={projectId} />
        )}
        {section === "exploratory" && (
          <ArtifactLists view="exploratory" result={result} projectId={projectId} />
        )}
        {section === "bugs" && (
          <ArtifactLists view="bugs" result={result} projectId={projectId} />
        )}
        {section === "regression" && (
          <ArtifactLists view="regression" result={result} projectId={projectId} />
        )}
        {section === "coverage" && projectId && (
          <CoveragePanel projectId={projectId} result={result} />
        )}
        {section === "evidence" && (
          <ArtifactLists view="evidence" result={result} projectId={projectId} />
        )}
      </div>
    </section>
  );
}
