"use client";

import { Loader2 } from "lucide-react";

export function AuthSessionShimmer() {
  return (
    <div
      className="fixed inset-0 z-50 flex min-h-screen items-center justify-center bg-hero-wash"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Checking session"
    >
      <div className="auth-loader-shimmer flex h-16 w-16 items-center justify-center rounded-full">
        <Loader2 className="h-8 w-8 animate-spin text-pine-700" aria-hidden="true" />
      </div>
    </div>
  );
}
