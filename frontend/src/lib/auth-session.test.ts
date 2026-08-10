import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetAuthSessionForTests,
  clearAuthSession,
  getAuthSession,
  hydrateAuthSession,
  setAuthSession,
} from "./auth-session";

const SESSION_STORAGE_KEY = "qa_copilot_auth_session";

function createWindowWithStorage(initialValue?: string) {
  const storage = new Map<string, string>();
  if (initialValue !== undefined) {
    storage.set(SESSION_STORAGE_KEY, initialValue);
  }
  return {
    localStorage: {
      getItem(key: string) {
        return storage.has(key) ? storage.get(key)! : null;
      },
      setItem(key: string, value: string) {
        storage.set(key, value);
      },
      removeItem(key: string) {
        storage.delete(key);
      },
    },
  };
}

describe("auth session storage bootstrap", () => {
  beforeEach(() => {
    __resetAuthSessionForTests();
  });

  afterEach(() => {
    __resetAuthSessionForTests();
    vi.unstubAllGlobals();
  });

  it("hydrates session from local storage", () => {
    vi.stubGlobal(
      "window",
      createWindowWithStorage(
        JSON.stringify({
          accessToken: "stored-access",
          refreshToken: "stored-refresh",
          user: { id: "u1", email: "stored@example.com", role: "admin" },
        })
      )
    );

    const hydrated = hydrateAuthSession();

    expect(hydrated.accessToken).toBe("stored-access");
    expect(hydrated.refreshToken).toBe("stored-refresh");
    expect(hydrated.user?.email).toBe("stored@example.com");
  });

  it("writes updates to local storage and clears them", () => {
    const windowMock = createWindowWithStorage();
    vi.stubGlobal("window", windowMock);

    hydrateAuthSession();
    setAuthSession({
      accessToken: "access-1",
      refreshToken: "refresh-1",
      user: { id: "u1", email: "qa@example.com" },
    });

    expect(windowMock.localStorage.getItem(SESSION_STORAGE_KEY)).toContain("access-1");
    clearAuthSession();
    expect(windowMock.localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(getAuthSession().accessToken).toBeNull();
  });

  it("falls back to empty session when storage is invalid JSON", () => {
    vi.stubGlobal("window", createWindowWithStorage("not-json"));

    const hydrated = hydrateAuthSession();

    expect(hydrated.accessToken).toBeNull();
    expect(hydrated.refreshToken).toBeNull();
    expect(hydrated.user).toBeNull();
  });
});
