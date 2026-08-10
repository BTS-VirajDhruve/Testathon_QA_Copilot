"""Retrieval planner and hybrid context fusion."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.graph.traversal import get_traversal
from app.models.enums import LLMTaskType, QAIntent
from app.models.schemas import FusedContext, RetrievalPlan
from app.rag.vector_store import get_vector_store
from app.services.model_router import ModelRoutingContext
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)


class RetrievalPlanner:
    def plan(
        self, query: str, intent: QAIntent, *, has_flow_graph: bool
    ) -> RetrievalPlan:
        q = query.lower()
        use_flow = has_flow_graph and (
            intent
            in {
                QAIntent.TEST_GENERATION,
                QAIntent.EXPLORATORY,
                QAIntent.REGRESSION,
                QAIntent.COVERAGE_GAP,
                QAIntent.IMPACT_ANALYSIS,
                QAIntent.GENERAL_QA,
                QAIntent.BUG_REPORT,
                QAIntent.REQUIREMENTS_ANALYSIS,
            }
            or any(
                k in q
                for k in (
                    "feature",
                    "flow",
                    "path",
                    "branch",
                    "journey",
                    "module",
                    "workflow",
                    "screen",
                    "page",
                )
            )
        )
        use_vector = (
            intent
            in {
                QAIntent.TEST_GENERATION,
                QAIntent.REQUIREMENTS_ANALYSIS,
                QAIntent.DOCUMENTATION,
                QAIntent.GENERAL_QA,
                QAIntent.EXPLORATORY,
            }
            or "requirement" in q
            or "policy" in q
            or "security" in q
        )
        use_graph = has_flow_graph or intent in {
            QAIntent.IMPACT_ANALYSIS,
            QAIntent.REGRESSION,
            QAIntent.COVERAGE_GAP,
        }
        use_tests = intent != QAIntent.DOCUMENTATION
        use_bugs = intent in {
            QAIntent.TEST_GENERATION,
            QAIntent.REGRESSION,
            QAIntent.IMPACT_ANALYSIS,
            QAIntent.DEFECT_PATTERN,
            QAIntent.BUG_REPORT,
            QAIntent.EXPLORATORY,
            QAIntent.COVERAGE_GAP,
            QAIntent.GENERAL_QA,
        }
        use_external = (
            "latest" in q or "cve" in q or "owasp" in q or "external research" in q
        )

        reason_parts = []
        if use_flow:
            reason_parts.append(
                "branch-level flow understanding from the user-provided system flow graph"
            )
        if use_graph:
            reason_parts.append("Graph RAG traversal of dependencies and relationships")
        if use_vector:
            reason_parts.append("semantic product context via Vector RAG")
        if use_tests:
            reason_parts.append("existing coverage")
        if use_bugs:
            reason_parts.append("historical defect patterns")
        if use_external:
            reason_parts.append("optional external research")

        return RetrievalPlan(
            use_user_flow_graph=use_flow,
            use_vector_rag=use_vector,
            use_graph_rag=use_graph,
            use_existing_tests=use_tests,
            use_historical_bugs=use_bugs,
            use_external_search=use_external,
            reason="The request requires " + ", ".join(reason_parts) + "."
            if reason_parts
            else "Minimal retrieval for this intent.",
        )


class IntentClassifier:
    KEYWORDS: list[tuple[QAIntent, tuple[str, ...]]] = [
        (QAIntent.EXPLORATORY, ("exploratory", "charter", "mission", "break the")),
        (QAIntent.BUG_REPORT, ("bug report", "defect report", "file a bug")),
        (
            QAIntent.REGRESSION,
            ("regression", "recommend tests after", "what to retest"),
        ),
        (
            QAIntent.IMPACT_ANALYSIS,
            ("impact", "impacted", "what components", "changed"),
        ),
        # Prefer generation when the user explicitly asks to generate tests,
        # even if the same query also mentions coverage gaps (hackathon demo journey).
        (
            QAIntent.TEST_GENERATION,
            (
                "generate comprehensive test",
                "generate tests",
                "generate test",
                "test case",
                "qa coverage",
                "test suite",
                "targeted tests",
            ),
        ),
        (
            QAIntent.COVERAGE_GAP,
            ("coverage gap", "uncovered", "missing tests", "coverage analysis"),
        ),
        (QAIntent.DEFECT_PATTERN, ("historical bug", "defect pattern", "recurring")),
        (QAIntent.DOCUMENTATION, ("qa documentation", "write docs", "test plan doc")),
        (
            QAIntent.REQUIREMENTS_ANALYSIS,
            ("analyze requirements", "requirement analysis"),
        ),
    ]

    def classify(self, query: str) -> QAIntent:
        openai = get_openai_service()
        if openai.available:
            data = openai.chat_json(
                "Classify the QA intent. Return JSON {intent, confidence}. "
                f"Allowed intents: {[i.value for i in QAIntent]}. "
                "If the user asks to generate tests and also identify coverage gaps, "
                "prefer test_generation.",
                query,
                task_type=LLMTaskType.INTENT_CLASSIFICATION,
                routing_context=ModelRoutingContext(
                    task_type=LLMTaskType.INTENT_CLASSIFICATION,
                    query=query,
                ),
            )
            try:
                return QAIntent(data.get("intent", "general_qa"))
            except ValueError:
                pass
        lower = query.lower()
        # Compound demo/product query: generate tests + coverage gaps → generation path
        asks_generate = "generate" in lower and "test" in lower
        asks_gaps = any(
            k in lower for k in ("coverage gap", "uncovered", "targeted test")
        )
        if asks_generate and asks_gaps:
            return QAIntent.TEST_GENERATION
        for intent, keys in self.KEYWORDS:
            if any(k in lower for k in keys):
                return intent
        return QAIntent.GENERAL_QA


class ContextFusionLayer:
    def __init__(self) -> None:
        self.store = get_graph_store()
        self.traversal = get_traversal()
        self.vectors = get_vector_store()
        self.planner = RetrievalPlanner()

    def fuse(
        self,
        project_id: str,
        query: str,
        intent: QAIntent,
        *,
        root_feature: str | None = None,
        plan: RetrievalPlan | None = None,
    ) -> tuple[RetrievalPlan, FusedContext]:
        graph = self.traversal.load_flow(project_id)
        has_flow = bool(graph.nodes)
        plan = plan or self.planner.plan(query, intent, has_flow_graph=has_flow)

        feature_context: dict[str, Any] = {}
        flow_paths: list[list[str]] = []
        graph_context: list[dict[str, Any]] = []
        semantic_context: list[dict[str, Any]] = []
        existing_coverage: list[dict[str, Any]] = []
        historical_risks: list[dict[str, Any]] = []
        external_context: list[dict[str, Any]] = []

        root = None
        if plan.use_user_flow_graph or plan.use_graph_rag:
            root = self.traversal.resolve_root(project_id, root_feature)
            if root:
                feature_context = {
                    "id": root.id,
                    "name": root.name,
                    "type": root.type.value,
                    "description": root.description,
                    "critical": root.is_critical,
                }
                branches = self.traversal.branches(project_id, root.id)
                feature_context["branches"] = [b.name for b in branches]
                paths = self.traversal.discover_paths(project_id, root.id)
                flow_paths = [p.node_names for p in paths]
                for path in paths[:20]:
                    graph_context.append(
                        {
                            "path": path.node_names,
                            "node_ids": path.node_ids,
                            "path_id": "→".join(path.node_ids)
                            if path.node_ids
                            else None,
                            "is_failure_path": path.is_failure_path,
                            "includes_external_dependency": path.includes_external_dependency,
                            "relationships": path.relationships,
                        }
                    )
                for edge, neighbor in self.store.neighbors(root.id, direction="both")[
                    :30
                ]:
                    graph_context.append(
                        {
                            "node_id": neighbor.id,
                            "entity": neighbor.name,
                            "type": neighbor.type.value,
                            "description": neighbor.description,
                            "inferred": neighbor.provenance.inferred,
                            "source_type": neighbor.provenance.source_type.value,
                            "edge_id": edge.id,
                            "relationship": str(edge.relationship),
                        }
                    )

        if plan.use_vector_rag:
            semantic_context = self.vectors.search(project_id, query, top_k=8)

        if plan.use_existing_tests:
            for tc in self.store.test_cases.values():
                if tc.get("project_id") != project_id:
                    continue
                if (
                    root
                    and root.name.lower() not in str(tc).lower()
                    and query.split()[0].lower() not in str(tc).lower()
                ):
                    # still include broadly for demo completeness when few tests
                    pass
                existing_coverage.append(
                    {
                        "test_case_id": tc.get("test_case_id"),
                        "title": tc.get("title"),
                        "graph_path": tc.get("graph_path"),
                        "priority": tc.get("priority"),
                        "project_id": project_id,
                        "source_type": "existing_test",
                    }
                )

        if plan.use_historical_bugs:
            for bug in self.store.bugs.values():
                if bug.get("project_id") != project_id:
                    continue
                historical_risks.append(
                    {
                        "bug_id": bug.get("bug_id"),
                        "title": bug.get("title"),
                        "severity": bug.get("severity"),
                        "affected_components": bug.get("affected_components"),
                        "graph_path": bug.get("graph_path"),
                        "project_id": project_id,
                        "source_type": "historical_bug",
                    }
                )

        if plan.use_external_search:
            external_context.append(
                {
                    "note": "External search flagged by planner but not executed in offline demo mode.",
                    "suggestion": "Consult domain-relevant security and quality standards for the selected feature.",
                }
            )

        feature_context["project_id"] = project_id
        fused = FusedContext(
            feature_context=feature_context,
            flow_paths=flow_paths,
            graph_context=graph_context,
            semantic_context=semantic_context,
            existing_coverage=existing_coverage[:40],
            historical_risks=historical_risks[:40],
            external_context=external_context,
        )
        fused = assert_project_consistency(fused, project_id)
        logger.info(
            "context_fused",
            project_id=project_id,
            paths=len(flow_paths),
            semantic=len(fused.semantic_context),
            tests=len(fused.existing_coverage),
            bugs=len(fused.historical_risks),
        )
        return plan, fused


def assert_project_consistency(fused: FusedContext, project_id: str) -> FusedContext:
    """Drop any fused evidence that belongs to another project before LLM generation."""

    def _item_project(item: dict[str, Any]) -> str | None:
        if item.get("project_id"):
            return str(item["project_id"])
        meta = item.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("project_id"):
            return str(meta["project_id"])
        return None

    dropped = 0

    def _filter(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonlocal dropped
        kept: list[dict[str, Any]] = []
        for item in items:
            pid = _item_project(item)
            if pid is not None and pid != project_id:
                dropped += 1
                continue
            kept.append(item)
        return kept

    fused.semantic_context = _filter(fused.semantic_context)
    fused.existing_coverage = _filter(fused.existing_coverage)
    fused.historical_risks = _filter(fused.historical_risks)
    if dropped:
        logger.warning(
            "mixed_project_evidence_dropped",
            project_id=project_id,
            dropped=dropped,
        )
    return fused


def get_intent_classifier() -> IntentClassifier:
    return IntentClassifier()


def get_context_fusion() -> ContextFusionLayer:
    return ContextFusionLayer()


def get_retrieval_planner() -> RetrievalPlanner:
    return RetrievalPlanner()
