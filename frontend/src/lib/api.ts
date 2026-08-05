import type {
  DashboardStats,
  HealthStatus,
  NodeInsight,
  Project,
  QACopilotResponse,
  SystemFlowGraph,
  BDDExportOptions,
  BDDExportPreview,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = 120_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: init?.signal || controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers || {}),
      },
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `Request failed: ${res.status}`);
    }
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out. Please retry.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (body: { name: string; description?: string; root_feature?: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  deleteProject: (id: string) =>
    request<{
      success: boolean;
      deleted_project_id: string;
      deleted_resources: {
        nodes: number;
        edges: number;
        documents: number;
        vectors: number;
        tests: number;
        bugs: number;
        coverage: number;
      };
    }>(`/api/projects/${id}`, { method: "DELETE" }),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  getFlow: (id: string) => request<SystemFlowGraph>(`/api/projects/${id}/flow`),
  saveFlow: (id: string, graph: SystemFlowGraph) =>
    request<SystemFlowGraph>(`/api/projects/${id}/flow`, {
      method: "PUT",
      body: JSON.stringify(graph),
    }),
  importFlow: (id: string, body: unknown) =>
    request<SystemFlowGraph>(`/api/projects/${id}/flow/import`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  flowFromText: (id: string, text: string) =>
    request<SystemFlowGraph>(`/api/projects/${id}/flow/from-text`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  flowFromTextStream: async (
    id: string,
    text: string,
    onProgress?: (event: { stage: string; message: string; meta?: Record<string, unknown> }) => void
  ): Promise<SystemFlowGraph> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120_000);
    try {
      const res = await fetch(`${API_URL}/api/projects/${id}/flow/from-text/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: controller.signal,
        cache: "no-store",
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `Request failed: ${res.status}`);
      }
      if (!res.body) {
        throw new Error("Streaming response body missing");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let graph: SystemFlowGraph | null = null;
      let streamError: string | null = null;

      const handleBlock = (block: string) => {
        const lines = block.split("\n");
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) return;
        const payload = JSON.parse(dataLines.join("\n"));
        if (eventName === "progress") {
          onProgress?.({
            stage: String(payload.stage || ""),
            message: String(payload.message || ""),
            meta: payload.meta,
          });
        } else if (eventName === "complete") {
          graph = payload as SystemFlowGraph;
        } else if (eventName === "error") {
          streamError = String(payload.message || "Natural-language graph generation failed");
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          if (part.trim()) handleBlock(part.trim());
        }
      }
      if (buffer.trim()) handleBlock(buffer.trim());
      if (streamError) throw new Error(streamError);
      if (!graph) throw new Error("Stream ended without a graph");
      return graph;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new Error("Request timed out. Please retry.");
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  },
  exportFlow: (id: string) => request<SystemFlowGraph>(`/api/projects/${id}/flow/export`),
  nodeInsight: (projectId: string, nodeId: string) =>
    request<NodeInsight>(`/api/projects/${projectId}/nodes/${nodeId}/insight`),
  dashboard: (id: string) => request<DashboardStats>(`/api/projects/${id}/dashboard`),
  coverage: (id: string) =>
    request<{
      overall_coverage: number;
      branch_coverage: number;
      covered_branches: string[];
      uncovered_branches: string[];
      critical_gaps: string[];
      calculation_notes: string[];
      recommended_tests?: string[];
      uncovered_failure_paths?: string[];
    }>(`/api/projects/${id}/coverage`),
  listDocuments: (id: string) =>
    request<Array<{ id: string; filename: string; chunk_count: number }>>(`/api/projects/${id}/documents`),
  ingestText: (id: string, filename: string, text: string) =>
    request(`/api/projects/${id}/documents/text`, {
      method: "POST",
      body: JSON.stringify({ filename, text }),
    }),
  uploadDocument: async (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/api/projects/${id}/documents/upload`, {
      method: "POST",
      body: form,
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `Upload failed: ${res.status}`);
    }
    return res.json();
  },
  atlassianStatus: () =>
    request<{
      enabled: boolean;
      configured: boolean;
      connected: boolean;
      status: string;
      selected_cloud_id?: string | null;
      selected_site_name?: string | null;
      selected_site_url?: string | null;
      error?: string | null;
    }>("/api/integrations/atlassian/status"),
  atlassianConnectUrl: (qaProjectId: string, returnView = "knowledge") =>
    `${API_URL}/api/integrations/atlassian/connect?qa_project_id=${encodeURIComponent(qaProjectId)}&return_view=${encodeURIComponent(returnView)}`,
  atlassianSites: () =>
    request<Array<{ cloud_id: string; name: string; url: string; avatar_url?: string }>>(
      "/api/integrations/atlassian/sites"
    ),
  atlassianSelectSite: (cloudId: string) =>
    request("/api/integrations/atlassian/select-site", {
      method: "POST",
      body: JSON.stringify({ cloud_id: cloudId }),
    }),
  atlassianDisconnect: () =>
    request("/api/integrations/atlassian/disconnect", { method: "POST" }),
  atlassianJiraProjects: (query?: string) =>
    request<{ items: Array<Record<string, unknown>>; total: number }>(
      `/api/integrations/atlassian/jira/projects${query ? `?query=${encodeURIComponent(query)}` : ""}`
    ),
  atlassianJiraIssueSearch: (body: Record<string, unknown>) =>
    request<{ items: Array<Record<string, unknown>>; next_page_token?: string | null }>(
      "/api/integrations/atlassian/jira/issues/search",
      { method: "POST", body: JSON.stringify(body) }
    ),
  atlassianJiraPreview: (issueKey: string) =>
    request<Record<string, unknown>>(
      `/api/integrations/atlassian/jira/issues/${encodeURIComponent(issueKey)}/preview`
    ),
  atlassianConfluenceSpaces: (query?: string, cursor?: string) => {
    const params = new URLSearchParams();
    if (query) params.set("query", query);
    if (cursor) params.set("cursor", cursor);
    const qs = params.toString();
    return request<{ items: Array<Record<string, unknown>>; next_cursor?: string | null }>(
      `/api/integrations/atlassian/confluence/spaces${qs ? `?${qs}` : ""}`
    );
  },
  atlassianConfluencePages: (spaceId: string, title?: string, cursor?: string) => {
    const params = new URLSearchParams();
    if (title) params.set("title", title);
    if (cursor) params.set("cursor", cursor);
    const qs = params.toString();
    return request<{ items: Array<Record<string, unknown>>; next_cursor?: string | null }>(
      `/api/integrations/atlassian/confluence/spaces/${encodeURIComponent(spaceId)}/pages${qs ? `?${qs}` : ""}`
    );
  },
  atlassianConfluencePreview: (pageId: string) =>
    request<Record<string, unknown>>(
      `/api/integrations/atlassian/confluence/pages/${encodeURIComponent(pageId)}/preview`
    ),
  atlassianImport: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/integrations/atlassian/import", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  atlassianListImports: (qaProjectId: string) =>
    request<Array<Record<string, unknown>>>(
      `/api/integrations/atlassian/imports?qa_project_id=${encodeURIComponent(qaProjectId)}`
    ),
  atlassianSyncImport: (sourceId: string, qaProjectId: string) =>
    request(
      `/api/integrations/atlassian/imports/${encodeURIComponent(sourceId)}/sync?qa_project_id=${encodeURIComponent(qaProjectId)}`,
      { method: "POST" }
    ),
  atlassianDeleteImport: (sourceId: string, qaProjectId: string) =>
    request(
      `/api/integrations/atlassian/imports/${encodeURIComponent(sourceId)}?qa_project_id=${encodeURIComponent(qaProjectId)}`,
      { method: "DELETE" }
    ),
  listTests: (id: string) => request<Array<Record<string, unknown>>>(`/api/projects/${id}/tests`),
  createManualTests: (projectId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/projects/${projectId}/tests`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateManualTest: (projectId: string, testCaseId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/projects/${projectId}/tests/${testCaseId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteManualTest: (projectId: string, testCaseId: string, force = false) =>
    request<Record<string, unknown>>(
      `/api/projects/${projectId}/tests/${testCaseId}?force=${force ? "true" : "false"}`,
      { method: "DELETE" }
    ),
  listBugs: (id: string) => request<Array<Record<string, unknown>>>(`/api/projects/${id}/bugs`),
  seedDemo: () =>
    request<{
      project_id: string;
      project_name: string;
      demo_query: string;
      nodes: number;
      reused_project?: boolean;
      graph_rewritten?: boolean;
      existing_tests?: number;
      historical_bugs?: number;
    }>("/api/demo/seed", { method: "POST" }),
  latestAnalysis: (id: string) =>
    request<{ project_id: string; analysis: QACopilotResponse | null }>(
      `/api/projects/${id}/latest-analysis`
    ),
  resumeCoverageClosure: (projectId: string, body: Record<string, unknown> = {}) =>
    request<{ project_id: string; analysis: QACopilotResponse }>(
      `/api/projects/${projectId}/coverage-closure/resume`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  testReview: (id: string) =>
    request<{ project_id: string; analysis: QACopilotResponse | null }>(
      `/api/projects/${id}/test-review`
    ),
  runTestReview: (id: string) =>
    request<{ project_id: string; analysis: QACopilotResponse }>(
      `/api/projects/${id}/test-review`,
      { method: "POST" }
    ),
  query: (body: {
    project_id: string;
    query: string;
    root_feature?: string;
    changed_node?: string;
    include_critic?: boolean;
    enable_targeted_regeneration?: boolean;
    max_regeneration_rounds?: number;
    max_gaps_per_round?: number;
    requested_outputs?: string[];
    automation_strategy?: string;
    include_test_review?: boolean;
    test_output_format?: "standard" | "bdd" | "both";
  }) =>
    request<QACopilotResponse>("/api/copilot/query", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  queryStream: async (
    body: {
      project_id: string;
      query: string;
      root_feature?: string;
      changed_node?: string;
      include_critic?: boolean;
      enable_targeted_regeneration?: boolean;
      max_regeneration_rounds?: number;
      max_gaps_per_round?: number;
      requested_outputs?: string[];
      automation_strategy?: string;
      include_test_review?: boolean;
      test_output_format?: "standard" | "bdd" | "both";
    },
    onProgress?: (event: {
      stage: string;
      message: string;
      meta?: Record<string, unknown>;
    }) => void,
    signal?: AbortSignal
  ): Promise<QACopilotResponse> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 300_000);
    const onAbort = () => controller.abort();
    if (signal) {
      if (signal.aborted) controller.abort();
      else signal.addEventListener("abort", onAbort, { once: true });
    }
    try {
      const res = await fetch(`${API_URL}/api/copilot/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `Request failed: ${res.status}`);
      }
      if (!res.body) {
        throw new Error("Streaming response body missing");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let result: QACopilotResponse | null = null;
      let streamError: string | null = null;

      const handleBlock = (block: string) => {
        const lines = block.split("\n");
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) return;
        const payload = JSON.parse(dataLines.join("\n"));
        if (eventName === "progress") {
          onProgress?.({
            stage: String(payload.stage || ""),
            message: String(payload.message || ""),
            meta: payload.meta,
          });
        } else if (eventName === "complete") {
          result = payload as QACopilotResponse;
        } else if (eventName === "error") {
          streamError = String(payload.message || "Agentic analysis failed");
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          if (part.trim()) handleBlock(part.trim());
        }
      }
      if (buffer.trim()) handleBlock(buffer.trim());
      if (streamError) throw new Error(streamError);
      if (!result) throw new Error("Stream ended without an analysis result");
      return result;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new Error("Request timed out. Please retry.");
      }
      throw err;
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
    }
  },
  exportBddFeature: async (projectId: string, feature?: string) => {
    const q = feature ? `?feature=${encodeURIComponent(feature)}` : "";
    const res = await fetch(`${API_URL}/api/projects/${projectId}/tests/export.feature${q}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `Export failed (${res.status})`);
    }
    return {
      text: await res.text(),
      filename:
        res.headers.get("Content-Disposition")?.match(/filename="?([^"]+)"?/)?.[1] ||
        "scenarios.feature",
    };
  },
  previewBddExport: async (projectId: string, body?: BDDExportOptions) => {
    const res = await fetch(
      `${API_URL}/api/projects/${projectId}/analyses/latest/exports/bdd/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || { scope: "all_final_generated" }),
        cache: "no-store",
      }
    );
    if (!res.ok) {
      const text = await res.text();
      try {
        const parsed = JSON.parse(text);
        const detail = parsed?.detail;
        if (detail && typeof detail === "object") {
          throw {
            message: detail.message || detail.code || text,
            code: detail.code,
            details: detail.details,
          };
        }
      } catch (err) {
        if (err && typeof err === "object" && "code" in err) throw err;
      }
      throw new Error(text || `Preview failed (${res.status})`);
    }
    return (await res.json()) as BDDExportPreview;
  },
  exportBddAnalysis: async (projectId: string, body?: BDDExportOptions) => {
    const res = await fetch(`${API_URL}/api/projects/${projectId}/analyses/latest/exports/bdd`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || { scope: "all_final_generated" }),
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      let message = text || `Export failed (${res.status})`;
      try {
        const parsed = JSON.parse(text);
        const detail = parsed?.detail;
        if (detail && typeof detail === "object") {
          message = detail.message || detail.code || message;
          return Promise.reject({
            message,
            code: detail.code,
            details: detail.details,
          });
        }
      } catch {
        /* plain text */
      }
      throw new Error(message);
    }
    const contentType = res.headers.get("Content-Type") || "";
    const blob = await res.blob();
    const fromHeader =
      res.headers.get("Content-Disposition")?.match(/filename="?([^"]+)"?/)?.[1] || null;
    const fallback = contentType.includes("csv")
      ? "test-cases-import.csv"
      : contentType.includes("zip")
        ? "bdd-export.zip"
        : "export.feature";
    return {
      blob,
      filename: fromHeader || fallback,
      scenarioCount: Number(res.headers.get("X-QA-Exported-Scenarios") || 0),
      fileCount: Number(res.headers.get("X-QA-Exported-Files") || 0),
    };
  },
  overrideAutomationReview: (
    projectId: string,
    testCaseId: string,
    body: {
      validity?: string;
      automation_suitability?: string;
      automation_layer?: string;
      automation_priority?: string;
      automation_effort?: string;
      review_status?: string;
      override_reason?: string;
    }
  ) =>
    request<{
      project_id: string;
      test_case_id: string;
      override: Record<string, unknown>;
    }>(`/api/projects/${projectId}/tests/${encodeURIComponent(testCaseId)}/automation-review`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  getAutomationProfile: (projectId: string) =>
    request<{ project_id: string; profile: Record<string, unknown> | null }>(
      `/api/projects/${projectId}/automation-profile`
    ),
  setAutomationProfile: (projectId: string, profile: Record<string, unknown>) =>
    request<{ project_id: string; profile: Record<string, unknown> }>(
      `/api/projects/${projectId}/automation-profile`,
      { method: "PUT", body: JSON.stringify(profile) }
    ),
};

export { API_URL };
