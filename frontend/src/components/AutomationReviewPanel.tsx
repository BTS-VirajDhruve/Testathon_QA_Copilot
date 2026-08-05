"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  AutomationSummary,
  QACopilotResponse,
  ReviewedTestCase,
  ValiditySummary,
} from "@/lib/types";

type ValidityFilter = "all" | "valid" | "invalid" | "needs_revision" | "insufficient_evidence";
type AutomationFilter =
  | "all"
  | "automate"
  | "automate_with_conditions"
  | "hybrid"
  | "manual"
  | "not_ready_for_automation"
  | "ui"
  | "api"
  | "integration"
  | "high_priority"
  | "low_effort";

const PRIORITY_RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  not_recommended: 4,
};
const EFFORT_RANK: Record<string, number> = { low: 0, medium: 1, high: 2, unknown: 3 };

function pillTone(value: string) {
  if (value === "valid" || value === "automate") return "bg-pine-700/10 text-pine-800";
  if (value === "needs_revision" || value === "automate_with_conditions")
    return "bg-brass-500/15 text-brass-900";
  if (value === "hybrid") return "bg-mist-200 text-ink-800";
  if (value === "manual" || value === "invalid") return "bg-ink-700/10 text-ink-800";
  return "bg-signal-high/10 text-signal-high";
}

function SummaryGrid({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; value: number }>;
}) {
  return (
    <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
      <div className="label">{title}</div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {items.map((item) => (
          <div key={item.label}>
            <div className="text-2xl font-display text-ink-900">{item.value}</div>
            <div className="text-xs text-ink-600/70">{item.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewCard({ item }: { item: ReviewedTestCase }) {
  const [open, setOpen] = useState(false);
  const tc = item.test_case;
  const vr = item.validity_review;
  const ar = item.automation_review;
  const mainValidity = vr.validity_reasons?.[0] || "No validity justification recorded.";
  const mainAutomation =
    ar?.automation_reasons?.[0] ||
    ar?.non_automation_reasons?.[0] ||
    "Automation feasibility is not available for this test.";

  return (
    <article className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-xs text-ink-600/60">{tc.test_case_id}</div>
          <h3 className="mt-1 font-medium text-ink-900">{tc.title}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="rounded-full bg-mist-100 px-2 py-0.5 text-[11px] uppercase tracking-wide text-ink-700">
            {tc.priority}
          </span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] uppercase tracking-wide ${pillTone(vr.validity)}`}>
            {vr.validity.replaceAll("_", " ")}
          </span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] uppercase tracking-wide ${pillTone(ar?.automation_suitability || "not_evaluated")}`}>
            {(ar?.automation_suitability || "not_evaluated").replaceAll("_", " ")}
          </span>
        </div>
      </div>

      <div className="mt-3 grid gap-2 text-sm text-ink-700 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Validity</div>
          <div>{vr.validity} · {vr.validity_score}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Automation</div>
          <div>{ar?.automation_suitability || "not_evaluated"}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Layer</div>
          <div>{ar?.recommended_layer || "none"}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Priority / Effort</div>
          <div>{ar?.automation_priority || "not_recommended"} · {ar?.estimated_effort || "unknown"}</div>
        </div>
      </div>

      <div className="mt-3 rounded-xl bg-mist-100/70 p-3 text-sm">
        <div className="label">Validity justification</div>
        <p className="mt-1 text-ink-800">{mainValidity}</p>
      </div>
      <div className="mt-2 rounded-xl bg-white/70 p-3 text-sm">
        <div className="label">Automation decision</div>
        <p className="mt-1 text-ink-800">{mainAutomation}</p>
      </div>

      <button
        type="button"
        className="mt-3 text-sm font-medium text-pine-800 underline-offset-2 hover:underline"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide details" : "Show details"}
      </button>

      {open ? (
        <div className="mt-3 space-y-3 border-t border-ink-700/10 pt-3 text-sm">
          {vr.quality_issues?.length ? (
            <div>
              <div className="label">Quality issues</div>
              <ul className="mt-1 list-disc pl-5 text-ink-800">
                {vr.quality_issues.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {vr.suggested_corrections?.length ? (
            <div>
              <div className="label">Suggested corrections</div>
              <ul className="mt-1 list-disc pl-5 text-ink-800">
                {vr.suggested_corrections.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {ar?.prerequisites?.length ? (
            <div>
              <div className="label">Prerequisites</div>
              <p className="mt-1 text-ink-800">{ar.prerequisites.join("; ")}</p>
            </div>
          ) : null}
          {ar?.blockers?.length ? (
            <div>
              <div className="label">Blockers</div>
              <p className="mt-1 text-ink-800">{ar.blockers.join("; ")}</p>
            </div>
          ) : null}
          {(ar?.test_data_requirements?.length || ar?.environment_requirements?.length) ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <div className="label">Data requirements</div>
                <p className="mt-1 text-ink-800">{(ar?.test_data_requirements || []).join("; ") || "—"}</p>
              </div>
              <div>
                <div className="label">Environment requirements</div>
                <p className="mt-1 text-ink-800">{(ar?.environment_requirements || []).join("; ") || "—"}</p>
              </div>
            </div>
          ) : null}
          {item.original_test_case ? (
            <div>
              <div className="label">Original vs reviewed test</div>
              <p className="mt-1 text-ink-600/80">Original: {item.original_test_case.title}</p>
              <p className="text-ink-900">Reviewed: {tc.title}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export function AutomationReviewPanel({
  result,
  projectId,
}: {
  result: QACopilotResponse | null;
  projectId: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<QACopilotResponse | null>(result);
  const [validityFilter, setValidityFilter] = useState<ValidityFilter>("all");
  const [automationFilter, setAutomationFilter] = useState<AutomationFilter>("all");

  useEffect(() => {
    setAnalysis(result);
  }, [result]);

  const reviewed = analysis?.reviewed_test_cases ?? [];
  const validitySummary: ValiditySummary | null = analysis?.validity_summary ?? null;
  const automationSummary: AutomationSummary | null = analysis?.automation_summary ?? null;
  const testCount = analysis?.test_cases?.length ?? 0;
  const validityStatus = analysis?.section_status?.test_validity_review?.status;
  const automationStatus = analysis?.section_status?.automation_feasibility_review?.status;

  const validityItems = useMemo(() => {
    return reviewed.filter((item) => {
      if (validityFilter === "all") return true;
      return item.validity_review.validity === validityFilter;
    });
  }, [reviewed, validityFilter]);

  const automationItems = useMemo(() => {
    let rows = reviewed.filter((item) => item.validity_review.validity === "valid");
    rows = rows.filter((item) => {
      const review = item.automation_review;
      if (!review) return false;
      if (automationFilter === "all") return true;
      if (automationFilter === "high_priority") {
        return ["critical", "high"].includes(review.automation_priority);
      }
      if (automationFilter === "low_effort") return review.estimated_effort === "low";
      if (["ui", "api", "integration"].includes(automationFilter)) {
        return review.recommended_layer === automationFilter;
      }
      return review.automation_suitability === automationFilter;
    });
    rows.sort((a, b) => {
      const ra = a.automation_review;
      const rb = b.automation_review;
      if (!ra || !rb) return 0;
      return (
        (PRIORITY_RANK[ra.automation_priority] ?? 9) -
        (PRIORITY_RANK[rb.automation_priority] ?? 9) ||
        (EFFORT_RANK[ra.estimated_effort] ?? 9) - (EFFORT_RANK[rb.estimated_effort] ?? 9)
      );
    });
    return rows;
  }, [reviewed, automationFilter]);

  async function reviewExisting() {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.runTestReview(projectId);
      setAnalysis(res.analysis);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    } finally {
      setBusy(false);
    }
  }

  async function refreshReview() {
    if (!projectId) return;
    try {
      const res = await api.testReview(projectId);
      setAnalysis(res.analysis);
    } catch {
      // Keep current view if review fetch fails.
    }
  }

  useEffect(() => {
    refreshReview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  let stateMessage: string | null = null;
  if (busy) {
    stateMessage = "Reviewing test validity...";
  } else if (error || validityStatus === "failed" || automationStatus === "failed") {
    stateMessage = `Test review failed. Original test cases are still available.${error ? ` ${error}` : ""}`;
  } else if (!testCount) {
    stateMessage = "No tests are available. Generate or import test cases first.";
  } else if (!reviewed.length) {
    stateMessage = `${testCount} tests are available but have not been reviewed.`;
  }

  return (
    <section className="panel space-y-4 p-6">
      <div>
        <div className="label">Automation Review</div>
        <h2 className="mt-2 font-display text-2xl">Validity-first review hierarchy</h2>
        <p className="mt-2 text-sm text-ink-700/75">
          Test validity is evaluated first. Automation feasibility is evaluated only for valid test cases.
        </p>
      </div>

      {stateMessage ? (
        <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4 text-sm text-ink-700">
          <p>{stateMessage}</p>
          {!busy && testCount > 0 && !reviewed.length ? (
            <button type="button" className="btn-secondary mt-3" onClick={reviewExisting}>
              Review Existing Tests
            </button>
          ) : null}
        </div>
      ) : null}

      {validitySummary ? (
        <SummaryGrid
          title="Step 1 — Test Validity"
          items={[
            { label: "Total Tests", value: validitySummary.total_tests },
            { label: "Valid", value: validitySummary.valid },
            { label: "Invalid", value: validitySummary.invalid },
            { label: "Needs Revision", value: validitySummary.needs_revision },
            { label: "Insufficient Evidence", value: validitySummary.insufficient_evidence },
          ]}
        />
      ) : null}

      {automationSummary ? (
        <SummaryGrid
          title="Step 2 — Automation Feasibility"
          items={[
            { label: "Valid Tests Evaluated", value: automationSummary.valid_tests_evaluated },
            { label: "Automate", value: automationSummary.automate },
            { label: "Conditional", value: automationSummary.automate_with_conditions },
            { label: "Hybrid", value: automationSummary.hybrid },
            { label: "Manual", value: automationSummary.manual + automationSummary.not_ready_for_automation },
          ]}
        />
      ) : null}

      {reviewed.length ? (
        <>
          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label">Step 1 — Test Validity</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(["all", "valid", "invalid", "needs_revision", "insufficient_evidence"] as ValidityFilter[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-full px-3 py-1 text-xs ${validityFilter === value ? "bg-pine-700 text-white" : "bg-mist-100 text-ink-700"}`}
                  onClick={() => setValidityFilter(value)}
                >
                  {value.replaceAll("_", " ")}
                </button>
              ))}
            </div>
            <div className="mt-3 grid gap-3">
              {validityItems.map((item) => (
                <ReviewCard key={`validity-${item.test_case.test_case_id}`} item={item} />
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
            <div className="label">Step 2 — Automation Feasibility</div>
            <p className="mt-2 text-sm text-ink-700/75">
              Automation feasibility is evaluated only for valid test cases.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(["all", "automate", "automate_with_conditions", "hybrid", "manual", "not_ready_for_automation", "ui", "api", "integration", "high_priority", "low_effort"] as AutomationFilter[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-full px-3 py-1 text-xs ${automationFilter === value ? "bg-pine-700 text-white" : "bg-mist-100 text-ink-700"}`}
                  onClick={() => setAutomationFilter(value)}
                >
                  {value.replaceAll("_", " ")}
                </button>
              ))}
            </div>
            <div className="mt-3 grid gap-3">
              {automationItems.map((item) => (
                <ReviewCard key={`automation-${item.test_case.test_case_id}`} item={item} />
              ))}
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

