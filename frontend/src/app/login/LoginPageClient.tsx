"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Loader2, LogIn } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthSessionShimmer } from "@/components/AuthSessionShimmer";
import { useAuth } from "@/lib/auth-context";
import { resolvePostLoginRedirect } from "@/lib/auth-routing";

export function LoginPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { status, login, error: authError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const redirectTo = useMemo(
    () => resolvePostLoginRedirect(searchParams.get("redirect")),
    [searchParams]
  );

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(redirectTo || "/");
    }
  }, [redirectTo, router, status]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace(redirectTo || "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to login.");
    } finally {
      setBusy(false);
    }
  }

  if (status === "loading" || status === "authenticated") {
    return <AuthSessionShimmer />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-hero-wash px-4">
      <div className="panel w-full max-w-md p-6">
        <h1 className="font-display text-2xl text-ink-900">Sign in</h1>
        <p className="mt-2 text-sm text-ink-700/75">
          Use your account to continue to Agentic QA Copilot.
        </p>

        {(error || authError) && (
          <div className="mt-4 rounded-xl border border-signal-high/30 bg-signal-high/10 px-4 py-3 text-sm text-signal-high">
            {error || authError}
          </div>
        )}

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block space-y-2 text-sm text-ink-700">
            <span>Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <label className="block space-y-2 text-sm text-ink-700">
            <span>Password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <button className="btn-primary w-full justify-center" type="submit" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
            <span>{busy ? "Signing in..." : "Sign in"}</span>
          </button>
          <div className="text-right text-sm">
            <Link className="text-pine-800 underline-offset-2 hover:underline" href="/forgot-password">
              Forgot password?
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
