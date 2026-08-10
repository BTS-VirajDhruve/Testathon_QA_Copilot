"""Evidence catalog and sanitization for explainable test generation."""

from __future__ import annotations

from typing import Any

from app.models.schemas import EvidenceReference, FusedContext


def build_evidence_catalog(fused: FusedContext) -> list[EvidenceReference]:
    """Collect real source identities available in fused retrieval context."""
    catalog: list[EvidenceReference] = []

    feature = fused.feature_context or {}
    if feature.get("id") or feature.get("name"):
        catalog.append(
            EvidenceReference(
                source_type="graph",
                source_id=feature.get("id"),
                source_title=feature.get("name") or "Feature",
                relevance="Target feature from user-provided system flow graph",
            )
        )

    for item in fused.graph_context:
        if item.get("path"):
            labels = item.get("path") or []
            ids = item.get("node_ids") or []
            catalog.append(
                EvidenceReference(
                    source_type="graph",
                    source_id=item.get("path_id") or ("→".join(ids) if ids else None),
                    source_title=" → ".join(labels) if labels else None,
                    relevance=(
                        "Failure path in system flow graph"
                        if item.get("is_failure_path")
                        else "Discovered user-flow path"
                    ),
                )
            )
            for nid, label in zip(ids, labels, strict=False):
                catalog.append(
                    EvidenceReference(
                        source_type="graph",
                        source_id=nid,
                        source_title=label,
                        relevance="Graph node on discovered path",
                    )
                )
        elif item.get("entity") or item.get("node_id"):
            catalog.append(
                EvidenceReference(
                    source_type="graph",
                    source_id=item.get("node_id"),
                    source_title=item.get("entity"),
                    relevance="Related graph entity",
                )
            )

    for hit in fused.semantic_context:
        meta = hit.get("metadata") or {}
        source_type = hit.get("source_type") or meta.get("source_type") or "requirement"
        if (
            source_type in {"jira_issue", "confluence_page"}
            or meta.get("provider") == "atlassian"
        ):
            source_type = meta.get("source_type") or source_type
            catalog.append(
                EvidenceReference(
                    source_type=source_type
                    if source_type in {"jira_issue", "confluence_page"}
                    else "requirement",
                    source_id=hit.get("id")
                    or meta.get("external_id")
                    or meta.get("document_id"),
                    source_title=meta.get("title")
                    or hit.get("source_reference")
                    or meta.get("external_key")
                    or meta.get("filename"),
                    relevance=(
                        f"Atlassian {source_type.replace('_', ' ')} via Vector RAG"
                        if meta.get("provider") == "atlassian"
                        else "Vector RAG requirement/document chunk"
                    ),
                )
            )
        else:
            catalog.append(
                EvidenceReference(
                    source_type="requirement",
                    source_id=hit.get("id") or meta.get("document_id"),
                    source_title=hit.get("source_reference")
                    or meta.get("filename")
                    or meta.get("source_reference"),
                    relevance="Vector RAG requirement/document chunk",
                )
            )

    for tc in fused.existing_coverage:
        catalog.append(
            EvidenceReference(
                source_type="existing_test",
                source_id=tc.get("test_case_id"),
                source_title=tc.get("title"),
                relevance="Existing project test case",
            )
        )

    for bug in fused.historical_risks:
        catalog.append(
            EvidenceReference(
                source_type="historical_bug",
                source_id=bug.get("bug_id"),
                source_title=bug.get("title"),
                relevance="Historical defect pattern",
            )
        )
        catalog.append(
            EvidenceReference(
                source_type="risk",
                source_id=bug.get("bug_id"),
                source_title=bug.get("title"),
                relevance=f"Risk signal from historical bug ({bug.get('severity') or 'unknown'})",
            )
        )

    return _dedupe(catalog)


def sanitize_evidence(
    claimed: list[Any],
    catalog: list[EvidenceReference],
) -> list[EvidenceReference]:
    """Keep only evidence that matches real catalog identities. Never invent IDs."""
    allowed_ids = {(e.source_type, e.source_id) for e in catalog if e.source_id}
    allowed_titles = {
        (e.source_type, (e.source_title or "").strip().lower())
        for e in catalog
        if e.source_title
    }

    out: list[EvidenceReference] = []
    for raw in claimed or []:
        if isinstance(raw, EvidenceReference):
            item = raw
        elif isinstance(raw, dict):
            try:
                item = EvidenceReference.model_validate(raw)
            except Exception:  # noqa: BLE001
                continue
        elif isinstance(raw, str):
            # Legacy string reference — keep only if it matches a known title/id
            matched = next(
                (
                    e
                    for e in catalog
                    if e.source_id == raw
                    or (e.source_title or "").lower() == raw.lower()
                    or raw.lower() in (e.source_title or "").lower()
                ),
                None,
            )
            if matched:
                out.append(matched)
            continue
        else:
            continue

        if item.source_id:
            if (item.source_type, item.source_id) in allowed_ids:
                out.append(item)
            continue
        # No ID: allow only if title matches a known catalog title for that type
        title_key = (item.source_type, (item.source_title or "").strip().lower())
        if item.source_title and title_key in allowed_titles:
            # Attach catalog ID when available
            match = next(
                (
                    e
                    for e in catalog
                    if e.source_type == item.source_type
                    and (e.source_title or "").strip().lower()
                    == (item.source_title or "").strip().lower()
                ),
                None,
            )
            if match:
                out.append(
                    EvidenceReference(
                        source_type=item.source_type,
                        source_id=match.source_id,
                        source_title=item.source_title or match.source_title,
                        relevance=item.relevance or match.relevance,
                    )
                )
    return _dedupe(out)


def evidence_for_graph_path(
    path_labels: list[str],
    catalog: list[EvidenceReference],
    *,
    relevance: str | None = None,
) -> list[EvidenceReference]:
    """Attach catalog graph evidence that matches the path labels / path title."""
    if not path_labels:
        return []
    path_title = " → ".join(path_labels)
    out: list[EvidenceReference] = []
    for e in catalog:
        if e.source_type != "graph":
            continue
        if e.source_title == path_title:
            out.append(
                EvidenceReference(
                    source_type=e.source_type,
                    source_id=e.source_id,
                    source_title=e.source_title,
                    relevance=relevance or e.relevance,
                )
            )
        elif e.source_title in path_labels:
            out.append(
                EvidenceReference(
                    source_type=e.source_type,
                    source_id=e.source_id,
                    source_title=e.source_title,
                    relevance=relevance or "Node on claimed graph path",
                )
            )
    return _dedupe(out)


def evidence_for_path_bugs_and_requirements(
    path_labels: list[str],
    fused: FusedContext,
    catalog: list[EvidenceReference],
) -> list[EvidenceReference]:
    """Deterministic evidence attachment from fused context for a graph path."""
    out = evidence_for_graph_path(path_labels, catalog)
    path_l = " ".join(path_labels).lower()

    for bug in fused.historical_risks:
        blob = (
            f"{bug.get('title', '')} {' '.join(bug.get('affected_components') or [])} "
            f"{' '.join(bug.get('graph_path') or [])}"
        ).lower()
        if any(p.lower() in blob for p in path_labels):
            out.append(
                EvidenceReference(
                    source_type="historical_bug",
                    source_id=bug.get("bug_id"),
                    source_title=bug.get("title"),
                    relevance="Historical bug intersects this graph path",
                )
            )

    for hit in fused.semantic_context[:2]:
        meta = hit.get("metadata") or {}
        out.append(
            EvidenceReference(
                source_type="requirement",
                source_id=hit.get("id") or meta.get("document_id"),
                source_title=hit.get("source_reference") or meta.get("filename"),
                relevance="Retrieved requirement/document context for this feature",
            )
        )

    for tc in fused.existing_coverage:
        title = (tc.get("title") or "").lower()
        gp = " ".join(str(x) for x in (tc.get("graph_path") or [])).lower()
        if path_l and (
            path_l in gp
            or any(p.lower() in title or p.lower() in gp for p in path_labels)
        ):
            out.append(
                EvidenceReference(
                    source_type="existing_test",
                    source_id=tc.get("test_case_id"),
                    source_title=tc.get("title"),
                    relevance="Related existing coverage",
                )
            )

    return _dedupe(out)


def legacy_source_strings(evidence: list[EvidenceReference]) -> list[str]:
    """Back-compat string list for source_references."""
    out: list[str] = []
    for e in evidence:
        if e.source_title and e.source_id:
            out.append(f"{e.source_type}:{e.source_id}:{e.source_title}")
        elif e.source_title:
            out.append(f"{e.source_type}:{e.source_title}")
        elif e.source_id:
            out.append(f"{e.source_type}:{e.source_id}")
        else:
            out.append(e.source_type)
    # Preserve uniqueness while keeping order
    seen: set[str] = set()
    unique: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _dedupe(items: list[EvidenceReference]) -> list[EvidenceReference]:
    seen: set[tuple[str | None, str | None, str | None]] = set()
    out: list[EvidenceReference] = []
    for e in items:
        key = (e.source_type, e.source_id, e.source_title)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out
