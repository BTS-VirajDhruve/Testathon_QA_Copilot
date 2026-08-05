"use client";

import {
  Activity,
  BookOpen,
  GitBranch,
  LayoutDashboard,
  Network,
  Sparkles,
} from "lucide-react";
import type { DashboardStats, HealthStatus, Project, QACopilotResponse, SystemFlowGraph } from "@/lib/types";
import type { PrimaryAppView, ResultSection } from "@/lib/workflow";
import { DashboardCards } from "@/components/DashboardCards";

type WorkflowStep = {
  id: PrimaryAppView;
  label: string;
  description: string;
  status: "ready" | "incomplete" | "not_started";
};

export function HomePanel({
  project,
  graph,
  dashboard,
  result,
  health,
  docsCount,
  onNavigate,
}: {
  project: Project | null;
  graph: SystemFlowGraph | null;
  dashboard: DashboardStats | null;
  result: QACopilotResponse | null;
  health: HealthStatus | null;
  docsCount?: number;
  onNavigate: (view: PrimaryAppView, section?: ResultSection, filters?: Record<string, string>) => void;
}) {
  const nodeCount = graph?.nodes.length ?? project?.node_count ?? 0;
  const edgeCount = graph?.edges.length ?? project?.edge_count ?? 0;
  const hasGraph = nodeCount > 0;
  const hasDocs = (docsCount ?? 0) > 0;
  const hasAnalysis = Boolean(result?.test_cases?.length);
  const rootFeature =
    graph?.nodes.find((n) => n.id === graph.root_node_id)?.name || result?.root_feature || null;

  const steps: WorkflowStep[] = [
    {
      id: "flow",
      label: "Build System Flow",
      description: "Author the system-flow graph for this project.",
      status: hasGraph ? "ready" : project ? "incomplete" : "not_started",
    },
    {
      id: "explorer",
      label: "Inspect Graph",
      description: "Explore nodes, edges, and critical paths.",
      status: hasGraph ? "ready" : "not_started",
    },
    {
      id: "knowledge",
      label: "Add Knowledge",
      description: "Ingest requirements and QA documents.",
      status: hasDocs ? "ready" : hasGraph ? "incomplete" : "not_started",
    },
    {
      id: "copilot",
      label: "Run QA Copilot",
      description: "Compose a prompt and generate evidence-backed tests.",
      status: hasAnalysis ? "ready" : hasGraph ? "incomplete" : "not_started",
    },
    {
      id: "results",
      label: "Review Analysis",
      description: "Inspect tests, automation review, and coverage.",
      status: hasAnalysis ? "ready" : "not_started",
    },
    {
      id: "trace",
      label: "Inspect Agent Trace",
      description: "Follow orchestrator stages and model routing.",
      status: result?.execution_trace?.length ? "ready" : "not_started",
    },
  ];

  return (
    <div className="space-y-5">
      <section className="panel overflow-hidden" aria-labelledby="home-title">
        <div className="border-b border-ink-700/10 px-6 py-5">
          <div className="label">Agentic QA Intelligence</div>
          <h1 id="home-title" className="mt-2 font-display text-3xl font-medium tracking-tight text-ink-900 md:text-4xl">
            Agentic QA Copilot
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-700/80 md:text-base">
            Understands your software via a system-flow graph + QA knowledge, then generates
            evidence-backed tests, finds high-risk gaps, and closes them with targeted regeneration.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-ink-700">
            {project ? (
              <span className="rounded-full bg-mist-100 px-3 py-1.5">
                Project: <strong className="text-ink-900">{project.name}</strong>
                {rootFeature ? ` · ${rootFeature}` : ""}
              </span>
            ) : (
              <span className="text-ink-600/70">Create a project to begin.</span>
            )}
            {health ? (
              <span className="rounded-full bg-mist-100 px-3 py-1.5">
                AI: {health.openai_client_ready || health.openai ? "ready" : "fallback"}
                {health.vector_store_mode ? ` · vectors ${health.vector_store_mode}` : ""}
              </span>
            ) : null}
          </div>
        </div>
        <div className="px-6 py-5">
          <DashboardCards
            stats={dashboard}
            project={project}
            onStatClick={(key) => {
              if (key === "tests" || key === "critical") {
                onNavigate("results", "tests", key === "critical" ? { priority: "high,critical" } : {});
              } else if (key === "gaps") {
                onNavigate("results", "coverage");
              } else if (key === "bugs") {
                onNavigate("results", "bugs");
              }
            }}
          />
        </div>
      </section>

      <section className="panel p-5" aria-labelledby="workflow-title">
        <h2 id="workflow-title" className="font-display text-xl text-ink-900">
          Workflow
        </h2>
        <p className="mt-1 text-sm text-ink-600/75">Follow the setup → analyze → observe sequence.</p>
        <ol className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {steps.map((step, idx) => (
            <li key={step.id}>
              <button
                type="button"
                onClick={() => onNavigate(step.id, step.id === "results" ? "overview" : undefined)}
                className="flex w-full flex-col rounded-2xl border border-ink-700/10 bg-white px-4 py-3 text-left transition hover:border-pine-700/30 hover:bg-mist-50"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] uppercase tracking-[0.14em] text-ink-600/55">
                    Step {idx + 1}
                  </span>
                  <StatusPill status={step.status} />
                </div>
                <div className="mt-2 font-medium text-ink-900">{step.label}</div>
                <p className="mt-1 text-xs leading-relaxed text-ink-600/75">{step.description}</p>
              </button>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="panel p-5">
          <h2 className="font-display text-xl text-ink-900">Latest analysis</h2>
          {result ? (
            <div className="mt-3 space-y-2 text-sm text-ink-800">
              <div>Feature: {result.root_feature || rootFeature || "—"}</div>
              <div>Tests: {result.test_cases?.length ?? 0}</div>
              <div>Bugs: {result.bug_reports?.length ?? 0}</div>
              <div>Regression: {result.regression_recommendations?.length ?? 0}</div>
              <div>
                Coverage:{" "}
                {result.coverage_after?.coverage_percentage ??
                  result.graph_coverage ??
                  "—"}
                {typeof (result.coverage_after?.coverage_percentage ?? result.graph_coverage) ===
                "number"
                  ? "%"
                  : ""}
              </div>
              <div>Format: {result.test_output_format || "standard"}</div>
              <button
                type="button"
                className="btn-secondary mt-3"
                onClick={() => onNavigate("results", "overview")}
              >
                <LayoutDashboard className="h-4 w-4" /> Open Analysis Results
              </button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-ink-600/70">No analysis yet for this project.</p>
          )}
        </div>

        <div className="panel p-5">
          <h2 className="font-display text-xl text-ink-900">Quick actions</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            <ActionBtn icon={GitBranch} label="Continue System Flow" onClick={() => onNavigate("flow")} />
            <ActionBtn icon={Network} label="Open Graph Explorer" onClick={() => onNavigate("explorer")} />
            <ActionBtn icon={BookOpen} label="Add Knowledge" onClick={() => onNavigate("knowledge")} />
            <ActionBtn icon={Sparkles} label="Run QA Analysis" onClick={() => onNavigate("copilot")} />
            <ActionBtn
              icon={LayoutDashboard}
              label="View Latest Results"
              onClick={() => onNavigate("results", "tests")}
            />
            <ActionBtn icon={Activity} label="Agent Trace" onClick={() => onNavigate("trace")} />
          </div>
          <p className="mt-4 text-xs text-ink-600/65">
            Graph: {nodeCount} nodes · {edgeCount} edges
            {docsCount != null ? ` · ${docsCount} documents` : ""}
          </p>
        </div>
      </section>
    </div>
  );
}

function StatusPill({ status }: { status: WorkflowStep["status"] }) {
  const label =
    status === "ready" ? "Ready" : status === "incomplete" ? "Incomplete" : "Not started";
  const cls =
    status === "ready"
      ? "bg-pine-700/10 text-pine-800"
      : status === "incomplete"
        ? "bg-amber-500/10 text-amber-800"
        : "bg-mist-100 text-ink-600";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase ${cls}`}>{label}</span>;
}

function ActionBtn({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof GitBranch;
  label: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className="btn-secondary text-xs" onClick={onClick}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
