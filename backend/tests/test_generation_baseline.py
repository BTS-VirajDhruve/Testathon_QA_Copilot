"""Regression baseline for deterministic TestCaseAgent generation.

Locks current heuristic/path-based behavior with OpenAI disabled so future
LLM-first changes can be compared against a stable contract.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.specialists import TestCaseAgent
from app.models.schemas import FusedContext
from app.models.schemas import TestCase as QATestCase


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


def _sample_fused() -> FusedContext:
    paths = [
        ["Sign In", "Email + Password", "Valid Credentials"],
        ["Sign In", "Email + Password", "Invalid Password"],
        ["Sign In", "Google OAuth", "Provider Failure"],
        ["Sign In", "Enterprise SSO", "SAML"],
    ]
    return FusedContext(
        feature_context={
            "id": "feature_signin",
            "name": "Sign In",
            "type": "Feature",
            "description": "Auth entry",
            "critical": True,
            "branches": [
                "Email + Password",
                "Google OAuth",
                "Enterprise SSO",
                "Self Registration",
            ],
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
                "includes_external_dependency": False,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FAILURE_PATH"],
            },
            {
                "path": paths[2],
                "is_failure_path": True,
                "includes_external_dependency": True,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FAILURE_PATH"],
            },
            {
                "path": paths[3],
                "is_failure_path": False,
                "includes_external_dependency": False,
                "relationships": ["HAS_AUTHENTICATION_METHOD", "HAS_FLOW"],
            },
        ],
        semantic_context=[
            {
                "id": "chunk_1",
                "content": "MFA retry limit is 5.",
                "score": 0.8,
                "source_reference": "authentication_requirements.md#chunk-0",
            }
        ],
        existing_coverage=[],
        historical_risks=[
            {
                "bug_id": "BUG-007",
                "title": "OAuth callback failure leaves orphan session cookie",
                "severity": "high",
                "affected_components": ["Google OAuth", "Callback"],
                "graph_path": ["Sign In", "Google OAuth", "Callback"],
            }
        ],
        external_context=[],
    )


def test_testcase_agent_deterministic_path_baseline():
    """Primary generator emits one structured case per fused flow path without LLM."""
    from app.services.openai_service import get_openai_service

    assert get_openai_service().available is False

    agent = TestCaseAgent()
    fused = _sample_fused()
    cases = agent.generate(
        query="Generate comprehensive QA coverage for Sign In.",
        fused=fused,
        project_id="project_baseline",
    )

    assert len(cases) == len(fused.flow_paths)
    assert all(isinstance(c, QATestCase) for c in cases)
    assert [c.test_case_id for c in cases] == ["TC-001", "TC-002", "TC-003", "TC-004"]

    for case, path in zip(cases, fused.flow_paths, strict=True):
        assert case.graph_path == path
        assert case.steps
        assert case.expected_result
        assert case.testing_technique
        assert case.preconditions
        assert case.test_data
        assert "User-provided system flow graph" in case.source_references
        assert case.project_id == "project_baseline"
        assert case.feature_id == "feature_signin"
        assert case.graph_reasoning
        # No LLM enrichment markers when OpenAI unavailable
        assert "LLM reasoning" not in case.source_references

    # Title conventions from deterministic helper
    assert cases[0].title.startswith("Successful journey:")
    assert cases[1].title.startswith("Graceful handling:")
    assert cases[2].title.startswith("Graceful handling:")
    assert cases[2].category == "security"
    assert cases[2].risk.value == "high"

    # Failure path steps include failure inject/observe wording
    assert any("failure" in s.lower() for s in cases[1].steps)


def test_testcase_agent_marks_existing_coverage_titles():
    fused = _sample_fused()
    fused.existing_coverage = [
        {
            "test_case_id": "TC-SEED",
            "title": "Successful journey: Sign In → Email + Password → Valid Credentials",
            "graph_path": fused.flow_paths[0],
            "priority": "high",
        }
    ]
    cases = TestCaseAgent().generate("Generate tests", fused, "project_baseline")
    assert cases[0].title.startswith("Verify existing coverage:")


def test_copilot_query_baseline_schema_contract(client):
    """API generation response keeps the fields the UI and agents depend on."""
    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
            "include_critic": True,
        },
    ).json()

    assert result["intent"] in {"test_generation", "general_qa"}
    assert result["retrieval_plan"]["use_user_flow_graph"] is True
    assert result["retrieval_plan"]["use_graph_rag"] is True
    assert "flow_paths" in result["fused_context_summary"] or result["fused_context_summary"]

    required_tc_fields = {
        "test_case_id",
        "title",
        "category",
        "priority",
        "risk",
        "preconditions",
        "test_data",
        "steps",
        "expected_result",
        "testing_technique",
        "graph_path",
        "graph_reasoning",
        "source_references",
        "confidence",
        "assumptions",
    }
    assert len(result["test_cases"]) >= len(result["discovered_graph_paths"]) or len(
        result["test_cases"]
    ) >= 8
    for tc in result["test_cases"]:
        assert required_tc_fields.issubset(tc.keys())
        assert isinstance(tc["graph_path"], list) and tc["graph_path"]
        assert isinstance(tc["steps"], list) and tc["steps"]

    # Critic may add cases, but baseline still exposes trace + evidence
    assert result["execution_trace"]
    assert any("Test Cases Generated" in step["step"] for step in result["execution_trace"])
    assert result["evidence"]
    assert "User-provided system flow graph" in result["evidence"]
