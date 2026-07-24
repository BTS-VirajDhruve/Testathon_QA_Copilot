"""Evidence / explainability / traceability tests (Phase 3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agents.evidence import (
    build_evidence_catalog,
    sanitize_evidence,
)
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
            {
                "node_id": "svc_session",
                "entity": "Session Service",
                "type": "Service",
                "description": "Creates sessions",
                "inferred": False,
                "source_type": "user_input",
                "edge_id": "edge_1",
                "relationship": "CALLS",
            },
        ],
        semantic_context=[
            {
                "id": "chunk_req_1",
                "document_id": "doc_auth",
                "content": "MFA retry limit is 5 attempts.",
                "score": 0.91,
                "source_reference": "authentication_requirements.md#chunk-0",
                "metadata": {
                    "filename": "authentication_requirements.md",
                    "document_id": "doc_auth",
                },
                "source_type": "requirement",
            }
        ],
        existing_coverage=[
            {
                "test_case_id": "TC-SEED",
                "title": "Successful email/password login",
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


def test_source_identity_preserved_in_catalog():
    fused = _fused()
    catalog = build_evidence_catalog(fused)
    ids = {(e.source_type, e.source_id) for e in catalog if e.source_id}
    assert ("graph", "feature_signin") in ids
    assert ("graph", "n1→n2→n3") in ids or ("graph", "n2") in ids
    assert ("requirement", "chunk_req_1") in ids
    assert ("existing_test", "TC-SEED") in ids
    assert ("historical_bug", "BUG-007") in ids


def test_sanitize_drops_fabricated_source_ids():
    fused = _fused()
    catalog = build_evidence_catalog(fused)
    claimed = [
        {"source_type": "historical_bug", "source_id": "BUG-007", "source_title": "real"},
        {"source_type": "historical_bug", "source_id": "BUG-FAKE-999", "source_title": "invented"},
        {"source_type": "requirement", "source_id": "chunk_req_1", "source_title": "auth"},
    ]
    cleaned = sanitize_evidence(claimed, catalog)
    cleaned_ids = {e.source_id for e in cleaned}
    assert "BUG-007" in cleaned_ids
    assert "chunk_req_1" in cleaned_ids
    assert "BUG-FAKE-999" not in cleaned_ids


def test_llm_traceability_preserves_reasoning_and_real_evidence(monkeypatch):
    fused = _fused()
    mock = MagicMock()
    mock.available = True
    mock.chat_json.return_value = {
        "test_cases": [
            {
                "title": "OAuth provider failure regression",
                "category": "regression",
                "priority": "high",
                "risk": "high",
                "steps": ["Start OAuth", "Force provider failure", "Check session"],
                "expected_result": "No orphan session",
                "graph_path": ["Sign In", "Google OAuth", "Provider Failure"],
                "reasoning": "Covers failure branch and BUG-007 pattern.",
                "graph_reasoning": "Covers failure branch and BUG-007 pattern.",
                "evidence": [
                    {
                        "source_type": "historical_bug",
                        "source_id": "BUG-007",
                        "source_title": "OAuth callback failure leaves orphan session cookie",
                        "relevance": "Historical defect on OAuth path",
                    },
                    {
                        "source_type": "graph",
                        "source_id": "n1→n4→n5",
                        "source_title": "Sign In → Google OAuth → Provider Failure",
                        "relevance": "Exact discovered path",
                    },
                    {
                        "source_type": "requirement",
                        "source_id": "FAKE-CHUNK",
                        "source_title": "Invented",
                        "relevance": "should be dropped",
                    },
                ],
                "confidence": "high",
                "assumptions": [],
            }
        ]
    }
    monkeypatch.setattr("app.agents.specialists.get_openai_service", lambda: mock)

    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert len(cases) == 1
    case = cases[0]
    assert case.generation_method == "llm"
    assert case.graph_path == ["Sign In", "Google OAuth", "Provider Failure"]
    assert case.reasoning and "BUG-007" in case.reasoning
    evidence_ids = {e.source_id for e in case.evidence}
    assert "BUG-007" in evidence_ids
    assert "n1→n4→n5" in evidence_ids
    assert "FAKE-CHUNK" not in evidence_ids


def test_fallback_traceability():
    fused = _fused()
    cases = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    assert cases
    assert all(c.generation_method == "deterministic_fallback" for c in cases)
    assert all(c.reasoning for c in cases)
    assert all(c.evidence for c in cases)
    assert any(e.source_type == "graph" for c in cases for e in c.evidence)


def test_critic_traceability():
    fused = _fused()
    base = TestCaseAgent().generate("Generate tests", fused, "proj_1")
    coverage = CoverageGapResult(
        root_feature="Sign In",
        uncovered_branches=["Enterprise SSO"],
        critical_gaps=["Uncovered branch: Enterprise SSO"],
        recommended_tests=["Add path coverage for Enterprise SSO"],
    )
    notes, improved = CriticAgent().review(test_cases=base, coverage=coverage, fused=fused)
    critic_cases = [c for c in improved if c.generation_method == "critic"]
    assert critic_cases
    assert any("Enterprise SSO" in ((c.title or "") + (c.reasoning or "")) for c in critic_cases)
    assert all(c.evidence for c in critic_cases)
    assert any(e.source_type == "coverage_gap" for c in critic_cases for e in c.evidence)
    assert notes


def test_api_response_serializes_evidence_fields(client):
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
    for tc in result["test_cases"]:
        assert "generation_method" in tc
        assert "evidence" in tc
        assert isinstance(tc["evidence"], list)
        for e in tc["evidence"]:
            assert "source_type" in e
            assert not str(e.get("source_id") or "").startswith("FAKE-")


def test_llm_context_includes_allowed_evidence_catalog():
    fused = _fused()
    ctx = TestCaseAgent().build_llm_context("Generate tests", fused)
    assert "allowed_evidence_catalog" in ctx
    catalog_ids = {
        e.get("source_id") for e in ctx["allowed_evidence_catalog"] if e.get("source_id")
    }
    assert "BUG-007" in catalog_ids
    assert "chunk_req_1" in catalog_ids
    assert "TC-SEED" in catalog_ids
    paths = ctx["discovered_graph_paths"]
    assert isinstance(paths, list)
    assert paths[0].get("node_ids")
    assert paths[0].get("path_id")
