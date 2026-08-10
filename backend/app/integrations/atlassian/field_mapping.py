"""Per-cloud-id Jira field mapping persistence."""

from __future__ import annotations

from app.db.mongo import get_atlassian_field_mappings_collection_sync
from app.integrations.atlassian.schemas import JiraFieldMapping


def load_mapping(cloud_id: str) -> JiraFieldMapping:
    row = get_atlassian_field_mappings_collection_sync().find_one({"cloud_id": cloud_id})
    raw = dict(row.get("mapping") or {}) if row else {}
    return JiraFieldMapping(
        cloud_id=cloud_id, **{k: v for k, v in raw.items() if k != "cloud_id"}
    )


def save_mapping(mapping: JiraFieldMapping) -> JiraFieldMapping:
    payload = mapping.model_dump(mode="json")
    get_atlassian_field_mappings_collection_sync().replace_one(
        {"cloud_id": mapping.cloud_id},
        {"_id": mapping.cloud_id, "cloud_id": mapping.cloud_id, "mapping": payload},
        upsert=True,
    )
    return mapping
