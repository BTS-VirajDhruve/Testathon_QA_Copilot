"""Logical obligation ↔ test matching (not title-token-only)."""

from __future__ import annotations

from app.agents.dedup import normalize_path, normalize_text
from app.models.enums import ObligationStatus, ObligationType, TestValidity
from app.models.schemas import (
    CoverageObligation,
    ObligationCoverageMatch,
    ReviewedTestCase,
    TestCase,
)


def _tokens(values: list[str] | str) -> set[str]:
    if isinstance(values, str):
        text = values
    else:
        text = " ".join(values)
    return {t for t in normalize_text(text).split() if len(t) > 2}


def _path_compatible(obligation_path: list[str], test_path: list[str]) -> bool:
    if not obligation_path:
        return True
    if not test_path:
        return False
    o = normalize_path(obligation_path)
    t = normalize_path(test_path)
    if o == t:
        return True
    # Leaf overlap or subsequence
    if o and o[-1] in t:
        return True
    if set(o).issubset(set(t)) or set(t).issubset(set(o)):
        return True
    return False


def _behavior_compatible(obligation: CoverageObligation, test: TestCase) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    missing: list[str] = []
    otype = obligation.obligation_type
    cat = (test.category or "").lower()
    title = (test.title or "").lower()
    blob = " ".join(
        [
            test.title or "",
            test.expected_result or "",
            " ".join(test.steps or []),
            test.testing_technique or "",
            test.reasoning or "",
        ]
    ).lower()

    def need(words: list[str], label: str) -> None:
        if any(w in blob for w in words):
            reasons.append(label)
        else:
            missing.append(label)

    if otype in (ObligationType.NEGATIVE_FLOW, ObligationType.VALIDATION) and "negative" in cat:
        reasons.append("negative_category")
    if otype == ObligationType.FAILURE_PATH:
        need(["fail", "error", "timeout", "invalid", "reject", "denied"], "failure_behavior")
    if otype == ObligationType.RECOVERY:
        need(["recover", "retry", "resume", "fallback", "restore"], "recovery_behavior")
    if otype == ObligationType.HISTORICAL_BUG_REGRESSION:
        need(["regression", "bug", "repro"], "regression_behavior")
        if obligation.bug_ids:
            if any(b.lower() in blob for b in obligation.bug_ids):
                reasons.append("bug_id_reference")
            else:
                # title overlap with obligation title is acceptable secondary signal
                if normalize_text(obligation.title) in normalize_text(title):
                    reasons.append("bug_title_overlap")
                else:
                    missing.append("bug_reference")
    if otype == ObligationType.SECURITY:
        need(["auth", "permission", "role", "token", "security", "unauthorized", "forbidden"], "security_behavior")
    if otype == ObligationType.ROLE_PERMISSION:
        need(["role", "permission", "authorize", "access", "denied", "allowed"], "role_behavior")
        if obligation.role and obligation.role.lower() in blob:
            reasons.append("role_named")
    if otype == ObligationType.BOUNDARY:
        need(["boundary", "min", "max", "edge", "limit", "length", "empty"], "boundary_behavior")
    if otype == ObligationType.STATE_TRANSITION:
        need(["state", "transition", "status", "move"], "state_behavior")
    if otype == ObligationType.EXTERNAL_DEPENDENCY:
        need(["timeout", "unavailable", "dependency", "provider", "external", "fallback"], "dependency_failure")
    if otype in (ObligationType.POSITIVE_FLOW, ObligationType.GRAPH_PATH, ObligationType.ALTERNATE_FLOW):
        if test.expected_result and len(test.expected_result.strip()) > 8:
            reasons.append("observable_outcome")
        else:
            missing.append("expected_result")
    if otype == ObligationType.REQUIREMENT and obligation.requirement_ids:
        if any(r.lower() in blob for r in obligation.requirement_ids):
            reasons.append("requirement_id")
        elif _tokens(obligation.title) & _tokens(blob):
            reasons.append("requirement_semantic_overlap")
        else:
            missing.append("requirement_link")

    # Expected result always required for coverage credit
    if not (test.expected_result or "").strip():
        missing.append("expected_result")
    elif len((test.expected_result or "").strip()) < 8:
        missing.append("observable_expected_result")
    else:
        reasons.append("has_expected_result")

    if not test.steps:
        missing.append("steps")
    else:
        reasons.append("has_steps")

    covered_signal = len(reasons) >= 2 and "expected_result" not in missing and "steps" not in missing
    # Type-specific: if we required a behavior label and it's missing, fail
    type_missing = [m for m in missing if m.endswith("_behavior") or m in ("bug_reference", "requirement_link", "role_named")]
    if type_missing and otype not in (
        ObligationType.POSITIVE_FLOW,
        ObligationType.GRAPH_PATH,
        ObligationType.REQUIREMENT,
    ):
        covered_signal = False
    return covered_signal, reasons, missing


def match_test_to_obligation(
    obligation: CoverageObligation,
    test: TestCase,
    *,
    validity: str | None = None,
) -> ObligationCoverageMatch:
    """Deterministic logical match. Title-only overlap is never sufficient."""
    missing: list[str] = []
    conflicts: list[str] = []
    reasons: list[str] = []
    score = 0.0

    if test.retired:
        return ObligationCoverageMatch(
            obligation_id=obligation.obligation_id,
            test_case_id=test.test_case_id,
            covered=False,
            match_score=0.0,
            missing_elements=["retired_test"],
        )

    if test.project_id and obligation.project_id and test.project_id != obligation.project_id:
        return ObligationCoverageMatch(
            obligation_id=obligation.obligation_id,
            test_case_id=test.test_case_id,
            covered=False,
            conflicting_elements=["wrong_project"],
        )

    if validity in (
        TestValidity.INVALID.value,
        TestValidity.NEEDS_REVISION.value,
        TestValidity.INSUFFICIENT_EVIDENCE.value,
        "invalid",
        "needs_revision",
        "insufficient_evidence",
    ):
        return ObligationCoverageMatch(
            obligation_id=obligation.obligation_id,
            test_case_id=test.test_case_id,
            covered=False,
            missing_elements=[f"validity:{validity}"],
        )

    if obligation.status == ObligationStatus.INSUFFICIENT_EVIDENCE:
        return ObligationCoverageMatch(
            obligation_id=obligation.obligation_id,
            test_case_id=test.test_case_id,
            covered=False,
            missing_elements=["obligation_insufficient_evidence"],
        )

    if _path_compatible(obligation.graph_path, test.graph_path or []):
        reasons.append("compatible_graph_path")
        score += 0.35
    else:
        missing.append("compatible_graph_path")

    ok, behavior_reasons, behavior_missing = _behavior_compatible(obligation, test)
    reasons.extend(behavior_reasons)
    missing.extend(behavior_missing)
    if ok:
        score += 0.45
    else:
        score += 0.1 * min(len(behavior_reasons), 2)

    # Explicit obligation link
    if obligation.obligation_id in (test.obligation_ids or []):
        reasons.append("explicit_obligation_link")
        score += 0.25

    # Title-only: may add a tiny score but cannot alone cover
    title_overlap = bool(_tokens(obligation.title) & _tokens(test.title or ""))
    if title_overlap:
        reasons.append("title_token_overlap")
        score += 0.05

    covered = (
        score >= 0.7
        and "compatible_graph_path" in reasons
        and "has_expected_result" in reasons
        and "has_steps" in reasons
        and "wrong_project" not in conflicts
        and ok
    )
    # Positive path may pass with path + steps + expected even without type keyword
    if (
        obligation.obligation_type
        in (ObligationType.POSITIVE_FLOW, ObligationType.GRAPH_PATH, ObligationType.ALTERNATE_FLOW)
        and "compatible_graph_path" in reasons
        and "has_expected_result" in reasons
        and "has_steps" in reasons
        and not test.retired
    ):
        covered = True
        score = max(score, 0.75)

    return ObligationCoverageMatch(
        obligation_id=obligation.obligation_id,
        test_case_id=test.test_case_id,
        covered=covered,
        match_score=round(min(score, 1.0), 3),
        match_reasons=reasons,
        missing_elements=missing,
        conflicting_elements=conflicts,
    )


def evaluate_obligation_coverage(
    obligations: list[CoverageObligation],
    tests: list[TestCase],
    reviews: list[ReviewedTestCase] | None = None,
) -> tuple[list[CoverageObligation], list[ObligationCoverageMatch], float]:
    """Update obligation statuses and return matches + mandatory coverage %."""
    validity_by_id: dict[str, str] = {}
    for r in reviews or []:
        tc = r.test_case
        tid = tc.test_case_id if tc else None
        if tid and r.validity_review:
            validity_by_id[tid] = r.validity_review.validity

    active_tests = [t for t in tests if not t.retired]
    matches: list[ObligationCoverageMatch] = []
    updated: list[CoverageObligation] = []

    for obl in obligations:
        if obl.status == ObligationStatus.INSUFFICIENT_EVIDENCE:
            updated.append(obl.model_copy(update={"covered_by_test_ids": [], "coverage_reason": None}))
            continue
        covering: list[str] = []
        best_reason = None
        for tc in active_tests:
            m = match_test_to_obligation(
                obl, tc, validity=validity_by_id.get(tc.test_case_id)
            )
            matches.append(m)
            if m.covered:
                covering.append(tc.test_case_id)
                best_reason = "; ".join(m.match_reasons)
        status = ObligationStatus.COVERED if covering else ObligationStatus.OPEN
        updated.append(
            obl.model_copy(
                update={
                    "status": status,
                    "covered_by_test_ids": covering,
                    "coverage_reason": best_reason,
                }
            )
        )

    mandatory = [o for o in updated if o.mandatory and o.status != ObligationStatus.INSUFFICIENT_EVIDENCE]
    covered = [o for o in mandatory if o.status == ObligationStatus.COVERED]
    pct = round(100.0 * len(covered) / len(mandatory), 2) if mandatory else 100.0
    return updated, matches, pct
