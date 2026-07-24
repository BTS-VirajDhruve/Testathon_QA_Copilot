"""Phase 5 — Demo polish, seed reliability, and productization tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


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


def test_demo_seed_repeatable_and_idempotent(client):
    first = client.post("/api/demo/seed").json()
    second = client.post("/api/demo/seed").json()

    assert first["project_id"] == second["project_id"]
    assert second["reused_project"] is True
    assert second["graph_rewritten"] is False
    assert first["existing_tests"] == second["existing_tests"] == 3
    assert first["historical_bugs"] == second["historical_bugs"] == 3
    assert "Microsoft Enterprise SSO" in (second.get("high_risk_uncovered_hint") or "")

    tests = client.get(f"/api/projects/{first['project_id']}/tests").json()
    curated = [t for t in tests if t["test_case_id"] in {"TC-001", "TC-002", "TC-003"}]
    assert len(curated) == 3
    assert "TC-004" not in {t["test_case_id"] for t in tests}

    bugs = client.get(f"/api/projects/{first['project_id']}/bugs").json()
    bug_ids = {b["bug_id"] for b in bugs}
    assert {"BUG-007", "BUG-012", "BUG-019"}.issubset(bug_ids)
    assert len([b for b in bugs if b["bug_id"] in {"BUG-007", "BUG-012", "BUG-019"}]) == 3


def test_demo_seed_contains_uncovered_high_risk_branch(client):
    seed = client.post("/api/demo/seed").json()
    flow = client.get(f"/api/projects/{seed['project_id']}/flow").json()
    names = {n["name"] for n in flow["nodes"]}
    assert "Sign In" in names
    assert "Microsoft Enterprise SSO" in names
    assert "SSO Timeout" in names
    assert "Account Lockout" in names

    coverage = client.get(f"/api/projects/{seed['project_id']}/coverage").json()
    # Seed leaves SSO largely uncovered by existing tests
    uncovered = " ".join(coverage.get("uncovered_branches") or []).lower()
    critical = " ".join(coverage.get("critical_gaps") or []).lower()
    assert "microsoft enterprise sso" in uncovered or "microsoft enterprise sso" in critical or "sso" in critical


def test_health_exposes_runtime_diagnostics_without_secrets(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert "openai_configured" in health
    assert "openai_client_ready" in health
    assert "vector_store_mode" in health
    assert "graph_store_mode" in health
    blob = str(health).lower()
    assert "sk-" not in blob
    assert "api_key" not in blob


def test_full_copilot_workflow_without_openai(client):
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": seed["demo_query"],
            "root_feature": "Sign In",
            "include_critic": True,
            "enable_targeted_regeneration": True,
            "max_regeneration_rounds": 1,
        },
    ).json()

    assert result["test_cases"]
    assert result["execution_trace"]
    assert result["coverage_before"] is not None
    assert result["coverage_after"] is not None
    assert result["generation_backend"] in {
        "deterministic_fallback",
        "mixed",
        "openai",
    }
    assert "runtime_diagnostics" in result
    assert result["runtime_diagnostics"].get("openai_configured") is False
    assert isinstance(result["duplicates_removed"], int)
    # Evidence remains valid / serializable
    for tc in result["test_cases"]:
        assert "evidence" in tc
        for e in tc["evidence"] or []:
            assert "source_type" in e
            assert not str(e.get("source_id") or "").startswith("FAKE-")


def test_full_copilot_workflow_with_mocked_openai(client, monkeypatch):
    seed = client.post("/api/demo/seed").json()

    mock = MagicMock()
    mock.available = True
    mock.configured = True
    mock.last_chat_backend = "openai"
    mock.last_embed_backend = "openai"
    mock.diagnostics.return_value = {
        "openai_configured": True,
        "openai_client_ready": True,
        "demo_fallback_enabled": True,
        "last_chat_backend": "openai",
        "last_embed_backend": "openai",
    }
    mock.chat_json.return_value = {
        "test_cases": [
            {
                "title": "SSO timeout actionable error",
                "category": "negative",
                "priority": "high",
                "risk": "high",
                "steps": ["Start Microsoft Enterprise SSO", "Force IdP timeout", "Observe UI"],
                "expected_result": "Actionable timeout error; no infinite spinner",
                "graph_path": ["Sign In", "Microsoft Enterprise SSO", "SSO Timeout"],
                "reasoning": "Covers high-risk uncovered SSO timeout path",
                "evidence": [],
                "confidence": "high",
            },
            {
                "title": "OAuth invalid state rejected",
                "category": "security",
                "priority": "high",
                "risk": "high",
                "steps": ["Begin Google OAuth", "Tamper callback state", "Submit callback"],
                "expected_result": "Invalid state is rejected; no session created",
                "graph_path": ["Sign In", "Google OAuth", "Callback"],
                "reasoning": "Regression for OAuth callback accepted invalid state",
                "evidence": [{"source_type": "historical_bug", "source_id": "BUG-007", "source_title": "OAuth callback accepted invalid state"}],
                "confidence": "high",
            },
        ]
    }

    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)
    monkeypatch.setattr("app.services.openai_service.get_openai_service", lambda: mock)
    monkeypatch.setattr("app.rag.retrieval.get_openai_service", lambda: mock)

    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": seed["demo_query"],
            "root_feature": "Sign In",
        },
    ).json()

    assert result["test_cases"]
    assert result["coverage_before"] is not None
    assert result["coverage_after"] is not None
    assert any(tc.get("generation_method") in {"llm", "critic", "deterministic_fallback"} for tc in result["test_cases"])
    # Response remains JSON-serializable (already via .json())
    assert "selected_coverage_gaps" in result
    assert "unresolved_gaps" in result


def test_coverage_loop_no_gaps_when_disabled(client):
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
    assert result["coverage_before"] is not None


def test_demo_copilot_loop_reserves_high_risk_for_targeted(client):
    """Demo seed + curated query must show Initial → Gaps → Targeted (not 100% after initial)."""
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": seed["demo_query"],
            "root_feature": "Sign In",
            "include_critic": True,
            "enable_targeted_regeneration": True,
            "max_regeneration_rounds": 1,
        },
    ).json()
    assert result["intent"] == "test_generation"
    assert result["initial_test_cases"]
    assert result["coverage_before"] is not None
    assert result["coverage_after"] is not None
    # Deterministic initial gen reserves SSO Timeout / Account Lockout for critic
    assert result["coverage_before"]["coverage_percentage"] < 100.0
    assert result["selected_coverage_gaps"] or result["targeted_test_cases"]
    if result["targeted_test_cases"]:
        assert result["regeneration_rounds"] >= 1
        assert all(tc.get("generation_method") == "critic" for tc in result["targeted_test_cases"])
        assert all(tc.get("closes_gap_id") or tc.get("closes_gap_title") for tc in result["targeted_test_cases"])
        assert result["coverage_after"]["covered_paths"] >= result["coverage_before"]["covered_paths"]
    # Trace honesty: skipped or complete targeted step is present
    steps = " | ".join(s["step"] for s in result["execution_trace"])
    assert "Initial Test Generation" in steps
    assert "Critic Review" in steps
    assert "Coverage Gap" in steps or "Gap Prioritization" in steps
    assert result["generation_backend"] in {"deterministic_fallback", "mixed", "openai"}

