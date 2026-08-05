"""Manual Feature + Scenario creation, validation, and persistence helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.bdd import convert_test_to_bdd, render_gherkin, validate_bdd_scenario
from app.agents.taxonomy import (
    build_normalized_tags,
    build_user_story,
    ensure_test_classified,
    parse_feature_reference,
    section_for_classification,
)
from app.models.enums import (
    ExecutionStatus,
    Priority,
    QualityAttribute,
    SuiteType,
    TestBehavior,
    TestLevel,
    TestNature,
    TestSource,
)
from app.models.schemas import (
    BDDStep,
    FeatureTestSpecification,
    TestCase,
    TestClassification,
    UserStory,
    new_id,
)

_PLACEHOLDER = re.compile(r"<([A-Za-z0-9_]+)>")


class ManualScenarioInput(BaseModel):
    scenario_id: str | None = None
    name: str
    scenario_type: str = "scenario"
    nature: TestNature = TestNature.FUNCTIONAL
    behavior: list[TestBehavior] = Field(default_factory=list)
    quality_attributes: list[QualityAttribute] = Field(default_factory=list)
    test_levels: list[TestLevel] = Field(default_factory=list)
    suite_types: list[SuiteType] = Field(default_factory=list)
    execution_status: ExecutionStatus = ExecutionStatus.MANUAL
    priority: Priority = Priority.MEDIUM
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    bdd_steps: list[BDDStep] = Field(default_factory=list)
    standard_steps: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    examples: list[dict[str, str]] = Field(default_factory=list)
    graph_path: list[str] = Field(default_factory=list)


class ManualFeatureCreateRequest(BaseModel):
    feature_name: str
    feature_reference: str | None = None
    feature_description: str | None = None
    as_a: str | None = None
    i_want: str | None = None
    so_that: str | None = None
    nature: TestNature = TestNature.FUNCTIONAL
    default_priority: Priority = Priority.MEDIUM
    scenarios: list[ManualScenarioInput] = Field(default_factory=list)
    force_overwrite_generated: bool = False


class ManualTestUpdateRequest(BaseModel):
    title: str | None = None
    scenario: ManualScenarioInput | None = None
    feature_name: str | None = None
    feature_reference: str | None = None
    as_a: str | None = None
    i_want: str | None = None
    so_that: str | None = None
    force_overwrite_generated: bool = False


def validate_scenario_steps(scenario: ManualScenarioInput) -> list[str]:
    issues: list[str] = []
    if not (scenario.name or "").strip():
        issues.append("missing_scenario_name")
    steps = scenario.bdd_steps or []
    if not steps and scenario.standard_steps:
        return issues
    if not steps:
        issues.append("missing_steps")
        return issues
    keywords = [(s.keyword or "").strip() for s in steps]
    texts = [(s.text or "").strip() for s in steps]
    if any(k not in {"Given", "When", "Then", "And", "But"} for k in keywords):
        issues.append("invalid_step_keyword")
    if any(not t for t in texts):
        issues.append("empty_step_text")
    if keywords and keywords[0] in {"And", "But"}:
        issues.append("scenario_starts_with_and_or_but")
    if not any(k == "When" for k in keywords):
        issues.append("missing_when")
    if not any(k == "Then" for k in keywords):
        issues.append("missing_then")

    placeholders: set[str] = set()
    for s in steps:
        placeholders.update(_PLACEHOLDER.findall(s.text or ""))
    stype = (scenario.scenario_type or "scenario").lower()
    if stype in {"scenario_outline", "outline"}:
        if not scenario.examples:
            issues.append("outline_missing_examples")
        else:
            headers = set(scenario.examples[0].keys())
            for row in scenario.examples:
                if set(row.keys()) != headers:
                    issues.append("inconsistent_example_headers")
                    break
            missing = placeholders - headers
            if missing:
                issues.append(f"example_headers_missing_placeholders:{','.join(sorted(missing))}")
            if len(scenario.examples) < 1:
                issues.append("outline_needs_data_rows")
    elif scenario.examples and not placeholders:
        issues.append("unnecessary_examples")
    return issues


def _classification_from_scenario(sc: ManualScenarioInput, default_priority: Priority) -> TestClassification:
    behavior = list(sc.behavior) or (
        [TestBehavior.NEGATIVE] if "negative" in (sc.name or "").lower() else [TestBehavior.POSITIVE]
    )
    suites = list(sc.suite_types) or [SuiteType.REGRESSION]
    return TestClassification(
        nature=sc.nature,
        behavior=behavior,
        quality_attributes=list(sc.quality_attributes),
        test_levels=list(sc.test_levels),
        suite_types=suites,
        execution_status=sc.execution_status or ExecutionStatus.MANUAL,
        priority=sc.priority or default_priority,
        source=TestSource.MANUAL,
    )


def scenario_to_test_case(
    sc: ManualScenarioInput,
    *,
    project_id: str,
    feature_name: str,
    feature_reference: str | None,
    user_story: UserStory,
    default_priority: Priority,
) -> tuple[TestCase, dict[str, Any]]:
    issues = validate_scenario_steps(sc)
    if issues:
        raise ValueError(";".join(issues))

    cls = _classification_from_scenario(sc, default_priority)
    tags = build_normalized_tags(cls, extra=sc.tags)
    expected = " and ".join(sc.expected_results) if sc.expected_results else ""
    if not expected and sc.bdd_steps:
        expected = " ".join(s.text for s in sc.bdd_steps if s.keyword in {"Then", "And"})
    steps = list(sc.standard_steps)
    if not steps and sc.bdd_steps:
        steps = [s.text for s in sc.bdd_steps if s.keyword in {"When", "And", "But"}]

    tc = TestCase(
        test_case_id=sc.scenario_id or new_id("TC"),
        title=sc.name.strip(),
        category="functional",
        priority=cls.priority,
        preconditions=list(sc.preconditions),
        test_data=dict(sc.test_data or {}),
        steps=steps or [s.text for s in sc.bdd_steps],
        expected_result=expected or "Observable outcome is confirmed",
        graph_path=list(sc.graph_path) or [feature_name],
        project_id=project_id,
        generation_method="manual",
        reasoning=sc.description,
        objective=sc.description,
        classification=cls,
        human_edited=True,
    )
    tc = ensure_test_classified(tc)
    bdd, status, notes = convert_test_to_bdd(
        tc,
        feature_name=feature_name,
        feature_description=user_story.to_description(),
    )
    if bdd is None:
        # Fall back to explicit BDD steps from the form
        from app.models.schemas import BDDScenario

        section = section_for_classification(cls)
        bdd = BDDScenario(
            feature=feature_name,
            feature_reference=feature_reference,
            feature_description=user_story.to_description(),
            section=section,
            rule=section,
            scenario_name=sc.name.strip(),
            scenario_type="scenario_outline"
            if (sc.scenario_type or "").lower() in {"scenario_outline", "outline"}
            else "scenario",
            tags=tags,
            steps=list(sc.bdd_steps),
            examples=list(sc.examples or []),
            priority=cls.priority.value,
            test_type=tc.category,
            classification=cls,
            graph_path=tc.graph_path,
            generation_method="manual",
            source_test_id=tc.test_case_id,
            conversion_status="ok" if not notes else "needs_revision",
            conversion_notes=notes,
        )
        bdd.gherkin_text = render_gherkin(bdd, tags_before_scenario=True)
        status = "ok"
    else:
        bdd.feature_reference = feature_reference
        bdd.feature_description = user_story.to_description()
        bdd.tags = tags or bdd.tags
        bdd.classification = cls
        bdd.section = section_for_classification(cls)
        bdd.rule = bdd.section
        if sc.bdd_steps:
            bdd.steps = list(sc.bdd_steps)
        if sc.examples:
            bdd.examples = list(sc.examples)
            bdd.scenario_type = "scenario_outline"
        bdd.gherkin_text = render_gherkin(bdd, tags_before_scenario=True)
        issues2 = validate_bdd_scenario(bdd)
        if issues2:
            bdd.conversion_status = "needs_revision"
            bdd.conversion_notes = list(dict.fromkeys((bdd.conversion_notes or []) + issues2))

    payload = tc.model_dump(mode="json")
    payload["bdd_scenario"] = bdd.model_dump(mode="json") if bdd else None
    payload["logical_test_id"] = tc.test_case_id
    payload["human_edited"] = True
    payload["feature_story"] = user_story.model_dump(mode="json")
    payload["feature_reference"] = feature_reference
    return tc, payload


def create_manual_feature_tests(
    project_id: str,
    body: ManualFeatureCreateRequest,
    store: Any,
) -> dict[str, Any]:
    if not (body.feature_name or "").strip():
        raise ValueError("feature_name_required")
    if not body.scenarios:
        raise ValueError("at_least_one_scenario_required")

    fname, fref = parse_feature_reference(body.feature_name.strip())
    feature_reference = body.feature_reference or fref
    story = build_user_story(
        fname,
        actor=body.as_a,
        goal=body.i_want,
        business_value=body.so_that,
    )
    created: list[dict[str, Any]] = []
    for sc in body.scenarios:
        _, payload = scenario_to_test_case(
            sc,
            project_id=project_id,
            feature_name=fname,
            feature_reference=feature_reference,
            user_story=story,
            default_priority=body.default_priority,
        )
        existing = None
        tid = payload.get("test_case_id")
        for row in store.test_cases.values():
            if row.get("project_id") == project_id and row.get("test_case_id") == tid:
                existing = row
                break
        if existing and not existing.get("human_edited") and existing.get("generation_method") not in {
            "manual",
            None,
        }:
            if not body.force_overwrite_generated:
                raise ValueError(f"refuse_overwrite_generated:{tid}")
        store.upsert_test_case(project_id, payload)
        created.append(payload)

    spec = FeatureTestSpecification(
        feature_name=fname,
        feature_reference=feature_reference,
        description=story.to_description(),
        user_story=story,
        scenario_ids=[c["test_case_id"] for c in created],
    )
    project = store.get_project(project_id) or {"id": project_id}
    stories = dict(project.get("feature_stories") or {})
    stories[fname] = spec.model_dump(mode="json")
    store.update_project_meta(project_id, {"feature_stories": stories})

    return {
        "feature": spec.model_dump(mode="json"),
        "test_cases": created,
        "count": len(created),
    }
