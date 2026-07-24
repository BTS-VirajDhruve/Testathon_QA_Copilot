import type {
  DashboardStats,
  NodeInsight,
  Project,
  QACopilotResponse,
  SystemFlowGraph,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
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
}

export const api = {
  health: () => request<{ status: string; openai: boolean }>("/api/health"),
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (body: { name: string; description?: string; root_feature?: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
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
  exportFlow: (id: string) => request<SystemFlowGraph>(`/api/projects/${id}/flow/export`),
  nodeInsight: (projectId: string, nodeId: string) =>
    request<NodeInsight>(`/api/projects/${projectId}/nodes/${nodeId}/insight`),
  dashboard: (id: string) => request<DashboardStats>(`/api/projects/${id}/dashboard`),
  coverage: (id: string) => request<DashboardStats & Record<string, unknown>>(`/api/projects/${id}/coverage`),
  listDocuments: (id: string) =>
    request<Array<{ id: string; filename: string; chunk_count: number }>>(`/api/projects/${id}/documents`),
  ingestText: (id: string, filename: string, text: string) =>
    request(`/api/projects/${id}/documents/text`, {
      method: "POST",
      body: JSON.stringify({ filename, text }),
    }),
  listTests: (id: string) => request<Array<Record<string, unknown>>>(`/api/projects/${id}/tests`),
  listBugs: (id: string) => request<Array<Record<string, unknown>>>(`/api/projects/${id}/bugs`),
  seedDemo: () =>
    request<{
      project_id: string;
      project_name: string;
      demo_query: string;
      nodes: number;
    }>("/api/demo/seed", { method: "POST" }),
  query: (body: {
    project_id: string;
    query: string;
    root_feature?: string;
    changed_node?: string;
  }) =>
    request<QACopilotResponse>("/api/copilot/query", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export { API_URL };