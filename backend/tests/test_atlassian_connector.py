"""Mocked Atlassian connector tests — no live credentials required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.integrations.atlassian import oauth, token_store
from app.integrations.atlassian.adf import adf_to_text
from app.integrations.atlassian.crypto import decrypt_secret, encrypt_secret
from app.integrations.atlassian.errors import (
    OAUTH_STATE_INVALID,
    AtlassianIntegrationError,
)
from app.integrations.atlassian.html_sanitize import html_to_text
from app.integrations.atlassian.import_service import import_sources, remove_source
from app.integrations.atlassian.jql import build_issue_jql, escape_jql_string
from app.integrations.atlassian.schemas import AtlassianImportRequest, ImportSourceItem


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_TOKEN_ENCRYPTION_KEY", "test-local-key-for-atlassian")
    from app.core.config import get_settings

    get_settings.cache_clear()
    token = "secret-access-token-value"
    enc = encrypt_secret(token)
    assert enc != token
    assert decrypt_secret(enc) == token
    get_settings.cache_clear()


def test_jql_escaping_and_builder():
    assert '\\"' in escape_jql_string('say "hi"')
    jql = build_issue_jql(project_key="MOM", text='login "flow"', issue_types=["Bug"])
    assert 'project = "MOM"' in jql
    assert "ORDER BY updated DESC" in jql
    with pytest.raises(AtlassianIntegrationError):
        build_issue_jql(project_key="bad key!")


def test_adf_and_html_conversion():
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Acceptance"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "User sees a status message"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Given session"}],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    text = adf_to_text(adf)
    assert "Acceptance" in text
    assert "status message" in text
    assert "Given session" in text

    html = '<p>Hello</p><script>alert(1)</script><a href="https://example.com">Link</a>'
    out = html_to_text(html)
    assert "Hello" in out
    assert "script" not in out.lower() or "alert" not in out
    assert "example.com" in out


def test_oauth_state_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLASSIAN_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(AtlassianIntegrationError) as exc:
        oauth.exchange_code("code", "bad-state")
    assert exc.value.code == OAUTH_STATE_INVALID
    get_settings.cache_clear()


def test_connection_status_configuration_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLASSIAN_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_ID", "")
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    st = oauth.connection_status()
    assert st.configured is False
    assert st.status == "configuration_missing"
    assert "access_token" not in st.model_dump()
    get_settings.cache_clear()


def test_tokens_never_in_status_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLASSIAN_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ENCRYPTION_KEY", "unit-test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    token_store.set_tokens(
        access_token="ACCESS_TOKEN_SECRET",
        refresh_token="REFRESH_TOKEN_SECRET",
        expires_in=3600,
        scopes=["read:jira-work"],
    )
    st = oauth.connection_status().model_dump(mode="json")
    blob = str(st)
    assert "ACCESS_TOKEN_SECRET" not in blob
    assert "REFRESH_TOKEN_SECRET" not in blob
    assert "encrypted" not in blob.lower()
    oauth.disconnect()
    assert token_store.load_connection() is None
    get_settings.cache_clear()


def test_import_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GRAPH_STORE_PATH", str(tmp_path / "graph.json"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    from app.core.config import get_settings
    from app.graph.store import get_graph_store

    get_settings.cache_clear()
    # reset singleton stores if present
    import app.graph.store as store_mod
    import app.rag.vector_store as vs_mod

    store_mod._store = None  # type: ignore[attr-defined]
    vs_mod._vector_store = None

    store = get_graph_store()
    project = store.create_project("Atl Test", root_feature="Feature")
    pid = project["id"]

    class FakePreview:
        id = "10001"
        key = "MOM-1"
        summary = "Create journey"
        issue_type = "Story"
        status = "To Do"
        priority = "High"
        labels = []
        components = []
        updated_at = "2026-01-01T00:00:00.000+0000"
        created_at = "2026-01-01T00:00:00.000+0000"
        parent_key = None
        url = "https://example.atlassian.net/browse/MOM-1"
        description_text = "User creates a journey and sees a success status message."
        acceptance_criteria_text = "Status message is displayed."
        extra_fields = {}

    fake_jira = MagicMock()
    fake_jira.normalize_issue.return_value = (
        "# MOM-1: Create journey\nStatus message is displayed.",
        FakePreview(),
    )

    with (
        patch(
            "app.integrations.atlassian.import_service.require_selected_cloud_id",
            return_value="cloud-1",
        ),
        patch(
            "app.integrations.atlassian.import_service.get_jira_adapter",
            return_value=fake_jira,
        ),
        patch(
            "app.integrations.atlassian.import_service.get_confluence_adapter",
            return_value=MagicMock(),
        ),
    ):
        req = AtlassianImportRequest(
            qa_project_id=pid,
            sources=[
                ImportSourceItem(
                    source_type="jira_issue",
                    external_id="10001",
                    external_key="MOM-1",
                )
            ],
        )
        r1 = import_sources(req)
        assert r1.imported == 1
        r2 = import_sources(req)
        assert r2.unchanged == 1
        assert r2.imported == 0
        source_id = r1.sources[0].source_id
        assert remove_source(source_id, pid) is True

    get_settings.cache_clear()


def test_project_isolation_for_imports(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GRAPH_STORE_PATH", str(tmp_path / "graph2.json"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma2"))
    import app.graph.store as store_mod
    import app.rag.vector_store as vs_mod
    from app.core.config import get_settings
    from app.graph.store import get_graph_store
    from app.integrations.atlassian import source_store

    get_settings.cache_clear()
    store_mod._store = None  # type: ignore[attr-defined]
    vs_mod._vector_store = None
    store = get_graph_store()
    a = store.create_project("A", root_feature="F")
    b = store.create_project("B", root_feature="F")

    class FakePreview:
        id = "200"
        key = "AAA-1"
        summary = "Iso"
        issue_type = "Bug"
        status = "Open"
        priority = "Low"
        labels = []
        components = []
        updated_at = "2026-01-02T00:00:00.000+0000"
        created_at = "2026-01-02T00:00:00.000+0000"
        parent_key = None
        url = None
        description_text = "Error message returned"
        acceptance_criteria_text = ""
        extra_fields = {}

    fake_jira = MagicMock()
    fake_jira.normalize_issue.return_value = (
        "# AAA-1\nError message returned",
        FakePreview(),
    )

    with (
        patch(
            "app.integrations.atlassian.import_service.require_selected_cloud_id",
            return_value="cloud-1",
        ),
        patch(
            "app.integrations.atlassian.import_service.get_jira_adapter",
            return_value=fake_jira,
        ),
        patch(
            "app.integrations.atlassian.import_service.get_confluence_adapter",
            return_value=MagicMock(),
        ),
    ):
        import_sources(
            AtlassianImportRequest(
                qa_project_id=a["id"],
                sources=[
                    ImportSourceItem(
                        source_type="jira_issue",
                        external_id="200",
                        external_key="AAA-1",
                    )
                ],
            )
        )
    assert len(source_store.list_sources(a["id"])) == 1
    assert len(source_store.list_sources(b["id"])) == 0
    get_settings.cache_clear()
