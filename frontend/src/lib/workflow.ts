import type { AppView, QACopilotResponse } from "./types";
import { primaryValidTests } from "./validTests";

/** Primary sidebar views (legacy output views redirect into Analysis Results). */
export type PrimaryAppView =
  | "home"
  | "flow"
  | "explorer"
  | "knowledge"
  | "copilot"
  | "results"
  | "trace";

export type ResultSection =
  | "overview"
  | "tests"
  | "automation"
  | "exploratory"
  | "bugs"
  | "regression"
  | "coverage"
  | "evidence";

export type NavGroupId = "overview" | "setup" | "analyze" | "observe";

export type NavItemDef = {
  id: PrimaryAppView;
  label: string;
  group: NavGroupId;
};

export const NAV_GROUPS: { id: NavGroupId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "setup", label: "Setup" },
  { id: "analyze", label: "Analyze" },
  { id: "observe", label: "Observability" },
];

export const WORKFLOW_NAV: NavItemDef[] = [
  { id: "home", label: "Home", group: "overview" },
  { id: "flow", label: "System Flow", group: "setup" },
  { id: "explorer", label: "Graph Explorer", group: "setup" },
  { id: "knowledge", label: "Knowledge Base", group: "setup" },
  { id: "copilot", label: "QA Copilot", group: "analyze" },
  { id: "results", label: "Analysis Results", group: "analyze" },
  { id: "trace", label: "Agent Trace", group: "observe" },
];

/** Legacy standalone output views → unified results section. */
export const LEGACY_VIEW_TO_SECTION: Partial<Record<AppView, ResultSection>> = {
  tests: "tests",
  automation: "automation",
  exploratory: "exploratory",
  bugs: "bugs",
  regression: "regression",
  coverage: "coverage",
  evidence: "evidence",
};

export const SECTION_QUERY_ALIASES: Record<string, ResultSection> = {
  overview: "overview",
  "test-cases": "tests",
  tests: "tests",
  automation: "automation",
  "automation-review": "automation",
  exploratory: "exploratory",
  missions: "exploratory",
  bugs: "bugs",
  "bug-reports": "bugs",
  regression: "regression",
  coverage: "coverage",
  evidence: "evidence",
  sources: "evidence",
};

export const RESULT_TABS: { id: ResultSection; label: string; shortLabel: string }[] = [
  { id: "overview", label: "Overview", shortLabel: "Overview" },
  { id: "tests", label: "Test Cases", shortLabel: "Tests" },
  { id: "automation", label: "Automation Review", shortLabel: "Automation" },
  { id: "exploratory", label: "Exploratory Missions", shortLabel: "Exploratory" },
  { id: "bugs", label: "Bug Reports", shortLabel: "Bugs" },
  { id: "regression", label: "Regression Recommendations", shortLabel: "Regression" },
  { id: "coverage", label: "Coverage", shortLabel: "Coverage" },
  { id: "evidence", label: "Sources & Evidence", shortLabel: "Evidence" },
];

export function isPrimaryView(view: AppView): view is PrimaryAppView {
  return WORKFLOW_NAV.some((item) => item.id === view);
}

export function resolveNavigation(
  view: AppView,
  section?: ResultSection | null
): { view: PrimaryAppView; section: ResultSection } {
  if (view === "results") {
    return { view: "results", section: section || "overview" };
  }
  const legacy = LEGACY_VIEW_TO_SECTION[view];
  if (legacy) {
    return { view: "results", section: legacy };
  }
  if (isPrimaryView(view)) {
    return { view, section: section || "overview" };
  }
  return { view: "home", section: section || "overview" };
}

export function parseSectionParam(raw: string | null | undefined): ResultSection {
  if (!raw) return "overview";
  const key = raw.trim().toLowerCase();
  return SECTION_QUERY_ALIASES[key] || "overview";
}

export function sectionToQueryParam(section: ResultSection): string {
  switch (section) {
    case "tests":
      return "test-cases";
    case "automation":
      return "automation";
    case "exploratory":
      return "exploratory";
    case "bugs":
      return "bugs";
    case "regression":
      return "regression";
    case "coverage":
      return "coverage";
    case "evidence":
      return "evidence";
    default:
      return "overview";
  }
}

export function resultTabCounts(result: QACopilotResponse | null): Record<ResultSection, number | null> {
  if (!result) {
    return {
      overview: null,
      tests: null,
      automation: null,
      exploratory: null,
      bugs: null,
      regression: null,
      coverage: null,
      evidence: null,
    };
  }
  const reviewed = result.reviewed_test_cases?.length ?? 0;
  const coverageGaps =
    (result.coverage_after?.gaps?.length ?? result.coverage?.uncovered_branches?.length ?? null);
  return {
    overview: null,
    tests: primaryValidTests(result).length,
    automation: reviewed || null,
    exploratory: result.exploratory_missions?.length ?? 0,
    bugs: result.bug_reports?.length ?? 0,
    regression: result.regression_recommendations?.length ?? 0,
    coverage: coverageGaps,
    evidence: result.evidence?.length ?? 0,
  };
}

/** Map real orchestrator stage names to user-facing progress labels. */
export function friendlyProgressLabel(stage: string): string {
  const s = stage.toLowerCase();
  if (s.includes("identify project") || s.includes("validating")) return "Validating project context";
  if (s.includes("reading system-flow") || s.includes("user flow graph loaded") || s.includes("root feature"))
    return "Reading system-flow graph";
  if (s.includes("retrieving project knowledge") || s.includes("classify intent") || s.includes("plan retrieval"))
    return "Retrieving project knowledge";
  if (s.includes("traverse") || s.includes("vector") || s.includes("fused") || s.includes("context fusion"))
    return "Fusing Graph RAG and Vector RAG context";
  if (s.includes("generating test") || s.includes("initial test") || s.includes("test cases generated"))
    return "Generating test cases";
  if (s.includes("critic")) return "Running critic and coverage analysis";
  if (s.includes("coverage gap") || s.includes("gap priorit")) return "Running critic and coverage analysis";
  if (s.includes("targeted")) return "Generating targeted tests";
  if (s.includes("test review") || s.includes("validity") || s.includes("quality pre-check"))
    return "Reviewing test validity";
  if (s.includes("automation")) return "Evaluating automation feasibility";
  if (s.includes("exploratory")) return "Generating exploratory missions";
  if (s.includes("bug report")) return "Generating bug reports";
  if (s.includes("regression")) return "Generating regression recommendations";
  if (s.includes("evidence")) return "Collecting sources and evidence";
  if (s.includes("final") || s.includes("bdd") || s.includes("format")) return "Finalizing analysis";
  return stage;
}

export const PROGRESS_MILESTONES = [
  "Validating project context",
  "Reading system-flow graph",
  "Retrieving project knowledge",
  "Fusing Graph RAG and Vector RAG context",
  "Generating test cases",
  "Running critic and coverage analysis",
  "Generating targeted tests",
  "Reviewing test validity",
  "Evaluating automation feasibility",
  "Generating exploratory missions",
  "Generating bug reports",
  "Generating regression recommendations",
  "Collecting sources and evidence",
  "Finalizing analysis",
] as const;

export type AnalysisProgressState = {
  status: "idle" | "queued" | "running" | "completed" | "failed";
  currentStage: string;
  currentStageLabel: string;
  completedStages: string[];
  completedLabels: string[];
  elapsedMs: number;
  message: string;
  startedAt: number | null;
};

export function createIdleProgress(): AnalysisProgressState {
  return {
    status: "idle",
    currentStage: "",
    currentStageLabel: "",
    completedStages: [],
    completedLabels: [],
    elapsedMs: 0,
    message: "",
    startedAt: null,
  };
}

export function applyProgressEvent(
  prev: AnalysisProgressState,
  event: { stage: string; message: string; meta?: Record<string, unknown> }
): AnalysisProgressState {
  const label = friendlyProgressLabel(event.stage);
  const metaStatus = String(event.meta?.status || "running");
  const rawCompleted = Array.isArray(event.meta?.completed_stages)
    ? (event.meta.completed_stages as string[])
    : prev.completedStages;
  const completedStages = [...rawCompleted];
  if (metaStatus !== "running" && event.stage && !completedStages.includes(event.stage)) {
    completedStages.push(event.stage);
  }
  const completedLabels = Array.from(
    new Set(completedStages.map((s) => friendlyProgressLabel(s)))
  );
  const elapsedMs =
    typeof event.meta?.elapsed_ms === "number" ? (event.meta.elapsed_ms as number) : prev.elapsedMs;
  return {
    ...prev,
    status: "running",
    currentStage: event.stage,
    currentStageLabel: label,
    completedStages,
    completedLabels,
    elapsedMs,
    message: event.message || prev.message,
    startedAt: prev.startedAt ?? Date.now(),
  };
}

export function progressRatio(progress: AnalysisProgressState): number | null {
  if (progress.status === "completed") return 1;
  if (progress.status !== "running" && progress.status !== "queued") return null;
  const hit = PROGRESS_MILESTONES.filter((m) => progress.completedLabels.includes(m)).length;
  if (hit === 0 && !progress.currentStageLabel) return null;
  const currentBonus = progress.currentStageLabel ? 0.35 : 0;
  const raw = (hit + currentBonus) / PROGRESS_MILESTONES.length;
  return Math.min(0.95, Math.max(0.05, raw));
}

export function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function containsLoadDemoCopy(text: string): boolean {
  return /load\s+demo\s+project/i.test(text);
}
