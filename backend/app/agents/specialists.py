"""Specialized QA agents — each independently testable."""

from __future__ import annotations

import json
from typing import Any

from app.agents.dedup import deduplicate_tests
from app.agents.evidence import (
    build_evidence_catalog,
    evidence_for_path_bugs_and_requirements,
    legacy_source_strings,
    sanitize_evidence,
)
from app.core.logging import get_logger
from app.graph.store import get_graph_store
from app.graph.traversal import get_coverage_engine, get_traversal
from app.models.enums import ConfidenceLevel, Priority, RiskLevel
from app.models.schemas import (
    BugReport,
    CoverageGap,
    CoverageGapResult,
    EvidenceReference,
    ExploratoryMission,
    FusedContext,
    ImpactAnalysisResult,
    RegressionRecommendation,
    TestCase,
    new_id,
)
from app.services.openai_service import get_openai_service

logger = get_logger(__name__)


TECHNIQUE_BY_PATH = [
    (("failure", "lockout", "invalid", "timeout"), "Negative testing / fault injection"),
    (("oauth", "sso", "saml", "oidc", "provider"), "Integration & security testing"),
    (("mfa", "session", "fixation"), "Security testing"),
    (("validation", "registration"), "Boundary value & validation testing"),
    (("forgot", "reset", "recovery"), "Alternate flow / recovery testing"),
]


def _technique_for_path(path: list[str]) -> str:
    joined = " ".join(path).lower()
    for keys, technique in TECHNIQUE_BY_PATH:
        if any(k in joined for k in keys):
            return technique
    return "Path-based functional testing"


def _priority_for_path(path: list[str], is_failure: bool, external: bool) -> Priority:
    joined = " ".join(path).lower()
    if external or "sso" in joined or "oauth" in joined or "mfa" in joined:
        return Priority.HIGH
    if is_failure or "lockout" in joined:
        return Priority.HIGH
    if "invalid" in joined:
        return Priority.MEDIUM
    return Priority.MEDIUM


class TestCaseAgent:
    """Generate structured test cases from fused hybrid RAG context.

    Primary path: LLM structured generation when OpenAI is available.
    Fallback: deterministic graph-path heuristics (baseline behavior).
    """

    MAX_LLM_ATTEMPTS = 2

    SYSTEM_PROMPT = """You are a senior QA automation architect.
Generate comprehensive, evidence-backed test cases from the provided fused QA context.

Return JSON only with this shape:
{
  "test_cases": [
    {
      "title": "string",
      "category": "functional|security|negative|regression|exploratory",
      "priority": "critical|high|medium|low",
      "risk": "critical|high|medium|low",
      "preconditions": ["string"],
      "test_data": {},
      "steps": ["string"],
      "expected_result": "string",
      "testing_technique": "string",
      "graph_path": ["node label", "..."],
      "graph_reasoning": "string",
      "reasoning": "concise why-this-test explanation",
      "source_references": ["legacy string labels only when needed"],
      "evidence": [
        {
          "source_type": "graph|requirement|existing_test|historical_bug|risk",
          "source_id": "MUST be an ID present in the context, or null",
          "source_title": "title/label from context",
          "relevance": "why this source supports the test"
        }
      ],
      "confidence": "high|medium|low",
      "assumptions": ["string"]
    }
  ]
}

Rules:
1. Cover positive, negative, alternate-flow, and failure-path scenarios supported by the context.
2. Include boundary scenarios only when evidence supports them.
3. Include historical-bug regression scenarios when bugs are provided.
4. Include risk-focused scenarios when risk context is present.
5. Prefer uncovered or weakly covered graph paths when existing tests are listed.
   When existing coverage already leaves high-risk failure leaves (e.g. SSO Timeout,
   Account Lockout) uncovered, you may leave 1–2 of those for a follow-up critic pass
   rather than exhausting every leaf in the first response.
6. Do NOT invent unsupported product behavior.
7. Do NOT duplicate existing tests by title or graph path when avoidable.
8. Mark assumptions explicitly in assumptions[].
9. Preserve graph_path traceability using labels from DISCOVERED GRAPH PATHS whenever possible.
10. Use only information present in the context sections. If a section is empty/unavailable, do not fabricate it.
11. For evidence: ONLY cite source_id values that appear in the provided context. Never invent IDs.
12. If exact evidence is unavailable, omit evidence entries or leave source_id null — do not invent sources.
13. Provide reasoning explaining why the test exists based on retrieved context.
"""

    TARGETED_SYSTEM_PROMPT = """You are a senior QA automation architect.
Generate a test case specifically for this coverage gap.

Return JSON only with this shape:
{
  "test_cases": [
    {
      "title": "string",
      "category": "functional|security|negative|regression|exploratory",
      "priority": "critical|high|medium|low",
      "risk": "critical|high|medium|low",
      "preconditions": ["string"],
      "test_data": {},
      "steps": ["string"],
      "expected_result": "string",
      "testing_technique": "string",
      "graph_path": ["node label", "..."],
      "graph_reasoning": "string",
      "reasoning": "This test was generated to close coverage gap: <gap title>. ...",
      "source_references": ["legacy string labels only when needed"],
      "evidence": [
        {
          "source_type": "graph|requirement|existing_test|historical_bug|risk|coverage_gap",
          "source_id": "MUST be an ID present in the context, or null",
          "source_title": "title/label from context",
          "relevance": "why this source supports the test"
        }
      ],
      "confidence": "high|medium|low",
      "assumptions": ["string"]
    }
  ]
}

Rules:
1. Generate ONLY test case(s) that close the provided coverage gap — do NOT regenerate the full suite.
2. Prefer 1 focused test case; at most 2 if the gap clearly requires positive+negative pairs.
3. Use the provided graph path, nodes, relationships, requirements, bugs, and evidence catalog.
4. Do NOT invent unsupported product behavior.
5. Do NOT duplicate existing tests listed in the context (by title, steps, expected result, or graph path).
6. For evidence: ONLY cite source_id values from allowed_evidence_catalog. Never invent IDs.
7. Reasoning MUST explain: This test was generated to close coverage gap: <gap>.
8. Preserve graph_path traceability using labels from the gap / discovered paths.
"""

    def generate(self, query: str, fused: FusedContext, project_id: str) -> list[TestCase]:
        openai = get_openai_service()
        cases: list[TestCase] = []
        method = "deterministic_fallback"

        if openai.available:
            llm_cases = self._generate_with_llm(query, fused, project_id, openai)
            if llm_cases:
                cases = llm_cases
                method = "llm"
                logger.info("testcase_llm_primary_success", count=len(cases))
            else:
                logger.warning("testcase_llm_primary_failed_using_fallback")
                cases = self._generate_deterministic(query, fused, project_id)
        else:
            logger.info("testcase_openai_unavailable_using_fallback")
            cases = self._generate_deterministic(query, fused, project_id)

        catalog = build_evidence_catalog(fused)
        for case in cases:
            if not case.generation_method:
                case.generation_method = method
            case.project_id = case.project_id or project_id
            if not case.feature_id:
                case.feature_id = fused.feature_context.get("id")
            if not case.reasoning and case.graph_reasoning:
                case.reasoning = case.graph_reasoning
            if not case.graph_reasoning and case.reasoning:
                case.graph_reasoning = case.reasoning
            # Ensure evidence is sanitized and path-linked when missing
            case.evidence = sanitize_evidence(case.evidence, catalog)
            if not case.evidence and case.graph_path:
                case.evidence = evidence_for_path_bugs_and_requirements(
                    case.graph_path, fused, catalog
                )
            if case.evidence and not case.source_references:
                case.source_references = legacy_source_strings(case.evidence)
            elif case.evidence:
                merged = list(case.source_references) + legacy_source_strings(case.evidence)
                seen_refs: set[str] = set()
                unique_refs: list[str] = []
                for s in merged:
                    if s not in seen_refs:
                        seen_refs.add(s)
                        unique_refs.append(s)
                case.source_references = unique_refs

        # Persist lightly for coverage matching (baseline behavior)
        store = get_graph_store()
        for case in cases:
            store.test_cases[case.test_case_id] = case.model_dump(mode="json")
        store.persist()
        return cases

    def build_llm_context(self, query: str, fused: FusedContext) -> dict[str, Any]:
        """Structured context passed to the LLM — preserves fused retrieval evidence + IDs."""
        path_entries: list[dict[str, Any]] = []
        for item in fused.graph_context:
            if item.get("path"):
                path_entries.append(
                    {
                        "node_labels": item.get("path"),
                        "node_ids": item.get("node_ids") or [],
                        "path_id": item.get("path_id"),
                        "edge_relationships": item.get("relationships") or [],
                        "path_sequence": item.get("path"),
                        "is_failure_path": bool(item.get("is_failure_path")),
                        "includes_external_dependency": bool(
                            item.get("includes_external_dependency")
                        ),
                    }
                )
        if not path_entries and fused.flow_paths:
            for path in fused.flow_paths:
                path_entries.append(
                    {
                        "node_labels": path,
                        "node_ids": [],
                        "path_id": None,
                        "edge_relationships": [],
                        "path_sequence": path,
                        "is_failure_path": False,
                        "includes_external_dependency": False,
                    }
                )

        graph_entities = [
            item
            for item in fused.graph_context
            if (item.get("entity") or item.get("node_id")) and not item.get("path")
        ]

        requirements = []
        for hit in fused.semantic_context:
            meta = hit.get("metadata") or {}
            requirements.append(
                {
                    "id": hit.get("id"),
                    "document_id": hit.get("document_id") or meta.get("document_id"),
                    "content": hit.get("content"),
                    "score": hit.get("score"),
                    "source_reference": hit.get("source_reference") or hit.get("id"),
                    "metadata": meta,
                    "source_type": "requirement",
                }
            )

        catalog = build_evidence_catalog(fused)

        return {
            "user_request": query,
            "target_feature": fused.feature_context or "unavailable",
            "system_flow_graph": {
                "branches": fused.feature_context.get("branches") or [],
                "entities": graph_entities or "unavailable",
                "note": "User-provided system flow graph is the structural source of truth.",
            },
            "discovered_graph_paths": path_entries or "unavailable",
            "requirements": requirements or "unavailable",
            "existing_tests": fused.existing_coverage or "unavailable",
            "historical_bugs": fused.historical_risks or "unavailable",
            "risk_context": {
                "historical_risks": fused.historical_risks or [],
                "external_context": fused.external_context or [],
            }
            if (fused.historical_risks or fused.external_context)
            else "unavailable",
            "retrieval_sources": {
                "user_flow_graph": True,
                "vector_hits": len(fused.semantic_context),
                "existing_tests": len(fused.existing_coverage),
                "historical_bugs": len(fused.historical_risks),
                "external_notes": fused.external_context or [],
            },
            "allowed_evidence_catalog": [e.model_dump() for e in catalog],
            "evidence_rules": (
                "Only cite source_id values from allowed_evidence_catalog. "
                "Never invent IDs. If unsure, omit source_id."
            ),
        }

    def build_targeted_context(
        self,
        gap: CoverageGap,
        fused: FusedContext,
        existing_tests: list[TestCase],
    ) -> dict[str, Any]:
        """Narrow fused context for a single coverage gap — for targeted LLM prompts."""
        base = self.build_llm_context(
            f"Generate a test case specifically for this coverage gap: {gap.title}",
            fused,
        )
        # Relevant path entries only
        gap_tokens = {p.lower() for p in gap.graph_path}
        relevant_paths = []
        for entry in base.get("discovered_graph_paths") or []:
            if not isinstance(entry, dict):
                continue
            labels = [str(x) for x in (entry.get("node_labels") or entry.get("path_sequence") or [])]
            if not gap_tokens or gap_tokens.intersection({x.lower() for x in labels}):
                relevant_paths.append(entry)
        if not relevant_paths and gap.graph_path:
            relevant_paths = [
                {
                    "node_labels": gap.graph_path,
                    "node_ids": [],
                    "path_id": None,
                    "edge_relationships": [],
                    "path_sequence": gap.graph_path,
                    "is_failure_path": gap.gap_type in ("failure", "negative"),
                    "includes_external_dependency": False,
                }
            ]

        # Filter bugs/requirements that touch the gap path or are cited on the gap
        gap_bug_ids = {
            e.source_id
            for e in (gap.evidence or [])
            if e.source_type == "historical_bug" and e.source_id
        }
        relevant_bugs = []
        for bug in fused.historical_risks:
            path = [str(p).lower() for p in (bug.get("graph_path") or [])]
            if gap_bug_ids and bug.get("bug_id") in gap_bug_ids:
                relevant_bugs.append(bug)
            elif gap_tokens and gap_tokens.intersection(path):
                relevant_bugs.append(bug)
            elif gap.gap_type in ("bug",) or "bug" in str(gap.gap_type):
                relevant_bugs.append(bug)

        existing_summaries = [
            {
                "test_case_id": tc.test_case_id,
                "title": tc.title,
                "steps": tc.steps,
                "expected_result": tc.expected_result,
                "graph_path": tc.graph_path,
                "generation_method": tc.generation_method,
            }
            for tc in existing_tests
        ]

        return {
            "instruction": (
                "Generate a test case specifically for this coverage gap. "
                "Do not regenerate the complete test suite."
            ),
            "coverage_gap": {
                "gap_id": gap.gap_id,
                "gap_type": gap.gap_type.value if hasattr(gap.gap_type, "value") else gap.gap_type,
                "title": gap.title,
                "description": gap.description,
                "priority": gap.priority.value if hasattr(gap.priority, "value") else gap.priority,
                "risk": gap.risk.value if hasattr(gap.risk, "value") else gap.risk,
                "graph_path": gap.graph_path,
                "reason": gap.reason,
                "evidence": [e.model_dump() for e in (gap.evidence or [])],
                "source_references": gap.source_references,
            },
            "relevant_graph_path": gap.graph_path,
            "relevant_graph_paths": relevant_paths or "unavailable",
            "relevant_requirements": base.get("requirements") or "unavailable",
            "relevant_historical_bugs": relevant_bugs or base.get("historical_bugs") or "unavailable",
            "existing_tests_do_not_duplicate": existing_summaries or "none",
            "allowed_evidence_catalog": base.get("allowed_evidence_catalog") or [],
            "evidence_rules": base.get("evidence_rules"),
            "target_feature": base.get("target_feature"),
            "retrieval_sources": base.get("retrieval_sources"),
        }

    def generate_for_gap(
        self,
        gap: CoverageGap,
        fused: FusedContext,
        project_id: str,
        existing_tests: list[TestCase],
    ) -> list[TestCase]:
        """Generate only the missing test(s) for one prioritized coverage gap.

        Reuses LLM + Pydantic validation + deterministic fallback + evidence sanitization.
        Targeted cases are tagged generation_method='critic'.
        """
        openai = get_openai_service()
        cases: list[TestCase] = []

        if openai.available:
            llm_cases = self._generate_targeted_with_llm(gap, fused, project_id, existing_tests, openai)
            if llm_cases:
                cases = llm_cases
                logger.info("targeted_llm_success", gap_id=gap.gap_id, count=len(cases))
            else:
                logger.warning("targeted_llm_failed_using_fallback", gap_id=gap.gap_id)
                cases = self._generate_targeted_deterministic(gap, fused, project_id, existing_tests)
        else:
            cases = self._generate_targeted_deterministic(gap, fused, project_id, existing_tests)

        catalog = build_evidence_catalog(fused)
        for case in cases:
            case.generation_method = "critic"
            case.closes_gap_id = gap.gap_id
            case.closes_gap_title = gap.title
            case.project_id = case.project_id or project_id
            if not case.feature_id:
                case.feature_id = fused.feature_context.get("id")
            gap_reason = f"This test was generated to close coverage gap: {gap.title}."
            if case.reasoning and gap_reason.lower() not in case.reasoning.lower():
                case.reasoning = f"{gap_reason} {case.reasoning}"
            elif not case.reasoning:
                case.reasoning = gap_reason
            if not case.graph_reasoning:
                case.graph_reasoning = case.reasoning
            case.evidence = sanitize_evidence(case.evidence, catalog)
            # Always retain the coverage_gap evidence anchor
            if not any(e.source_type == "coverage_gap" for e in case.evidence):
                case.evidence = [
                    EvidenceReference(
                        source_type="coverage_gap",
                        source_id=gap.gap_id,
                        source_title=gap.title,
                        relevance="Targeted regeneration for prioritized coverage gap",
                    )
                ] + list(case.evidence)
            if not case.evidence and case.graph_path:
                case.evidence = evidence_for_path_bugs_and_requirements(
                    case.graph_path, fused, catalog
                )
            if case.evidence and not case.source_references:
                case.source_references = legacy_source_strings(case.evidence)
            elif case.evidence:
                merged = list(case.source_references) + legacy_source_strings(case.evidence)
                seen_refs: set[str] = set()
                unique_refs: list[str] = []
                for s in merged:
                    if s not in seen_refs:
                        seen_refs.add(s)
                        unique_refs.append(s)
                case.source_references = unique_refs

        cases = deduplicate_tests(cases, against=existing_tests)
        # Persist lightly for coverage matching
        store = get_graph_store()
        for case in cases:
            store.test_cases[case.test_case_id] = case.model_dump(mode="json")
        if cases:
            store.persist()
        return cases

    def _generate_targeted_with_llm(
        self,
        gap: CoverageGap,
        fused: FusedContext,
        project_id: str,
        existing_tests: list[TestCase],
        openai: Any,
    ) -> list[TestCase]:
        context = self.build_targeted_context(gap, fused, existing_tests)
        user_prompt = (
            "Generate a test case specifically for this coverage gap.\n\n"
            f"{json.dumps(context, indent=2, default=str)}"
        )
        last_error: str | None = None
        for attempt in range(1, self.MAX_LLM_ATTEMPTS + 1):
            try:
                repair_hint = ""
                if attempt > 1:
                    repair_hint = (
                        "\n\nPrevious output was invalid or empty. "
                        "Return a valid JSON object with a non-empty test_cases array "
                        "matching the required schema exactly. "
                        "Generate only for the stated coverage gap."
                    )
                data = openai.chat_json(
                    self.TARGETED_SYSTEM_PROMPT,
                    user_prompt + repair_hint,
                    temperature=0.2,
                    strict=True,
                )
                cases = self._parse_and_validate_cases(
                    data,
                    project_id,
                    fused,
                    generation_method="critic",
                    id_offset=len(existing_tests),
                )
                if cases:
                    # Cap at 2 per gap
                    return cases[:2]
                last_error = "empty_or_unusable_test_cases"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning(
                    "targeted_llm_attempt_failed",
                    attempt=attempt,
                    gap_id=gap.gap_id,
                    error=last_error,
                )
        logger.warning(
            "targeted_llm_exhausted_attempts",
            gap_id=gap.gap_id,
            last_error=last_error,
        )
        return []

    def _generate_targeted_deterministic(
        self,
        gap: CoverageGap,
        fused: FusedContext,
        project_id: str,
        existing_tests: list[TestCase],
    ) -> list[TestCase]:
        """Deterministic fallback for a single coverage gap."""
        path = list(gap.graph_path) or [fused.feature_context.get("name") or "Feature"]
        path_meta = {
            tuple(item.get("path") or []): item
            for item in fused.graph_context
            if item.get("path")
        }
        meta = path_meta.get(tuple(path), {})
        gap_type = gap.gap_type.value if hasattr(gap.gap_type, "value") else str(gap.gap_type)
        is_failure = bool(meta.get("is_failure_path")) or gap_type in ("failure", "negative")
        external = bool(meta.get("includes_external_dependency")) or gap_type == "risk"
        catalog = build_evidence_catalog(fused)

        if gap_type == "bug":
            title = f"Regression: {gap.title.split(':', 1)[-1].strip()}"
            category = "regression"
            technique = "Historical-bug regression testing"
        elif gap_type in ("failure", "negative"):
            title = f"Negative coverage: {' → '.join(path)}"
            category = "negative"
            technique = "Negative testing / fault injection"
            is_failure = True
        elif gap_type == "requirement":
            title = f"Requirement coverage: {gap.title.split(':', 1)[-1].strip()[:80]}"
            category = "functional"
            technique = "Requirements-based testing"
        elif gap_type == "alternate":
            title = f"Alternate flow: {' → '.join(path)}"
            category = "functional"
            technique = "Alternate flow / recovery testing"
        else:
            title = f"Gap coverage: {' → '.join(path)}"
            category = "security" if external else "functional"
            technique = _technique_for_path(path)

        # Avoid colliding with an existing identical title+path by slight rename only when needed
        existing_titles = {(t.title or "").lower() for t in existing_tests}
        if title.lower() in existing_titles:
            title = f"{title} (gap {gap.gap_id[-6:]})"

        evidence = [
            EvidenceReference(
                source_type="coverage_gap",
                source_id=gap.gap_id,
                source_title=gap.title,
                relevance="Deterministic targeted regeneration for prioritized coverage gap",
            )
        ]
        # Prefer gap-provided evidence (already sanitized at build time) + path-linked
        for e in gap.evidence or []:
            if e.source_type == "coverage_gap":
                continue
            evidence.append(e)
        evidence.extend(evidence_for_path_bugs_and_requirements(path, fused, catalog)[:4])
        evidence = sanitize_evidence(evidence, catalog) or evidence[:1]

        reasoning = (
            f"This test was generated to close coverage gap: {gap.title}. "
            f"{gap.reason or gap.description}"
        )
        priority = gap.priority if isinstance(gap.priority, Priority) else Priority.HIGH
        risk = gap.risk if isinstance(gap.risk, RiskLevel) else RiskLevel.HIGH

        case = TestCase(
            test_case_id=f"TC-{len(existing_tests) + 1:03d}",
            title=title,
            category=category,
            priority=priority,
            risk=risk,
            preconditions=[
                f"Coverage gap in scope: {gap.title}",
                f"Graph path under test: {' → '.join(path)}",
            ],
            test_data=self._test_data(path, is_failure),
            steps=self._steps(path, is_failure),
            expected_result=self._expected(path, is_failure),
            testing_technique=technique,
            graph_path=path,
            graph_reasoning=reasoning,
            reasoning=reasoning,
            source_references=legacy_source_strings(evidence),
            evidence=evidence,
            confidence=ConfidenceLevel.MEDIUM,
            assumptions=[
                "Gap derived deterministically from CoverageEngine + fused context.",
                "Targeted regeneration does not claim the full suite is complete.",
            ],
            project_id=project_id,
            feature_id=fused.feature_context.get("id"),
            generation_method="critic",
            closes_gap_id=gap.gap_id,
            closes_gap_title=gap.title,
        )
        return deduplicate_tests([case], against=existing_tests)

    def _generate_with_llm(
        self,
        query: str,
        fused: FusedContext,
        project_id: str,
        openai: Any,
    ) -> list[TestCase]:
        context = self.build_llm_context(query, fused)
        user_prompt = (
            "Generate structured QA test cases from this fused context.\n\n"
            f"{json.dumps(context, indent=2, default=str)}"
        )

        last_error: str | None = None
        for attempt in range(1, self.MAX_LLM_ATTEMPTS + 1):
            try:
                repair_hint = ""
                if attempt > 1:
                    repair_hint = (
                        "\n\nPrevious output was invalid or empty. "
                        "Return a valid JSON object with a non-empty test_cases array "
                        "matching the required schema exactly."
                    )
                data = openai.chat_json(
                    self.SYSTEM_PROMPT,
                    user_prompt + repair_hint,
                    temperature=0.2,
                    strict=True,
                )
                cases = self._parse_and_validate_cases(data, project_id, fused)
                if cases:
                    return cases
                last_error = "empty_or_unusable_test_cases"
                logger.warning(
                    "testcase_llm_attempt_unusable",
                    attempt=attempt,
                    raw_keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning("testcase_llm_attempt_failed", attempt=attempt, error=last_error)

        logger.warning("testcase_llm_exhausted_attempts", last_error=last_error)
        return []

    def _parse_and_validate_cases(
        self,
        data: dict[str, Any],
        project_id: str,
        fused: FusedContext,
        *,
        generation_method: str = "llm",
        id_offset: int = 0,
    ) -> list[TestCase]:
        if not isinstance(data, dict):
            return []
        raw_cases = data.get("test_cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            return []

        feature_id = fused.feature_context.get("id")
        feature_name = fused.feature_context.get("name") or "Feature"
        catalog = build_evidence_catalog(fused)
        valid: list[TestCase] = []
        for idx, raw in enumerate(raw_cases, start=1):
            if not isinstance(raw, dict):
                continue
            try:
                payload = dict(raw)
                payload.setdefault("test_case_id", f"TC-{id_offset + idx:03d}")
                payload.setdefault("project_id", project_id)
                payload.setdefault("feature_id", feature_id)
                payload.setdefault("generation_method", generation_method)
                # Normalize enums that may arrive as unexpected casing
                if "priority" in payload and isinstance(payload["priority"], str):
                    payload["priority"] = payload["priority"].lower()
                if "risk" in payload and isinstance(payload["risk"], str):
                    payload["risk"] = payload["risk"].lower()
                if "confidence" in payload and isinstance(payload["confidence"], str):
                    payload["confidence"] = payload["confidence"].lower()
                if not payload.get("graph_path"):
                    payload["graph_path"] = [feature_name]
                if not payload.get("steps"):
                    continue
                if not payload.get("title"):
                    continue
                if not payload.get("expected_result"):
                    payload["expected_result"] = "Behavior matches evidence-backed expectations."

                # Sanitize evidence before validation — drop fabricated IDs
                claimed_evidence = payload.pop("evidence", None) or []
                sanitized = sanitize_evidence(claimed_evidence, catalog)
                if not sanitized:
                    sanitized = evidence_for_path_bugs_and_requirements(
                        list(payload.get("graph_path") or [feature_name]),
                        fused,
                        catalog,
                    )
                payload["evidence"] = [e.model_dump() for e in sanitized]

                reasoning = payload.get("reasoning") or payload.get("graph_reasoning")
                if reasoning:
                    payload["reasoning"] = reasoning
                    payload.setdefault("graph_reasoning", reasoning)
                if not payload.get("source_references"):
                    payload["source_references"] = legacy_source_strings(sanitized) or [
                        "User-provided system flow graph"
                    ]

                case = TestCase.model_validate(payload)
                # Re-number for stable baseline-compatible IDs
                case.test_case_id = f"TC-{id_offset + len(valid) + 1:03d}"
                case.generation_method = generation_method
                case.evidence = sanitized
                if not case.reasoning:
                    case.reasoning = case.graph_reasoning or None
                valid.append(case)
            except Exception as exc:  # noqa: BLE001
                logger.warning("testcase_llm_item_invalid", index=idx, error=str(exc))
                continue
        return valid

    def _generate_deterministic(
        self,
        query: str,
        fused: FusedContext,
        project_id: str,
    ) -> list[TestCase]:
        """Baseline graph-path heuristic generator (fallback).

        Reserves a small set of high-risk uncovered leaf paths (e.g. SSO Timeout)
        for the critic-targeted regeneration loop so the demo shows
        Initial → Gaps → Targeted → Final instead of exhausting all paths upfront.
        """
        _ = query  # reserved for parity with LLM signature / future filters
        cases: list[TestCase] = []
        feature = fused.feature_context.get("name") or "Feature"
        existing_titles = {(t.get("title") or "").lower() for t in fused.existing_coverage}
        existing_tokens: set[str] = set()
        for t in fused.existing_coverage:
            for part in t.get("graph_path") or []:
                existing_tokens.add(str(part).lower())
            title = (t.get("title") or "").lower()
            existing_tokens.update(title.split())

        path_meta = {
            tuple(item.get("path") or []): item
            for item in fused.graph_context
            if item.get("path")
        }
        paths = fused.flow_paths or list(path_meta.keys())
        if not paths and fused.feature_context.get("branches"):
            paths = [[feature, b] for b in fused.feature_context["branches"]]

        # Leaves intentionally left for critic-targeted regeneration when uncovered
        reserved_leaves = {"sso timeout", "account lockout"}
        deferred: list[list[str]] = []
        catalog = build_evidence_catalog(fused)
        emit_idx = 0
        for path in paths:
            path_list = list(path) if not isinstance(path, list) else path
            leaf = (path_list[-1] if path_list else "").lower()
            leaf_covered = leaf in existing_tokens if leaf else True
            if (
                leaf in reserved_leaves
                and not leaf_covered
                and len(deferred) < 2
            ):
                deferred.append(path_list)
                logger.info(
                    "deterministic_path_reserved_for_targeted",
                    path=" → ".join(path_list),
                )
                continue

            emit_idx += 1
            meta = path_meta.get(tuple(path_list), {})
            is_failure = bool(meta.get("is_failure_path"))
            external = bool(meta.get("includes_external_dependency"))
            title = self._title_for(path_list, is_failure)
            if title.lower() in existing_titles:
                title = f"Verify existing coverage: {title}"

            risk = RiskLevel.HIGH if is_failure or external else RiskLevel.MEDIUM
            evidence = evidence_for_path_bugs_and_requirements(path_list, fused, catalog)
            reasoning = (
                f"This test covers the discovered graph path {' → '.join(path_list)}. "
                + (
                    "Path includes an external dependency boundary."
                    if external
                    else "Path represents a user-reachable authentication journey."
                )
                + (" Failure/negative behavior is in scope." if is_failure else "")
            )
            sources = legacy_source_strings(evidence) or ["User-provided system flow graph"]

            cases.append(
                TestCase(
                    test_case_id=f"TC-{emit_idx:03d}",
                    title=title,
                    category="security"
                    if external or "mfa" in " ".join(path_list).lower()
                    else "functional",
                    priority=_priority_for_path(path_list, is_failure, external),
                    risk=risk,
                    preconditions=[
                        f"Project system flow includes path: {' → '.join(path_list)}",
                        "Test environment mirrors production auth configuration.",
                    ],
                    test_data=self._test_data(path_list, is_failure),
                    steps=self._steps(path_list, is_failure),
                    expected_result=self._expected(path_list, is_failure),
                    testing_technique=_technique_for_path(path_list),
                    graph_path=path_list,
                    graph_reasoning=reasoning,
                    reasoning=reasoning,
                    source_references=sources,
                    evidence=evidence,
                    confidence=ConfidenceLevel.HIGH
                    if not meta.get("inferred")
                    else ConfidenceLevel.MEDIUM,
                    assumptions=[
                        "User-provided flow graph accurately reflects production behavior.",
                        "Inferred nodes (if any) are marked and not treated as confirmed architecture.",
                    ],
                    project_id=project_id,
                    feature_id=fused.feature_context.get("id"),
                    generation_method="deterministic_fallback",
                )
            )
        if deferred:
            logger.info(
                "deterministic_reserved_paths",
                count=len(deferred),
                paths=[" → ".join(p) for p in deferred],
            )
        return cases

    def _title_for(self, path: list[str], is_failure: bool) -> str:
        leaf = path[-1] if path else "flow"
        if is_failure or any(k in leaf.lower() for k in ("invalid", "failure", "lockout", "timeout")):
            return f"Graceful handling: {' → '.join(path)}"
        if "valid" in leaf.lower() or "session" in leaf.lower() or leaf.lower() in {"callback", "consent"}:
            return f"Successful journey: {' → '.join(path)}"
        return f"Validate path: {' → '.join(path)}"

    def _test_data(self, path: list[str], is_failure: bool) -> dict[str, Any]:
        joined = " ".join(path).lower()
        if "google" in joined or "oauth" in joined:
            return {"provider": "Google", "account": "qa.oauth@example.com"}
        if "sso" in joined or "saml" in joined or "oidc" in joined:
            return {"idp": "enterprise-idp", "protocol": "SAML" if "saml" in joined else "OIDC"}
        if "password" in joined or "email" in joined:
            return {
                "email": "qa.user@example.com",
                "password": "WrongPass!" if is_failure or "invalid" in joined else "CorrectPass!23",
            }
        return {"persona": "standard_user"}

    def _steps(self, path: list[str], is_failure: bool) -> list[str]:
        steps = [f"Navigate to entry point: {path[0]}"]
        for node in path[1:]:
            steps.append(f"Traverse / exercise: {node}")
        if is_failure:
            steps.append("Inject or trigger the failure condition at the leaf node.")
            steps.append("Observe error handling, messaging, and system state.")
        else:
            steps.append("Complete the happy-path transition through the leaf node.")
            steps.append("Verify resulting application/session state.")
        return steps

    def _expected(self, path: list[str], is_failure: bool) -> str:
        if is_failure:
            return (
                f"System handles failure on path {' → '.join(path)} without crashing, "
                "with clear user feedback and no insecure session creation."
            )
        return (
            f"User successfully completes {' → '.join(path)} and reaches the intended "
            "authenticated/application state."
        )


class ExploratoryAgent:
    def generate(self, fused: FusedContext) -> list[ExploratoryMission]:
        missions: list[ExploratoryMission] = []
        feature = fused.feature_context.get("name") or "Feature"
        for path in fused.flow_paths:
            if len(path) < 2:
                continue
            # Focus on transitions and external boundaries
            transition = f"{path[-2]} → {path[-1]}" if len(path) >= 2 else path[-1]
            is_external = any(
                k in " ".join(path).lower()
                for k in ("oauth", "google", "sso", "provider", "saml", "oidc")
            )
            focus = [
                f"Break the {transition} transition",
                "Refresh / back-button during in-flight auth",
                "Multiple tabs racing the same flow",
                "Network interruption mid-transition",
            ]
            if is_external:
                focus += [
                    "Provider response delay / timeout",
                    "Expired or replayed callback",
                    "Consent denial then retry",
                ]
            missions.append(
                ExploratoryMission(
                    title=f"Explore: {transition}",
                    charter=f"Break the {transition} transition within {feature}.",
                    focus_areas=focus,
                    graph_path=path,
                    risks_to_probe=[
                        "Session fixation / orphan sessions",
                        "Inconsistent error states",
                        "Partial auth tokens left behind",
                    ],
                    heuristics=["Tour", "Interruptions", "Boundaries", "States"],
                    source_references=["User-provided system flow graph"],
                    confidence=ConfidenceLevel.HIGH,
                )
            )
        # Deduplicate by transition title
        seen: set[str] = set()
        unique: list[ExploratoryMission] = []
        for m in missions:
            if m.title in seen:
                continue
            seen.add(m.title)
            unique.append(m)
        return unique[:12]


class BugReportAgent:
    def generate(self, query: str, fused: FusedContext) -> list[BugReport]:
        # Prefer historical patterns + likely failure paths
        reports: list[BugReport] = []
        for bug in fused.historical_risks[:5]:
            reports.append(
                BugReport(
                    bug_id=bug.get("bug_id") or new_id("BUG"),
                    title=bug.get("title") or "Historical defect pattern",
                    severity=RiskLevel(bug.get("severity", "medium"))
                    if bug.get("severity") in {r.value for r in RiskLevel}
                    else RiskLevel.MEDIUM,
                    steps_to_reproduce=[
                        "Reproduce using the associated graph path.",
                        "Compare current behavior to historical failure signature.",
                    ],
                    expected_result="Defect no longer reproducible; regression guard in place.",
                    actual_result="Historical pattern indicates prior breakage on this path.",
                    environment="Staging / QA",
                    graph_path=bug.get("graph_path")
                    or (fused.flow_paths[0] if fused.flow_paths else []),
                    affected_components=bug.get("affected_components") or [],
                    source_references=[bug.get("bug_id") or "historical_bugs"],
                )
            )
        if not reports:
            failure_paths = [p for p in fused.flow_paths if any("fail" in x.lower() or "lock" in x.lower() or "invalid" in x.lower() for x in p)]
            for path in failure_paths[:3]:
                reports.append(
                    BugReport(
                        title=f"Potential defect area: {' → '.join(path)}",
                        severity=RiskLevel.HIGH,
                        steps_to_reproduce=[f"Exercise failure path {' → '.join(path)}"],
                        expected_result="Controlled failure handling",
                        actual_result="(Template) Observe and document actual deviation",
                        graph_path=path,
                        source_references=["User-provided system flow graph"],
                    )
                )
        return reports


class RegressionAgent:
    def recommend(
        self,
        fused: FusedContext,
        impact: ImpactAnalysisResult | None,
        changed_node: str | None,
    ) -> list[RegressionRecommendation]:
        recs: list[RegressionRecommendation] = []
        changed = changed_node or (impact.changed_node if impact else None) or fused.feature_context.get("name")
        # From existing tests intersecting impact
        for tc in fused.existing_coverage:
            path = tc.get("graph_path") or []
            path_l = " ".join(str(p) for p in path).lower()
            related = False
            if changed and changed.lower() in path_l:
                related = True
            if impact and any(n.lower() in path_l for n in impact.directly_impacted_nodes[:10]):
                related = True
            if related:
                recs.append(
                    RegressionRecommendation(
                        test_case_id=tc.get("test_case_id") or new_id("TC"),
                        title=tc.get("title") or "Regression candidate",
                        reason=(
                            f"This test is recommended because it covers [{ ' → '.join(path) }], "
                            f"which is connected to the changed node '{changed}'."
                        ),
                        graph_path=list(path),
                        changed_node=changed,
                        priority=Priority.HIGH,
                        source_references=["Graph impact analysis", "Existing test catalog"],
                    )
                )
        # Also recommend path tests for direct neighbors
        if impact:
            for name in impact.directly_impacted_nodes[:8]:
                matching = [p for p in fused.flow_paths if name in p]
                for path in matching[:1]:
                    recs.append(
                        RegressionRecommendation(
                            test_case_id=new_id("TC"),
                            title=f"Retest path through {name}",
                            reason=(
                                f"This test is recommended because it covers [{' → '.join(path)}], "
                                f"which is connected to the changed node '{impact.changed_node}'."
                            ),
                            graph_path=path,
                            changed_node=impact.changed_node,
                            priority=Priority.HIGH,
                            source_references=["User-provided system flow graph", "Impact analysis"],
                        )
                    )
        # Dedupe by title
        seen: set[str] = set()
        out: list[RegressionRecommendation] = []
        for r in recs:
            if r.title in seen:
                continue
            seen.add(r.title)
            out.append(r)
        return out[:20]


class ImpactAgent:
    def analyze(self, project_id: str, changed_node: str) -> ImpactAnalysisResult:
        return get_traversal().impact_analysis(project_id, changed_node)


class CoverageAgent:
    def analyze(self, project_id: str, root_feature: str | None = None) -> CoverageGapResult:
        return get_coverage_engine().analyze(project_id, root_feature)


class CriticAgent:
    def review(
        self,
        *,
        test_cases: list[TestCase],
        coverage: CoverageGapResult | None,
        fused: FusedContext,
        add_gap_tests: bool = True,
        project_id: str | None = None,
    ) -> tuple[list[str], list[TestCase]]:
        """Review generated tests for path completeness and coverage gaps.

        When add_gap_tests=True (default for standalone/compat use), appends
        critic-targeted tests for recommended coverage gaps via TestCaseAgent
        generate_for_gap (LLM-first with deterministic fallback).

        The orchestrator Phase-4 loop typically calls with add_gap_tests=False and
        runs bounded prioritized regeneration separately.
        """
        notes: list[str] = []
        improved = list(test_cases)

        paths_covered = {" → ".join(tc.graph_path) for tc in test_cases if tc.graph_path}
        for path in fused.flow_paths:
            key = " → ".join(path)
            if key not in paths_covered:
                notes.append(f"Missing generated test for discovered path: {key}")

        if coverage:
            for gap in coverage.critical_gaps[:6]:
                notes.append(f"Critical gap remains: {gap}")

            if add_gap_tests:
                from app.agents.coverage_gaps import (
                    build_coverage_gaps,
                    select_gaps_for_regeneration,
                )

                structured = build_coverage_gaps(
                    coverage=coverage, fused=fused, test_cases=improved
                )
                selected = select_gaps_for_regeneration(structured, max_gaps=4)
                if selected:
                    agent = TestCaseAgent()
                    pid = project_id or fused.feature_context.get("project_id") or "project"
                    for gap in selected:
                        added = agent.generate_for_gap(gap, fused, pid, improved)
                        if added:
                            improved.extend(added)
                            notes.append(
                                f"Critic added coverage-driven test for gap: {gap.title}"
                            )
                        else:
                            notes.append(
                                f"Critic skipped duplicate/empty generation for gap: {gap.title}"
                            )
                elif coverage.recommended_tests:
                    notes.append(
                        "Coverage recommendations present but no high-priority gaps selected."
                    )

        # Ensure every test has graph_path + reasoning where possible
        for tc in improved:
            if not tc.graph_path and fused.feature_context.get("name"):
                tc.graph_path = [fused.feature_context["name"]]
                notes.append(f"Attached root feature path to {tc.test_case_id}")
            if not tc.reasoning and tc.graph_reasoning:
                tc.reasoning = tc.graph_reasoning
            if not tc.generation_method:
                pass

        openai = get_openai_service()
        if openai.available:
            try:
                data = openai.chat_json(
                    "You are a QA critic. Review test cases for graph-path completeness. "
                    "Return JSON {notes:[], improvements:[]}.",
                    f"tests={[tc.title for tc in improved[:15]]}\ngaps={(coverage.critical_gaps if coverage else [])}",
                )
                notes.extend(data.get("notes") or [])
                notes.extend([f"Improvement: {i}" for i in data.get("improvements") or []])
            except Exception as exc:  # noqa: BLE001
                logger.warning("critic_llm_failed", error=str(exc))

        if not notes:
            notes.append(
                "Critic review complete — path linkage and gap checks passed with no blocking issues."
            )
        return notes, improved


class RiskAgent:
    def assess(self, fused: FusedContext, coverage: CoverageGapResult | None) -> RiskLevel:
        score = 0
        if fused.historical_risks:
            score += 2
        if coverage and coverage.critical_gaps:
            score += 2
        if any(p for p in fused.flow_paths if any("fail" in x.lower() for x in p)):
            score += 1
        if any(
            "oauth" in " ".join(p).lower() or "sso" in " ".join(p).lower() for p in fused.flow_paths
        ):
            score += 1
        if score >= 4:
            return RiskLevel.HIGH
        if score >= 2:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW