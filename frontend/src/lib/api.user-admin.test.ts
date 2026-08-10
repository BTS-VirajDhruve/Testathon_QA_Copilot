import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { __resetAuthSessionForTests, setAuthSession } from "./auth-session";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api user admin methods", () => {
  beforeEach(() => {
    __resetAuthSessionForTests();
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u-admin", email: "admin@example.com", role: "admin" },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("falls back to /api/auth/users when /api/users is unavailable", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404))
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: "u1",
            name: "QA User",
            email: "qa@example.com",
            role: "qa",
            is_active: true,
          },
        ])
      );
    vi.stubGlobal("fetch", fetchMock);

    const users = await api.listUsers();

    expect(users).toHaveLength(1);
    expect(users[0]?.email).toBe("qa@example.com");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/users");
  });

  it("soft deletes with fallback endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "method not allowed" }, 405))
      .mockResolvedValueOnce(jsonResponse({ detail: "method not allowed" }, 405))
      .mockResolvedValueOnce(jsonResponse({ success: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api.softDeleteUser("u2");

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/users/u2");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/users/u2");
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain("/api/users/u2/soft-delete");
  });

  it("surfaces a consistent error when user admin endpoints are absent", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.listUsers()).rejects.toMatchObject<ApiError>({
      code: "USER_ADMIN_ENDPOINT_UNAVAILABLE",
      status: 501,
    });
  });
});
