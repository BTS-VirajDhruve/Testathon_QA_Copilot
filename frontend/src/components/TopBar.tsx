"use client";

import { useEffect, useState } from "react";
import { FolderPlus, Loader2, Sparkles } from "lucide-react";
import type { HealthStatus, Project } from "@/lib/types";

export function TopBar({
  projects,
  projectId,
  onProjectChange,
  onCreateProject,
  onSeed,
  status,
  busy,
  health,
}: {
  projects: Project[];
  projectId: string;
  onProjectChange: (id: string) => void;
  onCreateProject: () => void;
  onSeed: () => void;
  status: string;
  busy: boolean;
  health: HealthStatus | null;
}) {
  const [showDiag, setShowDiag] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-ink-700/10 bg-mist-50/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink-900 text-brass-400">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <div className="font-display text-lg leading-none tracking-tight">QA Copilot</div>
            <div className="mt-1 text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
              Graph · Vector · Agents
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 md:ml-4">
          <select
            className="w-full max-w-sm rounded-xl border border-ink-700/15 bg-white/80 px-3 py-2 text-sm outline-none focus:border-pine-500"
            value={projectId}
            onChange={(e) => onProjectChange(e.target.value)}
          >
            <option value="">Select project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button className="btn-secondary" onClick={onCreateProject} disabled={busy}>
            <FolderPlus className="h-4 w-4" /> New
          </button>
          <button className="btn-brass" onClick={onSeed} disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Load Demo Project
          </button>
        </div>

        <div className="ml-auto flex items-center gap-2 text-xs text-ink-600/70">
          <button
            type="button"
            className="hidden rounded-full border border-ink-700/10 bg-white/70 px-3 py-1 sm:inline"
            onClick={() => setShowDiag((v) => !v)}
            title="Runtime diagnostics"
          >
            {status}
          </button>
          {health ? (
            <span
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                health.openai_client_ready
                  ? "bg-pine-700/10 text-pine-700"
                  : "bg-brass-500/15 text-brass-700"
              }`}
            >
              {health.openai_client_ready ? "OpenAI ready" : "Deterministic fallback"}
            </span>
          ) : null}
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-pine-700 text-xs font-medium text-white">
            QA
          </div>
        </div>
      </div>
      {showDiag && health ? (
        <div className="border-t border-ink-700/10 bg-white/90 px-5 py-2 text-xs text-ink-700/80">
          <span className="mr-4">OpenAI configured: {health.openai_configured ? "yes" : "no"}</span>
          <span className="mr-4">Vector: {health.vector_store_mode || "—"}</span>
          <span className="mr-4">Graph: {health.graph_store_mode || "—"}</span>
          <span>Fallback: {health.demo_fallback ? "enabled" : "disabled"}</span>
        </div>
      ) : null}
    </header>
  );
}
