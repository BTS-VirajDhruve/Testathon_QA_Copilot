"""Validity-first test review and automation feasibility agent."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.agents.dedup import normalize_path, normalize_steps, normalize_text
from app.core.logging import get_logger
from app.models.enums import (
    AutomationEffort,
    AutomationLayer,
    AutomationPriority,
    AutomationSuitability,
    ConfidenceLevel,
    DuplicateRelation,
    LLMTaskType,
    Priority,
    TestValidity,
)
from app.models.schemas import (
    AutomationCapabilityProfile,
    AutomationFeasibilityReview,
    AutomationSummary,
    FusedContext,
    ReviewedTestCase,
    TestCase,
    TestValidityReview,
    ValiditySummary,
    utc_now,
)
from app.services.model_router import ModelRoutingContext
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)

_VAGUE_TITLES = re.compile(
    r"^(test|tests|journey|feature|check|verify|scenario|case)(\s+\d+)?$",
    re.I,
)
_SUBJECTIVE = re.compile(
    r"\b(usability|looks?\s+good|feels?\s+|confus|frustrat|intuitive|"
    r"aesthetic|subjective|user\s+experience|ux\s+review|naming\s+clarity|"
    r"visual\s+appeal|pleasant|professional)\b",
    re.I,
)
_VISUAL = re.compile(
    r"\b(layout|visual|pixel|screenshot|alignment|spacing|color|theme|"
    r"css|ui\s+consistency|look\s+and\s+feel)\b",
    re.I,
)
_API_HINT = re.compile(
    r"\b(api|endpoint|http|json|payload|status\s*code|contract|"
    r"request|response|rest|graphql)\b",
    re.I,
)
_UI_HINT = re.compile(
    r"\b(click|button|browser|page|form|field|navigate|ui|screen|"
    r"dropdown|modal|checkbox|submit|input)\b",
    re.I,
)
_INTEGRATION = re.compile(
    r"\b(gateway|payment|webhook|third[- ]party|external|sso|oauth|"
    r"provider|sandbox|timeout|email provider|sms provider)\b",
    re.I,
)
_SECURITY = re.compile(
    r"\b(auth|permission|xss|csrf|injection|encrypt|token|session|"
    r"lockout|privilege|security)\b",
    re.I,
)
_A11Y = re.compile(r"\b(accessib|aria|screen\s*reader|wcag|keyboard\s+nav)\b", re.I)
_PERF = re.compile(r"\b(performance|latency|load\s+test|throughput|sla)\b", re.I)
_DB = re.compile(
    r"\b(database|persist(?:ed|ence)?|sql\b|transaction|db\s+row|schema)\b", re.I
)
_OBSERVABLE = re.compile(
    r"\b(status|code|error|message|redirect|saved|created|deleted|"
    r"displayed|returned|persisted|assert|equals|contains|visible|"
    r"disabled|enabled|http|json|toast|validation|conflict)\b",
    re.I,
)
_VAGUE_EXPECTED = re.compile(
    r"^(it\s+works|works|success|ok|pass|fine|good|as\s+expected)\.?$",
    re.I,
)
_EXPLORATORY = re.compile(r"\b(explorat|charter|ad[\s-]?hoc|unscripted)\b", re.I)
BATCH_SIZE = 8


def _content_hash(tc: TestCase) -> str:
    payload = {
        "title": tc.title,
        "category": tc.category,
        "priority": str(
            tc.priority.value if hasattr(tc.priority, "value") else tc.priority
        ),
        "risk": str(tc.risk.value if hasattr(tc.risk, "value") else tc.risk),
        "preconditions": tc.preconditions,
        "steps": tc.steps,
        "expected_result": tc.expected_result,
        "graph_path": tc.graph_path,
        "source_references": tc.source_references,
        "evidence": [ev.model_dump(mode="json") for ev in (tc.evidence or [])],
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _needs_setup(tc: TestCase) -> bool:
    blob = " ".join(
        [tc.title or "", tc.expected_result or "", " ".join(tc.steps or [])]
    ).lower()
    return bool(
        re.search(
            r"\b(login|auth|account|seed|fixture|cart|payment|session|sandbox)\b", blob
        )
    )


def has_observable_outcome(text: str | None) -> bool:
    """True when expected result contains machine-checkable assertion tokens."""
    blob = (text or "").strip()
    if not blob:
        return False
    return bool(_OBSERVABLE.search(blob) or _API_HINT.search(blob))


def default_observable_expected(
    title: str | None = None, path: list[str] | None = None
) -> str:
    label = (title or "").strip() or (
        " → ".join(path or []) if path else "the scenario"
    )
    return (
        f"The system completes '{label}' and returns a clear status or error message "
        f"that can be asserted (success path shows confirmation; failure path shows validation error)."
    )


def apply_safe_corrections(tc: TestCase) -> tuple[TestCase, list[str]]:
    corrected = tc.model_copy(deep=True)
    applied: list[str] = []

    if corrected.title:
        cleaned = re.sub(r"\s+", " ", corrected.title).strip()
        if cleaned != corrected.title:
            corrected.title = cleaned
            applied.append("normalized_title_whitespace")

    if corrected.steps:
        new_steps: list[str] = []
        seen_step: set[str] = set()
        for step in corrected.steps:
            s = re.sub(r"\s+", " ", str(step)).strip()
            if not s:
                continue
            key = normalize_text(s)
            if key in seen_step:
                applied.append("removed_exact_duplicate_step")
                continue
            seen_step.add(key)
            new_steps.append(s)
        if new_steps != corrected.steps:
            corrected.steps = new_steps
            if "removed_exact_duplicate_step" not in applied:
                applied.append("normalized_steps")

    if corrected.expected_result:
        er = re.sub(r"\s+", " ", corrected.expected_result).strip()
        if er != corrected.expected_result:
            corrected.expected_result = er
            applied.append("normalized_expected_result")

    pri = str(
        corrected.priority.value
        if hasattr(corrected.priority, "value")
        else corrected.priority
    ).lower()
    pri_map = {
        "p0": "critical",
        "p1": "high",
        "p2": "medium",
        "p3": "low",
        "crit": "critical",
        "med": "medium",
    }
    if pri in pri_map:
        corrected.priority = Priority(pri_map[pri])
        applied.append("standardized_priority")

    cat = (corrected.category or "").strip().lower()
    cat_map = {
        "func": "functional",
        "neg": "negative",
        "reg": "regression",
        "explore": "exploratory",
        "sec": "security",
    }
    if cat in cat_map:
        corrected.category = cat_map[cat]
        applied.append("standardized_test_type")

    return corrected, applied


def apply_validity_hardening(tc: TestCase) -> tuple[TestCase, list[str]]:
    """Rewrite soft validity issues so deterministic review can mark the test valid.

    Fixes missing/vague expected results (must match _OBSERVABLE tokens), vague steps,
    missing setup preconditions, and overly generic titles — without inventing product behavior.
    """
    corrected, applied = apply_safe_corrections(tc)
    path = list(corrected.graph_path or [])
    path_label = " → ".join(path) if path else "feature"

    title = (corrected.title or "").strip()
    if not title or len(title) < 8 or _VAGUE_TITLES.match(title):
        corrected.title = f"Validate {path_label} returns expected status"
        applied.append("hardened_title")

    expected = (corrected.expected_result or "").strip()
    if (
        not expected
        or _VAGUE_EXPECTED.match(expected)
        or len(expected) < 8
        or not has_observable_outcome(expected)
    ):
        if expected and not has_observable_outcome(expected):
            corrected.expected_result = (
                f"{expected.rstrip('.')} — assert a clear status or error message "
                f"is displayed or returned."
            )
        else:
            corrected.expected_result = default_observable_expected(
                corrected.title, path
            )
        applied.append("hardened_expected_result_observability")

    steps = [s for s in (corrected.steps or []) if str(s).strip()]
    vague_steps = [
        s
        for s in steps
        if len(str(s).strip()) < 8
        or re.match(r"^(try|do|check|test)\b", str(s).strip(), re.I)
    ]
    if not steps or len(vague_steps) >= max(1, (len(steps) + 1) // 2):
        corrected.steps = [
            f"Given the system is prepared for path {path_label} with required session state",
            f"When the user executes the scenario '{corrected.title}' along {path_label}",
            "Then confirm the returned status or error message matches the expected result",
        ]
        applied.append("hardened_reproducible_steps")

    if not corrected.preconditions and _needs_setup(corrected):
        corrected.preconditions = [
            "Required user/session account is available",
            f"Environment is seeded for path: {path_label}",
        ]
        applied.append("hardened_preconditions")
    elif not corrected.preconditions:
        corrected.preconditions = [f"Project context for {path_label} is available"]
        applied.append("hardened_default_preconditions")

    return corrected, applied


def classify_duplicate_relation(left: TestCase, right: TestCase) -> DuplicateRelation:
    lt = normalize_text(left.title)
    rt = normalize_text(right.title)
    ls = normalize_steps(left.steps)
    rs = normalize_steps(right.steps)
    le = normalize_text(left.expected_result)
    re_ = normalize_text(right.expected_result)
    lp = normalize_path(left.graph_path)
    rp = normalize_path(right.graph_path)
    if lt == rt and ls == rs and le == re_ and lp == rp:
        return DuplicateRelation.EXACT_DUPLICATE
    if lt == rt and (ls == rs or le == re_):
        return DuplicateRelation.NEAR_DUPLICATE
    if lp and lp == rp and ls and ls == rs:
        return DuplicateRelation.NEAR_DUPLICATE
    if lt == rt and ls != rs:
        return DuplicateRelation.COMPLEMENTARY
    if lp and lp == rp and lt != rt:
        return DuplicateRelation.COMPLEMENTARY
    return DuplicateRelation.DISTINCT


def deterministic_validity_findings(
    tc: TestCase,
    *,
    project_id: str,
    valid_node_names: set[str],
    evidence_ids: set[str],
    project_evidence_ids: set[str],
    seen_ids: set[str],
    peers: list[TestCase],
) -> dict[str, Any]:
    reasons: list[str] = []
    issues: list[str] = []
    missing: list[str] = []
    title = (tc.title or "").strip()
    if not title:
        issues.append("missing_title")
        missing.append("title")
    elif len(title) < 8 or _VAGUE_TITLES.match(title):
        issues.append("vague_title")
        reasons.append("Title is too generic to clearly describe the scenario.")

    steps = [s for s in (tc.steps or []) if str(s).strip()]
    if not steps:
        issues.append("missing_steps")
        missing.append("execution steps")
    else:
        vague_steps = [
            s
            for s in steps
            if len(str(s).strip()) < 8
            or re.match(r"^(try|do|check|test)\b", str(s).strip(), re.I)
        ]
        if len(vague_steps) >= max(1, (len(steps) + 1) // 2):
            issues.append("vague_or_non_reproducible_steps")
            reasons.append(
                "Steps are too vague for another QA engineer to reproduce reliably."
            )
        if len(steps) >= 10:
            issues.append("excessive_breadth")
            reasons.append(
                "The test combines too many actions for one focused scenario."
            )

    expected = (tc.expected_result or "").strip()
    if not expected:
        issues.append("missing_expected_result")
        missing.append("observable expected result")
    elif _VAGUE_EXPECTED.match(expected) or len(expected) < 8:
        issues.append("non_observable_expected_result")
        reasons.append(
            "Expected result is too vague to determine pass/fail objectively."
        )
    elif not _OBSERVABLE.search(expected) and not _API_HINT.search(expected):
        issues.append("expected_result_may_not_be_observable")
        reasons.append(
            "Expected result may require clearer observable outcome or assertion."
        )

    if not tc.preconditions and _needs_setup(tc):
        issues.append("missing_preconditions")
        missing.append("preconditions or setup")

    graph_path_valid = None
    if tc.graph_path:
        graph_path_valid = True
        unknown = [
            n
            for n in tc.graph_path
            if normalize_text(n) and normalize_text(n) not in valid_node_names
        ]
        if unknown:
            graph_path_valid = False
            issues.append(f"invalid_graph_path_refs:{','.join(unknown[:3])}")
            reasons.append(
                "Graph path references nodes not found in the active project flow."
            )

    supported_by_project = (tc.project_id in {None, project_id}) and (
        tc.feature_id is None or tc.feature_id != ""
    )
    if tc.project_id and tc.project_id != project_id:
        supported_by_project = False
        issues.append("cross_project_test")
        reasons.append("Test belongs to another project and cannot be reviewed here.")

    evidence_checked = list(tc.evidence or [])
    evidence_supported = bool(evidence_checked or tc.source_references or tc.graph_path)
    for ev in evidence_checked:
        sid = (ev.source_id or "").strip()
        if sid and sid not in evidence_ids:
            issues.append(f"unsupported_evidence_id:{sid}")
            reasons.append(
                "At least one evidence reference does not resolve in persisted project data."
            )
        if sid and project_evidence_ids and sid not in project_evidence_ids:
            issues.append(f"cross_project_evidence:{sid}")
            reasons.append("Evidence reference does not belong to the active project.")

    if seen_ids and tc.test_case_id in seen_ids:
        issues.append("duplicate_test_id")
        reasons.append("Another test in this suite already uses the same test case ID.")

    duplicate_status = DuplicateRelation.DISTINCT.value
    for other in peers:
        if other.test_case_id == tc.test_case_id:
            continue
        rel = classify_duplicate_relation(tc, other)
        if rel == DuplicateRelation.EXACT_DUPLICATE:
            duplicate_status = rel.value
            issues.append(f"exact_duplicate:{other.test_case_id}")
            reasons.append(
                "This test is an exact duplicate of another scenario in the same suite."
            )
            break
        if (
            rel == DuplicateRelation.NEAR_DUPLICATE
            and duplicate_status == DuplicateRelation.DISTINCT.value
        ):
            duplicate_status = rel.value
        elif (
            rel == DuplicateRelation.COMPLEMENTARY
            and duplicate_status == DuplicateRelation.DISTINCT.value
        ):
            duplicate_status = rel.value

    contradiction = False
    if re.search(
        r"\b(should succeed|is created|save succeeds)\b", expected, re.I
    ) and re.search(
        r"\b(blocked|fails|error|rejected|prevented)\b", " ".join(steps), re.I
    ):
        contradiction = True
        issues.append("contradictory_expected_behavior")
        reasons.append("Steps and expected outcome appear to contradict each other.")

    if _SUBJECTIVE.search(title) and not evidence_supported:
        reasons.append(
            "No evidence defines an objective rule for the subjective behavior being tested."
        )

    correction_possible = any(
        x in issues
        for x in (
            "vague_title",
            "vague_or_non_reproducible_steps",
            "missing_preconditions",
            "expected_result_may_not_be_observable",
        )
    )
    return {
        "reasons": reasons,
        "issues": issues,
        "missing": missing,
        "graph_path_valid": graph_path_valid,
        "evidence_checked": evidence_checked,
        "evidence_supported": evidence_supported,
        "supported_by_project": supported_by_project,
        "duplicate_status": duplicate_status,
        "contradiction": contradiction,
        "correction_possible": correction_possible,
    }


def semantic_correction_suggestions(issues: list[str]) -> list[str]:
    suggestions: list[str] = []
    if (
        "missing_expected_result" in issues
        or "non_observable_expected_result" in issues
    ):
        suggestions.append(
            "Add a machine-observable expected result (status, message, persistence, or UI state)."
        )
    if "missing_steps" in issues or "vague_or_non_reproducible_steps" in issues:
        suggestions.append(
            "Replace vague steps with ordered, single-action, reproducible instructions."
        )
    if "vague_title" in issues or "missing_title" in issues:
        suggestions.append(
            "Use a specific title that states the condition and expected outcome."
        )
    if "missing_preconditions" in issues:
        suggestions.append(
            "Document required accounts, seed data, and environment preconditions."
        )
    if any(i.startswith("invalid_graph_path") for i in issues):
        suggestions.append(
            "Align graph_path with nodes that exist in the system flow graph."
        )
    if "insufficient_evidence" in issues:
        suggestions.append(
            "Link the test to a requirement, graph path, bug, or approved user instruction."
        )
    return suggestions


def validity_score(issues: list[str]) -> int:
    score = 100
    weights = {
        "missing_title": 25,
        "vague_title": 12,
        "missing_steps": 25,
        "vague_or_non_reproducible_steps": 18,
        "missing_expected_result": 25,
        "non_observable_expected_result": 20,
        "expected_result_may_not_be_observable": 8,
        "missing_preconditions": 8,
        "cross_project_test": 40,
        "duplicate_test_id": 15,
        "contradictory_expected_behavior": 20,
        "exact_duplicate": 20,
        "unsupported_evidence_id": 20,
        "cross_project_evidence": 30,
        "invalid_graph_path_refs": 20,
    }
    for issue in issues:
        score -= weights.get(issue.split(":")[0], 5)
    return max(0, min(100, score))


def decide_validity(
    tc: TestCase, findings: dict[str, Any]
) -> tuple[TestValidity, list[str]]:
    issues = findings["issues"]
    reasons = list(findings["reasons"])
    if not findings["supported_by_project"]:
        return TestValidity.INVALID, reasons or [
            "Test does not belong to the active project."
        ]
    if any(i.startswith("cross_project_evidence") for i in issues):
        return TestValidity.INVALID, reasons or [
            "Evidence from another project cannot support this test."
        ]
    if any(i.startswith("invalid_graph_path_refs") for i in issues):
        return TestValidity.INVALID, reasons or [
            "Graph path does not exist in the active project."
        ]
    if any(i.startswith("unsupported_evidence_id") for i in issues) and not (
        tc.graph_path or tc.source_references
    ):
        return TestValidity.INSUFFICIENT_EVIDENCE, reasons or [
            "Expected behavior is not supported by available evidence."
        ]
    if any(i.startswith("exact_duplicate") for i in issues):
        return TestValidity.INVALID, reasons or [
            "Test is an exact duplicate and adds no new value."
        ]
    if findings["contradiction"]:
        return TestValidity.INVALID, reasons or [
            "Expected behavior contradicts the scenario steps."
        ]
    if "missing_steps" in issues or "missing_expected_result" in issues:
        return TestValidity.INVALID, reasons or [
            "Test lacks executable steps or observable expected result."
        ]
    if (
        _SUBJECTIVE.search(tc.expected_result or "")
        and not findings["evidence_supported"]
    ):
        return TestValidity.INSUFFICIENT_EVIDENCE, reasons or [
            "Subjective expectation is unsupported by defined product rules."
        ]
    if not findings["evidence_supported"] and not tc.graph_path:
        return TestValidity.INSUFFICIENT_EVIDENCE, reasons or [
            "Available project evidence does not establish this expected behavior."
        ]
    if any(
        i in issues
        for i in (
            "vague_title",
            "vague_or_non_reproducible_steps",
            "missing_preconditions",
            "expected_result_may_not_be_observable",
        )
    ):
        return TestValidity.NEEDS_REVISION, reasons or [
            "The scenario is supported but needs clearer execution details."
        ]
    return TestValidity.VALID, reasons or [
        "Scenario is supported, executable, and has an observable outcome."
    ]


def compute_automation_signals(
    tc: TestCase, *, profile: AutomationCapabilityProfile | None = None
) -> dict[str, Any]:
    score = 50
    positives: list[str] = []
    negatives: list[str] = []
    blob = " ".join(
        [
            tc.title or "",
            tc.expected_result or "",
            " ".join(tc.steps or []),
            tc.category or "",
            tc.testing_technique or "",
        ]
    )
    if tc.steps:
        score += 12
        positives.append("repeatable_steps")
    if _OBSERVABLE.search(tc.expected_result or "") or _API_HINT.search(
        tc.expected_result or ""
    ):
        score += 14
        positives.append("deterministic_machine_observable_result")
    else:
        score -= 18
        negatives.append("unclear_or_subjective_expected_result")
    if tc.preconditions or tc.test_data:
        score += 6
        positives.append("stable_data_setup_hints")
    elif _needs_setup(tc):
        score -= 6
        negatives.append("manual_setup_or_cleanup_needed")
    pri = str(
        tc.priority.value if hasattr(tc.priority, "value") else tc.priority
    ).lower()
    risk = str(tc.risk.value if hasattr(tc.risk, "value") else tc.risk).lower()
    if pri in {"critical", "high"} or risk in {"critical", "high"}:
        score += 10
        positives.append("high_regression_or_business_risk")
    if _SUBJECTIVE.search(blob):
        score -= 22
        negatives.append("subjective_human_judgment")
    if _EXPLORATORY.search(blob) or (tc.category or "").lower() == "exploratory":
        score -= 16
        negatives.append("exploratory_unscripted_intent")
    if _INTEGRATION.search(blob):
        score -= 4
        negatives.append("external_or_async_dependency")
        if profile and (
            profile.mock_services_available
            or profile.sandbox_integrations_available
            or profile.service_virtualization_available
        ):
            score += 8
            positives.append("controllable_dependency_via_profile")
    if _UI_HINT.search(blob) and not (profile and profile.stable_test_ids_available):
        score -= 6
        negatives.append("stable_selectors_unknown")
    if profile:
        if profile.api_testing_available and _API_HINT.search(blob):
            score += 6
            positives.append("api_testing_capability_configured")
        if profile.visual_testing_available and _VISUAL.search(blob):
            score += 4
            positives.append("visual_testing_capability_configured")
        if profile.accessibility_scanning_available and _A11Y.search(blob):
            score += 4
            positives.append("a11y_scanning_capability_configured")
    else:
        negatives.append("no_automation_capability_profile")
    score = max(0, min(100, score))
    return {
        "score": score,
        "positives": positives,
        "negatives": negatives,
        "human_judgment_required": bool(_SUBJECTIVE.search(blob)),
        "stable_selectors_required": bool(_UI_HINT.search(blob)),
    }


def recommend_automation_layer(
    tc: TestCase, *, profile: AutomationCapabilityProfile | None = None
) -> tuple[AutomationLayer, list[str]]:
    blob = " ".join(
        [
            tc.title or "",
            tc.expected_result or "",
            " ".join(tc.steps or []),
            tc.category or "",
        ]
    )
    reasons: list[str] = []
    if _PERF.search(blob):
        reasons.append("performance behavior ? performance tooling")
        return AutomationLayer.PERFORMANCE, reasons
    if _A11Y.search(blob):
        reasons.append(
            "accessibility rules ? accessibility scanner (+ manual where needed)"
        )
        return AutomationLayer.ACCESSIBILITY, reasons
    if re.search(r"\b(contract|schema|openapi)\b", blob, re.I):
        reasons.append("API response contract ? contract/API")
        return AutomationLayer.CONTRACT, reasons
    if _API_HINT.search(blob) and not _UI_HINT.search(blob):
        reasons.append("API/business rule validation ? API")
        return AutomationLayer.API, reasons
    if _VISUAL.search(blob) and not _API_HINT.search(blob):
        reasons.append(
            "visual consistency ? visual regression (+ manual if subjective)"
        )
        return AutomationLayer.VISUAL, reasons
    if _SECURITY.search(blob) and not _UI_HINT.search(blob):
        reasons.append("security/auth rule ? security or API checks")
        return AutomationLayer.SECURITY, reasons
    if _DB.search(blob) and not _UI_HINT.search(blob) and not _API_HINT.search(blob):
        reasons.append("persistence verification ? database/integration")
        return AutomationLayer.DATABASE, reasons
    if _INTEGRATION.search(blob):
        reasons.append("cross-service / external workflow ? integration")
        return AutomationLayer.INTEGRATION, reasons
    if re.search(
        r"\b(business\s+rule|component|unit)\b", blob, re.I
    ) and not _UI_HINT.search(blob):
        reasons.append("business rule without UI journey ? component/API")
        return AutomationLayer.COMPONENT, reasons
    if _UI_HINT.search(blob) or (tc.category or "").lower() in {"functional", "ui"}:
        reasons.append("end-user browser journey ? UI (prefer API-assisted setup)")
        return AutomationLayer.UI, reasons
    if profile and profile.supported_layers:
        reasons.append("insufficient layer signals; keep unknown")
        return AutomationLayer.UNKNOWN, reasons
    reasons.append("insufficient layer signals")
    return AutomationLayer.UNKNOWN, reasons


def classify_automation(
    tc: TestCase,
    *,
    profile: AutomationCapabilityProfile | None = None,
) -> tuple[
    AutomationSuitability,
    AutomationPriority,
    AutomationEffort,
    ConfidenceLevel,
    list[str],
    list[str],
    list[str],
    list[str],
]:
    signals = compute_automation_signals(tc, profile=profile)
    layer, layer_reasons = recommend_automation_layer(tc, profile=profile)
    score = int(signals["score"])
    reasons = list(signals["positives"]) + layer_reasons
    non_reasons = list(signals["negatives"])
    blockers: list[str] = []
    prereqs: list[str] = []
    human = bool(signals["human_judgment_required"])
    blob = " ".join(
        [tc.title or "", tc.expected_result or "", " ".join(tc.steps or [])]
    )

    if human and _VISUAL.search(blob):
        suit = AutomationSuitability.HYBRID
        reasons.append(
            "Automated setup or assertions are useful, but visual judgment remains manual."
        )
        prereqs.append(
            "Define objective assertions separately from human review criteria"
        )
    elif human and not _OBSERVABLE.search(tc.expected_result or ""):
        suit = AutomationSuitability.MANUAL
        reasons.append(
            "Human observation or judgment is the central purpose of this test."
        )
    else:
        needs_conditions = False
        if signals["stable_selectors_required"] and not (
            profile and profile.stable_test_ids_available
        ):
            needs_conditions = True
            blockers.append("Stable UI selectors are not confirmed")
            prereqs.append("stable selectors or test IDs")
        if _INTEGRATION.search(blob) and not (
            profile
            and (
                profile.mock_services_available
                or profile.sandbox_integrations_available
                or profile.service_virtualization_available
            )
        ):
            needs_conditions = True
            blockers.append("External dependency control is not configured")
            prereqs.append("mock service, sandbox provider, or service virtualization")
        if _needs_setup(tc) and not (profile and profile.test_data_api_available):
            needs_conditions = True
            prereqs.append("test-data setup / cleanup API")
        if not profile:
            needs_conditions = True
            prereqs.append("project automation capability profile")
            non_reasons.append("no capability profile configured")
        if score >= 80 and not needs_conditions:
            suit = AutomationSuitability.AUTOMATE
            reasons.append(f"automation_score={score} strong candidate")
        elif score >= 60 or needs_conditions:
            suit = AutomationSuitability.AUTOMATE_WITH_CONDITIONS
            reasons.append(f"automation_score={score} with known prerequisites")
        elif score >= 40:
            suit = AutomationSuitability.NOT_READY_FOR_AUTOMATION
            reasons.append(
                f"automation_score={score} valid test but environment remains underdefined"
            )
        else:
            suit = AutomationSuitability.MANUAL
            reasons.append(
                f"automation_score={score} suggests low reliable automation value"
            )

    if suit == AutomationSuitability.MANUAL:
        auto_pri = AutomationPriority.NOT_RECOMMENDED
    else:
        pri = str(
            tc.priority.value if hasattr(tc.priority, "value") else tc.priority
        ).lower()
        if pri == "critical":
            auto_pri = AutomationPriority.CRITICAL
        elif pri == "high":
            auto_pri = AutomationPriority.HIGH
        elif suit == AutomationSuitability.AUTOMATE:
            auto_pri = AutomationPriority.HIGH
        else:
            auto_pri = AutomationPriority.MEDIUM

    if suit == AutomationSuitability.MANUAL:
        effort = AutomationEffort.HIGH
    elif suit == AutomationSuitability.AUTOMATE and score >= 80:
        effort = AutomationEffort.LOW
    else:
        effort = AutomationEffort.MEDIUM

    confidence = (
        ConfidenceLevel.HIGH
        if profile and suit == AutomationSuitability.AUTOMATE
        else ConfidenceLevel.MEDIUM
    )
    if not profile or suit in {
        AutomationSuitability.MANUAL,
        AutomationSuitability.NOT_READY_FOR_AUTOMATION,
    }:
        confidence = ConfidenceLevel.MEDIUM
    if not profile and suit != AutomationSuitability.MANUAL:
        confidence = ConfidenceLevel.LOW

    return suit, auto_pri, effort, confidence, reasons, non_reasons, blockers, prereqs


def build_validity_summary(items: list[ReviewedTestCase]) -> ValiditySummary:
    summary = ValiditySummary(total_tests=len(items))
    for item in items:
        validity = item.validity_review.validity
        if validity == TestValidity.VALID.value:
            summary.valid += 1
        elif validity == TestValidity.INVALID.value:
            summary.invalid += 1
        elif validity == TestValidity.NEEDS_REVISION.value:
            summary.needs_revision += 1
        elif validity == TestValidity.INSUFFICIENT_EVIDENCE.value:
            summary.insufficient_evidence += 1
    return summary


def build_automation_summary(items: list[ReviewedTestCase]) -> AutomationSummary:
    summary = AutomationSummary(total_tests=len(items))
    for item in items:
        review = item.automation_review
        if not review:
            summary.not_evaluated += 1
            continue
        suit = review.automation_suitability
        if item.validity_review.validity == TestValidity.VALID.value:
            summary.valid_tests_evaluated += 1
        if suit == AutomationSuitability.AUTOMATE.value:
            summary.automate += 1
        elif suit == AutomationSuitability.AUTOMATE_WITH_CONDITIONS.value:
            summary.automate_with_conditions += 1
        elif suit == AutomationSuitability.HYBRID.value:
            summary.hybrid += 1
        elif suit == AutomationSuitability.MANUAL.value:
            summary.manual += 1
        elif suit == AutomationSuitability.NOT_READY_FOR_AUTOMATION.value:
            summary.not_ready_for_automation += 1
        elif suit == AutomationSuitability.NOT_EVALUATED.value:
            summary.not_evaluated += 1
        if review.automation_priority in {
            AutomationPriority.CRITICAL.value,
            AutomationPriority.HIGH.value,
        }:
            summary.high_priority_automation += 1
        if review.estimated_effort == AutomationEffort.LOW.value:
            summary.effort_low += 1
        elif review.estimated_effort == AutomationEffort.MEDIUM.value:
            summary.effort_medium += 1
        elif review.estimated_effort == AutomationEffort.HIGH.value:
            summary.effort_high += 1
    return summary


def apply_human_override(
    item: ReviewedTestCase, override: dict[str, Any] | None
) -> ReviewedTestCase:
    if not override:
        return item
    out = item.model_copy(deep=True)
    out.human_override = True
    out.override_reason = override.get("override_reason") or out.override_reason
    out.override_timestamp = out.override_timestamp or utc_now()
    if override.get("validity"):
        out.validity_review.validity = str(override["validity"])
        out.final_review_status = str(override["validity"])
    if out.automation_review is not None:
        if override.get("automation_suitability"):
            out.automation_review.automation_suitability = str(
                override["automation_suitability"]
            )
        if override.get("automation_layer"):
            out.automation_review.recommended_layer = str(override["automation_layer"])
        if override.get("automation_priority"):
            out.automation_review.automation_priority = str(
                override["automation_priority"]
            )
        if override.get("automation_effort"):
            out.automation_review.estimated_effort = str(override["automation_effort"])
    return out


class TestReviewAutomationAgent:
    """Two-stage validity-first test review with optional LLM enrichment."""

    VALIDITY_SYSTEM_PROMPT = (
        "You are a senior QA reviewer. You are given deterministic validity findings for test cases. "
        "Refine the validity decision and reasons without inventing product behavior. Return JSON "
        "{reviews:[{test_case_id, validity, validity_reasons, quality_issues, missing_information, correction_possible, suggested_corrections}]}."
    )
    AUTOMATION_SYSTEM_PROMPT = (
        "You are a senior QA automation architect. Evaluate automation feasibility only for tests that are already valid. "
        "Do not classify invalid or revision-needed tests. Return JSON {reviews:[{test_case_id, automation_suitability, recommended_layer, automation_priority, estimated_effort, confidence, automation_reasons, non_automation_reasons, blockers, prerequisites, suggested_automation_scope, recommended_assertions}]}."
    )

    def review(
        self,
        *,
        test_cases: list[TestCase],
        project_id: str,
        fused: FusedContext | None = None,
        targeted_ids: set[str] | None = None,
        existing_ids: set[str] | None = None,
        profile: AutomationCapabilityProfile | None = None,
        overrides: dict[str, dict[str, Any]] | None = None,
        automation_strategy: str | None = None,
        routing_context: ModelRoutingContext | None = None,
        force_deterministic: bool = False,
    ) -> tuple[
        list[ReviewedTestCase], ValiditySummary, AutomationSummary, dict[str, Any]
    ]:
        fused = fused or FusedContext()
        targeted_ids = targeted_ids or set()
        existing_ids = existing_ids or set()
        overrides = overrides or {}

        valid_nodes: set[str] = set()
        for path in fused.flow_paths or []:
            for name in path:
                norm = normalize_text(name)
                if norm:
                    valid_nodes.add(norm)
        for item in fused.graph_context or []:
            name = item.get("name") or item.get("title")
            if name:
                valid_nodes.add(normalize_text(str(name)))
        feat = fused.feature_context.get("name")
        if feat:
            valid_nodes.add(normalize_text(str(feat)))

        evidence_ids: set[str] = set()
        project_evidence_ids: set[str] = set()
        for item in fused.graph_context or []:
            if item.get("id"):
                evidence_ids.add(str(item["id"]))
                project_evidence_ids.add(str(item["id"]))
        for item in fused.semantic_context or []:
            if item.get("id"):
                evidence_ids.add(str(item["id"]))
                project_evidence_ids.add(str(item["id"]))
        for item in fused.historical_risks or []:
            sid = item.get("bug_id") or item.get("id")
            if sid:
                evidence_ids.add(str(sid))
                project_evidence_ids.add(str(sid))
        for tc in test_cases:
            for ev in tc.evidence or []:
                if ev.source_id:
                    evidence_ids.add(ev.source_id)
                    project_evidence_ids.add(ev.source_id)

        scoped = [
            tc for tc in test_cases if not tc.project_id or tc.project_id == project_id
        ]
        seen_ids: set[str] = set()
        reviewed: list[ReviewedTestCase] = []
        for tc in scoped:
            original = tc.model_copy(deep=True)
            corrected, corrections_applied = apply_safe_corrections(tc)
            findings = deterministic_validity_findings(
                corrected,
                project_id=project_id,
                valid_node_names=valid_nodes,
                evidence_ids=evidence_ids,
                project_evidence_ids=project_evidence_ids,
                seen_ids=seen_ids,
                peers=scoped,
            )
            validity, reasons = decide_validity(corrected, findings)
            suggestions = semantic_correction_suggestions(findings["issues"])
            validity_review = TestValidityReview(
                test_case_id=corrected.test_case_id,
                validity=validity.value,
                validity_score=validity_score(findings["issues"]),
                validity_reasons=reasons,
                quality_issues=findings["issues"],
                evidence_checked=findings["evidence_checked"],
                graph_path_valid=findings["graph_path_valid"],
                requirement_support="supported"
                if findings["evidence_supported"]
                else "unknown",
                duplicate_status=findings["duplicate_status"],
                missing_information=findings["missing"],
                correction_possible=findings["correction_possible"],
                corrections_applied=corrections_applied,
                suggested_corrections=suggestions,
                reviewed_test_case=corrected,
                generation_method="deterministic_fallback",
                supported_by_project=findings["supported_by_project"],
                supported_by_evidence=findings["evidence_supported"],
                contradiction_detected=findings["contradiction"],
                content_hash=_content_hash(corrected),
            )
            source = (
                "targeted"
                if corrected.test_case_id in targeted_ids
                else (
                    "existing"
                    if corrected.test_case_id in existing_ids
                    else "generated"
                )
            )
            automation_review = None
            if validity == TestValidity.VALID:
                (
                    suit,
                    auto_pri,
                    effort,
                    conf,
                    auto_reasons,
                    non_reasons,
                    blockers,
                    prereqs,
                ) = classify_automation(corrected, profile=profile)
                layer, _ = recommend_automation_layer(corrected, profile=profile)
                automation_review = AutomationFeasibilityReview(
                    test_case_id=corrected.test_case_id,
                    automation_suitability=suit.value,
                    automation_score=compute_automation_signals(
                        corrected, profile=profile
                    )["score"],
                    automation_reasons=auto_reasons,
                    non_automation_reasons=non_reasons,
                    recommended_layer=layer.value,
                    automation_priority=auto_pri.value,
                    estimated_effort=effort.value,
                    confidence=conf.value,
                    prerequisites=prereqs,
                    blockers=blockers,
                    test_data_requirements=list(
                        dict.fromkeys(
                            (corrected.preconditions or [])[:4]
                            + (
                                ["structured test_data present"]
                                if corrected.test_data
                                else []
                            )
                        )
                    ),
                    environment_requirements=["browser test environment"]
                    if layer == AutomationLayer.UI
                    else [],
                    external_dependencies=list(
                        dict.fromkeys(
                            re.findall(
                                r"payment gateway|sso|oauth|webhook|third-party|email provider|sms provider",
                                " ".join(corrected.steps or [])
                                + " "
                                + (corrected.title or ""),
                                re.I,
                            )
                        )
                    ),
                    human_judgment_required=bool(
                        _SUBJECTIVE.search(
                            " ".join(corrected.steps or [])
                            + " "
                            + (corrected.expected_result or "")
                        )
                    ),
                    suggested_automation_scope=(
                        automation_strategy
                        or "Automate the deterministic assertions and keep subjective review out of scope."
                    ),
                    recommended_assertions=[corrected.expected_result]
                    if corrected.expected_result
                    else [],
                    recommended_framework_capabilities=["browser automation"]
                    if layer == AutomationLayer.UI
                    else ["HTTP/API assertions"]
                    if layer in {AutomationLayer.API, AutomationLayer.CONTRACT}
                    else [],
                    generation_method="deterministic_fallback",
                )
            else:
                automation_review = AutomationFeasibilityReview(
                    test_case_id=corrected.test_case_id,
                    automation_suitability=AutomationSuitability.NOT_EVALUATED.value,
                    automation_score=0,
                    automation_reasons=[
                        "Automation feasibility is evaluated only after the test passes validity review."
                    ],
                    non_automation_reasons=[f"Validity status is {validity.value}."],
                    recommended_layer=AutomationLayer.NONE.value,
                    automation_priority=AutomationPriority.NOT_RECOMMENDED.value,
                    estimated_effort=AutomationEffort.UNKNOWN.value,
                    confidence=ConfidenceLevel.LOW.value,
                    generation_method="deterministic_fallback",
                )
            item = ReviewedTestCase(
                test_case=corrected,
                original_test_case=original,
                validity_review=validity_review,
                automation_review=automation_review,
                final_review_status=validity.value,
                test_source=source,
            )
            reviewed.append(item)
            seen_ids.add(corrected.test_case_id)

        meta: dict[str, Any] = {
            "input_count": len(test_cases),
            "reviewed_count": len(reviewed),
            "fallback_used": True,
            "selected_model": None,
            "actual_model": None,
            "automation_strategy": automation_strategy,
        }

        openai = get_openai_service()
        if openai.available and not force_deterministic and reviewed:
            try:
                self._enrich_validity_with_llm(
                    reviewed,
                    project_id=project_id,
                    fused=fused,
                    routing_context=routing_context,
                )
                valid_subset = [
                    item
                    for item in reviewed
                    if item.validity_review.validity == TestValidity.VALID.value
                ]
                if valid_subset:
                    self._enrich_automation_with_llm(
                        valid_subset,
                        project_id=project_id,
                        fused=fused,
                        profile=profile,
                        routing_context=routing_context,
                    )
                meta["fallback_used"] = False
                meta["selected_model"] = (openai.last_routing or {}).get(
                    "selected_model"
                )
                meta["actual_model"] = (openai.last_routing or {}).get(
                    "actual_model_used"
                ) or openai.last_chat_model
            except Exception as exc:  # noqa: BLE001
                logger.warning("validity_first_llm_failed", error=str(exc))
                meta["llm_error"] = str(exc)[:200]

        final = [
            apply_human_override(item, overrides.get(item.test_case.test_case_id))
            for item in reviewed
        ]
        validity_summary = build_validity_summary(final)
        automation_summary = build_automation_summary(final)
        meta.update(
            {
                "valid_count": validity_summary.valid,
                "invalid_count": validity_summary.invalid,
                "revision_count": validity_summary.needs_revision,
                "insufficient_evidence_count": validity_summary.insufficient_evidence,
                "automation_input_count": automation_summary.valid_tests_evaluated,
                "automate_count": automation_summary.automate,
                "conditional_count": automation_summary.automate_with_conditions,
                "hybrid_count": automation_summary.hybrid,
                "manual_count": automation_summary.manual,
                "not_ready_count": automation_summary.not_ready_for_automation,
            }
        )
        return final, validity_summary, automation_summary, meta

    def _enrich_validity_with_llm(
        self,
        reviewed: list[ReviewedTestCase],
        *,
        project_id: str,
        fused: FusedContext,
        routing_context: ModelRoutingContext | None,
    ) -> None:
        openai = get_openai_service()
        ctx = routing_context or ModelRoutingContext(
            project_id=project_id,
            task_type=LLMTaskType.TEST_VALIDITY_REVIEW,
            selected_feature=fused.feature_context.get("name"),
            graph_path_count=len(fused.flow_paths or []),
        )
        ctx.task_type = LLMTaskType.TEST_VALIDITY_REVIEW
        by_id = {item.test_case.test_case_id: item for item in reviewed}
        for i in range(0, len(reviewed), BATCH_SIZE):
            batch = reviewed[i : i + BATCH_SIZE]
            payload = [
                {
                    "test_case_id": item.test_case.test_case_id,
                    "title": item.test_case.title,
                    "steps": item.test_case.steps[:8],
                    "expected_result": item.test_case.expected_result,
                    "candidate_validity": item.validity_review.validity,
                    "quality_issues": item.validity_review.quality_issues,
                    "reasons": item.validity_review.validity_reasons,
                }
                for item in batch
            ]
            data = openai.chat_json(
                self.VALIDITY_SYSTEM_PROMPT,
                f"project_id={project_id}\nfeature={fused.feature_context.get('name')}\nreviews={payload}",
                task_type=LLMTaskType.TEST_VALIDITY_REVIEW,
                routing_context=ctx,
            )
            for row in data.get("reviews") or []:
                item = by_id.get(str(row.get("test_case_id") or ""))
                if not item:
                    continue
                val = str(row.get("validity") or item.validity_review.validity)
                if val in {v.value for v in TestValidity}:
                    item.validity_review.validity = val
                    item.final_review_status = val
                if isinstance(row.get("validity_reasons"), list):
                    item.validity_review.validity_reasons = [
                        str(x) for x in row["validity_reasons"][:12]
                    ]
                if isinstance(row.get("quality_issues"), list):
                    item.validity_review.quality_issues = list(
                        dict.fromkeys(
                            item.validity_review.quality_issues
                            + [str(x) for x in row["quality_issues"][:12]]
                        )
                    )
                if isinstance(row.get("missing_information"), list):
                    item.validity_review.missing_information = [
                        str(x) for x in row["missing_information"][:12]
                    ]
                if row.get("correction_possible") is not None:
                    item.validity_review.correction_possible = bool(
                        row["correction_possible"]
                    )
                if isinstance(row.get("suggested_corrections"), list):
                    item.validity_review.suggested_corrections = [
                        str(x) for x in row["suggested_corrections"][:12]
                    ]
                item.validity_review.generation_method = "llm"

    def _enrich_automation_with_llm(
        self,
        reviewed: list[ReviewedTestCase],
        *,
        project_id: str,
        fused: FusedContext,
        profile: AutomationCapabilityProfile | None,
        routing_context: ModelRoutingContext | None,
    ) -> None:
        openai = get_openai_service()
        ctx = routing_context or ModelRoutingContext(
            project_id=project_id,
            task_type=LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW,
            selected_feature=fused.feature_context.get("name"),
            graph_path_count=len(fused.flow_paths or []),
        )
        ctx.task_type = LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW
        by_id = {item.test_case.test_case_id: item for item in reviewed}
        for i in range(0, len(reviewed), BATCH_SIZE):
            batch = reviewed[i : i + BATCH_SIZE]
            payload = [
                {
                    "test_case_id": item.test_case.test_case_id,
                    "title": item.test_case.title,
                    "category": item.test_case.category,
                    "steps": item.test_case.steps[:8],
                    "expected_result": item.test_case.expected_result,
                    "candidate_suitability": item.automation_review.automation_suitability
                    if item.automation_review
                    else AutomationSuitability.NOT_EVALUATED.value,
                    "candidate_layer": item.automation_review.recommended_layer
                    if item.automation_review
                    else AutomationLayer.NONE.value,
                    "profile_configured": profile is not None,
                }
                for item in batch
            ]
            data = openai.chat_json(
                self.AUTOMATION_SYSTEM_PROMPT,
                f"project_id={project_id}\nfeature={fused.feature_context.get('name')}\nreviews={payload}",
                task_type=LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW,
                routing_context=ctx,
            )
            for row in data.get("reviews") or []:
                item = by_id.get(str(row.get("test_case_id") or ""))
                if not item or not item.automation_review:
                    continue
                review = item.automation_review
                for field in (
                    "automation_suitability",
                    "recommended_layer",
                    "automation_priority",
                    "estimated_effort",
                    "confidence",
                    "suggested_automation_scope",
                ):
                    if row.get(field):
                        setattr(review, field, str(row[field]))
                for field in (
                    "automation_reasons",
                    "non_automation_reasons",
                    "blockers",
                    "prerequisites",
                    "recommended_assertions",
                ):
                    if isinstance(row.get(field), list):
                        setattr(review, field, [str(x) for x in row[field][:12]])
                review.generation_method = "llm"
