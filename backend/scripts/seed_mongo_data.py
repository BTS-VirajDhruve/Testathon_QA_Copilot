"""Seed realistic sample data into migrated Mongo document-store collections.

The seed is idempotent: each record uses a deterministic `_id` and is upserted
with `replace_one(..., upsert=True)` so repeated runs do not create duplicates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.db.mongo import (
    get_atlassian_connections_collection_sync,
    get_atlassian_field_mappings_collection_sync,
    get_atlassian_oauth_states_collection_sync,
    get_collection_sync,
    init_mongo,
)

TARGET_COLLECTIONS = [
    "qa_projects",
    "qa_nodes",
    "qa_edges",
    "qa_documents",
    "qa_document_chunks",
    "qa_test_cases",
    "qa_bugs",
    "qa_analyses",
    "qa_test_reviews",
    "qa_test_review_overrides",
    "qa_graph_versions",
    "qa_external_knowledge_sources",
    "atlassian_connections",
    "atlassian_oauth_states",
    "atlassian_field_mappings",
    "users",
    "refresh_tokens",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime | None = None) -> str:
    return (ts or _now()).isoformat()


def _upsert_many(collection: Any, docs: list[dict[str, Any]]) -> int:
    for doc in docs:
        collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return len(docs)


def _seed_projects(now_iso: str) -> list[dict[str, Any]]:
    return [
        {
            "_id": "project_checkout_web",
            "project_id": "project_checkout_web",
            "project": {
                "id": "project_checkout_web",
                "name": "Web Checkout QA Baseline",
                "description": "Checkout journey with discounts, payment, and order confirmation.",
                "root_feature_id": "node_checkout_root",
                "root_node_id": "node_checkout_root",
                "graph_version": 3,
                "created_at": "2026-08-10T08:00:00+00:00",
                "updated_at": now_iso,
                "automation_capability_profile": {
                    "supported_layers": ["ui", "api", "integration"],
                    "ui_frameworks": ["playwright"],
                    "api_testing_available": True,
                    "stable_test_ids_available": True,
                    "test_data_api_available": True,
                    "database_access_available": False,
                    "ci_execution_available": True,
                    "visual_testing_available": True,
                    "accessibility_scanning_available": True,
                },
            },
        },
        {
            "_id": "project_mobile_identity",
            "project_id": "project_mobile_identity",
            "project": {
                "id": "project_mobile_identity",
                "name": "Mobile Identity Verification",
                "description": "KYC onboarding flow with OTP verification and risk checks.",
                "root_feature_id": "node_identity_root",
                "root_node_id": "node_identity_root",
                "graph_version": 2,
                "created_at": "2026-08-10T08:15:00+00:00",
                "updated_at": now_iso,
                "automation_capability_profile": {
                    "supported_layers": ["ui", "api"],
                    "ui_frameworks": ["appium"],
                    "api_testing_available": True,
                    "stable_test_ids_available": False,
                    "test_data_api_available": True,
                    "database_access_available": False,
                    "ci_execution_available": True,
                    "mobile_device_lab_available": True,
                },
            },
        },
    ]


def _seed_nodes(now_iso: str) -> list[dict[str, Any]]:
    seed_nodes = [
        {
            "node_id": "node_checkout_root",
            "project_id": "project_checkout_web",
            "type": "Feature",
            "name": "Checkout",
            "description": "Root checkout flow from cart to order success.",
        },
        {
            "node_id": "node_checkout_address",
            "project_id": "project_checkout_web",
            "type": "Page",
            "name": "Address Entry",
            "description": "Shipping address and postal code validation.",
        },
        {
            "node_id": "node_checkout_payment_api",
            "project_id": "project_checkout_web",
            "type": "API",
            "name": "Payment Authorization API",
            "description": "Calls gateway for card authorization and 3DS.",
        },
        {
            "node_id": "node_checkout_inventory",
            "project_id": "project_checkout_web",
            "type": "ExternalDependency",
            "name": "Inventory Service",
            "description": "Checks stock for all cart line items.",
        },
        {
            "node_id": "node_checkout_failure_payment",
            "project_id": "project_checkout_web",
            "type": "FailurePath",
            "name": "Payment Timeout Path",
            "description": "Fallback behavior when payment provider times out.",
            "is_failure_path": True,
        },
        {
            "node_id": "node_identity_root",
            "project_id": "project_mobile_identity",
            "type": "Feature",
            "name": "Identity Verification",
            "description": "KYC identity and liveness verification flow.",
        },
        {
            "node_id": "node_identity_capture",
            "project_id": "project_mobile_identity",
            "type": "Screen",
            "name": "Document Capture Screen",
            "description": "Capture passport image and validate quality.",
        },
        {
            "node_id": "node_identity_otp",
            "project_id": "project_mobile_identity",
            "type": "AuthenticationMethod",
            "name": "Phone OTP",
            "description": "One-time password verification before KYC submit.",
        },
        {
            "node_id": "node_identity_rules",
            "project_id": "project_mobile_identity",
            "type": "BusinessRule",
            "name": "Age and Country Eligibility",
            "description": "Reject unsupported countries and underage users.",
        },
    ]
    docs: list[dict[str, Any]] = []
    for node in seed_nodes:
        node_payload = {
            "id": node["node_id"],
            "type": node["type"],
            "name": node["name"],
            "description": node["description"],
            "metadata": {
                "seed": "mongo_seed_v1",
                "domain": "qa-copilot",
            },
            "criticality": "high" if "root" in node["node_id"] else "medium",
            "is_failure_path": bool(node.get("is_failure_path", False)),
            "is_external_dependency": node["type"] == "ExternalDependency",
            "is_critical": "root" in node["node_id"],
            "project_id": node["project_id"],
            "provenance": {
                "source_type": "user_input",
                "source_reference": "seed-script",
                "confidence": 1.0,
                "inferred": False,
            },
            "created_at": "2026-08-10T08:30:00+00:00",
            "updated_at": now_iso,
        }
        docs.append(
            {
                "_id": node["node_id"],
                "node_id": node["node_id"],
                "project_id": node["project_id"],
                "type": node["type"],
                "name_lc": node["name"].lower(),
                "node": node_payload,
            }
        )
    return docs


def _seed_edges(now_iso: str) -> list[dict[str, Any]]:
    seed_edges = [
        (
            "edge_checkout_root_address",
            "project_checkout_web",
            "node_checkout_root",
            "node_checkout_address",
            "HAS_CHILD",
        ),
        (
            "edge_checkout_address_inventory",
            "project_checkout_web",
            "node_checkout_address",
            "node_checkout_inventory",
            "DEPENDS_ON",
        ),
        (
            "edge_checkout_root_payment",
            "project_checkout_web",
            "node_checkout_root",
            "node_checkout_payment_api",
            "CALLS",
        ),
        (
            "edge_checkout_payment_failure",
            "project_checkout_web",
            "node_checkout_payment_api",
            "node_checkout_failure_payment",
            "HAS_FAILURE_PATH",
        ),
        (
            "edge_identity_root_capture",
            "project_mobile_identity",
            "node_identity_root",
            "node_identity_capture",
            "HAS_CHILD",
        ),
        (
            "edge_identity_capture_otp",
            "project_mobile_identity",
            "node_identity_capture",
            "node_identity_otp",
            "REQUIRES",
        ),
        (
            "edge_identity_root_rules",
            "project_mobile_identity",
            "node_identity_root",
            "node_identity_rules",
            "HAS_BUSINESS_RULE",
        ),
    ]
    docs: list[dict[str, Any]] = []
    for edge_id, project_id, source, target, relationship in seed_edges:
        docs.append(
            {
                "_id": edge_id,
                "edge_id": edge_id,
                "project_id": project_id,
                "source_node_id": source,
                "target_node_id": target,
                "relationship": relationship,
                "edge": {
                    "id": edge_id,
                    "source": source,
                    "target": target,
                    "relationship": relationship,
                    "metadata": {"seed": "mongo_seed_v1"},
                    "provenance": {
                        "source_type": "user_input",
                        "source_reference": "seed-script",
                        "confidence": 1.0,
                        "inferred": False,
                    },
                    "created_at": now_iso,
                },
            }
        )
    return docs


def _seed_documents_and_chunks(
    now_iso: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents = [
        {
            "_id": "doc_checkout_requirements",
            "document_id": "doc_checkout_requirements",
            "project_id": "project_checkout_web",
            "filename": "checkout_requirements.md",
            "content_hash": "sha256:checkout-requirements-v1",
            "document": {
                "id": "doc_checkout_requirements",
                "project_id": "project_checkout_web",
                "filename": "checkout_requirements.md",
                "content_type": "text/markdown",
                "text": "Checkout requires address validation, payment authorization, and order confirmation.",
                "chunk_ids": ["chunk_checkout_001", "chunk_checkout_002"],
                "created_at": now_iso,
                "chunks": [
                    {
                        "id": "chunk_checkout_001",
                        "document_id": "doc_checkout_requirements",
                        "project_id": "project_checkout_web",
                        "content": "Address entry validates postal code and country support before payment step.",
                        "metadata": {
                            "source_type": "requirements",
                            "feature": "Checkout",
                        },
                        "source_reference": "checkout_requirements.md#address",
                    },
                    {
                        "id": "chunk_checkout_002",
                        "document_id": "doc_checkout_requirements",
                        "project_id": "project_checkout_web",
                        "content": "If payment provider times out, user sees retry prompt and order is not created.",
                        "metadata": {
                            "source_type": "requirements",
                            "feature": "Checkout",
                        },
                        "source_reference": "checkout_requirements.md#payment-timeout",
                    },
                ],
            },
        },
        {
            "_id": "doc_identity_policy",
            "document_id": "doc_identity_policy",
            "project_id": "project_mobile_identity",
            "filename": "identity_policy.md",
            "content_hash": "sha256:identity-policy-v2",
            "document": {
                "id": "doc_identity_policy",
                "project_id": "project_mobile_identity",
                "filename": "identity_policy.md",
                "content_type": "text/markdown",
                "text": "Identity verification requires OTP and eligibility checks for age and country.",
                "chunk_ids": ["chunk_identity_001"],
                "created_at": now_iso,
                "chunks": [
                    {
                        "id": "chunk_identity_001",
                        "document_id": "doc_identity_policy",
                        "project_id": "project_mobile_identity",
                        "content": "Reject applicants under 18 or from unsupported countries before KYC submission.",
                        "metadata": {
                            "source_type": "policy",
                            "feature": "Identity Verification",
                        },
                        "source_reference": "identity_policy.md#eligibility",
                    }
                ],
            },
        },
    ]
    chunks = [
        {
            "_id": "chunk_checkout_001",
            "chunk_id": "chunk_checkout_001",
            "project_id": "project_checkout_web",
            "document_id": "doc_checkout_requirements",
            "source_type": "requirements",
            "feature": "Checkout",
            "chunk_index": 0,
            "chunk": documents[0]["document"]["chunks"][0],
        },
        {
            "_id": "chunk_checkout_002",
            "chunk_id": "chunk_checkout_002",
            "project_id": "project_checkout_web",
            "document_id": "doc_checkout_requirements",
            "source_type": "requirements",
            "feature": "Checkout",
            "chunk_index": 1,
            "chunk": documents[0]["document"]["chunks"][1],
        },
        {
            "_id": "chunk_identity_001",
            "chunk_id": "chunk_identity_001",
            "project_id": "project_mobile_identity",
            "document_id": "doc_identity_policy",
            "source_type": "policy",
            "feature": "Identity Verification",
            "chunk_index": 0,
            "chunk": documents[1]["document"]["chunks"][0],
        },
    ]
    return documents, chunks


def _seed_test_cases(now_iso: str) -> list[dict[str, Any]]:
    test_cases = [
        {
            "key": "project_checkout_web::TC-CHECKOUT-001",
            "project_id": "project_checkout_web",
            "test_case_id": "TC-CHECKOUT-001",
            "title": "Checkout succeeds with valid card and in-stock items",
            "priority": "high",
            "risk": "medium",
            "generation_method": "llm",
            "graph_path": ["Checkout", "Address Entry", "Payment Authorization API"],
            "expected_result": "Order confirmation is displayed and order ID is generated.",
        },
        {
            "key": "project_checkout_web::TC-CHECKOUT-002",
            "project_id": "project_checkout_web",
            "test_case_id": "TC-CHECKOUT-002",
            "title": "Checkout retries when payment authorization times out",
            "priority": "critical",
            "risk": "high",
            "generation_method": "targeted",
            "graph_path": [
                "Checkout",
                "Payment Authorization API",
                "Payment Timeout Path",
            ],
            "expected_result": "Retry prompt is shown and no duplicate order is created.",
        },
        {
            "key": "project_mobile_identity::TC-KYC-001",
            "project_id": "project_mobile_identity",
            "test_case_id": "TC-KYC-001",
            "title": "KYC completes for eligible user with valid OTP",
            "priority": "high",
            "risk": "medium",
            "generation_method": "llm",
            "graph_path": [
                "Identity Verification",
                "Document Capture Screen",
                "Phone OTP",
            ],
            "expected_result": "User profile status moves to verified.",
        },
    ]
    docs: list[dict[str, Any]] = []
    for case in test_cases:
        test_case_payload = {
            "test_case_id": case["test_case_id"],
            "title": case["title"],
            "category": "functional",
            "priority": case["priority"],
            "risk": case["risk"],
            "preconditions": ["User account exists", "Test data seeded"],
            "test_data": {"user_id": "seed-user-qa-analyst"},
            "steps": [
                "Open target experience",
                "Execute required user actions",
                "Submit and observe final state",
            ],
            "expected_result": case["expected_result"],
            "testing_technique": "state transition",
            "graph_path": case["graph_path"],
            "graph_reasoning": "Covers core user path with explicit failure/alternate handling.",
            "source_references": ["seed:requirements", "seed:flow-graph"],
            "confidence": "high",
            "assumptions": ["External dependencies are reachable in staging."],
            "project_id": case["project_id"],
            "feature_id": case["graph_path"][0].lower().replace(" ", "_"),
            "generation_method": case["generation_method"],
            "reasoning": "Regression-sensitive scenario selected from migrated graph paths.",
            "human_edited": False,
            "postconditions": ["System retains consistent state"],
            "objective": "Protect critical business flow from regressions.",
            "obligation_ids": [
                f"OBL-{case['test_case_id']}",
            ],
            "generation_round": 1,
            "revision_version": 1,
            "reviewer_finding_ids": [],
            "retired": False,
            "do_not_edit": False,
            "updated_at": now_iso,
        }
        docs.append(
            {
                "_id": case["key"],
                "key": case["key"],
                "project_id": case["project_id"],
                "test_case_id": case["test_case_id"],
                "generation_method": case["generation_method"],
                "updated_at": now_iso,
                "test_case": test_case_payload,
            }
        )
    return docs


def _seed_bugs(now_iso: str) -> list[dict[str, Any]]:
    bugs = [
        {
            "key": "project_checkout_web::BUG-CHECKOUT-401",
            "project_id": "project_checkout_web",
            "bug_id": "BUG-CHECKOUT-401",
            "title": "Order created twice after payment timeout retry",
            "severity": "high",
            "graph_path": [
                "Checkout",
                "Payment Authorization API",
                "Payment Timeout Path",
            ],
        },
        {
            "key": "project_mobile_identity::BUG-KYC-102",
            "project_id": "project_mobile_identity",
            "bug_id": "BUG-KYC-102",
            "title": "OTP resend bypasses rate limit after app backgrounding",
            "severity": "medium",
            "graph_path": ["Identity Verification", "Phone OTP"],
        },
    ]
    docs: list[dict[str, Any]] = []
    for bug in bugs:
        bug_payload = {
            "bug_id": bug["bug_id"],
            "title": bug["title"],
            "severity": bug["severity"],
            "steps_to_reproduce": [
                "Execute nominal flow until critical step",
                "Trigger unstable dependency behavior",
                "Observe inconsistent state transition",
            ],
            "expected_result": "System maintains idempotent and policy-compliant behavior.",
            "actual_result": "Observed behavior violates expected resilience controls.",
            "environment": "staging-eu-west",
            "graph_path": bug["graph_path"],
            "affected_components": ["web-frontend", "order-service"],
            "source_references": ["seed:historical-bugs"],
            "classification": "historical",
            "generation_method": "manual",
            "business_impact": "Can increase support load and user churn.",
            "missing_information": "",
            "project_id": bug["project_id"],
            "created_at": "2026-08-10T07:45:00+00:00",
        }
        docs.append(
            {
                "_id": bug["key"],
                "key": bug["key"],
                "project_id": bug["project_id"],
                "bug_id": bug["bug_id"],
                "created_at": "2026-08-10T07:45:00+00:00",
                "bug": bug_payload,
            }
        )
    return docs


def _seed_analyses(now_iso: str) -> list[dict[str, Any]]:
    analyses = [
        {
            "_id": "analysis_checkout_latest",
            "analysis_id": "analysis_checkout_latest",
            "project_id": "project_checkout_web",
            "is_latest": True,
            "created_at": "2026-08-10T08:40:00+00:00",
            "updated_at": now_iso,
            "analysis": {
                "analysis_id": "analysis_checkout_latest",
                "project_id": "project_checkout_web",
                "query": "Generate resilient checkout tests",
                "intent": "test_generation",
                "risk_level": "high",
                "test_cases": [
                    {"test_case_id": "TC-CHECKOUT-001"},
                    {"test_case_id": "TC-CHECKOUT-002"},
                ],
                "reviewed_test_cases": [
                    {"test_case": {"test_case_id": "TC-CHECKOUT-001"}},
                    {"test_case": {"test_case_id": "TC-CHECKOUT-002"}},
                ],
                "critical_gaps": ["Payment timeout handling path"],
                "coverage_before": {"coverage_percentage": 58.0, "total_paths": 12},
                "coverage_after": {"coverage_percentage": 82.0, "total_paths": 12},
                "created_at": "2026-08-10T08:40:00+00:00",
                "updated_at": now_iso,
            },
        },
        {
            "_id": "analysis_identity_latest",
            "analysis_id": "analysis_identity_latest",
            "project_id": "project_mobile_identity",
            "is_latest": True,
            "created_at": "2026-08-10T08:50:00+00:00",
            "updated_at": now_iso,
            "analysis": {
                "analysis_id": "analysis_identity_latest",
                "project_id": "project_mobile_identity",
                "query": "Assess KYC verification coverage",
                "intent": "coverage_gap",
                "risk_level": "medium",
                "test_cases": [{"test_case_id": "TC-KYC-001"}],
                "critical_gaps": ["Country eligibility edge rules"],
                "coverage_before": {"coverage_percentage": 49.0, "total_paths": 8},
                "coverage_after": {"coverage_percentage": 71.0, "total_paths": 8},
                "created_at": "2026-08-10T08:50:00+00:00",
                "updated_at": now_iso,
            },
        },
    ]
    return analyses


def _seed_reviews(now_iso: str) -> list[dict[str, Any]]:
    reviews = [
        {
            "_id": "project_checkout_web::TC-CHECKOUT-001",
            "key": "project_checkout_web::TC-CHECKOUT-001",
            "project_id": "project_checkout_web",
            "test_case_id": "TC-CHECKOUT-001",
            "updated_at": now_iso,
            "review": {
                "project_id": "project_checkout_web",
                "test_case_id": "TC-CHECKOUT-001",
                "validity_review": {
                    "validity": "valid",
                    "validity_score": 91,
                    "validity_reasons": [
                        "Steps map directly to observed checkout behavior."
                    ],
                },
                "automation_review": {
                    "automation_suitability": "automate",
                    "automation_score": 87,
                    "recommended_layer": "ui",
                },
                "final_review_status": "approved",
                "updated_at": now_iso,
            },
        },
        {
            "_id": "project_checkout_web::TC-CHECKOUT-002",
            "key": "project_checkout_web::TC-CHECKOUT-002",
            "project_id": "project_checkout_web",
            "test_case_id": "TC-CHECKOUT-002",
            "updated_at": now_iso,
            "review": {
                "project_id": "project_checkout_web",
                "test_case_id": "TC-CHECKOUT-002",
                "validity_review": {
                    "validity": "needs_revision",
                    "validity_score": 73,
                    "validity_reasons": [
                        "Timeout threshold must be specified per environment."
                    ],
                },
                "automation_review": {
                    "automation_suitability": "automate_with_conditions",
                    "automation_score": 68,
                    "recommended_layer": "integration",
                },
                "final_review_status": "needs_revision",
                "updated_at": now_iso,
            },
        },
    ]
    return reviews


def _seed_overrides(now_iso: str) -> list[dict[str, Any]]:
    override = {
        "_id": "project_checkout_web::TC-CHECKOUT-002",
        "key": "project_checkout_web::TC-CHECKOUT-002",
        "project_id": "project_checkout_web",
        "test_case_id": "TC-CHECKOUT-002",
        "override_timestamp": now_iso,
        "override": {
            "project_id": "project_checkout_web",
            "test_case_id": "TC-CHECKOUT-002",
            "human_override": True,
            "override_reason": "Manual business approval still required for large-value orders.",
            "final_review_status": "approved_with_changes",
            "override_timestamp": now_iso,
        },
    }
    return [override]


def _seed_graph_versions() -> list[dict[str, Any]]:
    return [
        {
            "_id": "project_checkout_web::1",
            "key": "project_checkout_web::1",
            "project_id": "project_checkout_web",
            "version": 1,
            "saved_at": "2026-08-10T08:10:00+00:00",
            "snapshot": {
                "project_id": "project_checkout_web",
                "root_node_id": "node_checkout_root",
                "version": 1,
                "nodes": ["node_checkout_root", "node_checkout_address"],
                "edges": ["edge_checkout_root_address"],
            },
        },
        {
            "_id": "project_checkout_web::2",
            "key": "project_checkout_web::2",
            "project_id": "project_checkout_web",
            "version": 2,
            "saved_at": "2026-08-10T08:20:00+00:00",
            "snapshot": {
                "project_id": "project_checkout_web",
                "root_node_id": "node_checkout_root",
                "version": 2,
                "nodes": [
                    "node_checkout_root",
                    "node_checkout_address",
                    "node_checkout_payment_api",
                ],
                "edges": [
                    "edge_checkout_root_address",
                    "edge_checkout_root_payment",
                ],
            },
        },
        {
            "_id": "project_mobile_identity::1",
            "key": "project_mobile_identity::1",
            "project_id": "project_mobile_identity",
            "version": 1,
            "saved_at": "2026-08-10T08:25:00+00:00",
            "snapshot": {
                "project_id": "project_mobile_identity",
                "root_node_id": "node_identity_root",
                "version": 1,
                "nodes": ["node_identity_root", "node_identity_capture"],
                "edges": ["edge_identity_root_capture"],
            },
        },
    ]


def _seed_external_sources(now_iso: str) -> list[dict[str, Any]]:
    return [
        {
            "_id": "src_jira_checkout_story_201",
            "source_id": "src_jira_checkout_story_201",
            "qa_project_id": "project_checkout_web",
            "cloud_id": "cloud_dev_ecommerce",
            "source_type": "jira_issue",
            "external_id": "201",
            "last_synced_at": now_iso,
            "source": {
                "source_id": "src_jira_checkout_story_201",
                "qa_project_id": "project_checkout_web",
                "provider": "atlassian",
                "source_type": "jira_issue",
                "cloud_id": "cloud_dev_ecommerce",
                "container_id": "1001",
                "container_key": "WEB",
                "external_id": "201",
                "external_key": "WEB-201",
                "title": "Checkout should retry payment timeout once",
                "normalized_content": "Story describes timeout retry and no duplicate orders.",
                "source_url": "https://example.atlassian.net/browse/WEB-201",
                "version": "14",
                "remote_created_at": "2026-07-01T09:00:00+00:00",
                "remote_updated_at": "2026-08-05T09:15:00+00:00",
                "imported_at": "2026-08-10T08:35:00+00:00",
                "last_synced_at": now_iso,
                "content_hash": "sha256:web-201-v14",
                "metadata": {"labels": ["checkout", "resilience"]},
                "sync_status": "imported",
                "document_id": "doc_checkout_requirements",
                "chunk_count": 2,
                "error": None,
            },
        },
        {
            "_id": "src_conf_identity_page_991",
            "source_id": "src_conf_identity_page_991",
            "qa_project_id": "project_mobile_identity",
            "cloud_id": "cloud_dev_mobile",
            "source_type": "confluence_page",
            "external_id": "991",
            "last_synced_at": now_iso,
            "source": {
                "source_id": "src_conf_identity_page_991",
                "qa_project_id": "project_mobile_identity",
                "provider": "atlassian",
                "source_type": "confluence_page",
                "cloud_id": "cloud_dev_mobile",
                "container_id": "KYCDOC",
                "container_key": "KYC",
                "external_id": "991",
                "external_key": None,
                "title": "Identity eligibility policy",
                "normalized_content": "KYC policy describes country and age restrictions.",
                "source_url": "https://example.atlassian.net/wiki/spaces/KYC/pages/991",
                "version": "7",
                "remote_created_at": "2026-06-15T10:00:00+00:00",
                "remote_updated_at": "2026-08-03T11:30:00+00:00",
                "imported_at": "2026-08-10T08:45:00+00:00",
                "last_synced_at": now_iso,
                "content_hash": "sha256:kyc-page-991-v7",
                "metadata": {"labels": ["kyc", "policy"]},
                "sync_status": "updated",
                "document_id": "doc_identity_policy",
                "chunk_count": 1,
                "error": None,
            },
        },
    ]


def _seed_atlassian(now_iso: str) -> dict[str, int]:
    connection_doc = {
        "_id": "local",
        "scope_key": "local",
        "updated_at": now_iso,
        "connection": {
            "connection_id": "atl_connection_seed_local",
            "user_scope_id": "local",
            "status": "connected",
            "selected_cloud_id": "cloud_dev_ecommerce",
            "selected_site_name": "Ecommerce Dev Site",
            "selected_site_url": "https://example.atlassian.net",
            "encrypted_access_token": "enc:seed-access-token",
            "encrypted_refresh_token": "enc:seed-refresh-token",
            "token_expiry": (_now() + timedelta(hours=4)).isoformat(),
            "granted_scopes": [
                "read:jira-work",
                "read:space:confluence",
                "read:page:confluence",
                "offline_access",
            ],
            "products": ["jira-software", "confluence"],
            "created_at": "2026-08-10T08:05:00+00:00",
            "updated_at": now_iso,
        },
    }
    state_docs = [
        {
            "_id": "oauth_state_seed_checkout",
            "state": "oauth_state_seed_checkout",
            "created_at": now_iso,
            "payload": {
                "cloud_id": "cloud_dev_ecommerce",
                "nonce": "seed-nonce-1",
                "created_at": now_iso,
            },
        },
        {
            "_id": "oauth_state_seed_identity",
            "state": "oauth_state_seed_identity",
            "created_at": now_iso,
            "payload": {
                "cloud_id": "cloud_dev_mobile",
                "nonce": "seed-nonce-2",
                "created_at": now_iso,
            },
        },
    ]
    mapping_docs = [
        {
            "_id": "cloud_dev_ecommerce",
            "cloud_id": "cloud_dev_ecommerce",
            "mapping": {
                "cloud_id": "cloud_dev_ecommerce",
                "summary_field": "summary",
                "description_field": "description",
                "acceptance_criteria_fields": ["customfield_10016"],
                "business_rules_fields": ["customfield_10103"],
                "test_notes_fields": ["customfield_10220"],
                "risk_fields": ["customfield_10300"],
                "environment_fields": ["customfield_10422"],
                "labels_field": "labels",
                "components_field": "components",
            },
        },
        {
            "_id": "cloud_dev_mobile",
            "cloud_id": "cloud_dev_mobile",
            "mapping": {
                "cloud_id": "cloud_dev_mobile",
                "summary_field": "summary",
                "description_field": "description",
                "acceptance_criteria_fields": ["customfield_20016"],
                "business_rules_fields": ["customfield_20103"],
                "test_notes_fields": ["customfield_20220"],
                "risk_fields": ["customfield_20300"],
                "environment_fields": ["customfield_20422"],
                "labels_field": "labels",
                "components_field": "components",
            },
        },
    ]

    conn_count = _upsert_many(
        get_atlassian_connections_collection_sync(), [connection_doc]
    )
    state_count = _upsert_many(get_atlassian_oauth_states_collection_sync(), state_docs)
    mapping_count = _upsert_many(
        get_atlassian_field_mappings_collection_sync(), mapping_docs
    )
    return {
        "atlassian_connections": conn_count,
        "atlassian_oauth_states": state_count,
        "atlassian_field_mappings": mapping_count,
    }


def _seed_users_and_refresh_tokens(now: datetime) -> dict[str, int]:
    users = [
        {
            "_id": "usr_seed_qa_admin",
            "name": "Seed QA Admin",
            "email": "qa.admin.seed@example.local",
            "password": "$argon2id$seed$qa$admin",
            "forgotPasswordToken": None,
            "forgotPasswordTokenExpiresAt": None,
            "inviteToken": None,
            "inviteTokenExpiresAt": None,
            "invitedAt": None,
            "inviteAcceptedAt": now,
            "isActive": True,
            "role": "admin",
            "createdAt": now,
            "updatedAt": now,
            "deletedAt": None,
        },
        {
            "_id": "usr_seed_qa_analyst",
            "name": "Seed QA Analyst",
            "email": "qa.analyst.seed@example.local",
            "password": "$argon2id$seed$qa$analyst",
            "forgotPasswordToken": None,
            "forgotPasswordTokenExpiresAt": None,
            "inviteToken": None,
            "inviteTokenExpiresAt": None,
            "invitedAt": now,
            "inviteAcceptedAt": now,
            "isActive": True,
            "role": "user",
            "createdAt": now,
            "updatedAt": now,
            "deletedAt": None,
        },
    ]
    refresh_tokens = [
        {
            "_id": "rt_seed_admin_active",
            "userId": "usr_seed_qa_admin",
            "tokenHash": "hash_seed_admin_active",
            "expiresAt": now + timedelta(days=10),
            "createdAt": now,
            "updatedAt": now,
            "revokedAt": None,
            "replacedByTokenId": None,
        },
        {
            "_id": "rt_seed_analyst_rotated",
            "userId": "usr_seed_qa_analyst",
            "tokenHash": "hash_seed_analyst_rotated",
            "expiresAt": now + timedelta(days=3),
            "createdAt": now - timedelta(days=2),
            "updatedAt": now - timedelta(days=1),
            "revokedAt": now - timedelta(days=1),
            "replacedByTokenId": "rt_seed_analyst_current",
        },
        {
            "_id": "rt_seed_analyst_current",
            "userId": "usr_seed_qa_analyst",
            "tokenHash": "hash_seed_analyst_current",
            "expiresAt": now + timedelta(days=12),
            "createdAt": now - timedelta(days=1),
            "updatedAt": now,
            "revokedAt": None,
            "replacedByTokenId": None,
        },
    ]
    return {
        "users": _upsert_many(get_collection_sync("users"), users),
        "refresh_tokens": _upsert_many(
            get_collection_sync("refresh_tokens"), refresh_tokens
        ),
    }


def _make_json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_make_json_safe(v) for v in value]
    return value


def _collection_summary() -> dict[str, Any]:
    counts: dict[str, int] = {}
    samples: dict[str, Any] = {}
    for collection_name in TARGET_COLLECTIONS:
        collection = get_collection_sync(collection_name)
        counts[collection_name] = collection.count_documents({})
        sample = collection.find_one(sort=[("_id", 1)])
        if sample is None:
            samples[collection_name] = None
            continue
        sample.pop("_id", None)
        samples[collection_name] = _make_json_safe(sample)
    return {"counts": counts, "samples": samples}


def run_seed(*, include_auth: bool = True) -> dict[str, Any]:
    settings = get_settings()
    if not settings.mongo_enabled:
        raise RuntimeError("MONGO_ENABLED must be true before running seed.")
    asyncio.run(init_mongo())

    now = _now()
    now_iso = _iso(now)

    seeded_counts: dict[str, int] = {}
    seeded_counts["qa_projects"] = _upsert_many(
        get_collection_sync("qa_projects"), _seed_projects(now_iso)
    )
    seeded_counts["qa_nodes"] = _upsert_many(
        get_collection_sync("qa_nodes"), _seed_nodes(now_iso)
    )
    seeded_counts["qa_edges"] = _upsert_many(
        get_collection_sync("qa_edges"), _seed_edges(now_iso)
    )

    documents, chunks = _seed_documents_and_chunks(now_iso)
    seeded_counts["qa_documents"] = _upsert_many(
        get_collection_sync("qa_documents"), documents
    )
    seeded_counts["qa_document_chunks"] = _upsert_many(
        get_collection_sync("qa_document_chunks"), chunks
    )
    seeded_counts["qa_test_cases"] = _upsert_many(
        get_collection_sync("qa_test_cases"), _seed_test_cases(now_iso)
    )
    seeded_counts["qa_bugs"] = _upsert_many(
        get_collection_sync("qa_bugs"), _seed_bugs(now_iso)
    )
    seeded_counts["qa_analyses"] = _upsert_many(
        get_collection_sync("qa_analyses"), _seed_analyses(now_iso)
    )
    seeded_counts["qa_test_reviews"] = _upsert_many(
        get_collection_sync("qa_test_reviews"), _seed_reviews(now_iso)
    )
    seeded_counts["qa_test_review_overrides"] = _upsert_many(
        get_collection_sync("qa_test_review_overrides"), _seed_overrides(now_iso)
    )
    seeded_counts["qa_graph_versions"] = _upsert_many(
        get_collection_sync("qa_graph_versions"), _seed_graph_versions()
    )
    seeded_counts["qa_external_knowledge_sources"] = _upsert_many(
        get_collection_sync("qa_external_knowledge_sources"),
        _seed_external_sources(now_iso),
    )
    seeded_counts.update(_seed_atlassian(now_iso))

    if include_auth:
        seeded_counts.update(_seed_users_and_refresh_tokens(now))

    summary = _collection_summary()
    return {
        "seeded_doc_count_by_collection": seeded_counts,
        "collection_counts_after_seed": summary["counts"],
        "sample_records": summary["samples"],
        "assumptions": {
            "mongo_enabled": settings.mongo_enabled,
            "mongo_uri": settings.mongo_uri,
            "mongo_db_name": settings.mongo_db_name,
            "vector_storage": "ChromaDB remains vector store; Mongo stores metadata/docs only.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="Skip seeding users and refresh_tokens collections.",
    )
    args = parser.parse_args()
    summary = run_seed(include_auth=not args.skip_auth)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
