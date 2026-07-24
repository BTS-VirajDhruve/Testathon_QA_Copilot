"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BookOpen,
  Bug,
  Compass,
  FileWarning,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Network,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  TestTubes,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AppView,
  DashboardStats,
  HealthStatus,
  Project,
  QACopilotResponse,
  SystemFlowGraph,
} from "@/lib/types";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { DashboardCards } from "@/components/DashboardCards";
import { FlowBuilder } from "@/components/FlowBuilder";
import { GraphExplorer } from "@/components/GraphExplorer";
import { CopilotPanel } from "@/components/CopilotPanel";
import { TracePanel } from "@/components/TracePanel";
import { ArtifactLists } from "@/components/ArtifactLists";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { CoveragePanel } from "@/components/CoveragePanel";

const NAV: { id: AppView; label: string; icon: typeof Sparkles }[] = [
  { id: "copilot", label: "QA Copilot", icon: Sparkles },
  { id: "flow", label: "System Flow", icon: GitBranch },
  { id: "explorer", label: "Graph Explorer", icon: Network },
  { id: "knowledge", label: "Knowledge Base", icon: BookOpen },
  { id: "tests", label: "Test Cases", icon: TestTubes },
  { id: "exploratory", label: "Exploratory", icon: Compass },
  { id: "bugs", label: "Bug Reports", icon: Bug },
  { id: "regression", label: "Regression", icon: RefreshCw },
  { id: "coverage", label: "Coverage", icon: ShieldAlert },
  { id: "trace", label: "Agent Trace", icon: Activity },
  { id: "evidence", label: "Sources & Evidence", icon: FileWarning },
];

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [view, setView] = useState<AppView>("copilot");
  const [graph, setGraph] = useState<SystemFlowGraph | null>(null);
  const [dashboard, setDashboard] = useState<DashboardStats | null>(null);
  const [result, setResult] = useState<QACopilotResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Connecting…");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [demoQuery, setDemoQuery] = useState<string | null>(null);
  const [lastQuery, setLastQuery] = useState<{ query: string; changedNode?: string } | null>(null);

  const selectedProject = useMemo(
    () => projects.find((p) => p.id === projectId) || null,
    [projects, projectId]
  );

  const refreshProjects = useCallback(async () => {
    const list = await api.listProjects();
    setProjects(list);
    if (!projectId && list[0]) setProjectId(list[0].id);
    return list;
  }, [projectId]);

  const refreshProjectData = useCallback(async (id: string) => {
    const [flow, dash] = await Promise.all([api.getFlow(id), api.dashboard(id)]);
    setGraph(flow);
    setDashboard(dash);
  }, []);

  const connect = useCallback(async () => {
    setBooting(true);
    setError(null);
    try {
      const h = await api.health();
      setHealth(h);
      const list = await refreshProjects();
      if (list[0]) await refreshProjectData(list[0].id);
      setStatus(
        h.openai_client_ready
          ? "Connected · OpenAI ready"
          : "Connected · Deterministic fallback"
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "API unavailable");
      setStatus("API offline");
    } finally {
      setBooting(false);
    }
  }, [refreshProjects, refreshProjectData]);

  useEffect(() => {
    connect();
  }, [connect]);

  useEffect(() => {
    if (!projectId) return;
    refreshProjectData(projectId).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load project")
    );
  }, [projectId, refreshProjectData]);

  async function handleSeed() {
    setBusy(true);
    setError(null);
    try {
      const seeded = await api.seedDemo();
      await refreshProjects();
      setProjectId(seeded.project_id);
      await refreshProjectData(seeded.project_id);
      setDemoQuery(seeded.demo_query);
      setResult(null);
      setStatus(
        `Demo ready · ${seeded.project_name} · ${seeded.nodes} nodes${
          seeded.reused_project ? " · reused" : ""
        }`
      );
      // Demo journey: land on Copilot with the curated query ready
      setView("copilot");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Seed failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateProject() {
    const name = window.prompt("Project name", "New QA Project");
    if (!name) return;
    const root = window.prompt("Root feature", "Sign In") || "Feature";
    setBusy(true);
    try {
      const project = await api.createProject({
        name,
        description: "Created from Agentic QA Copilot",
        root_feature: root,
      });
      await refreshProjects();
      setProjectId(project.id);
      setView("flow");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleQuery(query: string, changedNode?: string) {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    setView("copilot");
    setLastQuery({ query, changedNode });
    try {
      const response = await api.query({
        project_id: projectId,
        query,
        root_feature: graph?.nodes.find((n) => n.id === graph.root_node_id)?.name,
        changed_node: changedNode,
        include_critic: true,
        enable_targeted_regeneration: true,
        max_regeneration_rounds: 1,
      });
      setResult(response);
      await refreshProjectData(projectId);
      const backend =
        response.generation_backend === "openai"
          ? "OpenAI"
          : response.generation_backend === "deterministic_fallback"
            ? "fallback"
            : response.generation_backend || "mixed";
      setStatus(
        `Analysis complete · ${response.test_cases.length} tests · ${backend}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveGraph(next: SystemFlowGraph) {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveFlow(projectId, { ...next, project_id: projectId });
      setGraph(saved);
      const dash = await api.dashboard(projectId);
      setDashboard(dash);
      setStatus(`Graph saved · v${saved.version}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-hero-wash">
      <TopBar
        projects={projects}
        projectId={projectId}
        onProjectChange={setProjectId}
        onCreateProject={handleCreateProject}
        onSeed={handleSeed}
        status={status}
        busy={busy}
        health={health}
      />
      <div className="mx-auto flex max-w-[1600px] gap-5 px-5 pb-8 pt-5">
        <Sidebar items={NAV} view={view} onChange={setView} />
        <main className="min-w-0 flex-1 space-y-5">
          {error && (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-signal-high/30 bg-signal-high/10 px-4 py-3 text-sm text-signal-high">
              <span className="flex-1">{error}</span>
              <button
                className="btn-secondary"
                onClick={() => {
                  if (lastQuery) handleQuery(lastQuery.query, lastQuery.changedNode);
                  else connect();
                }}
              >
                <RefreshCw className="h-4 w-4" /> Retry
              </button>
              <button className="rounded-full p-1 hover:bg-white/40" onClick={() => setError(null)}>
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          {booting ? (
            <div className="panel flex items-center gap-3 px-6 py-8 text-sm text-ink-700/80">
              <Loader2 className="h-5 w-5 animate-spin text-pine-700" />
              Connecting to Agentic QA Copilot API…
            </div>
          ) : null}

          <section className="panel overflow-hidden">
            <div className="border-b border-ink-700/10 px-6 py-5">
              <div className="label">Agentic QA Intelligence</div>
              <h1 className="mt-2 font-display text-3xl font-medium tracking-tight text-ink-900 md:text-4xl">
                Agentic QA Copilot
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-700/80 md:text-base">
                Load the Enterprise Authentication Portal demo, inspect the Sign In system flow,
                then run one Copilot action for evidence-backed tests, critic gaps, and targeted
                regeneration.
              </p>
            </div>
            <div className="px-6 py-5">
              <DashboardCards stats={dashboard} project={selectedProject} />
            </div>
          </section>

          {view === "copilot" && (
            <CopilotPanel
              busy={busy}
              result={result}
              onQuery={handleQuery}
              projectReady={Boolean(projectId && graph?.nodes.length)}
              initialQuery={demoQuery}
            />
          )}
          {view === "flow" && graph && projectId && (
            <FlowBuilder
              graph={graph}
              busy={busy}
              projectId={projectId}
              onChange={setGraph}
              onSave={handleSaveGraph}
              onImported={async () => refreshProjectData(projectId)}
            />
          )}
          {view === "flow" && projectId && !graph && (
            <div className="panel px-6 py-8 text-sm text-ink-600/70">Loading system flow…</div>
          )}
          {view === "explorer" && graph && projectId && (
            <GraphExplorer projectId={projectId} graph={graph} />
          )}
          {view === "knowledge" && projectId && <KnowledgePanel projectId={projectId} />}
          {(view === "tests" ||
            view === "exploratory" ||
            view === "bugs" ||
            view === "regression" ||
            view === "evidence") && (
            <ArtifactLists view={view} result={result} projectId={projectId} />
          )}
          {view === "coverage" && projectId && (
            <CoveragePanel projectId={projectId} result={result} />
          )}
          {view === "trace" && <TracePanel result={result} />}

          {!projectId && !booting && (
            <div className="panel px-6 py-10 text-center">
              <LayoutDashboard className="mx-auto h-8 w-8 text-brass-500" />
              <h2 className="mt-3 font-display text-2xl">Start with the demo journey</h2>
              <p className="mx-auto mt-2 max-w-lg text-sm text-ink-700/75">
                Load Enterprise Authentication Portal to get a Sign In system flow, requirements,
                historical bugs, and existing tests — then run the QA Copilot.
              </p>
              <div className="mt-5 flex justify-center gap-3">
                <button className="btn-primary" onClick={handleCreateProject} disabled={busy}>
                  Create project
                </button>
                <button className="btn-brass" onClick={handleSeed} disabled={busy}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  Load Demo Project
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
