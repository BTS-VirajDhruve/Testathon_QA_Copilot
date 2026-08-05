"""Bounded GENERATE → REVIEW → REVISE → RECHECK loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.coverage_closure.convergence import ConvergenceController, RefinementLimits
from app.agents.coverage_closure.obligations import build_coverage_obligations, category_coverage_summary
from app.agents.coverage_closure.revision import apply_revision_plan, harden_suite_tests
from app.agents.coverage_closure.suite_review import build_suite_review
from app.agents.dedup import deduplicate_tests
from app.models.enums import ConvergenceStatus, ObligationStatus, TestValidity
from app.models.schemas import (
    CategoryCoverage,
    ConvergenceReport,
    CoverageObligation,
    FusedContext,
    ObligationCoverageMatch,
    RefinementIterationSnapshot,
    ReviewedTestCase,
    SystemFlowGraph,
    TestCase,
    TestSuiteReview,
    ValiditySummary,
)


TraceFn = Callable[[str, str, str], None]


@dataclass
class RefinementLoopResult:
    tests: list[TestCase]
    obligations: list[CoverageObligation]
    obligation_coverage: list[ObligationCoverageMatch]
    category_coverage: list[CategoryCoverage]
    iteration_history: list[RefinementIterationSnapshot]
    convergence_report: ConvergenceReport
    final_review: TestSuiteReview | None
    reviewed_test_cases: list[ReviewedTestCase] = field(default_factory=list)
    validity_summary: ValiditySummary | None = None


def _count_validity(reviewed: list[ReviewedTestCase]) -> tuple[int, int]:
    invalid = 0
    needs = 0
    for r in reviewed:
        v = (r.validity_review.validity if r.validity_review else "") or ""
        if v == TestValidity.INVALID.value:
            invalid += 1
        elif v == TestValidity.NEEDS_REVISION.value:
            needs += 1
    return invalid, needs


def run_refinement_loop(
    *,
    project_id: str,
    tests: list[TestCase],
    fused: FusedContext,
    graph: SystemFlowGraph | None,
    query: str,
    root_feature: str | None,
    review_agent: Any,
    limits: RefinementLimits | None = None,
    existing_obligations: list[CoverageObligation] | None = None,
    prior_history: list[RefinementIterationSnapshot] | None = None,
    emit_trace: TraceFn | None = None,
    force_deterministic_review: bool = True,
) -> RefinementLoopResult:
    """Run bounded coverage-closure refinement.

    Uses deterministic suite review + validity agent each round.
    Does not invent unsupported obligations (e.g. performance without targets).
    """
    limits = limits or RefinementLimits.from_settings()
    controller = ConvergenceController(limits=limits)
    if prior_history:
        controller.history.extend(prior_history)

    def trace(step: str, detail: str, status: str = "complete") -> None:
        if emit_trace:
            emit_trace(step, detail, status)

    obligations = existing_obligations or build_coverage_obligations(
        project_id=project_id,
        fused=fused,
        graph=graph,
        query=query,
        root_feature=root_feature,
    )
    trace(
        "Coverage Obligation Construction",
        f"{len(obligations)} modeled obligations "
        f"({sum(1 for o in obligations if o.mandatory)} mandatory)",
    )

    working = list(tests)
    # Dedupe once up front
    working = deduplicate_tests(working)
    initial_count = len([t for t in working if not t.retired])
    totals = {
        "tests_created": 0,
        "tests_revised": 0,
        "tests_retired": 0,
        "tests_merged": 0,
        "tests_split": 0,
        "duplicates_removed": 0,
    }

    reviewed: list[ReviewedTestCase] = []
    validity_summary: ValiditySummary | None = None
    final_review: TestSuiteReview | None = None
    modeled_pct = 0.0
    matches: list[ObligationCoverageMatch] = []
    invalid_before = 0
    needs_before = 0
    initial_coverage = 0.0
    status = ConvergenceStatus.PARTIAL
    stop_reason = ""

    for iteration in range(1, limits.max_iterations + 1):
        trace("Suite Review — Iteration N".replace("N", str(iteration)), f"reviewing {len(working)} tests")

        if not force_deterministic_review:
            controller.llm_calls += 1

        reviewed, validity_summary, _auto, _meta = review_agent.review(
            test_cases=[t for t in working if not t.retired],
            project_id=project_id,
            fused=fused,
            force_deterministic=force_deterministic_review,
        )
        # Apply safe corrections onto working set
        corrected_by_id = {
            r.test_case.test_case_id: r.test_case
            for r in reviewed
            if r.test_case and r.test_case.test_case_id
        }
        working = [
            corrected_by_id.get(t.test_case_id, t) if not t.retired else t for t in working
        ]

        invalid_count, needs_count = _count_validity(reviewed)
        if iteration == 1:
            invalid_before = invalid_count
            needs_before = needs_count

        review, obligations, modeled_pct = build_suite_review(
            project_id=project_id,
            tests=working,
            obligations=obligations,
            reviewed=reviewed,
            iteration=iteration,
        )
        matches = review.obligation_coverage
        final_review = review
        if iteration == 1:
            initial_coverage = modeled_pct

        open_mandatory = [
            o.obligation_id
            for o in obligations
            if o.mandatory
            and o.status not in (ObligationStatus.COVERED, ObligationStatus.INSUFFICIENT_EVIDENCE)
        ]
        snap = RefinementIterationSnapshot(
            iteration=iteration,
            test_count=len([t for t in working if not t.retired]),
            modeled_coverage_pct=modeled_pct,
            mandatory_total=sum(
                1
                for o in obligations
                if o.mandatory and o.status != ObligationStatus.INSUFFICIENT_EVIDENCE
            ),
            mandatory_covered=sum(
                1
                for o in obligations
                if o.mandatory and o.status == ObligationStatus.COVERED
            ),
            invalid_count=invalid_count,
            needs_revision_count=needs_count,
            open_mandatory_obligations=open_mandatory,
            findings_count=len(review.per_test_findings)
            + len(review.missing_scenario_findings)
            + len(review.duplicate_findings),
            message=f"coverage={modeled_pct}% invalid={invalid_count} needs_revision={needs_count}",
        )
        controller.record(snap)
        trace(
            f"Coverage Recalculation — Iteration {iteration}",
            f"modeled_coverage={modeled_pct}% open_mandatory={len(open_mandatory)}",
        )

        if controller.is_success(
            obligations=obligations,
            review=review,
            modeled_coverage=modeled_pct,
            invalid_count=invalid_count,
            needs_revision_count=needs_count,
        ):
            status = ConvergenceStatus.COMPLETE
            stop_reason = "all_mandatory_modeled_obligations_and_quality_gates_met"
            trace(
                f"Convergence Decision — Iteration {iteration}",
                "SUCCESS — 100% of modeled coverage obligations covered",
            )
            break

        stop, stop_status, reason = controller.should_stop(
            iteration=iteration,
            test_count=len([t for t in working if not t.retired]),
            review=review,
            modeled_coverage=modeled_pct,
        )
        # should_stop uses iteration>=max after completing this round's review;
        # allow revision when iteration < max
        if stop and reason == "maximum_iterations_reached":
            # Still allow one revision pass only if we haven't done max yet — actually
            # iteration == max means this was the last allowed review; stop without more gen.
            status = stop_status
            stop_reason = reason
            trace(
                f"Convergence Decision — Iteration {iteration}",
                f"STOP — {reason}",
                "skipped",
            )
            break

        if stop and reason != "maximum_iterations_reached":
            status = stop_status
            stop_reason = reason
            trace(
                f"Convergence Decision — Iteration {iteration}",
                f"STOP — {reason}",
                "skipped",
            )
            break

        if iteration >= limits.max_iterations:
            status = ConvergenceStatus.LIMIT_REACHED
            stop_reason = "maximum_iterations_reached"
            break

        trace(
            f"Revision Plan — Iteration {iteration}",
            f"revise={len(review.revision_plan.revise_test_ids)} "
            f"create={len(review.revision_plan.create_for_obligation_ids)} "
            f"retire={len(review.revision_plan.reject_test_ids)}",
        )
        working, stats = apply_revision_plan(
            tests=working,
            obligations=obligations,
            review=review,
            fused=fused,
            project_id=project_id,
            iteration=iteration,
            reviewed=reviewed,
            max_new=max(1, limits.max_tests - len([t for t in working if not t.retired])),
        )
        for k, v in stats.items():
            totals[k] = totals.get(k, 0) + v
        controller.history[-1] = snap.model_copy(
            update={
                "tests_created": stats.get("tests_created", 0),
                "tests_revised": stats.get("tests_revised", 0),
                "tests_retired": stats.get("tests_retired", 0),
                "duplicates_removed": stats.get("duplicates_removed", 0),
            }
        )
        trace(
            f"Test Revision — Iteration {iteration}",
            f"revised={stats.get('tests_revised', 0)} retired={stats.get('tests_retired', 0)}",
        )
        trace(
            f"Missing Scenario Generation — Iteration {iteration}",
            f"created={stats.get('tests_created', 0)}",
        )
        before_dedup = len(working)
        active = [t for t in working if not t.retired]
        retired = [t for t in working if t.retired]
        active = deduplicate_tests(active)
        working = active + retired
        dupes = max(0, before_dedup - len(working))
        totals["duplicates_removed"] += dupes
        trace(
            f"Deduplication — Iteration {iteration}",
            f"removed {dupes} duplicates; active={len(active)}",
        )
    else:
        status = ConvergenceStatus.LIMIT_REACHED
        stop_reason = stop_reason or "maximum_iterations_reached"

    # Final review pass for reporting
    if working:
        reviewed, validity_summary, _a, _m = review_agent.review(
            test_cases=[t for t in working if not t.retired],
            project_id=project_id,
            fused=fused,
            force_deterministic=force_deterministic_review,
        )
        invalid_probe, needs_probe = _count_validity(reviewed)
        if invalid_probe or needs_probe:
            trace(
                "Validity Hardening Pass",
                f"hardening suite before final gate (invalid={invalid_probe} needs_revision={needs_probe})",
            )
            working = harden_suite_tests(working)
            reviewed, validity_summary, _a, _m = review_agent.review(
                test_cases=[t for t in working if not t.retired],
                project_id=project_id,
                fused=fused,
                force_deterministic=True,
            )
        final_review, obligations, modeled_pct = build_suite_review(
            project_id=project_id,
            tests=working,
            obligations=obligations,
            reviewed=reviewed,
            iteration=len(controller.history) or 1,
        )
        matches = final_review.obligation_coverage
        invalid_after, needs_after = _count_validity(reviewed)
        if controller.is_success(
            obligations=obligations,
            review=final_review,
            modeled_coverage=modeled_pct,
            invalid_count=invalid_after,
            needs_revision_count=needs_after,
        ):
            status = ConvergenceStatus.COMPLETE
            stop_reason = "all_mandatory_modeled_obligations_and_quality_gates_met"
    else:
        invalid_after, needs_after = 0, 0

    if status != ConvergenceStatus.COMPLETE and not stop_reason:
        stop_reason = "partial_after_refinement"

    remaining_findings = []
    if final_review:
        remaining_findings = [
            f"{f.finding_type.value}:{f.test_case_id}" for f in final_review.per_test_findings
        ] + [m.title for m in final_review.missing_scenario_findings]

    report = controller.build_report(
        status=status,
        stop_reason=stop_reason,
        initial_test_count=initial_count,
        final_test_count=len([t for t in working if not t.retired]),
        initial_coverage=initial_coverage,
        final_coverage=modeled_pct,
        obligations=obligations,
        invalid_before=invalid_before,
        invalid_after=invalid_after,
        needs_before=needs_before,
        needs_after=needs_after,
        totals=totals,
        remaining_findings=remaining_findings,
        blockers=list(final_review.blocking_findings) if final_review else [],
    )
    trace("Final Validation", f"status={status.value} coverage={modeled_pct}%")

    cats = category_coverage_summary(obligations)
    return RefinementLoopResult(
        tests=working,
        obligations=obligations,
        obligation_coverage=matches,
        category_coverage=cats,
        iteration_history=list(controller.history),
        convergence_report=report,
        final_review=final_review,
        reviewed_test_cases=reviewed,
        validity_summary=validity_summary,
    )
