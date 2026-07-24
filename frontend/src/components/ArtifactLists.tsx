"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AppView, QACopilotResponse, TestCase } from "@/lib/types";
import { TestCaseEvidenceCard } from "@/components/TestCaseEvidenceCard";

export function ArtifactLists({
  view,
  result,
  projectId,
}: {
  view: AppView;
  result: QACopilotResponse | null;
  projectId: string;
}) {
  const [tests, setTests] = useState<Array<Record<string, unknown>>>([]);
  const [bugs, setBugs] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    if (!projectId) return;
    api.listTests(projectId).then(setTests).catch(() => setTests([]));
    api.listBugs(projectId).then(setBugs).catch(() => setBugs([]));
  }, [projectId, result]);

  if (view === "tests") {
    const items: TestCase[] = result?.test_cases?.length
      ? result.test_cases
      : tests.map((t) => ({
          test_case_id: String(t.test_case_id || ""),
          title: String(t.title || ""),
          graph_path: (t.graph_path as string[]) || [],
          graph_reasoning: String(t.graph_reasoning || ""),
          reasoning: (t.reasoning as string) || null,
          source_references: (t.source_references as string[]) || [],
          evidence: (t.evidence as TestCase["evidence"]) || [],
          generation_method: (t.generation_method as string) || null,
          confidence: String(t.confidence || "medium"),
          priority: String(t.priority || "medium"),
          risk: String(t.risk || "medium"),
          category: String(t.category || ""),
          preconditions: [],
          steps: (t.steps as string[]) || [],
          expected_result: String(t.expected_result || ""),
          testing_technique: "",
          assumptions: [],
        }));
    return (
      <Panel
        title="Test Cases"
        subtitle={
          result?.test_cases?.length
            ? "Latest Copilot-generated tests with evidence"
            : "Seeded / stored project tests"
        }
      >
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((tc) => (
            <TestCaseEvidenceCard key={tc.test_case_id} tc={tc} />
          ))}
          {items.length === 0 && <Empty text="No tests yet. Load the demo or run the Copilot." />}
        </div>
      </Panel>
    );
  }

  if (view === "exploratory") {
    const items = result?.exploratory_missions || [];
    return (
      <Panel title="Exploratory Missions" subtitle="Branch transitions, failures, and boundaries">
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((m) => (
            <article key={m.mission_id} className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
              <h3 className="font-medium">{m.title}</h3>
              <p className="mt-2 text-sm text-ink-700/75">{m.charter}</p>
              <div className="mt-2 font-mono text-xs text-pine-700">{m.graph_path.join(" → ")}</div>
              <ul className="mt-3 space-y-1 text-sm">
                {m.focus_areas.slice(0, 5).map((f) => (
                  <li key={f}>• {f}</li>
                ))}
              </ul>
            </article>
          ))}
          {items.length === 0 && <Empty text="Run a copilot analysis to generate exploratory missions." />}
        </div>
      </Panel>
    );
  }

  if (view === "bugs") {
    const items = result?.bug_reports?.length
      ? result.bug_reports
      : bugs.map((b) => ({
          bug_id: String(b.bug_id || ""),
          title: String(b.title || ""),
          severity: String(b.severity || "medium"),
          graph_path: (b.graph_path as string[]) || [],
        }));
    return (
      <Panel title="Bug Reports" subtitle="Historical patterns and structured defect templates">
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((b) => (
            <article key={b.bug_id} className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
              <div className="text-xs uppercase tracking-wide text-signal-high">{b.severity}</div>
              <h3 className="mt-1 font-medium">{b.title}</h3>
              <div className="mt-2 font-mono text-xs text-pine-700">
                {(b.graph_path || []).join(" → ")}
              </div>
            </article>
          ))}
          {items.length === 0 && <Empty text="No bugs yet. Load the demo or run a bug-report query." />}
        </div>
      </Panel>
    );
  }

  if (view === "regression") {
    const items = result?.regression_recommendations || [];
    return (
      <Panel title="Regression Recommendations" subtitle="Impact-linked retest guidance">
        <div className="space-y-3">
          {items.map((r) => (
            <article key={`${r.test_case_id}-${r.title}`} className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
              <h3 className="font-medium">{r.title}</h3>
              <p className="mt-2 text-sm text-ink-700/75">{r.reason}</p>
              <div className="mt-2 font-mono text-xs text-pine-700">{r.graph_path.join(" → ")}</div>
            </article>
          ))}
          {items.length === 0 && <Empty text="Run an impact/regression query to populate recommendations." />}
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Sources & Evidence" subtitle="Provenance for the latest analysis">
      {!result ? (
        <Empty text="Run an analysis to view evidence, confidence, and assumptions." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Box title="Evidence" items={result.evidence} />
          <Box title="Assumptions" items={result.assumptions} />
          <Box title="Critic notes" items={result.critic_notes} />
        </div>
      )}
    </Panel>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel p-6">
      <div className="label">{title}</div>
      <h2 className="mt-2 font-display text-2xl">{title}</h2>
      <p className="mt-1 text-sm text-ink-700/70">{subtitle}</p>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="text-sm text-ink-600/70">{text}</div>;
}

function Box({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-2xl border border-ink-700/10 bg-white/70 p-4">
      <div className="label mb-2">{title}</div>
      <ul className="space-y-1 text-sm">
        {items.map((i) => (
          <li key={i}>• {i}</li>
        ))}
      </ul>
    </div>
  );
}