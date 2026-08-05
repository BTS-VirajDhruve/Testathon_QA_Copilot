/**
 * Canonical navigation parser unit tests.
 * Run: npm test
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_ANALYSIS_SECTION,
  DEFAULT_VIEW,
  VALID_VIEWS,
  buildAppUrl,
  firstParam,
  parseAnalysisSection,
  parseAppLocation,
  parseView,
} from "./navigation";

describe("navigation parser", () => {
  it("missing view returns default", () => {
    expect(parseView(undefined)).toBe(DEFAULT_VIEW);
    expect(parseView(null)).toBe(DEFAULT_VIEW);
    expect(parseView("")).toBe(DEFAULT_VIEW);
    expect(parseAppLocation({}).view).toBe(DEFAULT_VIEW);
  });

  it("accepts valid views", () => {
    for (const view of VALID_VIEWS) {
      expect(parseView(view)).toBe(view);
    }
  });

  it("invalid view returns default", () => {
    expect(parseView("invalid")).toBe(DEFAULT_VIEW);
    expect(parseView("not-a-view")).toBe(DEFAULT_VIEW);
    expect(parseAppLocation({ view: "xyz" }).view).toBe(DEFAULT_VIEW);
  });

  it("handles array query values", () => {
    expect(firstParam(["results", "home"])).toBe("results");
    expect(parseView(["results", "home"])).toBe("results");
    expect(parseAnalysisSection(["tests", "bugs"])).toBe("tests");
    expect(parseAppLocation({ view: ["trace"], section: ["automation"] })).toEqual({
      view: "trace",
      section: DEFAULT_ANALYSIS_SECTION,
      testId: null,
    });
  });

  it("missing Results section returns default", () => {
    expect(parseAnalysisSection(undefined)).toBe(DEFAULT_ANALYSIS_SECTION);
    expect(parseAppLocation({ view: "results" }).section).toBe(DEFAULT_ANALYSIS_SECTION);
  });

  it("accepts valid Results sections", () => {
    expect(parseAppLocation({ view: "results", section: "tests" }).section).toBe("tests");
    expect(parseAppLocation({ view: "results", section: "test-cases" }).section).toBe("tests");
    expect(parseAppLocation({ view: "results", section: "automation-review" }).section).toBe(
      "automation"
    );
  });

  it("invalid Results section returns default", () => {
    expect(parseAnalysisSection("nope")).toBe(DEFAULT_ANALYSIS_SECTION);
    expect(parseAppLocation({ view: "results", section: "nope" }).section).toBe(
      DEFAULT_ANALYSIS_SECTION
    );
  });

  it("preserves testId only for results/tests", () => {
    expect(
      parseAppLocation({ view: "results", section: "tests", testId: "TC-1" }).testId
    ).toBe("TC-1");
    expect(parseAppLocation({ view: "results", section: "bugs", testId: "TC-1" }).testId).toBe(
      null
    );
    expect(parseAppLocation({ view: "home", testId: "TC-1" }).testId).toBe(null);
  });

  it("maps legacy output views into results", () => {
    expect(parseAppLocation({ view: "bugs" })).toEqual({
      view: "results",
      section: "bugs",
      testId: null,
    });
  });

  it("buildAppUrl is deterministic and strips stale params", () => {
    expect(
      buildAppUrl("/", { view: "home", section: "overview", testId: null }, "section=tests&testId=x")
    ).toBe("/?view=home");
    expect(
      buildAppUrl("/", { view: "results", section: "tests", testId: "TC-9" })
    ).toBe("/?view=results&section=test-cases&testId=TC-9");
    expect(
      buildAppUrl("/", { view: "results", section: "overview", testId: null })
    ).toBe("/?view=results&section=overview");
  });

  it("same input produces the same output repeatedly", () => {
    const input = { view: "results", section: "automation", testId: "noop" };
    expect(parseAppLocation(input)).toEqual(parseAppLocation(input));
    expect(parseAppLocation(input)).toEqual({
      view: "results",
      section: "automation",
      testId: null,
    });
  });

  it("does not access browser APIs", () => {
    const before = globalThis.window;
    // @ts-expect-error intentional isolation
    delete globalThis.window;
    try {
      expect(parseAppLocation({ view: "copilot" }).view).toBe("copilot");
      expect(buildAppUrl("/", { view: "flow", section: "overview", testId: null })).toBe(
        "/?view=flow"
      );
    } finally {
      globalThis.window = before;
    }
  });
});
