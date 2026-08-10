"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft, KeyRound, Loader2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { buildLoginHref } from "@/lib/auth-routing";
import { resolveAccountErrorMessage, validateAccountPasswordInput } from "@/lib/auth-account";
import { AuthSessionShimmer } from "@/components/AuthSessionShimmer";

export function ChangePasswordPageClient() {
  const router = useRouter();
  const pathname = usePathname() || "/account/change-password";
  const { status: authStatus } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (authStatus !== "unauthenticated") return;
    if (typeof window === "undefined") return;
    router.replace(buildLoginHref(pathname, window.location.search));
  }, [authStatus, pathname, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const validationError = validateAccountPasswordInput({
      currentPassword,
      newPassword,
      confirmPassword,
    });
    if (validationError) {
      setError(validationError);
      setSuccess(null);
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await api.authChangePassword({
        currentPassword,
        newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSuccess("Password changed successfully.");
    } catch (submitError) {
      setError(resolveAccountErrorMessage(submitError, "Unable to change password."));
    } finally {
      setSaving(false);
    }
  }

  if (authStatus === "loading") {
    return <AuthSessionShimmer />;
  }

  if (authStatus !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-hero-wash">
        <div className="panel flex items-center gap-3 px-6 py-5 text-sm text-ink-700/80">
          <Loader2 className="h-5 w-5 animate-spin text-pine-700" />
          Redirecting to login...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-hero-wash px-5 py-8">
      <div className="mx-auto max-w-3xl space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl text-ink-900">Change Password</h1>
            <p className="mt-1 text-sm text-ink-700/70">
              Confirm your current password before setting a new one.
            </p>
          </div>
          <Link href="/account" className="btn-secondary">
            <ArrowLeft className="h-4 w-4" /> Back to profile
          </Link>
        </div>

        {(error || success) && (
          <div
            className={`rounded-2xl border px-4 py-3 text-sm ${
              error
                ? "border-signal-high/30 bg-signal-high/10 text-signal-high"
                : "border-pine-700/20 bg-pine-700/10 text-pine-800"
            }`}
          >
            {error || success}
          </div>
        )}

        <section className="panel p-6">
          <form className="grid gap-4" onSubmit={handleSubmit}>
            <label className="space-y-2 text-sm text-ink-700">
              <span>Current password</span>
              <input
                type="password"
                autoComplete="current-password"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="space-y-2 text-sm text-ink-700">
              <span>New password</span>
              <input
                type="password"
                autoComplete="new-password"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="space-y-2 text-sm text-ink-700">
              <span>Confirm new password</span>
              <input
                type="password"
                autoComplete="new-password"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                disabled={saving}
              />
            </label>
            <div className="pt-2">
              <button className="btn-primary" type="submit" disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
                Update password
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}
