"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { buildLoginHref } from "@/lib/auth-routing";
import { resolveAccountErrorMessage, validateAccountProfileInput } from "@/lib/auth-account";

export function AccountPageClient() {
  const router = useRouter();
  const pathname = usePathname() || "/account";
  const { status: authStatus, session, refreshSession } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!session.user) return;
    setName(session.user.name || "");
    setEmail(session.user.email || "");
  }, [session.user]);

  useEffect(() => {
    if (authStatus === "authenticated") return;
    if (typeof window === "undefined") return;
    router.replace(buildLoginHref(pathname, window.location.search));
  }, [authStatus, pathname, router]);

  const unchanged = useMemo(() => {
    const currentName = session.user?.name || "";
    const currentEmail = session.user?.email || "";
    return name.trim() === currentName.trim() && email.trim().toLowerCase() === currentEmail.toLowerCase();
  }, [email, name, session.user?.email, session.user?.name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const profileError = validateAccountProfileInput({ name, email });
    if (profileError) {
      setError(profileError);
      setSuccess(null);
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await api.authUpdateMe({
        name: name.trim(),
        email: email.trim().toLowerCase(),
      });
      await refreshSession();
      setSuccess("Profile updated successfully.");
    } catch (submitError) {
      setError(resolveAccountErrorMessage(submitError, "Unable to update your profile."));
    } finally {
      setSaving(false);
    }
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
            <h1 className="font-display text-3xl text-ink-900">My Profile</h1>
            <p className="mt-1 text-sm text-ink-700/70">Update your personal details.</p>
          </div>
          <Link href="/" className="btn-secondary">
            <ArrowLeft className="h-4 w-4" /> Back to workspace
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
              <span>Name</span>
              <input
                type="text"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="space-y-2 text-sm text-ink-700">
              <span>Email</span>
              <input
                type="email"
                className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-ink-900 shadow-sm outline-none transition focus:border-pine-500 focus:ring-2 focus:ring-pine-300"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={saving}
              />
            </label>

            <div className="pt-2">
              <button className="btn-primary" type="submit" disabled={saving || unchanged}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save profile
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}
