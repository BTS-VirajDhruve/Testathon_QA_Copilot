"""Create / revise / retire tests from a RevisionPlan."""

from __future__ import annotations

from typing import Any

from app.agents.dedup import deduplicate_tests
from app.agents.evidence import build_evidence_catalog, evidence_for_path_bugs_and_requirements, sanitize_evidence
from app.agents.test_review_automation import (
    apply_safe_corrections,
    apply_validity_hardening,
    default_observable_expected,
    has_observable_outcome,
)
from app.models.enums import ObligationType, Priority, RiskLevel
from app.models.schemas import (
    CoverageObligation,
    FusedContext,
    ReviewedTestCase,
    RevisionPlan,
    TestCase,
    TestSuiteReview,
    new_id,
)


def _snapshot(tc: TestCase) -> dict[str, Any]:
    return tc.model_dump(mode="json")


def _finding_blob(findings: list[Any], reviewed: ReviewedTestCase | None) -> str:
    parts: list[str] = []
    for f in findings:
        parts.append(str(getattr(f, "revision_instruction", "") or ""))
        parts.append(str(getattr(f, "finding_type", "") or ""))
        parts.append(str(getattr(f, "message", "") or ""))
    if reviewed and reviewed.validity_review:
        vr = reviewed.validity_review
        parts.extend(vr.validity_reasons or [])
        parts.extend(vr.quality_issues or [])
        parts.append(str(vr.validity or ""))
    return " ".join(parts).lower()


def revise_test_from_findings(
    tc: TestCase,
    review: TestSuiteReview,
    reviewed: ReviewedTestCase | None,
    iteration: int,
) -> TestCase:
    """Apply safe corrections and fill obvious gaps while preserving logical ID."""
    findings = [f for f in review.per_test_findings if f.test_case_id == tc.test_case_id]
    if tc.do_not_edit or tc.human_edited:
        return tc

    base = tc
    corrected, applied = apply_safe_corrections(tc)
    if applied:
        base = corrected

    updated = base.model_copy(deep=True)
    prev = _snapshot(tc)
    finding_ids = [f.finding_id for f in findings]
    blob = _finding_blob(findings, reviewed)
    path = list(updated.graph_path or [])

    needs_expected_fix = (
        not (updated.expected_result or "").strip()
        or not has_observable_outcome(updated.expected_result)
        or any(
            key in blob
            for key in (
                "expected",
                "observable",
                "assertion",
                "expected_result_may_not_be_observable",
                "non_observable",
            )
        )
    )
    if needs_expected_fix:
        if (updated.expected_result or "").strip() and has_observable_outcome(updated.expected_result):
            pass
        elif (updated.expected_result or "").strip():
            updated.expected_result = (
                f"{updated.expected_result.rstrip('.')} — assert a clear status or error "
                f"message is displayed or returned."
            )
        else:
            updated.expected_result = default_observable_expected(updated.title, path)

    needs_steps_fix = (
        not updated.steps
        or "vague" in blob
        or "step" in blob
        or "non_reproducible" in blob
    )
    if needs_steps_fix and (
        not updated.steps
        or "vague" in blob
        or "non_reproducible" in blob
        or any(len(str(s).strip()) < 8 for s in (updated.steps or []))
    ):
        path_label = " → ".join(path or ["feature"])
        updated.steps = [
            f"Given the system is prepared for path {path_label} with required session state",
            f"When the user executes the scenario for {updated.title}",
            "Then confirm the returned status or error message matches the expected result",
        ]

    if not updated.preconditions or "precondition" in blob or "setup" in blob:
        path_label = " → ".join(path or ["feature"])
        updated.preconditions = [
            "Required user/session account is available",
            f"Environment is seeded for path: {path_label}",
        ]

    if (
        len((updated.title or "").strip()) < 8
        or "vague_title" in blob
        or ("vague" in blob and "title" in blob)
    ):
        updated.title = f"Validate {' → '.join(path or ['feature'])} returns expected status"

    # Final hardening pass clears remaining soft gates (observability tokens, etc.)
    hardened, _ = apply_validity_hardening(updated)
    updated = hardened

    updated.previous_version_snapshot = prev
    updated.revision_version = int(tc.revision_version or 1) + 1
    updated.generation_round = iteration
    updated.generation_method = updated.generation_method or "revision"
    updated.reviewer_finding_ids = list(dict.fromkeys((tc.reviewer_finding_ids or []) + finding_ids))
    updated.revision_summary = "; ".join(f.revision_instruction for f in findings)[:500]
    updated.reasoning = updated.revision_summary or updated.reasoning
    return updated


def create_test_for_obligation(
    obligation: CoverageObligation,
    fused: FusedContext,
    project_id: str,
    iteration: int,
) -> TestCase:
    path = list(obligation.graph_path) or [
        (fused.feature_context or {}).get("name") or "Feature"
    ]
    path_label = " → ".join(path)
    otype = obligation.obligation_type
    category = "functional"
    technique = "Requirements-based testing"
    title = obligation.title
    if otype in (ObligationType.NEGATIVE_FLOW, ObligationType.VALIDATION, ObligationType.FAILURE_PATH):
        category = "negative"
        technique = "Negative testing / fault injection"
        title = title if title.lower().startswith("negative") else f"Negative: {obligation.title}"
    elif otype == ObligationType.HISTORICAL_BUG_REGRESSION:
        category = "regression"
        technique = "Historical-bug regression testing"
    elif otype == ObligationType.SECURITY:
        category = "security"
        technique = "Security / authorization testing"
    elif otype == ObligationType.BOUNDARY:
        category = "boundary"
        technique = "Boundary value analysis"
    elif otype == ObligationType.RECOVERY:
        category = "recovery"
        technique = "Recovery / resilience testing"
    elif otype == ObligationType.ROLE_PERMISSION:
        category = "security"
        technique = "Role-based access testing"

    expected = default_observable_expected(title, path)
    if otype in (ObligationType.NEGATIVE_FLOW, ObligationType.FAILURE_PATH, ObligationType.VALIDATION):
        expected = (
            f"The system rejects or fails safely for '{obligation.title}' and surfaces an "
            f"error message or validation status without corrupting persisted state."
        )
    elif otype == ObligationType.RECOVERY:
        expected = (
            "After the failure, the system recovers or retries and reaches a stable state; "
            "a success status or recovery message is displayed or returned."
        )
    elif otype == ObligationType.SECURITY or otype == ObligationType.ROLE_PERMISSION:
        expected = (
            "Unauthorized access is denied with HTTP 401/403 status or an equivalent visible "
            "access-denied message; authorized access succeeds with a success status."
        )

    steps = [
        f"Given preconditions for {path_label} including required session state",
        f"When exercising {obligation.obligation_type.value.replace('_', ' ')}: {obligation.title}",
        "Then assert the returned status or error message matches the expected result",
    ]
    catalog = build_evidence_catalog(fused)
    evidence = evidence_for_path_bugs_and_requirements(path, fused, catalog)
    evidence = sanitize_evidence(evidence, catalog)

    created = TestCase(
        test_case_id=new_id("TC"),
        title=title[:160],
        category=category,
        priority=obligation.priority if isinstance(obligation.priority, Priority) else Priority.HIGH,
        risk=RiskLevel.HIGH
        if obligation.priority in (Priority.CRITICAL, Priority.HIGH)
        else RiskLevel.MEDIUM,
        preconditions=[
            "Required user/session account is available",
            f"Project context and graph path are available: {path_label}",
        ],
        steps=steps,
        expected_result=expected[:400],
        testing_technique=technique,
        graph_path=path,
        graph_reasoning=f"Generated for obligation {obligation.obligation_id}",
        project_id=project_id,
        generation_method="missing_scenario",
        reasoning=obligation.description or obligation.title,
        evidence=evidence,
        obligation_ids=[obligation.obligation_id],
        generation_round=iteration,
        revision_version=1,
        source_references=[e.source_id for e in evidence if e.source_id],
    )
    hardened, _ = apply_validity_hardening(created)
    return hardened


def harden_suite_tests(tests: list[TestCase]) -> list[TestCase]:
    """Apply validity hardening to every editable, non-retired test."""
    out: list[TestCase] = []
    for tc in tests:
        if tc.retired or tc.do_not_edit or tc.human_edited:
            out.append(tc)
            continue
        hardened, applied = apply_validity_hardening(tc)
        if applied:
            hardened = hardened.model_copy(
                update={
                    "revision_version": int(tc.revision_version or 1) + 1,
                    "revision_summary": (
                        (tc.revision_summary or "")
                        + ("; " if tc.revision_summary else "")
                        + "validity_hardening:"
                        + ",".join(applied)
                    )[:500],
                    "previous_version_snapshot": _snapshot(tc),
                }
            )
        out.append(hardened)
    return out


def apply_revision_plan(
    *,
    tests: list[TestCase],
    obligations: list[CoverageObligation],
    review: TestSuiteReview,
    fused: FusedContext,
    project_id: str,
    iteration: int,
    reviewed: list[ReviewedTestCase] | None = None,
    max_new: int = 40,
) -> tuple[list[TestCase], dict[str, int]]:
    """Execute create/revise/retire modes. Preserves logical IDs on revise."""
    plan: RevisionPlan = review.revision_plan
    reviewed_by_id = {
        (r.test_case.test_case_id if r.test_case else ""): r for r in (reviewed or [])
    }
    by_id = {t.test_case_id: t for t in tests}
    stats = {
        "tests_created": 0,
        "tests_revised": 0,
        "tests_retired": 0,
        "tests_merged": 0,
        "tests_split": 0,
        "duplicates_removed": 0,
    }

    # Retire duplicates / unsupported
    for tid in plan.reject_test_ids:
        tc = by_id.get(tid)
        if not tc or tc.do_not_edit:
            continue
        by_id[tid] = tc.model_copy(
            update={
                "retired": True,
                "revision_summary": "Retired by revision plan",
                "previous_version_snapshot": _snapshot(tc),
                "revision_version": int(tc.revision_version or 1) + 1,
                "generation_round": iteration,
            }
        )
        stats["tests_retired"] += 1

    # Revise
    for tid in plan.revise_test_ids:
        tc = by_id.get(tid)
        if not tc or tc.retired or tc.do_not_edit:
            continue
        by_id[tid] = revise_test_from_findings(
            tc, review, reviewed_by_id.get(tid), iteration
        )
        stats["tests_revised"] += 1

    obl_by_id = {o.obligation_id: o for o in obligations}
    new_cases: list[TestCase] = []
    for oid in plan.create_for_obligation_ids[:max_new]:
        obl = obl_by_id.get(oid)
        if not obl:
            continue
        # Skip insufficient evidence obligations — do not fabricate
        if obl.unsupported_reason or obl.obligation_type == ObligationType.INSUFFICIENT_EVIDENCE:
            continue
        # Already covered by an active non-retired test linked to obligation
        if any(
            oid in (t.obligation_ids or []) and not t.retired for t in by_id.values()
        ):
            continue
        created = create_test_for_obligation(obl, fused, project_id, iteration)
        new_cases.append(created)

    existing_list = list(by_id.values())
    unique_new = deduplicate_tests(new_cases, against=[t for t in existing_list if not t.retired])
    stats["duplicates_removed"] += max(0, len(new_cases) - len(unique_new))
    stats["tests_created"] = len(unique_new)
    for tc in unique_new:
        by_id[tc.test_case_id] = tc

    # Stable order: non-retired first
    ordered = sorted(by_id.values(), key=lambda t: (t.retired, t.test_case_id))
    return ordered, stats
