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
  Network,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  TestTubes,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AppView,
  DashboardStats,
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
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready");

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

  useEffect(() => {
    (async () => {
      try {
        await api.health();
        const list = await refreshProjects();
        if (list[0]) await refreshProjectData(list[0].id);
        setStatus("Connected");
      } catch (err) {
        setError(err instanceof Error ? err.message : "API unavailable");
        setStatus("API offline");
      }
    })();
  }, [refreshProjects, refreshProjectData]);

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
      setStatus(`Demo seeded · ${seeded.nodes} nodes`);
      setView("flow");
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
    try {
      const response = await api.query({
        project_id: projectId,
        query,
        root_feature: graph?.nodes.find((n) => n.id === graph.root_node_id)?.name,
        changed_node: changedNode,
      });
      setResult(response);
      await refreshProjectData(projectId);
      setStatus(`Analysis complete · ${response.test_cases.length} tests`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveGraph(next: SystemFlowGraph) {
    if (!projectId) return;
    setBusy(true);
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
      />
      <div className="mx-auto flex max-w-[1600px] gap-5 px-5 pb-8 pt-5">
        <Sidebar items={NAV} view={view} onChange={setView} />
        <main className="min-w-0 flex-1 space-y-5">
          {error && (
            <div className="rounded-2xl border border-signal-high/30 bg-signal-high/10 px-4 py-3 text-sm text-signal-high">
              {error}
            </div>
          )}

          <section className="panel overflow-hidden">
            <div className="border-b border-ink-700/10 px-6 py-5">
              <div className="label">Agentic QA Intelligence</div>
              <h1 className="mt-2 font-display text-3xl font-medium tracking-tight text-ink-900 md:text-4xl">
                Agentic QA Copilot
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-700/80 md:text-base">
                Define the system flow first. Then generate evidence-backed tests, exploratory
                missions, impact analysis, and coverage gaps with Graph RAG + Vector RAG.
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

          {!projectId && (
            <div className="panel px-6 py-10 text-center">
              <LayoutDashboard className="mx-auto h-8 w-8 text-brass-500" />
              <h2 className="mt-3 font-display text-2xl">Start with a project</h2>
              <p className="mx-auto mt-2 max-w-lg text-sm text-ink-700/75">
                Create a project or load the Sign In demo to define a system flow graph before
                asking the copilot for QA artifacts.
              </p>
              <div className="mt-5 flex justify-center gap-3">
                <button className="btn-primary" onClick={handleCreateProject}>
                  Create project
                </button>
                <button className="btn-brass" onClick={handleSeed}>
                  <Search className="h-4 w-4" /> Load Sign In demo
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}