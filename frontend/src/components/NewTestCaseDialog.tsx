"use client";

import { useMemo, useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";

type StepRow = { keyword: string; text: string };
type ScenarioDraft = {
  key: string;
  name: string;
  scenario_type: "scenario" | "scenario_outline";
  behavior: string;
  nature: string;
  priority: string;
  steps: StepRow[];
  examples: Array<Record<string, string>>;
};

const KEYWORDS = ["Given", "When", "Then", "And", "But"];

function blankScenario(key = "sc-1"): ScenarioDraft {
  return {
    key,
    name: "",
    scenario_type: "scenario",
    behavior: "positive",
    nature: "functional",
    priority: "medium",
    steps: [
      { keyword: "Given", text: "" },
      { keyword: "When", text: "" },
      { keyword: "Then", text: "" },
    ],
    examples: [],
  };
}

export function NewTestCaseDialog({
  open,
  projectId,
  onClose,
  onCreated,
}: {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [featureName, setFeatureName] = useState("");
  const [featureRef, setFeatureRef] = useState("");
  const [asA, setAsA] = useState("admin");
  const [iWant, setIWant] = useState("");
  const [soThat, setSoThat] = useState("");
  const [scenarios, setScenarios] = useState<ScenarioDraft[]>([blankScenario()]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canSubmit = useMemo(
    () => featureName.trim() && scenarios.every((s) => s.name.trim() && s.steps.some((st) => st.keyword === "When" && st.text.trim()) && s.steps.some((st) => st.keyword === "Then" && st.text.trim())),
    [featureName, scenarios]
  );

  if (!open) return null;

  function updateScenario(key: string, patch: Partial<ScenarioDraft>) {
    setScenarios((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)));
  }

  function moveScenario(index: number, dir: -1 | 1) {
    setScenarios((prev) => {
      const next = [...prev];
      const j = index + dir;
      if (j < 0 || j >= next.length) return prev;
      [next[index], next[j]] = [next[j], next[index]];
      return next;
    });
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.createManualTests(projectId, {
        feature_name: featureName.trim(),
        feature_reference: featureRef.trim() || null,
        as_a: asA.trim() || null,
        i_want: iWant.trim() || null,
        so_that: soThat.trim() || null,
        scenarios: scenarios.map((s) => ({
          name: s.name.trim(),
          scenario_type: s.scenario_type,
          nature: s.nature,
          behavior: [s.behavior],
          priority: s.priority,
          suite_types: ["regression"],
          execution_status: "manual",
          bdd_steps: s.steps.filter((st) => st.text.trim()),
          examples: s.scenario_type === "scenario_outline" ? s.examples : [],
        })),
      });
      onCreated();
      setScenarios([blankScenario()]);
      setFeatureName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-ink-900/50 p-4" role="dialog" aria-modal="true">
      <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-ink-700/10 bg-white shadow-soft">
        <div className="flex items-start justify-between gap-3 border-b border-ink-700/10 px-5 py-4">
          <div>
            <div className="label">Manual</div>
            <h2 className="mt-1 font-display text-2xl text-ink-900">New Test Case</h2>
            <p className="mt-1 text-sm text-ink-600/75">Fill Feature story and scenarios (Given / When / Then).</p>
          </div>
          <button type="button" className="rounded-full p-1 hover:bg-mist-100" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm">
              Feature name
              <input className="mt-1 w-full rounded-xl border border-ink-700/15 px-3 py-2" value={featureName} onChange={(e) => setFeatureName(e.target.value)} />
            </label>
            <label className="text-sm">
              Feature reference / ticket
              <input className="mt-1 w-full rounded-xl border border-ink-700/15 px-3 py-2" value={featureRef} onChange={(e) => setFeatureRef(e.target.value)} placeholder="Optional" />
            </label>
            <label className="text-sm">
              As a
              <input className="mt-1 w-full rounded-xl border border-ink-700/15 px-3 py-2" value={asA} onChange={(e) => setAsA(e.target.value)} />
            </label>
            <label className="text-sm">
              I want
              <input className="mt-1 w-full rounded-xl border border-ink-700/15 px-3 py-2" value={iWant} onChange={(e) => setIWant(e.target.value)} />
            </label>
            <label className="text-sm md:col-span-2">
              So that
              <input className="mt-1 w-full rounded-xl border border-ink-700/15 px-3 py-2" value={soThat} onChange={(e) => setSoThat(e.target.value)} />
            </label>
          </div>

          <div className="flex items-center justify-between">
            <h3 className="font-medium text-ink-900">Scenarios</h3>
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() =>
                setScenarios((p) => [...p, blankScenario(`sc-${p.length + 1}`)])
              }
            >
              <Plus className="h-3.5 w-3.5" /> Add scenario
            </button>
          </div>

          {scenarios.map((sc, index) => (
            <div key={sc.key} className="rounded-2xl border border-ink-700/10 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs uppercase tracking-wide text-ink-600/60">Scenario {index + 1}</div>
                <div className="flex gap-1">
                  <button type="button" className="btn-secondary text-xs" onClick={() => moveScenario(index, -1)} aria-label="Move up">
                    ↑
                  </button>
                  <button type="button" className="btn-secondary text-xs" onClick={() => moveScenario(index, 1)} aria-label="Move down">
                    ↓
                  </button>
                  <button
                    type="button"
                    className="rounded-full p-1 text-signal-high hover:bg-signal-high/10"
                    onClick={() => setScenarios((p) => (p.length === 1 ? p : p.filter((s) => s.key !== sc.key)))}
                    aria-label="Delete scenario"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                <input
                  className="rounded-xl border border-ink-700/15 px-3 py-2 text-sm md:col-span-2"
                  placeholder="e.g. Successful login with valid credentials."
                  value={sc.name}
                  onChange={(e) => updateScenario(sc.key, { name: e.target.value })}
                />
                <select
                  className="rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                  value={sc.scenario_type}
                  onChange={(e) =>
                    updateScenario(sc.key, {
                      scenario_type: e.target.value as ScenarioDraft["scenario_type"],
                    })
                  }
                >
                  <option value="scenario">Scenario</option>
                  <option value="scenario_outline">Scenario Outline</option>
                </select>
                <select
                  className="rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                  value={sc.behavior}
                  onChange={(e) => updateScenario(sc.key, { behavior: e.target.value })}
                >
                  <option value="positive">Positive</option>
                  <option value="negative">Negative</option>
                  <option value="boundary">Boundary</option>
                  <option value="edge_case">Edge case</option>
                </select>
              </div>
              <div className="mt-3 space-y-2">
                {sc.steps.map((step, si) => (
                  <div key={`${sc.key}-step-${si}`} className="flex gap-2">
                    <select
                      className="w-28 rounded-xl border border-ink-700/15 px-2 py-2 text-sm"
                      value={step.keyword}
                      onChange={(e) => {
                        const steps = [...sc.steps];
                        steps[si] = { ...step, keyword: e.target.value };
                        updateScenario(sc.key, { steps });
                      }}
                    >
                      {KEYWORDS.map((k) => (
                        <option key={k} value={k}>
                          {k}
                        </option>
                      ))}
                    </select>
                    <input
                      className="flex-1 rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                      placeholder="step text…"
                      value={step.text}
                      onChange={(e) => {
                        const steps = [...sc.steps];
                        steps[si] = { ...step, text: e.target.value };
                        updateScenario(sc.key, { steps });
                      }}
                    />
                    <button
                      type="button"
                      className="rounded-full p-1 text-signal-high hover:bg-signal-high/10"
                      onClick={() =>
                        updateScenario(sc.key, { steps: sc.steps.filter((_, i) => i !== si) })
                      }
                      aria-label="Delete step"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="text-xs font-medium text-pine-800"
                  onClick={() =>
                    updateScenario(sc.key, {
                      steps: [...sc.steps, { keyword: "And", text: "" }],
                    })
                  }
                >
                  + Add step
                </button>
              </div>
              {sc.scenario_type === "scenario_outline" ? (
                <div className="mt-3 rounded-xl bg-mist-50 p-3 text-xs text-ink-700">
                  Examples table: add rows as JSON objects with placeholder headers matching{" "}
                  <code>&lt;name&gt;</code> in steps. Use the API payload{" "}
                  <code>examples</code> field after save for full editing.
                </div>
              ) : null}
            </div>
          ))}
          {error ? <p className="text-sm text-signal-high">{error}</p> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-ink-700/10 bg-white px-5 py-4">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn-primary" disabled={!canSubmit || busy} onClick={submit}>
            Create test case
          </button>
        </div>
      </div>
    </div>
  );
}
