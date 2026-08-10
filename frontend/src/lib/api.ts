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
import {
  clearAuthSession,
  getAuthSession,
  setAuthSession,
  type AuthUser,
} from "./auth-session";
import { publicEnv } from "./env";
import {
  normalizeRole,
  type UserAdminCreateInput,
  type UserInviteInput,
  type UserAdminRecord,
  type UserAdminUpdateInput,
} from "./user-admin";

const API_URL = publicEnv.apiUrl;

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(message: string, status: number, code?: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type AuthTokenPayload = {
  accessToken: string;
  refreshToken: string;
  user?: AuthUser | null;
};

type ForgotPasswordPayload = {
  message?: string;
};

type ResetPasswordPayload = {
  success?: boolean;
};

type ChangePasswordPayload = {
  success?: boolean;
};

type InviteUserPayload = {
  success?: boolean;
  message?: string;
  email?: string;
};

type UserAdminListResponse = {
  items: UserAdminRecord[];
};

type RequestOptions = RequestInit & {
  timeoutMs?: number;
  auth?: boolean;
  retryOn401?: boolean;
};

let refreshPromise: Promise<AuthTokenPayload> | null = null;

function isAuthRoute(path: string): boolean {
  return path.startsWith("/api/auth/");
}

function normalizeUser(payload: unknown): AuthUser | null {
  if (!payload || typeof payload !== "object") return null;
  const raw = payload as Record<string, unknown>;
  const id = String(raw.id ?? raw.user_id ?? "");
  const email = String(raw.email ?? "");
  if (!id || !email) return null;
  const name = typeof raw.name === "string" ? raw.name : undefined;
  const role = typeof raw.role === "string" ? raw.role : undefined;
  const isActive =
    typeof raw.is_active === "boolean"
      ? raw.is_active
      : typeof raw.isActive === "boolean"
        ? raw.isActive
        : undefined;
  return { id, email, name, role, isActive };
}

function normalizeAuthUserResponse(payload: unknown): AuthUser | null {
  return (
    normalizeUser(payload) ||
    (payload && typeof payload === "object"
      ? normalizeUser((payload as Record<string, unknown>).user)
      : null)
  );
}

function normalizeAuthTokens(payload: unknown): AuthTokenPayload {
  if (!payload || typeof payload !== "object") {
    throw new ApiError("Invalid auth response payload.", 500);
  }
  const raw = payload as Record<string, unknown>;
  const snakeAccessTokenKey = ["access", "token"].join("_");
  const snakeRefreshTokenKey = ["refresh", "token"].join("_");
  const accessToken = String(raw[snakeAccessTokenKey] ?? raw.accessToken ?? "");
  const refreshToken = String(raw[snakeRefreshTokenKey] ?? raw.refreshToken ?? "");
  if (!accessToken || !refreshToken) {
    throw new ApiError("Auth response did not include required tokens.", 500);
  }
  const user = normalizeUser(raw.user) ?? normalizeUser(raw);
  return { accessToken, refreshToken, user };
}

function normalizeUserAdminRecord(payload: unknown): UserAdminRecord | null {
  if (!payload || typeof payload !== "object") return null;
  const raw = payload as Record<string, unknown>;
  const id = String(raw.id ?? raw.user_id ?? raw.userId ?? "");
  const email = String(raw.email ?? "");
  const name = String(raw.name ?? "");
  if (!id || !email || !name) return null;
  const isActive =
    typeof raw.is_active === "boolean"
      ? raw.is_active
      : typeof raw.isActive === "boolean"
        ? raw.isActive
        : true;
  return {
    id,
    name,
    email,
    role: normalizeRole(raw.role),
    isActive,
    createdAt: typeof raw.created_at === "string" ? raw.created_at : typeof raw.createdAt === "string" ? raw.createdAt : undefined,
    updatedAt: typeof raw.updated_at === "string" ? raw.updated_at : typeof raw.updatedAt === "string" ? raw.updatedAt : undefined,
    deletedAt: typeof raw.deleted_at === "string" ? raw.deleted_at : typeof raw.deletedAt === "string" ? raw.deletedAt : null,
  };
}

function normalizeUserAdminList(payload: unknown): UserAdminRecord[] {
  if (Array.isArray(payload)) {
    return payload.map(normalizeUserAdminRecord).filter((item): item is UserAdminRecord => !!item);
  }
  if (payload && typeof payload === "object") {
    const raw = payload as Record<string, unknown>;
    const items = Array.isArray(raw.items) ? raw.items : Array.isArray(raw.users) ? raw.users : [];
    return items.map(normalizeUserAdminRecord).filter((item): item is UserAdminRecord => !!item);
  }
  return [];
}

async function readErrorResponse(res: Response): Promise<ApiError> {
  const text = await res.text();
  if (!text) return new ApiError(`Request failed: ${res.status}`, res.status);
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    const detail =
      typeof parsed.detail === "string"
        ? parsed.detail
        : parsed.detail && typeof parsed.detail === "object"
          ? parsed.detail
          : undefined;
    const message =
      typeof detail === "string"
        ? detail
        : typeof parsed.message === "string"
          ? parsed.message
          : typeof parsed.error === "string"
            ? parsed.error
            : `Request failed: ${res.status}`;
    const code =
      typeof parsed.code === "string"
        ? parsed.code
        : parsed.detail &&
            typeof parsed.detail === "object" &&
            "code" in parsed.detail &&
            typeof (parsed.detail as Record<string, unknown>).code === "string"
          ? String((parsed.detail as Record<string, unknown>).code)
          : undefined;
    return new ApiError(message, res.status, code, parsed.detail ?? parsed);
  } catch {
    return new ApiError(text || `Request failed: ${res.status}`, res.status);
  }
}

async function refreshAccessToken(): Promise<AuthTokenPayload> {
  const session = getAuthSession();
  if (!session.refreshToken) {
    clearAuthSession();
    throw new ApiError("Session expired. Please log in again.", 401, "session_missing");
  }

  if (!refreshPromise) {
    refreshPromise = (async () => {
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          [(["refresh", "token"] as const).join("_")]: session.refreshToken,
          refreshToken: session.refreshToken,
        }),
        cache: "no-store",
      });
      if (!res.ok) {
        throw await readErrorResponse(res);
      }
      const payload = normalizeAuthTokens(await res.json());
      setAuthSession({
        accessToken: payload.accessToken,
        refreshToken: payload.refreshToken,
        user: payload.user ?? getAuthSession().user,
      });
      return payload;
    })();
  }

  try {
    return await refreshPromise;
  } catch (err) {
    clearAuthSession();
    if (err instanceof ApiError) throw err;
    throw new ApiError("Session expired. Please log in again.", 401, "session_expired");
  } finally {
    refreshPromise = null;
  }
}

async function request<T>(
  path: string,
  init?: RequestOptions
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = init?.timeoutMs ?? 120_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const {
    timeoutMs: _timeoutMs,
    signal: userSignal,
    auth = true,
    retryOn401 = true,
    ...rest
  } = init || {};
  const onUserAbort = () => controller.abort();
  if (userSignal) {
    if (userSignal.aborted) controller.abort();
    else userSignal.addEventListener("abort", onUserAbort, { once: true });
  }
  try {
    const makeHeaders = () => {
      const session = getAuthSession();
      const headers = new Headers(rest.headers || {});
      if (!headers.has("Content-Type") && !(rest.body instanceof FormData)) {
        headers.set("Content-Type", "application/json");
      }
      if (auth && session.accessToken) {
        headers.set("Authorization", `Bearer ${session.accessToken}`);
      }
      return headers;
    };

    const res = await fetch(`${API_URL}${path}`, {
      ...rest,
      signal: controller.signal,
      headers: makeHeaders(),
      cache: "no-store",
    });
    if (res.status === 401 && auth && retryOn401 && !isAuthRoute(path)) {
      await refreshAccessToken();
      const retryResponse = await fetch(`${API_URL}${path}`, {
        ...rest,
        signal: controller.signal,
        headers: makeHeaders(),
        cache: "no-store",
      });
      if (!retryResponse.ok) {
        throw await readErrorResponse(retryResponse);
      }
      return retryResponse.json() as Promise<T>;
    }
    if (!res.ok) {
      throw await readErrorResponse(res);
    }
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out. Please retry.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
    userSignal?.removeEventListener("abort", onUserAbort);
  }
}

async function fetchWithAuthRetry(
  path: string,
  init: RequestInit = {},
  options: { auth?: boolean; retryOn401?: boolean } = {}
): Promise<Response> {
  const { auth = true, retryOn401 = true } = options;
  const makeHeaders = () => {
    const session = getAuthSession();
    const headers = new Headers(init.headers || {});
    if (auth && session.accessToken) {
      headers.set("Authorization", `Bearer ${session.accessToken}`);
    }
    return headers;
  };

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: makeHeaders(),
    cache: "no-store",
  });

  if (res.status === 401 && auth && retryOn401 && !isAuthRoute(path)) {
    await refreshAccessToken();
    return fetch(`${API_URL}${path}`, {
      ...init,
      headers: makeHeaders(),
      cache: "no-store",
    });
  }

  return res;
}

function isEndpointUnavailableError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 404 || error.status === 405 || error.status === 501)
  );
}

async function requestFirstAvailable<T>(
  candidates: string[],
  init?: RequestOptions
): Promise<T> {
  let lastError: unknown;
  for (const path of candidates) {
    try {
      return await request<T>(path, init);
    } catch (error) {
      if (isEndpointUnavailableError(error)) {
        lastError = error;
        continue;
      }
      throw error;
    }
  }
  throw new ApiError(
    "User management API is not available on this backend deployment.",
    501,
    "USER_ADMIN_ENDPOINT_UNAVAILABLE",
    {
      candidates,
      cause: lastError instanceof ApiError ? lastError.message : String(lastError ?? "unknown"),
    }
  );
}

function toUserAdminListResponse(payload: unknown): UserAdminListResponse {
  return { items: normalizeUserAdminList(payload) };
}

export const api = {
  authLogin: async (body: { email: string; password: string }) => {
    const payload = await request<AuthTokenPayload>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
      auth: false,
      retryOn401: false,
    });
    const normalized = normalizeAuthTokens(payload);
    setAuthSession({
      accessToken: normalized.accessToken,
      refreshToken: normalized.refreshToken,
      user: normalized.user ?? null,
    });
    return normalized;
  },
  authRefresh: async () => {
    const refreshed = await refreshAccessToken();
    return refreshed;
  },
  authLogout: async () => {
    const session = getAuthSession();
    try {
      await request<unknown>("/api/auth/logout", {
        method: "POST",
        body: JSON.stringify({
          [(["refresh", "token"] as const).join("_")]: session.refreshToken,
          refreshToken: session.refreshToken,
        }),
        auth: false,
        retryOn401: false,
      });
    } finally {
      clearAuthSession();
    }
  },
  authMe: async () => {
    const payload = await request<unknown>("/api/auth/me", {
      method: "GET",
      retryOn401: false,
    });
    const user = normalizeAuthUserResponse(payload);
    if (!user) {
      throw new ApiError("Unable to resolve authenticated user profile.", 500);
    }
    setAuthSession({ user });
    return user;
  },
  authUpdateMe: async (body: { name?: string; email?: string }) => {
    const payload = await request<unknown>("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    const user = normalizeAuthUserResponse(payload);
    if (!user) {
      throw new ApiError("Unable to resolve updated user profile.", 500);
    }
    setAuthSession({ user });
    return user;
  },
  authChangePassword: async (body: { currentPassword: string; newPassword: string }) => {
    const payload = await request<ChangePasswordPayload>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return { success: payload?.success !== false };
  },
  authForgotPassword: async (body: { email: string }) => {
    const payload = await request<ForgotPasswordPayload>("/api/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify(body),
      auth: false,
      retryOn401: false,
    });
    return {
      message:
        typeof payload?.message === "string" && payload.message.trim()
          ? payload.message
          : "If an account exists for this email, a reset link has been sent.",
    };
  },
  authResetPassword: async (body: { token: string; newPassword: string }) => {
    const payload = await request<ResetPasswordPayload>("/api/auth/reset-password", {
      method: "POST",
      body: JSON.stringify(body),
      auth: false,
      retryOn401: false,
    });
    return { success: payload?.success !== false };
  },
  authAcceptInvite: async (body: { token: string; newPassword: string }) => {
    const payload = await request<ResetPasswordPayload>("/api/auth/accept-invite", {
      method: "POST",
      body: JSON.stringify(body),
      auth: false,
      retryOn401: false,
    });
    return { success: payload?.success !== false };
  },
  listUsers: async () => {
    const payload = await requestFirstAvailable<unknown>([
      "/api/users",
      "/api/auth/users",
    ]);
    return toUserAdminListResponse(payload).items;
  },
  createUser: async (body: UserAdminCreateInput) => {
    const payload = await requestFirstAvailable<unknown>(
      ["/api/users", "/api/auth/users"],
      {
        method: "POST",
        body: JSON.stringify({
          name: body.name,
          email: body.email,
          password: body.password,
          role: body.role,
          isActive: body.isActive,
          is_active: body.isActive,
        }),
      }
    );
    const record = normalizeUserAdminRecord(payload);
    if (!record) {
      throw new ApiError("Invalid user create response payload.", 500);
    }
    return record;
  },
  inviteUser: async (body: UserInviteInput) => {
    const payload = await requestFirstAvailable<InviteUserPayload>(
      ["/api/users/invite", "/api/auth/users/invite"],
      {
        method: "POST",
        body: JSON.stringify({
          name: body.name,
          email: body.email,
          role: body.role,
        }),
      }
    );
    return {
      success: payload?.success !== false,
      message:
        typeof payload?.message === "string" && payload.message.trim()
          ? payload.message
          : "Invitation email sent successfully.",
      email:
        typeof payload?.email === "string" && payload.email.trim()
          ? payload.email.trim().toLowerCase()
          : body.email.trim().toLowerCase(),
    };
  },
  updateUser: async (userId: string, body: UserAdminUpdateInput) => {
    const payload = await requestFirstAvailable<unknown>(
      [`/api/users/${encodeURIComponent(userId)}`, `/api/auth/users/${encodeURIComponent(userId)}`],
      {
        method: "PATCH",
        body: JSON.stringify({
          ...body,
          is_active: body.isActive,
        }),
      }
    ).catch(async (error) => {
      if (!isEndpointUnavailableError(error)) throw error;
      return requestFirstAvailable<unknown>(
        [`/api/users/${encodeURIComponent(userId)}`, `/api/auth/users/${encodeURIComponent(userId)}`],
        {
          method: "PUT",
          body: JSON.stringify({
            ...body,
            is_active: body.isActive,
          }),
        }
      );
    });
    const record = normalizeUserAdminRecord(payload);
    if (!record) {
      throw new ApiError("Invalid user update response payload.", 500);
    }
    return record;
  },
  deactivateUser: async (userId: string) => {
    const encoded = encodeURIComponent(userId);
    try {
      const payload = await requestFirstAvailable<unknown>([
        `/api/users/${encoded}/deactivate`,
        `/api/auth/users/${encoded}/deactivate`,
      ], {
        method: "POST",
      });
      const record = normalizeUserAdminRecord(payload);
      if (record) return record;
    } catch (error) {
      if (!isEndpointUnavailableError(error)) throw error;
    }
    return api.updateUser(userId, { isActive: false });
  },
  softDeleteUser: async (userId: string) => {
    const encoded = encodeURIComponent(userId);
    try {
      return await requestFirstAvailable<{ success?: boolean }>([
        `/api/users/${encoded}`,
        `/api/auth/users/${encoded}`,
      ], {
        method: "DELETE",
      });
    } catch (error) {
      if (!isEndpointUnavailableError(error)) throw error;
      return requestFirstAvailable<{ success?: boolean }>([
        `/api/users/${encoded}/soft-delete`,
        `/api/auth/users/${encoded}/soft-delete`,
      ], {
        method: "POST",
      });
    }
  },
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
    }>(`/api/projects/${id}`, { method: "DELETE", timeoutMs: 45_000 }),
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
      const res = await fetchWithAuthRetry(`/api/projects/${id}/flow/from-text/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: controller.signal,
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
    const res = await fetchWithAuthRetry(`/api/projects/${id}/documents/upload`, {
      method: "POST",
      body: form,
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
      const res = await fetchWithAuthRetry("/api/copilot/query/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
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
    const res = await fetchWithAuthRetry(`/api/projects/${projectId}/tests/export.feature${q}`);
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
    const res = await fetchWithAuthRetry(`/api/projects/${projectId}/analyses/latest/exports/bdd/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || { scope: "all_final_generated" }),
    });
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
    const res = await fetchWithAuthRetry(`/api/projects/${projectId}/analyses/latest/exports/bdd`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || { scope: "all_final_generated" }),
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
