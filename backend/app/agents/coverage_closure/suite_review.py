"""Machine-actionable suite review built from validity + obligation gaps."""

from __future__ import annotations

from app.agents.coverage_closure.matching import evaluate_obligation_coverage
from app.agents.dedup import is_duplicate
from app.models.enums import (
    GeneratorRevisionMode,
    ObligationStatus,
    ObligationType,
    Priority,
    ReviewFindingType,
    TestValidity,
)
from app.models.schemas import (
    CoverageObligation,
    MissingScenarioFinding,
    ReviewedTestCase,
    RevisionPlan,
    TestCase,
    TestReviewFinding,
    TestSuiteReview,
    new_id,
)

_VALIDITY_TO_FINDING = {
    TestValidity.INVALID.value: ReviewFindingType.INVALID_TEST,
    TestValidity.NEEDS_REVISION.value: ReviewFindingType.NEEDS_REVISION,
    TestValidity.INSUFFICIENT_EVIDENCE.value: ReviewFindingType.INSUFFICIENT_EVIDENCE,
}


def build_suite_review(
    *,
    project_id: str,
    tests: list[TestCase],
    obligations: list[CoverageObligation],
    reviewed: list[ReviewedTestCase] | None = None,
    iteration: int = 1,
) -> tuple[TestSuiteReview, list[CoverageObligation], float]:
    active = [t for t in tests if not t.retired]
    updated_obligations, matches, modeled_pct = evaluate_obligation_coverage(
        obligations, active, reviewed
    )

    per_test: list[TestReviewFinding] = []
    duplicates: list[TestReviewFinding] = []
    missing: list[MissingScenarioFinding] = []
    blocking: list[str] = []

    reviewed_by_id = {
        (r.test_case.test_case_id if r.test_case else ""): r for r in (reviewed or [])
    }

    # Per-test findings from validity review → executable instructions
    for tc in active:
        rev = reviewed_by_id.get(tc.test_case_id)
        if not rev or not rev.validity_review:
            continue
        validity = rev.validity_review.validity
        if validity == TestValidity.VALID.value:
            continue
        ftype = _VALIDITY_TO_FINDING.get(validity, ReviewFindingType.NEEDS_REVISION)
        suggestions = list(rev.validity_review.suggested_corrections or [])
        issues = list(rev.validity_review.quality_issues or [])
        missing_info = list(rev.validity_review.missing_information or [])
        instruction = "; ".join(
            suggestions or issues or ["Revise test to satisfy validity gates."]
        )
        criteria = suggestions or [
            "Observable expected result present",
            "At least one When/action step",
            "Valid project-scoped graph path",
            "Evidence references only catalog IDs",
        ]
        finding = TestReviewFinding(
            finding_id=new_id("FIND"),
            test_case_id=tc.test_case_id,
            severity=Priority.HIGH
            if validity == TestValidity.INVALID.value
            else Priority.MEDIUM,
            finding_type=ftype,
            explanation="; ".join(issues or [validity]),
            affected_fields=[
                "title",
                "steps",
                "expected_result",
                "graph_path",
                "evidence",
            ],
            required_action=GeneratorRevisionMode.REVISE
            if validity != TestValidity.INSUFFICIENT_EVIDENCE.value
            else GeneratorRevisionMode.RETIRE,
            revision_instruction=instruction,
            acceptance_criteria=criteria
            + ([f"Provide: {m}" for m in missing_info] if missing_info else []),
        )
        per_test.append(finding)
        if finding.severity in (Priority.CRITICAL, Priority.HIGH):
            blocking.append(finding.finding_id)

    # Exact duplicates
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if is_duplicate(a, [b]):
                finding = TestReviewFinding(
                    finding_id=new_id("FIND"),
                    test_case_id=b.test_case_id,
                    severity=Priority.MEDIUM,
                    finding_type=ReviewFindingType.EXACT_DUPLICATE,
                    explanation=f"Exact/near duplicate of {a.test_case_id}",
                    affected_fields=["title", "steps", "expected_result", "graph_path"],
                    required_action=GeneratorRevisionMode.RETIRE,
                    revision_instruction=f"Retire {b.test_case_id}; retain {a.test_case_id}.",
                    acceptance_criteria=[
                        "Only one logical test remains for this fingerprint"
                    ],
                )
                duplicates.append(finding)

    # Missing scenarios from open mandatory obligations
    for obl in updated_obligations:
        if not obl.mandatory:
            continue
        if obl.status in (
            ObligationStatus.COVERED,
            ObligationStatus.INSUFFICIENT_EVIDENCE,
        ):
            continue
        category = "functional"
        if obl.obligation_type in (
            ObligationType.NEGATIVE_FLOW,
            ObligationType.FAILURE_PATH,
            ObligationType.VALIDATION,
        ):
            category = "negative"
        elif obl.obligation_type == ObligationType.HISTORICAL_BUG_REGRESSION:
            category = "regression"
        elif obl.obligation_type == ObligationType.SECURITY:
            category = "security"
        missing.append(
            MissingScenarioFinding(
                finding_id=new_id("MISS"),
                obligation_ids=[obl.obligation_id],
                category=category,
                priority=obl.priority
                if isinstance(obl.priority, Priority)
                else Priority.HIGH,
                title=f"Missing: {obl.title}",
                explanation=obl.description or obl.title,
                required_graph_path=list(obl.graph_path),
                required_behavior=obl.obligation_type.value,
                required_expected_outcome="Observable pass/fail outcome aligned to the obligation",
                evidence_references=list(obl.evidence_references),
                generation_instruction=(
                    f"CREATE a focused test for obligation {obl.obligation_id} "
                    f"({obl.obligation_type.value}). Graph path: {' → '.join(obl.graph_path) or 'feature root'}. "
                    f"Do not regenerate unrelated covered tests. "
                    f"Include steps + observable expected result. Link obligation_ids=[{obl.obligation_id}]."
                ),
                acceptance_criteria=[
                    "Compatible graph path",
                    "Observable expected result",
                    "Non-empty steps",
                    f"Covers obligation {obl.obligation_id}",
                    "Same project_id",
                ],
            )
        )

    revise_ids = [
        f.test_case_id
        for f in per_test
        if f.required_action == GeneratorRevisionMode.REVISE
    ]
    reject_ids = [
        f.test_case_id
        for f in per_test + duplicates
        if f.required_action == GeneratorRevisionMode.RETIRE
    ]
    create_ids = [oid for m in missing for oid in m.obligation_ids]
    retain_ids = [
        tc.test_case_id
        for tc in active
        if tc.test_case_id not in revise_ids and tc.test_case_id not in reject_ids
    ]

    plan = RevisionPlan(
        revise_test_ids=list(dict.fromkeys(revise_ids)),
        reject_test_ids=list(dict.fromkeys(reject_ids)),
        retain_test_ids=retain_ids,
        create_for_obligation_ids=list(dict.fromkeys(create_ids)),
        priority_order=list(dict.fromkeys(revise_ids + create_ids + reject_ids)),
        instructions=[f.revision_instruction for f in per_test]
        + [m.generation_instruction for m in missing]
        + [d.revision_instruction for d in duplicates],
    )

    invalid_like = sum(
        1
        for f in per_test
        if f.finding_type
        in (ReviewFindingType.INVALID_TEST, ReviewFindingType.NEEDS_REVISION)
    )
    quality = max(
        0.0, 100.0 - invalid_like * 5 - len(missing) * 3 - len(duplicates) * 2
    )
    recommendation = (
        "succeed"
        if modeled_pct >= 100 and not per_test and not missing and not duplicates
        else "continue"
    )

    review = TestSuiteReview(
        review_id=new_id("REV"),
        project_id=project_id,
        iteration=iteration,
        overall_status="open" if recommendation == "continue" else "ready",
        suite_quality_score=round(quality, 2),
        obligation_coverage=matches,
        per_test_findings=per_test,
        missing_scenario_findings=missing,
        duplicate_findings=duplicates,
        revision_plan=plan,
        blocking_findings=blocking,
        convergence_recommendation=recommendation,
    )
    return review, updated_obligations, modeled_pct
