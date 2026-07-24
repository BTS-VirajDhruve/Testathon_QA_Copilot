"use client";

import { FolderPlus, Loader2, Sparkles } from "lucide-react";
import type { Project } from "@/lib/types";

export function TopBar({
  projects,
  projectId,
  onProjectChange,
  onCreateProject,
  onSeed,
  status,
  busy,
}: {
  projects: Project[];
  projectId: string;
  onProjectChange: (id: string) => void;
  onCreateProject: () => void;
  onSeed: () => void;
  status: string;
  busy: boolean;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-ink-700/10 bg-mist-50/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-5 py-3">
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

        <div className="ml-4 hidden min-w-0 flex-1 items-center gap-3 md:flex">
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
          <button className="btn-secondary" onClick={onCreateProject}>
            <FolderPlus className="h-4 w-4" /> New
          </button>
          <button className="btn-brass" onClick={onSeed} disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Load demo
          </button>
        </div>

        <div className="ml-auto flex items-center gap-3 text-xs text-ink-600/70">
          <span className="hidden rounded-full border border-ink-700/10 bg-white/70 px-3 py-1 sm:inline">
            {status}
          </span>
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-pine-700 text-xs font-medium text-white">
            QA
          </div>
        </div>
      </div>
    </header>
  );
}