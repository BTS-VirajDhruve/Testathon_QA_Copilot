"""BDD / Gherkin rendering, validation, and conservative standard→BDD conversion.

Canonical logical tests remain TestCase objects. BDD is a rendered representation
that preserves graph paths, evidence, priority, and source test IDs.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.dedup import normalize_text
from app.models.enums import TestOutputFormat
from app.models.schemas import (
    BDDScenario,
    BDDStep,
    EvidenceReference,
    GeneratedTestArtifact,
    TestCase,
    new_id,
)

_VALID_KEYWORDS = {"Given", "When", "Then", "And", "But"}
_VAGUE_EXPECTED = re.compile(
    r"^(it\s+works|works|success|successful|ok|pass|fine|good|as\s+expected|"
    r"behaves?\s+as\s+expected|works?\s+correctly)\.?$",
    re.I,
)
_ACTIONISH = re.compile(
    r"\b(click|select|enter|submit|post|get|put|delete|open|navigate|trigger|"
    r"send|create|save|confirm|approve|reject|attempt|perform|invoke|call)\b",
    re.I,
)
_PLACEHOLDER = re.compile(r"<([A-Za-z0-9_]+)>")


def slug_tag(value: str) -> str:
    text = normalize_text(value).replace(" ", "-")
    text = re.sub(r"[^a-z0-9\-]+", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:48]


def scenario_section(category: str | None) -> str:
    """Map legacy category string to section comment."""
    from app.agents.taxonomy import infer_behaviors, infer_nature, section_for_classification
    from app.models.schemas import TestClassification

    cls = TestClassification(
        nature=infer_nature(category or ""),
        behavior=infer_behaviors(category or ""),
    )
    return section_for_classification(cls)


def build_feature_description(feature: str, *, role: str | None = None) -> str:
    """Gherkin feature narrative in As a / I want / So that form."""
    from app.agents.taxonomy import build_user_story

    return build_user_story(feature, role_hint=role).to_description()


def build_tags(tc: TestCase, *, automation: str | None = None) -> list[str]:
    """Normalized tags from TestClassification (+ optional automation hint)."""
    from app.agents.taxonomy import (
        build_normalized_tags,
        ensure_test_classified,
        execution_from_automation_suitability,
    )

    classified = ensure_test_classified(tc, automation_suitability=automation)
    cls = classified.classification
    assert cls is not None
    if automation:
        cls = cls.model_copy(
            update={"execution_status": execution_from_automation_suitability(automation)}
        )
    return build_normalized_tags(cls)


def escape_table_cell(value: str) -> str:
    text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n")


def render_gherkin(
    scenario: BDDScenario,
    *,
    include_feature: bool = True,
    include_traceability_comments: bool = False,
    tags_before_scenario: bool = True,
) -> str:
    """Render a single scenario. Export uses tags_before_scenario=True (Cucumber-valid)."""
    lines: list[str] = []
    if include_feature:
        title = scenario.feature
        if scenario.feature_reference and f"[{scenario.feature_reference}]" not in title:
            title = f"{scenario.feature} [{scenario.feature_reference}]"
        lines.append(f"Feature: {title}")
        description = scenario.feature_description or build_feature_description(scenario.feature)
        for raw_line in str(description).splitlines():
            text = raw_line.strip()
            if text:
                lines.append(f"  {text}")
        lines.append("")
        section = (
            (scenario.section or scenario.rule or "").strip().upper()
            or scenario_section(scenario.test_type)
        )
        if section:
            lines.append(f"  # {section}")
            lines.append("")
    if include_traceability_comments:
        lines.extend(_traceability_comment_lines(scenario, indent="  "))
    keyword = "Scenario Outline" if scenario.scenario_type == "scenario_outline" else "Scenario"
    if tags_before_scenario and scenario.tags:
        lines.append("  " + " ".join(scenario.tags))
    lines.append(f"  {keyword}: {scenario.scenario_name}")
    if not tags_before_scenario and scenario.tags:
        # UI-oriented layout only
        lines.append("    " + " ".join(scenario.tags))
    for step in scenario.background:
        lines.append(f"    {step.keyword} {step.text}")
    for step in scenario.steps:
        lines.append(f"    {step.keyword} {step.text}")
    if scenario.scenario_type == "scenario_outline" and scenario.examples:
        lines.append("    Examples:")
        headers = list(scenario.examples[0].keys())
        lines.append("      | " + " | ".join(escape_table_cell(h) for h in headers) + " |")
        for row in scenario.examples:
            lines.append(
                "      | "
                + " | ".join(escape_table_cell(str(row.get(h, ""))) for h in headers)
                + " |"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_gherkin_ui(scenario: BDDScenario, **kwargs: Any) -> str:
    """UI display renderer — tags may appear under the scenario title."""
    return render_gherkin(scenario, tags_before_scenario=False, **kwargs)


def _traceability_comment_lines(scenario: BDDScenario, *, indent: str = "  ") -> list[str]:
    comments: list[str] = []
    if scenario.source_test_id:
        comments.append(f"{indent}# Test ID: {scenario.source_test_id}")
    if scenario.id:
        comments.append(f"{indent}# Logical Test ID: {scenario.id}")
    if scenario.graph_path:
        comments.append(f"{indent}# Graph Path: {' > '.join(scenario.graph_path)}")
    reqs = [r for r in (scenario.requirement_references or []) if r]
    if reqs:
        comments.append(f"{indent}# Requirements: {', '.join(reqs[:8])}")
    bugs = [b for b in (scenario.bug_references or []) if b]
    if bugs:
        comments.append(f"{indent}# Bugs: {', '.join(bugs[:8])}")
    if scenario.generation_method:
        comments.append(f"{indent}# Generation: {scenario.generation_method}")
    if comments:
        comments.append("")
    return comments


def render_feature_file(
    scenarios: list[BDDScenario],
    *,
    feature_name: str | None = None,
    include_traceability_comments: bool = False,
    include_feature_tags: bool = False,
    max_background_steps: int = 4,
    tags_before_scenario: bool = True,
) -> str:
    """Cucumber-valid feature file. Tags appear before Scenario by default."""
    from app.agents.taxonomy import SECTION_ORDER, section_for_classification

    if not scenarios:
        return ""
    feature = feature_name or scenarios[0].feature or "Generated Feature"
    ref = next((s.feature_reference for s in scenarios if s.feature_reference), None)
    if ref and f"[{ref}]" not in feature:
        feature = f"{feature} [{ref}]"
    description = next((s.feature_description for s in scenarios if s.feature_description), None)
    if not description:
        description = build_feature_description(feature)

    feature_tags: list[str] = []
    if include_feature_tags:
        seen: set[str] = set()
        for sc in scenarios:
            for tag in sc.tags or []:
                if tag not in seen:
                    seen.add(tag)
                    feature_tags.append(tag)
        feature_tags = feature_tags[:6]

    lines: list[str] = []
    if feature_tags:
        lines.append(" ".join(feature_tags))
    lines.append(f"Feature: {feature}")
    if description:
        for raw_line in str(description).splitlines():
            text = raw_line.strip()
            if text:
                lines.append(f"  {text}")
    lines.append("")

    backgrounds = [tuple((s.keyword, s.text) for s in sc.background) for sc in scenarios]
    shared_bg = (
        backgrounds[0]
        if backgrounds and all(b == backgrounds[0] and b for b in backgrounds)
        else None
    )
    if shared_bg:
        shared_bg = shared_bg[: max(0, max_background_steps)]
        lines.append("  Background:")
        for keyword, text in shared_bg:
            lines.append(f"    {keyword} {text}")
        lines.append("")

    by_section: dict[str, list[BDDScenario]] = {}
    for sc in scenarios:
        section = (sc.section or sc.rule or "").strip().upper()
        if not section and sc.classification is not None:
            section = section_for_classification(sc.classification)
        if not section:
            section = scenario_section(sc.test_type)
        by_section.setdefault(section, []).append(sc)

    section_order = [s for s in SECTION_ORDER if s in by_section]
    section_order.extend(s for s in by_section if s not in section_order)

    for section_name in section_order:
        section_scenarios = by_section[section_name]
        if not section_scenarios:
            continue
        lines.append(f"  # {section_name}")
        lines.append("")
        for scenario in section_scenarios:
            if include_traceability_comments:
                for c in _traceability_comment_lines(scenario, indent="  "):
                    lines.append(c)
            keyword = (
                "Scenario Outline"
                if scenario.scenario_type == "scenario_outline"
                else "Scenario"
            )
            tags = scenario.tags or []
            if tags_before_scenario and tags:
                lines.append("  " + " ".join(tags))
            lines.append(f"  {keyword}: {scenario.scenario_name}")
            if not tags_before_scenario and tags:
                lines.append("    " + " ".join(tags))
            local_bg = [] if shared_bg else list(scenario.background)
            for step in local_bg:
                lines.append(f"    {step.keyword} {step.text}")
            for step in scenario.steps:
                lines.append(f"    {step.keyword} {step.text}")
            if scenario.scenario_type == "scenario_outline" and scenario.examples:
                lines.append("    Examples:")
                headers = list(scenario.examples[0].keys())
                lines.append(
                    "      | " + " | ".join(escape_table_cell(h) for h in headers) + " |"
                )
                for row in scenario.examples:
                    lines.append(
                        "      | "
                        + " | ".join(escape_table_cell(str(row.get(h, ""))) for h in headers)
                        + " |"
                    )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def validate_bdd_scenario(
    scenario: BDDScenario,
    *,
    valid_node_names: set[str] | None = None,
    evidence_ids: set[str] | None = None,
    seen_names: set[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    if not (scenario.feature or "").strip():
        issues.append("missing_feature_name")
    if not (scenario.scenario_name or "").strip():
        issues.append("missing_scenario_name")
    elif seen_names is not None:
        key = normalize_text(scenario.scenario_name)
        if key in seen_names:
            issues.append("duplicate_scenario_name")
        seen_names.add(key)

    if not scenario.steps:
        issues.append("missing_steps")
    keywords = [s.keyword for s in scenario.steps]
    if any(k not in _VALID_KEYWORDS for k in keywords):
        issues.append("invalid_step_keyword")
    if any(not (s.text or "").strip() for s in scenario.steps):
        issues.append("empty_step_text")
    if not any(k == "When" for k in keywords):
        issues.append("missing_when")
    if not any(k == "Then" for k in keywords):
        issues.append("missing_then")

    placeholders = set()
    for step in scenario.steps:
        placeholders.update(_PLACEHOLDER.findall(step.text or ""))
    if scenario.scenario_type == "scenario_outline":
        if not scenario.examples:
            issues.append("outline_missing_examples")
        else:
            headers = set(scenario.examples[0].keys())
            for row in scenario.examples:
                if set(row.keys()) != headers:
                    issues.append("inconsistent_example_headers")
                    break
            missing = placeholders - headers
            unused = headers - placeholders
            if missing:
                issues.append(f"example_headers_missing_placeholders:{','.join(sorted(missing))}")
            if unused and not placeholders:
                issues.append("examples_without_placeholders")
    elif scenario.examples and not placeholders:
        issues.append("unnecessary_examples")

    if valid_node_names and scenario.graph_path:
        unknown = [
            n
            for n in scenario.graph_path
            if normalize_text(n) and normalize_text(n) not in valid_node_names
        ]
        if unknown:
            issues.append(f"invalid_graph_path_refs:{','.join(unknown[:3])}")

    if evidence_ids is not None:
        for ev in scenario.evidence_references or []:
            sid = (ev.source_id or "").strip()
            if sid and sid not in evidence_ids:
                issues.append(f"unsupported_evidence_id:{sid}")

    # Lightweight parseability check: Feature/Scenario + indented steps
    gherkin = scenario.gherkin_text or render_gherkin(scenario)
    if "Feature:" not in gherkin or ("Scenario:" not in gherkin and "Scenario Outline:" not in gherkin):
        issues.append("unparseable_gherkin_structure")
    return issues


def _split_expected(expected: str) -> list[str]:
    parts = re.split(r"\s+(?:and|,)\s+", expected.strip(), flags=re.I)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def convert_test_to_bdd(
    tc: TestCase,
    *,
    feature_name: str | None = None,
    feature_description: str | None = None,
) -> tuple[BDDScenario | None, str, list[str]]:
    """Conservative standard→BDD conversion. Returns (scenario|None, status, notes)."""
    notes: list[str] = []
    title = (tc.title or "").strip()
    steps = [str(s).strip() for s in (tc.steps or []) if str(s).strip()]
    expected = (tc.expected_result or "").strip()
    feature = feature_name or (tc.graph_path[0] if tc.graph_path else "Generated Feature")

    if not title:
        return None, "needs_revision", ["missing_title"]
    if not steps:
        return None, "needs_revision", ["missing_steps"]
    if not expected or _VAGUE_EXPECTED.match(expected) or len(expected) < 8:
        return None, "needs_revision", ["vague_or_missing_expected_result"]

    action_idxs = [i for i, s in enumerate(steps) if _ACTIONISH.search(s)]
    if not action_idxs:
        # Fall back to last step as primary action
        action_idxs = [len(steps) - 1]
        notes.append("inferred_primary_action_as_last_step")

    primary_idx = action_idxs[0]
    given_texts = list(tc.preconditions or []) + steps[:primary_idx]
    when_texts = [steps[primary_idx]]
    and_after_when = steps[primary_idx + 1 :]
    then_texts = _split_expected(expected)

    bdd_steps: list[BDDStep] = []
    if given_texts:
        bdd_steps.append(BDDStep(keyword="Given", text=_as_state_clause(given_texts[0])))
        for text in given_texts[1:]:
            bdd_steps.append(BDDStep(keyword="And", text=_as_state_clause(text)))
    bdd_steps.append(BDDStep(keyword="When", text=_as_action_clause(when_texts[0])))
    for text in and_after_when:
        bdd_steps.append(BDDStep(keyword="And", text=_as_action_clause(text)))
    bdd_steps.append(BDDStep(keyword="Then", text=_as_outcome_clause(then_texts[0])))
    for text in then_texts[1:]:
        bdd_steps.append(BDDStep(keyword="And", text=_as_outcome_clause(text)))

    scenario = BDDScenario(
        id=new_id("BDD"),
        feature=feature,
        feature_description=feature_description or build_feature_description(feature),
        feature_reference=None,
        rule=None,
        section=None,
        scenario_name=title,
        scenario_type="scenario",
        tags=[],
        steps=bdd_steps,
        priority=str(tc.priority.value if hasattr(tc.priority, "value") else tc.priority),
        test_type=tc.category or "functional",
        classification=None,
        graph_path=list(tc.graph_path or []),
        requirement_references=[
            ev.source_id or ev.source_title or ""
            for ev in (tc.evidence or [])
            if (ev.source_type or "").lower() in {"requirement", "document"}
        ],
        bug_references=[
            ev.source_id or ev.source_title or ""
            for ev in (tc.evidence or [])
            if "bug" in (ev.source_type or "").lower()
        ],
        evidence_references=list(tc.evidence or []),
        assumptions=list(tc.assumptions or []),
        generation_method=tc.generation_method or "deterministic_conversion",
        source_test_id=tc.test_case_id,
        conversion_status="ok",
        conversion_notes=notes,
    )
    from app.agents.taxonomy import (
        ensure_test_classified,
        parse_feature_reference,
        section_for_classification,
    )

    classified = ensure_test_classified(tc)
    cls = classified.classification
    assert cls is not None
    fname, fref = parse_feature_reference(feature)
    scenario.feature = fname
    scenario.feature_reference = fref
    scenario.classification = cls
    scenario.section = section_for_classification(cls)
    scenario.rule = scenario.section  # keep rule for older consumers
    scenario.tags = build_tags(classified)
    scenario.test_type = classified.category or scenario.test_type
    scenario.gherkin_text = render_gherkin(scenario, tags_before_scenario=True)
    issues = validate_bdd_scenario(scenario)
    if issues:
        scenario.conversion_status = "needs_revision"
        scenario.conversion_notes = notes + issues
        return scenario, "needs_revision", scenario.conversion_notes
    return scenario, "ok", notes


def _as_state_clause(text: str) -> str:
    cleaned = text.strip().rstrip(".")
    if re.match(r"^(the\s+user|a\s+|an\s+|there\s+is|user\s+is)\b", cleaned, re.I):
        return cleaned
    return cleaned[0].lower() + cleaned[1:] if cleaned else cleaned


def _as_action_clause(text: str) -> str:
    cleaned = text.strip().rstrip(".")
    cleaned = re.sub(r"^(navigate to entry point:\s*)", "the user navigates to ", cleaned, flags=re.I)
    cleaned = re.sub(r"^(traverse\s*/\s*exercise:\s*)", "the user exercises ", cleaned, flags=re.I)
    if re.match(r"^(the\s+user|user)\b", cleaned, re.I):
        return cleaned
    if _ACTIONISH.match(cleaned):
        return f"the user {cleaned[0].lower() + cleaned[1:]}"
    return cleaned


def _as_outcome_clause(text: str) -> str:
    cleaned = text.strip().rstrip(".")
    if re.match(r"^(the\s+|a\s+|an\s+|exactly\s+|no\s+|user\s+)", cleaned, re.I):
        return cleaned
    return cleaned[0].lower() + cleaned[1:] if cleaned else cleaned


def build_generated_artifacts(
    test_cases: list[TestCase],
    *,
    output_format: TestOutputFormat | str,
    feature_name: str | None = None,
    valid_node_names: set[str] | None = None,
    evidence_ids: set[str] | None = None,
) -> tuple[list[GeneratedTestArtifact], list[BDDScenario], dict[str, Any]]:
    from app.agents.taxonomy import ensure_test_classified

    fmt = (
        output_format
        if isinstance(output_format, TestOutputFormat)
        else TestOutputFormat(str(output_format or "standard").lower())
    )
    artifacts: list[GeneratedTestArtifact] = []
    scenarios: list[BDDScenario] = []
    validation_errors: list[str] = []
    converted = 0
    needs_revision = 0
    seen_names: set[str] = set()
    classified_cases = [ensure_test_classified(tc) for tc in test_cases]

    for tc in classified_cases:
        logical_id = tc.test_case_id
        standard = tc
        bdd: BDDScenario | None = None
        if fmt in {TestOutputFormat.BDD, TestOutputFormat.BOTH}:
            bdd, status, notes = convert_test_to_bdd(tc, feature_name=feature_name)
            if bdd is None:
                needs_revision += 1
                validation_errors.append(f"{tc.test_case_id}:conversion_failed:{','.join(notes)}")
            else:
                issues = validate_bdd_scenario(
                    bdd,
                    valid_node_names=valid_node_names,
                    evidence_ids=evidence_ids,
                    seen_names=seen_names,
                )
                if issues:
                    bdd.conversion_status = "needs_revision"
                    bdd.conversion_notes = list(dict.fromkeys((bdd.conversion_notes or []) + issues))
                    needs_revision += 1
                    validation_errors.append(f"{tc.test_case_id}:{','.join(issues[:4])}")
                else:
                    converted += 1
                scenarios.append(bdd)

        if fmt == TestOutputFormat.BOTH:
            artifact_format = "both"
        elif fmt == TestOutputFormat.BDD:
            artifact_format = "bdd"
        else:
            artifact_format = "standard"

        artifacts.append(
            GeneratedTestArtifact(
                id=new_id("ART"),
                format=artifact_format,
                logical_test_id=logical_id,
                standard_test_case=standard,
                bdd_scenario=bdd,
                source_test_id=tc.test_case_id,
                graph_path=list(tc.graph_path or []),
                evidence=list(tc.evidence or []),
                priority=str(tc.priority.value if hasattr(tc.priority, "value") else tc.priority),
                generation_method=tc.generation_method,
            )
        )

    meta = {
        "requested_format": fmt.value,
        "logical_test_count": len(classified_cases),
        "standard_count": len(classified_cases) if fmt != TestOutputFormat.BDD else 0,
        "bdd_count": len(scenarios),
        "converted_ok": converted,
        "needs_revision": needs_revision,
        "validation_errors": validation_errors[:40],
        "classified_test_cases": classified_cases,
    }
    if fmt == TestOutputFormat.STANDARD:
        meta["bdd_count"] = 0
    elif fmt == TestOutputFormat.BDD:
        meta["standard_count"] = 0
    return artifacts, scenarios, meta


def safe_feature_filename(feature_name: str, project_name: str | None = None) -> str:
    base = slug_tag(feature_name) or "generated-feature"
    prefix = slug_tag(project_name or "")
    name = f"{prefix}-{base}" if prefix else base
    return f"{name}.feature"
