"""LLM-first TestCaseAgent tests — success, context quality, and fallbacks."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agents.specialists import CriticAgent, TestCaseAgent
from app.models.schemas import CoverageGapResult, FusedContext


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


def _fused() -> FusedContext:
    paths = [
        ["Sign In", "Email + Password", "Valid Credentials"],
        ["Sign In", "Google OAuth", "Provider Failure"],
    ]
    return FusedContext(
        feature_context={
            "id": "feature_signin",
            "name": "Sign In",
            "type": "Feature",
            "branches": ["Email + Password", "Google OAuth"],
        },
        flow_paths=paths,
        graph_context=[
            {
                "path": paths[0],
                "is_failure_path": False,
                "includes_external_dependency": False,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FLOW"],
            },
            {
                "path": paths[1],
                "is_failure_path": True,
                "includes_external_dependency": True,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FAILURE_PATH"],
            },
            {
                "entity": "Session Service",
                "type": "Service",
                "description": "Creates sessions",
                "inferred": False,
                "source_type": "user_input",
            },
        ],
        semantic_context=[
            {
                "id": "chunk_1",
                "content": "MFA retry limit is 5 attempts.",
                "score": 0.91,
                "source_reference": "authentication_requirements.md#chunk-0",
                "metadata": {"filename": "authentication_requirements.md"},
            }
        ],
        existing_coverage=[
            {
                "test_case_id": "TC-SEED",
                "title": "Successful email/password login",
                "graph_path": paths[0],
                "priority": "high",
            }
        ],
        historical_risks=[
            {
                "bug_id": "BUG-007",
                "title": "OAuth callback failure leaves orphan session cookie",
                "severity": "high",
                "affected_components": ["Google OAuth"],
                "graph_path": ["Sign In", "Google OAuth", "Callback"],
            }
        ],
        external_context=[],
    )


def _valid_llm_payload() -> dict[str, Any]:
    return {
        "test_cases": [
            {
                "title": "Successful password login with MFA policy awareness",
                "category": "functional",
                "priority": "high",
                "risk": "medium",
                "preconditions": ["User has valid credentials"],
                "test_data": {"email": "qa@example.com"},
                "steps": [
                    "Open Sign In",
                    "Enter email/password",
                    "Complete login",
                ],
                "expected_result": "Authenticated session created",
                "testing_technique": "Path-based functional testing",
                "graph_path": ["Sign In", "Email + Password", "Valid Credentials"],
                "graph_reasoning": "Covers happy-path password authentication.",
                "source_references": [
                    "User-provided system flow graph",
                    "authentication_requirements.md#chunk-0",
                ],
                "confidence": "high",
                "assumptions": [],
            },
            {
                "title": "Regression: OAuth provider failure must not leave orphan session",
                "category": "regression",
                "priority": "high",
                "risk": "high",
                "preconditions": ["Google OAuth configured"],
                "test_data": {"provider": "Google"},
                "steps": [
                    "Start Google OAuth",
                    "Force provider failure",
                    "Inspect cookies/session state",
                ],
                "expected_result": "No orphan session cookie; recoverable error shown",
                "testing_technique": "Historical defect regression",
                "graph_path": ["Sign In", "Google OAuth", "Provider Failure"],
                "graph_reasoning": "Mapped to failure path and BUG-007.",
                "source_references": ["BUG-007", "User-provided system flow graph"],
                "confidence": "high",
                "assumptions": ["Provider failure is injectable in test env"],
            },
        ]
    }


def test_llm_success_uses_structured_context(monkeypatch):
    captured: dict[str, Any] = {}

    mock = MagicMock()
    mock.available = True

    def fake_chat_json(system: str, user: str, **kwargs):
        captured["system"] = system
        captured["user"] = user
        captured["kwargs"] = kwargs
        assert kwargs.get("strict") is True
        return _valid_llm_payload()

    mock.chat_json.side_effect = fake_chat_json
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    agent = TestCaseAgent()
    fused = _fused()
    cases = agent.generate("Generate comprehensive QA coverage for Sign In.", fused, "proj_1")

    assert mock.chat_json.called
    assert len(cases) == 2
    assert all(c.generation_method == "llm" for c in cases)
    assert cases[0].test_case_id == "TC-001"
    assert cases[0].steps
    assert cases[0].graph_path

    # Context quality: fused evidence present in prompt
    user_prompt = captured["user"]
    assert "Generate comprehensive QA coverage for Sign In." in user_prompt
    assert "Sign In" in user_prompt
    assert "Valid Credentials" in user_prompt
    assert "Provider Failure" in user_prompt
    assert "MFA retry limit is 5 attempts." in user_prompt
    assert "authentication_requirements.md#chunk-0" in user_prompt
    assert "Successful email/password login" in user_prompt
    assert "BUG-007" in user_prompt
    assert "HAS_AUTHENTICATION_METHOD" in user_prompt or "discovered_graph_paths" in user_prompt


def test_build_llm_context_sections_preserve_empty_as_unavailable():
    agent = TestCaseAgent()
    fused = FusedContext(
        feature_context={"id": "f1", "name": "Checkout", "branches": []},
        flow_paths=[],
        graph_context=[],
        semantic_context=[],
        existing_coverage=[],
        historical_risks=[],
        external_context=[],
    )
    ctx = agent.build_llm_context("Generate tests", fused)
    assert ctx["user_request"] == "Generate tests"
    assert ctx["requirements"] == "unavailable"
    assert ctx["existing_tests"] == "unavailable"
    assert ctx["historical_bugs"] == "unavailable"
    assert ctx["risk_context"] == "unavailable"
    assert ctx["discovered_graph_paths"] == "unavailable"


def test_llm_api_exception_falls_back(monkeypatch):
    mock = MagicMock()
    mock.available = True
    mock.chat_json.side_effect = TimeoutError("timeout")
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert len(cases) == len(fused.flow_paths)
    assert all(c.generation_method == "deterministic_fallback" for c in cases)
    assert mock.chat_json.call_count == TestCaseAgent.MAX_LLM_ATTEMPTS


def test_llm_malformed_json_structure_falls_back(monkeypatch):
    mock = MagicMock()
    mock.available = True
    mock.chat_json.return_value = {"not_test_cases": []}
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert all(c.generation_method == "deterministic_fallback" for c in cases)


def test_llm_invalid_testcase_items_fall_back_when_none_valid(monkeypatch):
    mock = MagicMock()
    mock.available = True
    mock.chat_json.return_value = {
        "test_cases": [
            {"title": "", "steps": []},  # invalid / skipped
            {"priority": "not-a-real-priority", "title": "x", "steps": ["a"]},  # pydantic fail
        ]
    }
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert all(c.generation_method == "deterministic_fallback" for c in cases)


def test_llm_empty_response_falls_back(monkeypatch):
    mock = MagicMock()
    mock.available = True
    mock.chat_json.return_value = {"test_cases": []}
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert len(cases) == 2
    assert cases[0].generation_method == "deterministic_fallback"


def test_no_api_key_uses_deterministic_generator():
    from app.services.openai_service import get_openai_service

    assert get_openai_service().available is False
    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert len(cases) == 2
    assert all(c.generation_method == "deterministic_fallback" for c in cases)


def test_critic_compatibility_with_llm_cases(monkeypatch):
    mock = MagicMock()
    mock.available = True
    mock.chat_json.return_value = _valid_llm_payload()
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    coverage = CoverageGapResult(
        root_feature="Sign In",
        uncovered_branches=["Enterprise SSO"],
        critical_gaps=["Uncovered branch: Enterprise SSO"],
        recommended_tests=["Add path coverage for Enterprise SSO"],
    )
    notes, improved = CriticAgent().review(test_cases=cases, coverage=coverage, fused=fused)
    assert notes
    assert len(improved) >= len(cases)
    assert all(tc.graph_path for tc in improved)


def test_copilot_api_still_works_without_openai(client):
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
    assert all(tc.get("graph_path") for tc in result["test_cases"])
    # Without OpenAI key, generation_method should be deterministic_fallback
    # (critic-added cases may omit or inherit — primary generated set should include it)
    methods = {tc.get("generation_method") for tc in result["test_cases"]}
    assert "deterministic_fallback" in methods or None in methods
