"use client";

import type { EvidenceReference, TestCase } from "@/lib/types";

function methodLabel(method?: string | null) {
  if (method === "llm") return "LLM (OpenAI)";
  if (method === "deterministic_fallback") return "Deterministic fallback";
  if (method === "critic") return "Critic-targeted (gap closure)";
  if (method === "agent") return "Initial generation";
  if (method === "manual") return "Manual / curated";
  return method || null;
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

export function TestCaseEvidenceCard({
  tc,
  emphasizeWhy = false,
}: {
  tc: TestCase;
  emphasizeWhy?: boolean;
}) {
  const method = methodLabel(tc.generation_method);
  const why = tc.reasoning || tc.graph_reasoning;
  const evidence = tc.evidence || [];
  const groups = groupEvidence(evidence);
  const isTargeted = tc.generation_method === "critic" || Boolean(tc.closes_gap_title);
  const branch =
    tc.graph_path && tc.graph_path.length > 1 ? tc.graph_path[1] : tc.graph_path?.[0];

  const whyBlock = (
    <div
      className={`mt-3 rounded-xl px-3 py-2 ${
        emphasizeWhy || isTargeted
          ? "border border-pine-700/25 bg-pine-700/5"
          : "bg-mist-100/80"
      }`}
    >
      <div className="label">Why did the AI generate this test?</div>
      {isTargeted && tc.closes_gap_title ? (
        <p className="mt-2 rounded-lg border border-pine-700/20 bg-white/80 px-2.5 py-2 text-sm font-semibold text-pine-900">
          Generated to address coverage gap: {tc.closes_gap_title}
        </p>
      ) : null}
      {why ? <p className="mt-2 text-sm leading-relaxed text-ink-800">{why}</p> : (
        <p className="mt-2 text-sm text-ink-600/70">No reasoning provided for this test.</p>
      )}
      {tc.graph_path?.length ? (
        <div className="mt-2">
          <div className="text-[11px] font-medium uppercase tracking-wide text-ink-600/70">Graph path</div>
          <div className="mt-0.5 font-mono text-xs text-pine-700">{tc.graph_path.join(" → ")}</div>
          {branch ? (
            <div className="mt-1 text-xs text-ink-600/70">Feature branch: {branch}</div>
          ) : null}
        </div>
      ) : null}
      {method ? (
        <p className="mt-2 text-xs text-ink-600/80">
          Generation method: <span className="font-semibold text-ink-800">{method}</span>
          {tc.closes_gap_id ? (
            <span className="ml-2 font-mono text-[10px] text-ink-600/50">({tc.closes_gap_id})</span>
          ) : null}
        </p>
      ) : null}
    </div>
  );

  return (
    <article
      className={`rounded-2xl border bg-white/70 p-4 ${
        isTargeted ? "border-pine-700/25 ring-1 ring-pine-700/10" : "border-ink-700/10"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-xs text-ink-600/60">{tc.test_case_id}</div>
          <h3 className="mt-1 font-medium text-ink-900">{tc.title}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] uppercase tracking-wide ${
              isTargeted ? "bg-pine-700/10 text-pine-800" : "bg-mist-100 text-ink-700"
            }`}
          >
            {isTargeted ? "Targeted" : "Initial"}
          </span>
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

      {(emphasizeWhy || isTargeted) && whyBlock}

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

      {!emphasizeWhy && !isTargeted && whyBlock}

      {!isTargeted && (tc.closes_gap_title || tc.closes_gap_id) ? (
        <div className="mt-3 rounded-xl border border-pine-700/20 bg-pine-700/5 px-3 py-2">
          <div className="label">Coverage gap addressed</div>
          <p className="mt-1 text-sm text-ink-800">{tc.closes_gap_title || tc.closes_gap_id}</p>
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
                    {e.source_title || e.source_id || e.source_type}
                    {e.relevance ? ` — ${e.relevance}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-600/60">No structured evidence attached to this case.</p>
      )}
    </article>
  );
}
