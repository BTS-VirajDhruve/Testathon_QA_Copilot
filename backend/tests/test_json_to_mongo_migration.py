"""Tests for JSON -> Mongo document-store migration guarantees."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from app.db.mongo import get_sync_database
from app.graph.store import get_graph_store
from app.integrations.atlassian import field_mapping, token_store
from app.integrations.atlassian.schemas import JiraFieldMapping
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_mongo_migration_env(monkeypatch, tmp_path):
    graph_path = tmp_path / "graph_store.json"
    chroma = tmp_path / "chroma"
    data = tmp_path / "data"
    data.mkdir()
    chroma.mkdir()
    monkeypatch.setenv("GRAPH_STORE_PATH", str(graph_path))
    monkeypatch.setenv("CHROMA_DIR", str(chroma))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("ENABLE_DEMO_FALLBACK", "false")
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MONGO_ENABLED", "true")
    monkeypatch.setenv("MONGO_URI", "mongomock://localhost")
    monkeypatch.setenv(
        "MONGO_DB_NAME",
        f"qa_copilot_migration_{tmp_path.name}",
    )
    monkeypatch.setenv("ATLASSIAN_TOKEN_ENCRYPTION_KEY", "migration-test-key")

    import asyncio

    import app.core.config as config
    import app.db.mongo as mongo_mod
    import app.graph.store as store_mod
    import app.rag.vector_store as vs_mod
    import app.services.openai_service as oa_mod

    config.get_settings.cache_clear()
    asyncio.run(mongo_mod.close_mongo())
    asyncio.run(mongo_mod.init_mongo())
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None
    yield
    config.get_settings.cache_clear()
    asyncio.run(mongo_mod.close_mongo())
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None


@pytest.fixture
def client(authenticated_client: TestClient):
    return authenticated_client


def test_graph_lifecycle_and_project_scoped_concurrency(client: TestClient):
    store = get_graph_store()

    project_a = client.post(
        "/api/projects",
        json={"name": "Migration A", "root_feature": "Checkout"},
    ).json()
    project_b = client.post(
        "/api/projects",
        json={"name": "Migration B", "root_feature": "Upload"},
    ).json()
    for project in (project_a, project_b):
        imported = client.post(
            f"/api/projects/{project['id']}/flow/import",
            json={
                "root": "Root",
                "branches": [{"name": "Branch One"}, {"name": "Branch Two"}],
            },
        )
        assert imported.status_code == 200

    def _upsert_many(project_id: str) -> None:
        for idx in range(12):
            store.upsert_test_case(
                project_id,
                {"test_case_id": "TC-COLLIDE", "title": f"{project_id}-#{idx}"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_upsert_many, project_a["id"])
        future_b = pool.submit(_upsert_many, project_b["id"])
        future_a.result()
        future_b.result()

    db = get_sync_database()
    assert db["qa_projects"].count_documents({}) == 2
    assert db["qa_nodes"].count_documents({"project_id": project_a["id"]}) > 0
    assert db["qa_nodes"].count_documents({"project_id": project_b["id"]}) > 0

    test_docs = list(db["qa_test_cases"].find({"test_case_id": "TC-COLLIDE"}))
    assert len(test_docs) == 2
    assert {row["project_id"] for row in test_docs} == {
        project_a["id"],
        project_b["id"],
    }
    assert len({row["key"] for row in test_docs}) == 2

    deleted = client.delete(f"/api/projects/{project_a['id']}")
    assert deleted.status_code == 200
    assert (
        db["qa_projects"].count_documents({"project_id": project_a["id"]}) == 0
    )
    assert db["qa_nodes"].count_documents({"project_id": project_a["id"]}) == 0
    assert (
        db["qa_test_cases"].count_documents({"project_id": project_a["id"]}) == 0
    )
    assert (
        db["qa_projects"].count_documents({"project_id": project_b["id"]}) == 1
    )
    assert db["qa_nodes"].count_documents({"project_id": project_b["id"]}) > 0


def test_document_chunk_persistence_and_no_vectors_in_mongo(client: TestClient):
    project = client.post(
        "/api/projects",
        json={"name": "Docs Migration", "root_feature": "Knowledge"},
    ).json()
    text = (
        "Checkout flow requires address validation.\n\n"
        "Retry policy applies when external inventory times out.\n\n"
        "Manual approval path is required for high-value orders."
    )
    ingest = client.post(
        f"/api/projects/{project['id']}/documents/text",
        json={"filename": "requirements.md", "text": text},
    )
    assert ingest.status_code == 200
    assert ingest.json()["indexed_chunks"] >= 1

    hits = client.get(
        f"/api/projects/{project['id']}/search",
        params={"q": "inventory timeout"},
    )
    assert hits.status_code == 200
    assert isinstance(hits.json(), list)

    db = get_sync_database()
    doc = db["qa_documents"].find_one({"project_id": project["id"]})
    assert doc is not None
    chunks = list(db["qa_document_chunks"].find({"project_id": project["id"]}))
    assert chunks
    for row in chunks:
        assert "embedding" not in row
        assert "embedding" not in (row.get("chunk") or {})

    # Migration contract: Mongo stores JSON documents/chunks, not vector embeddings.
    mongo_collections = set(db.list_collection_names())
    disallowed_vector_collections = {
        "vectors",
        "embeddings",
        "qa_vectors",
        "vector_index",
    }
    assert not (mongo_collections & disallowed_vector_collections)


def test_analysis_reviews_and_overrides_persist_in_mongo(client: TestClient):
    project = client.post(
        "/api/projects",
        json={"name": "Review Persistence", "root_feature": "Create Journey"},
    ).json()
    project_id = project["id"]

    client.post(
        f"/api/projects/{project_id}/flow/import",
        json={"root": "Create Journey", "branches": [{"name": "Save"}]},
    )
    store = get_graph_store()
    store.upsert_test_case(
        project_id,
        {
            "test_case_id": "TC-REV-1",
            "title": "Save Journey with required title",
            "steps": ["Open page", "Enter title", "Click Save"],
            "expected_result": "Journey is saved",
            "graph_path": ["Create Journey", "Save"],
        },
    )

    store.set_latest_analysis(
        project_id,
        {
            "analysis_id": "analysis-review-1",
            "project_id": project_id,
            "reviewed_test_cases": [{"test_case": {"test_case_id": "TC-REV-1"}}],
            "test_cases": [{"test_case_id": "TC-REV-1"}],
        },
    )
    store.set_test_review(
        project_id,
        "TC-REV-1",
        {
            "project_id": project_id,
            "test_case_id": "TC-REV-1",
            "validity_review": {"validity": "valid"},
            "automation_review": {"automation_suitability": "automate"},
        },
    )
    override = client.patch(
        f"/api/projects/{project_id}/tests/TC-REV-1/automation-review",
        json={
            "automation_suitability": "manual",
            "override_reason": "Needs human UX judgment",
        },
    )
    assert override.status_code == 200

    db = get_sync_database()
    analysis_doc = db["qa_analyses"].find_one(
        {"project_id": project_id, "is_latest": True}
    )
    assert analysis_doc is not None
    review_doc = db["qa_test_reviews"].find_one(
        {"project_id": project_id, "test_case_id": "TC-REV-1"}
    )
    assert review_doc is not None
    override_doc = db["qa_test_review_overrides"].find_one(
        {"project_id": project_id, "test_case_id": "TC-REV-1"}
    )
    assert override_doc is not None
    assert (override_doc.get("override") or {}).get("human_override") is True


def test_atlassian_token_state_and_field_mapping_persist_to_mongo():
    token_store.set_tokens(
        access_token="atl-access-token",
        refresh_token="atl-refresh-token",
        expires_in=1800,
        scopes=["read:jira-work"],
    )
    token_store.save_oauth_state(
        "state-123",
        {"cloud_id": "cloud-1", "nonce": "abc"},
    )
    mapping = JiraFieldMapping(
        cloud_id="cloud-1", acceptance_criteria_fields=["customfield_10016"]
    )
    field_mapping.save_mapping(mapping)

    db = get_sync_database()
    conn_doc = db["atlassian_connections"].find_one({"scope_key": "local"})
    assert conn_doc is not None
    assert (conn_doc.get("connection") or {}).get("encrypted_access_token")
    assert token_store.get_access_token() == "atl-access-token"
    assert token_store.get_refresh_token() == "atl-refresh-token"

    state_doc = db["atlassian_oauth_states"].find_one({"state": "state-123"})
    assert state_doc is not None
    popped = token_store.pop_oauth_state("state-123")
    assert popped is not None
    assert (
        db["atlassian_oauth_states"].find_one({"state": "state-123"})
        is None
    )

    mapping_doc = db["atlassian_field_mappings"].find_one({"cloud_id": "cloud-1"})
    assert mapping_doc is not None
    loaded = field_mapping.load_mapping("cloud-1")
    assert loaded.acceptance_criteria_fields == ["customfield_10016"]


def test_health_reports_mongo_chroma_runtime(client: TestClient):
    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["graph_store_mode"] in {"mongo", "neo4j+mongo"}
    assert payload["vector_store_mode"] == "chroma"
    assert payload["graph_store_path"] is None
