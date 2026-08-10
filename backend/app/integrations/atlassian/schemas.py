"""Pydantic models for Atlassian integration (API-safe — no token fields)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ConnectionStatus = Literal[
    "disconnected",
    "connecting",
    "connected",
    "expired",
    "revoked",
    "failed",
    "configuration_missing",
]

SyncStatus = Literal[
    "imported",
    "unchanged",
    "updated",
    "failed",
    "remote_missing",
    "permission_lost",
]

SourceType = Literal["jira_issue", "confluence_page"]


class AtlassianSite(BaseModel):
    cloud_id: str
    name: str
    url: str
    avatar_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)


class AtlassianConnectionStatus(BaseModel):
    enabled: bool
    configured: bool
    connected: bool
    status: ConnectionStatus
    selected_cloud_id: str | None = None
    selected_site_name: str | None = None
    selected_site_url: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    token_expiry: datetime | None = None
    error: str | None = None


class JiraProjectSummary(BaseModel):
    id: str
    key: str
    name: str
    project_type: str | None = None
    simplified: bool | None = None
    style: str | None = None
    avatar_url: str | None = None
    category: str | None = None
    url: str | None = None


class JiraIssueSummary(BaseModel):
    id: str
    key: str
    summary: str
    issue_type: str | None = None
    status: str | None = None
    priority: str | None = None
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    updated_at: str | None = None
    created_at: str | None = None
    parent_key: str | None = None
    url: str | None = None


class JiraIssuePreview(JiraIssueSummary):
    description_text: str = ""
    acceptance_criteria_text: str = ""
    extra_fields: dict[str, str] = Field(default_factory=dict)
    raw_fields_sample: dict[str, Any] = Field(default_factory=dict)


class ConfluenceSpaceSummary(BaseModel):
    id: str
    key: str
    name: str
    type: str | None = None
    status: str | None = None
    description: str | None = None
    icon_url: str | None = None
    web_url: str | None = None


class ConfluencePageSummary(BaseModel):
    id: str
    space_id: str | None = None
    parent_id: str | None = None
    title: str
    status: str | None = None
    author_display_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    version_number: int | None = None
    web_url: str | None = None
    has_children: bool = False


class ConfluencePagePreview(ConfluencePageSummary):
    body_text: str = ""
    labels: list[str] = Field(default_factory=list)
    breadcrumb: list[str] = Field(default_factory=list)


class JiraFieldMapping(BaseModel):
    cloud_id: str
    summary_field: str = "summary"
    description_field: str = "description"
    acceptance_criteria_fields: list[str] = Field(default_factory=list)
    business_rules_fields: list[str] = Field(default_factory=list)
    test_notes_fields: list[str] = Field(default_factory=list)
    risk_fields: list[str] = Field(default_factory=list)
    environment_fields: list[str] = Field(default_factory=list)
    labels_field: str = "labels"
    components_field: str = "components"


class JiraFieldInfo(BaseModel):
    id: str
    name: str
    custom: bool = False
    schema_type: str | None = None


class ExternalKnowledgeSource(BaseModel):
    source_id: str
    qa_project_id: str
    provider: Literal["atlassian"] = "atlassian"
    source_type: SourceType
    cloud_id: str
    container_id: str | None = None
    container_key: str | None = None
    external_id: str
    external_key: str | None = None
    title: str
    normalized_content: str = ""
    source_url: str | None = None
    version: str | None = None
    remote_created_at: str | None = None
    remote_updated_at: str | None = None
    imported_at: str | None = None
    last_synced_at: str | None = None
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sync_status: SyncStatus = "imported"
    document_id: str | None = None
    chunk_count: int = 0
    error: str | None = None


class ImportSourceItem(BaseModel):
    source_type: SourceType
    external_id: str
    external_key: str | None = None
    container_id: str | None = None
    container_key: str | None = None


class ImportOptions(BaseModel):
    include_comments: bool = False
    include_child_pages: bool = False
    replace_existing: bool = True


class AtlassianImportRequest(BaseModel):
    qa_project_id: str
    sources: list[ImportSourceItem]
    options: ImportOptions = Field(default_factory=ImportOptions)


class ImportFailure(BaseModel):
    external_id: str
    source_type: SourceType | None = None
    error: str
    code: str | None = None


class AtlassianImportReport(BaseModel):
    requested: int
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[ImportFailure] = Field(default_factory=list)
    sources: list[ExternalKnowledgeSource] = Field(default_factory=list)


class SelectSiteBody(BaseModel):
    cloud_id: str


class JiraIssueSearchBody(BaseModel):
    project_key: str | None = None
    project_id: str | None = None
    text: str | None = None
    issue_types: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    jql: str | None = None
    max_results: int = 50
    next_page_token: str | None = None


class SyncSelectedBody(BaseModel):
    qa_project_id: str
    source_ids: list[str] = Field(default_factory=list)
