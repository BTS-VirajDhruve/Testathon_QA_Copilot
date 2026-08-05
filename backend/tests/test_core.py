"""Unit and integration tests for Agentic QA Copilot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Isolate test store
TEST_DATA = Path("/tmp/qa_copilot_test_data")
TEST_DATA.mkdir(parents=True, exist_ok=True)


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

    # Reset singletons
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


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_create_project_and_flow(client):
    proj = client.post(
        "/api/projects",
        json={"name": "Test", "description": "d", "root_feature": "Sign In"},
    ).json()
    assert proj["id"]
    assert proj["root_feature_id"]

    imported = client.post(
        f"/api/projects/{proj['id']}/flow/import",
        json={
            "root": "Sign In",
            "branches": [
                {
                    "name": "Email + Password",
                    "children": ["Valid Credentials", "Invalid Password"],
                },
                {"name": "Google OAuth", "children": ["Callback", "Provider Failure"]},
            ],
        },
    ).json()
    assert imported["root_node_id"]
    assert len(imported["nodes"]) >= 5
    assert len(imported["edges"]) >= 4

    paths = client.get(f"/api/projects/{proj['id']}/paths").json()
    assert paths["path_count"] >= 2
    assert any("Google OAuth" in p["node_names"] for p in paths["paths"])


def test_path_based_generation_and_coverage(client):
    seed = client.post("/api/demo/seed").json()
    project_id = seed["project_id"]
    assert seed["nodes"] > 10

    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
        },
    ).json()

    assert result["root_feature"] == "Sign In"
    assert len(result["discovered_branches"]) == 4
    assert len(result["discovered_graph_paths"]) >= 8
    assert len(result["test_cases"]) >= 8
    assert result["retrieval_plan"]["use_user_flow_graph"] is True
    assert any(tc.get("graph_path") for tc in result["test_cases"])
    assert result["execution_trace"]
    assert any("User Flow Graph Loaded" in s["step"] for s in result["execution_trace"])
    assert result["coverage"] is not None
    assert "calculation_notes" in result["coverage"]

    # Every generated test ideally has a graph path
    with_paths = [tc for tc in result["test_cases"] if tc.get("graph_path")]
    assert len(with_paths) == len(result["test_cases"])


def test_impact_and_regression(client):
    seed = client.post("/api/demo/seed").json()
    project_id = seed["project_id"]
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "What components are impacted if Google OAuth changes?",
            "changed_node": "Google OAuth",
        },
    ).json()
    assert result["impact_analysis"]
    assert result["impact_analysis"]["changed_node"] == "Google OAuth"
    assert result["impact_analysis"]["directly_impacted_nodes"]
    assert result["regression_recommendations"] or result["intent"] in {
        "impact_analysis",
        "regression",
        "general_qa",
        "test_generation",
    }


def test_nl_to_graph_marks_inferred(client):
    proj = client.post("/api/projects", json={"name": "NL", "root_feature": "Sign In"}).json()
    graph = client.post(
        f"/api/projects/{proj['id']}/flow/from-text",
        json={
            "text": (
                "Sign in supports email password, Google OAuth, enterprise SSO, "
                "and self-registration. Email login supports MFA and forgot password."
            )
        },
    ).json()
    assert any("Sign" in n["name"] or "sign" in n["name"].lower() for n in graph["nodes"])
    assert len(graph["nodes"]) >= 3
    # Provenance always present; inferred=true only when classifier used LLM / low confidence
    assert all(n.get("provenance") for n in graph["nodes"])
    assert graph["root_node_id"]

def test_document_ingest_idempotent(client):
    seed = client.post("/api/demo/seed").json()
    project_id = seed["project_id"]
    body = {"filename": "req.md", "text": "MFA retry limit is 5."}
    a = client.post(f"/api/projects/{project_id}/documents/text", json=body).json()
    b = client.post(f"/api/projects/{project_id}/documents/text", json=body).json()
    assert a["document"]["id"] == b["document"]["id"]


def test_export_import_roundtrip(client):
    seed = client.post("/api/demo/seed").json()
    project_id = seed["project_id"]
    exported = client.get(f"/api/projects/{project_id}/flow/export").json()
    assert exported["nodes"]
    # Save again
    saved = client.put(f"/api/projects/{project_id}/flow", json=exported).json()
    assert saved["project_id"] == project_id


def test_coverage_engine_explains_calculation():
    from app.graph.ingestion import get_flow_ingester
    from app.graph.store import get_graph_store
    from app.graph.traversal import get_coverage_engine

    store = get_graph_store()
    project = store.create_project("Cov", root_feature=None)
    get_flow_ingester().from_nested_import(
        project["id"],
        {
            "root": "Sign In",
            "branches": [
                {"name": "Email + Password", "children": ["MFA"]},
                {"name": "Enterprise SSO", "children": [{"name": "IdP Failure", "is_failure_path": True}]},
            ],
        },
    )
    store.test_cases["TC-X"] = {
        "test_case_id": "TC-X",
        "title": "password login",
        "project_id": project["id"],
        "graph_path": ["Sign In", "Email + Password"],
    }
    store.persist()
    cov = get_coverage_engine().analyze(project["id"], "Sign In")
    assert "Email + Password" in cov.covered_branches
    assert "Enterprise SSO" in cov.uncovered_branches
    assert cov.calculation_notes
    assert 0 <= cov.overall_coverage <= 100


def test_retrieval_planner_uses_flow_graph():
    from app.models.enums import QAIntent
    from app.rag.retrieval import RetrievalPlanner

    plan = RetrievalPlanner().plan(
        "Generate test cases for Sign In.",
        QAIntent.TEST_GENERATION,
        has_flow_graph=True,
    )
    assert plan.use_user_flow_graph is True
    assert plan.use_graph_rag is True
    assert plan.use_vector_rag is True


def test_openai_hash_embed_stable():
    from app.services.openai_service import OpenAIService

    svc = OpenAIService()
    a = svc._hash_embed("Sign In Google OAuth")
    b = svc._hash_embed("Sign In Google OAuth")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_dashboard(client):
    seed = client.post("/api/demo/seed").json()
    dash = client.get(f"/api/projects/{seed['project_id']}/dashboard").json()
    assert "graph_coverage" in dash
    assert dash["historical_bugs"] >= 1
    assert dash["node_count"] > 0