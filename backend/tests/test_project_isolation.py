"""Project isolation, generic feature support, and RAG scoping tests."""

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


def _create_project(client: TestClient, name: str, root: str | None = None) -> dict:
    body: dict = {"name": name, "description": f"{name} isolation test"}
    if root is not None:
        body["root_feature"] = root
    return client.post("/api/projects", json=body).json()


def _import_flow(client: TestClient, project_id: str, root: str, branches: list) -> dict:
    return client.post(
        f"/api/projects/{project_id}/flow/import",
        json={"root": root, "branches": branches},
    ).json()


# ---------------------------------------------------------------------------
# A. PROJECT CREATION
# ---------------------------------------------------------------------------


def test_new_project_has_no_demo_content(client):
    demo = client.post("/api/demo/seed").json()
    assert demo["root_feature"] == "Sign In"

    empty = _create_project(client, "Clean Project")
    flow = client.get(f"/api/projects/{empty['id']}/flow").json()
    tests = client.get(f"/api/projects/{empty['id']}/tests").json()
    bugs = client.get(f"/api/projects/{empty['id']}/bugs").json()
    docs = client.get(f"/api/projects/{empty['id']}/documents").json()
    dash = client.get(f"/api/projects/{empty['id']}/dashboard").json()
    analysis = client.get(f"/api/projects/{empty['id']}/latest-analysis").json()

    assert flow["nodes"] == [] or len(flow["nodes"]) == 0
    assert tests == []
    assert bugs == []
    assert docs == []
    assert dash["test_case_count"] == 0
    assert dash["historical_bugs"] == 0
    assert dash["node_count"] == 0
    assert analysis["analysis"] is None
    assert empty["id"] != demo["project_id"]


def test_new_project_with_custom_root_is_not_signin(client):
    proj = _create_project(client, "Checkout App", "Checkout")
    flow = client.get(f"/api/projects/{proj['id']}/flow").json()
    names = [n["name"] for n in flow["nodes"]]
    assert "Checkout" in names
    assert "Sign In" not in names


# ---------------------------------------------------------------------------
# B / C. PROJECT SWITCHING + DEMO LOADING
# ---------------------------------------------------------------------------


def test_demo_seed_idempotent_and_selects_demo(client):
    first = client.post("/api/demo/seed").json()
    second = client.post("/api/demo/seed").json()
    assert first["project_id"] == second["project_id"]
    assert second["reused_project"] is True
    flow = client.get(f"/api/projects/{second['project_id']}/flow").json()
    assert any(n["name"] == "Sign In" for n in flow["nodes"])


def test_demo_load_does_not_overwrite_other_project(client):
    other = _create_project(client, "Other Store", "Checkout")
    _import_flow(
        client,
        other["id"],
        "Checkout",
        [{"name": "Guest Checkout"}, {"name": "Payment"}],
    )
    demo = client.post("/api/demo/seed").json()
    other_flow = client.get(f"/api/projects/{other['id']}/flow").json()
    other_names = [n["name"] for n in other_flow["nodes"]]
    assert "Checkout" in other_names
    assert "Sign In" not in other_names
    assert demo["project_id"] != other["id"]


# ---------------------------------------------------------------------------
# D. GRAPH RAG ISOLATION
# ---------------------------------------------------------------------------


def test_graph_rag_no_cross_project_paths(client):
    a = _create_project(client, "Auth A", "Sign In")
    b = _create_project(client, "Shop B", "Checkout")
    _import_flow(
        client,
        a["id"],
        "Sign In",
        [{"name": "Email + Password", "children": ["Valid Credentials"]}],
    )
    _import_flow(
        client,
        b["id"],
        "Checkout",
        [{"name": "Guest Checkout"}, {"name": "Payment"}],
    )

    paths_a = client.get(f"/api/projects/{a['id']}/paths").json()
    paths_b = client.get(f"/api/projects/{b['id']}/paths").json()

    names_a = {" → ".join(p["node_names"]) for p in paths_a["paths"]}
    names_b = {" → ".join(p["node_names"]) for p in paths_b["paths"]}
    assert any("Sign In" in n for n in names_a)
    assert any("Checkout" in n for n in names_b)
    assert not any("Checkout" in n for n in names_a)
    assert not any("Sign In" in n for n in names_b)


def test_same_feature_name_isolated_across_projects(client):
    a = _create_project(client, "Portal A", "Search")
    b = _create_project(client, "Portal B", "Search")
    _import_flow(client, a["id"], "Search", [{"name": "Filters A"}])
    _import_flow(client, b["id"], "Search", [{"name": "Filters B"}])

    paths_a = client.get(f"/api/projects/{a['id']}/paths").json()
    paths_b = client.get(f"/api/projects/{b['id']}/paths").json()
    assert any("Filters A" in p["node_names"] for p in paths_a["paths"])
    assert any("Filters B" in p["node_names"] for p in paths_b["paths"])
    assert not any("Filters B" in p["node_names"] for p in paths_a["paths"])


def test_empty_project_graph_paths(client):
    empty = _create_project(client, "Empty")
    paths = client.get(f"/api/projects/{empty['id']}/paths")
    # Empty projects have no root — honest 404, not demo fallback
    assert paths.status_code == 404
    flow = client.get(f"/api/projects/{empty['id']}/flow").json()
    assert flow["nodes"] == []


# ---------------------------------------------------------------------------
# E. VECTOR RAG ISOLATION
# ---------------------------------------------------------------------------


def test_vector_rag_no_cross_project_hits(client):
    a = _create_project(client, "Docs A", "Feature A")
    b = _create_project(client, "Docs B", "Feature B")
    shared_text = "UNIQUE_VECTOR_ISOLATION_TOKEN shared wording for both projects"

    client.post(
        f"/api/projects/{a['id']}/documents/text",
        json={"filename": "a.md", "text": f"{shared_text} project-alpha-only"},
    )
    client.post(
        f"/api/projects/{b['id']}/documents/text",
        json={"filename": "b.md", "text": f"{shared_text} project-beta-only"},
    )

    hits_a = client.get(f"/api/projects/{a['id']}/search", params={"q": shared_text}).json()
    hits_b = client.get(f"/api/projects/{b['id']}/search", params={"q": shared_text}).json()

    # API may return list or {hits: [...]} depending on route — normalize
    list_a = hits_a if isinstance(hits_a, list) else hits_a.get("hits") or hits_a.get("results") or []
    list_b = hits_b if isinstance(hits_b, list) else hits_b.get("hits") or hits_b.get("results") or []

    contents_a = " ".join(str(h.get("content", "")) for h in list_a)
    contents_b = " ".join(str(h.get("content", "")) for h in list_b)
    assert "project-alpha-only" in contents_a or list_a == []
    assert "project-beta-only" not in contents_a
    assert "project-beta-only" in contents_b or list_b == []
    assert "project-alpha-only" not in contents_b


def test_empty_project_vector_search(client):
    empty = _create_project(client, "No Knowledge")
    hits = client.get(f"/api/projects/{empty['id']}/search", params={"q": "anything"}).json()
    list_hits = hits if isinstance(hits, list) else hits.get("hits") or []
    assert list_hits == []


# ---------------------------------------------------------------------------
# F. HYBRID RAG / ARTIFACT KEY ISOLATION
# ---------------------------------------------------------------------------


def test_test_case_keys_do_not_collide_across_projects(client):
    from app.graph.store import get_graph_store

    a = _create_project(client, "Proj A", "Checkout")
    b = _create_project(client, "Proj B", "Upload")
    store = get_graph_store()
    store.upsert_test_case(a["id"], {"test_case_id": "TC-001", "title": "Checkout happy path"})
    store.upsert_test_case(b["id"], {"test_case_id": "TC-001", "title": "Upload happy path"})
    store.persist()

    tests_a = client.get(f"/api/projects/{a['id']}/tests").json()
    tests_b = client.get(f"/api/projects/{b['id']}/tests").json()
    assert len(tests_a) == 1
    assert len(tests_b) == 1
    assert tests_a[0]["title"] == "Checkout happy path"
    assert tests_b[0]["title"] == "Upload happy path"


def test_hybrid_context_single_project(client):
    from app.models.enums import QAIntent
    from app.rag.retrieval import assert_project_consistency, get_context_fusion

    a = _create_project(client, "Hybrid A", "Checkout")
    b = _create_project(client, "Hybrid B", "Sign In")
    _import_flow(client, a["id"], "Checkout", [{"name": "Payment"}])
    _import_flow(client, b["id"], "Sign In", [{"name": "Email + Password"}])
    client.post(
        f"/api/projects/{a['id']}/documents/text",
        json={"filename": "a.md", "text": "Checkout payment requirements"},
    )
    client.post(
        f"/api/projects/{b['id']}/documents/text",
        json={"filename": "b.md", "text": "Sign In oauth requirements"},
    )

    fusion = get_context_fusion()
    plan, fused = fusion.fuse(a["id"], "Generate tests for Checkout", QAIntent.TEST_GENERATION, root_feature="Checkout")
    fused = assert_project_consistency(fused, a["id"])
    assert plan is not None
    assert fused.feature_context.get("project_id") == a["id"]
    for hit in fused.semantic_context:
        meta = hit.get("metadata") or {}
        pid = hit.get("project_id") or meta.get("project_id")
        if pid:
            assert pid == a["id"]
    for tc in fused.existing_coverage:
        assert tc.get("project_id") in (None, a["id"])
    blob = str(fused.flow_paths) + str(fused.feature_context)
    assert "Checkout" in blob or fused.feature_context.get("name") == "Checkout"
    assert "Sign In" not in str(fused.flow_paths)


# ---------------------------------------------------------------------------
# G. GENERIC FEATURE SUPPORT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,root,branches,query_token",
    [
        (
            "E-commerce Store",
            "Checkout",
            [
                {"name": "Guest Checkout"},
                {"name": "Registered User"},
                {"name": "Payment"},
                {"name": "Address Validation"},
            ],
            "Checkout",
        ),
        (
            "Document Portal",
            "File Upload",
            [
                {"name": "Valid File"},
                {"name": "Unsupported Type", "is_failure_path": True},
                {"name": "Oversized File", "is_failure_path": True},
                {"name": "Upload Interrupted", "is_failure_path": True},
            ],
            "Upload",
        ),
        (
            "Catalog",
            "Product Search",
            [{"name": "Filters"}, {"name": "Sorting"}, {"name": "Empty Results"}],
            "Search",
        ),
        (
            "Admin Console",
            "Admin Role Management",
            [{"name": "Role Assignment"}, {"name": "Permission Check"}],
            "Role",
        ),
        (
            "Orders API",
            "API Order Creation",
            [{"name": "Schema Validation"}, {"name": "Inventory Service"}],
            "Order",
        ),
    ],
)
def test_generic_feature_generation(client, name, root, branches, query_token):
    proj = _create_project(client, name, root)
    _import_flow(client, proj["id"], root, branches)
    client.post(
        f"/api/projects/{proj['id']}/documents/text",
        json={"filename": f"{root.lower().replace(' ', '_')}.md", "text": f"Requirements for {root}."},
    )

    result = client.post(
        "/api/copilot/query",
        json={
            "project_id": proj["id"],
            "query": f"Generate comprehensive QA coverage for {root}.",
            "root_feature": root,
            "include_critic": True,
            "enable_targeted_regeneration": True,
            "max_regeneration_rounds": 1,
        },
    ).json()

    assert result["project_id"] == proj["id"]
    assert result.get("root_feature") == root
    assert result["test_cases"], f"Expected tests for {root}"
    joined = " ".join(
        tc.get("title", "") + " " + " ".join(tc.get("graph_path") or []) for tc in result["test_cases"]
    )
    assert query_token.lower() in joined.lower() or root.lower() in joined.lower()
    # Sign In must not appear unless it is the feature under test
    if root != "Sign In":
        assert "sign in" not in joined.lower()


# ---------------------------------------------------------------------------
# H. EMPTY PROJECT
# ---------------------------------------------------------------------------


def test_empty_project_copilot_no_crash(client):
    empty = _create_project(client, "Blank")
    result = client.post(
        "/api/copilot/query",
        json={"project_id": empty["id"], "query": "Generate tests for anything"},
    ).json()
    assert result["project_id"] == empty["id"]
    # Honest empty / low-confidence response — no demo Sign In injection
    narrative = (result.get("narrative") or "").lower()
    assert "sign in" not in narrative or result.get("root_feature") in (None, "")


def test_missing_project_returns_404_style(client):
    res = client.get("/api/projects/does_not_exist/flow")
    assert res.status_code == 404
    dash = client.get("/api/projects/does_not_exist/dashboard")
    assert dash.status_code == 404


# ---------------------------------------------------------------------------
# Persistence path stability
# ---------------------------------------------------------------------------


def test_settings_paths_are_absolute():
    from app.core.config import get_settings

    settings = get_settings()
    from pathlib import Path

    assert Path(settings.data_dir).is_absolute()
    assert Path(settings.chroma_dir).is_absolute()
    assert Path(settings.graph_store_path).is_absolute()
