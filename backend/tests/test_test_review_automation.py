"""Tests for validity-first test review and automation feasibility."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agents.test_review_automation import (
    TestReviewAutomationAgent,
    apply_human_override,
    apply_safe_corrections,
    classify_automation,
    classify_duplicate_relation,
    compute_automation_signals,
    deterministic_validity_findings,
    recommend_automation_layer,
)
from app.models.enums import (
    AutomationLayer,
    AutomationSuitability,
    DuplicateRelation,
    LLMTaskType,
    Priority,
    RiskLevel,
    TestValidity,
)
from app.models.schemas import AutomationCapabilityProfile, FusedContext, TestCase
from app.services.model_router import DEFAULT_TASK_MODEL_MAP, ModelRoutingContext, get_model_router, reset_model_router


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
    monkeypatch.setenv("MODEL_ROUTING_ENABLED", "true")
    for key in (
        "OPENAI_MODEL_TEST_REVIEW_AUTOMATION",
        "OPENAI_MODEL_TEST_VALIDITY_REVIEW",
        "OPENAI_MODEL_AUTOMATION_FEASIBILITY_REVIEW",
    ):
        monkeypatch.delenv(key, raising=False)

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
def client():
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def agent() -> TestReviewAutomationAgent:
    return TestReviewAutomationAgent()


def _tc(**kwargs) -> TestCase:
    defaults = dict(
        test_case_id="TC-001",
        title="Validate mandatory Journey title before save",
        category="functional",
        priority=Priority.HIGH,
        risk=RiskLevel.HIGH,
        preconditions=["User is authenticated", "Journey editor is open"],
        steps=[
            "Open Create Journey",
            "Leave title blank",
            "Click Save",
            "Observe validation message",
        ],
        expected_result="Save is blocked and a title-required validation message is displayed",
        graph_path=["Momenta", "Create Journey", "Save"],
        evidence=[],
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


def test_validity_precheck_marks_supported_test_valid(agent: TestReviewAutomationAgent):
    reviewed, validity_summary, automation_summary, meta = agent.review(
        test_cases=[_tc()],
        project_id="proj-a",
        fused=FusedContext(feature_context={"name": "Momenta"}, flow_paths=[["Momenta", "Create Journey", "Save"]]),
        force_deterministic=True,
    )
    assert reviewed[0].validity_review.validity == TestValidity.VALID.value
    assert validity_summary.valid == 1
    assert automation_summary.valid_tests_evaluated == 1
    assert meta["fallback_used"] is True


def test_invalid_test_gets_not_evaluated_automation(agent: TestReviewAutomationAgent):
    bad = _tc(title="Check whether Journey looks professional", steps=["Try the feature"], expected_result="It works", preconditions=[])
    reviewed, validity_summary, automation_summary, _ = agent.review(
        test_cases=[bad],
        project_id="proj-a",
        force_deterministic=True,
    )
    item = reviewed[0]
    assert item.validity_review.validity in {
        TestValidity.INVALID.value,
        TestValidity.NEEDS_REVISION.value,
        TestValidity.INSUFFICIENT_EVIDENCE.value,
    }
    assert item.automation_review is not None
    assert item.automation_review.automation_suitability == AutomationSuitability.NOT_EVALUATED.value
    assert validity_summary.total_tests == 1
    assert automation_summary.valid_tests_evaluated == 0


def test_needs_revision_supported_incomplete(agent: TestReviewAutomationAgent):
    case = _tc(expected_result="Message shown", steps=["Click Save"])
    reviewed, validity_summary, _, _ = agent.review(
        test_cases=[case],
        project_id="proj-a",
        fused=FusedContext(feature_context={"name": "Momenta"}, flow_paths=[["Momenta", "Create Journey", "Save"]]),
        force_deterministic=True,
    )
    assert reviewed[0].validity_review.validity in {
        TestValidity.NEEDS_REVISION.value,
        TestValidity.VALID.value,
    }
    assert validity_summary.total_tests == 1


def test_insufficient_evidence_when_unsupported(agent: TestReviewAutomationAgent):
    case = _tc(graph_path=[], source_references=[], evidence=[], title="Judge copied content appropriateness", expected_result="Content feels contextually appropriate")
    reviewed, validity_summary, _, _ = agent.review(
        test_cases=[case],
        project_id="proj-a",
        force_deterministic=True,
    )
    assert reviewed[0].validity_review.validity == TestValidity.INSUFFICIENT_EVIDENCE.value
    assert validity_summary.insufficient_evidence == 1


def test_deterministic_api_test_automates():
    tc = _tc(
        title="Prevent duplicate Journey submission via API",
        category="api",
        steps=["POST /journeys with payload A", "POST /journeys again with identical idempotency key", "Read response status codes"],
        expected_result="Second request returns HTTP 409 Conflict and no duplicate row is created",
        graph_path=["Momenta", "Create Journey", "API"],
    )
    layer, _ = recommend_automation_layer(tc, profile=AutomationCapabilityProfile(api_testing_available=True))
    suit, *_ = classify_automation(
        tc,
        profile=AutomationCapabilityProfile(
            api_testing_available=True,
            test_data_api_available=True,
            stable_test_ids_available=True,
        ),
    )
    assert layer in {AutomationLayer.API, AutomationLayer.CONTRACT, AutomationLayer.INTEGRATION}
    assert suit == AutomationSuitability.AUTOMATE


def test_ui_missing_selectors_is_conditional():
    tc = _tc(
        title="Create blank Journey from UI",
        steps=["Click Create Journey", "Enter title", "Click Save", "Verify Journey appears in list"],
        expected_result="Journey is created and visible in the list with the entered title",
    )
    suit, *_ = classify_automation(tc, profile=None)
    assert suit == AutomationSuitability.AUTOMATE_WITH_CONDITIONS


def test_hybrid_and_manual_classifications():
    hybrid = _tc(
        title="Verify error message visual usability after failed save",
        steps=["Trigger validation error", "Confirm error toast is displayed", "Assess whether the layout and spacing look acceptable"],
        expected_result="Error message is displayed and layout looks good for users",
    )
    suit1, *_ = classify_automation(hybrid, profile=None)
    assert suit1 in {AutomationSuitability.HYBRID, AutomationSuitability.MANUAL}

    manual = _tc(
        title="Exploratory review of Journey naming clarity",
        category="exploratory",
        steps=["Open naming dialog", "Assess whether names feel intuitive to a new user"],
        expected_result="Names feel clear and not confusing",
    )
    suit2, *_ = classify_automation(manual, profile=None)
    assert suit2 == AutomationSuitability.MANUAL


def test_exact_duplicate_detection():
    a = _tc(test_case_id="TC-A")
    b = _tc(test_case_id="TC-B")
    assert classify_duplicate_relation(a, b) == DuplicateRelation.EXACT_DUPLICATE


def test_safe_corrections_apply_low_risk_changes():
    corrected, applied = apply_safe_corrections(_tc(title="  Validate   title  ", steps=["Click Save", "Click Save", "See error"]))
    assert corrected.steps.count("Click Save") == 1
    assert applied


def test_project_isolation(agent: TestReviewAutomationAgent):
    foreign = _tc(test_case_id="TC-X", project_id="other-project")
    local = _tc(test_case_id="TC-Y", project_id="proj-a")
    reviewed, validity_summary, _, _ = agent.review(
        test_cases=[foreign, local],
        project_id="proj-a",
        force_deterministic=True,
    )
    ids = {r.test_case.test_case_id for r in reviewed}
    assert ids == {"TC-Y"}
    assert validity_summary.total_tests == 1


def test_pipeline_order_only_valid_tests_counted_for_automation(agent: TestReviewAutomationAgent):
    good = _tc(test_case_id="TC-GOOD")
    bad = _tc(test_case_id="TC-BAD", title="Test Journey", steps=["Try the feature"], expected_result="It works", preconditions=[])
    reviewed, validity_summary, automation_summary, _ = agent.review(
        test_cases=[good, bad],
        project_id="proj-a",
        fused=FusedContext(feature_context={"name": "Momenta"}, flow_paths=[["Momenta", "Create Journey", "Save"]]),
        force_deterministic=True,
    )
    assert validity_summary.total_tests == 2
    assert automation_summary.valid_tests_evaluated == 1
    by_id = {item.test_case.test_case_id: item for item in reviewed}
    assert by_id["TC-BAD"].automation_review.automation_suitability == AutomationSuitability.NOT_EVALUATED.value


def test_provider_failure_uses_deterministic_fallback(agent: TestReviewAutomationAgent):
    mock_oa = MagicMock()
    mock_oa.available = True
    mock_oa.chat_json.side_effect = RuntimeError("provider down")
    with patch("app.agents.test_review_automation.get_openai_service", return_value=mock_oa):
        reviewed, _, _, meta = agent.review(
            test_cases=[_tc()],
            project_id="proj-a",
            force_deterministic=False,
        )
    assert reviewed
    assert meta["fallback_used"] is True


def test_manual_override_persists(agent: TestReviewAutomationAgent):
    reviewed, _, _, _ = agent.review(
        test_cases=[_tc()],
        project_id="proj-a",
        force_deterministic=True,
    )
    item = reviewed[0]
    overridden = apply_human_override(item, {"automation_suitability": "manual", "override_reason": "Product wants exploratory check"})
    assert overridden.human_override is True
    assert overridden.automation_review is not None
    assert overridden.automation_review.automation_suitability == "manual"


def test_test_review_endpoint_reviews_existing_tests(client):
    project = client.post("/api/projects", json={"name": "Momenta", "description": "d", "root_feature": "Create Journey"}).json()
    project_id = project["id"]
    flow = {
        "project_id": project_id,
        "root": "Momenta",
        "branches": [
            {"name": "Create Journey", "children": [{"name": "Save"}]}
        ],
    }
    imported = client.post(f"/api/projects/{project_id}/flow/import", json=flow)
    assert imported.status_code == 200

    from app.graph.store import get_graph_store

    store = get_graph_store()
    store.upsert_test_case(project_id, _tc(project_id=project_id).model_dump(mode="json"))
    store.persist()

    res = client.post(f"/api/projects/{project_id}/test-review")
    assert res.status_code == 200
    payload = res.json()["analysis"]
    assert len(payload.get("reviewed_test_cases") or []) == 1
    assert payload["section_status"]["test_validity_review"]["status"] == "success"
    assert payload["section_status"]["automation_feasibility_review"]["status"] in {"success", "empty"}

    get_res = client.get(f"/api/projects/{project_id}/test-review")
    assert get_res.status_code == 200
    assert len((get_res.json()["analysis"] or {}).get("reviewed_test_cases") or []) == 1


def test_partial_failure_keeps_tests_visible(client):
    seeded = client.post("/api/demo/seed?force=true")
    assert seeded.status_code == 200
    project_id = seeded.json().get("project_id") or client.get("/api/projects").json()[0]["id"]
    with patch("app.agents.orchestrator.TestReviewAutomationAgent.review", side_effect=RuntimeError("boom")):
        res = client.post(
            "/api/copilot/query",
            json={
                "project_id": project_id,
                "query": "Generate test cases for the sign-in flow",
                "include_critic": True,
                "enable_targeted_regeneration": False,
                "requested_outputs": ["test_cases"],
            },
        )
    assert res.status_code == 200
    payload = res.json()
    assert isinstance(payload.get("test_cases"), list)
    assert payload["section_status"]["test_review_automation"]["status"] == "failed"


def test_response_contract_arrays_exist(agent: TestReviewAutomationAgent):
    reviewed, validity_summary, automation_summary, _ = agent.review(
        test_cases=[_tc()],
        project_id="proj-a",
        force_deterministic=True,
    )
    assert reviewed[0].validity_review is not None
    assert validity_summary.total_tests == 1
    assert automation_summary.total_tests == 1


def test_model_routing_task_types():
    router = get_model_router()
    for task in (
        LLMTaskType.TEST_REVIEW_AUTOMATION,
        LLMTaskType.TEST_VALIDITY_REVIEW,
        LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW,
    ):
        sel = router.resolve_model(task, ModelRoutingContext(task_type=task))
        assert sel.requested_task_type == task
        assert sel.base_model == DEFAULT_TASK_MODEL_MAP[task]


def test_momenta_and_checkout_examples(agent: TestReviewAutomationAgent):
    cases = [
        _tc(test_case_id="TC-M1"),
        _tc(
            test_case_id="TC-M2",
            title="Prevent duplicate Journey creation",
            category="api",
            steps=["POST journey", "POST identical journey", "Check conflict response"],
            expected_result="Second request returns HTTP 409 and no duplicate Journey is persisted",
        ),
        _tc(
            test_case_id="TC-C1",
            title="Payment gateway timeout handling",
            steps=["Submit payment", "Simulate gateway timeout", "Observe retry and user message"],
            expected_result="Timeout error message is displayed and no duplicate charge exists",
            graph_path=["Checkout", "Payment Gateway"],
        ),
    ]
    reviewed, validity_summary, automation_summary, _ = agent.review(
        test_cases=cases,
        project_id="proj-a",
        fused=FusedContext(feature_context={"name": "Momenta"}, flow_paths=[["Momenta", "Create Journey", "Save"], ["Checkout", "Payment Gateway"]]),
        force_deterministic=True,
    )
    assert validity_summary.total_tests == 3
    assert automation_summary.valid_tests_evaluated >= 1
    by_id = {item.test_case.test_case_id: item for item in reviewed}
    assert by_id["TC-M1"].validity_review.validity in {"valid", "needs_revision"}
    assert by_id["TC-M2"].automation_review is not None
