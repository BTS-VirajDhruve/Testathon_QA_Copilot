"""Deterministic coverage-obligation universe builder."""

from __future__ import annotations

import re

from app.models.enums import (
    NodeType,
    ObligationStatus,
    ObligationType,
    Priority,
    RiskLevel,
)
from app.models.schemas import (
    CategoryCoverage,
    CoverageObligation,
    EvidenceReference,
    FusedContext,
    SystemFlowGraph,
    new_id,
)

_PERF_HINT = re.compile(
    r"\b(performance|latency|throughput|sla|response\s*time|load\s*test)\b", re.I
)
_A11Y_HINT = re.compile(r"\b(accessib|aria|wcag|keyboard|screen\s*reader)\b", re.I)
_SECURITY_HINT = re.compile(
    r"\b(auth|permission|role|security|token|session|xss|csrf|inject|encrypt|lockout|sso|oauth)\b",
    re.I,
)


def _prio_from_risk(risk: RiskLevel | str) -> Priority:
    value = risk.value if isinstance(risk, RiskLevel) else str(risk).lower()
    if value in ("critical",):
        return Priority.CRITICAL
    if value in ("high",):
        return Priority.HIGH
    if value in ("low",):
        return Priority.LOW
    return Priority.MEDIUM


def _query_flags(query: str) -> dict[str, bool]:
    q = query or ""
    return {
        "security": bool(_SECURITY_HINT.search(q)) or "security" in q.lower(),
        "accessibility": bool(_A11Y_HINT.search(q)) or "accessibility" in q.lower(),
        "performance": bool(_PERF_HINT.search(q)) or "performance" in q.lower(),
        "exhaustive_negative": "negative" in q.lower() or "exhaustive" in q.lower(),
    }


def build_coverage_obligations(
    *,
    project_id: str,
    fused: FusedContext,
    graph: SystemFlowGraph | None = None,
    query: str = "",
    root_feature: str | None = None,
) -> list[CoverageObligation]:
    """Build a finite modeled coverage universe from graph + fused context.

    Only emits categories supported by project context or explicit user request.
    Does not invent unsupported non-functional thresholds.
    """
    flags = _query_flags(query)
    obligations: list[CoverageObligation] = []
    feature_id = None
    feature_name = (
        root_feature or (fused.feature_context or {}).get("name") or "Feature"
    )

    seen: set[str] = set()

    def _add(obl: CoverageObligation) -> None:
        key = f"{obl.obligation_type.value}|{'|'.join(obl.graph_path)}|{obl.title.lower()}"
        if key in seen:
            return
        seen.add(key)
        obligations.append(obl)

    # Graph paths from fused context
    for item in fused.graph_context or []:
        path = list(item.get("path") or [])
        if not path:
            continue
        is_failure = bool(item.get("is_failure_path"))
        external = bool(item.get("includes_external_dependency"))
        otype = (
            ObligationType.FAILURE_PATH if is_failure else ObligationType.POSITIVE_FLOW
        )
        if any("alternate" in str(p).lower() for p in path):
            otype = ObligationType.ALTERNATE_FLOW
        _add(
            CoverageObligation(
                obligation_id=new_id("OBL"),
                project_id=project_id,
                feature_id=feature_id,
                obligation_type=otype,
                title=f"{otype.value.replace('_', ' ').title()}: {' → '.join(path)}",
                description=f"Cover modeled path {' → '.join(path)}",
                priority=Priority.HIGH if is_failure or external else Priority.MEDIUM,
                mandatory=True,
                graph_path=path,
                evidence_basis="system_flow_graph",
                evidence_references=[
                    EvidenceReference(
                        source_type="graph",
                        source_id="system_flow",
                        excerpt=" → ".join(path),
                        relevance="graph_path",
                    )
                ],
            )
        )
        if is_failure:
            _add(
                CoverageObligation(
                    obligation_id=new_id("OBL"),
                    project_id=project_id,
                    obligation_type=ObligationType.RECOVERY,
                    title=f"Recovery after failure: {' → '.join(path)}",
                    description="Verify recovery/retry behavior after the failure path.",
                    priority=Priority.HIGH,
                    mandatory=True,
                    graph_path=path,
                    evidence_basis="failure_path",
                )
            )
        if external:
            _add(
                CoverageObligation(
                    obligation_id=new_id("OBL"),
                    project_id=project_id,
                    obligation_type=ObligationType.EXTERNAL_DEPENDENCY,
                    title=f"External dependency failure: {' → '.join(path)}",
                    description="Verify behavior when the external dependency fails or times out.",
                    priority=Priority.HIGH,
                    mandatory=True,
                    graph_path=path,
                    evidence_basis="external_dependency",
                )
            )

    # Graph nodes (validations, rules, roles, states)
    if graph:
        for node in graph.nodes:
            if node.project_id and node.project_id != project_id:
                continue
            ntype = node.type.value if hasattr(node.type, "value") else str(node.type)
            path = [feature_name, node.name]
            if ntype in (NodeType.VALIDATION.value, "Validation"):
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.VALIDATION,
                        title=f"Validation: {node.name}",
                        description=node.description or f"Validate {node.name}",
                        priority=Priority.HIGH if node.is_critical else Priority.MEDIUM,
                        mandatory=True,
                        graph_path=path,
                        graph_node_ids=[node.id],
                        evidence_basis="validation_node",
                    )
                )
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.NEGATIVE_FLOW,
                        title=f"Negative validation: {node.name}",
                        description=f"Reject invalid input for {node.name}",
                        priority=Priority.HIGH,
                        mandatory=True,
                        graph_path=path,
                        graph_node_ids=[node.id],
                        evidence_basis="validation_node",
                    )
                )
            elif ntype in (NodeType.BUSINESS_RULE.value, "BusinessRule"):
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.BUSINESS_RULE,
                        title=f"Business rule: {node.name}",
                        description=node.description or node.name,
                        priority=Priority.HIGH if node.is_critical else Priority.MEDIUM,
                        mandatory=True,
                        graph_path=path,
                        graph_node_ids=[node.id],
                        evidence_basis="business_rule",
                    )
                )
            elif ntype in (
                NodeType.ROLE.value,
                NodeType.PERMISSION.value,
                "Role",
                "Permission",
            ):
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.ROLE_PERMISSION,
                        title=f"Role/permission: {node.name}",
                        description=node.description or f"Authorize {node.name}",
                        priority=Priority.CRITICAL
                        if node.is_critical
                        else Priority.HIGH,
                        mandatory=True,
                        graph_path=path,
                        graph_node_ids=[node.id],
                        role=node.name,
                        evidence_basis="role_permission",
                    )
                )
            elif ntype in (NodeType.STATE.value, "State"):
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.STATE_TRANSITION,
                        title=f"State: {node.name}",
                        description=node.description or f"Cover state {node.name}",
                        priority=Priority.MEDIUM,
                        mandatory=True,
                        graph_path=path,
                        graph_node_ids=[node.id],
                        state_to=node.name,
                        evidence_basis="state_node",
                    )
                )
            elif (
                ntype
                in (
                    NodeType.FAILURE_PATH.value,
                    "FailurePath",
                )
                or node.is_failure_path
            ):
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.FAILURE_PATH,
                        title=f"Failure path: {node.name}",
                        description=node.description or node.name,
                        priority=Priority.HIGH,
                        mandatory=True,
                        graph_path=path,
                        graph_node_ids=[node.id],
                        evidence_basis="failure_node",
                    )
                )

    # Requirements
    for req in fused.semantic_context or []:
        rid = str(req.get("id") or req.get("source_reference") or "")
        text = str(req.get("text") or req.get("title") or req.get("content") or "")
        if not text:
            continue
        _add(
            CoverageObligation(
                project_id=project_id,
                obligation_type=ObligationType.REQUIREMENT,
                title=f"Requirement: {text[:100]}",
                description=text[:500],
                priority=Priority.HIGH,
                mandatory=True,
                requirement_ids=[rid] if rid else [],
                evidence_basis="requirement",
                evidence_references=[
                    EvidenceReference(
                        source_type="requirement",
                        source_id=rid or "requirement",
                        excerpt=text[:200],
                        relevance="requirement",
                    )
                ],
            )
        )
        if _SECURITY_HINT.search(text) or flags["security"]:
            _add(
                CoverageObligation(
                    project_id=project_id,
                    obligation_type=ObligationType.SECURITY,
                    title=f"Security: {text[:80]}",
                    description=text[:400],
                    priority=Priority.CRITICAL,
                    mandatory=True,
                    requirement_ids=[rid] if rid else [],
                    evidence_basis="security_requirement",
                )
            )
        if _PERF_HINT.search(text) or flags["performance"]:
            has_target = bool(
                re.search(
                    r"\b(\d+\s*ms|\d+\s*s|sla|p95|throughput\s*[><=])\b", text, re.I
                )
            )
            if has_target:
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.PERFORMANCE,
                        title=f"Performance: {text[:80]}",
                        description=text[:400],
                        priority=Priority.MEDIUM,
                        mandatory=False,
                        requirement_ids=[rid] if rid else [],
                        evidence_basis="performance_requirement",
                    )
                )
            else:
                _add(
                    CoverageObligation(
                        project_id=project_id,
                        obligation_type=ObligationType.INSUFFICIENT_EVIDENCE,
                        title=f"Performance target missing: {text[:60]}",
                        description="Performance mentioned without measurable threshold.",
                        priority=Priority.LOW,
                        mandatory=False,
                        status=ObligationStatus.INSUFFICIENT_EVIDENCE,
                        unsupported_reason="missing_performance_target",
                        requirement_ids=[rid] if rid else [],
                        evidence_basis="insufficient_evidence",
                    )
                )
        if _A11Y_HINT.search(text) or flags["accessibility"]:
            _add(
                CoverageObligation(
                    project_id=project_id,
                    obligation_type=ObligationType.ACCESSIBILITY,
                    title=f"Accessibility: {text[:80]}",
                    description=text[:400],
                    priority=Priority.MEDIUM,
                    mandatory=flags["accessibility"],
                    requirement_ids=[rid] if rid else [],
                    evidence_basis="accessibility_requirement",
                )
            )

    # Historical bugs → regression obligations
    for bug in fused.historical_risks or []:
        if str(bug.get("project_id") or project_id) not in ("", project_id):
            continue
        bid = str(bug.get("bug_id") or bug.get("id") or "")
        title = str(bug.get("title") or bid or "Historical bug")
        path = list(bug.get("graph_path") or [feature_name])
        _add(
            CoverageObligation(
                project_id=project_id,
                obligation_type=ObligationType.HISTORICAL_BUG_REGRESSION,
                title=f"Bug regression: {title}",
                description=str(bug.get("description") or title),
                priority=_prio_from_risk(
                    bug.get("severity") or bug.get("risk") or "high"
                ),
                mandatory=True,
                graph_path=path,
                bug_ids=[bid] if bid else [],
                evidence_basis="historical_bug",
            )
        )

    # Boundary obligation when validations exist or exhaustive negatives requested
    if flags["exhaustive_negative"] or any(
        o.obligation_type == ObligationType.VALIDATION for o in obligations
    ):
        _add(
            CoverageObligation(
                project_id=project_id,
                obligation_type=ObligationType.BOUNDARY,
                title=f"Boundary values for {feature_name}",
                description="Cover min/max/edge input boundaries for validations.",
                priority=Priority.MEDIUM,
                mandatory=True,
                graph_path=[feature_name],
                evidence_basis="validation_context",
            )
        )

    # Context-aware security if auth-like graph nodes exist
    if flags["security"] or any(
        o.obligation_type in (ObligationType.ROLE_PERMISSION, ObligationType.SECURITY)
        for o in obligations
    ):
        if not any(o.obligation_type == ObligationType.SECURITY for o in obligations):
            _add(
                CoverageObligation(
                    project_id=project_id,
                    obligation_type=ObligationType.SECURITY,
                    title=f"Security controls for {feature_name}",
                    description="Verify authz/authn controls on the feature.",
                    priority=Priority.CRITICAL,
                    mandatory=True,
                    graph_path=[feature_name],
                    evidence_basis="security_context",
                )
            )

    return _prioritize(obligations)


def _prioritize(items: list[CoverageObligation]) -> list[CoverageObligation]:
    type_rank = {
        ObligationType.SECURITY: 0,
        ObligationType.ROLE_PERMISSION: 1,
        ObligationType.HISTORICAL_BUG_REGRESSION: 2,
        ObligationType.DATA_INTEGRITY: 3,
        ObligationType.FAILURE_PATH: 4,
        ObligationType.RECOVERY: 5,
        ObligationType.REQUIREMENT: 6,
        ObligationType.EXTERNAL_DEPENDENCY: 7,
        ObligationType.NEGATIVE_FLOW: 8,
        ObligationType.VALIDATION: 9,
        ObligationType.STATE_TRANSITION: 10,
        ObligationType.BOUNDARY: 11,
        ObligationType.CONCURRENCY: 12,
        ObligationType.POSITIVE_FLOW: 13,
        ObligationType.ALTERNATE_FLOW: 14,
        ObligationType.PERFORMANCE: 20,
        ObligationType.INSUFFICIENT_EVIDENCE: 99,
    }
    prio_rank = {
        Priority.CRITICAL: 0,
        Priority.HIGH: 1,
        Priority.MEDIUM: 2,
        Priority.LOW: 3,
    }

    def key(o: CoverageObligation) -> tuple[int, int, str]:
        return (
            prio_rank.get(
                o.priority if isinstance(o.priority, Priority) else Priority.MEDIUM, 2
            ),
            type_rank.get(o.obligation_type, 50),
            o.title.lower(),
        )

    return sorted(items, key=key)


def category_coverage_summary(
    obligations: list[CoverageObligation],
) -> list[CategoryCoverage]:
    buckets: dict[str, list[CoverageObligation]] = {}
    for o in obligations:
        if o.status == ObligationStatus.INSUFFICIENT_EVIDENCE:
            cat = "insufficient_evidence"
        else:
            cat = o.obligation_type.value
        buckets.setdefault(cat, []).append(o)

    out: list[CategoryCoverage] = []
    for cat, items in sorted(buckets.items()):
        covered = [o for o in items if o.status == ObligationStatus.COVERED]
        missing = [
            o.obligation_id
            for o in items
            if o.status not in (ObligationStatus.COVERED, ObligationStatus.RETIRED)
        ]
        applicability = (
            "insufficient_evidence" if cat == "insufficient_evidence" else "applicable"
        )
        total = len(items)
        cov = len(covered)
        out.append(
            CategoryCoverage(
                category=cat,
                required_obligations=total,
                covered_obligations=cov,
                coverage_percentage=round(100.0 * cov / total, 2) if total else 0.0,
                missing_obligations=missing,
                evidence_basis=items[0].evidence_basis if items else "",
                applicability=applicability,
            )
        )
    return out
