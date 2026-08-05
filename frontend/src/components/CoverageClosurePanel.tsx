"use client";

import type { QACopilotResponse } from "@/lib/types";
import { api } from "@/lib/api";

export function CoverageClosurePanel({
  result,
  projectId,
  onResumed,
}: {
  result: QACopilotResponse | null;
  projectId?: string;
  onResumed?: () => void;
}) {
  const report = result?.convergence_report;
  const history = result?.iteration_history || [];
  if (!report && history.length === 0) return null;

  const status = report?.status || "partial";
  const complete = status === "complete";
  const stoppedEarly = !complete && Boolean(report);

  async function resume() {
    if (!projectId) return;
    await api.resumeCoverageClosure(projectId, {});
    onResumed?.();
  }

  return (
    <section className="rounded-2xl border border-ink-700/10 bg-white/80 p-4" aria-labelledby="closure-title">
      <h3 id="closure-title" className="font-display text-lg text-ink-900">
        Coverage closure
      </h3>
      <p className="mt-1 text-sm text-ink-600/75">
        {complete
          ? "Internal revision completed — showing valid tests only"
          : "Internal reviewer revised the suite; Test Experience shows valid tests only"}
      </p>

      {report ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-sm">
          <Stat label="Modeled coverage" value={`${report.final_modeled_coverage}%`} />
          <Stat
            label="Mandatory covered"
            value={`${report.mandatory_obligations_covered}/${report.mandatory_obligations_total}`}
          />
          <Stat
            label="Valid tests shown"
            value={`${result?.valid_tests?.length ?? result?.test_cases?.length ?? 0}`}
          />
          <Stat label="Internal revisions" value={`${report.tests_revised}`} />
          <Stat label="Iterations" value={`${report.iterations_completed}`} />
          <Stat label="Created" value={`${report.tests_created}`} />
          <Stat label="Status" value={status.replaceAll("_", " ")} />
          <Stat label="Stop reason" value={report.stop_reason || "—"} />
        </div>
      ) : null}

      {stoppedEarly ? (
        <div className="mt-3 rounded-xl border border-brass-500/30 bg-brass-500/10 px-3 py-2 text-sm text-ink-800">
          Coverage closure stopped before all modeled obligations were covered. Valid tests are still
          shown in Test Experience.
          {report?.remaining_obligations?.length ? (
            <div className="mt-1 text-xs text-ink-700/80">
              Remaining mandatory obligations: {report.remaining_obligations.length}
            </div>
          ) : null}
          {projectId ? (
            <button type="button" className="btn-secondary mt-2 text-xs" onClick={() => void resume()}>
              Resume Coverage Closure
            </button>
          ) : null}
        </div>
      ) : null}

      {history.length ? (
        <div className="mt-4">
          <div className="text-[11px] uppercase tracking-wide text-ink-600/60">Refinement history</div>
          <ol className="mt-2 space-y-2">
            {history.map((round) => (
              <li
                key={round.iteration}
                className="rounded-xl border border-ink-700/10 bg-mist-50 px-3 py-2 text-sm"
              >
                <div className="font-medium">Round {round.iteration}</div>
                <div className="text-ink-700/80">
                  {round.test_count} tests · {round.modeled_coverage_pct}% coverage ·{" "}
                  {round.tests_revised ?? 0} internal revisions · {round.tests_created ?? 0} missing
                  scenarios
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-mist-100/80 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-ink-600/60">{label}</div>
      <div className="mt-0.5 font-medium text-ink-900">{value}</div>
    </div>
  );
}
