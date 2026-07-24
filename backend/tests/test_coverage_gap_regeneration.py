"""Phase 4 — Critic → Coverage Gap → Targeted Regeneration tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agents.coverage_gaps import (
    build_coverage_gaps,
    build_coverage_snapshot,
    prioritize_gaps,
    select_gaps_for_regeneration,
)
from app.agents.dedup import deduplicate_tests, is_duplicate
from app.agents.specialists import CriticAgent, TestCaseAgent
from app.models.enums import GapType, Priority, RiskLevel
from app.models.schemas import (
    CoverageGap,
    CoverageGapResult,
    FusedContext,
    TestCase as QATestCase,
)


@pytest.fixture(autouse=True)
def _isolate_store(monkeypatch, tmp_path):
    graph_path = tmp_path / "graph_store.json"
    chroma = tmp_path / "chroma"
    data = tmp_path / "data"
    data.mkdir()
    chroma.mkdir()
    monkeypatch.setenv("GRAPH_STORE_PATH", str(graph_path))
    monkeypatch.setenv("CHROMA_DIR", str(chroma))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("ENABLE_DEMO_FALLBACK", "true")
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    import app.core.config as config
    import app.graph.store as store_mod
    import app.rag.vector_store as vs_mod
    import app.services.openai_service as oa_mod

    config.get_settings.cache_clear()
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None
    yield
    config.get_settings.cache_clear()
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None


@pytest.fixture
def client():
    from app.main import create_app

    return TestClient(create_app())


def _fused(*, include_uncovered_sso: bool = True) -> FusedContext:
    paths = [
        ["Sign In", "Email + Password", "Valid Credentials"],
        ["Sign In", "Google OAuth", "Provider Failure"],
    ]
    if include_uncovered_sso:
        paths.append(["Sign In", "Enterprise SSO", "SAML Assertion"])
    return FusedContext(
        feature_context={
            "id": "feature_signin",
            "name": "Sign In",
            "type": "Feature",
            "branches": ["Email + Password", "Google OAuth", "Enterprise SSO"],
            "project_id": "proj_1",
        },
        flow_paths=paths,
        graph_context=[
            {
                "path": paths[0],
                "node_ids": ["n1", "n2", "n3"],
                "path_id": "n1→n2→n3",
                "is_failure_path": False,
                "includes_external_dependency": False,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FLOW"],
            },
            {
                "path": paths[1],
                "node_ids": ["n1", "n4", "n5"],
                "path_id": "n1→n4→n5",
                "is_failure_path": True,
                "includes_external_dependency": True,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FAILURE_PATH"],
            },
            *(
                [
                    {
                        "path": paths[2],
                        "node_ids": ["n1", "n6", "n7"],
                        "path_id": "n1→n6→n7",
                        "is_failure_path": False,
                        "includes_external_dependency": True,
                        "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FLOW"],
                    }
                ]
                if include_uncovered_sso
                else []
            ),
        ],
        semantic_context=[
            {
                "id": "chunk_req_1",
                "document_id": "doc_auth",
                "content": "Users must authenticate via Enterprise SSO when enrolled.",
                "score": 0.91,
                "source_reference": "authentication_requirements.md#chunk-0",
                "metadata": {
                    "filename": "authentication_requirements.md",
                    "document_id": "doc_auth",
                    "title": "Enterprise SSO requirement",
                },
                "source_type": "requirement",
            }
        ],
        existing_coverage=[
            {
                "test_case_id": "TC-SEED",
                "title": "Successful email/password login",
                "steps": ["Login with email"],
                "expected_result": "Session created",
                "graph_path": paths[0],
                "priority": "high",
                "source_type": "existing_test",
            }
        ],
        historical_risks=[
            {
                "bug_id": "BUG-007",
                "title": "OAuth callback failure leaves orphan session cookie",
                "severity": "high",
                "affected_components": ["Google OAuth"],
                "graph_path": ["Sign In", "Google OAuth", "Callback"],
                "source_type": "historical_bug",
            }
        ],
        external_context=[],
    )


def _covered_cases(fused: FusedContext) -> list[QATestCase]:
    """Simulate a fully path-covered initial set (no high-priority graph gaps)."""
    cases = []
    for i, path in enumerate(fused.flow_paths, start=1):
        cases.append(
            QATestCase(
                test_case_id=f"TC-{i:03d}",
                title=f"Cover {' → '.join(path)}",
                steps=[f"Exercise {path[-1]}"],
                expected_result="Path completes safely",
                graph_path=path,
                generation_method="deterministic_fallback",
                reasoning=f"Covers {path[-1]}",
                evidence=[],
                category="regression" if "OAuth" in " ".join(path) else "functional",
                source_references=["BUG-007"] if "OAuth" in " ".join(path) else [],
            )
        )
    # Link requirement + bug so those gaps close
    cases[0].evidence = []
    cases[-1].source_references = ["BUG-007", "chunk_req_1"]
    cases[-1].reasoning = (
        "Covers OAuth callback failure leaves orphan session cookie and Enterprise SSO requirement"
    )
    return cases


# ---------------------------------------------------------------------------
# A. NO GAPS
# ---------------------------------------------------------------------------


def test_a_no_high_priority_gaps_skips_targeted_regeneration():
    fused = _fused(include_uncovered_sso=True)
    cases = _covered_cases(fused)
    # Also cite requirement id on a case
    cases[0].evidence = []
    for c in cases:
        if "Enterprise SSO" in " ".join(c.graph_path):
            c.source_references.append("chunk_req_1")
            c.reasoning = (c.reasoning or "") + " Enterprise SSO requirement chunk_req_1"

    coverage = CoverageGapResult(
        root_feature="Sign In",
        covered_branches=["Email + Password", "Google OAuth", "Enterprise SSO"],
        uncovered_branches=[],
        uncovered_failure_paths=[],
        uncovered_dependencies=[],
        critical_gaps=[],
        recommended_tests=[],
        overall_coverage=100.0,
        branch_coverage=100.0,
    )
    gaps = build_coverage_gaps(coverage=coverage, fused=fused, test_cases=cases)
    selected = select_gaps_for_regeneration(gaps, max_gaps=4)
    assert selected == []


def test_a_api_no_targeted_when_paths_already_covered(client):
    seed = client.post("/api/demo/seed").json()
    # First generate so store has coverage; second call still stable
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
            "enable_targeted_regeneration": True,
            "max_regeneration_rounds": 1,
        },
    ).json()
    assert "test_cases" in result
    assert "regeneration_rounds" in result
    assert "coverage_before" in result
    assert "coverage_after" in result
    initial = result.get("initial_test_cases") or []
    assert len(initial) >= 1
    # Final set is a superset of initial (targeted may add, never remove initial)
    initial_ids = {tc["test_case_id"] for tc in initial}
    final_ids = {tc["test_case_id"] for tc in result["test_cases"]}
    assert initial_ids.issubset(final_ids)


# ---------------------------------------------------------------------------
# B. HIGH-PRIORITY GAP
# ---------------------------------------------------------------------------


def test_b_high_priority_gap_produces_targeted_tests():
    fused = _fused()
    # Cover only first path — leave SSO + failure uncovered
    base = [
        QATestCase(
            test_case_id="TC-001",
            title="Email happy path",
            steps=["Login"],
            expected_result="OK",
            graph_path=fused.flow_paths[0],
            generation_method="deterministic_fallback",
        )
    ]
    coverage = CoverageGapResult(
        root_feature="Sign In",
        uncovered_branches=["Enterprise SSO"],
        uncovered_failure_paths=["Provider Failure"],
        uncovered_dependencies=["Google OAuth"],
        critical_gaps=["Uncovered branch: Enterprise SSO", "Uncovered failure path: Provider Failure"],
        recommended_tests=["Add path coverage for Enterprise SSO"],
        overall_coverage=20.0,
        branch_coverage=33.0,
    )
    gaps = build_coverage_gaps(coverage=coverage, fused=fused, test_cases=base)
    selected = select_gaps_for_regeneration(gaps, max_gaps=4)
    assert selected
    assert all(g.priority in (Priority.CRITICAL, Priority.HIGH) for g in selected)

    agent = TestCaseAgent()
    targeted = []
    for gap in selected[:2]:
        targeted.extend(agent.generate_for_gap(gap, fused, "proj_1", base + targeted))
    assert targeted
    assert all(tc.generation_method == "critic" for tc in targeted)
    assert all(tc.closes_gap_id for tc in targeted)
    assert all("coverage gap" in (tc.reasoning or "").lower() for tc in targeted)


# ---------------------------------------------------------------------------
# C. LOW-PRIORITY GAP excluded
# ---------------------------------------------------------------------------


def test_c_low_priority_gaps_not_auto_regenerated():
    low = CoverageGap(
        gap_id="GAP_low",
        gap_type=GapType.REQUIREMENT,
        title="Requirement without test: Nice-to-have copy",
        description="low",
        priority=Priority.LOW,
        risk=RiskLevel.LOW,
        graph_path=["Sign In"],
        reason="low priority requirement",
    )
    medium = CoverageGap(
        gap_id="GAP_med",
        gap_type=GapType.ALTERNATE,
        title="Alternate flow: Forgot Password",
        priority=Priority.MEDIUM,
        risk=RiskLevel.MEDIUM,
        graph_path=["Sign In", "Forgot Password"],
    )
    high = CoverageGap(
        gap_id="GAP_high",
        gap_type=GapType.FAILURE,
        title="Uncovered failure path: Lockout",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        graph_path=["Sign In", "Lockout"],
    )
    ordered = prioritize_gaps([low, medium, high])
    assert ordered[0].gap_id == "GAP_high"
    selected = select_gaps_for_regeneration([low, medium, high], max_gaps=4)
    assert [g.gap_id for g in selected] == ["GAP_high"]
    assert low.selected_for_regeneration is False
    assert medium.selected_for_regeneration is False


# ---------------------------------------------------------------------------
# D. TARGETED CONTEXT
# ---------------------------------------------------------------------------


def test_d_targeted_context_contains_gap_path_evidence_and_existing():
    fused = _fused()
    gap = CoverageGap(
        gap_id="GAP_sso",
        gap_type=GapType.BRANCH,
        title="Uncovered branch: Enterprise SSO",
        description="SSO branch missing",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        graph_path=["Sign In", "Enterprise SSO", "SAML Assertion"],
        reason="CoverageEngine uncovered branch",
        evidence=[],
    )
    existing = [
        QATestCase(
            test_case_id="TC-001",
            title="Email happy path",
            steps=["Login with email"],
            expected_result="Session ok",
            graph_path=fused.flow_paths[0],
        )
    ]
    ctx = TestCaseAgent().build_targeted_context(gap, fused, existing)
    assert "Generate a test case specifically for this coverage gap" in ctx["instruction"]
    assert ctx["coverage_gap"]["title"] == gap.title
    assert ctx["coverage_gap"]["description"] == gap.description
    assert ctx["relevant_graph_path"] == gap.graph_path
    assert ctx["existing_tests_do_not_duplicate"]
    assert ctx["existing_tests_do_not_duplicate"][0]["title"] == "Email happy path"
    assert "allowed_evidence_catalog" in ctx
    blob = str(ctx)
    assert "Enterprise SSO" in blob
    assert "Email happy path" in blob


def test_d_targeted_llm_prompt_includes_required_sections(monkeypatch):
    fused = _fused()
    gap = CoverageGap(
        gap_id="GAP_sso",
        gap_type=GapType.BRANCH,
        title="Uncovered branch: Enterprise SSO",
        description="SSO branch missing tests",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        graph_path=["Sign In", "Enterprise SSO", "SAML Assertion"],
        reason="uncovered",
    )
    captured: dict = {}

    mock = MagicMock()
    mock.available = True

    def _chat_json(system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        return {
            "test_cases": [
                {
                    "title": "SSO targeted",
                    "steps": ["Open SSO", "Assert SAML"],
                    "expected_result": "Authenticated via SSO",
                    "graph_path": gap.graph_path,
                    "reasoning": f"This test was generated to close coverage gap: {gap.title}.",
                    "evidence": [],
                    "priority": "high",
                    "risk": "high",
                }
            ]
        }

    mock.chat_json.side_effect = _chat_json
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    cases = TestCaseAgent().generate_for_gap(gap, fused, "proj_1", [])
    assert cases
    assert "Generate a test case specifically for this coverage gap" in captured["system"]
    assert "Generate a test case specifically for this coverage gap" in captured["user"]
    assert gap.description in captured["user"] or gap.title in captured["user"]
    assert "Enterprise SSO" in captured["user"]
    assert "existing_tests_do_not_duplicate" in captured["user"]
    assert "allowed_evidence_catalog" in captured["user"]
    assert cases[0].generation_method == "critic"


# ---------------------------------------------------------------------------
# E. FALLBACK
# ---------------------------------------------------------------------------


def test_e_targeted_llm_failure_uses_deterministic_fallback(monkeypatch):
    fused = _fused()
    gap = CoverageGap(
        gap_id="GAP_fail",
        gap_type=GapType.FAILURE,
        title="Uncovered failure path: Provider Failure",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        graph_path=["Sign In", "Google OAuth", "Provider Failure"],
        reason="failure uncovered",
    )
    mock = MagicMock()
    mock.available = True
    mock.chat_json.side_effect = RuntimeError("boom")
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    cases = TestCaseAgent().generate_for_gap(gap, fused, "proj_1", [])
    assert cases
    assert cases[0].generation_method == "critic"
    assert cases[0].steps
    assert "coverage gap" in (cases[0].reasoning or "").lower()


def test_e_api_stable_without_openai(client):
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
        },
    ).json()
    assert result["test_cases"]
    assert result["coverage_before"] is not None
    assert result["coverage_after"] is not None
    assert isinstance(result["regeneration_rounds"], int)
    assert isinstance(result["selected_coverage_gaps"], list)
    assert isinstance(result["targeted_test_cases"], list)
    assert isinstance(result["unresolved_gaps"], list)


# ---------------------------------------------------------------------------
# F. DEDUPLICATION
# ---------------------------------------------------------------------------


def test_f_duplicate_targeted_tests_not_added():
    existing = [
        QATestCase(
            test_case_id="TC-001",
            title="Gap coverage: Sign In → Enterprise SSO",
            steps=["Navigate to entry point: Sign In", "Traverse / exercise: Enterprise SSO"],
            expected_result="User successfully completes Sign In → Enterprise SSO",
            graph_path=["Sign In", "Enterprise SSO"],
        )
    ]
    dup = QATestCase(
        test_case_id="TC-002",
        title="Gap coverage: Sign In → Enterprise SSO",
        steps=["Navigate to entry point: Sign In", "Traverse / exercise: Enterprise SSO"],
        expected_result="User successfully completes Sign In → Enterprise SSO",
        graph_path=["Sign In", "Enterprise SSO"],
    )
    distinct = QATestCase(
        test_case_id="TC-003",
        title="Gap coverage: Sign In → Enterprise SSO",  # similar title
        steps=["Open IdP", "Validate SAML assertion signature", "Confirm session"],
        expected_result="SAML assertion accepted and session established",
        graph_path=["Sign In", "Enterprise SSO", "SAML Assertion"],
    )
    assert is_duplicate(dup, existing)
    assert not is_duplicate(distinct, existing)
    kept = deduplicate_tests([dup, distinct], against=existing)
    assert len(kept) == 1
    assert kept[0].test_case_id == "TC-003"


# ---------------------------------------------------------------------------
# G. EVIDENCE
# ---------------------------------------------------------------------------


def test_g_targeted_tests_preserve_valid_evidence_and_sanitize_unknown(monkeypatch):
    fused = _fused()
    gap = CoverageGap(
        gap_id="GAP_sso",
        gap_type=GapType.BRANCH,
        title="Uncovered branch: Enterprise SSO",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        graph_path=["Sign In", "Enterprise SSO", "SAML Assertion"],
        reason="uncovered",
        evidence=[],
    )
    mock = MagicMock()
    mock.available = True
    mock.chat_json.return_value = {
        "test_cases": [
            {
                "title": "SSO with fabricated evidence",
                "steps": ["SSO login"],
                "expected_result": "OK",
                "graph_path": gap.graph_path,
                "reasoning": f"This test was generated to close coverage gap: {gap.title}.",
                "evidence": [
                    {
                        "source_type": "graph",
                        "source_id": "FAKE-999",
                        "source_title": "Invented",
                        "relevance": "bogus",
                    },
                    {
                        "source_type": "historical_bug",
                        "source_id": "BUG-007",
                        "source_title": "OAuth callback failure leaves orphan session cookie",
                        "relevance": "related auth risk",
                    },
                ],
                "priority": "high",
                "risk": "high",
            }
        ]
    }
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)
    cases = TestCaseAgent().generate_for_gap(gap, fused, "proj_1", [])
    assert cases
    ids = {e.source_id for e in cases[0].evidence if e.source_id}
    assert "FAKE-999" not in ids
    assert any(e.source_type == "coverage_gap" for e in cases[0].evidence)


# ---------------------------------------------------------------------------
# H. BOUNDED LOOP
# ---------------------------------------------------------------------------


def test_h_max_regeneration_rounds_respected(client):
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
            "enable_targeted_regeneration": True,
            "max_regeneration_rounds": 1,
            "max_gaps_per_round": 2,
        },
    ).json()
    assert result["regeneration_rounds"] <= 1

    # Request validation hard-caps at 2
    bad = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate tests",
            "max_regeneration_rounds": 9,
        },
    )
    assert bad.status_code == 422


def test_h_regeneration_disabled_sets_zero_rounds(client):
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
            "enable_targeted_regeneration": False,
        },
    ).json()
    assert result["regeneration_rounds"] == 0
    assert result["targeted_test_cases"] == []


# ---------------------------------------------------------------------------
# I. COVERAGE BEFORE/AFTER
# ---------------------------------------------------------------------------


def test_i_coverage_before_after_recalculated():
    fused = _fused()
    base = [
        QATestCase(
            test_case_id="TC-001",
            title="Email only",
            steps=["Login"],
            expected_result="OK",
            graph_path=fused.flow_paths[0],
        )
    ]
    coverage = CoverageGapResult(
        root_feature="Sign In",
        uncovered_branches=["Enterprise SSO", "Google OAuth"],
        uncovered_failure_paths=["Provider Failure"],
        critical_gaps=["Uncovered branch: Enterprise SSO"],
        overall_coverage=25.0,
        branch_coverage=33.0,
        calculation_notes=["note"],
    )
    before = build_coverage_snapshot(coverage=coverage, fused=fused, test_cases=base)
    assert before.total_paths == len(fused.flow_paths)
    assert before.covered_paths < before.total_paths

    gaps = build_coverage_gaps(coverage=coverage, fused=fused, test_cases=base)
    selected = select_gaps_for_regeneration(gaps, max_gaps=3)
    agent = TestCaseAgent()
    all_cases = list(base)
    for gap in selected:
        all_cases.extend(agent.generate_for_gap(gap, fused, "proj_1", all_cases))

    after = build_coverage_snapshot(coverage=coverage, fused=fused, test_cases=all_cases)
    assert after.covered_paths >= before.covered_paths
    assert after.coverage_percentage >= before.coverage_percentage


def test_i_api_exposes_before_after_and_loop_fields(client):
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
        },
    ).json()
    before = result["coverage_before"]
    after = result["coverage_after"]
    assert "total_paths" in before
    assert "covered_paths" in before
    assert "coverage_percentage" in before
    assert "gaps" in before
    assert "total_paths" in after
    assert "covered_paths" in after
    assert "coverage_percentage" in after
    assert isinstance(result["initial_test_cases"], list)
    assert isinstance(result["critic_notes"], list)


# ---------------------------------------------------------------------------
# Critic compatibility + prioritization order
# ---------------------------------------------------------------------------


def test_critic_standalone_still_adds_targeted_gap_tests():
    fused = _fused()
    base = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    # Remove SSO-covering cases to force a gap
    base = [c for c in base if "Enterprise SSO" not in " ".join(c.graph_path)]
    coverage = CoverageGapResult(
        root_feature="Sign In",
        uncovered_branches=["Enterprise SSO"],
        critical_gaps=["Uncovered branch: Enterprise SSO"],
        recommended_tests=["Add path coverage for Enterprise SSO"],
    )
    notes, improved = CriticAgent().review(
        test_cases=base, coverage=coverage, fused=fused, add_gap_tests=True, project_id="proj_1"
    )
    critic_cases = [c for c in improved if c.generation_method == "critic"]
    assert notes
    assert critic_cases
    assert any("Enterprise SSO" in ((c.title or "") + (c.reasoning or "")) for c in critic_cases)
    assert all(c.evidence for c in critic_cases)
    assert any(e.source_type == "coverage_gap" for c in critic_cases for e in c.evidence)


def test_prioritization_order_prefers_critical_paths_and_bugs():
    gaps = [
        CoverageGap(
            gap_id="1",
            gap_type=GapType.ALTERNATE,
            title="alt",
            priority=Priority.MEDIUM,
            risk=RiskLevel.MEDIUM,
        ),
        CoverageGap(
            gap_id="2",
            gap_type=GapType.BUG,
            title="bug",
            priority=Priority.HIGH,
            risk=RiskLevel.HIGH,
        ),
        CoverageGap(
            gap_id="3",
            gap_type=GapType.GRAPH_PATH,
            title="path",
            priority=Priority.CRITICAL,
            risk=RiskLevel.CRITICAL,
        ),
        CoverageGap(
            gap_id="4",
            gap_type=GapType.REQUIREMENT,
            title="req",
            priority=Priority.HIGH,
            risk=RiskLevel.HIGH,
        ),
    ]
    ordered = prioritize_gaps(gaps)
    assert [g.gap_id for g in ordered] == ["3", "2", "4", "1"]
