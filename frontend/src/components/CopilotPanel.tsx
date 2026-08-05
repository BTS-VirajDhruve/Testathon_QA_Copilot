"use client";

import { useMemo } from "react";
import { ShieldAlert, Sparkles } from "lucide-react";
import type { QACopilotResponse } from "@/lib/types";
import { TestCaseEvidenceCard } from "@/components/TestCaseEvidenceCard";
import { RegenerationLoopPanel } from "@/components/RegenerationLoopPanel";
import { AnalysisComposer } from "@/components/AnalysisComposer";
import type { AnalysisProgressState } from "@/lib/workflow";
import { primaryValidTests } from "@/lib/validTests";

export function CopilotPanel({
  busy,
  result,
  onQuery,
  projectReady,
  emptyGraph,
  initialQuery,
  projectName,
  rootFeature,
  testOutputFormat,
  onTestOutputFormatChange,
  readiness,
  progress,
  onOpenResults,
  onOpenTrace,
}: {
  busy: boolean;
  result: QACopilotResponse | null;
  onQuery: (query: string, changedNode?: string) => void;
  projectReady: boolean;
  emptyGraph?: boolean;
  initialQuery?: string | null;
  projectName?: string | null;
  rootFeature?: string | null;
  testOutputFormat?: "standard" | "bdd" | "both";
  onTestOutputFormatChange?: (format: "standard" | "bdd" | "both") => void;
  readiness?: {
    flowReady: boolean;
    nodeCount: number;
    edgeCount: number;
    documentCount: number;
    featureName?: string | null;
  };
  progress?: AnalysisProgressState | null;
  onOpenResults?: () => void;
  onOpenTrace?: () => void;
}) {
  const summary = useMemo(() => {
    if (!result) return null;
    const tests = primaryValidTests(result);
    return {
      tests: tests.length,
      before: result.coverage_before?.coverage_percentage,
      after: result.coverage_after?.coverage_percentage,
    };
  }, [result]);

  const previewTests = useMemo(() => primaryValidTests(result).slice(0, 8), [result]);

  return (
    <section className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
      <AnalysisComposer
        busy={busy}
        projectReady={projectReady}
        emptyGraph={emptyGraph}
        initialQuery={initialQuery}
        projectName={projectName}
        rootFeature={rootFeature || result?.root_feature}
        testOutputFormat={testOutputFormat}
        onTestOutputFormatChange={onTestOutputFormatChange}
        readiness={readiness}
        progress={progress}
        onQuery={onQuery}
        onOpenResults={onOpenResults}
        onOpenTrace={onOpenTrace}
        hasResult={Boolean(result)}
      />

      <div className="panel p-6">
        <div className="label">Latest analysis</div>
        {!result ? (
          <div className="mt-3 space-y-3 text-sm text-ink-700/75">
            <p>No analysis yet for this project.</p>
            <div className="rounded-2xl border border-dashed border-ink-700/15 bg-mist-100/50 p-4">
              <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-600/70">
                <Sparkles className="h-3.5 w-3.5" /> Expected story
              </div>
              <p className="mt-2 font-mono text-xs leading-relaxed text-ink-800">
                INITIAL ANALYSIS → CRITIC → COVERAGE GAPS → TARGETED TESTS → FINAL COVERAGE
              </p>
            </div>
          </div>
        ) : (
          <div className="mt-3 space-y-4">
            <div className="rounded-2xl bg-ink-900 px-4 py-4 text-mist-50">
              <div className="text-xs uppercase tracking-[0.14em] text-brass-400">QA Risk</div>
              <div className="mt-1 font-display text-3xl">{result.risk_level.toUpperCase()}</div>
              <div className="mt-2 text-sm text-mist-200">
                {result.root_feature} · {result.discovered_branches?.length ?? 0} branches
                {result.graph_coverage != null ? ` · ${result.graph_coverage}% coverage` : ""}
              </div>
            </div>
            {summary ? (
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-xl bg-mist-100/80 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Tests</div>
                  <div className="font-display text-xl">{summary.tests}</div>
                </div>
                <div className="rounded-xl bg-mist-100/80 px-3 py-2">
                  <div className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-ink-600/60">
                    <ShieldAlert className="h-3 w-3" /> Coverage
                  </div>
                  <div className="font-display text-xl">
                    {summary.before ?? "—"}% → {summary.after ?? "—"}%
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {result ? (
        <div className="space-y-5 xl:col-span-2">
          <RegenerationLoopPanel result={result} />
          <div className="grid gap-4 md:grid-cols-2">
            {previewTests.map((tc) => (
              <TestCaseEvidenceCard key={tc.test_case_id} tc={tc} />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
