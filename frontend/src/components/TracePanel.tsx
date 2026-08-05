"use client";

import type { QACopilotResponse } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  complete: "bg-pine-600 text-white",
  error: "bg-signal-high text-white",
  skipped: "bg-brass-500/80 text-white",
  pending: "bg-mist-200 text-ink-700",
  running: "bg-mist-200 text-ink-700",
};

/** Map real orchestrator step names to demo-friendly labels without inventing events. */
function friendlyLabel(step: string): string {
  const s = step.toLowerCase();
  if (s.includes("model routing") || s.includes("model selection")) return "Model Routing";
  if (s.includes("complexity")) return "Complexity Assessment";
  if (s.includes("model escalation") || s.includes("escalation")) return "Model Escalation";
  if (s.includes("reviewer decision")) return "Reviewer Decision";
  if (s.includes("reviewer pass")) return "Reviewer Pass";
  if (s.includes("classify intent") || s.includes("intent")) return "Intent Classification";
  if (s.includes("traverse user flow") || (s.includes("graph") && s.includes("path")))
    return "Graph Retrieval";
  if (s.includes("vector") || s.includes("semantic")) return "Vector Retrieval";
  if (s.includes("plan retrieval") || s.includes("fused") || s.includes("context fusion"))
    return "Context Fusion";
  if (s.includes("initial test") || s.includes("test cases generated"))
    return "Initial Test Generation";
  if (s.includes("evidence") && s.includes("valid")) return "Evidence Validation";
  if (s.includes("critic")) return "Critic Review";
  if (s.includes("coverage gap analysis")) return "Coverage Gap Analysis";
  if (s.includes("gap priorit")) return "Gap Prioritization";
  if (s.includes("targeted regeneration") || s.includes("targeted test"))
    return "Targeted Test Generation";
  if (s.includes("coverage obligation")) return "Coverage Obligation Construction";
  if (s.includes("suite review")) return "Suite Review";
  if (s.includes("revision plan")) return "Revision Plan";
  if (s.includes("test revision")) return "Test Revision";
  if (s.includes("missing scenario")) return "Missing Scenario Generation";
  if (s.includes("coverage recalculation")) return "Coverage Recalculation";
  if (s.includes("convergence decision")) return "Convergence Decision";
  if (s.includes("final validation")) return "Final Validation";
  if (s.includes("coverage closure")) return "Coverage Closure";
  if (s.includes("dedup")) return "Deduplication";
  if (s.includes("final coverage")) return "Final Coverage";
  if (s.includes("quality pre-check") || s.includes("test quality")) return "Test Quality Pre-check";
  if (s.includes("automation feasibility") || s.includes("test review and automation"))
    return "Test Review and Automation Feasibility";
  if (s.includes("automation layer")) return "Automation Layer Recommendation";
  if (s.includes("test review validation")) return "Test Review Validation";
  if (s.includes("automation summary")) return "Automation Summary Aggregation";
  if (s.includes("test format selection") || s.includes("format selection")) return "Test Format Selection";
  if (s.includes("canonical test")) return "Canonical Test Generation";
  if (s.includes("standard test rendering")) return "Standard Test Rendering";
  if (s.includes("bdd scenario rendering") || s.includes("bdd rendering")) return "BDD Scenario Rendering";
  if (s.includes("bdd validation")) return "BDD Validation";
  if (s.includes("targeted bdd")) return "Targeted BDD Generation";
  if (s.includes("test format persistence") || s.includes("format persistence")) return "Test Format Persistence";
  if (s.includes("reuse persisted")) return "Reuse Persisted Tests";
  return step;
}

export function TracePanel({ result }: { result: QACopilotResponse | null }) {
  return (
    <section className="panel p-6">
      <div className="label">Agent Execution Trace</div>
      <h2 className="mt-2 font-display text-2xl">Visible orchestrator workflow</h2>
      <p className="mt-2 text-sm text-ink-700/75">
        Only steps that actually executed are listed. Skipped steps stay marked skipped — nothing is
        invented for the demo.
      </p>
      {!result ? (
        <p className="mt-4 text-sm text-ink-600/70">No analysis run for this project.</p>
      ) : (
        <ol className="mt-5 space-y-2">
          {(result.execution_trace || []).map((step, idx) => {
            const label = friendlyLabel(step.step);
            const showOriginal = label !== step.step;
            return (
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
                    <div className="font-medium text-ink-900">{label}</div>
                    <span className="rounded-full bg-mist-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-600/70">
                      {step.status}
                    </span>
                  </div>
                  {showOriginal ? (
                    <div className="mt-0.5 text-[11px] text-ink-600/50">{step.step}</div>
                  ) : null}
                  {step.detail ? (
                    <div className="mt-1 text-sm text-ink-700/75">{step.detail}</div>
                  ) : null}
                  {step.timestamp ? (
                    <div className="mt-1 text-[11px] text-ink-600/50">{step.timestamp}</div>
                  ) : null}
                </div>
              </li>
            );
          })}
          {(result.execution_trace || []).length === 0 ? (
            <p className="text-sm text-ink-600/70">Trace was empty for this response.</p>
          ) : null}
        </ol>
      )}
    </section>
  );
}
