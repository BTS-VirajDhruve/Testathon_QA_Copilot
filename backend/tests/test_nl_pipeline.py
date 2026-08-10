"""Tests for deterministic NL → Intermediate Tree → Graph pipeline."""

from __future__ import annotations

import time

import pytest
from app.graph.nl.builder import tree_to_nested_import, validate_and_repair_graph
from app.graph.nl.classifier import (
    NodeClassifier,
    clear_classification_cache,
    parse_classification_table,
)
from app.graph.nl.parser import parse_to_tree
from app.graph.nl.pipeline import NLGraphPipeline
from app.graph.nl.preprocessor import normalize_text
from app.models.enums import NodeType
from app.models.schemas import GraphNode, SystemFlowGraph
from fastapi.testclient import TestClient

SIMPLE_NL = "Checkout supports guest checkout, registered user, payment, and address validation."

BULLET_NL = """
Checkout is the root feature
- Cart Validation
- Guest Checkout
- Registered User
- Payment
  - Card
  - Wallet
  - COD
- Confirmation
"""

MEDIUM_NL = (
    "Sign In supports email password, Google OAuth, enterprise SSO, "
    "and self-registration. Email login supports MFA and forgot password. "
    "Account lockout is a failure path."
)


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
    clear_classification_cache()
    yield
    config.get_settings.cache_clear()
    store_mod._store = None
    store_mod._neo4j = None
    vs_mod._vector_store = None
    oa_mod._openai_service = None
    clear_classification_cache()


@pytest.fixture
def client(authenticated_client: TestClient):
    return authenticated_client


def test_preprocessor_normalizes_bullets_and_spaces():
    pre = normalize_text("Checkout\n\n\n*  Cart\n• Payment\n\n\n")
    assert "-" in pre.text
    assert "Cart" in pre.text
    assert pre.paragraph_count >= 1


def test_bullet_parser_builds_hierarchy():
    pre = normalize_text(BULLET_NL)
    tree = parse_to_tree(pre)
    assert tree.root.name.lower().startswith("checkout")
    names = [n.name for n in tree.root.children]
    assert any("Payment" in n for n in names)
    payment = next(n for n in tree.root.children if "Payment" in n.name)
    child_names = [c.name for c in payment.children]
    assert any("Card" in c for c in child_names)
    assert any("Wallet" in c for c in child_names)


def test_prose_parser_extracts_supports_list():
    pre = normalize_text(SIMPLE_NL)
    tree = parse_to_tree(pre)
    assert "Checkout" in tree.root.name
    child_names = [c.name.lower() for c in tree.root.children]
    assert any("guest" in n for n in child_names)
    assert any("payment" in n for n in child_names)


def test_classification_table_parser():
    raw = """
Node Name | Node Type
Payment Gateway Timeout | FailurePath
Inventory Service | ExternalDependency
Card Payment | UserFlow
"""
    mapping = parse_classification_table(raw)
    assert mapping["payment gateway timeout"][0] == NodeType.FAILURE_PATH
    assert mapping["inventory service"][0] == NodeType.EXTERNAL_DEPENDENCY


def test_rule_classifier_no_llm_for_simple_graph():
    clear_classification_cache()
    pre = normalize_text(SIMPLE_NL)
    tree = parse_to_tree(pre)
    clf = NodeClassifier()
    clf.threshold = 0.55
    stats = clf.classify_tree(tree, project_id="test")
    assert stats["llm_calls"] <= 1
    nested = tree_to_nested_import(tree)
    assert nested.root
    assert nested.branches


def test_pipeline_deterministic_hierarchy():
    clear_classification_cache()
    pipe = NLGraphPipeline()
    a = pipe.run(SIMPLE_NL, project_id="p1")
    b = pipe.run(SIMPLE_NL, project_id="p1")
    assert a.nested.root == b.nested.root
    assert [br.name for br in a.nested.branches] == [
        br.name for br in b.nested.branches
    ]
    assert a.stats["llm_calls"] == b.stats["llm_calls"]


def test_pipeline_never_returns_llm_json_shape_directly():
    result = NLGraphPipeline().run(MEDIUM_NL, project_id="p2")
    assert result.nested.root
    dumped = result.nested.model_dump()
    assert "id" not in dumped
    for br in dumped["branches"]:
        assert "id" not in br


def test_validate_and_repair_attaches_orphans():
    root = GraphNode(id="feature_a", type=NodeType.FEATURE, name="Root", project_id="p")
    orphan = GraphNode(
        id="node_b", type=NodeType.SUB_FEATURE, name="Orphan", project_id="p"
    )
    graph = SystemFlowGraph(
        project_id="p",
        root_node_id="feature_a",
        nodes=[root, orphan],
        edges=[],
    )
    fixed, repairs = validate_and_repair_graph(graph)
    assert any(r.startswith("orphaned_attached") for r in repairs)
    assert any(e.target == "node_b" for e in fixed.edges)


def test_api_nl_to_graph_uses_new_pipeline(client):
    clear_classification_cache()
    proj = client.post(
        "/api/projects", json={"name": "NL Pipe", "root_feature": "Checkout"}
    ).json()
    graph = client.post(
        f"/api/projects/{proj['id']}/flow/from-text",
        json={"text": SIMPLE_NL},
    ).json()
    names = {n["name"] for n in graph["nodes"]}
    assert any("Checkout" in n for n in names)
    assert len(graph["nodes"]) >= 3
    assert graph["root_node_id"]
    targets = {e["target"] for e in graph["edges"]}
    for n in graph["nodes"]:
        if n["id"] == graph["root_node_id"]:
            continue
        assert n["id"] in targets


def test_json_import_unchanged(client):
    proj = client.post(
        "/api/projects", json={"name": "JSON", "root_feature": "X"}
    ).json()
    payload = {
        "root": "Checkout",
        "description": "typed import",
        "branches": [
            {"name": "Guest Checkout", "type": "UserFlow"},
            {
                "name": "Payment",
                "type": "UserFlow",
                "children": [{"name": "Card", "type": "SubFeature"}],
            },
        ],
    }
    graph = client.post(f"/api/projects/{proj['id']}/flow/import", json=payload).json()
    names = {n["name"] for n in graph["nodes"]}
    assert "Checkout" in names
    assert "Guest Checkout" in names
    assert "Card" in names


def test_nl_benchmark_faster_than_legacy_heuristic_path():
    clear_classification_cache()
    pipe = NLGraphPipeline()
    t0 = time.perf_counter()
    result = pipe.run(SIMPLE_NL, project_id="bench")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 2000
    assert result.stats["llm_calls"] <= 1
    assert result.nested.branches


@pytest.mark.parametrize(
    "text",
    [SIMPLE_NL, BULLET_NL, MEDIUM_NL],
)
def test_pipeline_produces_valid_nested_for_fixtures(text: str):
    clear_classification_cache()
    result = NLGraphPipeline().run(text, project_id="fix")
    assert result.nested.root
    assert isinstance(result.nested.branches, list)
