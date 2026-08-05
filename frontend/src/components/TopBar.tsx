"use client";

import { useEffect, useRef, useState } from "react";
import { FolderPlus, Loader2, MoreVertical, Sparkles, Trash2 } from "lucide-react";
import type { HealthStatus, Project } from "@/lib/types";

export function TopBar({
  projects,
  projectId,
  onProjectChange,
  onCreateProject,
  onDeleteProject,
  status,
  busy,
  health,
  apiUrl,
}: {
  projects: Project[];
  projectId: string;
  onProjectChange: (id: string) => void;
  onCreateProject: () => void;
  onDeleteProject: (id: string) => Promise<void> | void;
  status: string;
  busy: boolean;
  health: HealthStatus | null;
  apiUrl?: string;
}) {
  const [showDiag, setShowDiag] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const selected = projects.find((p) => p.id === projectId) || null;

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    if (menuOpen) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  async function confirmDelete() {
    if (!selected) return;
    setDeleting(true);
    try {
      await onDeleteProject(selected.id);
      setConfirmOpen(false);
    } finally {
      setDeleting(false);
    }
  }

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

          <div className="relative" ref={menuRef}>
            <button
              type="button"
              className="btn-secondary px-2.5"
              disabled={busy || !projectId}
              onClick={() => setMenuOpen((v) => !v)}
              title="Project actions"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreVertical className="h-4 w-4" />
            </button>
            {menuOpen ? (
              <div
                role="menu"
                className="absolute left-0 z-40 mt-1 min-w-[180px] rounded-xl border border-ink-700/10 bg-white py-1 shadow-soft"
              >
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-signal-high hover:bg-signal-high/10"
                  onClick={() => {
                    setMenuOpen(false);
                    setConfirmOpen(true);
                  }}
                >
                  <Trash2 className="h-4 w-4" /> Delete Project
                </button>
              </div>
            ) : null}
          </div>

          <button className="btn-secondary" onClick={onCreateProject} disabled={busy}>
            <FolderPlus className="h-4 w-4" /> New
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
      {showDiag ? (
        <div className="border-t border-ink-700/10 bg-white/90 px-5 py-2 text-xs text-ink-700/80">
          {apiUrl ? <span className="mr-4">API: {apiUrl}</span> : null}
          {health ? (
            <>
              <span className="mr-4">OpenAI configured: {health.openai_configured ? "yes" : "no"}</span>
              <span className="mr-4">Vector: {health.vector_store_mode || "—"}</span>
              <span className="mr-4">Graph: {health.graph_store_mode || "—"}</span>
              <span>Fallback: {health.demo_fallback ? "enabled" : "disabled"}</span>
            </>
          ) : (
            <span>Health unavailable</span>
          )}
        </div>
      ) : null}

      {confirmOpen && selected ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-project-title"
        >
          <div className="w-full max-w-md rounded-2xl border border-ink-700/10 bg-white p-6 shadow-soft">
            <h2 id="delete-project-title" className="font-display text-2xl text-ink-900">
              Delete Project
            </h2>
            <p className="mt-3 text-sm text-ink-700/85">
              You are about to permanently delete:
            </p>
            <p className="mt-1 text-sm font-semibold text-ink-900">{selected.name}</p>
            <p className="mt-4 text-sm text-ink-700/85">This will remove:</p>
            <ul className="mt-2 space-y-1 text-sm text-ink-700/80">
              <li>• Graph</li>
              <li>• Knowledge</li>
              <li>• Tests</li>
              <li>• Bugs</li>
              <li>• Coverage</li>
              <li>• Analysis</li>
              <li>• Agent Trace</li>
              <li>• Evidence</li>
            </ul>
            <p className="mt-4 text-sm font-medium text-signal-high">
              This action cannot be undone.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                disabled={deleting}
                onClick={() => setConfirmOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={deleting}
                onClick={confirmDelete}
              >
                {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                Delete
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
