/**
 * Canonical URL-driven navigation for the Agentic QA Copilot shell.
 * Pure parsers — no browser APIs. Safe for server and client.
 */
import type { AppView } from "./types";
import {
  LEGACY_VIEW_TO_SECTION,
  WORKFLOW_NAV,
  isPrimaryView,
  parseSectionParam,
  sectionToQueryParam,
  type PrimaryAppView,
  type ResultSection,
} from "./workflow";

export type { PrimaryAppView, ResultSection };

/** Product default landing view. */
export const DEFAULT_VIEW: PrimaryAppView = "home";

/** Default Analysis Results tab. */
export const DEFAULT_ANALYSIS_SECTION: ResultSection = "overview";

export const VALID_VIEWS: readonly PrimaryAppView[] = WORKFLOW_NAV.map((item) => item.id);

export const VALID_ANALYSIS_SECTIONS: readonly ResultSection[] = [
  "overview",
  "tests",
  "automation",
  "exploratory",
  "bugs",
  "regression",
  "coverage",
  "evidence",
] as const;

export type AppLocation = {
  view: PrimaryAppView;
  section: ResultSection;
  testId: string | null;
};

export type SearchParamInput = string | string[] | undefined | null;

/** Normalize Next.js searchParams values to a single string. */
export function firstParam(value: SearchParamInput): string | undefined {
  if (value == null) return undefined;
  if (Array.isArray(value)) {
    const first = value.find((v) => typeof v === "string" && v.trim().length > 0);
    return first?.trim();
  }
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}

export function parseView(raw: SearchParamInput): PrimaryAppView {
  const value = firstParam(raw)?.toLowerCase();
  if (!value) return DEFAULT_VIEW;

  if (isPrimaryView(value as AppView)) {
    return value as PrimaryAppView;
  }

  const legacy = LEGACY_VIEW_TO_SECTION[value as AppView];
  if (legacy) {
    return "results";
  }

  return DEFAULT_VIEW;
}

export function parseAnalysisSection(raw: SearchParamInput): ResultSection {
  const value = firstParam(raw);
  if (!value) return DEFAULT_ANALYSIS_SECTION;
  const parsed = parseSectionParam(value);
  return VALID_ANALYSIS_SECTIONS.includes(parsed) ? parsed : DEFAULT_ANALYSIS_SECTION;
}

/**
 * Parse application location from query-like input.
 * Never reads window / localStorage.
 */
export function parseAppLocation(query: {
  view?: SearchParamInput;
  section?: SearchParamInput;
  results?: SearchParamInput;
  testId?: SearchParamInput;
}): AppLocation {
  const rawView = firstParam(query.view)?.toLowerCase();
  let view = parseView(query.view);
  let section = parseAnalysisSection(query.section ?? query.results);

  if (rawView) {
    const legacy = LEGACY_VIEW_TO_SECTION[rawView as AppView];
    if (legacy) {
      view = "results";
      section = legacy;
    }
  }

  if (view !== "results") {
    section = DEFAULT_ANALYSIS_SECTION;
  }

  const testIdRaw = firstParam(query.testId) ?? null;
  const testId = view === "results" && section === "tests" ? testIdRaw : null;

  return { view, section, testId };
}

export function buildAppUrl(
  pathname: string,
  location: Pick<AppLocation, "view" | "section" | "testId">,
  currentSearch?: string | URLSearchParams
): string {
  const params =
    typeof currentSearch === "string"
      ? new URLSearchParams(currentSearch.startsWith("?") ? currentSearch.slice(1) : currentSearch)
      : currentSearch
        ? new URLSearchParams(currentSearch)
        : new URLSearchParams();

  params.set("view", location.view);

  if (location.view === "results") {
    params.set("section", sectionToQueryParam(location.section));
  } else {
    params.delete("section");
    params.delete("results");
  }

  if (location.view === "results" && location.section === "tests" && location.testId) {
    params.set("testId", location.testId);
  } else {
    params.delete("testId");
  }

  const qs = params.toString();
  const base = pathname || "/";
  return qs ? `${base}?${qs}` : base;
}
