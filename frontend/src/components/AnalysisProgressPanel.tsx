"use client";

import { Loader2 } from "lucide-react";
import {
  formatElapsed,
  progressRatio,
  PROGRESS_MILESTONES,
  type AnalysisProgressState,
} from "@/lib/workflow";

export function AnalysisProgressPanel({
  progress,
  onOpenResults,
  onOpenTrace,
}: {
  progress: AnalysisProgressState;
  onOpenResults?: () => void;
  onOpenTrace?: () => void;
}) {
  if (progress.status === "idle") return null;

  const ratio = progressRatio(progress);
  const determinate = ratio != null;
  const liveLabel =
    progress.status === "failed"
      ? "Analysis failed"
      : progress.status === "completed"
        ? "Analysis complete"
        : progress.currentStageLabel || "Starting analysis…";

  return (
    <section
      className="rounded-2xl border border-pine-700/20 bg-pine-700/5 p-4"
      aria-live="polite"
      aria-busy={progress.status === "running" || progress.status === "queued"}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
            Analysis progress
          </div>
          <div className="mt-1 flex items-center gap-2 text-sm font-medium text-pine-900">
            {(progress.status === "running" || progress.status === "queued") && (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            )}
            <span>{liveLabel}</span>
          </div>
          {progress.message ? (
            <p className="mt-1 text-xs text-ink-700/75">{progress.message}</p>
          ) : null}
        </div>
        <div className="text-right text-xs text-ink-600/70">
          <div>
            Elapsed:{" "}
            <span className="font-mono text-ink-900">{formatElapsed(progress.elapsedMs)}</span>
          </div>
          <div className="mt-0.5 capitalize">{progress.status}</div>
        </div>
      </div>

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-white/70"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={determinate ? Math.round((ratio || 0) * 100) : undefined}
        aria-label={liveLabel}
      >
        {determinate ? (
          <div
            className="h-full rounded-full bg-pine-700 transition-[width] duration-500"
            style={{ width: `${Math.round((ratio || 0) * 100)}%` }}
          />
        ) : (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-pine-700/70" />
        )}
      </div>

      <ol className="mt-3 grid gap-1 sm:grid-cols-2">
        {PROGRESS_MILESTONES.map((milestone) => {
          const done = progress.completedLabels.includes(milestone);
          const current = progress.currentStageLabel === milestone && !done;
          return (
            <li
              key={milestone}
              className={`rounded-lg px-2 py-1 text-[11px] ${
                done
                  ? "bg-pine-700/10 text-pine-800"
                  : current
                    ? "bg-brass-500/15 text-ink-900"
                    : "text-ink-600/55"
              }`}
            >
              {done ? "✓ " : current ? "→ " : "○ "}
              {milestone}
            </li>
          );
        })}
      </ol>

      <div className="mt-3 flex flex-wrap gap-2">
        {onOpenResults ? (
          <button type="button" className="btn-secondary text-xs" onClick={onOpenResults}>
            Open Analysis Results
          </button>
        ) : null}
        {onOpenTrace ? (
          <button type="button" className="btn-secondary text-xs" onClick={onOpenTrace}>
            Open Agent Trace
          </button>
        ) : null}
      </div>
    </section>
  );
}
