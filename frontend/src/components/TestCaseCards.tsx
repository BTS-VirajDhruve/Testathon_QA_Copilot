"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import type { BDDScenario, ReviewedTestCase, TestCase } from "@/lib/types";

export type CompactTestItem = {
  id: string;
  title: string;
  feature?: string;
  category?: string;
  priority?: string;
  source?: string;
  validity?: string | null;
  automation?: string | null;
  standard?: TestCase | null;
  bdd?: BDDScenario | null;
  reviewed?: ReviewedTestCase | null;
};

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  const cls =
    tone === "good"
      ? "bg-pine-700/10 text-pine-800"
      : tone === "warn"
        ? "bg-amber-500/15 text-amber-900"
        : tone === "bad"
          ? "bg-signal-high/15 text-signal-high"
          : "bg-mist-100 text-ink-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${cls}`}>
      {children}
    </span>
  );
}

export function CompactTestCard({
  item,
  selected,
  onSelect,
  onOpen,
}: {
  item: CompactTestItem;
  selected?: boolean;
  onSelect?: (id: string) => void;
  onOpen: (id: string) => void;
}) {
  return (
    <article
      role="button"
      tabIndex={0}
      aria-label={`Open test ${item.id}`}
      className={`flex h-full cursor-pointer flex-col rounded-2xl border p-4 text-left transition hover:border-pine-700/40 hover:bg-mist-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-pine-600 ${
        selected ? "border-pine-700 bg-pine-700/5" : "border-ink-700/10 bg-white"
      }`}
      onClick={() => onOpen(item.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(item.id);
        }
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="font-mono text-xs text-ink-600/70">{item.id}</div>
        {onSelect ? (
          <input
            type="checkbox"
            checked={!!selected}
            aria-label={`Select ${item.id}`}
            onClick={(e) => e.stopPropagation()}
            onChange={() => onSelect(item.id)}
          />
        ) : null}
      </div>
      <h3 className="mt-2 line-clamp-2 font-medium text-ink-900">{item.title}</h3>
      {item.feature ? <p className="mt-1 line-clamp-1 text-xs text-ink-600/70">{item.feature}</p> : null}
      <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
        {item.category ? <Badge>{item.category}</Badge> : null}
        {item.priority ? <Badge tone="warn">{item.priority}</Badge> : null}
        {item.source ? <Badge>{item.source}</Badge> : null}
        {item.validity && item.validity === "valid" ? (
          <Badge tone="good">valid</Badge>
        ) : null}
        {item.automation ? <Badge tone="good">{item.automation}</Badge> : null}
      </div>
    </article>
  );
}

export function TestCaseDetailDrawer({
  item,
  open,
  onClose,
}: {
  item: CompactTestItem | null;
  open: boolean;
  onClose: () => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  useEffect(() => {
    if (!open) setDetailsOpen(false);
  }, [open, item?.id]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !item) return null;
  const bdd = item.bdd;
  const standard = item.standard;
  const review = item.reviewed;

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink-900/40" role="dialog" aria-modal="true">
      <button type="button" className="flex-1" aria-label="Close detail" onClick={onClose} />
      <div className="flex h-full w-full max-w-xl flex-col overflow-hidden bg-white shadow-soft md:max-w-lg">
        <div className="flex items-start justify-between gap-3 border-b border-ink-700/10 px-5 py-4">
          <div>
            <div className="font-mono text-xs text-ink-600/70">{item.id}</div>
            <h2 className="mt-1 font-display text-xl text-ink-900">{item.title}</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {item.category ? <Badge>{item.category}</Badge> : null}
              {item.priority ? <Badge tone="warn">{item.priority}</Badge> : null}
              {item.source ? <Badge>{item.source}</Badge> : null}
            </div>
          </div>
          <button type="button" className="rounded-full p-1 hover:bg-mist-100" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4 text-sm">
          {bdd ? (
            <section>
              <h3 className="label">BDD scenario</h3>
              <pre className="mt-2 overflow-auto rounded-xl bg-ink-900 p-3 font-mono text-xs text-mist-50">
                {bdd.gherkin_text ||
                  [
                    `Feature: ${bdd.feature}`,
                    bdd.feature_description,
                    "",
                    bdd.section ? `# ${bdd.section}` : "",
                    (bdd.tags || []).join(" "),
                    `Scenario: ${bdd.scenario_name}`,
                    ...(bdd.steps || []).map((s) => `  ${s.keyword} ${s.text}`),
                  ]
                    .filter(Boolean)
                    .join("\n")}
              </pre>
            </section>
          ) : null}
          {standard ? (
            <section>
              <h3 className="label">Standard test</h3>
              <div className="mt-2 space-y-2 text-ink-800">
                {standard.objective || standard.reasoning ? (
                  <p>{standard.objective || standard.reasoning}</p>
                ) : null}
                {(standard.preconditions || []).length ? (
                  <div>
                    <div className="font-medium">Preconditions</div>
                    <ul className="list-disc pl-5">
                      {standard.preconditions.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div>
                  <div className="font-medium">Steps</div>
                  <ol className="list-decimal pl-5">
                    {(standard.steps || []).map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ol>
                </div>
                <div>
                  <div className="font-medium">Expected</div>
                  <p>{standard.expected_result}</p>
                </div>
              </div>
            </section>
          ) : null}
          {standard?.classification || bdd?.classification ? (
            <section>
              <h3 className="label">Classification</h3>
              <pre className="mt-2 overflow-auto rounded-xl bg-mist-100 p-3 text-xs">
                {JSON.stringify(standard?.classification || bdd?.classification, null, 2)}
              </pre>
            </section>
          ) : null}
          {review ? (
            <section>
              <h3 className="label">Review</h3>
              <p className="mt-2">
                Validity: {review.validity_review?.validity || "—"}
              </p>
              <p className="mt-1 text-ink-700/80">
                {(review.validity_review?.validity_reasons || []).join("; ") ||
                  review.override_reason ||
                  ""}
              </p>
              {review.automation_review ? (
                <div className="mt-3">
                  <div className="font-medium">Automation</div>
                  <p>
                    {review.automation_review.automation_suitability} ·{" "}
                    {review.automation_review.recommended_layer}
                  </p>
                  <p className="text-ink-700/80">
                    {(review.automation_review.automation_reasons || []).join("; ")}
                  </p>
                </div>
              ) : null}
            </section>
          ) : null}
          <section>
            <h3 className="label">Evidence</h3>
            <p className="mt-2 text-ink-700/80">
              Graph path: {(standard?.graph_path || bdd?.graph_path || []).join(" > ") || "—"}
            </p>
          </section>
          <section>
            <button
              type="button"
              className="text-xs font-medium uppercase tracking-wide text-pine-800"
              onClick={() => setDetailsOpen((v) => !v)}
              aria-expanded={detailsOpen}
            >
              {detailsOpen ? "Hide" : "Show"} Additional Details
            </button>
            {detailsOpen ? (
              <div className="mt-2 space-y-2 rounded-xl border border-ink-700/10 bg-mist-50 p-3 text-xs text-ink-700">
                <p>Why generated: {standard?.reasoning || "—"}</p>
                <p>Generation method: {standard?.generation_method || bdd?.generation_method || "—"}</p>
                <p>Gap: {standard?.closes_gap_title || "—"}</p>
              </div>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}

export function useCompactTestItems(
  result: {
    test_cases?: TestCase[];
    valid_tests?: TestCase[];
    bdd_scenarios?: BDDScenario[];
    generated_test_artifacts?: Array<{
      logical_test_id: string;
      standard_test_case?: TestCase | null;
      bdd_scenario?: BDDScenario | null;
    }>;
    reviewed_test_cases?: ReviewedTestCase[];
    category_counts?: Record<string, number>;
  } | null
): CompactTestItem[] {
  return useMemo(() => {
    if (!result) return [];
    const reviewedById = new Map(
      (result.reviewed_test_cases || [])
        .map((r) => [r.test_case?.test_case_id, r] as const)
        .filter((entry): entry is [string, ReviewedTestCase] => Boolean(entry[0]))
    );
    const isValidId = (id: string) => {
      const v = reviewedById.get(id)?.validity_review?.validity;
      if (!v) {
        // Prefer explicit valid_tests membership when present
        if (result.valid_tests?.length) {
          return result.valid_tests.some((t) => t.test_case_id === id);
        }
        return true;
      }
      return v === "valid";
    };
    const artifacts = result.generated_test_artifacts || [];
    if (artifacts.length) {
      return artifacts
        .filter((a) => isValidId(a.logical_test_id))
        .map((a) => {
        const std = a.standard_test_case || null;
        const bdd = a.bdd_scenario || null;
        const id = a.logical_test_id;
        const reviewed = reviewedById.get(id) || null;
        const suit = reviewed?.automation_review?.automation_suitability;
        return {
          id,
          title: bdd?.scenario_name || std?.title || id,
          feature: bdd?.feature || std?.graph_path?.[0],
          category: std?.classification?.nature || std?.category || bdd?.section || "functional",
          priority: std?.priority || bdd?.priority || "medium",
          source: std?.classification?.source || std?.generation_method || "generated",
          validity: reviewed?.validity_review?.validity || null,
          automation:
            suit === "automate"
              ? "automation yes"
              : suit === "manual"
                ? "manual"
                : suit === "automate_with_conditions" || suit === "hybrid"
                  ? "automation partial"
                  : null,
          standard: std,
          bdd,
          reviewed,
        };
      });
    }
    const suite =
      result.valid_tests?.length
        ? result.valid_tests
        : (result.test_cases || []).filter((tc) => isValidId(tc.test_case_id));
    return suite.map((tc) => {
      const bdd = (result.bdd_scenarios || []).find((s) => s.source_test_id === tc.test_case_id) || null;
      const reviewed = reviewedById.get(tc.test_case_id) || null;
      const suit = reviewed?.automation_review?.automation_suitability;
      return {
        id: tc.test_case_id,
        title: bdd?.scenario_name || tc.title,
        feature: bdd?.feature || tc.graph_path?.[0],
        category: tc.classification?.nature || tc.category,
        priority: tc.priority,
        source: tc.classification?.source || tc.generation_method || "generated",
        validity: reviewed?.validity_review?.validity || "valid",
        automation:
          suit === "automate"
            ? "automation yes"
            : suit === "manual"
              ? "manual"
              : suit === "automate_with_conditions" || suit === "hybrid"
                ? "automation partial"
                : null,
        standard: tc,
        bdd,
        reviewed,
      };
    });
  }, [result]);
}
