"use client";

import type { EvidenceReference, TestCase } from "@/lib/types";

function methodLabel(method?: string | null) {
  if (method === "llm") return "LLM";
  if (method === "deterministic_fallback") return "Deterministic fallback";
  if (method === "critic") return "Critic";
  return null;
}

function groupEvidence(evidence: EvidenceReference[]) {
  const groups: Record<string, EvidenceReference[]> = {};
  for (const e of evidence) {
    const key = e.source_type || "other";
    groups[key] = groups[key] || [];
    groups[key].push(e);
  }
  return groups;
}

const GROUP_LABELS: Record<string, string> = {
  graph: "Graph context",
  requirement: "Requirements",
  existing_test: "Existing tests",
  historical_bug: "Historical bugs",
  risk: "Risk context",
  coverage_gap: "Coverage gaps",
};

export function TestCaseEvidenceCard({ tc }: { tc: TestCase }) {
  const method = methodLabel(tc.generation_method);
  const why = tc.reasoning || tc.graph_reasoning;
  const evidence = tc.evidence || [];
  const groups = groupEvidence(evidence);
  const branch =
    tc.graph_path && tc.graph_path.length > 1 ? tc.graph_path[1] : tc.graph_path?.[0];

  return (
    <article className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-xs text-ink-600/60">{tc.test_case_id}</div>
          <h3 className="mt-1 font-medium text-ink-900">{tc.title}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="rounded-full bg-mist-100 px-2 py-0.5 text-[11px] uppercase tracking-wide">
            {tc.priority}
          </span>
          <span className="rounded-full bg-mist-100 px-2 py-0.5 text-[11px] uppercase tracking-wide">
            risk {tc.risk}
          </span>
          {method ? (
            <span className="rounded-full bg-pine-700/10 px-2 py-0.5 text-[11px] uppercase tracking-wide text-pine-700">
              {method}
            </span>
          ) : null}
        </div>
      </div>

      {tc.steps?.length ? (
        <div className="mt-3">
          <div className="label">Steps</div>
          <ol className="mt-1 list-decimal space-y-1 pl-4 text-sm text-ink-700/80">
            {tc.steps.slice(0, 6).map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
        </div>
      ) : null}

      {tc.expected_result ? (
        <div className="mt-3">
          <div className="label">Expected result</div>
          <p className="mt-1 text-sm text-ink-700/80">{tc.expected_result}</p>
        </div>
      ) : null}

      {why ? (
        <div className="mt-3 rounded-xl bg-mist-100/80 px-3 py-2">
          <div className="label">Why this test exists</div>
          <p className="mt-1 text-sm text-ink-800">{why}</p>
        </div>
      ) : null}

      {tc.graph_path?.length ? (
        <div className="mt-3">
          <div className="label">Graph context</div>
          <div className="mt-1 font-mono text-xs text-pine-700">
            {tc.graph_path.join(" → ")}
          </div>
          {branch ? (
            <div className="mt-1 text-xs text-ink-600/70">Feature branch: {branch}</div>
          ) : null}
        </div>
      ) : null}

      {Object.keys(groups).length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="label">Supporting evidence</div>
          {Object.entries(groups).map(([type, items]) => (
            <div key={type}>
              <div className="text-[11px] font-medium uppercase tracking-wide text-ink-600/70">
                {GROUP_LABELS[type] || type}
              </div>
              <ul className="mt-1 space-y-1 text-xs text-ink-700/80">
                {items.map((e, i) => (
                  <li key={`${e.source_type}-${e.source_id}-${e.source_title}-${i}`}>
                    • {e.source_title || e.source_id || e.source_type}
                    {e.source_id ? (
                      <span className="text-ink-600/50"> ({e.source_id})</span>
                    ) : null}
                    {e.relevance ? (
                      <span className="block pl-3 text-ink-600/65">{e.relevance}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : tc.source_references?.length ? (
        <div className="mt-3 text-xs text-ink-600/70">
          Sources: {tc.source_references.join(" · ")}
        </div>
      ) : null}

      <div className="mt-3 text-xs text-ink-600/60">Confidence: {tc.confidence}</div>
    </article>
  );
}
