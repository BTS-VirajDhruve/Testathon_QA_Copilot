"""Graph-aware QA Orchestrator — end-to-end agentic workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.bdd import build_generated_artifacts
from app.agents.coverage_gaps import (
    build_coverage_gaps,
    build_coverage_snapshot,
    gaps_still_open,
    select_gaps_for_regeneration,
)
from app.agents.dedup import deduplicate_tests, dedupe_strings
from app.agents.specialists import (
    BugReportAgent,
    CoverageAgent,
    CriticAgent,
    ExploratoryAgent,
    ImpactAgent,
    RegressionAgent,
    RiskAgent,
    TestCaseAgent,
    basic_test_quality_failed,
    run_premium_reviewer_pass,
)
from app.agents.test_review_automation import TestReviewAutomationAgent
from app.agents.coverage_closure import RefinementLimits, run_refinement_loop
from app.core.config import get_settings
from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.graph.traversal import get_traversal
from app.models.enums import (
    ConfidenceLevel,
    ConvergenceStatus,
    LLMTaskType,
    QAIntent,
    RiskLevel,
    TestOutputFormat,
    TestValidity,
)
from app.models.schemas import (
    AgentTraceStep,
    AutomationCapabilityProfile,
    AutomationSummary,
    BDDScenario,
    CoverageGap,
    ConvergenceReport,
    CoverageObligation,
    GeneratedTestArtifact,
    ObligationCoverageMatch,
    QACopilotRequest,
    QACopilotResponse,
    RefinementIterationSnapshot,
    ReviewedTestCase,
    SectionStatus,
    TestCase,
    TestSuiteReview,
    ValiditySummary,
    utc_now,
)
from app.rag.retrieval import get_context_fusion, get_intent_classifier
from app.services.model_router import (
    assess_requirement_complexity,
    build_routing_context_from_fused,
    decide_reviewer,
    get_model_router,
)

logger = get_logger(__name__)

# Hard ceiling — never allow unbounded critic regeneration loops
MAX_REGENERATION_ROUNDS_HARD = 2


class QAOrchestrator:
    def __init__(self) -> None:
        self.store = get_graph_store()
        self.traversal = get_traversal()
        self.classifier = get_intent_classifier()
        self.fusion = get_context_fusion()
        self.test_agent = TestCaseAgent()
        self.exploratory_agent = ExploratoryAgent()
        self.bug_agent = BugReportAgent()
        self.regression_agent = RegressionAgent()
        self.impact_agent = ImpactAgent()
        self.coverage_agent = CoverageAgent()
        self.critic_agent = CriticAgent()
        self.risk_agent = RiskAgent()
        self.test_review_agent = TestReviewAutomationAgent()
        self._progress_cb: Callable[[str, str, dict[str, Any]], None] | None = None
        self._progress_started = None
        self._progress_completed: list[str] = []

    def _trace(
        self, steps: list[AgentTraceStep], step: str, detail: str = "", status: str = "complete"
    ) -> None:
        steps.append(AgentTraceStep(step=step, status=status, detail=detail, timestamp=utc_now()))
        if status in {"complete", "error", "skipped"} and step not in self._progress_completed:
            self._progress_completed.append(step)
        self._emit_progress(step, detail, status)

    def _begin_stage(self, step: str, detail: str = "") -> None:
        """Emit a running-stage progress event without appending a completed trace step."""
        self._emit_progress(step, detail, "running")

    def _emit_progress(self, step: str, detail: str, status: str) -> None:
        if not self._progress_cb:
            return
        elapsed_ms = 0
        if self._progress_started is not None:
            elapsed_ms = int((utc_now() - self._progress_started).total_seconds() * 1000)
        try:
            self._progress_cb(
                step,
                detail,
                {
                    "status": status,
                    "completed_stages": list(self._progress_completed),
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception:  # noqa: BLE001 — progress must never break analysis
            logger.debug("Analysis progress callback failed", exc_info=True)

    def run(
        self,
        request: QACopilotRequest,
        on_progress: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> QACopilotResponse:
        self._progress_cb = on_progress
        self._progress_started = utc_now()
        self._progress_completed = []
        try:
            return self._run_inner(request)
        finally:
            self._progress_cb = None
            self._progress_started = None
            self._progress_completed = []

    def _run_inner(self, request: QACopilotRequest) -> QACopilotResponse:
        trace: list[AgentTraceStep] = []
        project = self.store.get_project(request.project_id)
        if not project:
            self._trace(trace, "Identify Project", f"Project {request.project_id} not found", "error")
            return QACopilotResponse(
                project_id=request.project_id,
                query=request.query,
                intent=QAIntent.GENERAL_QA.value,
                narrative="Project not found. Create a project and system flow graph first.",
                execution_trace=trace,
                confidence=ConfidenceLevel.LOW,
                assumptions=["Valid project_id is required."],
            )

        self._trace(trace, "Identify Project", f"{project.get('name')} ({request.project_id})")
        self._begin_stage("Reading system-flow graph", "Loading project flow graph")

        from app.services.openai_service import get_openai_service

        openai = get_openai_service()
        openai.clear_routing_events()

        graph = self.traversal.load_flow(request.project_id)
        self._trace(
            trace,
            "User Flow Graph Loaded",
            f"{len(graph.nodes)} nodes, {len(graph.edges)} edges, v{graph.version}",
        )

        root = self.traversal.resolve_root(request.project_id, request.root_feature)
        root_name = root.name if root else request.root_feature
        if root:
            self._trace(trace, "Root Feature Identified", root.name)
            branches = self.traversal.branches(request.project_id, root.id)
            self._trace(trace, f"{len(branches)} Branches Found", ", ".join(b.name for b in branches))
            paths = self.traversal.discover_paths(request.project_id, root.id)
            self._trace(
                trace,
                f"{len(paths)} Graph Paths Discovered",
                f"max depth leaf paths from {root.name}",
            )
        else:
            branches, paths = [], []
            self._trace(trace, "Root Feature Identified", "No root feature in graph", "skipped")

        intent = self.classifier.classify(request.query)
        self._begin_stage("Retrieving project knowledge", "Planning Graph RAG + Vector RAG retrieval")
        self._trace(trace, "Classify Intent", intent.value)

        plan, fused = self.fusion.fuse(
            request.project_id,
            request.query,
            intent,
            root_feature=request.root_feature or root_name,
        )
        self._trace(trace, "Plan Retrieval", plan.reason)
        if plan.use_user_flow_graph:
            self._trace(trace, "Traverse User Flow Graph", f"{len(fused.flow_paths)} paths in fused context")
        if plan.use_graph_rag:
            self._trace(trace, "Traverse Graph RAG", f"{len(fused.graph_context)} graph context items")
        if plan.use_vector_rag:
            self._trace(
                trace,
                f"Vector RAG Retrieved {len(fused.semantic_context)} Documents",
                ", ".join(
                    str(s.get("source_reference") or s.get("id")) for s in fused.semantic_context[:5]
                ),
            )
        if plan.use_existing_tests:
            self._trace(trace, f"{len(fused.existing_coverage)} Existing Test Cases Found")
        if plan.use_historical_bugs:
            self._trace(trace, f"{len(fused.historical_risks)} Historical Bugs Found")

        impact = None
        changed = request.changed_node
        wants_complete = self._wants_complete_analysis(request, intent)
        if (
            intent in (QAIntent.IMPACT_ANALYSIS, QAIntent.REGRESSION)
            or changed
            or wants_complete
        ):
            target = changed or self._extract_changed_node(request.query) or (root_name or "")
            if target:
                impact = self.impact_agent.analyze(request.project_id, target)
                self._trace(
                    trace,
                    "Analyze Impact",
                    f"{impact.changed_node}: {len(impact.directly_impacted_nodes)} direct, "
                    f"risk={impact.risk_level.value}",
                )
            elif wants_complete:
                self._trace(trace, "Analyze Impact", "No root/changed node available", "skipped")

        coverage = None
        if intent in (
            QAIntent.COVERAGE_GAP,
            QAIntent.TEST_GENERATION,
            QAIntent.GENERAL_QA,
            QAIntent.REGRESSION,
        ) or "coverage" in request.query.lower():
            coverage = self.coverage_agent.analyze(request.project_id, root_name)
            self._trace(
                trace,
                "Analyze Graph Coverage Gaps",
                f"overall={coverage.overall_coverage}% gaps={len(coverage.critical_gaps)}",
            )

        self._trace(trace, "Analyze Risk", "Computing risk from history + gaps + external deps")
        risk = self.risk_agent.assess(fused, coverage)
        self._trace(trace, "Risk Analysis Complete", risk.value)

        router = get_model_router()
        primary_task = router.intent_to_task_type(intent.value) or LLMTaskType.TEST_CASE_GENERATION
        user_requested_review = any(
            k in request.query.lower()
            for k in ("expert review", "deep review", "premium review", "senior review")
        )
        routing_ctx = build_routing_context_from_fused(
            project_id=request.project_id,
            task_type=primary_task,
            query=request.query,
            user_intent=intent.value,
            fused=fused,
            user_requested_review=user_requested_review,
        )
        complexity = assess_requirement_complexity(routing_ctx)
        routing_ctx.requirement_complexity = complexity.category
        selection = router.resolve_model(primary_task, routing_ctx)
        self._trace(
            trace,
            "Model Routing",
            f"task={primary_task.value} base={selection.base_model} selected={selection.selected_model}",
        )
        self._trace(
            trace,
            "Complexity Assessment",
            f"{complexity.category.value} (score={complexity.score}; {', '.join(complexity.signals[:5]) or 'none'})",
        )
        if selection.escalated:
            self._trace(
                trace,
                "Model Escalation",
                f"{selection.base_model} → {selection.selected_model}: {selection.escalation_reason}",
            )

        test_cases: list[TestCase] = []
        exploratory = []
        bugs = []
        regressions = []
        section_status: dict[str, SectionStatus] = {
            "test_cases": SectionStatus(status="skipped"),
            "test_case_generation": SectionStatus(status="skipped"),
            "exploratory_scenarios": SectionStatus(status="skipped"),
            "bug_reports": SectionStatus(status="skipped"),
            "regression_recommendations": SectionStatus(status="skipped"),
            "coverage": SectionStatus(status="skipped"),
            "test_review_automation": SectionStatus(status="skipped"),
            "test_validity_review": SectionStatus(status="skipped"),
            "automation_feasibility_review": SectionStatus(status="skipped"),
        }
        output_format = request.test_output_format or TestOutputFormat.STANDARD
        self._trace(
            trace,
            "Test Format Selection",
            f"requested_format={output_format.value}",
        )
        if coverage is not None:
            section_status["coverage"] = SectionStatus(
                status="success" if coverage.critical_gaps or coverage.overall_coverage is not None else "empty",
                count=len(coverage.critical_gaps or []),
            )

        requested = {o.strip().lower() for o in (request.requested_outputs or []) if o}
        review_only = bool(requested) and requested <= {
            "test_automation_review",
            "automation_review",
            "test_review",
            "test_validity_review",
            "automation_feasibility_review",
        }
        want_test_review = (
            request.include_test_review
            and (
                wants_complete
                or review_only
                or bool(
                    requested
                    & {
                        "test_automation_review",
                        "automation_review",
                        "test_review",
                        "test_validity_review",
                        "automation_feasibility_review",
                        "test_cases",
                        "tests",
                    }
                )
                or intent
                in (
                    QAIntent.TEST_GENERATION,
                    QAIntent.GENERAL_QA,
                    QAIntent.REQUIREMENTS_ANALYSIS,
                    QAIntent.REGRESSION,
                    QAIntent.COVERAGE_GAP,
                )
            )
        )
        want_tests = wants_complete or bool(
            requested & {"test_cases", "tests"}
        ) or intent in (
            QAIntent.TEST_GENERATION,
            QAIntent.GENERAL_QA,
            QAIntent.REQUIREMENTS_ANALYSIS,
            QAIntent.REGRESSION,
            QAIntent.COVERAGE_GAP,
        )
        want_exploratory = wants_complete or bool(
            requested & {"exploratory_scenarios", "exploratory"}
        ) or intent in (
            QAIntent.TEST_GENERATION,
            QAIntent.GENERAL_QA,
            QAIntent.REQUIREMENTS_ANALYSIS,
            QAIntent.EXPLORATORY,
        )
        want_bugs = wants_complete or bool(
            requested & {"bug_reports", "bugs"}
        ) or intent == QAIntent.BUG_REPORT
        want_regression = wants_complete or bool(
            requested & {"regression_recommendations", "regression"}
        ) or intent in (
            QAIntent.TEST_GENERATION,
            QAIntent.GENERAL_QA,
            QAIntent.REQUIREMENTS_ANALYSIS,
            QAIntent.REGRESSION,
            QAIntent.IMPACT_ANALYSIS,
        )
        # Automation-only: reuse persisted tests; do not regenerate the suite
        if review_only:
            want_tests = False
            want_exploratory = False
            want_bugs = False
            want_regression = False
            persisted = [
                tc
                for tc in self.store.test_cases.values()
                if tc.get("project_id") == request.project_id
            ]
            loaded: list[TestCase] = []
            for raw in persisted:
                try:
                    loaded.append(TestCase.model_validate(raw))
                except Exception:  # noqa: BLE001
                    continue
            if not loaded:
                latest = self.store.get_latest_analysis(request.project_id) or {}
                for raw in latest.get("test_cases") or []:
                    try:
                        loaded.append(TestCase.model_validate(raw))
                    except Exception:  # noqa: BLE001
                        continue
            test_cases = loaded
            if test_cases:
                section_status["test_cases"] = SectionStatus(
                    status="success", count=len(test_cases)
                )
                self._trace(
                    trace,
                    "Reuse Persisted Tests",
                    f"{len(test_cases)} tests loaded for automation review only",
                )
            else:
                section_status["test_cases"] = SectionStatus(status="empty", count=0)
                self._trace(
                    trace,
                    "Reuse Persisted Tests",
                    "No persisted tests available for review",
                    "skipped",
                )

        if want_tests and intent in (
            QAIntent.TEST_GENERATION,
            QAIntent.GENERAL_QA,
            QAIntent.REQUIREMENTS_ANALYSIS,
            QAIntent.REGRESSION,
        ):
            try:
                self._begin_stage("Generating test cases", "Running TestCaseAgent")
                test_cases = self.test_agent.generate(
                    request.query,
                    fused,
                    request.project_id,
                    routing_context=routing_ctx,
                    user_intent=intent.value,
                )
                methods = {tc.generation_method for tc in test_cases if tc.generation_method}
                self._trace(
                    trace,
                    "Initial Test Generation",
                    f"{len(test_cases)} cases · methods={sorted(m for m in methods if m)}",
                )
                evidence_count = sum(len(tc.evidence or []) for tc in test_cases)
                self._trace(
                    trace,
                    "Evidence Validation",
                    f"{evidence_count} evidence refs across {len(test_cases)} tests (fabricated IDs sanitized)",
                )
                section_status["test_cases"] = SectionStatus(
                    status="success" if test_cases else "empty",
                    count=len(test_cases),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("test_generation_failed", error=str(exc))
                section_status["test_cases"] = SectionStatus(
                    status="failed", count=0, error=str(exc)[:240]
                )
                self._trace(trace, "Initial Test Generation", str(exc)[:160], "error")

        if want_exploratory and intent != QAIntent.BUG_REPORT:
            try:
                if intent == QAIntent.EXPLORATORY or want_exploratory:
                    exploratory = self.exploratory_agent.generate(fused)
                    self._trace(trace, "Exploratory Missions Generated", str(len(exploratory)))
                    section_status["exploratory_scenarios"] = SectionStatus(
                        status="success" if exploratory else "empty",
                        count=len(exploratory),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("exploratory_generation_failed", error=str(exc))
                section_status["exploratory_scenarios"] = SectionStatus(
                    status="failed", count=0, error=str(exc)[:240]
                )
                self._trace(trace, "Exploratory Missions Generated", str(exc)[:160], "error")

        if want_bugs:
            try:
                bugs = self.bug_agent.generate(request.query, fused, coverage=coverage)
                self._trace(trace, "Bug Report Generation", str(len(bugs)))
                section_status["bug_reports"] = SectionStatus(
                    status="success" if bugs else "empty",
                    count=len(bugs),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("bug_report_generation_failed", error=str(exc))
                section_status["bug_reports"] = SectionStatus(
                    status="failed", count=0, error=str(exc)[:240]
                )
                self._trace(trace, "Bug Report Generation", str(exc)[:160], "error")

        if want_regression:
            try:
                regressions = self.regression_agent.recommend(
                    fused,
                    impact,
                    changed,
                    coverage=coverage,
                    generated_tests=test_cases,
                )
                self._trace(trace, "Regression Recommendation Generation", str(len(regressions)))
                section_status["regression_recommendations"] = SectionStatus(
                    status="success" if regressions else "empty",
                    count=len(regressions),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("regression_generation_failed", error=str(exc))
                section_status["regression_recommendations"] = SectionStatus(
                    status="failed", count=0, error=str(exc)[:240]
                )
                self._trace(trace, "Regression Recommendation Generation", str(exc)[:160], "error")

        if intent == QAIntent.COVERAGE_GAP and coverage:
            self._trace(trace, "Coverage Gaps Identified", ", ".join(coverage.uncovered_branches[:6]))
            if not test_cases and ("generate" in request.query.lower() and "test" in request.query.lower()):
                try:
                    test_cases = self.test_agent.generate(
                        request.query,
                        fused,
                        request.project_id,
                        routing_context=routing_ctx,
                        user_intent=intent.value,
                    )
                    self._trace(
                        trace,
                        "Initial Test Generation",
                        f"{len(test_cases)} cases (coverage_gap intent with generate request)",
                    )
                    section_status["test_cases"] = SectionStatus(
                        status="success" if test_cases else "empty",
                        count=len(test_cases),
                    )
                except Exception as exc:  # noqa: BLE001
                    section_status["test_cases"] = SectionStatus(
                        status="failed", count=0, error=str(exc)[:240]
                    )

        # Snapshot of initial generation (before critic-targeted regeneration)
        initial_test_cases = [tc.model_copy(deep=True) for tc in test_cases]

        critic_notes: list[str] = []
        if request.include_critic and test_cases:
            # Notes-only critic in orchestrator — targeted regen is the Phase-4 loop below
            critic_notes, test_cases = self.critic_agent.review(
                test_cases=test_cases,
                coverage=coverage,
                fused=fused,
                add_gap_tests=False,
                project_id=request.project_id,
            )
            self._trace(trace, "Critic Review Complete", f"{len(critic_notes)} notes")

        # Recompute coverage against initial generated set for before-snapshot
        if test_cases and (
            request.enable_targeted_regeneration or intent != QAIntent.COVERAGE_GAP
        ):
            coverage = self.coverage_agent.analyze(request.project_id, root_name)

        coverage_before = None
        coverage_after = None
        selected_gaps: list[CoverageGap] = []
        targeted_tests: list[TestCase] = []
        unresolved: list[CoverageGap] = []
        regeneration_rounds = 0
        duplicates_removed = 0

        run_regen = (
            bool(request.enable_targeted_regeneration)
            and request.include_critic
            and bool(test_cases)
            and intent
            in (
                QAIntent.TEST_GENERATION,
                QAIntent.GENERAL_QA,
                QAIntent.REQUIREMENTS_ANALYSIS,
                QAIntent.REGRESSION,
                QAIntent.COVERAGE_GAP,
            )
        )

        if run_regen:
            all_gaps = build_coverage_gaps(
                coverage=coverage, fused=fused, test_cases=test_cases
            )
            coverage_before = build_coverage_snapshot(
                coverage=coverage, fused=fused, test_cases=test_cases, gaps=all_gaps
            )
            self._trace(
                trace,
                "Coverage Gap Analysis",
                f"{len(all_gaps)} structured gaps; "
                f"path_coverage={coverage_before.coverage_percentage}% "
                f"({coverage_before.covered_paths}/{coverage_before.total_paths})",
            )

            max_rounds = max(0, min(int(request.max_regeneration_rounds), MAX_REGENERATION_ROUNDS_HARD))
            max_gaps = max(0, int(request.max_gaps_per_round))

            for round_idx in range(1, max_rounds + 1):
                selected = select_gaps_for_regeneration(all_gaps, max_gaps=max_gaps)
                # Skip gaps already closed in prior round
                closed_ids = {tc.closes_gap_id for tc in targeted_tests if tc.closes_gap_id}
                selected = [g for g in selected if g.gap_id not in closed_ids]
                if not selected:
                    self._trace(
                        trace,
                        f"Targeted Regeneration Round {round_idx}",
                        "No high-priority gaps selected — skipping regeneration",
                        "skipped",
                    )
                    break

                selected_gaps = selected if round_idx == 1 else selected_gaps + [
                    g for g in selected if g.gap_id not in {x.gap_id for x in selected_gaps}
                ]
                self._trace(
                    trace,
                    "Gap Prioritization",
                    f"selected {len(selected)}/{len(all_gaps)} high-priority gaps "
                    f"(round {round_idx}/{max_rounds})",
                )

                round_new: list[TestCase] = []
                for gap in selected:
                    generated = self.test_agent.generate_for_gap(
                        gap,
                        fused,
                        request.project_id,
                        test_cases + round_new,
                        routing_context=routing_ctx.model_copy(
                            update={
                                "task_type": LLMTaskType.TARGETED_TEST_GENERATION,
                                "regeneration_round": round_idx,
                            }
                        ),
                        user_intent=intent.value,
                    )
                    round_new.extend(generated)

                unique_new = deduplicate_tests(round_new, against=test_cases)
                from app.agents.dedup import is_duplicate

                unique_new = [
                    tc
                    for tc in unique_new
                    if not is_duplicate(tc, fused.existing_coverage)
                ]
                round_dupes = max(0, len(round_new) - len(unique_new))
                duplicates_removed += round_dupes
                self._trace(
                    trace,
                    "Deduplication",
                    f"kept {len(unique_new)} / {len(round_new)} targeted tests "
                    f"(removed {round_dupes} duplicates)",
                )

                if not unique_new:
                    self._trace(
                        trace,
                        f"Targeted Regeneration Round {round_idx}",
                        "All generated targeted tests were duplicates — stopping",
                        "skipped",
                    )
                    break

                test_cases = test_cases + unique_new
                targeted_tests.extend(unique_new)
                regeneration_rounds = round_idx
                self._trace(
                    trace,
                    f"Targeted Regeneration Round {round_idx}",
                    f"added {len(unique_new)} critic-targeted tests",
                )

                # Refresh coverage engine view after persist from generate_for_gap
                coverage = self.coverage_agent.analyze(request.project_id, root_name)
                all_gaps = build_coverage_gaps(
                    coverage=coverage, fused=fused, test_cases=test_cases
                )
                # Default policy: only round 1 unless explicitly configured for 2
                # and high-priority gaps remain. Never auto-loop further.
                remaining_high = select_gaps_for_regeneration(all_gaps, max_gaps=max_gaps)
                if round_idx >= max_rounds or not remaining_high:
                    break

            coverage_after = build_coverage_snapshot(
                coverage=coverage, fused=fused, test_cases=test_cases
            )
            unresolved = gaps_still_open(
                coverage_after.gaps or all_gaps,
                test_cases,
            )
            self._trace(
                trace,
                "Final Coverage Analysis",
                f"before={coverage_before.coverage_percentage}% "
                f"after={coverage_after.coverage_percentage}% "
                f"unresolved={len(unresolved)} rounds={regeneration_rounds}",
            )
            self._trace(trace, "Improve Output", f"{len(test_cases)} final test cases")
        elif test_cases:
            # Still expose before snapshot when regeneration disabled
            all_gaps = build_coverage_gaps(
                coverage=coverage, fused=fused, test_cases=test_cases
            )
            coverage_before = build_coverage_snapshot(
                coverage=coverage, fused=fused, test_cases=test_cases, gaps=all_gaps
            )
            coverage_after = coverage_before
            unresolved = [
                g
                for g in all_gaps
                if (g.priority.value if hasattr(g.priority, "value") else str(g.priority))
                in ("critical", "high")
            ]
            self._trace(trace, "Improve Output", f"{len(test_cases)} final test cases")

        evidence = ["User-provided system flow graph"]
        evidence.extend(
            str(s.get("source_reference") or s.get("id")) for s in fused.semantic_context[:5]
        )
        evidence.extend(str(b.get("bug_id") or b.get("title")) for b in fused.historical_risks[:5])
        evidence = [e for e in evidence if e]

        assumptions = [
            "User-provided flow graph is the primary structural source of truth.",
            "Inferred relationships are marked and not treated as confirmed architecture.",
            "Coverage scores compare graph nodes to existing test path/title tokens.",
            "Targeted regeneration is bounded (default 1 round, hard max 2) and only for high/critical gaps.",
        ]
        if not fused.semantic_context:
            assumptions.append(
                "No vector documents matched; recommendations rely more on graph structure."
            )

        confidence = ConfidenceLevel.HIGH if fused.flow_paths and test_cases else ConfidenceLevel.MEDIUM
        if not graph.nodes:
            confidence = ConfidenceLevel.LOW

        # Prefer after-coverage for top-level graph_coverage when available
        final_coverage_pct = None
        if coverage_after is not None:
            final_coverage_pct = coverage_after.overall_coverage
        elif coverage is not None:
            final_coverage_pct = coverage.overall_coverage

        final_critical = dedupe_strings(
            [g.title for g in unresolved[:12]]
            if unresolved
            else (coverage.critical_gaps if coverage else [])
        )

        from app.rag.vector_store import get_vector_store
        from app.core.config import get_settings

        methods = {tc.generation_method for tc in test_cases if tc.generation_method}
        if methods == {"llm"} or (methods <= {"llm", "critic"} and "llm" in methods and "deterministic_fallback" not in methods):
            generation_backend = "openai" if openai.available else "deterministic_fallback"
        elif "deterministic_fallback" in methods and "llm" not in methods:
            generation_backend = "deterministic_fallback"
        elif methods:
            generation_backend = "mixed"
        else:
            generation_backend = (
                "openai" if openai.available else "deterministic_fallback"
            )

        # Conditional high-tier reviewer (max 1) — distinct from CriticAgent
        quality_failed, quality_issues = basic_test_quality_failed(test_cases)
        reviewer_decision = decide_reviewer(routing_ctx, quality_failed=quality_failed)
        self._trace(
            trace,
            "Reviewer Decision",
            (
                f"required={reviewer_decision.required}"
                + (f" · {', '.join(reviewer_decision.reasons)}" if reviewer_decision.reasons else "")
            ),
            "complete" if reviewer_decision.required else "skipped",
        )
        if reviewer_decision.required and test_cases:
            review_notes, test_cases = run_premium_reviewer_pass(
                test_cases=test_cases,
                fused=fused,
                project_id=request.project_id,
                routing_context=routing_ctx,
                quality_issues=quality_issues,
            )
            if review_notes:
                critic_notes.extend(review_notes)
                self._trace(trace, "Reviewer Pass", f"{len(review_notes)} notes")

        # --- Iterative coverage-closure refinement (additive, bounded) ---
        settings = get_settings()
        refinement_enabled = (
            settings.test_refinement_enabled
            if request.enable_test_refinement is None
            else bool(request.enable_test_refinement)
        )
        coverage_obligations: list[CoverageObligation] = []
        obligation_coverage_matches: list[ObligationCoverageMatch] = []
        category_coverage_list: list = []
        iteration_history: list[RefinementIterationSnapshot] = []
        convergence_report: ConvergenceReport | None = None
        final_suite_review: TestSuiteReview | None = None
        refinement_ran = False

        reviewed_test_cases: list[ReviewedTestCase] = []
        validity_summary: ValiditySummary | None = None
        automation_summary: AutomationSummary | None = None
        valid_tests: list[TestCase] = []
        invalid_tests: list[TestCase] = []
        needs_revision_tests: list[TestCase] = []
        insufficient_evidence_tests: list[TestCase] = []
        automation_candidates: list[TestCase] = []
        manual_tests: list[TestCase] = []
        hybrid_tests: list[TestCase] = []
        conditional_automation_tests: list[TestCase] = []
        not_evaluated_tests: list[TestCase] = []

        if (
            refinement_enabled
            and want_test_review
            and test_cases
            and intent
            in (
                QAIntent.TEST_GENERATION,
                QAIntent.GENERAL_QA,
                QAIntent.REQUIREMENTS_ANALYSIS,
                QAIntent.REGRESSION,
                QAIntent.COVERAGE_GAP,
            )
        ):
            prior_hist: list[RefinementIterationSnapshot] = []
            prior_obls: list[CoverageObligation] | None = None
            if request.resume_refinement:
                prev = self.store.get_latest_analysis(request.project_id) or {}
                if isinstance(prev, dict) and prev.get("project_id") == request.project_id:
                    prior_hist = [
                        RefinementIterationSnapshot.model_validate(x)
                        for x in (prev.get("iteration_history") or [])
                    ]
                    prior_obls = [
                        CoverageObligation.model_validate(x)
                        for x in (prev.get("coverage_obligations") or [])
                    ] or None
                    if prev.get("test_cases"):
                        # Prefer continuing from persisted suite when resuming
                        try:
                            test_cases = [TestCase.model_validate(t) for t in prev["test_cases"]]
                        except Exception:
                            pass

            def _emit(step: str, detail: str, status: str = "complete") -> None:
                self._trace(trace, step, detail, status)

            limits = RefinementLimits.from_settings(
                max_iterations_override=request.test_refinement_max_iterations
            )
            try:
                refine = run_refinement_loop(
                    project_id=request.project_id,
                    tests=test_cases,
                    fused=fused,
                    graph=graph,
                    query=request.query,
                    root_feature=root_name,
                    review_agent=self.test_review_agent,
                    limits=limits,
                    existing_obligations=prior_obls,
                    prior_history=prior_hist,
                    emit_trace=_emit,
                    force_deterministic_review=not openai.available,
                )
                refinement_ran = True
                test_cases = refine.tests
                coverage_obligations = refine.obligations
                obligation_coverage_matches = refine.obligation_coverage
                category_coverage_list = refine.category_coverage
                iteration_history = refine.iteration_history
                convergence_report = refine.convergence_report
                final_suite_review = refine.final_review
                reviewed_test_cases = refine.reviewed_test_cases
                validity_summary = refine.validity_summary
                section_status["test_refinement"] = SectionStatus(
                    status=(
                        "success"
                        if convergence_report
                        and convergence_report.status == ConvergenceStatus.COMPLETE
                        else "partial_success"
                    ),
                    count=len([t for t in test_cases if not t.retired]),
                    iterations=convergence_report.iterations_completed if convergence_report else 0,
                    modeled_coverage=(
                        convergence_report.final_modeled_coverage if convergence_report else None
                    ),
                    invalid=convergence_report.invalid_after if convergence_report else None,
                    needs_revision=(
                        convergence_report.needs_revision_after if convergence_report else None
                    ),
                    remaining_mandatory_obligations=(
                        len(convergence_report.remaining_obligations) if convergence_report else None
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self._trace(
                    trace,
                    "Coverage Closure Failed",
                    str(exc),
                    "error",
                )
                section_status["test_refinement"] = SectionStatus(
                    status="failed",
                    error=str(exc),
                )

        if want_test_review and test_cases and not refinement_ran:
            self._trace(
                trace,
                "Load Final Test Suite",
                f"Loaded {len(test_cases)} tests for validity-first review",
            )
            try:
                profile_raw = self.store.get_automation_capability_profile(request.project_id)
                profile = (
                    AutomationCapabilityProfile.model_validate(profile_raw)
                    if profile_raw
                    else None
                )
                overrides = self.store.list_test_review_overrides(request.project_id)
                existing_ids = {
                    str(t.get("test_case_id"))
                    for t in fused.existing_coverage
                    if t.get("test_case_id")
                }
                targeted_ids = {tc.test_case_id for tc in targeted_tests}
                reviewed_test_cases, validity_summary, automation_summary, review_meta = (
                    self.test_review_agent.review(
                        test_cases=test_cases,
                        project_id=request.project_id,
                        fused=fused,
                        targeted_ids=targeted_ids,
                        existing_ids=existing_ids,
                        profile=profile,
                        overrides=overrides,
                        automation_strategy=request.automation_strategy,
                        routing_context=routing_ctx,
                    )
                )
                # Enrich suite with safe corrections without dropping originals
                corrected_by_id = {
                    r.test_case.test_case_id: r.test_case for r in reviewed_test_cases
                }
                test_cases = [
                    corrected_by_id.get(tc.test_case_id, tc) for tc in test_cases
                ]
                # Silent validity hardening for soft needs_revision before user-facing suite
                from app.agents.coverage_closure.revision import harden_suite_tests

                soft_ids = {
                    item.test_case.test_case_id
                    for item in reviewed_test_cases
                    if item.test_case
                    and item.validity_review.validity
                    in (
                        TestValidity.NEEDS_REVISION.value,
                        TestValidity.INVALID.value,
                    )
                }
                if soft_ids:
                    hardened = harden_suite_tests(test_cases)
                    reviewed_test_cases, validity_summary, automation_summary, review_meta = (
                        self.test_review_agent.review(
                            test_cases=hardened,
                            project_id=request.project_id,
                            fused=fused,
                            targeted_ids=targeted_ids,
                            existing_ids=existing_ids,
                            profile=profile,
                            overrides=overrides,
                            automation_strategy=request.automation_strategy,
                            routing_context=routing_ctx,
                            force_deterministic=True,
                        )
                    )
                    corrected_by_id = {
                        r.test_case.test_case_id: r.test_case for r in reviewed_test_cases
                    }
                    test_cases = [
                        corrected_by_id.get(tc.test_case_id, tc) for tc in hardened
                    ]
                    self._trace(
                        trace,
                        "Validity Hardening Pass",
                        f"re-reviewed {len(soft_ids)} soft-invalid tests",
                    )
                valid_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.validity_review.validity == "valid"
                ]
                invalid_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.validity_review.validity == "invalid"
                ]
                needs_revision_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.validity_review.validity == "needs_revision"
                ]
                insufficient_evidence_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.validity_review.validity == "insufficient_evidence"
                ]
                # Primary user-facing suite is valid-only
                test_cases = [
                    t for t in valid_tests if not getattr(t, "retired", False)
                ]
                automation_candidates = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "automate"
                ]
                conditional_automation_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability
                    == "automate_with_conditions"
                ]
                hybrid_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "hybrid"
                ]
                manual_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "manual"
                ]
                not_evaluated_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "not_evaluated"
                ]
                self._trace(
                    trace,
                    "Deterministic Validity Pre-check",
                    f"input={review_meta.get('input_count', 0)} reviewed={review_meta.get('reviewed_count', 0)}",
                )
                self._trace(
                    trace,
                    "Semantic Test Validity Review",
                    (
                        f"valid={review_meta.get('valid_count', 0)} "
                        f"invalid={review_meta.get('invalid_count', 0)} "
                        f"needs_revision={review_meta.get('revision_count', 0)} "
                        f"fallback={review_meta.get('fallback_used')} "
                        f"model={review_meta.get('actual_model') or review_meta.get('selected_model') or 'deterministic'}"
                    ),
                )
                self._trace(
                    trace,
                    "Valid Test Filtering",
                    (
                        f"valid={len(valid_tests)} invalid={len(invalid_tests)} "
                        f"needs_revision={len(needs_revision_tests)} insufficient={len(insufficient_evidence_tests)}"
                    ),
                )
                self._trace(
                    trace,
                    "Automation Feasibility Pre-check",
                    f"input={len(valid_tests)} valid tests only",
                )
                self._trace(
                    trace,
                    "Automation Feasibility Review",
                    (
                        f"evaluated={automation_summary.valid_tests_evaluated if automation_summary else 0} "
                        f"automate={automation_summary.automate} "
                        f"conditional={automation_summary.automate_with_conditions} "
                        f"hybrid={automation_summary.hybrid} "
                        f"manual={automation_summary.manual} "
                        f"not_ready={automation_summary.not_ready_for_automation}"
                    ),
                )
                self._trace(
                    trace,
                    "Automation Layer Recommendation",
                    f"high_priority={automation_summary.high_priority_automation if automation_summary else 0}",
                )
                self._trace(
                    trace,
                    "Review Summary Aggregation",
                    (
                        f"valid={validity_summary.valid if validity_summary else 0} "
                        f"invalid={validity_summary.invalid if validity_summary else 0} "
                        f"needs_revision={validity_summary.needs_revision if validity_summary else 0}"
                    ),
                )
                persisted_reviews = [
                    item.model_dump(mode="json") for item in reviewed_test_cases
                ]
                self.store.bulk_set_test_reviews(request.project_id, persisted_reviews)
                self._trace(
                    trace,
                    "Review Persistence",
                    f"persisted={len(persisted_reviews)} review records",
                )
                section_status["test_review_automation"] = SectionStatus(
                    status="success" if reviewed_test_cases else "empty",
                    count=len(reviewed_test_cases),
                )
                section_status["test_validity_review"] = SectionStatus(
                    status="success" if reviewed_test_cases else "empty",
                    count=len(reviewed_test_cases),
                )
                section_status["automation_feasibility_review"] = SectionStatus(
                    status="success" if valid_tests else "empty",
                    count=len(valid_tests),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("test_review_automation_failed", error=str(exc))
                # Partial failure: keep original test suite visible
                section_status["test_review_automation"] = SectionStatus(
                    status="failed",
                    count=0,
                    error=str(exc)[:240],
                )
                self._trace(
                    trace,
                    "Semantic Test Validity Review",
                    str(exc)[:160],
                    "error",
                )
        elif refinement_ran and want_test_review and reviewed_test_cases:
            active_reviewed = [
                r
                for r in reviewed_test_cases
                if r.test_case and not getattr(r.test_case, "retired", False)
            ]
            valid_tests = [
                item.test_case
                for item in active_reviewed
                if item.validity_review.validity == TestValidity.VALID.value
            ]
            invalid_tests = [
                item.test_case
                for item in active_reviewed
                if item.validity_review.validity == TestValidity.INVALID.value
            ]
            needs_revision_tests = [
                item.test_case
                for item in active_reviewed
                if item.validity_review.validity == TestValidity.NEEDS_REVISION.value
            ]
            insufficient_evidence_tests = [
                item.test_case
                for item in active_reviewed
                if item.validity_review.validity == TestValidity.INSUFFICIENT_EVIDENCE.value
            ]
            # Primary user-facing suite is valid-only after silent refinement
            test_cases = [t for t in valid_tests if not getattr(t, "retired", False)]
            self._trace(
                trace,
                "Valid Test Filtering",
                f"showing {len(test_cases)} valid tests "
                f"(hidden needs_revision={len(needs_revision_tests)} invalid={len(invalid_tests)})",
            )
            try:
                profile_raw = self.store.get_automation_capability_profile(request.project_id)
                profile = (
                    AutomationCapabilityProfile.model_validate(profile_raw)
                    if profile_raw
                    else None
                )
                overrides = self.store.list_test_review_overrides(request.project_id)
                _rev, _vs, automation_summary, _meta = self.test_review_agent.review(
                    test_cases=valid_tests
                    or [t for t in test_cases if not getattr(t, "retired", False)],
                    project_id=request.project_id,
                    fused=fused,
                    profile=profile,
                    overrides=overrides,
                    automation_strategy=request.automation_strategy,
                    routing_context=routing_ctx,
                    force_deterministic=True,
                )
                auto_by_id = {
                    r.test_case.test_case_id: r
                    for r in _rev
                    if r.test_case and r.automation_review
                }
                merged: list[ReviewedTestCase] = []
                for r in reviewed_test_cases:
                    tid = r.test_case.test_case_id if r.test_case else ""
                    other = auto_by_id.get(tid)
                    if other and other.automation_review:
                        merged.append(
                            r.model_copy(update={"automation_review": other.automation_review})
                        )
                    else:
                        merged.append(r)
                reviewed_test_cases = merged
                automation_candidates = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "automate"
                    and item.test_case
                ]
                conditional_automation_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability
                    == "automate_with_conditions"
                    and item.test_case
                ]
                hybrid_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "hybrid"
                    and item.test_case
                ]
                manual_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "manual"
                    and item.test_case
                ]
                not_evaluated_tests = [
                    item.test_case
                    for item in reviewed_test_cases
                    if item.automation_review
                    and item.automation_review.automation_suitability == "not_evaluated"
                    and item.test_case
                ]
                self.store.bulk_set_test_reviews(
                    request.project_id,
                    [item.model_dump(mode="json") for item in reviewed_test_cases],
                )
                self._trace(
                    trace,
                    "Automation Feasibility Review",
                    f"evaluated={automation_summary.valid_tests_evaluated if automation_summary else 0}",
                )
                section_status["test_review_automation"] = SectionStatus(
                    status="success" if reviewed_test_cases else "empty",
                    count=len(reviewed_test_cases),
                )
                section_status["test_validity_review"] = SectionStatus(
                    status="success" if reviewed_test_cases else "empty",
                    count=len(reviewed_test_cases),
                )
                section_status["automation_feasibility_review"] = SectionStatus(
                    status="success" if valid_tests else "empty",
                    count=len(valid_tests),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("post_refinement_automation_failed", error=str(exc))
                section_status["automation_feasibility_review"] = SectionStatus(
                    status="failed", error=str(exc)[:240]
                )
        elif want_test_review:
            section_status["test_review_automation"] = SectionStatus(status="empty", count=0)
            section_status["test_validity_review"] = SectionStatus(status="empty", count=0)
            section_status["automation_feasibility_review"] = SectionStatus(status="empty", count=0)
            self._trace(
                trace,
                "Load Final Test Suite",
                "No tests available to review",
                "skipped",
            )

        settings = get_settings()
        last_route = openai.last_routing or {}
        model_routing = {
            "task_type": primary_task.value,
            "base_model": selection.base_model,
            "selected_model": selection.selected_model,
            "actual_model_used": last_route.get("actual_model_used") or openai.last_chat_model,
            "escalated": selection.escalated,
            "escalation_reason": selection.escalation_reason,
            "fallback_used": bool(last_route.get("fallback_used")),
            "reviewer_triggered": reviewer_decision.required,
            "reviewer_reasons": reviewer_decision.reasons,
            "complexity": complexity.category.value,
            "complexity_score": complexity.score,
            "routing_policy_version": selection.routing_policy_version,
            "events": list(openai.routing_events[-8:]),
        }
        runtime_diagnostics = {
            **openai.diagnostics(),
            **get_vector_store().diagnostics(),
            "graph_store_mode": "neo4j+json" if settings.neo4j_enabled else "json",
            "generation_backend": generation_backend,
            "duplicates_removed": duplicates_removed,
            "model_routing": model_routing,
        }
        if generation_backend == "deterministic_fallback":
            assumptions.append(
                "OpenAI was unavailable or unused for this run; deterministic generation produced the tests."
            )

        # Format rendering: TestCase remains canonical; BDD is derived when requested
        generated_artifacts: list[GeneratedTestArtifact] = []
        bdd_scenarios: list[BDDScenario] = []
        if test_cases:
            self._trace(
                trace,
                "Canonical Test Generation",
                f"{len(test_cases)} logical tests available for format={output_format.value}",
            )
            if output_format in {TestOutputFormat.STANDARD, TestOutputFormat.BOTH}:
                self._trace(
                    trace,
                    "Standard Test Rendering",
                    f"{len(test_cases)} standard representations",
                )
            if output_format in {TestOutputFormat.BDD, TestOutputFormat.BOTH}:
                valid_nodes: set[str] = set()
                for path in fused.flow_paths or []:
                    for name in path:
                        from app.agents.dedup import normalize_text as _norm

                        if _norm(name):
                            valid_nodes.add(_norm(name))
                evidence_ids = {
                    str(ev.source_id)
                    for tc in test_cases
                    for ev in (tc.evidence or [])
                    if ev.source_id
                }
                try:
                    generated_artifacts, bdd_scenarios, bdd_meta = build_generated_artifacts(
                        test_cases,
                        output_format=output_format,
                        feature_name=root_name,
                        valid_node_names=valid_nodes,
                        evidence_ids=evidence_ids,
                    )
                    self._trace(
                        trace,
                        "BDD Scenario Rendering",
                        (
                            f"bdd={bdd_meta.get('bdd_count', 0)} "
                            f"ok={bdd_meta.get('converted_ok', 0)} "
                            f"needs_revision={bdd_meta.get('needs_revision', 0)}"
                        ),
                    )
                    self._trace(
                        trace,
                        "BDD Validation",
                        (
                            f"errors={len(bdd_meta.get('validation_errors') or [])} "
                            f"format={output_format.value}"
                        ),
                    )
                    status = "success"
                    if bdd_meta.get("needs_revision") and bdd_meta.get("converted_ok"):
                        status = "partial_success"
                    elif bdd_meta.get("bdd_count", 0) == 0 and output_format != TestOutputFormat.STANDARD:
                        status = "failed" if test_cases else "empty"
                    section_status["test_case_generation"] = SectionStatus(
                        status=status if bdd_scenarios or output_format == TestOutputFormat.STANDARD else "partial_success",
                        count=len(test_cases),
                        requested_format=output_format.value,
                        logical_test_count=len(test_cases),
                        standard_count=bdd_meta.get("standard_count"),
                        bdd_count=bdd_meta.get("bdd_count"),
                        validation_errors=list(bdd_meta.get("validation_errors") or [])[:20],
                    )
                    # Persist BDD side-car on matching test records without overwriting human edits
                    for artifact in generated_artifacts:
                        if not artifact.bdd_scenario or not artifact.source_test_id:
                            continue
                        existing = None
                        key = self.store.artifact_key(request.project_id, artifact.source_test_id)
                        existing = self.store.test_cases.get(key)
                        if existing and existing.get("human_edited"):
                            continue
                        payload = {
                            **(existing or {}),
                            "project_id": request.project_id,
                            "test_case_id": artifact.source_test_id,
                            "bdd_scenario": artifact.bdd_scenario.model_dump(mode="json"),
                            "logical_test_id": artifact.logical_test_id,
                            "test_output_format": output_format.value,
                        }
                        if artifact.standard_test_case and not existing:
                            payload.update(artifact.standard_test_case.model_dump(mode="json"))
                        self.store.upsert_test_case(request.project_id, payload)
                    self.store.persist()
                    self._trace(
                        trace,
                        "Test Format Persistence",
                        f"artifacts={len(generated_artifacts)} bdd={len(bdd_scenarios)}",
                    )
                    # Critic-style BDD notes (additive)
                    for sc in bdd_scenarios:
                        if sc.conversion_status == "needs_revision":
                            critic_notes.append(
                                f"BDD needs revision for '{sc.scenario_name}': "
                                + ", ".join((sc.conversion_notes or [])[:3])
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("bdd_rendering_failed", error=str(exc))
                    if output_format == TestOutputFormat.BOTH:
                        section_status["test_case_generation"] = SectionStatus(
                            status="partial_success",
                            count=len(test_cases),
                            requested_format=output_format.value,
                            logical_test_count=len(test_cases),
                            standard_count=len(test_cases),
                            bdd_count=0,
                            error=str(exc)[:240],
                            validation_errors=[str(exc)[:240]],
                        )
                        assumptions.append(
                            "BDD rendering failed; standard test cases were preserved."
                        )
                    else:
                        section_status["test_case_generation"] = SectionStatus(
                            status="failed",
                            count=len(test_cases),
                            requested_format=output_format.value,
                            logical_test_count=len(test_cases),
                            standard_count=0,
                            bdd_count=0,
                            error=str(exc)[:240],
                        )
                    self._trace(trace, "BDD Scenario Rendering", str(exc)[:160], "error")
            else:
                generated_artifacts, _, std_meta = build_generated_artifacts(
                    test_cases,
                    output_format=TestOutputFormat.STANDARD,
                    feature_name=root_name,
                )
                section_status["test_case_generation"] = SectionStatus(
                    status="success" if test_cases else "empty",
                    count=len(test_cases),
                    requested_format=output_format.value,
                    logical_test_count=len(test_cases),
                    standard_count=len(test_cases),
                    bdd_count=0,
                )
                self._trace(
                    trace,
                    "Test Format Persistence",
                    f"artifacts={len(generated_artifacts)} format=standard",
                )
            if output_format == TestOutputFormat.BDD and regeneration_rounds:
                self._trace(
                    trace,
                    "Targeted BDD Generation",
                    f"targeted={len(targeted_tests)} preserved_format=bdd",
                )

        narrative = self._narrative(
            root_name=root_name,
            risk=risk,
            branches=branches,
            paths=paths,
            coverage=coverage,
            test_cases=test_cases,
            critic_notes=critic_notes,
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            regeneration_rounds=regeneration_rounds,
            targeted_count=len(targeted_tests),
            unresolved=unresolved,
        )
        self._trace(trace, "Final Response Ready", f"confidence={confidence.value}")

        from app.agents.taxonomy import (
            build_feature_specifications,
            build_user_story,
            category_counts,
            classification_summary,
            ensure_test_classified,
        )

        classified_for_summary = [ensure_test_classified(tc) for tc in test_cases]
        _feature_specs = build_feature_specifications(
            classified_for_summary,
            feature_fallback=root_name,
        )
        _feature_story = build_user_story(root_name or "Feature") if root_name else None
        if _feature_specs and _feature_specs[0].user_story:
            _feature_story = _feature_specs[0].user_story
        _cat_counts = category_counts(classified_for_summary)
        _class_summary = classification_summary(classified_for_summary)

        # Prefer classified copies on the response
        test_cases = classified_for_summary

        response = QACopilotResponse(
            project_id=request.project_id,
            query=request.query,
            intent=intent.value,
            risk_level=risk,
            root_feature=root_name,
            discovered_branches=[b.name for b in branches],
            discovered_graph_paths=[p.node_names for p in paths],
            graph_coverage=final_coverage_pct,
            critical_gaps=final_critical,
            historical_bug_patterns=[
                str(b.get("title") or b.get("bug_id")) for b in fused.historical_risks[:10]
            ],
            test_cases=test_cases,
            exploratory_missions=exploratory,
            bug_reports=bugs,
            regression_recommendations=regressions,
            impact_analysis=impact,
            coverage=coverage,
            retrieval_plan=plan,
            fused_context_summary={
                "feature": fused.feature_context.get("name"),
                "flow_paths": len(fused.flow_paths),
                "semantic_hits": len(fused.semantic_context),
                "existing_tests": len(fused.existing_coverage),
                "historical_bugs": len(fused.historical_risks),
                "initial_tests": len(initial_test_cases),
                "targeted_tests": len(targeted_tests),
                "regeneration_rounds": regeneration_rounds,
                "graph_context_items": len(fused.graph_context),
                "vector_hits": len(fused.semantic_context),
            },
            evidence=evidence,
            confidence=confidence,
            assumptions=assumptions,
            critic_notes=critic_notes,
            execution_trace=trace,
            narrative=narrative,
            initial_test_cases=initial_test_cases,
            selected_coverage_gaps=selected_gaps,
            targeted_test_cases=targeted_tests,
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            regeneration_rounds=regeneration_rounds,
            unresolved_gaps=unresolved,
            duplicates_removed=duplicates_removed,
            generation_backend=generation_backend,
            runtime_diagnostics=runtime_diagnostics,
            model_routing=model_routing,
            section_status=section_status,
            reviewed_test_cases=reviewed_test_cases,
            valid_tests=valid_tests,
            invalid_tests=invalid_tests,
            needs_revision_tests=needs_revision_tests,
            insufficient_evidence_tests=insufficient_evidence_tests,
            automation_candidates=automation_candidates,
            manual_tests=manual_tests,
            hybrid_tests=hybrid_tests,
            conditional_automation_tests=conditional_automation_tests,
            not_evaluated_tests=not_evaluated_tests,
            validity_summary=validity_summary,
            automation_summary=automation_summary,
            test_output_format=output_format.value,
            bdd_scenarios=bdd_scenarios,
            generated_test_artifacts=generated_artifacts,
            feature_test_specifications=_feature_specs,
            feature_story=_feature_story,
            test_classification_summary=_class_summary,
            category_counts=_cat_counts,
            coverage_obligations=coverage_obligations,
            obligation_coverage=obligation_coverage_matches,
            category_coverage=category_coverage_list,
            iteration_history=iteration_history,
            convergence_report=convergence_report,
            final_suite_review=final_suite_review,
        )
        try:
            self.store.set_latest_analysis(
                request.project_id,
                response.model_dump(mode="json"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("latest_analysis_persist_failed", error=str(exc))
        return response

    def _wants_complete_analysis(self, request: QACopilotRequest, intent: QAIntent) -> bool:
        """True when the user asked for a full multi-section QA analysis."""
        requested = {o.strip().lower() for o in (request.requested_outputs or []) if o}
        complete_markers = {
            "test_cases",
            "exploratory_scenarios",
            "bug_reports",
            "regression_recommendations",
            "coverage",
            "evidence",
        }
        if requested and len(requested & complete_markers) >= 3:
            return True
        q = (request.query or "").lower()
        if any(
            phrase in q
            for phrase in (
                "complete qa",
                "comprehensive",
                "end-to-end",
                "end to end",
                "full analysis",
                "full qa",
                "multi-section",
                "bug report",
                "regression",
                "coverage gap",
                "generate test",
            )
        ):
            return True
        return intent in (
            QAIntent.TEST_GENERATION,
            QAIntent.GENERAL_QA,
            QAIntent.REQUIREMENTS_ANALYSIS,
        )

    def _extract_changed_node(self, query: str) -> str | None:
        import re

        patterns = [
            r"if\s+(.+?)\s+changes?",
            r"(.+?)\s+changed",
            r"impact(?:ed)?(?:\s+components)?(?:\s+if)?\s+(.+?)(?:\?|$)",
        ]
        for pat in patterns:
            m = re.search(pat, query, re.I)
            if m:
                return m.group(1).strip(" .?")
        return None

    def _narrative(self, **kwargs) -> str:
        root = kwargs.get("root_name") or "Feature"
        risk = kwargs.get("risk") or RiskLevel.MEDIUM
        branches = kwargs.get("branches") or []
        paths = kwargs.get("paths") or []
        coverage = kwargs.get("coverage")
        test_cases = kwargs.get("test_cases") or []
        coverage_before = kwargs.get("coverage_before")
        coverage_after = kwargs.get("coverage_after")
        regeneration_rounds = kwargs.get("regeneration_rounds") or 0
        targeted_count = kwargs.get("targeted_count") or 0
        unresolved = kwargs.get("unresolved") or []
        lines = [
            f"QA RISK: {risk.value.upper()}",
            f"ROOT FEATURE: {root}",
            f"DISCOVERED BRANCHES: {len(branches)}",
            f"DISCOVERED GRAPH PATHS: {len(paths)}",
        ]
        if coverage_before is not None:
            lines.append(
                f"INITIAL COVERAGE: {coverage_before.coverage_percentage}% "
                f"({coverage_before.covered_paths}/{coverage_before.total_paths} paths)"
            )
        if coverage:
            lines.append(f"GRAPH COVERAGE: {coverage.overall_coverage}%")
            if coverage.critical_gaps:
                lines.append("CRITICAL GAPS:")
                lines.extend(f"• {g}" for g in coverage.critical_gaps[:8])
        if regeneration_rounds:
            lines.append(f"TARGETED REGENERATION ROUNDS: {regeneration_rounds}")
            lines.append(f"CRITIC-TARGETED TESTS ADDED: {targeted_count}")
        if coverage_after is not None:
            lines.append(
                f"FINAL COVERAGE: {coverage_after.coverage_percentage}% "
                f"({coverage_after.covered_paths}/{coverage_after.total_paths} paths)"
            )
        if unresolved:
            lines.append(f"UNRESOLVED GAPS: {len(unresolved)}")
            lines.extend(f"• {g.title}" for g in unresolved[:6])
        if test_cases:
            lines.append("RECOMMENDED TESTS:")
            lines.extend(f"• {tc.title}" for tc in test_cases[:12])
        return "\n".join(lines)


def get_orchestrator() -> QAOrchestrator:
    return QAOrchestrator()
