"""Specialized QA agents — each independently testable."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.graph.traversal import get_coverage_engine, get_traversal
from app.models.enums import ConfidenceLevel, Priority, RiskLevel
from app.models.schemas import (
    BugReport,
    CoverageGapResult,
    ExploratoryMission,
    FusedContext,
    ImpactAnalysisResult,
    RegressionRecommendation,
    TestCase,
    new_id,
)
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)


TECHNIQUE_BY_PATH = [
    (("failure", "lockout", "invalid", "timeout"), "Negative testing / fault injection"),
    (("oauth", "sso", "saml", "oidc", "provider"), "Integration & security testing"),
    (("mfa", "session", "fixation"), "Security testing"),
    (("validation", "registration"), "Boundary value & validation testing"),
    (("forgot", "reset", "recovery"), "Alternate flow / recovery testing"),
]


def _technique_for_path(path: list[str]) -> str:
    joined = " ".join(path).lower()
    for keys, technique in TECHNIQUE_BY_PATH:
        if any(k in joined for k in keys):
            return technique
    return "Path-based functional testing"


def _priority_for_path(path: list[str], is_failure: bool, external: bool) -> Priority:
    joined = " ".join(path).lower()
    if external or "sso" in joined or "oauth" in joined or "mfa" in joined:
        return Priority.HIGH
    if is_failure or "lockout" in joined:
        return Priority.HIGH
    if "invalid" in joined:
        return Priority.MEDIUM
    return Priority.MEDIUM


class TestCaseAgent:
    def generate(self, query: str, fused: FusedContext, project_id: str) -> list[TestCase]:
        cases: list[TestCase] = []
        feature = fused.feature_context.get("name") or "Feature"
        existing_titles = { (t.get("title") or "").lower() for t in fused.existing_coverage }

        # Prefer graph-path based generation
        path_meta = {
            tuple(item.get("path") or []): item
            for item in fused.graph_context
            if item.get("path")
        }
        paths = fused.flow_paths or list(path_meta.keys())
        if not paths and fused.feature_context.get("branches"):
            paths = [[feature, b] for b in fused.feature_context["branches"]]

        for idx, path in enumerate(paths, start=1):
            path_list = list(path) if not isinstance(path, list) else path
            meta = path_meta.get(tuple(path_list), {})
            is_failure = bool(meta.get("is_failure_path"))
            external = bool(meta.get("includes_external_dependency"))
            leaf = path_list[-1] if path_list else feature
            title = self._title_for(path_list, is_failure)
            if title.lower() in existing_titles:
                # Still emit but mark as regression-relevant coverage check
                title = f"Verify existing coverage: {title}"

            risk = RiskLevel.HIGH if is_failure or external else RiskLevel.MEDIUM
            related_bugs = [
                b.get("bug_id") or b.get("title")
                for b in fused.historical_risks
                if any(p.lower() in str(b).lower() for p in path_list)
            ][:3]
            sources = ["User-provided system flow graph"]
            if fused.semantic_context:
                sources.append(fused.semantic_context[0].get("source_reference") or "Vector RAG requirements")
            if related_bugs:
                sources.extend([str(b) for b in related_bugs])

            cases.append(
                TestCase(
                    test_case_id=f"TC-{idx:03d}",
                    title=title,
                    category="security" if external or "mfa" in " ".join(path_list).lower() else "functional",
                    priority=_priority_for_path(path_list, is_failure, external),
                    risk=risk,
                    preconditions=[
                        f"Project system flow includes path: {' → '.join(path_list)}",
                        "Test environment mirrors production auth configuration.",
                    ],
                    test_data=self._test_data(path_list, is_failure),
                    steps=self._steps(path_list, is_failure),
                    expected_result=self._expected(path_list, is_failure),
                    testing_technique=_technique_for_path(path_list),
                    graph_path=path_list,
                    graph_reasoning=(
                        f"This test covers the discovered graph path {' → '.join(path_list)}. "
                        + (
                            "Path includes an external dependency boundary."
                            if external
                            else "Path represents a user-reachable authentication journey."
                        )
                        + (
                            " Failure/negative behavior is in scope."
                            if is_failure
                            else ""
                        )
                    ),
                    source_references=sources,
                    confidence=ConfidenceLevel.HIGH if not meta.get("inferred") else ConfidenceLevel.MEDIUM,
                    assumptions=[
                        "User-provided flow graph accurately reflects production behavior.",
                        "Inferred nodes (if any) are marked and not treated as confirmed architecture.",
                    ],
                    project_id=project_id,
                    feature_id=fused.feature_context.get("id"),
                )
            )

        # Supplement with LLM if available for cross-method security cases
        openai = get_openai_service()
        if openai.available and cases:
            try:
                data = openai.chat_json(
                    "You are a senior QA engineer. Given fused QA context, propose up to 3 additional "
                    "cross-cutting security/session test cases as JSON {test_cases:[{title,steps,expected_result,graph_path,graph_reasoning}]}.",
                    f"Query: {query}\nFeature: {feature}\nBranches: {fused.feature_context.get('branches')}\n"
                    f"Historical risks: {fused.historical_risks[:5]}",
                )
                for extra in data.get("test_cases", [])[:3]:
                    cases.append(
                        TestCase(
                            test_case_id=f"TC-{len(cases)+1:03d}",
                            title=extra.get("title") or "Cross-cutting auth security check",
                            category="security",
                            priority=Priority.HIGH,
                            risk=RiskLevel.HIGH,
                            steps=extra.get("steps") or ["Exercise cross-method auth edge case."],
                            expected_result=extra.get("expected_result") or "Secure handling without session leakage.",
                            testing_technique="Security testing",
                            graph_path=extra.get("graph_path") or [feature],
                            graph_reasoning=extra.get("graph_reasoning") or "LLM-assisted cross-path security case.",
                            source_references=["LLM reasoning", "User-provided system flow graph"],
                            confidence=ConfidenceLevel.MEDIUM,
                            assumptions=["Additional case may be partially inferred."],
                            project_id=project_id,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("testcase_llm_enrichment_failed", error=str(exc))

        # Persist lightly for coverage matching
        store = get_graph_store()
        for case in cases:
            store.test_cases[case.test_case_id] = case.model_dump(mode="json")
        store.persist()
        return cases

    def _title_for(self, path: list[str], is_failure: bool) -> str:
        leaf = path[-1] if path else "flow"
        if is_failure or any(k in leaf.lower() for k in ("invalid", "failure", "lockout", "timeout")):
            return f"Graceful handling: {' → '.join(path)}"
        if "valid" in leaf.lower() or "session" in leaf.lower() or leaf.lower() in {"callback", "consent"}:
            return f"Successful journey: {' → '.join(path)}"
        return f"Validate path: {' → '.join(path)}"

    def _test_data(self, path: list[str], is_failure: bool) -> dict[str, Any]:
        joined = " ".join(path).lower()
        if "google" in joined or "oauth" in joined:
            return {"provider": "Google", "account": "qa.oauth@example.com"}
        if "sso" in joined or "saml" in joined or "oidc" in joined:
            return {"idp": "enterprise-idp", "protocol": "SAML" if "saml" in joined else "OIDC"}
        if "password" in joined or "email" in joined:
            return {
                "email": "qa.user@example.com",
                "password": "WrongPass!" if is_failure or "invalid" in joined else "CorrectPass!23",
            }
        return {"persona": "standard_user"}

    def _steps(self, path: list[str], is_failure: bool) -> list[str]:
        steps = [f"Navigate to entry point: {path[0]}"]
        for node in path[1:]:
            steps.append(f"Traverse / exercise: {node}")
        if is_failure:
            steps.append("Inject or trigger the failure condition at the leaf node.")
            steps.append("Observe error handling, messaging, and system state.")
        else:
            steps.append("Complete the happy-path transition through the leaf node.")
            steps.append("Verify resulting application/session state.")
        return steps

    def _expected(self, path: list[str], is_failure: bool) -> str:
        if is_failure:
            return (
                f"System handles failure on path {' → '.join(path)} without crashing, "
                "with clear user feedback and no insecure session creation."
            )
        return f"User successfully completes {' → '.join(path)} and reaches the intended authenticated/application state."


class ExploratoryAgent:
    def generate(self, fused: FusedContext) -> list[ExploratoryMission]:
        missions: list[ExploratoryMission] = []
        feature = fused.feature_context.get("name") or "Feature"
        for path in fused.flow_paths:
            if len(path) < 2:
                continue
            # Focus on transitions and external boundaries
            transition = f"{path[-2]} → {path[-1]}" if len(path) >= 2 else path[-1]
            is_external = any(
                k in " ".join(path).lower()
                for k in ("oauth", "google", "sso", "provider", "saml", "oidc")
            )
            focus = [
                f"Break the {transition} transition",
                "Refresh / back-button during in-flight auth",
                "Multiple tabs racing the same flow",
                "Network interruption mid-transition",
            ]
            if is_external:
                focus += [
                    "Provider response delay / timeout",
                    "Expired or replayed callback",
                    "Consent denial then retry",
                ]
            missions.append(
                ExploratoryMission(
                    title=f"Explore: {transition}",
                    charter=f"Break the {transition} transition within {feature}.",
                    focus_areas=focus,
                    graph_path=path,
                    risks_to_probe=[
                        "Session fixation / orphan sessions",
                        "Inconsistent error states",
                        "Partial auth tokens left behind",
                    ],
                    heuristics=["Tour", "Interruptions", "Boundaries", "States"],
                    source_references=["User-provided system flow graph"],
                    confidence=ConfidenceLevel.HIGH,
                )
            )
        # Deduplicate by transition title
        seen: set[str] = set()
        unique: list[ExploratoryMission] = []
        for m in missions:
            if m.title in seen:
                continue
            seen.add(m.title)
            unique.append(m)
        return unique[:12]


class BugReportAgent:
    def generate(self, query: str, fused: FusedContext) -> list[BugReport]:
        # Prefer historical patterns + likely failure paths
        reports: list[BugReport] = []
        for bug in fused.historical_risks[:5]:
            reports.append(
                BugReport(
                    bug_id=bug.get("bug_id") or new_id("BUG"),
                    title=bug.get("title") or "Historical defect pattern",
                    severity=RiskLevel(bug.get("severity", "medium"))
                    if bug.get("severity") in {r.value for r in RiskLevel}
                    else RiskLevel.MEDIUM,
                    steps_to_reproduce=[
                        "Reproduce using the associated graph path.",
                        "Compare current behavior to historical failure signature.",
                    ],
                    expected_result="Defect no longer reproducible; regression guard in place.",
                    actual_result="Historical pattern indicates prior breakage on this path.",
                    environment="Staging / QA",
                    graph_path=bug.get("graph_path")
                    or (fused.flow_paths[0] if fused.flow_paths else []),
                    affected_components=bug.get("affected_components") or [],
                    source_references=[bug.get("bug_id") or "historical_bugs"],
                )
            )
        if not reports:
            failure_paths = [p for p in fused.flow_paths if any("fail" in x.lower() or "lock" in x.lower() or "invalid" in x.lower() for x in p)]
            for path in failure_paths[:3]:
                reports.append(
                    BugReport(
                        title=f"Potential defect area: {' → '.join(path)}",
                        severity=RiskLevel.HIGH,
                        steps_to_reproduce=[f"Exercise failure path {' → '.join(path)}"],
                        expected_result="Controlled failure handling",
                        actual_result="(Template) Observe and document actual deviation",
                        graph_path=path,
                        source_references=["User-provided system flow graph"],
                    )
                )
        return reports


class RegressionAgent:
    def recommend(
        self,
        fused: FusedContext,
        impact: ImpactAnalysisResult | None,
        changed_node: str | None,
    ) -> list[RegressionRecommendation]:
        recs: list[RegressionRecommendation] = []
        changed = changed_node or (impact.changed_node if impact else None) or fused.feature_context.get("name")
        # From existing tests intersecting impact
        for tc in fused.existing_coverage:
            path = tc.get("graph_path") or []
            path_l = " ".join(str(p) for p in path).lower()
            related = False
            if changed and changed.lower() in path_l:
                related = True
            if impact and any(n.lower() in path_l for n in impact.directly_impacted_nodes[:10]):
                related = True
            if related:
                recs.append(
                    RegressionRecommendation(
                        test_case_id=tc.get("test_case_id") or new_id("TC"),
                        title=tc.get("title") or "Regression candidate",
                        reason=(
                            f"This test is recommended because it covers [{ ' → '.join(path) }], "
                            f"which is connected to the changed node '{changed}'."
                        ),
                        graph_path=list(path),
                        changed_node=changed,
                        priority=Priority.HIGH,
                        source_references=["Graph impact analysis", "Existing test catalog"],
                    )
                )
        # Also recommend path tests for direct neighbors
        if impact:
            for name in impact.directly_impacted_nodes[:8]:
                matching = [p for p in fused.flow_paths if name in p]
                for path in matching[:1]:
                    recs.append(
                        RegressionRecommendation(
                            test_case_id=new_id("TC"),
                            title=f"Retest path through {name}",
                            reason=(
                                f"This test is recommended because it covers [{' → '.join(path)}], "
                                f"which is connected to the changed node '{impact.changed_node}'."
                            ),
                            graph_path=path,
                            changed_node=impact.changed_node,
                            priority=Priority.HIGH,
                            source_references=["User-provided system flow graph", "Impact analysis"],
                        )
                    )
        # Dedupe by title
        seen: set[str] = set()
        out: list[RegressionRecommendation] = []
        for r in recs:
            if r.title in seen:
                continue
            seen.add(r.title)
            out.append(r)
        return out[:20]


class ImpactAgent:
    def analyze(self, project_id: str, changed_node: str) -> ImpactAnalysisResult:
        return get_traversal().impact_analysis(project_id, changed_node)


class CoverageAgent:
    def analyze(self, project_id: str, root_feature: str | None = None) -> CoverageGapResult:
        return get_coverage_engine().analyze(project_id, root_feature)


class CriticAgent:
    def review(
        self,
        *,
        test_cases: list[TestCase],
        coverage: CoverageGapResult | None,
        fused: FusedContext,
    ) -> tuple[list[str], list[TestCase]]:
        notes: list[str] = []
        improved = list(test_cases)

        paths_covered = {" → ".join(tc.graph_path) for tc in test_cases if tc.graph_path}
        for path in fused.flow_paths:
            key = " → ".join(path)
            if key not in paths_covered:
                notes.append(f"Missing generated test for discovered path: {key}")

        if coverage:
            for gap in coverage.critical_gaps[:6]:
                notes.append(f"Critical gap remains: {gap}")
            # Auto-add recommended gap tests if not present
            for rec in coverage.recommended_tests[:4]:
                if not any(rec.lower() in tc.title.lower() for tc in improved):
                    improved.append(
                        TestCase(
                            test_case_id=f"TC-{len(improved)+1:03d}",
                            title=rec,
                            category="functional",
                            priority=Priority.HIGH,
                            risk=RiskLevel.HIGH,
                            steps=["Design and execute coverage for the identified uncovered graph branch/path."],
                            expected_result="Uncovered graph area gains explicit test evidence.",
                            testing_technique="Coverage-gap driven testing",
                            graph_path=[coverage.root_feature],
                            graph_reasoning="Added by Critic Agent to close an identified graph coverage gap.",
                            source_references=["Coverage analysis", "User-provided system flow graph"],
                            confidence=ConfidenceLevel.MEDIUM,
                            assumptions=["Gap derived from comparing graph nodes to existing test path tokens."],
                        )
                    )
                    notes.append(f"Critic added coverage-driven test: {rec}")

        # Ensure every test has graph_path
        for tc in improved:
            if not tc.graph_path and fused.feature_context.get("name"):
                tc.graph_path = [fused.feature_context["name"]]
                notes.append(f"Attached root feature path to {tc.test_case_id}")

        openai = get_openai_service()
        if openai.available:
            try:
                data = openai.chat_json(
                    "You are a QA critic. Review test cases for graph-path completeness. "
                    "Return JSON {notes:[], improvements:[]}.",
                    f"tests={[tc.title for tc in improved[:15]]}\ngaps={(coverage.critical_gaps if coverage else [])}",
                )
                notes.extend(data.get("notes") or [])
                notes.extend([f"Improvement: {i}" for i in data.get("improvements") or []])
            except Exception as exc:  # noqa: BLE001
                logger.warning("critic_llm_failed", error=str(exc))

        if not notes:
            notes.append("Critic review complete — path linkage and gap checks passed with no blocking issues.")
        return notes, improved


class RiskAgent:
    def assess(self, fused: FusedContext, coverage: CoverageGapResult | None) -> RiskLevel:
        score = 0
        if fused.historical_risks:
            score += 2
        if coverage and coverage.critical_gaps:
            score += 2
        if any(p for p in fused.flow_paths if any("fail" in x.lower() for x in p)):
            score += 1
        if any(
            "oauth" in " ".join(p).lower() or "sso" in " ".join(p).lower() for p in fused.flow_paths
        ):
            score += 1
        if score >= 4:
            return RiskLevel.HIGH
        if score >= 2:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW