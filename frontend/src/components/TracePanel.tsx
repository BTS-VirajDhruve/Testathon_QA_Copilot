"use client";

import type { QACopilotResponse } from "@/lib/types";

export function TracePanel({ result }: { result: QACopilotResponse | null }) {
  return (
    <section className="panel p-6">
      <div className="label">Agent Execution Trace</div>
      <h2 className="mt-2 font-display text-2xl">Visible orchestrator workflow</h2>
      {!result ? (
        <p className="mt-4 text-sm text-ink-600/70">Run a copilot query to see the agent trace.</p>
      ) : (
        <ol className="mt-5 space-y-2">
          {result.execution_trace.map((step, idx) => (
            <li
              key={`${step.step}-${idx}`}
              className="flex items-start gap-3 rounded-2xl border border-ink-700/10 bg-white/70 px-4 py-3"
            >
              <span
                className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ${
                  step.status === "complete"
                    ? "bg-pine-600 text-white"
                    : step.status === "error"
                      ? "bg-signal-high text-white"
                      : "bg-mist-200 text-ink-700"
                }`}
              >
                {step.status === "complete" ? "✓" : idx + 1}
              </span>
              <div>
                <div className="font-medium text-ink-900">{step.step}</div>
                {step.detail ? (
                  <div className="mt-1 text-sm text-ink-700/75">{step.detail}</div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}