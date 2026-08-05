"""Safe JQL builder — never concatenate raw user strings unchecked."""

from __future__ import annotations

import re

from app.integrations.atlassian.errors import JQL_INVALID, AtlassianIntegrationError

_SAFE_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
_SAFE_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def escape_jql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def quote(value: str) -> str:
    return f'"{escape_jql_string(value)}"'


def build_issue_jql(
    *,
    project_key: str | None = None,
    text: str | None = None,
    issue_types: list[str] | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    labels: list[str] | None = None,
    advanced_jql: str | None = None,
) -> str:
    if advanced_jql and advanced_jql.strip():
        jql = advanced_jql.strip()
        if re.search(r";|--|/\*", jql):
            raise AtlassianIntegrationError(JQL_INVALID, "Advanced JQL contains disallowed tokens")
        return jql

    clauses: list[str] = []
    if project_key:
        if not _SAFE_KEY.match(project_key):
            raise AtlassianIntegrationError(JQL_INVALID, "Invalid Jira project key")
        clauses.append(f"project = {quote(project_key)}")

    if text and text.strip():
        clauses.append(f"text ~ {quote(text.strip())}")

    def _in_clause(field: str, values: list[str]) -> None:
        cleaned = [v.strip() for v in values if v and v.strip()]
        if not cleaned:
            return
        for v in cleaned:
            if not _SAFE_IDENT.match(v) and not re.match(r"^[\w \-./]+$", v):
                raise AtlassianIntegrationError(JQL_INVALID, f"Invalid value for {field}")
        joined = ", ".join(quote(v) for v in cleaned)
        clauses.append(f"{field} in ({joined})")

    _in_clause("issuetype", issue_types or [])
    _in_clause("status", statuses or [])
    _in_clause("priority", priorities or [])
    _in_clause("labels", labels or [])

    if not clauses:
        raise AtlassianIntegrationError(
            JQL_INVALID,
            "Provide a project key or search filters",
        )
    return " AND ".join(clauses) + " ORDER BY updated DESC"
