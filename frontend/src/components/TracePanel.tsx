"use client";

import type { QACopilotResponse } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  complete: "bg-pine-600 text-white",
  error: "bg-signal-high text-white",
  skipped: "bg-brass-500/80 text-white",
  pending: "bg-mist-200 text-ink-700",
  running: "bg-mist-200 text-ink-700",
};

export function TracePanel({ result }: { result: QACopilotResponse | null }) {
  return (
    <section className="panel p-6">
      <div className="label">Agent Execution Trace</div>
      <h2 className="mt-2 font-display text-2xl">Visible orchestrator workflow</h2>
      <p className="mt-2 text-sm text-ink-700/75">
        Only steps that actually executed are listed. Skipped steps are marked honestly.
      </p>
      {!result ? (
        <p className="mt-4 text-sm text-ink-600/70">Run a copilot query to see the agent trace.</p>
      ) : (
        <ol className="mt-5 space-y-2">
          {(result.execution_trace || []).map((step, idx) => (
            <li
              key={`${step.step}-${idx}`}
              className="flex items-start gap-3 rounded-2xl border border-ink-700/10 bg-white/70 px-4 py-3"
            >
              <span
                className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ${
                  STATUS_STYLES[step.status] || STATUS_STYLES.pending
                }`}
              >
                {step.status === "complete" ? "✓" : step.status === "skipped" ? "–" : idx + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="font-medium text-ink-900">{step.step}</div>
                  <span className="rounded-full bg-mist-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-600/70">
                    {step.status}
                  </span>
                </div>
                {step.detail ? (
                  <div className="mt-1 text-sm text-ink-700/75">{step.detail}</div>
                ) : null}
                {step.timestamp ? (
                  <div className="mt-1 text-[11px] text-ink-600/50">{step.timestamp}</div>
                ) : null}
              </div>
            </li>
          ))}
          {(result.execution_trace || []).length === 0 ? (
            <p className="text-sm text-ink-600/70">Trace was empty for this response.</p>
          ) : null}
        </ol>
      )}
    </section>
  );
}
