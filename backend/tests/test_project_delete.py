"""Complete project deletion — isolation, resource cleanup, demo recreate."""

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
def client():
    from app.main import create_app

    return TestClient(create_app())


def _create(client: TestClient, name: str, root: str | None = None) -> dict:
    body: dict = {"name": name}
    if root is not None:
        body["root_feature"] = root
    return client.post("/api/projects", json=body).json()


def _import_graph(client: TestClient, project_id: str) -> dict:
    return client.post(
        f"/api/projects/{project_id}/flow/import",
        json={
            "root": "Checkout",
            "branches": [
                {"name": "Guest Checkout"},
                {"name": "Payment", "children": [{"name": "Card"}]},
            ],
        },
    ).json()


def test_delete_unknown_project(client):
    res = client.delete("/api/projects/project_does_not_exist")
    assert res.status_code == 404


def test_delete_empty_project(client):
    proj = _create(client, "Empty")
    res = client.delete(f"/api/projects/{proj['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["deleted_project_id"] == proj["id"]
    assert body["deleted_resources"]["nodes"] == 0
    assert client.get(f"/api/projects/{proj['id']}").status_code == 404
    assert all(p["id"] != proj["id"] for p in client.get("/api/projects").json())


def test_delete_project_with_graph(client):
    proj = _create(client, "WithGraph")
    graph = _import_graph(client, proj["id"])
    assert len(graph["nodes"]) >= 3
    res = client.delete(f"/api/projects/{proj['id']}").json()
    assert res["deleted_resources"]["nodes"] >= 3
    assert res["deleted_resources"]["edges"] >= 2
    assert client.get(f"/api/projects/{proj['id']}/flow").status_code == 404


def test_delete_project_with_knowledge_and_vectors(client):
    a = _create(client, "KnowA")
    b = _create(client, "KnowB")
    client.post(
        f"/api/projects/{a['id']}/documents/text",
        json={"filename": "a.md", "text": "Project A checkout validation rules."},
    )
    client.post(
        f"/api/projects/{b['id']}/documents/text",
        json={"filename": "b.md", "text": "Project B refund policy details."},
    )
    # Ensure B still searchable after A delete
    before_b = client.get(f"/api/projects/{b['id']}/documents").json()
    assert len(before_b) >= 1

    deleted = client.delete(f"/api/projects/{a['id']}").json()
    assert deleted["deleted_resources"]["documents"] >= 1
    assert deleted["deleted_resources"]["vectors"] >= 1
    assert client.get(f"/api/projects/{a['id']}").status_code == 404
    assert client.get(f"/api/projects/{a['id']}/documents").json() == []

    docs_b = client.get(f"/api/projects/{b['id']}/documents").json()
    assert len(docs_b) == len(before_b)
    hits = client.get(f"/api/projects/{b['id']}/search", params={"q": "refund"}).json()
    assert isinstance(hits, list)

def test_delete_project_with_bugs_and_tests(client):
    from app.graph.store import get_graph_store

    proj = _create(client, "Artifacts", root="Feature")
    other = _create(client, "KeepMe", root="Other")
    store = get_graph_store()
    store.upsert_test_case(proj["id"], {"test_case_id": "TC-DEL-1", "title": "A test"})
    store.upsert_bug(proj["id"], {"bug_id": "BUG-DEL-1", "title": "A bug"})
    store.upsert_test_case(other["id"], {"test_case_id": "TC-KEEP-1", "title": "Keep"})
    store.upsert_bug(other["id"], {"bug_id": "BUG-KEEP-1", "title": "Keep"})
    store.set_latest_analysis(
        proj["id"],
        {
            "project_id": proj["id"],
            "coverage": {"overall_coverage": 0.4},
            "execution_trace": [],
            "evidence": [],
        },
    )

    deleted = client.delete(f"/api/projects/{proj['id']}").json()
    assert deleted["deleted_resources"]["tests"] >= 1
    assert deleted["deleted_resources"]["bugs"] >= 1
    assert deleted["deleted_resources"]["coverage"] >= 1

    assert client.get(f"/api/projects/{proj['id']}").status_code == 404
    assert client.get(f"/api/projects/{proj['id']}/tests").json() == []
    assert client.get(f"/api/projects/{proj['id']}/bugs").json() == []
    keep_tests = client.get(f"/api/projects/{other['id']}/tests").json()
    keep_bugs = client.get(f"/api/projects/{other['id']}/bugs").json()
    assert any(t.get("test_case_id") == "TC-KEEP-1" or "TC-KEEP-1" in str(t) for t in keep_tests)
    assert any(b.get("bug_id") == "BUG-KEEP-1" or "BUG-KEEP-1" in str(b) for b in keep_bugs)

def test_delete_does_not_affect_other_projects(client):
    a = _create(client, "Project A", root="A Root")
    b = _create(client, "Project B", root="B Root")
    ga = _import_graph(client, a["id"])
    gb = client.post(
        f"/api/projects/{b['id']}/flow/import",
        json={"root": "Payments", "branches": [{"name": "Card"}, {"name": "Wallet"}]},
    ).json()
    b_node_ids = {n["id"] for n in gb["nodes"]}
    b_names = {n["name"] for n in gb["nodes"]}

    client.delete(f"/api/projects/{a['id']}")
    assert client.get(f"/api/projects/{a['id']}").status_code == 404

    still = client.get(f"/api/projects/{b['id']}").json()
    assert still["id"] == b["id"]
    flow_b = client.get(f"/api/projects/{b['id']}/flow").json()
    assert {n["id"] for n in flow_b["nodes"]} == b_node_ids
    assert {n["name"] for n in flow_b["nodes"]} == b_names
    # A graph nodes must not leak into B
    assert not ({n["id"] for n in ga["nodes"]} & {n["id"] for n in flow_b["nodes"]})


def test_delete_demo_and_reseed(client):
    seed = client.post("/api/demo/seed").json()
    demo_id = seed["project_id"]
    assert client.get(f"/api/projects/{demo_id}").status_code == 200

    deleted = client.delete(f"/api/projects/{demo_id}").json()
    assert deleted["success"] is True
    assert client.get(f"/api/projects/{demo_id}").status_code == 404

    again = client.post("/api/demo/seed").json()
    assert again["project_id"] != demo_id or again.get("reused_project") is False
    assert client.get(f"/api/projects/{again['project_id']}").status_code == 200
    flow = client.get(f"/api/projects/{again['project_id']}/flow").json()
    assert len(flow["nodes"]) > 0


def test_delete_selected_vs_non_selected_isolation(client):
    """Deleting one of two projects leaves the other fully intact (simulates selected/non-selected)."""
    selected = _create(client, "Selected")
    other = _create(client, "Other")
    _import_graph(client, selected["id"])
    _import_graph(client, other["id"])

    # Delete non-selected (other) first
    client.delete(f"/api/projects/{other['id']}")
    assert client.get(f"/api/projects/{selected['id']}/flow").json()["nodes"]
    assert client.get(f"/api/projects/{other['id']}").status_code == 404

    # Delete selected
    client.delete(f"/api/projects/{selected['id']}")
    ids = {p["id"] for p in client.get("/api/projects").json()}
    assert selected["id"] not in ids
    assert other["id"] not in ids


def test_delete_response_shape(client):
    proj = _create(client, "Shape")
    _import_graph(client, proj["id"])
    body = client.delete(f"/api/projects/{proj['id']}").json()
    assert set(body.keys()) >= {"success", "deleted_project_id", "deleted_resources"}
    resources = body["deleted_resources"]
    for key in ("nodes", "edges", "documents", "vectors", "tests", "bugs", "coverage"):
        assert key in resources
        assert isinstance(resources[key], int)
