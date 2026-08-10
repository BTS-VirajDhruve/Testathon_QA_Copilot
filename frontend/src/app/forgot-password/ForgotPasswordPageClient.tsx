"use client";

import { FormEvent, useState } from "react";
import { ArrowLeft, Loader2, MailCheck } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import {
  FORGOT_PASSWORD_NEUTRAL_MESSAGE,
  normalizeForgotPasswordEmail,
  validateForgotPasswordEmail,
} from "@/lib/auth-password";

export function ForgotPasswordPageClient() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    const validationError = validateForgotPasswordEmail(email);
    if (validationError) {
      setError(validationError);
      return;
    }

    setBusy(true);
    try {
      const payload = await api.authForgotPassword({
        email: normalizeForgotPasswordEmail(email),
      });
      setSuccess(payload.message || FORGOT_PASSWORD_NEUTRAL_MESSAGE);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Unable to submit request right now. Please try again."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-hero-wash px-4">
      <div className="panel w-full max-w-md p-6">
        <h1 className="font-display text-2xl text-ink-900">Forgot password</h1>
        <p className="mt-2 text-sm text-ink-700/75">
          Enter your email and we will send a reset link if your account is eligible.
        </p>

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

          <button className="btn-primary w-full justify-center" type="submit" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MailCheck className="h-4 w-4" />}
            <span>{busy ? "Sending..." : "Send reset link"}</span>
          </button>
        </form>

        <div className="mt-4">
          <Link href="/login" className="btn-secondary inline-flex">
            <ArrowLeft className="h-4 w-4" /> Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
