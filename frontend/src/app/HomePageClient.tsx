"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  BookOpen,
  GitBranch,
  Home,
  LayoutDashboard,
  Loader2,
  Network,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { API_URL, api } from "@/lib/api";
import type {
  DashboardStats,
  HealthStatus,
  Project,
  QACopilotResponse,
  SystemFlowGraph,
} from "@/lib/types";
import {
  WORKFLOW_NAV,
  applyProgressEvent,
  createIdleProgress,
  type AnalysisProgressState,
  type PrimaryAppView,
  type ResultSection,
} from "@/lib/workflow";
import {
  type AppLocation,
  buildAppUrl,
  parseAppLocation,
} from "@/lib/navigation";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { FlowBuilder } from "@/components/FlowBuilder";
import { GraphExplorer } from "@/components/GraphExplorer";
import { CopilotPanel } from "@/components/CopilotPanel";
import { TracePanel } from "@/components/TracePanel";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { AnalysisResultsPanel } from "@/components/AnalysisResultsPanel";
import { HomePanel } from "@/components/HomePanel";
import { PageHeader } from "@/components/PageHeader";

const NAV_ICONS = {
  home: Home,
  flow: GitBranch,
  explorer: Network,
  knowledge: BookOpen,
  copilot: Sparkles,
  results: LayoutDashboard,
  trace: Activity,
} as const;

const NAV = WORKFLOW_NAV.map((item) => ({
  ...item,
  icon: NAV_ICONS[item.id as keyof typeof NAV_ICONS] || LayoutDashboard,
}));

/** Keeps React location in sync with the URL after hydration (back/forward, soft nav). */
function LocationSync({ onLocation }: { onLocation: (next: AppLocation) => void }) {
  const searchParams = useSearchParams();
  useEffect(() => {
    onLocation(
      parseAppLocation({
        view: searchParams.get("view"),
        section: searchParams.get("section") ?? searchParams.get("results"),
        testId: searchParams.get("testId"),
      })
    );
  }, [onLocation, searchParams]);
  return null;
}

export function HomePageClient({ initialLocation }: { initialLocation: AppLocation }) {
  const router = useRouter();
  const pathname = usePathname() || "/";

  /** Seeded from the server-parsed URL so SSR HTML matches the first client render. */
  const [location, setLocation] = useState<AppLocation>(initialLocation);
  const view = location.view;
  const resultSection = location.section;

  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [graph, setGraph] = useState<SystemFlowGraph | null>(null);
  const [dashboard, setDashboard] = useState<DashboardStats | null>(null);
  const [result, setResult] = useState<QACopilotResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [projectLoading, setProjectLoading] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Connecting…");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [lastQuery, setLastQuery] = useState<{ query: string; changedNode?: string } | null>(null);
  const [testOutputFormat, setTestOutputFormat] = useState<"standard" | "bdd" | "both">("bdd");
  const [documentCount, setDocumentCount] = useState(0);
  const [progress, setProgress] = useState<AnalysisProgressState>(createIdleProgress());

  const loadTokenRef = useRef(0);
  const projectIdRef = useRef(projectId);
  const locationRef = useRef(location);
  const analysisAbortRef = useRef<AbortController | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  projectIdRef.current = projectId;
  locationRef.current = location;

  const applyLocation = useCallback((next: AppLocation) => {
    setLocation((prev) => {
      if (
        prev.view === next.view &&
        prev.section === next.section &&
        prev.testId === next.testId
      ) {
        return prev;
      }
      return next;
    });
  }, []);

  const navigateTo = useCallback(
    (
      next: Partial<AppLocation> & { view: PrimaryAppView },
      mode: "push" | "replace" = "push"
    ) => {
      const resolved = parseAppLocation({
        view: next.view,
        section: next.section ?? (next.view === "results" ? resultSection : undefined),
        testId: next.testId !== undefined ? next.testId : location.testId,
      });
      setLocation(resolved);
      const href = buildAppUrl(pathname, resolved);
      if (mode === "replace") {
        router.replace(href, { scroll: false });
      } else {
        router.push(href, { scroll: false });
      }
    },
    [location.testId, pathname, resultSection, router]
  );

  const setView = useCallback(
    (next: PrimaryAppView) => {
      navigateTo({ view: next }, "push");
    },
    [navigateTo]
  );

  const setResultSection = useCallback(
    (section: ResultSection) => {
      navigateTo({ view: "results", section }, "push");
    },
    [navigateTo]
  );

  const selectedProject = useMemo(
    () => projects.find((p) => p.id === projectId) || null,
    [projects, projectId]
  );

  const scopedResult = useMemo(() => {
    if (!result || !projectId) return null;
    if (result.project_id && result.project_id !== projectId) return null;
    return result;
  }, [result, projectId]);

  const refreshProjects = useCallback(async () => {
    const list = await api.listProjects();
    setProjects(list);
    return list;
  }, []);

  const refreshProjectData = useCallback(async (id: string, token?: number) => {
    const [flow, dash, analysisPayload, docs] = await Promise.all([
      api.getFlow(id),
      api.dashboard(id),
      api.latestAnalysis(id).catch(() => ({ project_id: id, analysis: null })),
      api.listDocuments(id).catch(() => []),
    ]);
    if (token != null && token !== loadTokenRef.current) return;
    if (projectIdRef.current !== id) return;
    setGraph(flow);
    setDashboard(dash);
    setDocumentCount(Array.isArray(docs) ? docs.length : 0);
    const analysis = analysisPayload?.analysis;
    if (analysis && (!analysis.project_id || analysis.project_id === id)) {
      setResult((prev) => {
        if (
          prev &&
          prev.project_id === id &&
          (prev.bug_reports?.length || 0) >= (analysis.bug_reports?.length || 0) &&
          (prev.regression_recommendations?.length || 0) >=
            (analysis.regression_recommendations?.length || 0) &&
          (prev.test_cases?.length || 0) >= (analysis.test_cases?.length || 0) &&
          (prev.reviewed_test_cases?.length || 0) >= (analysis.reviewed_test_cases?.length || 0)
        ) {
          return {
            ...analysis,
            ...prev,
            coverage: prev.coverage || analysis.coverage,
            coverage_before: prev.coverage_before || analysis.coverage_before,
            coverage_after: prev.coverage_after || analysis.coverage_after,
            reviewed_test_cases:
              (analysis.reviewed_test_cases?.length || 0) >=
              (prev.reviewed_test_cases?.length || 0)
                ? analysis.reviewed_test_cases
                : prev.reviewed_test_cases,
            validity_summary: analysis.validity_summary || prev.validity_summary,
            automation_summary: analysis.automation_summary || prev.automation_summary,
            section_status: {
              ...(prev.section_status || {}),
              ...(analysis.section_status || {}),
            },
          };
        }
        return analysis as QACopilotResponse;
      });
    }
  }, []);

  const selectProject = useCallback(
    async (id: string) => {
      const token = ++loadTokenRef.current;
      if (analysisAbortRef.current) {
        analysisAbortRef.current.abort();
        analysisAbortRef.current = null;
      }
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
      setGraph(null);
      setDashboard(null);
      setResult(null);
      setLastQuery(null);
      setDocumentCount(0);
      setProgress(createIdleProgress());
      setProjectId(id);
      if (!id) return;
      setProjectLoading(true);
      setError(null);
      try {
        await refreshProjectData(id, token);
      } catch (err) {
        if (token === loadTokenRef.current) {
          setError(err instanceof Error ? err.message : "Failed to load project");
        }
      } finally {
        if (token === loadTokenRef.current) setProjectLoading(false);
      }
    },
    [refreshProjectData]
  );

  const connect = useCallback(async () => {
    setBooting(true);
    setError(null);
    try {
      const h = await api.health();
      setHealth(h);
      await refreshProjects();
      setStatus(
        h.openai_client_ready
          ? "Connected · OpenAI ready"
          : "Connected · Deterministic fallback"
      );
      // Stay on "Select project" until the user chooses one. Only reload if a
      // project is already selected (e.g. reconnect / create / explicit change).
      if (projectIdRef.current) {
        await selectProject(projectIdRef.current);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "API unavailable");
      setStatus("API offline");
    } finally {
      setBooting(false);
    }
  }, [refreshProjects, selectProject]);

  useEffect(() => {
    connect();
    return () => {
      if (analysisAbortRef.current) analysisAbortRef.current.abort();
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreateProject() {
    const name = window.prompt("Project name", "New QA Project");
    if (!name) return;
    const rootRaw = window.prompt(
      "Root feature (optional — leave blank for an empty graph)",
      ""
    );
    if (rootRaw === null) return;
    const root = rootRaw.trim();
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name,
        description: "Created from Agentic QA Copilot",
        root_feature: root || undefined,
      });
      await refreshProjects();
      await selectProject(project.id);
      setView("home");
      setStatus(
        root
          ? `Created ${name} · root ${root}`
          : `Created ${name} · empty graph — add a root feature to begin`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleProjectChange(id: string) {
    await selectProject(id);
  }

  async function handleDeleteProject(id: string) {
    const name = projects.find((p) => p.id === id)?.name || id;
    setBusy(true);
    setError(null);
    setStatus(`Deleting ${name}…`);
    try {
      const wasSelected = projectIdRef.current === id;
      await api.deleteProject(id);
      const list = await refreshProjects();
      if (wasSelected) {
        const nextId = list.find((p) => p.id !== id)?.id || "";
        setStatus(
          nextId
            ? `Deleted ${name} · switched project`
            : `Deleted ${name} · no projects left`
        );
        // Return from delete before heavy project reload so the confirm dialog
        // can close; selectProject still drives projectLoading in the shell.
        void selectProject(nextId);
      } else {
        setStatus(`Deleted ${name}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setStatus("Delete failed");
      throw err;
    } finally {
      setBusy(false);
    }
  }

  async function handleQuery(query: string, changedNode?: string) {
    if (!projectId || busy) return;
    const forProject = projectId;
    setBusy(true);
    setError(null);
    setView("copilot");
    setLastQuery({ query, changedNode });
    setProgress({
      ...createIdleProgress(),
      status: "running",
      currentStage: "Validating project context",
      currentStageLabel: "Validating project context",
      message: "Starting agentic analysis…",
      startedAt: Date.now(),
      elapsedMs: 0,
    });

    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    elapsedTimerRef.current = setInterval(() => {
      setProgress((prev) => {
        if (prev.status !== "running" || !prev.startedAt) return prev;
        return { ...prev, elapsedMs: Date.now() - prev.startedAt };
      });
    }, 1000);

    const abort = new AbortController();
    analysisAbortRef.current = abort;

    try {
      const response = await api.queryStream(
        {
          project_id: forProject,
          query,
          root_feature: graph?.nodes.find((n) => n.id === graph.root_node_id)?.name,
          changed_node: changedNode,
          include_critic: true,
          enable_targeted_regeneration: true,
          max_regeneration_rounds: 1,
          test_output_format: testOutputFormat,
          requested_outputs: [
            "test_cases",
            "exploratory_scenarios",
            "bug_reports",
            "regression_recommendations",
            "coverage",
            "evidence",
          ],
        },
        (event) => {
          if (projectIdRef.current !== forProject) return;
          setProgress((prev) => applyProgressEvent(prev, event));
          const label = (event.stage || "").toLowerCase();
          const firstReady =
            label.includes("initial test") ||
            label.includes("generating test") ||
            label.includes("exploratory") ||
            label.includes("bug report") ||
            label.includes("regression");
          if (firstReady && locationRef.current.view === "copilot") {
            const next = parseAppLocation({ view: "results", section: "overview" });
            setLocation(next);
            locationRef.current = next;
            router.replace(buildAppUrl(pathname, next), { scroll: false });
          }
        },
        abort.signal
      );
      if (projectIdRef.current !== forProject) return;
      setResult(response);
      setProgress((prev) => ({
        ...prev,
        status: "completed",
        currentStageLabel: "Finalizing analysis",
        message: "Analysis complete",
        elapsedMs: prev.startedAt ? Date.now() - prev.startedAt : prev.elapsedMs,
      }));
      setResultSection("overview");
      await refreshProjectData(forProject, loadTokenRef.current);
      const backend =
        response.generation_backend === "openai"
          ? "OpenAI"
          : response.generation_backend === "deterministic_fallback"
            ? "fallback"
            : response.generation_backend || "mixed";
      setStatus(
        `Analysis complete · ${response.test_cases.length} tests · ${response.bug_reports?.length || 0} bugs · ${response.regression_recommendations?.length || 0} regression · ${backend}`
      );
    } catch (err) {
      if (projectIdRef.current === forProject) {
        const message = err instanceof Error ? err.message : "Query failed";
        if (!abort.signal.aborted || message !== "Request timed out. Please retry.") {
          setError(message);
        }
        setProgress((prev) => ({
          ...prev,
          status: "failed",
          message,
        }));
        setStatus("Analysis failed");
      }
    } finally {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
      if (analysisAbortRef.current === abort) analysisAbortRef.current = null;
      setBusy(false);
    }
  }

  async function handleSaveGraph(next: SystemFlowGraph) {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveFlow(projectId, { ...next, project_id: projectId });
      if (projectIdRef.current !== projectId) return;
      setGraph(saved);
      const dash = await api.dashboard(projectId);
      if (projectIdRef.current !== projectId) return;
      setDashboard(dash);
      setStatus(`Graph saved · v${saved.version}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const rootFeatureName = graph?.nodes.find((n) => n.id === graph.root_node_id)?.name;
  const projectReady = Boolean(projectId && graph && graph.nodes.length > 0);
  const emptyGraph = Boolean(projectId && graph && graph.nodes.length === 0);

  return (
    <div className="min-h-screen bg-hero-wash">
      <Suspense fallback={null}>
        <LocationSync onLocation={applyLocation} />
      </Suspense>
      <TopBar
        projects={projects}
        projectId={projectId}
        onProjectChange={handleProjectChange}
        onCreateProject={handleCreateProject}
        onDeleteProject={handleDeleteProject}
        status={status}
        busy={busy || projectLoading}
        health={health}
        apiUrl={API_URL}
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

          {view === "home" && (
            <HomePanel
              project={selectedProject}
              graph={graph}
              dashboard={dashboard}
              result={scopedResult}
              health={health}
              docsCount={documentCount}
              onNavigate={(nextView, section, filters) => {
                const resolved = parseAppLocation({
                  view: nextView,
                  section: section || (nextView === "results" ? "overview" : undefined),
                  testId: filters?.testId ?? null,
                });
                setLocation(resolved);
                const params = new URLSearchParams(
                  buildAppUrl(pathname, resolved).split("?")[1] || ""
                );
                if (filters) {
                  Object.entries(filters).forEach(([k, v]) => {
                    if (k === "view" || k === "section" || k === "testId") return;
                    params.set(k, v);
                  });
                }
                const qs = params.toString();
                router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
              }}
            />
          )}

          {view === "copilot" && (
            <>
              <PageHeader
                title="QA Copilot"
                subtitle={[selectedProject?.name, rootFeatureName].filter(Boolean).join(" · ") || undefined}
                meta={projectReady ? "Graph ready for analysis" : emptyGraph ? "Empty graph" : "Select a project"}
              />
              <CopilotPanel
                key={projectId || "none"}
                busy={busy}
                result={scopedResult}
                onQuery={handleQuery}
                projectReady={projectReady}
                emptyGraph={emptyGraph}
                projectName={selectedProject?.name}
                rootFeature={rootFeatureName}
                testOutputFormat={testOutputFormat}
                onTestOutputFormatChange={setTestOutputFormat}
                readiness={{
                  flowReady: projectReady,
                  nodeCount: graph?.nodes.length || 0,
                  edgeCount: graph?.edges.length || 0,
                  documentCount,
                  featureName: rootFeatureName,
                }}
                progress={progress}
                onOpenResults={() => setResultSection("overview")}
                onOpenTrace={() => setView("trace")}
              />
            </>
          )}
          {view === "flow" && (
            <PageHeader
              title="System Flow"
              subtitle={[selectedProject?.name, rootFeatureName].filter(Boolean).join(" · ") || undefined}
              meta={
                graph
                  ? `${graph.nodes.length} nodes · ${graph.edges.length} edges`
                  : projectLoading
                    ? "Loading…"
                    : "No graph"
              }
            />
          )}
          {view === "flow" && projectId && projectLoading && !graph && (
            <div className="panel px-6 py-8 text-sm text-ink-600/70">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" /> Loading system flow…
            </div>
          )}
          {view === "flow" && graph && projectId && (
            <FlowBuilder
              key={projectId}
              graph={graph}
              busy={busy}
              projectId={projectId}
              onChange={setGraph}
              onSave={handleSaveGraph}
              onImported={async () => refreshProjectData(projectId, loadTokenRef.current)}
            />
          )}
          {view === "flow" && projectId && graph && graph.nodes.length === 0 && (
            <div className="panel px-6 py-6 text-sm text-ink-700/80">
              No system flow defined yet. Add a root feature, import JSON, or extract from natural
              language.
            </div>
          )}
          {view === "explorer" && (
            <PageHeader
              title="Graph Explorer"
              subtitle={[selectedProject?.name, rootFeatureName].filter(Boolean).join(" · ") || undefined}
              meta={graph ? `${graph.nodes.length} nodes · ${graph.edges.length} edges` : "No graph"}
            />
          )}
          {view === "explorer" && projectId && (!graph || graph.nodes.length === 0) && (
            <div className="panel px-6 py-8 text-sm text-ink-600/70">No graph available for this project.</div>
          )}
          {view === "explorer" && graph && projectId && graph.nodes.length > 0 && (
            <GraphExplorer key={projectId} projectId={projectId} graph={graph} />
          )}
          {view === "knowledge" && (
            <PageHeader
              title="Knowledge Base"
              subtitle={selectedProject?.name}
              meta={documentCount != null ? `${documentCount} document(s)` : undefined}
            />
          )}
          {view === "knowledge" && projectId && (
            <KnowledgePanel
              key={projectId}
              projectId={projectId}
              onDocumentsChanged={(count) => setDocumentCount(count)}
            />
          )}
          {view === "results" && projectId && (
            <>
              <PageHeader
                title="Analysis Results"
                subtitle={[selectedProject?.name, rootFeatureName].filter(Boolean).join(" · ") || undefined}
                meta={
                  scopedResult
                    ? `${scopedResult.test_cases?.length ?? 0} tests · ${scopedResult.risk_level || "—"} risk`
                    : "No analysis yet"
                }
              />
              <AnalysisResultsPanel
                key={`${projectId}-results`}
                projectId={projectId}
                projectName={selectedProject?.name}
                result={scopedResult}
                section={resultSection}
                onSectionChange={setResultSection}
                progress={progress}
                busy={busy}
                onOpenCopilot={() => setView("copilot")}
                onOpenTrace={() => setView("trace")}
                onRerun={
                  lastQuery
                    ? () => handleQuery(lastQuery.query, lastQuery.changedNode)
                    : undefined
                }
                onRefresh={() => refreshProjectData(projectId, loadTokenRef.current)}
              />
            </>
          )}
          {view === "trace" && (
            <>
              <PageHeader
                title="Agent Trace"
                subtitle={[selectedProject?.name, rootFeatureName].filter(Boolean).join(" · ") || undefined}
                meta={
                  scopedResult?.execution_trace?.length
                    ? `${scopedResult.execution_trace.length} steps`
                    : "No trace yet"
                }
              />
              <TracePanel key={projectId} result={scopedResult} />
            </>
          )}

          {!projectId && !booting && (
            <div className="panel px-6 py-10 text-center">
              <LayoutDashboard className="mx-auto h-8 w-8 text-brass-500" />
              <h2 className="mt-3 font-display text-2xl">
                {projects.length > 0 ? "Select a project to begin" : "Create a project to begin"}
              </h2>
              <p className="mx-auto mt-2 max-w-lg text-sm text-ink-700/75">
                {projects.length > 0
                  ? "Choose a project from the top bar, or create a new one to define a system flow, add knowledge, and run QA Copilot."
                  : "Start with an empty project, define a system flow, add knowledge, then run QA Copilot and review unified Analysis Results."}
              </p>
              <div className="mt-5 flex justify-center gap-3">
                <button className="btn-primary" onClick={handleCreateProject} disabled={busy}>
                  Create project
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
