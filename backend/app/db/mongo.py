"""MongoDB connection lifecycle and collection access helpers."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DESCENDING, ReturnDocument
from pymongo.mongo_client import MongoClient

from app.core.config import get_settings
from app.core.logging import get_logger

try:
    import mongomock
except ImportError:  # pragma: no cover - runtime safety
    mongomock = None

logger = get_logger(__name__)


@dataclass
class MongoHealth:
    status: str = "not_initialized"
    connected: bool = False
    error: str | None = None


_client: AsyncIOMotorClient | Any | None = None
_database: Any | None = None
_sync_client: MongoClient[Any] | Any | None = None
_sync_database: Any | None = None
_health = MongoHealth()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _build_client() -> AsyncIOMotorClient | Any:
    settings = get_settings()
    uri = settings.mongo_uri.strip()
    if uri.startswith("mongomock://"):
        if mongomock is None:
            raise RuntimeError("mongomock is required for mongomock:// Mongo URI")
        return mongomock.MongoClient()
    return AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=settings.mongo_connect_timeout_ms,
    )


def _build_sync_client() -> MongoClient[Any] | Any:
    settings = get_settings()
    uri = settings.mongo_uri.strip()
    if uri.startswith("mongomock://"):
        if mongomock is None:
            raise RuntimeError("mongomock is required for mongomock:// Mongo URI")
        return mongomock.MongoClient()
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=settings.mongo_connect_timeout_ms,
    )


async def _ensure_indexes(db: Any) -> None:
    users = db["users"]
    refresh_tokens = db["refresh_tokens"]
    await _maybe_await(users.create_index("email", unique=True, name="ux_users_email"))
    await _maybe_await(
        users.create_index(
            [("forgotPasswordToken", 1), ("forgotPasswordTokenExpiresAt", 1)],
            name="ix_users_forgot_password_token_lookup",
        )
    )
    await _maybe_await(
        users.create_index(
            [("inviteToken", 1), ("inviteTokenExpiresAt", 1)],
            name="ix_users_invite_token_lookup",
        )
    )
    await _maybe_await(
        refresh_tokens.create_index(
            "tokenHash",
            unique=True,
            name="ux_refresh_tokens_token_hash",
        )
    )
    await _maybe_await(
        refresh_tokens.create_index("userId", name="ix_refresh_tokens_user_id")
    )
    await _maybe_await(
        refresh_tokens.create_index(
            "expiresAt",
            expireAfterSeconds=0,
            name="ix_refresh_tokens_expires_at",
        )
    )
    # Graph/domain JSON migration collections
    qa_projects = db["qa_projects"]
    qa_nodes = db["qa_nodes"]
    qa_edges = db["qa_edges"]
    qa_documents = db["qa_documents"]
    qa_document_chunks = db["qa_document_chunks"]
    qa_test_cases = db["qa_test_cases"]
    qa_bugs = db["qa_bugs"]
    qa_analyses = db["qa_analyses"]
    qa_test_reviews = db["qa_test_reviews"]
    qa_test_review_overrides = db["qa_test_review_overrides"]
    qa_graph_versions = db["qa_graph_versions"]
    qa_external_knowledge_sources = db["qa_external_knowledge_sources"]
    atlassian_connections = db["atlassian_connections"]
    atlassian_oauth_states = db["atlassian_oauth_states"]
    atlassian_field_mappings = db["atlassian_field_mappings"]

    await _maybe_await(
        qa_projects.create_index("project_id", unique=True, name="ux_qa_projects_project_id")
    )
    await _maybe_await(qa_nodes.create_index("node_id", unique=True, name="ux_qa_nodes_node_id"))
    await _maybe_await(qa_nodes.create_index("project_id", name="ix_qa_nodes_project_id"))
    await _maybe_await(
        qa_nodes.create_index([("project_id", 1), ("type", 1)], name="ix_qa_nodes_project_type")
    )
    await _maybe_await(
        qa_nodes.create_index([("project_id", 1), ("name_lc", 1)], name="ix_qa_nodes_project_name_lc")
    )
    await _maybe_await(qa_edges.create_index("edge_id", unique=True, name="ux_qa_edges_edge_id"))
    await _maybe_await(
        qa_edges.create_index(
            [("project_id", 1), ("source_node_id", 1)],
            name="ix_qa_edges_project_source",
        )
    )
    await _maybe_await(
        qa_edges.create_index(
            [("project_id", 1), ("target_node_id", 1)],
            name="ix_qa_edges_project_target",
        )
    )
    await _maybe_await(
        qa_edges.create_index(
            [("project_id", 1), ("relationship", 1)],
            name="ix_qa_edges_project_relationship",
        )
    )
    await _maybe_await(
        qa_documents.create_index("document_id", unique=True, name="ux_qa_documents_document_id")
    )
    await _maybe_await(
        qa_documents.create_index(
            [("project_id", 1), ("filename", 1), ("content_hash", 1)],
            name="ix_qa_documents_project_file_hash",
        )
    )
    await _maybe_await(
        qa_document_chunks.create_index("chunk_id", unique=True, name="ux_qa_document_chunks_chunk_id")
    )
    await _maybe_await(
        qa_document_chunks.create_index(
            [("project_id", 1), ("document_id", 1)],
            name="ix_qa_document_chunks_project_document",
        )
    )
    await _maybe_await(
        qa_document_chunks.create_index(
            [("project_id", 1), ("source_type", 1), ("feature", 1)],
            name="ix_qa_document_chunks_project_source_feature",
        )
    )
    await _maybe_await(
        qa_test_cases.create_index(
            [("project_id", 1), ("test_case_id", 1)],
            unique=True,
            name="ux_qa_test_cases_project_test_case",
        )
    )
    await _maybe_await(
        qa_test_cases.create_index(
            [("project_id", 1), ("generation_method", 1)],
            name="ix_qa_test_cases_project_generation",
        )
    )
    await _maybe_await(
        qa_test_cases.create_index(
            [("project_id", 1), ("updated_at", 1)],
            name="ix_qa_test_cases_project_updated_at",
        )
    )
    await _maybe_await(
        qa_bugs.create_index(
            [("project_id", 1), ("bug_id", 1)],
            unique=True,
            name="ux_qa_bugs_project_bug",
        )
    )
    await _maybe_await(
        qa_bugs.create_index(
            [("project_id", 1), ("created_at", 1)],
            name="ix_qa_bugs_project_created_at",
        )
    )
    await _maybe_await(
        qa_analyses.create_index("analysis_id", unique=True, name="ux_qa_analyses_analysis_id")
    )
    await _maybe_await(
        qa_analyses.create_index(
            [("project_id", 1), ("is_latest", 1)],
            name="ix_qa_analyses_project_latest",
        )
    )
    await _maybe_await(
        qa_analyses.create_index(
            [("project_id", 1), ("created_at", DESCENDING)],
            name="ix_qa_analyses_project_created_desc",
        )
    )
    await _maybe_await(
        qa_test_reviews.create_index(
            [("project_id", 1), ("test_case_id", 1)],
            unique=True,
            name="ux_qa_test_reviews_project_test_case",
        )
    )
    await _maybe_await(
        qa_test_reviews.create_index(
            [("project_id", 1), ("updated_at", 1)],
            name="ix_qa_test_reviews_project_updated_at",
        )
    )
    await _maybe_await(
        qa_test_review_overrides.create_index(
            [("project_id", 1), ("test_case_id", 1)],
            unique=True,
            name="ux_qa_test_review_overrides_project_test_case",
        )
    )
    await _maybe_await(
        qa_test_review_overrides.create_index(
            [("project_id", 1), ("override_timestamp", 1)],
            name="ix_qa_test_review_overrides_project_override_timestamp",
        )
    )
    await _maybe_await(
        qa_graph_versions.create_index(
            [("project_id", 1), ("version", 1)],
            unique=True,
            name="ux_qa_graph_versions_project_version",
        )
    )
    await _maybe_await(
        qa_graph_versions.create_index(
            [("project_id", 1), ("saved_at", DESCENDING)],
            name="ix_qa_graph_versions_project_saved_desc",
        )
    )
    await _maybe_await(
        qa_external_knowledge_sources.create_index(
            "source_id",
            unique=True,
            name="ux_qa_external_knowledge_sources_source_id",
        )
    )
    await _maybe_await(
        qa_external_knowledge_sources.create_index(
            [("qa_project_id", 1), ("cloud_id", 1), ("source_type", 1), ("external_id", 1)],
            unique=True,
            name="ux_qa_external_knowledge_sources_identity",
        )
    )
    await _maybe_await(
        qa_external_knowledge_sources.create_index(
            [("qa_project_id", 1), ("last_synced_at", 1)],
            name="ix_qa_external_knowledge_sources_project_synced",
        )
    )
    await _maybe_await(
        atlassian_connections.create_index("scope_key", unique=True, name="ux_atlassian_connections_scope_key")
    )
    await _maybe_await(
        atlassian_connections.create_index("updated_at", name="ix_atlassian_connections_updated_at")
    )
    await _maybe_await(
        atlassian_oauth_states.create_index("state", unique=True, name="ux_atlassian_oauth_states_state")
    )
    await _maybe_await(
        atlassian_oauth_states.create_index(
            "created_at",
            expireAfterSeconds=1800,
            name="ix_atlassian_oauth_states_created_at_ttl",
        )
    )
    await _maybe_await(
        atlassian_field_mappings.create_index("cloud_id", unique=True, name="ux_atlassian_field_mappings_cloud_id")
    )


async def init_mongo() -> None:
    """Initialize Mongo client once and pre-create required indexes."""
    global _client, _database, _health, _sync_client, _sync_database
    settings = get_settings()
    if not settings.mongo_enabled:
        _health = MongoHealth(status="disabled", connected=False, error=None)
        _client = None
        _database = None
        return
    if _client is not None and _database is not None:
        return

    try:
        logger.info("mongo_connecting", db_name=settings.mongo_db_name)
        _client = _build_client()
        _database = _client[settings.mongo_db_name]
        _sync_client = _build_sync_client()
        _sync_database = _sync_client[settings.mongo_db_name]
        if not settings.mongo_uri.strip().startswith("mongomock://"):
            await _client.admin.command("ping")
            _sync_client.admin.command("ping")
        await _ensure_indexes(_database)
        _health = MongoHealth(status="connected", connected=True, error=None)
        logger.info(
            "mongo_connected", db_name=settings.mongo_db_name, status=_health.status
        )
    except Exception as exc:  # noqa: BLE001
        _health = MongoHealth(
            status="error",
            connected=False,
            error=str(exc)[:200],
        )
        logger.warning(
            "mongo_connection_failed",
            error=_health.error,
            required=settings.mongo_required,
        )
        _client = None
        _database = None
        _sync_client = None
        _sync_database = None
        if settings.mongo_required:
            raise RuntimeError(
                "MongoDB is required but not reachable",
            ) from exc


async def close_mongo() -> None:
    """Close Mongo client and reset state."""
    global _client, _database, _health, _sync_client, _sync_database
    try:
        if _client is not None and hasattr(_client, "close"):
            await _maybe_await(_client.close())
        if _sync_client is not None and hasattr(_sync_client, "close"):
            _sync_client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mongo_close_failed", error=str(exc)[:200])
    finally:
        _client = None
        _database = None
        _sync_client = None
        _sync_database = None
        if _health.status != "disabled":
            _health = MongoHealth(status="closed", connected=False, error=None)
        logger.info("mongo_disconnected", status=_health.status)


def get_database() -> Any:
    if _database is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(init_mongo())
    if _database is None:
        raise RuntimeError("MongoDB is not initialized")
    return _database


def get_sync_database() -> Any:
    if _sync_database is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(init_mongo())
    if _sync_database is None:
        raise RuntimeError("MongoDB is not initialized")
    return _sync_database


def get_users_collection() -> Any:
    return get_database()["users"]


def get_refresh_tokens_collection() -> Any:
    return get_database()["refresh_tokens"]


def get_collection_sync(name: str) -> Any:
    return get_sync_database()[name]


def get_qa_projects_collection_sync() -> Any:
    return get_collection_sync("qa_projects")


def get_qa_nodes_collection_sync() -> Any:
    return get_collection_sync("qa_nodes")


def get_qa_edges_collection_sync() -> Any:
    return get_collection_sync("qa_edges")


def get_qa_documents_collection_sync() -> Any:
    return get_collection_sync("qa_documents")


def get_qa_document_chunks_collection_sync() -> Any:
    return get_collection_sync("qa_document_chunks")


def get_qa_test_cases_collection_sync() -> Any:
    return get_collection_sync("qa_test_cases")


def get_qa_bugs_collection_sync() -> Any:
    return get_collection_sync("qa_bugs")


def get_qa_analyses_collection_sync() -> Any:
    return get_collection_sync("qa_analyses")


def get_qa_test_reviews_collection_sync() -> Any:
    return get_collection_sync("qa_test_reviews")


def get_qa_test_review_overrides_collection_sync() -> Any:
    return get_collection_sync("qa_test_review_overrides")


def get_qa_graph_versions_collection_sync() -> Any:
    return get_collection_sync("qa_graph_versions")


def get_qa_external_knowledge_sources_collection_sync() -> Any:
    return get_collection_sync("qa_external_knowledge_sources")


def get_atlassian_connections_collection_sync() -> Any:
    return get_collection_sync("atlassian_connections")


def get_atlassian_oauth_states_collection_sync() -> Any:
    return get_collection_sync("atlassian_oauth_states")


def get_atlassian_field_mappings_collection_sync() -> Any:
    return get_collection_sync("atlassian_field_mappings")


def upsert_latest_analysis_sync(project_id: str, payload: dict[str, Any]) -> None:
    analyses = get_qa_analyses_collection_sync()
    analysis_id = str(payload.get("analysis_id") or f"latest-{project_id}")
    analyses.update_many({"project_id": project_id}, {"$set": {"is_latest": False}})
    analyses.find_one_and_update(
        {"analysis_id": analysis_id},
        {
            "$set": {
                "analysis_id": analysis_id,
                "project_id": project_id,
                "is_latest": True,
                "analysis": payload,
                "created_at": payload.get("created_at") or payload.get("updated_at"),
                "updated_at": payload.get("updated_at"),
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def mongo_health_signal() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.mongo_enabled,
        "required": settings.mongo_required,
        "status": _health.status,
        "connected": _health.connected,
        "database": settings.mongo_db_name,
        "error": _health.error,
    }
