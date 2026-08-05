import { describe, expect, it } from "vitest";
import { primaryValidTests } from "./validTests";
import type { QACopilotResponse } from "./types";

describe("primaryValidTests", () => {
  it("prefers valid_tests when present", () => {
    const result = {
      test_cases: [
        { test_case_id: "TC-1", title: "A" },
        { test_case_id: "TC-2", title: "B" },
      ],
      valid_tests: [{ test_case_id: "TC-1", title: "A" }],
      needs_revision_tests: [{ test_case_id: "TC-2", title: "B" }],
    } as unknown as QACopilotResponse;
    expect(primaryValidTests(result).map((t) => t.test_case_id)).toEqual(["TC-1"]);
  });

  it("filters by reviewed validity when valid_tests is empty", () => {
    const result = {
      test_cases: [
        { test_case_id: "TC-1", title: "A" },
        { test_case_id: "TC-2", title: "B" },
      ],
      reviewed_test_cases: [
        {
          test_case: { test_case_id: "TC-1", title: "A" },
          validity_review: { validity: "valid" },
        },
        {
          test_case: { test_case_id: "TC-2", title: "B" },
          validity_review: { validity: "needs_revision" },
        },
      ],
    } as unknown as QACopilotResponse;
    expect(primaryValidTests(result).map((t) => t.test_case_id)).toEqual(["TC-1"]);
  });

  it("uses test count from valid suite in resultTabCounts", async () => {
    const { resultTabCounts } = await import("./workflow");
    const result = {
      test_cases: [{ test_case_id: "TC-1" }, { test_case_id: "TC-2" }],
      valid_tests: [{ test_case_id: "TC-1" }],
      exploratory_missions: [],
      bug_reports: [],
      regression_recommendations: [],
      evidence: [],
    } as unknown as QACopilotResponse;
    expect(resultTabCounts(result).tests).toBe(1);
  });
});
