"""Graph-aware QA Orchestrator — end-to-end agentic workflow."""

from __future__ import annotations

from app.agents.coverage_gaps import (
    build_coverage_gaps,
    build_coverage_snapshot,
    gaps_still_open,
    select_gaps_for_regeneration,
)
from app.agents.dedup import deduplicate_tests
from app.agents.specialists import (
    BugReportAgent,
    CoverageAgent,
    CriticAgent,
    ExploratoryAgent,
    ImpactAgent,
    RegressionAgent,
    RiskAgent,
    TestCaseAgent,
)
from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.graph.traversal import get_traversal
from app.models.enums import ConfidenceLevel, QAIntent, RiskLevel
from app.models.schemas import (
    AgentTraceStep,
    CoverageGap,
    QACopilotRequest,
    QACopilotResponse,
    TestCase,
    utc_now,
)
from app.rag.retrieval import get_context_fusion, get_intent_classifier

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

    def _trace(
        self, steps: list[AgentTraceStep], step: str, detail: str = "", status: str = "complete"
    ) -> None:
        steps.append(AgentTraceStep(step=step, status=status, detail=detail, timestamp=utc_now()))

    def run(self, request: QACopilotRequest) -> QACopilotResponse:
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
        if intent in (QAIntent.IMPACT_ANALYSIS, QAIntent.REGRESSION) or changed:
            target = changed or self._extract_changed_node(request.query) or (root_name or "")
            if target:
                impact = self.impact_agent.analyze(request.project_id, target)
                self._trace(
                    trace,
                    "Analyze Impact",
                    f"{impact.changed_node}: {len(impact.directly_impacted_nodes)} direct, "
                    f"risk={impact.risk_level.value}",
                )

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

        test_cases: list[TestCase] = []
        exploratory = []
        bugs = []
        regressions = []

        if intent in (QAIntent.TEST_GENERATION, QAIntent.GENERAL_QA, QAIntent.REQUIREMENTS_ANALYSIS):
            test_cases = self.test_agent.generate(request.query, fused, request.project_id)
            self._trace(trace, "Test Cases Generated", f"{len(test_cases)} cases from graph paths")
            exploratory = self.exploratory_agent.generate(fused)
            self._trace(trace, "Exploratory Missions Generated", str(len(exploratory)))
            regressions = self.regression_agent.recommend(fused, impact, changed)
            self._trace(trace, "Regression Recommendations", str(len(regressions)))

        if intent == QAIntent.EXPLORATORY:
            exploratory = self.exploratory_agent.generate(fused)
            self._trace(trace, "Exploratory Missions Generated", str(len(exploratory)))

        if intent == QAIntent.BUG_REPORT:
            bugs = self.bug_agent.generate(request.query, fused)
            self._trace(trace, "Bug Reports Generated", str(len(bugs)))

        if intent == QAIntent.REGRESSION:
            if not test_cases:
                test_cases = self.test_agent.generate(request.query, fused, request.project_id)
            regressions = self.regression_agent.recommend(fused, impact, changed)
            self._trace(trace, "Regression Recommendations", str(len(regressions)))

        if intent == QAIntent.IMPACT_ANALYSIS and impact:
            regressions = self.regression_agent.recommend(fused, impact, changed)
            self._trace(trace, "Regression Recommendations", str(len(regressions)))

        if intent == QAIntent.COVERAGE_GAP and coverage:
            self._trace(trace, "Coverage Gaps Identified", ", ".join(coverage.uncovered_branches[:6]))

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
                        gap, fused, request.project_id, test_cases + round_new
                    )
                    round_new.extend(generated)

                unique_new = deduplicate_tests(round_new, against=test_cases)
                # Also dedupe against project existing coverage catalog (title/path/steps)
                from app.agents.dedup import is_duplicate

                unique_new = [
                    tc
                    for tc in unique_new
                    if not is_duplicate(tc, fused.existing_coverage)
                ]

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

        final_critical = (
            [g.title for g in unresolved[:12]]
            if unresolved
            else (coverage.critical_gaps if coverage else [])
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

        return QACopilotResponse(
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
