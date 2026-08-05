"""Graph traversal, path discovery, impact, and coverage engines."""

from __future__ import annotations

from typing import Any

from app.graph.store import get_graph_store
from app.models.enums import NodeType, RiskLevel
from app.models.schemas import (
    CoverageGapResult,
    GraphNode,
    GraphPath,
    ImpactAnalysisResult,
    NodeInsight,
    SystemFlowGraph,
)


class GraphTraversalService:
    def __init__(self) -> None:
        self.store = get_graph_store()

    def load_flow(self, project_id: str) -> SystemFlowGraph:
        return self.store.get_project_graph(project_id)

    def resolve_root(self, project_id: str, root_feature: str | None = None) -> GraphNode | None:
        graph = self.load_flow(project_id)
        if root_feature:
            found = self.store.find_node_by_name(project_id, root_feature)
            if found:
                return found
            # fuzzy contains
            matches = self.store.find_nodes(project_id, name=root_feature)
            if matches:
                return matches[0]
        if graph.root_node_id:
            return self.store.get_node(graph.root_node_id)
        features = self.store.find_nodes(project_id, node_type=NodeType.FEATURE)
        return features[0] if features else None

    def discover_paths(self, project_id: str, root_id: str, max_depth: int = 8) -> list[GraphPath]:
        return self.store.discover_paths(project_id, root_id, max_depth=max_depth)

    def branches(self, project_id: str, root_id: str) -> list[GraphNode]:
        return [n for _, n in self.store.neighbors(root_id, direction="outgoing") if n.project_id == project_id]

    def node_insight(self, project_id: str, node_id: str) -> NodeInsight | None:
        node = self.store.get_node(node_id)
        if not node or node.project_id != project_id:
            return None

        outgoing = self.store.neighbors(node_id, direction="outgoing")
        incoming = self.store.neighbors(node_id, direction="incoming")

        connected_features = [
            n.name
            for _, n in incoming + outgoing
            if n.type in (NodeType.FEATURE, NodeType.SUB_FEATURE, NodeType.USER_JOURNEY)
        ]
        dependencies = [
            n.name
            for _, n in outgoing + incoming
            if n.type
            in (
                NodeType.EXTERNAL_DEPENDENCY,
                NodeType.THIRD_PARTY_PROVIDER,
                NodeType.SERVICE,
                NodeType.API,
                NodeType.DATABASE,
                NodeType.COMPONENT,
            )
            or n.is_external_dependency
        ]
        flows = [
            n.name
            for _, n in outgoing
            if n.type in (NodeType.USER_FLOW, NodeType.ALTERNATE_FLOW, NodeType.STATE, NodeType.AUTHENTICATION_METHOD)
        ]

        existing_tests = [
            tc.get("title") or tc.get("test_case_id", "")
            for tc in self.store.test_cases.values()
            if tc.get("project_id") == project_id
            and (
                node.name.lower() in str(tc.get("graph_path", [])).lower()
                or node.name.lower() in (tc.get("title") or "").lower()
            )
        ]
        historical_bugs = [
            b.get("title") or b.get("bug_id", "")
            for b in self.store.bugs.values()
            if b.get("project_id") == project_id
            and node.name.lower() in (b.get("title", "") + " " + " ".join(b.get("affected_components", []))).lower()
        ]

        risk = RiskLevel.MEDIUM
        if node.is_failure_path or node.is_critical or node.is_external_dependency:
            risk = RiskLevel.HIGH
        if historical_bugs:
            risk = RiskLevel.HIGH

        coverage = None
        if existing_tests and flows:
            coverage = min(1.0, len(existing_tests) / max(1, len(flows)))
        elif existing_tests:
            coverage = 0.75
        elif flows:
            coverage = 0.0

        return NodeInsight(
            node=node,
            connected_features=sorted(set(connected_features)),
            dependencies=sorted(set(dependencies)),
            flows=sorted(set(flows)),
            existing_tests=existing_tests[:20],
            historical_bugs=historical_bugs[:20],
            risk=risk,
            coverage=coverage,
            incoming=[
                {"from": n.name, "relationship": str(e.relationship), "node_id": n.id}
                for e, n in incoming
            ],
            outgoing=[
                {"to": n.name, "relationship": str(e.relationship), "node_id": n.id}
                for e, n in outgoing
            ],
        )

    def impact_analysis(self, project_id: str, changed_name_or_id: str) -> ImpactAnalysisResult:
        node = self.store.get_node(changed_name_or_id)
        if node and node.project_id != project_id:
            node = None
        if not node:
            node = self.store.find_node_by_name(project_id, changed_name_or_id)
        if not node:
            matches = self.store.find_nodes(project_id, name=changed_name_or_id)
            node = matches[0] if matches else None
        if not node:
            return ImpactAnalysisResult(
                changed_node=changed_name_or_id,
                risk_level=RiskLevel.LOW,
                reasoning_paths=[f"Node '{changed_name_or_id}' not found in project graph."],
            )

        sub = self.store.impact_subgraph(node.id, max_depth=4)
        impacted_tests = [
            tc.get("test_case_id") or tc.get("title", "")
            for tc in self.store.test_cases.values()
            if tc.get("project_id") == project_id
            and (
                node.name.lower() in str(tc.get("graph_path", [])).lower()
                or any(x.lower() in str(tc.get("graph_path", [])).lower() for x in sub["direct"][:10])
            )
        ]
        historical = [
            b.get("bug_id") or b.get("title", "")
            for b in self.store.bugs.values()
            if b.get("project_id") == project_id
            and node.name.lower() in (b.get("title", "") + str(b.get("affected_components", []))).lower()
        ]
        features = [n for n in sub["direct"] + sub["indirect"] if True]
        # Classify features vs flows heuristically via store lookup
        impacted_features: list[str] = []
        impacted_flows: list[str] = []
        for name in features:
            found = self.store.find_node_by_name(project_id, name)
            if not found:
                continue
            if found.type in (NodeType.FEATURE, NodeType.SUB_FEATURE):
                impacted_features.append(name)
            elif found.type in (NodeType.USER_FLOW, NodeType.AUTHENTICATION_METHOD, NodeType.ALTERNATE_FLOW):
                impacted_flows.append(name)

        risk = RiskLevel.MEDIUM
        if node.is_external_dependency or node.is_critical or len(impacted_tests) > 3:
            risk = RiskLevel.HIGH
        if historical:
            risk = RiskLevel.HIGH

        reasoning = []
        for path in sub["paths"][:15]:
            reasoning.append(path)
        for tc in impacted_tests[:5]:
            reasoning.append(
                f"{tc} is impacted because it covers paths connected to the changed node '{node.name}'."
            )

        return ImpactAnalysisResult(
            changed_node=node.name,
            directly_impacted_nodes=sub["direct"],
            indirectly_impacted_nodes=sub["indirect"],
            impacted_user_flows=sorted(set(impacted_flows)),
            impacted_features=sorted(set(impacted_features)),
            impacted_test_cases=impacted_tests,
            historical_bugs=historical,
            risk_level=risk,
            reasoning_paths=reasoning,
        )


class CoverageEngine:
    def __init__(self) -> None:
        self.store = get_graph_store()
        self.traversal = GraphTraversalService()

    def analyze(self, project_id: str, root_feature: str | None = None) -> CoverageGapResult:
        # Lazy import avoids circular import: graph ↔ agents package init
        from app.agents.dedup import dedupe_strings

        root = self.traversal.resolve_root(project_id, root_feature)
        if not root:
            return CoverageGapResult(
                root_feature=root_feature or "unknown",
                calculation_notes=["No root feature found in user flow graph."],
            )

        branches = self.traversal.branches(project_id, root.id)
        paths = self.traversal.discover_paths(project_id, root.id)

        # Existing coverage signals from seeded/generated test cases
        covered_names: set[str] = set()
        for tc in self.store.test_cases.values():
            if tc.get("project_id") != project_id:
                continue
            for part in tc.get("graph_path", []) or []:
                covered_names.add(str(part).lower())
            title = (tc.get("title") or "").lower()
            for b in branches:
                if b.name.lower() in title:
                    covered_names.add(b.name.lower())

        covered_branches = [b.name for b in branches if b.name.lower() in covered_names]
        uncovered_branches = [b.name for b in branches if b.name.lower() not in covered_names]

        failure_nodes = [
            n
            for n in self.store.find_nodes(project_id)
            if n.is_failure_path or n.type == NodeType.FAILURE_PATH
        ]
        uncovered_failures = [n.name for n in failure_nodes if n.name.lower() not in covered_names]
        covered_failures = [n.name for n in failure_nodes if n.name.lower() in covered_names]

        deps = [
            n
            for n in self.store.find_nodes(project_id)
            if n.is_external_dependency
            or n.type in (NodeType.EXTERNAL_DEPENDENCY, NodeType.THIRD_PARTY_PROVIDER)
        ]
        uncovered_deps = [n.name for n in deps if n.name.lower() not in covered_names]
        covered_deps = [n.name for n in deps if n.name.lower() in covered_names]

        states = self.store.find_nodes(project_id, node_type=NodeType.STATE)
        uncovered_states = [n.name for n in states if n.name.lower() not in covered_names]

        rules = self.store.find_nodes(project_id, node_type=NodeType.BUSINESS_RULE)
        uncovered_rules = [n.name for n in rules if n.name.lower() not in covered_names]

        branch_cov = (len(covered_branches) / len(branches)) if branches else 1.0
        failure_cov = (len(covered_failures) / len(failure_nodes)) if failure_nodes else 1.0
        dep_cov = (len(covered_deps) / len(deps)) if deps else 1.0
        root_cov = 1.0 if covered_branches or covered_names else 0.0

        # Weighted overall — explained transparently
        overall = round((0.4 * branch_cov + 0.3 * failure_cov + 0.2 * dep_cov + 0.1 * root_cov) * 100, 1)

        critical_gaps: list[str] = []
        for name in dedupe_strings(uncovered_branches):
            node = next((b for b in branches if b.name == name), None)
            if node and (node.is_critical or node.is_external_dependency or "sso" in name.lower()):
                critical_gaps.append(f"Uncovered branch: {name}")
        for name in dedupe_strings(uncovered_failures):
            critical_gaps.append(f"Uncovered failure path: {name}")
        for name in dedupe_strings(uncovered_deps):
            critical_gaps.append(f"Uncovered external dependency: {name}")
        critical_gaps = dedupe_strings(critical_gaps)

        recommended = [f"Add path coverage for {n}" for n in dedupe_strings(uncovered_branches)[:8]]
        recommended += [f"Add negative/failure test for {n}" for n in dedupe_strings(uncovered_failures)[:5]]
        recommended = dedupe_strings(recommended)
        notes = [
            f"Root feature coverage = 100% if any branch/path is covered, else 0% → {root_cov * 100:.0f}%",
            f"Branch coverage = covered_branches / direct_children = {len(covered_branches)}/{len(branches)} → {branch_cov * 100:.0f}%",
            f"Failure path coverage = {len(covered_failures)}/{len(failure_nodes)} → {failure_cov * 100:.0f}%",
            f"Dependency coverage = {len(covered_deps)}/{len(deps)} → {dep_cov * 100:.0f}%",
            "Overall = 0.4*branch + 0.3*failure + 0.2*dependency + 0.1*root",
            f"Discovered leaf graph paths from root: {len(paths)}",
            "Coverage is matched by comparing existing test graph_path/title tokens against node names — not fabricated precision.",
        ]

        return CoverageGapResult(
            root_feature=root.name,
            covered_branches=dedupe_strings(covered_branches),
            uncovered_branches=dedupe_strings(uncovered_branches),
            uncovered_failure_paths=dedupe_strings(uncovered_failures),
            uncovered_dependencies=dedupe_strings(uncovered_deps),
            uncovered_states=dedupe_strings(uncovered_states),
            uncovered_business_rules=dedupe_strings(uncovered_rules),
            critical_gaps=critical_gaps,
            recommended_tests=recommended,
            root_feature_coverage=round(root_cov * 100, 1),
            branch_coverage=round(branch_cov * 100, 1),
            failure_path_coverage=round(failure_cov * 100, 1),
            dependency_coverage=round(dep_cov * 100, 1),
            overall_coverage=overall,
            calculation_notes=notes,
        )


def get_traversal() -> GraphTraversalService:
    return GraphTraversalService()


def get_coverage_engine() -> CoverageEngine:
    return CoverageEngine()