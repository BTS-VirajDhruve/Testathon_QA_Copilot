"""Seed ShopEase Ecommerce dummy project for QA Copilot."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SAMPLE_DIR = REPO_ROOT / "sample_data" / "ecommerce"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.graph.ingestion import get_flow_ingester
from app.graph.store import get_graph_store
from app.models.schemas import NestedFlowImport
from app.rag.document_ingestion import get_document_ingester
from app.rag.vector_store import get_vector_store

DEMO_PROJECT_NAME = "ShopEase Ecommerce Portal"
DEMO_FLOW_VERSION = "ecommerce-v1"
ROOT_FEATURE = "ShopEase Ecommerce"

KB_FILES = [
    "ecommerce_requirements.md",
    "billing_and_pricing_rules.md",
    "payment_and_security.md",
    "qa_acceptance_criteria.md",
]


def _load_json(name: str) -> Any:
    path = SAMPLE_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_text(name: str) -> str:
    return (SAMPLE_DIR / name).read_text(encoding="utf-8")


def _ecommerce_flow() -> dict[str, Any]:
    return _load_json("ecommerce_flow_typed.json")


def _existing_tests() -> list[dict[str, Any]]:
    return _load_json("seed_tests.json")


def _historical_bugs() -> list[dict[str, Any]]:
    return _load_json("seed_bugs.json")


DEMO_QUERY = (
    "Analyze the ShopEase Ecommerce flow. Generate comprehensive tests focused on "
    "authentication, cart mutations, discount stacking, GST and delivery bill amount "
    "generation, payment failure paths, historical bugs, and uncovered branches. "
    "Then identify coverage gaps and generate targeted tests for the highest-risk gaps."
)


def _flow_fingerprint(flow: dict[str, Any]) -> str:
    payload = json.dumps(flow, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{DEMO_FLOW_VERSION}:{payload}".encode("utf-8")).hexdigest()


def _find_demo_project(store: Any) -> dict[str, Any] | None:
    return next((p for p in store.list_projects() if p.get("name") == DEMO_PROJECT_NAME), None)


def seed_ecommerce_demo(*, force: bool = False) -> dict[str, Any]:
    """Deterministic, repeatable seed for the ShopEase ecommerce dummy project."""
    if not SAMPLE_DIR.is_dir():
        raise FileNotFoundError(f"Ecommerce sample data not found at {SAMPLE_DIR}")

    flow = _ecommerce_flow()
    existing_tests = _existing_tests()
    historical_bugs = _historical_bugs()
    seed_test_ids = {tc["test_case_id"] for tc in existing_tests}
    seed_bug_ids = {bug["bug_id"] for bug in historical_bugs}

    store = get_graph_store()
    fingerprint = _flow_fingerprint(flow)
    reused_project = False
    graph_rewritten = False

    existing = _find_demo_project(store)
    if existing and not force:
        project_id = existing["id"]
        reused_project = True
    else:
        if existing and force:
            project_id = existing["id"]
            reused_project = True
        else:
            project = store.create_project(
                name=DEMO_PROJECT_NAME,
                description=(
                    "Dummy ecommerce portal: auth, catalog, cart, discounts, "
                    "GST/delivery billing, payment, and logout."
                ),
                root_feature=None,
            )
            project_id = project["id"]

    project = store.projects.get(project_id) or {}
    meta = dict(project.get("metadata") or {})
    prior_fp = meta.get("demo_flow_fingerprint")
    graph = store.get_project_graph(project_id)

    if force or prior_fp != fingerprint or not graph.nodes:
        ingester = get_flow_ingester()
        graph = ingester.from_nested_import(
            project_id,
            NestedFlowImport.model_validate(flow),
        )
        graph_rewritten = True
        meta["demo_flow_fingerprint"] = fingerprint
        meta["demo_flow_version"] = DEMO_FLOW_VERSION
        meta["demo_kind"] = "ecommerce"
        project["metadata"] = meta
        project["name"] = DEMO_PROJECT_NAME
        project["description"] = (
            "Dummy ecommerce portal: auth, catalog, cart, discounts, "
            "GST/delivery billing, payment, and logout."
        )
        store.projects[project_id] = project
    else:
        graph = store.get_project_graph(project_id)

    document_ids: list[str] = []
    indexed_total = 0
    for filename in KB_FILES:
        text = _load_text(filename)
        doc = get_document_ingester().ingest_text(
            project_id,
            filename,
            text,
            content_type="text/markdown",
        )
        document_ids.append(doc.id)
        chunks = [
            c for c in get_document_ingester().get_chunks(project_id) if c.document_id == doc.id
        ]
        indexed_total += get_vector_store().upsert_chunks(chunks)

    for tc in existing_tests:
        payload = {**tc, "project_id": project_id, "source": "ecommerce_seed"}
        store.test_cases[tc["test_case_id"]] = payload
    for bug in historical_bugs:
        payload = {**bug, "project_id": project_id, "source": "ecommerce_seed"}
        store.bugs[bug["bug_id"]] = payload

    # Keep intentional coverage gaps: Payment Gateway Timeout, Inventory Reservation
    # Failure, Promo Stacking Rejected, Incorrect Total Display.
    for tc_id, tc in list(store.test_cases.items()):
        if tc.get("project_id") == project_id and tc_id not in seed_test_ids:
            del store.test_cases[tc_id]
    for bug_id, bug in list(store.bugs.items()):
        if bug.get("project_id") == project_id and bug_id not in seed_bug_ids:
            del store.bugs[bug_id]

    store.persist()

    project_tests = [
        tc
        for tc in store.test_cases.values()
        if tc.get("project_id") == project_id and tc.get("test_case_id") in seed_test_ids
    ]
    project_bugs = [
        b for b in store.bugs.values() if b.get("project_id") == project_id and b.get("bug_id") in seed_bug_ids
    ]

    return {
        "project_id": project_id,
        "project_name": DEMO_PROJECT_NAME,
        "root_feature": ROOT_FEATURE,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "document_ids": document_ids,
        "indexed_chunks": indexed_total,
        "existing_tests": len(project_tests),
        "historical_bugs": len(project_bugs),
        "demo_query": DEMO_QUERY,
        "reused_project": reused_project,
        "graph_rewritten": graph_rewritten,
        "flow_fingerprint": fingerprint,
        "high_risk_uncovered_hint": (
            "Payment Gateway Timeout / Inventory Reservation Failure / "
            "Promo Stacking Rejected / Incorrect Total Display"
        ),
        "sample_dir": str(SAMPLE_DIR),
    }


if __name__ == "__main__":
    result = seed_ecommerce_demo(force=True)
    print(result)
