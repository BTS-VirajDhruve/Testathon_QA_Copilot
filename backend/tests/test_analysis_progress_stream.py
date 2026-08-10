"""Tests for analysis progress SSE stream."""

from __future__ import annotations

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
def client(authenticated_client: TestClient):
    return authenticated_client


def test_copilot_query_stream_emits_progress_and_complete(client):
    created = client.post(
        "/api/projects",
        json={"name": "Stream Progress Project", "root_feature": "Checkout"},
    )
    assert created.status_code == 200
    project_id = created.json()["id"]

    with client.stream(
        "POST",
        "/api/copilot/query/stream",
        json={
            "project_id": project_id,
            "query": "Generate comprehensive QA coverage for Checkout.",
            "include_critic": True,
            "enable_targeted_regeneration": False,
            "requested_outputs": [
                "test_cases",
                "exploratory_scenarios",
                "bug_reports",
                "regression_recommendations",
                "coverage",
                "evidence",
            ],
        },
        timeout=120,
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        body = ""
        for chunk in response.iter_text():
            body += chunk

    assert "event: progress" in body
    assert "event: complete" in body
    assert "Identify Project" in body or "Reading system-flow" in body
    assert "test_cases" in body
    assert "execution_trace" in body
    assert "sk-" not in body
    assert "OPENAI_API_KEY" not in body


def test_copilot_query_remains_compatible(client):
    created = client.post(
        "/api/projects",
        json={"name": "Compat Query Project", "root_feature": "Login"},
    )
    assert created.status_code == 200
    project_id = created.json()["id"]
    response = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate tests for Login.",
            "requested_outputs": ["test_cases", "coverage"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id
    assert "section_status" in payload
    assert "execution_trace" in payload
