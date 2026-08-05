"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  AppView,
  QACopilotResponse,
  SectionStatus,
  TestCase,
} from "@/lib/types";
import { BddExportTrigger, type BddExportApi } from "@/components/BddExportControls";
import {
  CompactTestCard,
  TestCaseDetailDrawer,
  useCompactTestItems,
} from "@/components/TestCaseCards";
import { NewTestCaseDialog } from "@/components/NewTestCaseDialog";

function statusTone(status?: string) {
  if (status === "failed") return "text-signal-high";
  if (status === "empty" || status === "skipped") return "text-ink-600/70";
  return "text-pine-700";
}

function SectionBanner({
  section,
  emptyCopy,
  failedCopy,
  skippedCopy,
}: {
  section?: SectionStatus;
  emptyCopy: string;
  failedCopy: string;
  skippedCopy: string;
}) {
  if (!section) return null;
  if (section.status === "failed") {
    return (
      <div className={`mb-3 text-sm ${statusTone(section.status)}`}>
        {failedCopy}
        {section.error ? ` (${section.error})` : ""}
      </div>
    );
  }
  if (section.status === "skipped") {
    return <div className={`mb-3 text-sm ${statusTone(section.status)}`}>{skippedCopy}</div>;
  }
  if (section.status === "empty") {
    return <div className={`mb-3 text-sm ${statusTone(section.status)}`}>{emptyCopy}</div>;
  }
  return null;
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel space-y-4 p-6">
      <div>
        <div className="label">{title}</div>
        {subtitle ? <p className="mt-2 text-sm text-ink-700/75">{subtitle}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-ink-600/70">{text}</p>;
}


export function ArtifactLists({
  view,
  result,
  projectId,
  bddExport,
  onRefresh,
}: {
  view: AppView;
  result: QACopilotResponse | null;
  projectId: string;
  bddExport?: BddExportApi;
  onRefresh?: () => void;
}) {
  const [tests, setTests] = useState<Array<Record<string, unknown>>>([]);
  const [bugs, setBugs] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    if (!projectId) {
      setTests([]);
      setBugs([]);
      return;
    }
    let cancelled = false;
    api
      .listTests(projectId)
      .then((rows) => {
        if (!cancelled) setTests(rows);
      })
      .catch(() => {
        if (!cancelled) setTests([]);
      });
    api
      .listBugs(projectId)
      .then((rows) => {
        if (!cancelled) setBugs(rows);
      })
      .catch(() => {
        if (!cancelled) setBugs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, result]);

  const resultForProject =
    result && (!result.project_id || result.project_id === projectId) ? result : null;
  const sectionStatus = resultForProject?.section_status || {};
  const format = resultForProject?.test_output_format || "standard";

  if (view === "tests") {
    return (
      <TestsSection
        resultForProject={resultForProject}
        projectId={projectId}
        storedTests={tests}
        bddExport={bddExport}
        sectionStatus={sectionStatus}
        format={format}
        onRefresh={() => {
          api.listTests(projectId).then(setTests).catch(() => setTests([]));
          onRefresh?.();
        }}
      />
    );
  }

  if (view === "exploratory") {
    const items = resultForProject?.exploratory_missions || [];
    return (
      <Panel title="Exploratory Missions" subtitle="Branch transitions, failures, and boundaries">
        <SectionBanner
          section={sectionStatus.exploratory_scenarios}
          emptyCopy="No exploratory missions were produced."
          failedCopy="Exploratory generation failed. Other analysis sections may still be available."
          skippedCopy="Exploratory generation was not requested."
        />
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((m, index) => (
            <article key={m.mission_id || `em-${index}`} className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
              <h3 className="font-medium">{m.title}</h3>
              <p className="mt-2 text-sm text-ink-700/75">{m.charter}</p>
              <div className="mt-2 font-mono text-xs text-pine-700">{m.graph_path.join(" → ")}</div>
              <ul className="mt-3 space-y-1 text-sm">
                {m.focus_areas.slice(0, 5).map((f, fIdx) => (
                  <li key={`${m.mission_id || index}-focus-${fIdx}`}>• {f}</li>
                ))}
              </ul>
            </article>
          ))}
          {items.length === 0 && <Empty text="No exploratory missions yet." />}
        </div>
      </Panel>
    );
  }

  if (view === "bugs") {
    const items = resultForProject?.bug_reports?.length
      ? resultForProject.bug_reports
      : bugs.map((b) => ({
          bug_id: String(b.bug_id || ""),
          title: String(b.title || ""),
          severity: String(b.severity || "medium"),
          graph_path: (b.graph_path as string[]) || [],
          classification: (b.classification as string) || undefined,
          generation_method: (b.generation_method as string) || undefined,
        }));
    return (
      <Panel title="Bug Reports" subtitle="Evidence-backed defect candidates">
        <SectionBanner
          section={sectionStatus.bug_reports}
          emptyCopy="No bug reports were produced."
          failedCopy="Bug report generation failed."
          skippedCopy="Bug report generation was not requested."
        />
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((b, index) => (
            <article key={b.bug_id || `bug-${index}`} className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
              <div className="text-xs text-ink-600/60">{b.bug_id}</div>
              <h3 className="mt-1 font-medium">{b.title}</h3>
              <div className="mt-2 text-sm text-ink-700/75">Severity: {b.severity}</div>
              <div className="mt-2 font-mono text-xs text-pine-700">{(b.graph_path || []).join(" → ")}</div>
            </article>
          ))}
          {items.length === 0 && <Empty text="No bug reports yet." />}
        </div>
      </Panel>
    );
  }

  if (view === "regression") {
    const items = resultForProject?.regression_recommendations || [];
    return (
      <Panel title="Regression Recommendations" subtitle="High-risk retest candidates after change">
        <SectionBanner
          section={sectionStatus.regression_recommendations}
          emptyCopy="No regression recommendations were produced."
          failedCopy="Regression recommendation generation failed."
          skippedCopy="Regression recommendations were not requested."
        />
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((r, index) => (
            <article
              key={r.recommendation_id || r.test_case_id || `reg-${index}`}
              className="rounded-2xl border border-ink-700/10 bg-white/70 p-4"
            >
              <h3 className="font-medium">{r.title}</h3>
              <p className="mt-2 text-sm text-ink-700/75">{r.reason}</p>
              <div className="mt-2 font-mono text-xs text-pine-700">{(r.graph_path || []).join(" → ")}</div>
            </article>
          ))}
          {items.length === 0 && <Empty text="No regression recommendations yet." />}
        </div>
      </Panel>
    );
  }

  if (view === "evidence") {
    const evidence = resultForProject?.evidence || [];
    return (
      <Panel title="Sources & Evidence" subtitle="Evidence strings attached to the latest analysis">
        <ul className="space-y-2 text-sm">
          {evidence.map((e, idx) => (
            <li key={`${e}-${idx}`} className="rounded-xl bg-mist-100/70 px-3 py-2">
              {e}
            </li>
          ))}
          {evidence.length === 0 && <Empty text="No evidence strings for this analysis." />}
        </ul>
      </Panel>
    );
  }

  return null;
}
function TestsSection({
  resultForProject,
  projectId,
  storedTests,
  bddExport,
  sectionStatus,
  format,
  onRefresh,
}: {
  resultForProject: QACopilotResponse | null;
  projectId: string;
  storedTests: Array<Record<string, unknown>>;
  bddExport?: BddExportApi;
  sectionStatus: Record<string, SectionStatus | undefined>;
  format: string;
  onRefresh: () => void;
}) {
  const analysisItems = useCompactTestItems(resultForProject);
  const items = useMemo(() => {
    const byId = new Map(analysisItems.map((i) => [i.id, i]));
    for (const row of storedTests) {
      const id = String(row.test_case_id || row.id || "");
      if (!id || byId.has(id)) continue;
      byId.set(id, {
        id,
        title: String(row.title || id),
        feature: Array.isArray(row.graph_path) ? String(row.graph_path[0] || "") : undefined,
        category: String(
          (row.classification as { nature?: string } | undefined)?.nature ||
            row.category ||
            "functional"
        ),
        priority: String(row.priority || "medium"),
        source: String(
          (row.classification as { source?: string } | undefined)?.source ||
            row.generation_method ||
            "manual"
        ),
        standard: row as unknown as TestCase,
        bdd: null,
        reviewed: null,
      });
    }
    return Array.from(byId.values());
  }, [analysisItems, storedTests]);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tid = params.get("testId");
    if (tid) setOpenId(tid);
    const f = params.get("filter");
    if (f) setFilter(f);
  }, []);

  const counts = resultForProject?.category_counts || {};
  const filtered = items.filter((item) => {
    const cat = String(item.category || "").toLowerCase();
    if (filter === "functional" && !cat.includes("functional")) return false;
    if (filter === "negative" && !cat.includes("negative")) return false;
    if (filter === "non_functional" && !cat.includes("non")) return false;
    if (filter === "recommended_for_automation" && item.automation !== "automation yes") return false;
    if (filter === "manual" && item.automation !== "manual" && item.source !== "manual") return false;
    if (query) {
      const q = query.toLowerCase();
      const blob = `${item.id} ${item.title} ${item.feature || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
  const active = items.find((i) => i.id === openId) || null;

  function openItem(id: string) {
    setOpenId(id);
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      params.set("section", "test-cases");
      params.set("testId", id);
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    }
  }

  return (
    <Panel
      title="Test Cases"
      subtitle={
        analysisItems.length
          ? `Latest Copilot-generated valid tests (${format}) · compact cards`
          : "Stored project tests"
      }
    >
      <SectionBanner
        section={sectionStatus.test_cases || sectionStatus.test_case_generation}
        emptyCopy="No test cases were produced for this analysis."
        failedCopy="Test case generation failed. Other analysis sections may still be available."
        skippedCopy="Test case generation was not requested."
      />
      <div className="mb-3 flex flex-wrap gap-2">
        {(
          [
            ["all", `All (${counts.all ?? items.length})`],
            ["functional", `Functional (${counts.functional ?? "—"})`],
            ["negative", `Negative (${counts.negative ?? "—"})`],
            ["non_functional", `Non-functional (${counts.non_functional ?? "—"})`],
            ["recommended_for_automation", `Automatable (${counts.recommended_for_automation ?? "—"})`],
            ["manual", `Manual (${counts.manual ?? "—"})`],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`rounded-full px-3 py-1 text-xs ${
              filter === id ? "bg-ink-900 text-white" : "bg-mist-100 text-ink-700"
            }`}
            onClick={() => setFilter(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="min-w-[200px] flex-1 rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
          placeholder="Search ID, scenario, feature…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search tests"
        />
        {bddExport ? <BddExportTrigger exportApi={bddExport} compact /> : null}
        <button type="button" className="btn-secondary text-xs" onClick={() => setCreateOpen(true)}>
          New Test Case
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {filtered.map((item) => (
          <CompactTestCard
            key={item.id}
            item={item}
            selected={selected.includes(item.id)}
            onSelect={(id) =>
              setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
            }
            onOpen={openItem}
          />
        ))}
        {filtered.length === 0 && <Empty text="No tests match the current filters." />}
      </div>
      <TestCaseDetailDrawer item={active} open={Boolean(openId)} onClose={() => setOpenId(null)} />
      <NewTestCaseDialog
        open={createOpen}
        projectId={projectId}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false);
          onRefresh();
        }}
      />
    </Panel>
  );
}
