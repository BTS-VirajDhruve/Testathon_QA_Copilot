"use client";

import { FormEvent, useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import {
  getResetPasswordErrorMessage,
  resolveResetToken,
  validateResetPasswordForm,
} from "@/lib/auth-password";

export function ResetPasswordPageClient() {
  const searchParams = useSearchParams();
  const token = useMemo(() => resolveResetToken(searchParams.get("token")), [searchParams]);
  const hasToken = token.length > 0;

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    const validationError = validateResetPasswordForm({
      token,
      newPassword,
      confirmPassword,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setBusy(true);
    try {
      await api.authResetPassword({
        token,
        newPassword,
      });
      setSuccess("Password reset successful. Sign in with your new password.");
      setNewPassword("");
      setConfirmPassword("");
    } catch (submitError) {
      setError(getResetPasswordErrorMessage(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-hero-wash px-4">
      <div className="panel w-full max-w-md p-6">
        <h1 className="font-display text-2xl text-ink-900">Reset password</h1>
        <p className="mt-2 text-sm text-ink-700/75">
          Set a new password for your account using the reset link token.
        </p>

        {!hasToken && !success && (
          <div className="mt-4 rounded-xl border border-signal-high/30 bg-signal-high/10 px-4 py-3 text-sm text-signal-high">
            This reset link is missing a token. Request a new reset link.
          </div>
        )}

        {(error || success) && (
          <div
            className={`mt-4 rounded-xl border px-4 py-3 text-sm ${
              error
                ? "border-signal-high/30 bg-signal-high/10 text-signal-high"
                : "border-pine-700/20 bg-pine-700/10 text-pine-800"
            }`}
          >
            {error || success}
          </div>
        )}

        {!success && (
          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <label className="block space-y-2 text-sm text-ink-700">
              <span>New password</span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </label>

            <label className="block space-y-2 text-sm text-ink-700">
              <span>Confirm password</span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
            </label>

            <button className="btn-primary w-full justify-center" type="submit" disabled={busy || !hasToken}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
              <span>{busy ? "Resetting..." : "Reset password"}</span>
            </button>
          </form>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <Link href="/login" className="btn-secondary inline-flex">
            <ArrowLeft className="h-4 w-4" /> Back to sign in
          </Link>
          {success && (
            <Link href="/login" className="btn-primary inline-flex">
              <CheckCircle2 className="h-4 w-4" /> Continue to sign in
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
