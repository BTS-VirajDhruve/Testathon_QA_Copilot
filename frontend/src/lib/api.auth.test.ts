import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { __resetAuthSessionForTests, getAuthSession, setAuthSession } from "./auth-session";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api auth session behavior", () => {
  beforeEach(() => {
    __resetAuthSessionForTests();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stores tokens on login and attaches bearer token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          access_token: "access-1",
          refresh_token: "refresh-1",
          user: { id: "u1", email: "qa@example.com", role: "admin" },
        })
      )
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    await api.authLogin({ email: "qa@example.com", password: "secret" });
    await api.listProjects();

    const listProjectsCall = fetchMock.mock.calls[1];
    const headers = new Headers((listProjectsCall[1] as RequestInit | undefined)?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-1");
    expect(getAuthSession().refreshToken).toBe("refresh-1");
  });

  it("refreshes once on 401 and retries request", async () => {
    setAuthSession({
      accessToken: "expired-access",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired token" }, 401))
      .mockResolvedValueOnce(
        jsonResponse({
          access_token: "access-2",
          refresh_token: "refresh-2",
        })
      )
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    await api.listProjects();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retryCall = fetchMock.mock.calls[2];
    const headers = new Headers((retryCall[1] as RequestInit | undefined)?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-2");
    expect(getAuthSession().refreshToken).toBe("refresh-2");
  });

  it("does not loop retries when refresh fails", async () => {
    setAuthSession({
      accessToken: "expired-access",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired token" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid refresh" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.listProjects()).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getAuthSession().accessToken).toBeNull();
    expect(getAuthSession().refreshToken).toBeNull();
  });

  it("logs out by revoking refresh token and clearing local session", async () => {
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ success: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api.authLogout();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0];
    const init = request[1] as RequestInit | undefined;
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain("refresh-1");
    expect(getAuthSession().accessToken).toBeNull();
    expect(getAuthSession().refreshToken).toBeNull();
    expect(getAuthSession().user).toBeNull();
  });

  it("still clears local session when logout API call fails", async () => {
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.authLogout()).rejects.toThrow("unauthorized");

    expect(getAuthSession().accessToken).toBeNull();
    expect(getAuthSession().refreshToken).toBeNull();
    expect(getAuthSession().user).toBeNull();
  });

  it("does not refresh/retry auth endpoints on 401", async () => {
    setAuthSession({
      accessToken: "expired-access",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired token" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.authMe()).rejects.toThrow("expired token");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reads authenticated profile from nested /me response", async () => {
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: null,
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        user: { id: "u1", email: "qa@example.com", role: "qa", name: "QA User" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = await api.authMe();

    expect(user.email).toBe("qa@example.com");
    expect(user.name).toBe("QA User");
    expect(getAuthSession().user?.email).toBe("qa@example.com");
  });

  it("updates profile and refreshes session user payload", async () => {
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com", name: "QA" },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        user: { id: "u1", email: "updated@example.com", name: "Updated QA", role: "qa" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = await api.authUpdateMe({ name: "Updated QA", email: "updated@example.com" });

    expect(user.email).toBe("updated@example.com");
    expect(getAuthSession().user?.name).toBe("Updated QA");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0];
    const init = request[1] as RequestInit | undefined;
    expect(init?.method).toBe("PATCH");
  });

  it("submits change-password with auth headers", async () => {
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ success: true }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.authChangePassword({
      currentPassword: "CurrentPass123!",
      newPassword: "NewPass123!",
    });

    expect(response.success).toBe(true);
    const request = fetchMock.mock.calls[0];
    const init = request[1] as RequestInit | undefined;
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain("currentPassword");
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-1");
  });

  it("submits forgot password without auth headers", async () => {
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        message: "If an account exists for this email, a reset link has been sent.",
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.authForgotPassword({ email: "qa@example.com" });

    expect(response.message).toContain("If an account exists for this email");
    const request = fetchMock.mock.calls[0];
    const init = request[1] as RequestInit | undefined;
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBeNull();
    expect(init?.method).toBe("POST");
  });

  it("uses neutral fallback message when forgot-password payload omits message", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.authForgotPassword({ email: "qa@example.com" });

    expect(response.message).toBe("If an account exists for this email, a reset link has been sent.");
  });

  it("resets password and returns success true by default", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.authResetPassword({
      token: "token-for-test-1234567890123456",
      newPassword: "UpdatedPass123!",
    });

    expect(response.success).toBe(true);
    const request = fetchMock.mock.calls[0];
    const init = request[1] as RequestInit | undefined;
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain("newPassword");
  });

  it("propagates reset token errors from backend", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid or expired reset token" }, 400));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.authResetPassword({
        token: "token-for-test-1234567890123456",
        newPassword: "UpdatedPass123!",
      })
    ).rejects.toThrow("Invalid or expired reset token");
  });
});
