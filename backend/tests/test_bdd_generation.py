"""Tests for BDD / Gherkin generation, conversion, validation, and API contract."""

from __future__ import annotations

import pytest
from app.agents.bdd import (
    build_generated_artifacts,
    convert_test_to_bdd,
    render_feature_file,
    validate_bdd_scenario,
)
from app.models.enums import Priority, RiskLevel, TestOutputFormat
from app.models.schemas import QACopilotRequest, TestCase
from app.services.model_router import reset_model_router
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
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
    reset_model_router()
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None
    yield
    config.get_settings.cache_clear()
    reset_model_router()
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None


@pytest.fixture
def client(authenticated_client: TestClient):
    return authenticated_client


def _tc(**kwargs) -> TestCase:
    defaults = dict(
        test_case_id="TC-001",
        title="Create a blank Journey with a title and default language",
        category="functional",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        preconditions=[
            "User is inside the intended Journey folder",
            "Create New Journey form is open",
        ],
        steps=[
            "Enter a valid Journey title",
            "Select a default language",
            "Submit the creation request",
        ],
        expected_result="One blank Journey should be created in the selected folder and the selected default language should be retained",
        graph_path=["Create a Journey", "Create Blank Journey", "Enter Title"],
        evidence=[],
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


def test_request_default_format_is_standard():
    req = QACopilotRequest(project_id="p1", query="generate tests")
    assert req.test_output_format == TestOutputFormat.STANDARD


def test_invalid_format_returns_422(client):
    project = client.post(
        "/api/projects", json={"name": "P", "description": "d"}
    ).json()
    res = client.post(
        "/api/copilot/query",
        json={
            "project_id": project["id"],
            "query": "generate tests",
            "test_output_format": "gherkin-lite",
            "include_critic": False,
            "enable_targeted_regeneration": False,
        },
    )
    assert res.status_code == 422


def test_convert_valid_standard_to_bdd():
    scenario, status, notes = convert_test_to_bdd(
        _tc(), feature_name="Create a Journey"
    )
    assert status == "ok"
    assert scenario is not None
    assert scenario.feature == "Create a Journey"
    assert any(s.keyword == "When" for s in scenario.steps)
    assert any(s.keyword == "Then" for s in scenario.steps)
    assert "Feature:" in scenario.gherkin_text
    assert not validate_bdd_scenario(scenario)


def test_unsafe_conversion_needs_revision():
    scenario, status, notes = convert_test_to_bdd(
        _tc(title="Check journey", steps=["Try it"], expected_result="It works"),
        feature_name="Create a Journey",
    )
    assert status == "needs_revision"
    assert (
        "vague_or_missing_expected_result" in notes
        or scenario is None
        or (scenario and scenario.conversion_status == "needs_revision")
    )


def test_both_mode_shares_logical_id():
    artifacts, scenarios, meta = build_generated_artifacts(
        [_tc()],
        output_format=TestOutputFormat.BOTH,
        feature_name="Create a Journey",
    )
    assert meta["logical_test_count"] == 1
    assert len(artifacts) == 1
    assert artifacts[0].logical_test_id == "TC-001"
    assert artifacts[0].standard_test_case is not None
    assert artifacts[0].bdd_scenario is not None
    assert artifacts[0].bdd_scenario.source_test_id == "TC-001"
    assert len(scenarios) == 1


def test_feature_export_is_parseable_gherkin():
    _, scenarios, _ = build_generated_artifacts(
        [
            _tc(),
            _tc(
                test_case_id="TC-002",
                title="Reject Journey creation without a title",
                steps=["Submit the form without a Journey title"],
                expected_result="The Journey should not be created and a title validation message should be displayed",
            ),
        ],
        output_format=TestOutputFormat.BDD,
        feature_name="Create a Journey",
    )
    body = render_feature_file(scenarios, feature_name="Create a Journey")
    assert body.startswith("Feature: Create a Journey")
    assert "As " in body
    assert "I want" in body
    assert "# FUNCTIONAL" in body or "# NEGATIVE" in body
    assert "Scenario:" in body
    assert "@priority-" in body
    assert "@regression" in body
    assert "@automation-" in body
    assert "When " in body
    assert "Then " in body


def test_copilot_standard_backward_compatible(client):
    seeded = client.post("/api/demo/seed?force=true")
    assert seeded.status_code == 200
    project_id = seeded.json()["project_id"]
    res = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate test cases for Sign In",
            "include_critic": False,
            "enable_targeted_regeneration": False,
            "requested_outputs": ["test_cases"],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload.get("test_output_format", "standard") == "standard"
    assert isinstance(payload.get("test_cases"), list)
    assert "bdd_scenarios" in payload
    assert "generated_test_artifacts" in payload


def test_copilot_bdd_mode(client):
    seeded = client.post("/api/demo/seed?force=true")
    project_id = seeded.json()["project_id"]
    res = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate test cases for Sign In",
            "test_output_format": "bdd",
            "include_critic": False,
            "enable_targeted_regeneration": False,
            "requested_outputs": ["test_cases"],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["test_output_format"] == "bdd"
    assert payload["test_cases"]  # canonical preserved for coverage/review
    assert isinstance(payload.get("bdd_scenarios"), list)
    assert (
        payload["section_status"]["test_case_generation"]["requested_format"] == "bdd"
    )


def test_export_feature_endpoint(client):
    seeded = client.post("/api/demo/seed?force=true")
    project_id = seeded.json()["project_id"]
    gen = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate test cases for Sign In",
            "test_output_format": "bdd",
            "include_critic": False,
            "enable_targeted_regeneration": False,
            "requested_outputs": ["test_cases"],
        },
    )
    assert gen.status_code == 200
    if not gen.json().get("bdd_scenarios"):
        pytest.skip("No BDD scenarios produced in this environment")
    export = client.get(f"/api/projects/{project_id}/tests/export.feature")
    assert export.status_code == 200
    assert "Feature:" in export.text
    assert "attachment" in (export.headers.get("content-disposition") or "")
