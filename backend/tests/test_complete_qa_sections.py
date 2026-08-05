"""Coverage dedupe + complete QA analysis bug/regression section tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.dedup import dedupe_strings


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


def test_dedupe_strings_preserves_first_and_order():
    values = [
        "Uncovered external dependency: Payment Gateway",
        "Uncovered external dependency: Payment Gateway",
        "  Uncovered external dependency: Payment Gateway  ",
        "Uncovered failure path: Timeout",
    ]
    out = dedupe_strings(values)
    assert out == [
        "Uncovered external dependency: Payment Gateway",
        "Uncovered failure path: Timeout",
    ]


def test_coverage_engine_dedupes_critical_gaps(client):
    from app.graph.store import get_graph_store
    from app.graph.traversal import get_coverage_engine
    from app.models.enums import NodeType
    from app.models.schemas import GraphEdge, GraphNode

    proj = client.post("/api/projects", json={"name": "DupGaps", "root_feature": "Checkout"}).json()
    store = get_graph_store()
    root = next(n for n in store.get_project_graph(proj["id"]).nodes if n.type == NodeType.FEATURE)
    # Two external dependency nodes with the same display name
    for i in range(2):
        dep = GraphNode(
            type=NodeType.EXTERNAL_DEPENDENCY,
            name="Payment Gateway",
            project_id=proj["id"],
            is_external_dependency=True,
        )
        store.upsert_node(dep)
        store.upsert_edge(GraphEdge(source=root.id, target=dep.id, relationship="DEPENDS_ON"))

    coverage = get_coverage_engine().analyze(proj["id"], "Checkout")
    gateway_ext = [
        g
        for g in coverage.critical_gaps
        if g.casefold() == "uncovered external dependency: payment gateway"
    ]
    assert len(gateway_ext) == 1
    # Exact duplicate strings must not appear
    assert len(coverage.critical_gaps) == len(dedupe_strings(coverage.critical_gaps))


def test_complete_analysis_returns_bugs_and_regression(client):
    seed = client.post("/api/demo/seed").json()
    project_id = seed["project_id"]
    res = client.post(
        "/api/copilot/query",
        json={
            "project_id": project_id,
            "query": "Generate comprehensive test cases and coverage gaps for Sign In",
            "include_critic": True,
            "requested_outputs": [
                "test_cases",
                "exploratory_scenarios",
                "bug_reports",
                "regression_recommendations",
                "coverage",
                "evidence",
            ],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("bug_reports"), list)
    assert isinstance(body.get("regression_recommendations"), list)
    assert len(body["bug_reports"]) >= 1
    assert len(body["regression_recommendations"]) >= 1
    status = body.get("section_status") or {}
    assert status.get("bug_reports", {}).get("status") in {"success", "empty"}
    assert status.get("regression_recommendations", {}).get("status") in {"success", "empty"}
    assert status["bug_reports"]["count"] == len(body["bug_reports"])
    # Trace should mention both agents
    steps = " ".join(s.get("step", "") for s in body.get("execution_trace") or [])
    assert "Bug Report" in steps
    assert "Regression" in steps


def test_checkout_style_graph_produces_both_sections(client):
    proj = client.post(
        "/api/projects",
        json={"name": "Checkout QA", "root_feature": "Checkout"},
    ).json()
    client.post(
        f"/api/projects/{proj['id']}/flow/import",
        json={
            "root": "Checkout",
            "branches": [
                {"name": "Cart Validation", "type": "Validation"},
                {
                    "name": "Payment",
                    "type": "UserFlow",
                    "children": [
                        {"name": "Payment Gateway", "type": "ExternalDependency", "is_external_dependency": True},
                        {"name": "Payment Decline", "type": "FailurePath", "is_failure_path": True},
                        {"name": "Gateway Timeout", "type": "FailurePath", "is_failure_path": True},
                    ],
                },
                {"name": "Order Confirmation", "type": "UserFlow"},
            ],
        },
    )
    body = client.post(
        "/api/copilot/query",
        json={
            "project_id": proj["id"],
            "query": "Complete QA analysis for Checkout",
            "requested_outputs": [
                "test_cases",
                "bug_reports",
                "regression_recommendations",
                "coverage",
            ],
        },
    ).json()
    assert body["bug_reports"], "expected candidate bug reports from failure/external paths"
    assert body["regression_recommendations"], "expected regression recommendations"
    assert "bug_reports" in (body.get("section_status") or {})


def test_response_always_includes_arrays(client):
    proj = client.post("/api/projects", json={"name": "Emptyish"}).json()
    body = client.post(
        "/api/copilot/query",
        json={"project_id": proj["id"], "query": "Generate tests"},
    ).json()
    assert "bug_reports" in body
    assert "regression_recommendations" in body
    assert isinstance(body["bug_reports"], list)
    assert isinstance(body["regression_recommendations"], list)
