"""Graph-aware QA Orchestrator — end-to-end agentic workflow."""

from __future__ import annotations

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
from app.models.schemas import AgentTraceStep, QACopilotRequest, QACopilotResponse, utc_now
from app.rag.retrieval import get_context_fusion, get_intent_classifier

logger = get_logger(__name__)


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

    def _trace(self, steps: list[AgentTraceStep], step: str, detail: str = "", status: str = "complete") -> None:
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
            self._trace(trace, f"{len(paths)} Graph Paths Discovered", f"max depth leaf paths from {root.name}")
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

        test_cases = []
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

        critic_notes: list[str] = []
        if request.include_critic and test_cases:
            critic_notes, test_cases = self.critic_agent.review(
                test_cases=test_cases,
                coverage=coverage,
                fused=fused,
            )
            self._trace(trace, "Critic Review Complete", f"{len(critic_notes)} notes")
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
        ]
        if not fused.semantic_context:
            assumptions.append("No vector documents matched; recommendations rely more on graph structure.")

        confidence = ConfidenceLevel.HIGH if fused.flow_paths and test_cases else ConfidenceLevel.MEDIUM
        if not graph.nodes:
            confidence = ConfidenceLevel.LOW

        narrative = self._narrative(
            root_name=root_name,
            risk=risk,
            branches=branches,
            paths=paths,
            coverage=coverage,
            test_cases=test_cases,
            critic_notes=critic_notes,
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
            graph_coverage=coverage.overall_coverage if coverage else None,
            critical_gaps=coverage.critical_gaps if coverage else [],
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
            },
            evidence=evidence,
            confidence=confidence,
            assumptions=assumptions,
            critic_notes=critic_notes,
            execution_trace=trace,
            narrative=narrative,
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
        lines = [
            f"QA RISK: {risk.value.upper()}",
            f"ROOT FEATURE: {root}",
            f"DISCOVERED BRANCHES: {len(branches)}",
            f"DISCOVERED GRAPH PATHS: {len(paths)}",
        ]
        if coverage:
            lines.append(f"GRAPH COVERAGE: {coverage.overall_coverage}%")
            if coverage.critical_gaps:
                lines.append("CRITICAL GAPS:")
                lines.extend(f"• {g}" for g in coverage.critical_gaps[:8])
        if test_cases:
            lines.append("RECOMMENDED TESTS:")
            lines.extend(f"• {tc.title}" for tc in test_cases[:12])
        return "\n".join(lines)


def get_orchestrator() -> QAOrchestrator:
    return QAOrchestrator()