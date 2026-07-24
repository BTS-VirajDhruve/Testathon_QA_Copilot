"""Seed realistic Sign In demo data for the hackathon workflow."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Allow `python -m seed.demo_seed` from backend/
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.graph.ingestion import get_flow_ingester
from app.graph.store import get_graph_store
from app.models.enums import RiskLevel
from app.models.schemas import NestedFlowImport
from app.rag.document_ingestion import get_document_ingester
from app.rag.vector_store import get_vector_store


SIGNIN_FLOW = {
    "root": "Sign In",
    "description": "User authentication entry point for the platform.",
    "branches": [
        {
            "name": "Email + Password",
            "type": "AuthenticationMethod",
            "description": "Classic credential authentication",
            "children": [
                {"name": "Valid Credentials", "type": "UserFlow"},
                {"name": "Invalid Password", "type": "FailurePath", "is_failure_path": True},
                {"name": "Forgot Password", "type": "AlternateFlow"},
                {"name": "MFA", "type": "SubFeature", "is_critical": True},
                {
                    "name": "Account Lockout",
                    "type": "FailurePath",
                    "is_failure_path": True,
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
                {"name": "Callback", "type": "UserFlow"},
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
            "name": "Enterprise SSO",
            "type": "AuthenticationMethod",
            "description": "Enterprise identity federation",
            "children": [
                {"name": "SAML", "type": "UserFlow"},
                {"name": "OIDC", "type": "UserFlow"},
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
# Authentication Requirements

## Sign In
- Users must authenticate before accessing protected application resources.
- Supported methods: Email + Password, Google OAuth, Enterprise SSO, Self Registration.
- MFA is required for privileged roles when using Email + Password.
- Account lockout triggers after 5 consecutive invalid password attempts.
- Forgot Password must send a time-limited reset link (15 minutes).

## Google OAuth
- OAuth consent must be explicit.
- Callback must validate state parameter to prevent CSRF.
- Provider failures must show recoverable error messaging without creating sessions.
- Session Creation occurs only after successful callback token exchange.

## Enterprise SSO
- SAML and OIDC are both supported.
- Identity Provider Failure must not leak internal errors.
- Session fixation protections are mandatory after IdP assertion.

## Security
- Session cookies must be Secure, HttpOnly, SameSite=Lax or Strict.
- Rate limiting applies to password and MFA attempts.
"""

EXISTING_TESTS = [
    {
        "test_case_id": "TC-001",
        "title": "Successful email/password login",
        "graph_path": ["Sign In", "Email + Password", "Valid Credentials"],
        "priority": "high",
        "category": "functional",
    },
    {
        "test_case_id": "TC-002",
        "title": "Invalid password rejection",
        "graph_path": ["Sign In", "Email + Password", "Invalid Password"],
        "priority": "high",
        "category": "functional",
    },
    {
        "test_case_id": "TC-003",
        "title": "Successful Google OAuth login",
        "graph_path": ["Sign In", "Google OAuth", "Consent", "Callback", "Session Creation"],
        "priority": "high",
        "category": "functional",
    },
    {
        "test_case_id": "TC-004",
        "title": "Google OAuth provider failure handling",
        "graph_path": ["Sign In", "Google OAuth", "Provider Failure"],
        "priority": "high",
        "category": "negative",
    },
    {
        "test_case_id": "TC-005",
        "title": "Self-registration email verification",
        "graph_path": ["Sign In", "Self Registration", "Email Verification"],
        "priority": "medium",
        "category": "functional",
    },
]

HISTORICAL_BUGS = [
    {
        "bug_id": "BUG-007",
        "title": "OAuth callback failure leaves orphan session cookie",
        "severity": "high",
        "affected_components": ["Google OAuth", "Callback", "Session Creation"],
        "graph_path": ["Sign In", "Google OAuth", "Callback", "Session Creation"],
    },
    {
        "bug_id": "BUG-012",
        "title": "Session creation failure after successful IdP assertion",
        "severity": "high",
        "affected_components": ["Enterprise SSO", "Session Creation"],
        "graph_path": ["Sign In", "Enterprise SSO", "OIDC"],
    },
    {
        "bug_id": "BUG-019",
        "title": "Repeated MFA attempts bypass rate limit",
        "severity": "critical",
        "affected_components": ["MFA", "Email + Password"],
        "graph_path": ["Sign In", "Email + Password", "MFA"],
    },
    {
        "bug_id": "BUG-021",
        "title": "Account lockout recovery email not sent",
        "severity": "medium",
        "affected_components": ["Account Lockout", "Forgot Password"],
        "graph_path": ["Sign In", "Email + Password", "Account Lockout"],
    },
]


def seed_signin_demo(*, force: bool = False) -> dict[str, Any]:
    store = get_graph_store()

    # Reuse existing demo project if present
    existing = next(
        (p for p in store.list_projects() if p.get("name") == "Auth Platform Demo"),
        None,
    )
    if existing and not force:
        project_id = existing["id"]
    else:
        project = store.create_project(
            name="Auth Platform Demo",
            description="Hackathon demo project centered on Sign In system flow.",
            root_feature=None,
        )
        project_id = project["id"]

    ingester = get_flow_ingester()
    graph = ingester.from_nested_import(
        project_id,
        NestedFlowImport.model_validate(SIGNIN_FLOW),
    )

    # Documents + vectors
    doc = get_document_ingester().ingest_text(
        project_id,
        "authentication_requirements.md",
        AUTH_REQUIREMENTS,
        content_type="text/markdown",
    )
    chunks = [c for c in get_document_ingester().get_chunks(project_id) if c.document_id == doc.id]
    indexed = get_vector_store().upsert_chunks(chunks)

    # Existing tests & bugs
    for tc in EXISTING_TESTS:
        payload = {**tc, "project_id": project_id}
        store.test_cases[tc["test_case_id"]] = payload
    for bug in HISTORICAL_BUGS:
        payload = {**bug, "project_id": project_id}
        store.bugs[bug["bug_id"]] = payload
    store.persist()

    return {
        "project_id": project_id,
        "project_name": "Auth Platform Demo",
        "root_feature": "Sign In",
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "document_id": doc.id,
        "indexed_chunks": indexed,
        "existing_tests": len(EXISTING_TESTS),
        "historical_bugs": len(HISTORICAL_BUGS),
        "demo_query": "Generate comprehensive QA coverage for Sign In.",
    }


if __name__ == "__main__":
    result = seed_signin_demo(force=True)
    print(result)