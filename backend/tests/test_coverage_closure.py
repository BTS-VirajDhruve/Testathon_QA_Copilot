"""Tests for iterative coverage-closure: obligations, matching, review, loop."""

from __future__ import annotations

from app.agents.coverage_closure.convergence import (
    ConvergenceController,
    RefinementLimits,
)
from app.agents.coverage_closure.loop import run_refinement_loop
from app.agents.coverage_closure.matching import (
    match_test_to_obligation,
)
from app.agents.coverage_closure.obligations import build_coverage_obligations
from app.agents.coverage_closure.revision import (
    apply_revision_plan,
    create_test_for_obligation,
)
from app.agents.coverage_closure.suite_review import build_suite_review
from app.agents.test_review_automation import TestReviewAutomationAgent
from app.models.enums import (
    ConvergenceStatus,
    NodeType,
    ObligationStatus,
    ObligationType,
    Priority,
    SourceType,
)
from app.models.schemas import (
    CoverageObligation,
    FusedContext,
    GraphNode,
    Provenance,
    ReviewedTestCase,
    SystemFlowGraph,
    TestCase,
    TestValidityReview,
)


def _fused(**kwargs) -> FusedContext:
    base = dict(
        feature_context={"name": "Checkout"},
        flow_paths=[["Checkout", "Pay"]],
        graph_context=[
            {
                "path": ["Checkout", "Pay"],
                "is_failure_path": False,
                "includes_external_dependency": False,
            },
            {
                "path": ["Checkout", "Payment Gateway Timeout"],
                "is_failure_path": True,
                "includes_external_dependency": True,
            },
        ],
        semantic_context=[
            {
                "id": "REQ-1",
                "text": "User must authenticate before checkout",
                "source_reference": "REQ-1",
            },
            {
                "id": "REQ-PERF",
                "text": "Checkout performance under load should be improved for users",
                "source_reference": "REQ-PERF",
            },
        ],
        existing_coverage=[],
        historical_risks=[
            {
                "bug_id": "BUG-9",
                "title": "Double charge on retry",
                "graph_path": ["Checkout", "Pay"],
                "severity": "high",
                "project_id": "p1",
            }
        ],
    )
    base.update(kwargs)
    return FusedContext(**base)


def test_obligation_builder_paths_bugs_requirements_and_insufficient_perf():
    graph = SystemFlowGraph(
        project_id="p1",
        nodes=[
            GraphNode(
                id="n1",
                project_id="p1",
                name="Card validation",
                type=NodeType.VALIDATION,
                provenance=Provenance(source_type=SourceType.USER_INPUT),
            ),
            GraphNode(
                id="n2",
                project_id="p1",
                name="Admin",
                type=NodeType.ROLE,
                provenance=Provenance(source_type=SourceType.USER_INPUT),
            ),
        ],
        edges=[],
    )
    obls = build_coverage_obligations(
        project_id="p1",
        fused=_fused(),
        graph=graph,
        query="focus on security and negative scenarios",
        root_feature="Checkout",
    )
    types = {o.obligation_type for o in obls}
    assert ObligationType.POSITIVE_FLOW in types or ObligationType.FAILURE_PATH in types
    assert ObligationType.HISTORICAL_BUG_REGRESSION in types
    assert ObligationType.REQUIREMENT in types
    assert ObligationType.ROLE_PERMISSION in types or ObligationType.SECURITY in types
    assert ObligationType.INSUFFICIENT_EVIDENCE in types  # performance without target
    # irrelevant localization not forced
    assert ObligationType.LOCALIZATION not in types


def test_title_only_match_is_insufficient():
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.FAILURE_PATH,
        title="Payment Gateway Timeout failure",
        graph_path=["Checkout", "Payment Gateway Timeout"],
        mandatory=True,
    )
    tc = TestCase(
        test_case_id="TC1",
        title="Payment Gateway Timeout failure",
        steps=["do something"],
        expected_result="ok",
        graph_path=["Checkout", "Pay"],
        project_id="p1",
    )
    m = match_test_to_obligation(obl, tc)
    assert m.covered is False


def test_matching_behavior_and_path_covers_and_wrong_project_never():
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.POSITIVE_FLOW,
        title="Checkout Pay happy path",
        graph_path=["Checkout", "Pay"],
        mandatory=True,
    )
    good = TestCase(
        test_case_id="TC2",
        title="Complete checkout payment",
        steps=["Given cart", "When user pays", "Then order confirmed"],
        expected_result="Order status becomes Confirmed with visible confirmation id",
        graph_path=["Checkout", "Pay"],
        project_id="p1",
        obligation_ids=[obl.obligation_id],
    )
    assert match_test_to_obligation(obl, good).covered is True

    wrong = good.model_copy(update={"project_id": "other"})
    assert match_test_to_obligation(obl, wrong).covered is False
    assert "wrong_project" in match_test_to_obligation(obl, wrong).conflicting_elements


def test_invalid_test_does_not_count_as_covered():
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.POSITIVE_FLOW,
        title="Checkout Pay",
        graph_path=["Checkout", "Pay"],
        mandatory=True,
    )
    tc = TestCase(
        test_case_id="TC3",
        title="Checkout Pay",
        steps=["When pay"],
        expected_result="Order confirmed with status Confirmed",
        graph_path=["Checkout", "Pay"],
        project_id="p1",
    )
    m = match_test_to_obligation(obl, tc, validity="invalid")
    assert m.covered is False


def test_reviewer_findings_include_revision_instructions():
    tc = TestCase(
        test_case_id="TC4",
        title="x",
        steps=[],
        expected_result="",
        graph_path=["Checkout"],
        project_id="p1",
    )
    reviewed = [
        ReviewedTestCase(
            test_case=tc,
            validity_review=TestValidityReview(
                test_case_id="TC4",
                validity="needs_revision",
                validity_score=20,
                validity_reasons=["missing_expected_result"],
                quality_issues=["missing_expected_result", "missing_steps"],
                evidence_checked=[],
                requirement_support="unknown",
                duplicate_status="distinct",
                missing_information=[],
                correction_possible=True,
                corrections_applied=[],
                suggested_corrections=["Add a machine-observable expected result"],
            ),
            final_review_status="needs_revision",
        )
    ]
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.NEGATIVE_FLOW,
        title="Negative card validation",
        graph_path=["Checkout", "Card validation"],
        mandatory=True,
        priority=Priority.HIGH,
    )
    review, _, _ = build_suite_review(
        project_id="p1",
        tests=[tc],
        obligations=[obl],
        reviewed=reviewed,
        iteration=1,
    )
    assert review.per_test_findings
    assert review.per_test_findings[0].revision_instruction
    assert review.per_test_findings[0].acceptance_criteria
    assert review.missing_scenario_findings
    assert review.missing_scenario_findings[0].generation_instruction
    assert (
        review.revision_plan.revise_test_ids
        or review.revision_plan.create_for_obligation_ids
    )


def test_revision_preserves_logical_id_and_history():
    fused = _fused()
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.BOUNDARY,
        title="Boundary card length",
        graph_path=["Checkout", "Card validation"],
        mandatory=True,
    )
    weak = TestCase(
        test_case_id="TC_KEEP",
        title="x",
        steps=[],
        expected_result="",
        graph_path=["Checkout", "Card validation"],
        project_id="p1",
    )
    reviewed = [
        ReviewedTestCase(
            test_case=weak,
            validity_review=TestValidityReview(
                test_case_id="TC_KEEP",
                validity="needs_revision",
                validity_score=10,
                validity_reasons=["missing_steps"],
                quality_issues=["missing_steps"],
                evidence_checked=[],
                requirement_support="unknown",
                duplicate_status="distinct",
                missing_information=[],
                correction_possible=True,
                corrections_applied=[],
                suggested_corrections=["Add steps"],
            ),
            final_review_status="needs_revision",
        )
    ]
    review, obls, _ = build_suite_review(
        project_id="p1", tests=[weak], obligations=[obl], reviewed=reviewed, iteration=1
    )
    updated, stats = apply_revision_plan(
        tests=[weak],
        obligations=obls,
        review=review,
        fused=fused,
        project_id="p1",
        iteration=1,
        reviewed=reviewed,
    )
    kept = next(t for t in updated if t.test_case_id == "TC_KEEP")
    assert kept.test_case_id == "TC_KEEP"
    assert kept.previous_version_snapshot is not None
    assert kept.steps
    assert kept.expected_result
    assert stats["tests_revised"] >= 1


def test_insufficient_evidence_obligation_not_fabricated():
    fused = _fused()
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.INSUFFICIENT_EVIDENCE,
        title="Performance target missing",
        unsupported_reason="missing_performance_target",
        status=ObligationStatus.INSUFFICIENT_EVIDENCE,
        mandatory=False,
    )
    from app.models.schemas import RevisionPlan, TestSuiteReview

    review = TestSuiteReview(
        project_id="p1",
        revision_plan=RevisionPlan(create_for_obligation_ids=[obl.obligation_id]),
    )
    tests, stats = apply_revision_plan(
        tests=[],
        obligations=[obl],
        review=review,
        fused=fused,
        project_id="p1",
        iteration=1,
    )
    assert stats["tests_created"] == 0
    assert tests == []


def test_loop_respects_max_iterations_and_stops():
    fused = _fused()
    agent = TestReviewAutomationAgent()
    initial = [
        TestCase(
            test_case_id="TC_A",
            title="Pay happy path",
            steps=["Given cart", "When pay", "Then confirmed"],
            expected_result="Order Confirmed with id visible",
            graph_path=["Checkout", "Pay"],
            project_id="p1",
            category="functional",
        )
    ]
    limits = RefinementLimits(
        max_iterations=2,
        max_tests=50,
        min_improvement_percent=1.0,
        stagnation_rounds=2,
        max_llm_calls=0,
        require_all_mandatory=True,
        require_zero_invalid=True,
        require_zero_needs_revision=True,
    )
    result = run_refinement_loop(
        project_id="p1",
        tests=initial,
        fused=fused,
        graph=None,
        query="generate exhaustive negative scenarios",
        root_feature="Checkout",
        review_agent=agent,
        limits=limits,
        force_deterministic_review=True,
    )
    assert result.convergence_report is not None
    assert result.convergence_report.iterations_completed <= 2
    assert result.convergence_report.status in (
        ConvergenceStatus.COMPLETE,
        ConvergenceStatus.PARTIAL,
        ConvergenceStatus.LIMIT_REACHED,
        ConvergenceStatus.STAGNATED,
    )
    # No infinite loop
    assert len(result.iteration_history) <= 2


def test_success_requires_more_than_coverage_alone():
    limits = RefinementLimits(max_iterations=3)
    ctrl = ConvergenceController(limits=limits)
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.POSITIVE_FLOW,
        title="x",
        graph_path=["A"],
        mandatory=True,
        status=ObligationStatus.COVERED,
    )
    from app.models.enums import GeneratorRevisionMode, ReviewFindingType
    from app.models.schemas import TestReviewFinding, TestSuiteReview

    review = TestSuiteReview(
        project_id="p1",
        per_test_findings=[
            TestReviewFinding(
                test_case_id="TC1",
                severity=Priority.HIGH,
                finding_type=ReviewFindingType.INVALID_TEST,
                revision_instruction="fix me",
                required_action=GeneratorRevisionMode.REVISE,
                acceptance_criteria=["ok"],
            )
        ],
    )
    assert (
        ctrl.is_success(
            obligations=[obl],
            review=review,
            modeled_coverage=100.0,
            invalid_count=1,
            needs_revision_count=0,
        )
        is False
    )


def test_create_test_for_obligation_sets_link():
    fused = _fused()
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.RECOVERY,
        title="Recover after gateway timeout",
        graph_path=["Checkout", "Payment Gateway Timeout"],
        mandatory=True,
    )
    tc = create_test_for_obligation(obl, fused, "p1", iteration=2)
    assert obl.obligation_id in tc.obligation_ids
    assert tc.generation_round == 2
    assert (
        "status" in (tc.expected_result or "").lower()
        or "message" in (tc.expected_result or "").lower()
    )


def test_create_and_revise_pass_deterministic_validity():
    from app.agents.dedup import normalize_text
    from app.agents.test_review_automation import (
        apply_validity_hardening,
        decide_validity,
        deterministic_validity_findings,
    )
    from app.models.enums import TestValidity

    fused = _fused()
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.NEGATIVE_FLOW,
        title="Reject invalid card",
        graph_path=["Checkout", "Card validation"],
        mandatory=True,
        priority=Priority.HIGH,
    )
    created = create_test_for_obligation(obl, fused, "p1", iteration=1)
    node_names = {
        normalize_text(n)
        for n in ["Checkout", "Pay", "Payment Gateway Timeout", "Card validation"]
        if normalize_text(n)
    }
    findings = deterministic_validity_findings(
        created,
        project_id="p1",
        valid_node_names=node_names,
        evidence_ids=set(),
        project_evidence_ids=set(),
        seen_ids=set(),
        peers=[],
    )
    validity, _ = decide_validity(created, findings)
    assert validity == TestValidity.VALID

    weak = TestCase(
        test_case_id="TC_WEAK",
        title="x",
        steps=["do it"],
        expected_result="it works",
        graph_path=["Checkout", "Pay"],
        project_id="p1",
    )
    hardened, applied = apply_validity_hardening(weak)
    assert applied
    findings2 = deterministic_validity_findings(
        hardened,
        project_id="p1",
        valid_node_names=node_names,
        evidence_ids=set(),
        project_evidence_ids=set(),
        seen_ids=set(),
        peers=[],
    )
    validity2, _ = decide_validity(hardened, findings2)
    assert validity2 == TestValidity.VALID


def test_generation_volume_settings_defaults():
    from app.core.config import get_settings

    s = get_settings()
    assert s.test_generation_min_cases >= 25
    assert s.test_generation_max_per_gap >= 3
    assert s.test_generation_max_gaps_per_round >= 8
    assert s.test_refinement_max_iterations >= 6


def test_revision_expected_result_uses_observable_tokens():
    fused = _fused()
    weak = TestCase(
        test_case_id="TC_KEEP",
        title="Checkout pay path",
        steps=["Given cart ready", "When user pays", "Then done"],
        expected_result="Observable outcome confirming payment",
        graph_path=["Checkout", "Pay"],
        project_id="p1",
    )
    reviewed = [
        ReviewedTestCase(
            test_case=weak,
            validity_review=TestValidityReview(
                test_case_id="TC_KEEP",
                validity="needs_revision",
                validity_score=40,
                validity_reasons=["Expected result may not be observable"],
                quality_issues=["expected_result_may_not_be_observable"],
                evidence_checked=[],
                requirement_support="unknown",
                duplicate_status="distinct",
                missing_information=[],
                correction_possible=True,
                corrections_applied=[],
                suggested_corrections=["Add observable assertion"],
            ),
            final_review_status="needs_revision",
        )
    ]
    obl = CoverageObligation(
        project_id="p1",
        obligation_type=ObligationType.POSITIVE_FLOW,
        title="Pay succeeds",
        graph_path=["Checkout", "Pay"],
        mandatory=True,
    )
    review, obls, _ = build_suite_review(
        project_id="p1", tests=[weak], obligations=[obl], reviewed=reviewed, iteration=1
    )
    updated, _ = apply_revision_plan(
        tests=[weak],
        obligations=obls,
        review=review,
        fused=fused,
        project_id="p1",
        iteration=1,
        reviewed=reviewed,
    )
    kept = next(t for t in updated if t.test_case_id == "TC_KEEP")
    er = (kept.expected_result or "").lower()
    assert any(
        tok in er
        for tok in ("status", "error", "message", "visible", "returned", "created")
    )
