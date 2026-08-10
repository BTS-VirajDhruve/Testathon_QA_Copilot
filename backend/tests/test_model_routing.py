"""Tests for task-aware model routing, escalation, reviewer, and fallbacks."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.models.auth import UserCreateInput
from app.models.enums import LLMTaskType, RequirementComplexity
from app.services.model_router import (
    DEFAULT_TASK_MODEL_MAP,
    ModelRoutingContext,
    assess_requirement_complexity,
    decide_reviewer,
    get_model_router,
    reset_model_router,
)
from app.services.user_service import get_user_service


@pytest.fixture(autouse=True)
def _routing_env(monkeypatch, tmp_path):
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
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("MODEL_ROUTING_ENABLED", "true")
    monkeypatch.setenv("MODEL_ESCALATION_ENABLED", "true")
    monkeypatch.setenv("MODEL_REVIEWER_ENABLED", "false")
    monkeypatch.setenv("MODEL_ROUTING_ENABLED_TASKS", "*")
    # Clear task overrides so defaults apply
    for key in (
        "OPENAI_MODEL_INTENT_CLASSIFICATION",
        "OPENAI_MODEL_QA_DOCUMENTATION",
        "OPENAI_MODEL_REGRESSION_SELECTION",
        "OPENAI_MODEL_BUG_REPORT",
        "OPENAI_MODEL_TEST_CASE_GENERATION",
        "OPENAI_MODEL_TARGETED_TEST_GENERATION",
        "OPENAI_MODEL_EXPLORATORY_SCENARIO",
        "OPENAI_MODEL_REVIEWER_PASS",
        "OPENAI_MODEL_GRAPH_EXTRACTION",
        "OPENAI_MODEL_OUTPUT_REPAIR",
        "OPENAI_MODEL_CRITIC_NOTES",
        "OPENAI_MODEL_TEST_REVIEW_AUTOMATION",
        "OPENAI_MODEL_TEST_VALIDITY_REVIEW",
        "OPENAI_MODEL_AUTOMATION_FEASIBILITY_REVIEW",
        "OPENAI_MODEL_ESCALATION_TARGET",
    ):
        monkeypatch.delenv(key, raising=False)

    import app.core.config as config
    import app.services.openai_service as oa_mod

    config.get_settings.cache_clear()
    reset_model_router()
    oa_mod._openai_service = None
    yield
    config.get_settings.cache_clear()
    reset_model_router()
    oa_mod._openai_service = None


def test_base_routing_defaults():
    router = get_model_router()
    expected = {
        LLMTaskType.QA_DOCUMENTATION: "gpt-5.4-mini",
        LLMTaskType.REGRESSION_SELECTION: "gpt-5.4-mini",
        LLMTaskType.BUG_REPORT: "gpt-5.6-luna",
        LLMTaskType.TEST_CASE_GENERATION: "gpt-5.6-luna",
        LLMTaskType.EXPLORATORY_SCENARIO: "gpt-5.6-sol",
        LLMTaskType.REVIEWER_PASS: "gpt-5.6-terra",
        LLMTaskType.TEST_VALIDITY_REVIEW: "gpt-5.6-luna",
        LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW: "gpt-5.6-luna",
    }
    for task, model in expected.items():
        sel = router.resolve_model(task, ModelRoutingContext(task_type=task))
        assert sel.base_model == model
        assert sel.selected_model == model
        assert sel.requested_task_type == task


def test_environment_override(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL_BUG_REPORT", "custom-bug-model")
    import app.core.config as config

    config.get_settings.cache_clear()
    reset_model_router()
    sel = get_model_router().resolve_model(LLMTaskType.BUG_REPORT)
    assert sel.selected_model == "custom-bug-model"
    assert sel.base_model == "custom-bug-model"


def test_routing_disabled_uses_global_default(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTING_ENABLED", "false")
    import app.core.config as config

    config.get_settings.cache_clear()
    reset_model_router()
    sel = get_model_router().resolve_model(LLMTaskType.TEST_CASE_GENERATION)
    assert sel.selected_model == "gpt-4o-mini"
    assert sel.routing_enabled_for_task is False


def test_enabled_tasks_allowlist(monkeypatch):
    monkeypatch.setenv(
        "MODEL_ROUTING_ENABLED_TASKS", "qa_documentation,regression_selection"
    )
    import app.core.config as config

    config.get_settings.cache_clear()
    reset_model_router()
    router = get_model_router()
    doc = router.resolve_model(LLMTaskType.QA_DOCUMENTATION)
    assert doc.selected_model == DEFAULT_TASK_MODEL_MAP[LLMTaskType.QA_DOCUMENTATION]
    gen = router.resolve_model(LLMTaskType.TEST_CASE_GENERATION)
    assert gen.selected_model == "gpt-4o-mini"
    assert gen.routing_enabled_for_task is False


def test_complexity_escalation_high():
    ctx = ModelRoutingContext(
        task_type=LLMTaskType.TEST_CASE_GENERATION,
        input_token_estimate=3000,
        graph_path_count=15,
        retrieved_document_count=8,
        security_sensitive=True,
        financial_impact=True,
    )
    assessment = assess_requirement_complexity(ctx)
    assert assessment.category == RequirementComplexity.HIGH
    ctx.requirement_complexity = assessment.category
    sel = get_model_router().resolve_model(LLMTaskType.TEST_CASE_GENERATION, ctx)
    assert sel.escalated is True
    assert sel.selected_model == DEFAULT_TASK_MODEL_MAP[LLMTaskType.REVIEWER_PASS]
    assert sel.escalation_reason


def test_complexity_low_stays_on_luna():
    ctx = ModelRoutingContext(
        task_type=LLMTaskType.TEST_CASE_GENERATION,
        input_token_estimate=100,
        graph_path_count=2,
        retrieved_document_count=0,
    )
    assessment = assess_requirement_complexity(ctx)
    assert assessment.category == RequirementComplexity.LOW
    ctx.requirement_complexity = assessment.category
    sel = get_model_router().resolve_model(LLMTaskType.TEST_CASE_GENERATION, ctx)
    assert sel.escalated is False
    assert sel.selected_model == "gpt-5.6-luna"


def test_reviewer_disabled_by_default():
    ctx = ModelRoutingContext(
        security_sensitive=True,
        release_blocking=True,
        financial_impact=True,
    )
    decision = decide_reviewer(ctx, quality_failed=True)
    assert decision.required is False
    assert "reviewer_disabled" in decision.reasons


def test_reviewer_enabled_triggers(monkeypatch):
    monkeypatch.setenv("MODEL_REVIEWER_ENABLED", "true")
    import app.core.config as config

    config.get_settings.cache_clear()
    reset_model_router()
    ctx = ModelRoutingContext(security_sensitive=True, release_blocking=True)
    decision = decide_reviewer(ctx)
    assert decision.required is True
    assert "security_sensitive" in decision.reasons
    assert "release_blocking" in decision.reasons


def test_intent_to_task_skips_extra_classifier():
    router = get_model_router()
    assert (
        router.intent_to_task_type("test_generation")
        == LLMTaskType.TEST_CASE_GENERATION
    )
    assert router.intent_to_task_type("exploratory") == LLMTaskType.EXPLORATORY_SCENARIO
    assert router.intent_to_task_type("bug_report") == LLMTaskType.BUG_REPORT
    assert router.intent_to_task_type("unknown") is None


def test_model_unavailable_falls_back_to_global(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    import app.core.config as config
    import app.services.openai_service as oa_mod

    config.get_settings.cache_clear()
    reset_model_router()
    oa_mod._openai_service = None

    service = oa_mod.OpenAIService()
    mock_client = MagicMock()

    def _create(**kwargs):
        model = kwargs.get("model")
        if model == "gpt-5.6-luna":
            raise RuntimeError(
                "The model `gpt-5.6-luna` does not exist or you do not have access"
            )
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return resp

    mock_client.chat.completions.create.side_effect = _create
    service._client = mock_client

    raw = service.chat(
        "system",
        "user",
        json_mode=True,
        task_type=LLMTaskType.TEST_CASE_GENERATION,
        routing_context=ModelRoutingContext(task_type=LLMTaskType.TEST_CASE_GENERATION),
    )
    assert '"ok"' in raw or "ok" in raw
    assert service.last_chat_model == "gpt-4o-mini"
    assert service.last_routing.get("fallback_used") is True
    assert service.last_routing.get("actual_model_used") == "gpt-4o-mini"
    assert "gpt-5.6-luna" in service._unavailable_models


def test_complete_provider_failure_uses_deterministic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    import app.core.config as config
    import app.services.openai_service as oa_mod

    config.get_settings.cache_clear()
    reset_model_router()
    oa_mod._openai_service = None
    service = oa_mod.OpenAIService()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError(
        "rate limit exceeded"
    )
    service._client = mock_client

    raw = service.chat(
        "Classify the QA intent. Return JSON",
        "generate tests",
        json_mode=True,
        task_type=LLMTaskType.INTENT_CLASSIFICATION,
    )
    data = oa_mod.OpenAIService._parse_json(raw)
    assert "intent" in data
    assert service.last_chat_backend == "deterministic_fallback"
    assert service.last_routing.get("actual_model_used") is None


def test_agents_pass_task_type_not_model_id():
    """Smoke: chat_json is invoked with task_type kwarg from TestCaseAgent path."""
    import app.agents.specialists as specialists

    openai = MagicMock()
    openai.available = True
    openai.chat_json.return_value = {
        "test_cases": [
            {
                "test_case_id": "TC-001",
                "title": "Checkout happy path",
                "steps": ["Open checkout", "Pay"],
                "expected_result": "Order placed",
                "graph_path": ["Checkout", "Payment"],
            }
        ]
    }
    fused = specialists.FusedContext(
        feature_context={"id": "f1", "name": "Checkout", "project_id": "p1"},
        flow_paths=[["Checkout", "Payment"]],
        graph_context=[{"path": ["Checkout", "Payment"]}],
    )
    agent = specialists.TestCaseAgent()
    cases = agent._generate_with_llm("Generate tests for Checkout", fused, "p1", openai)
    assert cases
    assert openai.chat_json.called
    kwargs = openai.chat_json.call_args.kwargs
    assert kwargs.get("task_type") == LLMTaskType.TEST_CASE_GENERATION
    assert "model" not in kwargs


def test_copilot_response_includes_model_routing(monkeypatch):
    from app.main import create_app
    from fastapi.testclient import TestClient

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
    reset_model_router()

    client = TestClient(create_app())
    email = f"routing-admin-{uuid4().hex[:8]}@example.com"
    password = "SecurePass123!"
    asyncio.run(
        get_user_service().create_user(
            UserCreateInput(
                name="Routing Test Admin",
                email=email,
                password=password,
                role="admin",
                isActive=True,
            )
        )
    )
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["accessToken"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    seed = client.post("/api/demo/seed").json()
    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": seed["project_id"],
            "query": "Generate comprehensive QA coverage for Sign In.",
            "root_feature": "Sign In",
        },
    ).json()
    assert "model_routing" in result
    assert result["model_routing"].get("task_type")
    assert result["model_routing"].get("base_model")
    assert result["model_routing"].get("selected_model")
    assert any(
        step["step"] == "Model Routing" for step in result.get("execution_trace") or []
    )
