"""Coverage gap analysis, deterministic prioritization, and before/after snapshots.

Reuses CoverageEngine outputs + fused graph/bug/requirement context.
Does not ask the LLM to sort gaps.
"""

from __future__ import annotations

from app.agents.dedup import dedupe_strings
from app.agents.evidence import (
    build_evidence_catalog,
    evidence_for_path_bugs_and_requirements,
    legacy_source_strings,
)
from app.models.enums import GapType, Priority, RiskLevel
from app.models.schemas import (
    CoverageGap,
    CoverageGapResult,
    CoverageSnapshot,
    EvidenceReference,
    FusedContext,
    TestCase,
    new_id,
)

# Deterministic priority ranks (lower = more important)
_PRIORITY_RANK = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}

_RISK_RANK = {
    RiskLevel.CRITICAL: 0,
    RiskLevel.HIGH: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.LOW: 3,
}

# Gap-type preference within the same priority/risk band
_TYPE_RANK = {
    GapType.GRAPH_PATH: 0,
    GapType.BUG: 1,
    GapType.REQUIREMENT: 2,
    GapType.FAILURE: 3,
    GapType.NEGATIVE: 4,
    GapType.RISK: 5,
    GapType.ALTERNATE: 6,
    GapType.BRANCH: 7,
}

# Priorities that qualify for automatic targeted regeneration
REGENERATION_PRIORITIES = {Priority.CRITICAL, Priority.HIGH}


def _as_priority(value: Priority | str) -> Priority:
    if isinstance(value, Priority):
        return value
    try:
        return Priority(str(value).lower())
    except ValueError:
        return Priority.MEDIUM


def _as_risk(value: RiskLevel | str) -> RiskLevel:
    if isinstance(value, RiskLevel):
        return value
    try:
        return RiskLevel(str(value).lower())
    except ValueError:
        return RiskLevel.MEDIUM


def _as_gap_type(value: GapType | str) -> GapType:
    if isinstance(value, GapType):
        return value
    try:
        return GapType(str(value).lower())
    except ValueError:
        return GapType.BRANCH


def _path_covered(path: list[str], test_cases: list[TestCase]) -> bool:
    if not path:
        return False
    key = " → ".join(path).lower()
    tokens = {p.lower() for p in path}
    for tc in test_cases:
        tc_path = tc.graph_path or []
        if " → ".join(tc_path).lower() == key:
            return True
        tc_tokens = {str(p).lower() for p in tc_path}
        # Leaf / branch token present in a test path or title
        leaf = path[-1].lower()
        title = (tc.title or "").lower()
        if leaf in tc_tokens or leaf in title:
            return True
        if len(tokens) >= 2 and tokens.issubset(tc_tokens | {w for w in title.split()}):
            return True
    return False


def _find_path_for_name(name: str, fused: FusedContext, root: str) -> list[str]:
    name_l = name.lower()
    for path in fused.flow_paths:
        if any(str(p).lower() == name_l for p in path):
            return list(path)
        if any(name_l in str(p).lower() for p in path):
            return list(path)
    for item in fused.graph_context:
        path = item.get("path") or []
        if any(str(p).lower() == name_l for p in path):
            return list(path)
    return [root, name] if root else [name]


def _gap_evidence(
    path: list[str],
    fused: FusedContext,
    *,
    gap_title: str,
    relevance: str,
) -> list[EvidenceReference]:
    catalog = build_evidence_catalog(fused)
    evidence = [
        EvidenceReference(
            source_type="coverage_gap",
            source_id=None,
            source_title=gap_title,
            relevance=relevance,
        )
    ]
    evidence.extend(evidence_for_path_bugs_and_requirements(path, fused, catalog)[:6])
    return evidence


def build_coverage_gaps(
    *,
    coverage: CoverageGapResult | None,
    fused: FusedContext,
    test_cases: list[TestCase],
) -> list[CoverageGap]:
    """Derive structured gaps from CoverageEngine + uncovered graph paths + bugs."""
    gaps: list[CoverageGap] = []
    root = (
        (coverage.root_feature if coverage else None)
        or fused.feature_context.get("name")
        or "Feature"
    )
    seen: set[str] = set()

    def _add(gap: CoverageGap) -> None:
        key = f"{_as_gap_type(gap.gap_type).value}|{normalize_key(gap.title)}|{'→'.join(gap.graph_path).lower()}"
        if key in seen:
            return
        seen.add(key)
        gaps.append(gap)

    # 1) Uncovered leaf graph paths
    for path in fused.flow_paths:
        if _path_covered(path, test_cases):
            continue
        joined = " → ".join(path)
        is_failure = any(
            k in joined.lower()
            for k in ("fail", "invalid", "lockout", "timeout", "error")
        )
        is_external = any(
            k in joined.lower()
            for k in ("oauth", "sso", "saml", "oidc", "provider", "google")
        )
        is_alt = any(
            k in joined.lower() for k in ("forgot", "reset", "recovery", "alternate")
        )
        if is_failure:
            gtype, priority, risk = GapType.FAILURE, Priority.HIGH, RiskLevel.HIGH
        elif is_external:
            gtype, priority, risk = GapType.GRAPH_PATH, Priority.HIGH, RiskLevel.HIGH
        elif is_alt:
            gtype, priority, risk = GapType.ALTERNATE, Priority.MEDIUM, RiskLevel.MEDIUM
        else:
            gtype, priority, risk = (
                GapType.GRAPH_PATH,
                Priority.MEDIUM,
                RiskLevel.MEDIUM,
            )
        title = f"Uncovered graph path: {joined}"
        evidence = _gap_evidence(
            path, fused, gap_title=title, relevance="Uncovered discovered leaf path"
        )
        _add(
            CoverageGap(
                gap_id=new_id("GAP"),
                gap_type=gtype,
                title=title,
                description=f"No generated test covers the discovered path {joined}.",
                priority=priority,
                risk=risk,
                graph_path=list(path),
                source_references=legacy_source_strings(evidence),
                evidence=evidence,
                reason="Graph path discovery found this leaf path without matching test coverage.",
            )
        )

    if not coverage:
        return prioritize_gaps(gaps)

    # 2) Uncovered critical / high-risk branches
    critical_branch_names = {
        g.split(":", 1)[-1].strip().lower()
        for g in coverage.critical_gaps
        if g.lower().startswith("uncovered branch")
    }
    for branch in coverage.uncovered_branches:
        path = _find_path_for_name(branch, fused, root)
        branch_l = branch.lower()
        is_critical = (
            branch_l in critical_branch_names
            or "sso" in branch_l
            or "oauth" in branch_l
        )
        priority = Priority.HIGH if is_critical else Priority.MEDIUM
        risk = RiskLevel.HIGH if is_critical else RiskLevel.MEDIUM
        title = f"Uncovered branch: {branch}"
        evidence = _gap_evidence(
            path, fused, gap_title=title, relevance="Coverage engine uncovered branch"
        )
        _add(
            CoverageGap(
                gap_id=new_id("GAP"),
                gap_type=GapType.BRANCH,
                title=title,
                description=f"Direct branch '{branch}' under {root} has no matching test path/title tokens.",
                priority=priority,
                risk=risk,
                graph_path=path,
                source_references=legacy_source_strings(evidence),
                evidence=evidence,
                reason="CoverageEngine marked this branch as uncovered.",
            )
        )

    # 3) Failure / negative scenarios
    for name in coverage.uncovered_failure_paths:
        path = _find_path_for_name(name, fused, root)
        title = f"Uncovered failure path: {name}"
        evidence = _gap_evidence(
            path, fused, gap_title=title, relevance="Uncovered failure/negative path"
        )
        _add(
            CoverageGap(
                gap_id=new_id("GAP"),
                gap_type=GapType.FAILURE,
                title=title,
                description=f"Failure path '{name}' lacks explicit negative/failure test coverage.",
                priority=Priority.HIGH,
                risk=RiskLevel.HIGH,
                graph_path=path,
                source_references=legacy_source_strings(evidence),
                evidence=evidence,
                reason="Failure-path node is uncovered by existing/generated tests.",
            )
        )

    # 4) External dependency / risk gaps
    for name in coverage.uncovered_dependencies:
        path = _find_path_for_name(name, fused, root)
        title = f"Uncovered external dependency: {name}"
        evidence = _gap_evidence(
            path,
            fused,
            gap_title=title,
            relevance="Uncovered external dependency boundary",
        )
        _add(
            CoverageGap(
                gap_id=new_id("GAP"),
                gap_type=GapType.RISK,
                title=title,
                description=f"External dependency '{name}' is uncovered — high integration risk.",
                priority=Priority.HIGH,
                risk=RiskLevel.HIGH,
                graph_path=path,
                source_references=legacy_source_strings(evidence),
                evidence=evidence,
                reason="External dependency node lacks test path coverage.",
            )
        )

    # 5) Historical bugs without regression coverage
    for bug in fused.historical_risks:
        bug_path = list(bug.get("graph_path") or [])
        bug_title = str(bug.get("title") or bug.get("bug_id") or "Historical bug")
        bug_id = str(bug.get("bug_id") or "")
        covered_by_bug = False
        for tc in test_cases:
            blob = " ".join(
                [
                    tc.title or "",
                    tc.reasoning or "",
                    " ".join(tc.source_references or []),
                    " ".join(e.source_id or "" for e in (tc.evidence or [])),
                    " ".join(e.source_title or "" for e in (tc.evidence or [])),
                ]
            ).lower()
            if bug_id and bug_id.lower() in blob:
                covered_by_bug = True
                break
            if bug_title.lower() in blob:
                covered_by_bug = True
                break
            if bug_path and _path_covered(bug_path, [tc]):
                # Path covered alone is not enough — need regression intent signal
                if "regression" in (tc.category or "").lower() or "bug" in blob:
                    covered_by_bug = True
                    break
        if covered_by_bug:
            continue
        path = bug_path or ([root] if root else [])
        severity = _as_risk(bug.get("severity") or "high")
        priority = (
            Priority.CRITICAL
            if severity in (RiskLevel.CRITICAL, RiskLevel.HIGH)
            else Priority.MEDIUM
        )
        title = f"Missing bug regression: {bug_title}"
        evidence = [
            EvidenceReference(
                source_type="coverage_gap",
                source_id=None,
                source_title=title,
                relevance="Historical bug lacks a regression test in the generated set",
            ),
            EvidenceReference(
                source_type="historical_bug",
                source_id=bug.get("bug_id"),
                source_title=bug_title,
                relevance="Historical defect pattern requiring regression coverage",
            ),
        ]
        evidence.extend(
            evidence_for_path_bugs_and_requirements(
                path, fused, build_evidence_catalog(fused)
            )[:4]
        )
        _add(
            CoverageGap(
                gap_id=new_id("GAP"),
                gap_type=GapType.BUG,
                title=title,
                description=f"Historical bug '{bug_title}' has no corresponding regression test.",
                priority=priority,
                risk=severity,
                graph_path=path,
                source_references=legacy_source_strings(evidence),
                evidence=evidence,
                reason="Historical bug pattern present in fused context without matching regression coverage.",
            )
        )

    # 6) Requirements with no corresponding test (soft signal from semantic hits)
    for hit in fused.semantic_context[:8]:
        req_id = str(hit.get("id") or hit.get("document_id") or "")
        content = str(hit.get("content") or "")
        meta = hit.get("metadata") or {}
        req_title = str(
            meta.get("title")
            or hit.get("source_reference")
            or (content[:80] + ("…" if len(content) > 80 else ""))
            or req_id
            or "Requirement"
        )
        if not content and not req_id:
            continue
        covered = False
        for tc in test_cases:
            blob = " ".join(
                [
                    tc.title or "",
                    " ".join(tc.source_references or []),
                    " ".join(e.source_id or "" for e in (tc.evidence or [])),
                    " ".join(e.source_title or "" for e in (tc.evidence or [])),
                ]
            ).lower()
            if req_id and req_id.lower() in blob:
                covered = True
                break
            # Require a stronger signal than loose word overlap for requirements
            if req_title.lower()[:40] and req_title.lower()[:40] in blob:
                covered = True
                break
        if covered:
            continue
        # Only elevate to high when requirement text signals must/critical/shall
        urgent = any(
            k in content.lower() for k in ("must ", "critical", "shall ", "required")
        )
        path = [root] if root else []
        title = f"Requirement without test: {req_title}"
        evidence = [
            EvidenceReference(
                source_type="coverage_gap",
                source_id=None,
                source_title=title,
                relevance="Requirement chunk not cited by any generated test",
            ),
            EvidenceReference(
                source_type="requirement",
                source_id=req_id or None,
                source_title=req_title,
                relevance="Retrieved requirement lacking corresponding test evidence",
            ),
        ]
        _add(
            CoverageGap(
                gap_id=new_id("GAP"),
                gap_type=GapType.REQUIREMENT,
                title=title,
                description=f"Requirement evidence '{req_title}' is not linked to a generated test.",
                priority=Priority.HIGH if urgent else Priority.LOW,
                risk=RiskLevel.HIGH if urgent else RiskLevel.LOW,
                graph_path=path,
                source_references=legacy_source_strings(evidence),
                evidence=evidence,
                reason="Semantic requirement hit is not referenced by generated test evidence.",
            )
        )

    return prioritize_gaps(gaps)


def normalize_key(text: str) -> str:
    return " ".join((text or "").lower().split())


def prioritize_gaps(gaps: list[CoverageGap]) -> list[CoverageGap]:
    """Deterministic sort — never delegated to the LLM."""

    def sort_key(g: CoverageGap) -> tuple[int, int, int, str]:
        return (
            _PRIORITY_RANK.get(_as_priority(g.priority), 9),
            _RISK_RANK.get(_as_risk(g.risk), 9),
            _TYPE_RANK.get(_as_gap_type(g.gap_type), 9),
            normalize_key(g.title),
        )

    return sorted(gaps, key=sort_key)


def select_gaps_for_regeneration(
    gaps: list[CoverageGap],
    *,
    max_gaps: int = 4,
) -> list[CoverageGap]:
    """Select only critical/high priority gaps for targeted regeneration."""
    selected: list[CoverageGap] = []
    for gap in prioritize_gaps(gaps):
        if _as_priority(gap.priority) not in REGENERATION_PRIORITIES:
            continue
        gap.selected_for_regeneration = True
        selected.append(gap)
        if len(selected) >= max_gaps:
            break
    return selected


def compute_path_coverage(
    flow_paths: list[list[str]],
    test_cases: list[TestCase],
) -> tuple[int, int, float]:
    total = len(flow_paths)
    if total == 0:
        return 0, 0, 100.0
    covered = sum(1 for path in flow_paths if _path_covered(path, test_cases))
    pct = round((covered / total) * 100, 1)
    return total, covered, pct


def build_coverage_snapshot(
    *,
    coverage: CoverageGapResult | None,
    fused: FusedContext,
    test_cases: list[TestCase],
    gaps: list[CoverageGap] | None = None,
) -> CoverageSnapshot:
    """Build explainable before/after coverage snapshot."""
    structured = (
        gaps
        if gaps is not None
        else build_coverage_gaps(coverage=coverage, fused=fused, test_cases=test_cases)
    )
    total, covered, path_pct = compute_path_coverage(fused.flow_paths, test_cases)
    overall = coverage.overall_coverage if coverage else path_pct
    branch = coverage.branch_coverage if coverage else path_pct
    notes = list(coverage.calculation_notes) if coverage else []
    notes.append(
        f"Path coverage = covered_leaf_paths / discovered_leaf_paths = {covered}/{total} → {path_pct}%"
    )
    notes.append(
        "Path matching uses exact path strings, leaf tokens in graph_path/title, and token subsets — deterministic."
    )
    return CoverageSnapshot(
        total_paths=total,
        covered_paths=covered,
        coverage_percentage=path_pct,
        overall_coverage=overall,
        branch_coverage=branch,
        gaps=structured,
        critical_gaps=dedupe_strings(
            list(coverage.critical_gaps)
            if coverage
            else [
                g.title
                for g in structured
                if _as_priority(g.priority) in REGENERATION_PRIORITIES
            ][:12]
        ),
        uncovered_branches=dedupe_strings(
            list(coverage.uncovered_branches) if coverage else []
        ),
        calculation_notes=notes,
    )


def gaps_still_open(
    gaps: list[CoverageGap],
    test_cases: list[TestCase],
) -> list[CoverageGap]:
    """Return gaps that remain unresolved after targeted tests were added."""
    unresolved: list[CoverageGap] = []
    closed_ids = {tc.closes_gap_id for tc in test_cases if tc.closes_gap_id}

    for gap in gaps:
        gtype = _as_gap_type(gap.gap_type)

        # Explicitly closed by a targeted test that still covers the path (when present)
        if gap.gap_id in closed_ids:
            if gap.graph_path and not _path_covered(gap.graph_path, test_cases):
                unresolved.append(gap)
            continue

        if gtype in (GapType.BUG, GapType.REQUIREMENT):
            needle = normalize_key(gap.title.split(":", 1)[-1])
            found = False
            for tc in test_cases:
                blob = normalize_key(
                    " ".join(
                        [
                            tc.title or "",
                            tc.reasoning or "",
                            tc.closes_gap_title or "",
                            " ".join(e.source_title or "" for e in (tc.evidence or [])),
                            " ".join(e.source_id or "" for e in (tc.evidence or [])),
                        ]
                    )
                )
                if needle and needle[:40] in blob:
                    found = True
                    break
            if not found:
                unresolved.append(gap)
            continue

        if gap.graph_path:
            if not _path_covered(gap.graph_path, test_cases):
                unresolved.append(gap)
            continue

        # No path and not closed — still open
        unresolved.append(gap)

    return prioritize_gaps(unresolved)
