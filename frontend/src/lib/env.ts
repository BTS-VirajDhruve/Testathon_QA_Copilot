const DEFAULT_API_URL = "http://localhost:8000";

export type PublicEnv = {
  apiUrl: string;
};

function normalizeApiUrl(value?: string): string {
  const trimmed = value?.trim();
  if (!trimmed) return DEFAULT_API_URL;
  return trimmed.replace(/\/+$/, "");
}

export function getPublicEnv(): PublicEnv {
  return {
    apiUrl: normalizeApiUrl(process.env.NEXT_PUBLIC_API_URL),
  };
}

export const publicEnv = getPublicEnv();
