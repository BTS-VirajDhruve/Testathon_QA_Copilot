"""Typed Atlassian integration errors (safe for API responses)."""

from __future__ import annotations


class AtlassianIntegrationError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


ATLASSIAN_NOT_CONFIGURED = "ATLASSIAN_NOT_CONFIGURED"
ATLASSIAN_NOT_CONNECTED = "ATLASSIAN_NOT_CONNECTED"
OAUTH_STATE_INVALID = "OAUTH_STATE_INVALID"
OAUTH_CONSENT_DENIED = "OAUTH_CONSENT_DENIED"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
TOKEN_REFRESH_FAILED = "TOKEN_REFRESH_FAILED"
SITE_NOT_SELECTED = "SITE_NOT_SELECTED"
SITE_NOT_ACCESSIBLE = "SITE_NOT_ACCESSIBLE"
JIRA_PERMISSION_DENIED = "JIRA_PERMISSION_DENIED"
CONFLUENCE_PERMISSION_DENIED = "CONFLUENCE_PERMISSION_DENIED"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
RATE_LIMITED = "RATE_LIMITED"
JQL_INVALID = "JQL_INVALID"
FIELD_MAPPING_INVALID = "FIELD_MAPPING_INVALID"
CONTENT_CONVERSION_FAILED = "CONTENT_CONVERSION_FAILED"
IMPORT_LIMIT_EXCEEDED = "IMPORT_LIMIT_EXCEEDED"
VECTOR_INGESTION_FAILED = "VECTOR_INGESTION_FAILED"
SYNC_FAILED = "SYNC_FAILED"
PROJECT_MISMATCH = "PROJECT_MISMATCH"
INTEGRATION_DISABLED = "INTEGRATION_DISABLED"
