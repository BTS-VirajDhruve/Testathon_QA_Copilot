export type AuthUser = {
  id: string;
  email: string;
  name?: string;
  role?: string;
  isActive?: boolean;
};

export type AuthSession = {
  accessToken: string | null;
  refreshToken: string | null;
  user: AuthUser | null;
};

const SESSION_STORAGE_KEY = "qa_copilot_auth_session";

const emptySession: AuthSession = {
  accessToken: null,
  refreshToken: null,
  user: null,
};

let sessionState: AuthSession = { ...emptySession };
const listeners = new Set<(session: AuthSession) => void>();
let hydrated = false;

function canUseStorage() {
  return typeof window !== "undefined" && !!window.localStorage;
}

function writeToStorage(next: AuthSession) {
  if (!canUseStorage()) return;
  if (!next.accessToken && !next.refreshToken && !next.user) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(next));
}

function readFromStorage(): AuthSession {
  if (!canUseStorage()) return { ...emptySession };
  const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) return { ...emptySession };
  try {
    const parsed = JSON.parse(raw) as Partial<AuthSession>;
    return {
      accessToken: parsed.accessToken || null,
      refreshToken: parsed.refreshToken || null,
      user: parsed.user || null,
    };
  } catch {
    return { ...emptySession };
  }
}

function emit() {
  for (const listener of listeners) listener(getAuthSession());
}

export function hydrateAuthSession() {
  if (hydrated) return getAuthSession();
  hydrated = true;
  sessionState = readFromStorage();
  emit();
  return getAuthSession();
}

export function getAuthSession(): AuthSession {
  return {
    accessToken: sessionState.accessToken,
    refreshToken: sessionState.refreshToken,
    user: sessionState.user,
  };
}

export function setAuthSession(update: Partial<AuthSession>) {
  const next: AuthSession = {
    accessToken: update.accessToken ?? sessionState.accessToken ?? null,
    refreshToken: update.refreshToken ?? sessionState.refreshToken ?? null,
    user: update.user ?? sessionState.user ?? null,
  };
  sessionState = next;
  writeToStorage(next);
  emit();
}

export function clearAuthSession() {
  sessionState = { ...emptySession };
  writeToStorage(sessionState);
  emit();
}

export function subscribeAuthSession(listener: (session: AuthSession) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function __resetAuthSessionForTests() {
  hydrated = false;
  sessionState = { ...emptySession };
  listeners.clear();
}
