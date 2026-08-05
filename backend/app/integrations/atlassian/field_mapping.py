"""Per-cloud-id Jira field mapping persistence."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.integrations.atlassian.schemas import JiraFieldMapping


def _path() -> Path:
    return get_settings().atlassian_data_dir / "field_mappings.json"


def load_mapping(cloud_id: str) -> JiraFieldMapping:
    data = {}
    path = _path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    raw = data.get(cloud_id) or {}
    return JiraFieldMapping(cloud_id=cloud_id, **{k: v for k, v in raw.items() if k != "cloud_id"})


def save_mapping(mapping: JiraFieldMapping) -> JiraFieldMapping:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    data[mapping.cloud_id] = mapping.model_dump(mode="json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
    return mapping
