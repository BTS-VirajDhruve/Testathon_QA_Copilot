"""Cucumber-compliant BDD export from a persisted analysis.

Builds typed feature documents from the final logical test suite, reuses existing
BDD when valid, converts Standard tests deterministically, validates structure,
and packages .feature files plus an optional import CSV for test-case forms.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.bdd import (
    convert_test_to_bdd,
    render_feature_file,
    safe_feature_filename,
    slug_tag,
    validate_bdd_scenario,
)
from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.graph.traversal import get_traversal
from app.models.schemas import (
    BDDScenario,
    BDDStep,
    GeneratedTestArtifact,
    ReviewedTestCase,
    TestCase,
    utc_now,
)

logger = get_logger(__name__)

EXPORTER_VERSION = "1.1.0"
MAX_BACKGROUND_STEPS = 4

ExportScope = Literal[
    "all_final_generated",
    "valid_only",
    "current_filtered",
    "selected",
]


class BDDExportError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class BDDExportRequest(BaseModel):
    scope: ExportScope = "all_final_generated"
    test_ids: list[str] = Field(default_factory=list)
    include_traceability_comments: bool = True
    include_tags: bool = True
    include_import_csv: bool = True
    language: str = "en"
    strict: bool = True


class ExcludedTest(BaseModel):
    test_id: str
    title: str = ""
    reason: str
    suggested_correction: str | None = None


class FeatureFilePayload(BaseModel):
    filename: str
    feature_name: str
    content: str
    scenario_count: int
    logical_test_ids: list[str] = Field(default_factory=list)


class BDDExportManifest(BaseModel):
    project_id: str
    analysis_id: str
    project_name: str | None = None
    selected_feature: str | None = None
    export_timestamp: str
    scope: str
    language: str = "en"
    logical_test_count: int = 0
    scenario_count: int = 0
    outline_row_count: int = 0
    files: list[str] = Field(default_factory=list)
    included_test_ids: list[str] = Field(default_factory=list)
    excluded_tests: list[ExcludedTest] = Field(default_factory=list)
    validation_status: str = "ok"
    traceability_comments_enabled: bool = True
    tags_enabled: bool = True
    import_csv_enabled: bool = True
    strict: bool = True
    exporter_version: str = EXPORTER_VERSION
    converted_count: int = 0
    reused_bdd_count: int = 0
    repair_count: int = 0


class BDDExportPreview(BaseModel):
    project_id: str
    analysis_id: str
    status: str = "ok"
    file_count: int = 0
    scenario_count: int = 0
    logical_test_count: int = 0
    excluded_tests: list[ExcludedTest] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    files: list[FeatureFilePayload] = Field(default_factory=list)
    csv_preview: str | None = None
    steps_csv: str | None = None
    manifest: BDDExportManifest


class BDDExportPackage(BaseModel):
    project_id: str
    analysis_id: str
    filename: str
    content_type: str
    content: bytes
    preview: BDDExportPreview


def _tags_for_form(tags: list[str] | None) -> str:
    """Semicolon-separated tags without leading @ — matches form chip entry."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        text = (raw or "").strip()
        if text.startswith("@"):
            text = text[1:]
        text = text.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return ";".join(cleaned)


def _scenario_type_label(scenario_type: str | None) -> str:
    if (scenario_type or "").lower() in {"scenario_outline", "outline"}:
        return "Scenario Outline"
    return "Scenario"


def _section_for_scenario(sc: BDDScenario) -> str:
    section = (sc.section or sc.rule or "").strip().upper()
    if section:
        return section
    if sc.classification is not None:
        from app.agents.taxonomy import section_for_classification

        return section_for_classification(sc.classification)
    from app.agents.bdd import scenario_section

    return scenario_section(sc.test_type)


def _priority_for_csv(sc: BDDScenario) -> str:
    for tag in sc.tags or []:
        t = tag.lstrip("@").lower()
        if t.startswith("priority-"):
            return t.replace("priority-", "", 1)
    return (sc.priority or "medium").lower()


def _automation_for_csv(sc: BDDScenario) -> str:
    for tag in sc.tags or []:
        t = tag.lstrip("@").lower()
        if t.startswith("automation-"):
            return t.replace("automation-", "", 1)
        if t in {"automatable", "automate"}:
            return "yes"
        if t in {"conditional-automation", "hybrid"}:
            return "partial"
        if t == "manual":
            return "no"
    return "yes"


def render_import_csv(scenarios: list[BDDScenario]) -> str:
    """CSV for New Test Case form import — one row per scenario.

    Columns map to Journey Editor / New Test Case fields:
      feature_name, feature_description, section, scenario_name, scenario_type,
      tags, steps (Keyword|text lines), priority, automation, test_id, graph_path
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        [
            "feature_name",
            "feature_description",
            "section",
            "scenario_name",
            "scenario_type",
            "tags",
            "steps",
            "priority",
            "automation",
            "test_id",
            "graph_path",
        ]
    )
    for sc in scenarios:
        step_lines: list[str] = []
        for step in list(sc.background or []) + list(sc.steps or []):
            keyword = (step.keyword or "Given").strip()
            text = (step.text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            text = text.replace("|", "\\|")
            step_lines.append(f"{keyword}|{text}")
        description = (
            (sc.feature_description or "").replace("\r\n", "\n").replace("\r", "\n")
        )
        writer.writerow(
            [
                sc.feature or "",
                description,
                _section_for_scenario(sc),
                sc.scenario_name or "",
                _scenario_type_label(sc.scenario_type),
                _tags_for_form(sc.tags),
                "\n".join(step_lines),
                _priority_for_csv(sc),
                _automation_for_csv(sc),
                sc.source_test_id or sc.id or "",
                " > ".join(sc.graph_path or []),
            ]
        )
    return buf.getvalue()


def render_steps_csv(scenarios: list[BDDScenario]) -> str:
    """One-row-per-step CSV — easy to edit in Excel then regroup by scenario_name."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        [
            "feature_name",
            "feature_description",
            "section",
            "scenario_name",
            "scenario_type",
            "tags",
            "step_order",
            "keyword",
            "step_text",
            "priority",
            "automation",
            "test_id",
            "graph_path",
        ]
    )
    for sc in scenarios:
        order = 0
        description = (
            (sc.feature_description or "").replace("\r\n", "\n").replace("\r", "\n")
        )
        for step in list(sc.background or []) + list(sc.steps or []):
            order += 1
            writer.writerow(
                [
                    sc.feature or "",
                    description,
                    _section_for_scenario(sc),
                    sc.scenario_name or "",
                    _scenario_type_label(sc.scenario_type),
                    _tags_for_form(sc.tags),
                    order,
                    (step.keyword or "Given").strip(),
                    (step.text or "").strip(),
                    _priority_for_csv(sc),
                    _automation_for_csv(sc),
                    sc.source_test_id or sc.id or "",
                    " > ".join(sc.graph_path or []),
                ]
            )
    return buf.getvalue()


def _analysis_id_for(analysis: dict[str, Any], project_id: str) -> str:
    """Stable-ish id for latest analysis (no multi-analysis store yet)."""
    trace = analysis.get("execution_trace") or []
    stamp = ""
    if trace:
        stamp = str(trace[-1].get("timestamp") or "")
    query = str(analysis.get("query") or "")[:48]
    base = slug_tag(f"{project_id}-{stamp}-{query}") or "latest"
    return f"latest-{base}"[:80]


def _as_test_case(raw: Any) -> TestCase | None:
    try:
        if isinstance(raw, TestCase):
            return raw
        return TestCase.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def _as_bdd(raw: Any) -> BDDScenario | None:
    try:
        if isinstance(raw, BDDScenario):
            return raw
        return BDDScenario.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def _validity_map(analysis: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in analysis.get("reviewed_test_cases") or []:
        try:
            reviewed = (
                ReviewedTestCase.model_validate(row)
                if not isinstance(row, ReviewedTestCase)
                else row
            )
        except Exception:  # noqa: BLE001
            continue
        tid = reviewed.test_case.test_case_id if reviewed.test_case else None
        validity = (
            getattr(reviewed.validity_review, "validity", None)
            if reviewed.validity_review
            else None
        )
        if tid and validity is not None:
            out[tid] = str(validity.value if hasattr(validity, "value") else validity)
    for bucket, label in (
        ("valid_tests", "valid"),
        ("invalid_tests", "invalid"),
        ("needs_revision_tests", "needs_revision"),
        ("insufficient_evidence_tests", "insufficient_evidence"),
    ):
        for row in analysis.get(bucket) or []:
            tc = _as_test_case(row)
            if tc and tc.test_case_id not in out:
                out[tc.test_case_id] = label
    return out


def _automation_tags(analysis: dict[str, Any], test_id: str) -> list[str]:
    tags: list[str] = []
    for row in analysis.get("reviewed_test_cases") or []:
        try:
            reviewed = (
                ReviewedTestCase.model_validate(row)
                if not isinstance(row, ReviewedTestCase)
                else row
            )
        except Exception:  # noqa: BLE001
            continue
        tid = reviewed.test_case.test_case_id if reviewed.test_case else None
        if tid != test_id or not reviewed.automation_review:
            continue
        suit = str(
            getattr(reviewed.automation_review, "automation_suitability", "") or ""
        ).lower()
        mapping = {
            "automate": "@automation-yes",
            "automate_with_conditions": "@automation-partial",
            "hybrid": "@automation-partial",
            "manual": "@automation-no",
        }
        if suit in mapping:
            tags.append(mapping[suit])
        layer = str(
            getattr(reviewed.automation_review, "recommended_layer", "") or ""
        ).lower()
        if layer in {"ui", "api", "integration"}:
            tags.append(f"@{layer}")
        break
    return tags


def _normalize_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    legacy_priority = {"critical", "high", "medium", "low"}
    legacy_auto = {
        "automatable": "automation-yes",
        "automate": "automation-yes",
        "conditional-automation": "automation-partial",
        "hybrid": "automation-partial",
        "manual": "automation-no",
    }
    for raw in tags:
        text = (raw or "").strip().lower()
        if not text:
            continue
        if not text.startswith("@"):
            text = f"@{text}"
        text = text.replace(" ", "-")
        text = "".join(ch for ch in text if ch.isalnum() or ch in {"@", "-", "_"})
        bare = text[1:]
        if bare in legacy_priority:
            text = f"@priority-{bare}"
        elif bare in legacy_auto:
            text = f"@{legacy_auto[bare]}"
        if text in {"@", "@-"} or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out[:12]


def _collect_logical_tests(
    analysis: dict[str, Any],
    *,
    project_id: str,
    scope: ExportScope,
    test_ids: list[str],
) -> tuple[list[TestCase], list[ExcludedTest], dict[str, BDDScenario]]:
    """Return deduped final logical tests + existing BDD index by source/logical id."""
    if analysis.get("project_id") and analysis["project_id"] != project_id:
        raise BDDExportError(
            "PROJECT_MISMATCH",
            "Analysis project_id does not match the requested project.",
            {
                "analysis_project_id": analysis.get("project_id"),
                "project_id": project_id,
            },
        )

    existing_bdd: dict[str, BDDScenario] = {}
    for row in analysis.get("bdd_scenarios") or []:
        sc = _as_bdd(row)
        if not sc:
            continue
        key = sc.source_test_id or sc.id
        if key:
            existing_bdd[key] = sc

    for row in analysis.get("generated_test_artifacts") or []:
        try:
            art = (
                GeneratedTestArtifact.model_validate(row)
                if not isinstance(row, GeneratedTestArtifact)
                else row
            )
        except Exception:  # noqa: BLE001
            continue
        if art.bdd_scenario and art.bdd_scenario.conversion_status == "ok":
            key = (
                art.logical_test_id
                or art.source_test_id
                or art.bdd_scenario.source_test_id
            )
            if key:
                existing_bdd[key] = art.bdd_scenario

    by_id: dict[str, TestCase] = {}
    excluded: list[ExcludedTest] = []

    # Prefer artifacts for logical identity; fall back to test_cases
    artifacts = analysis.get("generated_test_artifacts") or []
    if artifacts:
        for row in artifacts:
            try:
                art = (
                    GeneratedTestArtifact.model_validate(row)
                    if not isinstance(row, GeneratedTestArtifact)
                    else row
                )
            except Exception:  # noqa: BLE001
                continue
            tc = art.standard_test_case
            if tc is None:
                continue
            if tc.project_id and tc.project_id != project_id:
                raise BDDExportError(
                    "PROJECT_MISMATCH",
                    f"Test {tc.test_case_id} belongs to another project.",
                    {"test_id": tc.test_case_id, "test_project_id": tc.project_id},
                )
            lid = art.logical_test_id or tc.test_case_id
            by_id[lid] = tc
            if art.bdd_scenario and art.bdd_scenario.conversion_status == "ok":
                existing_bdd[lid] = art.bdd_scenario
    else:
        for row in analysis.get("test_cases") or []:
            tc = _as_test_case(row)
            if not tc:
                continue
            if tc.project_id and tc.project_id != project_id:
                raise BDDExportError(
                    "PROJECT_MISMATCH",
                    f"Test {tc.test_case_id} belongs to another project.",
                    {"test_id": tc.test_case_id, "test_project_id": tc.project_id},
                )
            by_id[tc.test_case_id] = tc

    validity = _validity_map(analysis)
    selected = set(test_ids or [])

    filtered: list[TestCase] = []
    for lid, tc in by_id.items():
        if scope == "selected":
            if lid not in selected and tc.test_case_id not in selected:
                continue
        if scope in {"valid_only", "current_filtered"}:
            # current_filtered with no client filter == valid_only semantics on backend
            if validity:
                status = validity.get(tc.test_case_id) or validity.get(lid)
                if status != "valid":
                    excluded.append(
                        ExcludedTest(
                            test_id=tc.test_case_id,
                            title=tc.title,
                            reason="validity_not_valid",
                            suggested_correction="Fix validity issues or use All Final Generated Tests.",
                        )
                    )
                    continue
            # If no validity data exists, valid_only cannot silently invent validity —
            # attempt conversion for all remaining tests.
        if scope == "selected" and not selected:
            raise BDDExportError(
                "NO_TESTS",
                "Selected Tests scope requires at least one test id.",
            )
        filtered.append(tc)

    if scope == "selected" and selected and not filtered:
        raise BDDExportError(
            "INVALID_TEST_REFERENCE",
            "None of the selected test ids belong to this analysis.",
            {"test_ids": list(selected)[:20]},
        )

    return filtered, excluded, existing_bdd


def _apply_declarative_style(scenario: BDDScenario) -> BDDScenario:
    """Light deterministic rewrite to prefer business wording over click/type wording."""
    procedural = (
        r"\b(click(?:s|ing)?|type(?:s|ing)?|enter(?:s|ing)? into|css selector|xpath|"
        r"locate(?:s|ing)? an? element|open url)\b"
    )
    import re

    new_steps: list[BDDStep] = []
    for step in scenario.steps:
        text = step.text
        # Keep UI wording when the step is explicitly about UI state
        ui_behavior = re.search(
            r"\b(keyboard|focus|screen[- ]reader|disabled|visible validation|"
            r"responsive|aria-|announcement)\b",
            text,
            re.I,
        )
        if not ui_behavior and re.search(procedural, text, re.I):
            text = re.sub(
                r"\bclicks?\s+(?:the\s+)?([A-Za-z0-9 _-]+)\s+button\b",
                r"chooses \1",
                text,
                flags=re.I,
            )
            text = re.sub(
                r"\btypes?\s+.+\s+into\s+(?:the\s+)?([A-Za-z0-9 _-]+)\s*(?:field|textbox|input)?\b",
                r"provides a value for \1",
                text,
                flags=re.I,
            )
            text = re.sub(
                r"\bopens?\s+url\s+\S+",
                "navigates to the relevant page",
                text,
                flags=re.I,
            )
        new_steps.append(BDDStep(keyword=step.keyword, text=text.strip()))
    return scenario.model_copy(update={"steps": new_steps})


def _enrich_tags(
    scenario: BDDScenario,
    *,
    analysis: dict[str, Any],
    include_tags: bool,
) -> BDDScenario:
    if not include_tags:
        return scenario.model_copy(update={"tags": []})
    tags = list(scenario.tags or [])
    # Drop conflicting legacy automation tags before adding review-based ones
    tags = [
        t
        for t in tags
        if not str(t).lstrip("@").lower().startswith("automation-")
        and str(t).lstrip("@").lower()
        not in {"automatable", "manual", "hybrid", "conditional-automation"}
    ]
    if scenario.source_test_id:
        tags.extend(_automation_tags(analysis, scenario.source_test_id))
    if not any(str(t).lstrip("@").lower().startswith("automation-") for t in tags):
        tags.append("@automation-yes")
    if not any(str(t).lstrip("@").lower() == "regression" for t in tags):
        tags.append("@regression")
    if scenario.generation_method == "critic":
        tags.append("@targeted")
    return scenario.model_copy(update={"tags": _normalize_tags(tags)})


def _resolve_scenarios(
    tests: list[TestCase],
    *,
    existing_bdd: dict[str, BDDScenario],
    analysis: dict[str, Any],
    feature_fallback: str | None,
    include_tags: bool,
    valid_node_names: set[str] | None,
    evidence_ids: set[str] | None,
) -> tuple[list[BDDScenario], list[ExcludedTest], int, int]:
    scenarios: list[BDDScenario] = []
    excluded: list[ExcludedTest] = []
    converted = 0
    reused = 0
    seen_names: set[str] = set()

    for tc in tests:
        feature = feature_fallback or (
            tc.graph_path[0] if tc.graph_path else "Generated Feature"
        )
        reused_sc = existing_bdd.get(tc.test_case_id)
        scenario: BDDScenario | None = None
        notes: list[str] = []

        if reused_sc and reused_sc.conversion_status == "ok":
            scenario = reused_sc.model_copy(deep=True)
            if not scenario.feature:
                scenario.feature = feature
            if not scenario.feature_description:
                from app.agents.bdd import build_feature_description

                scenario.feature_description = build_feature_description(
                    scenario.feature
                )
            if not scenario.rule:
                from app.agents.bdd import scenario_section

                scenario.rule = scenario_section(tc.category or scenario.test_type)
            reused += 1
        else:
            scenario, status, notes = convert_test_to_bdd(tc, feature_name=feature)
            if scenario is None or status != "ok":
                excluded.append(
                    ExcludedTest(
                        test_id=tc.test_case_id,
                        title=tc.title,
                        reason=",".join(notes) or "bdd_conversion_failed",
                        suggested_correction=(
                            "Provide a clear primary action and observable expected result."
                        ),
                    )
                )
                continue
            converted += 1

        scenario = _apply_declarative_style(scenario)
        scenario = _enrich_tags(scenario, analysis=analysis, include_tags=include_tags)
        issues = validate_bdd_scenario(
            scenario,
            valid_node_names=valid_node_names,
            evidence_ids=evidence_ids,
            seen_names=seen_names,
        )
        if issues:
            excluded.append(
                ExcludedTest(
                    test_id=tc.test_case_id,
                    title=tc.title,
                    reason=",".join(issues),
                    suggested_correction="Revise the scenario so it has Given/When/Then and unique name.",
                )
            )
            continue
        scenarios.append(scenario)

    return scenarios, excluded, converted, reused


def _group_by_feature(scenarios: list[BDDScenario]) -> dict[str, list[BDDScenario]]:
    groups: dict[str, list[BDDScenario]] = {}
    for sc in scenarios:
        key = (sc.feature or "Generated Feature").strip() or "Generated Feature"
        groups.setdefault(key, []).append(sc)
    return groups


def _limit_shared_background(scenarios: list[BDDScenario]) -> list[BDDScenario]:
    """Cap shared background length; excess stays in scenarios (renderer extracts shared)."""
    if not scenarios:
        return scenarios
    backgrounds = [
        tuple((s.keyword, s.text) for s in sc.background) for sc in scenarios
    ]
    if not backgrounds or not all(b == backgrounds[0] and b for b in backgrounds):
        return scenarios
    shared = backgrounds[0]
    if len(shared) <= MAX_BACKGROUND_STEPS:
        return scenarios
    # Keep only the first N as background; move the rest into each scenario's steps as Given/And
    keep = shared[:MAX_BACKGROUND_STEPS]
    overflow = shared[MAX_BACKGROUND_STEPS:]
    updated: list[BDDScenario] = []
    for sc in scenarios:
        overflow_steps = [BDDStep(keyword=k, text=t) for k, t in overflow]
        # Ensure first overflow continues with And if needed
        updated.append(
            sc.model_copy(
                update={
                    "background": [BDDStep(keyword=k, text=t) for k, t in keep],
                    "steps": overflow_steps + list(sc.steps),
                }
            )
        )
    return updated


def _validate_feature_document(content: str, scenarios: list[BDDScenario]) -> list[str]:
    issues: list[str] = []
    feature_count = sum(
        1 for line in content.splitlines() if line.startswith("Feature:")
    )
    if feature_count != 1:
        issues.append(f"feature_count_{feature_count}")
    if "Scenario:" not in content and "Scenario Outline:" not in content:
        issues.append("missing_scenario_keyword")
    names = [normalize_name(sc.scenario_name) for sc in scenarios]
    if len(names) != len(set(names)):
        issues.append("duplicate_scenario_names_in_file")
    background_lines = [
        line for line in content.splitlines() if line.strip() == "Background:"
    ]
    if len(background_lines) > 1:
        issues.append("multiple_backgrounds")
    return issues


def normalize_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def build_export_preview(
    project_id: str,
    request: BDDExportRequest,
    *,
    analysis: dict[str, Any] | None = None,
) -> BDDExportPreview:
    if request.language.lower() != "en":
        raise BDDExportError(
            "UNSUPPORTED_LANGUAGE",
            "Only English (en) Gherkin export is supported currently.",
            {"language": request.language},
        )

    store = get_graph_store()
    project = store.get_project(project_id)
    if not project:
        raise BDDExportError(
            "ANALYSIS_NOT_FOUND", "Project not found.", {"project_id": project_id}
        )

    analysis = (
        analysis if analysis is not None else store.get_latest_analysis(project_id)
    )
    if not analysis:
        raise BDDExportError(
            "ANALYSIS_NOT_FOUND",
            "No persisted analysis found for this project.",
            {"project_id": project_id},
        )

    analysis_id = _analysis_id_for(analysis, project_id)
    tests, scope_excluded, existing_bdd = _collect_logical_tests(
        analysis,
        project_id=project_id,
        scope=request.scope,
        test_ids=request.test_ids,
    )
    if not tests and request.scope != "valid_only":
        raise BDDExportError("NO_TESTS", "No generated tests are available to export.")

    from app.agents.dedup import normalize_text

    graph = get_traversal().load_flow(project_id)
    valid_nodes = {
        normalize_text(n.name) for n in graph.nodes if n.name and normalize_text(n.name)
    }
    evidence_ids: set[str] = set()
    for tc in tests:
        for ev in tc.evidence or []:
            if ev.source_id:
                evidence_ids.add(ev.source_id)

    scenarios, conversion_excluded, converted, reused = _resolve_scenarios(
        tests,
        existing_bdd=existing_bdd,
        analysis=analysis,
        feature_fallback=analysis.get("root_feature") or project.get("name"),
        include_tags=request.include_tags,
        valid_node_names=valid_nodes,
        evidence_ids=evidence_ids or None,
    )
    excluded = scope_excluded + conversion_excluded

    if (
        request.strict
        and conversion_excluded
        and request.scope == "all_final_generated"
    ):
        raise BDDExportError(
            "BDD_CONVERSION_FAILED",
            "One or more tests could not be converted into valid Gherkin.",
            {
                "excluded_tests": [e.model_dump() for e in conversion_excluded],
                "valid_only_available": True,
                "convertible_count": len(scenarios),
                "failed_count": len(conversion_excluded),
            },
        )

    if not scenarios:
        raise BDDExportError(
            "NO_TESTS",
            "No valid Gherkin scenarios remain after conversion/filtering.",
            {"excluded_tests": [e.model_dump() for e in excluded]},
        )

    groups = _group_by_feature(scenarios)
    files: list[FeatureFilePayload] = []
    warnings: list[str] = []
    project_name = project.get("name")

    for feature_name, group in groups.items():
        group = _limit_shared_background(group)
        content = render_feature_file(
            group,
            feature_name=feature_name,
            include_traceability_comments=request.include_traceability_comments,
            include_feature_tags=request.include_tags,
        )
        doc_issues = _validate_feature_document(content, group)
        if doc_issues:
            raise BDDExportError(
                "GHERKIN_VALIDATION_FAILED",
                f"Rendered feature '{feature_name}' failed structural validation.",
                {"feature": feature_name, "issues": doc_issues},
            )
        filename = safe_feature_filename(feature_name, project_name)
        files.append(
            FeatureFilePayload(
                filename=filename,
                feature_name=feature_name,
                content=content,
                scenario_count=len(group),
                logical_test_ids=[s.source_test_id or s.id for s in group],
            )
        )

    outline_rows = sum(
        len(sc.examples)
        for group in groups.values()
        for sc in group
        if sc.scenario_type == "scenario_outline"
    )
    included_ids = [s.source_test_id or s.id for s in scenarios]
    csv_preview = render_import_csv(scenarios) if request.include_import_csv else None
    steps_csv = render_steps_csv(scenarios) if request.include_import_csv else None
    manifest_files = [f.filename for f in files]
    if request.include_import_csv:
        manifest_files.extend(["test-cases-import.csv", "test-steps-import.csv"])
    manifest = BDDExportManifest(
        project_id=project_id,
        analysis_id=analysis_id,
        project_name=project_name,
        selected_feature=analysis.get("root_feature"),
        export_timestamp=utc_now().isoformat(),
        scope=request.scope,
        language=request.language,
        logical_test_count=len(tests),
        scenario_count=len(scenarios),
        outline_row_count=outline_rows,
        files=manifest_files,
        included_test_ids=included_ids,
        excluded_tests=excluded,
        validation_status="ok",
        traceability_comments_enabled=request.include_traceability_comments,
        tags_enabled=request.include_tags,
        import_csv_enabled=request.include_import_csv,
        strict=request.strict,
        converted_count=converted,
        reused_bdd_count=reused,
    )

    logger.info(
        "bdd_export_prepared",
        extra={
            "project_id": project_id,
            "analysis_id": analysis_id,
            "scope": request.scope,
            "logical_test_count": len(tests),
            "scenario_count": len(scenarios),
            "file_count": len(files),
            "converted_count": converted,
            "reused_bdd_count": reused,
            "excluded_count": len(excluded),
            "import_csv": request.include_import_csv,
        },
    )

    return BDDExportPreview(
        project_id=project_id,
        analysis_id=analysis_id,
        status="ok",
        file_count=len(files),
        scenario_count=len(scenarios),
        logical_test_count=len(tests),
        excluded_tests=excluded,
        warnings=warnings,
        files=files,
        csv_preview=csv_preview,
        steps_csv=steps_csv,
        manifest=manifest,
    )


def build_export_package(
    project_id: str, request: BDDExportRequest
) -> BDDExportPackage:
    preview = build_export_preview(project_id, request)
    project_name = preview.manifest.project_name or "project"
    analysis_slug = slug_tag(preview.analysis_id) or "latest"
    project_slug = slug_tag(project_name) or "project"

    # Primary deliverable for form import: CSV (not .feature / ZIP)
    if request.include_import_csv:
        csv_body = preview.csv_preview or render_import_csv([])
        csv_name = f"{project_slug}-{analysis_slug}-test-cases.csv"
        return BDDExportPackage(
            project_id=project_id,
            analysis_id=preview.analysis_id,
            filename=csv_name,
            content_type="text/csv; charset=utf-8",
            content=csv_body.encode("utf-8"),
            preview=preview,
        )

    if len(preview.files) == 1:
        file = preview.files[0]
        return BDDExportPackage(
            project_id=project_id,
            analysis_id=preview.analysis_id,
            filename=file.filename,
            content_type="text/plain; charset=utf-8",
            content=file.content.encode("utf-8"),
            preview=preview,
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in preview.files:
            zf.writestr(f"features/{file.filename}", file.content.encode("utf-8"))
        zf.writestr(
            "export-manifest.json",
            json.dumps(preview.manifest.model_dump(mode="json"), indent=2).encode(
                "utf-8"
            ),
        )
        report_lines = [
            "# BDD Export Report",
            "",
            f"- Project: {project_name}",
            f"- Analysis: {preview.analysis_id}",
            f"- Scope: {preview.manifest.scope}",
            f"- Scenarios: {preview.scenario_count}",
            f"- Feature files: {preview.file_count}",
            f"- Excluded: {len(preview.excluded_tests)}",
            "",
            "Note: This package contains Gherkin feature files only.",
            "It does not include executable Cucumber step definitions.",
        ]
        zf.writestr("export-report.md", "\n".join(report_lines).encode("utf-8"))

    zip_name = f"{project_slug}-{analysis_slug}-bdd.zip"
    return BDDExportPackage(
        project_id=project_id,
        analysis_id=preview.analysis_id,
        filename=zip_name,
        content_type="application/zip",
        content=buf.getvalue(),
        preview=preview,
    )


def _csv_readme() -> str:
    return """# Test Case Import CSV

These CSVs map exported BDD scenarios into a New Test Case form (Journey Editor style).

## test-cases-import.csv (one row per scenario)

| Column | Form / Gherkin field |
|--------|----------------------|
| feature_name | Feature: … |
| feature_description | As a / I want / So that |
| section | # FUNCTIONAL or # NEGATIVE |
| scenario_name | Scenario name |
| scenario_type | Type (Scenario / Scenario Outline) |
| tags | Tags without @ (e.g. priority-high;regression;automation-yes) |
| steps | Step rows — each line is `Keyword|step text` |
| priority | high / medium / low / critical |
| automation | yes / partial / no |

Example `steps` cell:

```
Given|the admin is in Helix Studio
When|they create a new journey with name "Leader Onboarding"
Then|the journey is created and listed in the journey library
And|all entered details are persisted on reload
```

## Tag tips

Map exported tags into form chips where possible:

- `regression` → Regression
- `automation-yes` → Automation
- `priority-high` / `priority-medium` → custom priority tags
"""
