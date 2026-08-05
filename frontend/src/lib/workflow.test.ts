/**
 * Workflow navigation / deep-link / demo-removal unit tests.
 * Run: npm test
 */
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";
import {
  WORKFLOW_NAV,
  applyProgressEvent,
  containsLoadDemoCopy,
  createIdleProgress,
  formatElapsed,
  parseSectionParam,
  progressRatio,
  resolveNavigation,
  resultTabCounts,
  sectionToQueryParam,
} from "./workflow";
import type { QACopilotResponse } from "./types";

function walkTsx(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) walkTsx(full, out);
    else if (/\.(tsx|ts)$/.test(name) && !name.includes(".test.")) out.push(full);
  }
  return out;
}

describe("workflow navigation", () => {
  it("orders sidebar as Overview → Setup → Analyze → Observe", () => {
    expect(WORKFLOW_NAV.map((i) => i.id)).toEqual([
      "home",
      "flow",
      "explorer",
      "knowledge",
      "copilot",
      "results",
      "trace",
    ]);
    expect(WORKFLOW_NAV[0].group).toBe("overview");
  });

  it("places QA Copilot after Knowledge Base", () => {
    const knowledgeIdx = WORKFLOW_NAV.findIndex((i) => i.id === "knowledge");
    const copilotIdx = WORKFLOW_NAV.findIndex((i) => i.id === "copilot");
    expect(copilotIdx).toBe(knowledgeIdx + 1);
  });

  it("places Analysis Results after QA Copilot", () => {
    const copilotIdx = WORKFLOW_NAV.findIndex((i) => i.id === "copilot");
    const resultsIdx = WORKFLOW_NAV.findIndex((i) => i.id === "results");
    expect(resultsIdx).toBe(copilotIdx + 1);
  });

  it("does not include standalone output pages in primary nav", () => {
    const ids = new Set(WORKFLOW_NAV.map((i) => i.id));
    for (const legacy of ["tests", "automation", "exploratory", "bugs", "regression", "coverage", "evidence"]) {
      expect(ids.has(legacy as never)).toBe(false);
    }
  });
});

describe("legacy redirects / deep links", () => {
  it("maps old output views to Analysis Results sections", () => {
    expect(resolveNavigation("tests")).toEqual({ view: "results", section: "tests" });
    expect(resolveNavigation("automation")).toEqual({ view: "results", section: "automation" });
    expect(resolveNavigation("bugs")).toEqual({ view: "results", section: "bugs" });
    expect(resolveNavigation("evidence")).toEqual({ view: "results", section: "evidence" });
  });

  it("parses section query aliases", () => {
    expect(parseSectionParam("test-cases")).toBe("tests");
    expect(parseSectionParam("automation-review")).toBe("automation");
    expect(parseSectionParam("bug-reports")).toBe("bugs");
    expect(parseSectionParam("unknown")).toBe("overview");
  });

  it("serializes section query params", () => {
    expect(sectionToQueryParam("tests")).toBe("test-cases");
    expect(sectionToQueryParam("overview")).toBe("overview");
  });
});

describe("tab counts", () => {
  it("returns accurate counts from analysis result", () => {
    const result = {
      test_cases: [{}, {}, {}],
      exploratory_missions: [{}],
      bug_reports: [{}, {}],
      regression_recommendations: [{}, {}, {}, {}],
      evidence: ["a", "b"],
      reviewed_test_cases: [{}, {}],
    } as unknown as QACopilotResponse;
    const counts = resultTabCounts(result);
    expect(counts.tests).toBe(3);
    expect(counts.exploratory).toBe(1);
    expect(counts.bugs).toBe(2);
    expect(counts.regression).toBe(4);
    expect(counts.evidence).toBe(2);
    expect(counts.automation).toBe(2);
  });
});

describe("progress helpers", () => {
  it("applies real stage updates and formats elapsed time", () => {
    let state = createIdleProgress();
    state = { ...state, status: "running", startedAt: Date.now() };
    state = applyProgressEvent(state, {
      stage: "Identify Project",
      message: "ok",
      meta: { status: "complete", completed_stages: ["Identify Project"], elapsed_ms: 4200 },
    });
    expect(state.currentStageLabel).toBe("Validating project context");
    expect(state.completedStages).toContain("Identify Project");
    expect(formatElapsed(state.elapsedMs)).toBe("00:04");
    expect(progressRatio(state)).not.toBeNull();
  });

  it("uses indeterminate-friendly null ratio when idle", () => {
    expect(progressRatio(createIdleProgress())).toBeNull();
  });
});

describe("demo removal", () => {
  it("detects Load Demo Project copy", () => {
    expect(containsLoadDemoCopy("Click Load Demo Project")).toBe(true);
    expect(containsLoadDemoCopy("Create a project to begin")).toBe(false);
  });

  it("has no Load Demo Project UI copy in components or pages", () => {
    const roots = [join(__dirname, "../components"), join(__dirname, "../app")];
    const hits: string[] = [];
    for (const root of roots) {
      for (const file of walkTsx(root)) {
        const text = readFileSync(file, "utf8");
        if (containsLoadDemoCopy(text) || /\bonSeed\b/.test(text) || /\bhandleSeed\b/.test(text)) {
          hits.push(file);
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
