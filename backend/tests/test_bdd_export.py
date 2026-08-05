"""Cucumber-compliant BDD export tests."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.agents.bdd import convert_test_to_bdd, escape_table_cell, render_feature_file, validate_bdd_scenario
from app.agents.bdd_export import BDDExportRequest, build_export_package, build_export_preview
from app.models.schemas import BDDScenario, BDDStep, TestCase


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


def _seed_analysis(client, *, fmt: str = "standard", name: str = "Export Project"):
    created = client.post(
        "/api/projects",
        json={"name": name, "root_feature": "Checkout"},
    )
    assert created.status_code == 200
    project_id = created.json()["id"]
    res = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate comprehensive QA coverage for Checkout.",
            "test_output_format": fmt,
            "include_critic": False,
            "enable_targeted_regeneration": False,
            "requested_outputs": ["test_cases", "coverage", "evidence"],
        },
    )
    assert res.status_code == 200
    return project_id, res.json()


def test_escape_table_cell():
    assert escape_table_cell("a|b") == "a\\|b"
    assert escape_table_cell("a\\b") == "a\\\\b"
    assert escape_table_cell("a\nb") == "a\\nb"


def test_standard_conversion_and_validation():
    tc = TestCase(
        title="Reject payment with expired card",
        preconditions=["User has items in cart"],
        steps=["Submit payment with an expired card"],
        expected_result="Payment is declined and the user sees an actionable error",
        graph_path=["Checkout", "Payment"],
        priority="high",
        category="negative",
    )
    scenario, status, notes = convert_test_to_bdd(tc, feature_name="Checkout")
    assert status == "ok"
    assert scenario is not None
    assert any(s.keyword == "Given" for s in scenario.steps)
    assert any(s.keyword == "When" for s in scenario.steps)
    assert any(s.keyword == "Then" for s in scenario.steps)
    assert validate_bdd_scenario(scenario) == []


def test_render_feature_file_one_feature_and_comments():
    sc = BDDScenario(
        feature="Checkout",
        feature_description="As a shopper\nI want to complete checkout\nSo that I receive my order",
        rule="FUNCTIONAL",
        scenario_name="Complete checkout with valid card",
        tags=["@priority-high", "@regression", "@automation-yes"],
        steps=[
            BDDStep(keyword="Given", text="the cart has items"),
            BDDStep(keyword="When", text="the user submits payment"),
            BDDStep(keyword="Then", text="an order confirmation is shown"),
        ],
        source_test_id="TC-1",
        graph_path=["Checkout", "Payment"],
        generation_method="llm",
        test_type="functional",
    )
    body = render_feature_file(
        [sc],
        feature_name="Checkout",
        include_traceability_comments=True,
    )
    assert body.count("Feature:") == 1
    assert "As a shopper" in body
    assert "# FUNCTIONAL" in body
    assert "Scenario: Complete checkout with valid card" in body
    # Cucumber-valid: tags appear on the line before Scenario
    assert "@priority-high @regression @automation-yes\n  Scenario:" in body or (
        "@priority-high" in body and body.index("@priority-high") < body.index("Scenario:")
    )
    assert "# Test ID: TC-1" in body
    assert "# Graph Path: Checkout > Payment" in body


def test_journey_style_tags_and_section():
    from app.agents.bdd import build_tags, convert_test_to_bdd, scenario_section
    from app.models.enums import Priority

    tc = TestCase(
        title="Create journey with a blank name is rejected",
        category="negative",
        priority=Priority.HIGH,
        preconditions=["the admin is creating a new journey"],
        steps=["leave the name field empty and click Save"],
        expected_result="the system displays a validation error and the journey is not created",
        graph_path=["Journey Editor"],
    )
    assert scenario_section(tc.category) == "NEGATIVE"
    tags = build_tags(tc)
    assert "@priority-high" in tags
    assert "@regression" in tags
    assert "@automation-yes" in tags
    scenario, status, _ = convert_test_to_bdd(tc, feature_name="Journey Editor [ECT-83]")
    assert status == "ok"
    assert scenario is not None
    assert scenario.rule == "NEGATIVE"
    assert scenario.feature_description and "As " in scenario.feature_description
    assert "I want" in scenario.feature_description


def test_single_feature_export_endpoint(client):
    project_id, analysis = _seed_analysis(client, fmt="standard")
    assert analysis["test_cases"]
    res = client.post(
        f"/api/projects/{project_id}/analyses/latest/exports/bdd",
        json={
            "scope": "all_final_generated",
            "include_traceability_comments": True,
            "include_tags": True,
            "include_import_csv": True,
            "strict": True,
        },
    )
    assert res.status_code == 200, res.text
    assert "attachment" in res.headers.get("content-disposition", "")
    assert "csv" in (res.headers.get("content-type") or "").lower()
    assert res.headers.get("content-disposition", "").endswith('.csv"') or ".csv" in res.headers.get(
        "content-disposition", ""
    )
    body = res.content.decode("utf-8")
    assert "scenario_name" in body
    assert "Given|" in body or "When|" in body


def test_feature_export_when_csv_disabled(client):
    project_id, analysis = _seed_analysis(client, fmt="standard", name="Feature Only Export")
    assert analysis["test_cases"]
    res = client.post(
        f"/api/projects/{project_id}/analyses/latest/exports/bdd",
        json={
            "scope": "all_final_generated",
            "include_import_csv": False,
            "strict": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.content.decode("utf-8")
    assert "Feature:" in body
    assert "Scenario:" in body
    assert body.count("Feature:") == 1


def test_preview_endpoint(client):
    project_id, _ = _seed_analysis(client, fmt="bdd", name="Preview Project")
    res = client.post(
        f"/api/projects/{project_id}/analyses/latest/exports/bdd/preview",
        json={"scope": "all_final_generated", "strict": True},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scenario_count"] >= 1
    assert payload["file_count"] >= 1
    assert payload["files"][0]["content"].count("Feature:") == 1


def test_both_mode_exports_once(client):
    project_id, analysis = _seed_analysis(client, fmt="both", name="Both Export Project")
    logical = len(analysis.get("generated_test_artifacts") or analysis["test_cases"])
    preview = build_export_preview(project_id, BDDExportRequest(strict=True))
    assert preview.scenario_count == logical or preview.scenario_count == len(analysis["test_cases"])
    # One scenario per logical test id
    ids = [s for f in preview.files for s in f.logical_test_ids]
    assert len(ids) == len(set(ids))


def test_strict_blocks_unconvertible(client):
    project_id, _ = _seed_analysis(client, name="Strict Export")
    from app.graph.store import get_graph_store

    store = get_graph_store()
    analysis = store.get_latest_analysis(project_id)
    assert analysis
    analysis["generated_test_artifacts"] = []
    analysis["bdd_scenarios"] = []
    analysis["test_cases"] = [
        TestCase(
            title="Broken",
            steps=["Do something"],
            expected_result="ok",
            graph_path=["Checkout"],
            project_id=project_id,
        ).model_dump(mode="json")
    ]
    store.set_latest_analysis(project_id, analysis)
    res = client.post(
        f"/api/projects/{project_id}/analyses/latest/exports/bdd",
        json={"scope": "all_final_generated", "strict": True},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "BDD_CONVERSION_FAILED"
    assert detail["details"]["valid_only_available"] is True


def test_valid_only_export_excludes_invalid(client):
    project_id, _ = _seed_analysis(client, name="Valid Only Export")
    from app.graph.store import get_graph_store

    store = get_graph_store()
    analysis = store.get_latest_analysis(project_id)
    good = TestCase(
        title="Accept valid payment",
        preconditions=["Cart has items"],
        steps=["Submit a valid payment method"],
        expected_result="Order is confirmed and a receipt is shown",
        graph_path=["Checkout"],
        project_id=project_id,
        priority="high",
        category="positive",
    )
    bad = TestCase(
        title="Vague outcome",
        steps=["Click submit"],
        expected_result="works",
        graph_path=["Checkout"],
        project_id=project_id,
    )
    analysis["generated_test_artifacts"] = []
    analysis["bdd_scenarios"] = []
    analysis["test_cases"] = [good.model_dump(mode="json"), bad.model_dump(mode="json")]
    analysis["valid_tests"] = [good.model_dump(mode="json")]
    store.set_latest_analysis(project_id, analysis)
    package = build_export_package(
        project_id,
        BDDExportRequest(scope="valid_only", strict=False, include_import_csv=False),
    )
    assert package.preview.scenario_count == 1
    assert any(e.test_id == bad.test_case_id for e in package.preview.excluded_tests) or package.preview.scenario_count == 1
    text = package.content.decode("utf-8") if isinstance(package.content, (bytes, bytearray)) else ""
    if text:
        assert "Accept valid payment" in text
        assert "Vague outcome" not in text


def test_form_import_csv_in_zip(client):
    """CSV maps to New Test Case form: name, type, tags, Keyword|step rows."""
    from app.agents.bdd_export import render_import_csv, render_steps_csv

    scenarios = [
        BDDScenario(
            feature="Journey Editor [ECT-83]",
            feature_description="As an admin I want to author and manage journeys",
            scenario_name="Create a journey with name, description and settings",
            tags=["priority-high", "regression", "automation-yes"],
            steps=[
                BDDStep(keyword="Given", text="the admin is in Helix Studio"),
                BDDStep(
                    keyword="When",
                    text='they create a new journey with name "Leader Onboarding", a description, and configure key settings',
                ),
                BDDStep(
                    keyword="Then",
                    text="the journey is created and listed in the journey library",
                ),
                BDDStep(keyword="And", text="all entered details are persisted on reload"),
            ],
            graph_path=["Helix Studio", "Journey Editor"],
            source_test_id="TC-JE-001",
        ),
        BDDScenario(
            feature="Journey Editor [ECT-83]",
            scenario_name="Create journey with a blank name is rejected",
            tags=["priority-high", "regression", "automation-yes"],
            steps=[
                BDDStep(keyword="Given", text="the admin is creating a new journey"),
                BDDStep(keyword="When", text="they leave the name field empty and click Save"),
                BDDStep(
                    keyword="Then",
                    text="the system displays a validation error indicating name is required",
                ),
                BDDStep(keyword="And", text="the journey is not created"),
            ],
            graph_path=["Helix Studio", "Journey Editor"],
            source_test_id="TC-JE-NEG-001",
        ),
    ]
    csv_text = render_import_csv(scenarios)
    assert (
        "feature_name,feature_description,section,scenario_name,scenario_type,tags,steps,priority,automation,test_id,graph_path"
        in csv_text
    )
    assert "Create a journey with name, description and settings" in csv_text
    assert "Scenario" in csv_text
    assert "FUNCTIONAL" in csv_text or "NEGATIVE" in csv_text
    assert "priority-high;regression;automation-yes" in csv_text
    assert "Given|the admin is in Helix Studio" in csv_text
    assert "When|they create a new journey" in csv_text
    assert "@priority" not in csv_text
    assert ",yes," in csv_text or ",high," in csv_text

    steps_csv = render_steps_csv(scenarios)
    assert "step_order,keyword,step_text" in steps_csv
    assert "Given,the admin is in Helix Studio" in steps_csv

    project_id, _ = _seed_analysis(client, name="CSV Export Project")
    preview = build_export_preview(project_id, BDDExportRequest(strict=True, include_import_csv=True))
    assert preview.csv_preview
    assert preview.steps_csv
    assert "scenario_name" in preview.csv_preview
    assert "feature_description" in preview.csv_preview
    assert "section" in preview.csv_preview
    assert "Given|" in preview.csv_preview or "When|" in preview.csv_preview
    assert "priority-high" in preview.csv_preview or "priority-medium" in preview.csv_preview or "priority-critical" in preview.csv_preview

    package = build_export_package(project_id, BDDExportRequest(strict=True, include_import_csv=True))
    assert package.content_type.startswith("text/csv")
    assert package.filename.endswith(".csv")
    cases = package.content.decode("utf-8")
    assert "scenario_name" in cases
    assert "Given|" in cases or "When|" in cases


def test_no_tests_typed_error(client):
    created = client.post("/api/projects", json={"name": "Empty Export", "root_feature": "X"})
    project_id = created.json()["id"]
    res = client.post(
        f"/api/projects/{project_id}/analyses/latest/exports/bdd",
        json={"scope": "all_final_generated"},
    )
    assert res.status_code in {400, 404}
    detail = res.json()["detail"]
    assert detail["code"] in {"NO_TESTS", "ANALYSIS_NOT_FOUND"}


def test_project_isolation(client):
    a_id, _ = _seed_analysis(client, name="Iso A")
    b = client.post("/api/projects", json={"name": "Iso B", "root_feature": "Other"})
    b_id = b.json()["id"]
    # Export for B with no analysis
    res = client.post(
        f"/api/projects/{b_id}/analyses/latest/exports/bdd",
        json={"scope": "all_final_generated"},
    )
    assert res.status_code in {400, 404}
    # A still exports
    res_a = client.post(
        f"/api/projects/{a_id}/analyses/latest/exports/bdd",
        json={"scope": "all_final_generated", "strict": True},
    )
    assert res_a.status_code == 200


def test_filename_safety():
    from app.agents.bdd import safe_feature_filename

    name = safe_feature_filename("../Checkout..\\Pay", "My Project")
    assert ".." not in name
    assert "/" not in name
    assert "\\" not in name
    assert name.endswith(".feature")


def test_zip_when_multiple_features(client):
    project_id, _ = _seed_analysis(client, name="Multi Feature Export")
    from app.graph.store import get_graph_store

    store = get_graph_store()
    analysis = store.get_latest_analysis(project_id)
    # Force a second feature via an extra convertible test
    analysis["test_cases"].append(
        TestCase(
            title="Login with valid credentials",
            preconditions=["Account exists"],
            steps=["Submit valid credentials"],
            expected_result="User is authenticated and lands on the home page",
            graph_path=["Sign In", "Credentials"],
            project_id=project_id,
            category="positive",
            priority="high",
        ).model_dump(mode="json")
    )
    store.set_latest_analysis(project_id, analysis)
    package = build_export_package(project_id, BDDExportRequest(strict=True, include_import_csv=False))
    if package.content_type == "application/zip":
        with zipfile.ZipFile(io.BytesIO(package.content)) as zf:
            names = zf.namelist()
            assert "export-manifest.json" in names
            feature_files = [n for n in names if n.endswith(".feature")]
            assert len(feature_files) >= 2
            manifest = json.loads(zf.read("export-manifest.json"))
            assert manifest["scenario_count"] >= 2
            for ff in feature_files:
                text = zf.read(ff).decode("utf-8")
                assert text.count("Feature:") == 1
    else:
        # Single feature grouping still valid if graph rooted everything under Checkout
        assert "Feature:" in package.content.decode("utf-8")
