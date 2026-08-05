import type { QACopilotResponse, ReviewedTestCase, TestCase } from "@/lib/types";

/** Primary suite shown in Test Experience / Copilot — valid tests only. */
export function primaryValidTests(
  result: Pick<QACopilotResponse, "test_cases" | "valid_tests" | "reviewed_test_cases"> | null | undefined
): TestCase[] {
  if (!result) return [];
  if (result.valid_tests?.length) {
    return result.valid_tests;
  }
  const reviewedById = new Map<string, ReviewedTestCase>();
  for (const r of result.reviewed_test_cases || []) {
    const id = r.test_case?.test_case_id;
    if (id) reviewedById.set(id, r);
  }
  if (reviewedById.size) {
    return (result.test_cases || []).filter((tc) => {
      const validity = reviewedById.get(tc.test_case_id)?.validity_review?.validity;
      return !validity || validity === "valid";
    });
  }
  return result.test_cases || [];
}
