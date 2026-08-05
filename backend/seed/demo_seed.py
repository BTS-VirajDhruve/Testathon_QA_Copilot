"""Seed realistic Sign In demo data for the hackathon workflow."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python -m seed.demo_seed` from backend/
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.graph.ingestion import get_flow_ingester
from app.graph.store import get_graph_store
from app.models.schemas import NestedFlowImport
from app.rag.document_ingestion import get_document_ingester
from app.rag.vector_store import get_vector_store

DEMO_PROJECT_NAME = "Enterprise Authentication Portal"
DEMO_FLOW_VERSION = "phase5-v1"

SIGNIN_FLOW = {
    "root": "Sign In",
    "description": "Enterprise authentication entry for the platform.",
    "branches": [
        {
            "name": "Email + Password",
            "type": "AuthenticationMethod",
            "description": "Classic credential authentication",
            "children": [
                {"name": "Valid Credentials", "type": "UserFlow"},
                {"name": "Invalid Password", "type": "FailurePath", "is_failure_path": True},
                {"name": "Forgot Password", "type": "AlternateFlow"},
                {
                    "name": "MFA",
                    "type": "SubFeature",
                    "is_critical": True,
                    "criticality": "high",
                },
                {
                    "name": "Account Lockout",
                    "type": "FailurePath",
                    "is_failure_path": True,
                    "is_critical": True,
                    "criticality": "high",
                },
            ],
        },
        {
            "name": "Google OAuth",
            "type": "AuthenticationMethod",
            "description": "Social login via Google",
            "children": [
                {"name": "Consent", "type": "UserFlow"},
                {"name": "Callback", "type": "UserFlow", "is_critical": True, "criticality": "high"},
                {
                    "name": "Provider Failure",
                    "type": "FailurePath",
                    "is_failure_path": True,
                    "is_external_dependency": True,
                },
                {"name": "Session Creation", "type": "State"},
            ],
        },
        {
            "name": "Microsoft Enterprise SSO",
            "type": "AuthenticationMethod",
            "description": "Enterprise identity federation via Microsoft IdP",
            "is_critical": True,
            "criticality": "high",
            "is_external_dependency": True,
            "children": [
                {"name": "SAML", "type": "UserFlow"},
                {"name": "OIDC", "type": "UserFlow"},
                {
                    "name": "SSO Timeout",
                    "type": "FailurePath",
                    "is_failure_path": True,
                    "is_external_dependency": True,
                    "is_critical": True,
                    "criticality": "high",
                },
                {
                    "name": "Identity Provider Failure",
                    "type": "FailurePath",
                    "is_failure_path": True,
                    "is_external_dependency": True,
                },
            ],
        },
        {
            "name": "Self Registration",
            "type": "AlternateFlow",
            "description": "New user registration entry from sign-in",
            "children": [
                {"name": "Email Verification", "type": "Validation"},
                {"name": "Profile Creation", "type": "UserFlow"},
            ],
        },
    ],
}

AUTH_REQUIREMENTS = """
# Authentication Requirements — Enterprise Authentication Portal

## Sign In
- Users must authenticate before accessing protected application resources.
- Unauthenticated users cannot access protected pages such as Dashboard.
- Supported methods: Email + Password, Google OAuth, Microsoft Enterprise SSO, Self Registration.
- MFA is required for privileged roles when using Email + Password.
- Account locks after repeated failed login attempts (5 consecutive invalid passwords).
- Forgot Password must send a time-limited reset link (15 minutes).

## Google OAuth
- OAuth consent must be explicit.
- OAuth callback state must be validated to prevent CSRF.
- Provider failures must show recoverable error messaging without creating sessions.
- Session Creation occurs only after successful callback token exchange.

## Microsoft Enterprise SSO
- SAML and OIDC are both supported.
- SSO timeout must produce an actionable error (never an infinite loading state).
- Identity Provider Failure must not leak internal errors.
- Session fixation protections are mandatory after IdP assertion.

## Security
- Session cookies must be Secure, HttpOnly, SameSite=Lax or Strict.
- Rate limiting applies to password and MFA attempts.
"""

# Intentionally leave Microsoft Enterprise SSO / SSO Timeout uncovered so the
# coverage loop can demonstrate Initial → Gaps → Targeted → Final.
EXISTING_TESTS = [
    {
        "test_case_id": "TC-001",
        "title": "Successful email login",
        "graph_path": ["Sign In", "Email + Password", "Valid Credentials"],
        "priority": "high",
        "category": "functional",
        "steps": ["Open Sign In", "Enter valid email/password", "Submit"],
        "expected_result": "Authenticated session is created and Dashboard is reachable.",
    },
    {
        "test_case_id": "TC-002",
        "title": "Invalid password",
        "graph_path": ["Sign In", "Email + Password", "Invalid Password"],
        "priority": "high",
        "category": "negative",
        "steps": ["Open Sign In", "Enter valid email with wrong password", "Submit"],
        "expected_result": "Login is rejected with a clear error; no session is created.",
    },
    {
        "test_case_id": "TC-003",
        "title": "Successful Google OAuth login",
        "graph_path": ["Sign In", "Google OAuth", "Consent", "Callback", "Session Creation"],
        "priority": "high",
        "category": "functional",
        "steps": ["Choose Google OAuth", "Approve consent", "Complete callback"],
        "expected_result": "Session is created only after successful callback token exchange.",
    },
]

HISTORICAL_BUGS = [
    {
        "bug_id": "BUG-007",
        "title": "OAuth callback accepted invalid state",
        "severity": "high",
        "affected_components": ["Google OAuth", "Callback"],
        "graph_path": ["Sign In", "Google OAuth", "Callback"],
    },
    {
        "bug_id": "BUG-012",
        "title": "Locked users accessed Dashboard directly",
        "severity": "critical",
        "affected_components": ["Account Lockout", "Dashboard"],
        "graph_path": ["Sign In", "Email + Password", "Account Lockout"],
    },
    {
        "bug_id": "BUG-019",
        "title": "SSO timeout caused an infinite loading state",
        "severity": "high",
        "affected_components": ["Microsoft Enterprise SSO", "SSO Timeout"],
        "graph_path": ["Sign In", "Microsoft Enterprise SSO", "SSO Timeout"],
    },
]

DEMO_QUERY = (
    "Analyze the Sign In flow. Generate comprehensive tests focused on security, "
    "negative scenarios, historical bugs, and uncovered branches. Then identify "
    "coverage gaps and generate targeted tests for the highest-risk gaps."
)

SEED_TEST_IDS = {tc["test_case_id"] for tc in EXISTING_TESTS}
SEED_BUG_IDS = {bug["bug_id"] for bug in HISTORICAL_BUGS}


def _flow_fingerprint() -> str:
    payload = json.dumps(SIGNIN_FLOW, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{DEMO_FLOW_VERSION}:{payload}".encode("utf-8")).hexdigest()


def _find_demo_project(store: Any) -> dict[str, Any] | None:
    for name in (DEMO_PROJECT_NAME, "Auth Platform Demo"):
        found = next((p for p in store.list_projects() if p.get("name") == name), None)
        if found:
            return found
    return None


def seed_signin_demo(*, force: bool = False) -> dict[str, Any]:
    """Deterministic, repeatable, idempotent demo seed.

    Re-running without force:
    - Reuses the demo project
    - Skips graph rewrite when the flow fingerprint is unchanged
    - Upserts fixed-ID tests/bugs (no uncontrolled duplicates)
    - Document ingest remains content-hash idempotent
    """
    store = get_graph_store()
    fingerprint = _flow_fingerprint()
    reused_project = False
    graph_rewritten = False

    existing = _find_demo_project(store)
    if existing and not force:
        project_id = existing["id"]
        reused_project = True
        # Normalize legacy demo name
        if existing.get("name") != DEMO_PROJECT_NAME:
            existing["name"] = DEMO_PROJECT_NAME
            existing["description"] = (
                "Hackathon demo: Enterprise Authentication Portal centered on Sign In."
            )
            store.projects[project_id] = existing
    else:
        if existing and force:
            project_id = existing["id"]
            reused_project = True
            existing["name"] = DEMO_PROJECT_NAME
            store.projects[project_id] = existing
        else:
            project = store.create_project(
                name=DEMO_PROJECT_NAME,
                description=(
                    "Hackathon demo: Enterprise Authentication Portal centered on Sign In."
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
            NestedFlowImport.model_validate(SIGNIN_FLOW),
        )
        graph_rewritten = True
        meta["demo_flow_fingerprint"] = fingerprint
        meta["demo_flow_version"] = DEMO_FLOW_VERSION
        project["metadata"] = meta
        project["name"] = DEMO_PROJECT_NAME
        store.projects[project_id] = project
    else:
        graph = store.get_project_graph(project_id)

    # Documents + vectors (content-hash idempotent)
    doc = get_document_ingester().ingest_text(
        project_id,
        "authentication_requirements.md",
        AUTH_REQUIREMENTS,
        content_type="text/markdown",
    )
    chunks = [c for c in get_document_ingester().get_chunks(project_id) if c.document_id == doc.id]
    indexed = get_vector_store().upsert_chunks(chunks)

    # Upsert seed tests/bugs by stable IDs — never invent extra seed copies
    for tc in EXISTING_TESTS:
        payload = {**tc, "project_id": project_id, "source": "demo_seed"}
        store.upsert_test_case(project_id, payload)
    for bug in HISTORICAL_BUGS:
        payload = {**bug, "project_id": project_id, "source": "demo_seed"}
        store.upsert_bug(project_id, payload)

    # Restore curated demo catalog after Copilot persistence so re-Load Demo
    # keeps intentional coverage gaps (SSO Timeout / Account Lockout).
    for tc_id, tc in list(store.test_cases.items()):
        if tc.get("project_id") == project_id and tc.get("test_case_id") not in SEED_TEST_IDS:
            del store.test_cases[tc_id]
    for bug_id, bug in list(store.bugs.items()):
        if bug.get("project_id") == project_id and bug.get("bug_id") not in SEED_BUG_IDS:
            del store.bugs[bug_id]

    store.persist()

    project_tests = [
        tc
        for tc in store.test_cases.values()
        if tc.get("project_id") == project_id and tc.get("test_case_id") in SEED_TEST_IDS
    ]
    project_bugs = [
        b for b in store.bugs.values() if b.get("project_id") == project_id and b.get("bug_id") in SEED_BUG_IDS
    ]

    return {
        "project_id": project_id,
        "project_name": DEMO_PROJECT_NAME,
        "root_feature": "Sign In",
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "document_id": doc.id,
        "indexed_chunks": indexed,
        "existing_tests": len(project_tests),
        "historical_bugs": len(project_bugs),
        "demo_query": DEMO_QUERY,
        "reused_project": reused_project,
        "graph_rewritten": graph_rewritten,
        "flow_fingerprint": fingerprint,
        "high_risk_uncovered_hint": "Microsoft Enterprise SSO / SSO Timeout",
    }


if __name__ == "__main__":
    result = seed_signin_demo(force=True)
    print(result)
