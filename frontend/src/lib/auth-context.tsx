"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  type AuthSession,
  clearAuthSession,
  getAuthSession,
  hydrateAuthSession,
  setAuthSession,
  subscribeAuthSession,
} from "@/lib/auth-session";
import { ApiError, api } from "@/lib/api";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  status: AuthStatus;
  session: AuthSession;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function statusFromSession(session: AuthSession): AuthStatus {
  return session.accessToken && session.refreshToken ? "authenticated" : "unauthenticated";
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSessionState] = useState<AuthSession>(() => getAuthSession());
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const initial = hydrateAuthSession();
    setSessionState(initial);
    setStatus(statusFromSession(initial));
    const unsubscribe = subscribeAuthSession((next) => {
      setSessionState(next);
      setStatus(statusFromSession(next));
    });
    return unsubscribe;
  }, []);

  const bootstrap = useCallback(async () => {
    const current = getAuthSession();
    if (!current.refreshToken && !current.accessToken) {
      clearAuthSession();
      setError(null);
      return;
    }

    try {
      let user = current.user;
      if (!user) {
        user = await api.authMe();
      }
      setAuthSession({ user });
      setError(null);
    } catch (err) {
      const shouldTryRefresh = err instanceof ApiError && err.status === 401;
      if (!shouldTryRefresh) {
        clearAuthSession();
        setError(getErrorMessage(err, "Unable to validate session."));
        return;
      }
      try {
        await api.authRefresh();
        const user = await api.authMe();
        setAuthSession({ user });
        setError(null);
      } catch (refreshErr) {
        clearAuthSession();
        setError(getErrorMessage(refreshErr, "Session expired. Please log in again."));
      }
    }
  }, []);

  useEffect(() => {
    if (status === "loading") return;
    void bootstrap();
  }, [bootstrap, status]);

  const login = useCallback(async (email: string, password: string) => {
    setError(null);
    try {
      const payload = await api.authLogin({ email, password });
      setAuthSession({
        accessToken: payload.accessToken,
        refreshToken: payload.refreshToken,
        user: payload.user ?? null,
      });
      if (!payload.user) {
        const user = await api.authMe();
        setAuthSession({ user });
      }
    } catch (err) {
      setError(getErrorMessage(err, "Login failed."));
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    setError(null);
    try {
      await api.authLogout();
    } catch {
      // Logout should still clear local session if API call fails.
    } finally {
      clearAuthSession();
    }
  }, []);

  const refreshSession = useCallback(async () => {
    setError(null);
    try {
      await api.authRefresh();
      const user = await api.authMe();
      setAuthSession({ user });
    } catch (err) {
      clearAuthSession();
      setError(getErrorMessage(err, "Session refresh failed."));
      throw err;
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, session, error, login, logout, refreshSession }),
    [error, login, logout, refreshSession, session, status]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
