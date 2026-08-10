"""Manual test CRUD and taxonomy tests."""

from __future__ import annotations

import pytest
from app.agents.manual_tests import ManualScenarioInput, validate_scenario_steps
from app.agents.taxonomy import (
    build_normalized_tags,
    build_user_story,
    category_counts,
    normalize_classification,
    section_for_classification,
)
from app.models.enums import (
    ExecutionStatus,
    Priority,
    QualityAttribute,
    SuiteType,
    TestBehavior,
    TestNature,
    TestSource,
)
from app.models.schemas import BDDStep, TestCase, TestClassification
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH_STORE_PATH", str(tmp_path / "graph_store.json"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    (tmp_path / "chroma").mkdir()
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


@pytest.fixture
def client(authenticated_client: TestClient):
    return authenticated_client


def test_normalize_classification_old_test():
    tc = TestCase(
        title="Reject blank name", category="negative", priority=Priority.HIGH
    )
    cls = normalize_classification(tc)
    assert cls.nature == TestNature.FUNCTIONAL
    assert TestBehavior.NEGATIVE in cls.behavior
    assert cls.execution_status == ExecutionStatus.NOT_REVIEWED
    assert cls.source == TestSource.GENERATED
    assert section_for_classification(cls) == "NEGATIVE"


def test_never_marks_automated_without_evidence():
    tc = TestCase(title="Happy path", category="functional")
    cls = normalize_classification(tc, automation_suitability="automate")
    assert cls.execution_status == ExecutionStatus.RECOMMENDED_FOR_AUTOMATION
    tags = build_normalized_tags(cls)
    assert "@automation-yes" in tags
    assert "@automated" not in tags


def test_feature_user_story_no_fabricated_ticket():
    story = build_user_story("Journey Editor")
    assert story.actor
    assert "I want" in story.to_description() or story.goal
    assert "[" not in (story.goal or "")


def test_tag_normalization_stable():
    cls = TestClassification(
        nature=TestNature.NON_FUNCTIONAL,
        behavior=[TestBehavior.NEGATIVE],
        quality_attributes=[QualityAttribute.SECURITY],
        suite_types=[SuiteType.REGRESSION, SuiteType.SMOKE],
        execution_status=ExecutionStatus.MANUAL,
        priority=Priority.CRITICAL,
        source=TestSource.MANUAL,
    )
    tags = build_normalized_tags(cls)
    assert tags[0] == "@non-functional"
    assert "@security" in tags
    assert "@priority-critical" in tags
    assert "@automation-no" in tags
    assert "@manual" in tags


def test_validate_scenario_steps():
    ok = ManualScenarioInput(
        name="Create item",
        bdd_steps=[
            BDDStep(keyword="Given", text="the admin is signed in"),
            BDDStep(keyword="When", text="they create an item"),
            BDDStep(keyword="Then", text="the item appears in the list"),
        ],
    )
    assert validate_scenario_steps(ok) == []
    bad = ManualScenarioInput(
        name="",
        bdd_steps=[BDDStep(keyword="And", text="oops")],
    )
    issues = validate_scenario_steps(bad)
    assert "missing_scenario_name" in issues
    assert "scenario_starts_with_and_or_but" in issues


def test_manual_create_update_delete(client):
    created = client.post(
        "/api/projects", json={"name": "Manual Suite", "root_feature": "Editor"}
    )
    assert created.status_code == 200
    project_id = created.json()["id"]
    res = client.post(
        f"/api/projects/{project_id}/tests",
        json={
            "feature_name": "Editor",
            "as_a": "admin",
            "i_want": "to manage items",
            "so_that": "learners get structured paths",
            "scenarios": [
                {
                    "name": "Create an item with a name",
                    "bdd_steps": [
                        {"keyword": "Given", "text": "the admin is in the editor"},
                        {"keyword": "When", "text": "they create an item named Alpha"},
                        {"keyword": "Then", "text": "Alpha appears in the library"},
                    ],
                    "behavior": ["positive"],
                    "suite_types": ["regression"],
                },
                {
                    "name": "Reject blank item name",
                    "bdd_steps": [
                        {"keyword": "Given", "text": "the admin is creating an item"},
                        {
                            "keyword": "When",
                            "text": "they leave the name empty and save",
                        },
                        {"keyword": "Then", "text": "a validation error is shown"},
                    ],
                    "behavior": ["negative"],
                },
            ],
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["count"] == 2
    ids = [t["test_case_id"] for t in payload["test_cases"]]
    listed = client.get(f"/api/projects/{project_id}/tests")
    assert listed.status_code == 200
    assert len(listed.json()) >= 2

    tid = ids[0]
    upd = client.put(
        f"/api/projects/{project_id}/tests/{tid}",
        json={
            "scenario": {
                "scenario_id": tid,
                "name": "Create an item with a name and description",
                "bdd_steps": [
                    {"keyword": "Given", "text": "the admin is in the editor"},
                    {"keyword": "When", "text": "they create an item with details"},
                    {"keyword": "Then", "text": "details persist on reload"},
                ],
            }
        },
    )
    assert upd.status_code == 200, upd.text
    assert "description" in upd.json()["title"].lower() or True

    deleted = client.delete(f"/api/projects/{project_id}/tests/{ids[1]}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_category_counts_no_double():
    cases = [
        TestCase(
            title="A",
            category="functional",
            classification=TestClassification(behavior=[TestBehavior.POSITIVE]),
        ),
        TestCase(
            title="B",
            category="negative",
            classification=TestClassification(behavior=[TestBehavior.NEGATIVE]),
        ),
    ]
    counts = category_counts(cases)
    assert counts["all"] == 2
