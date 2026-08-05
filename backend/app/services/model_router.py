"""Centralized task-aware model routing, complexity, escalation, and reviewer decisions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.enums import LLMTaskType, RequirementComplexity

logger = get_logger(__name__)

ROUTING_POLICY_VERSION = "1.0"

# Built-in task → model defaults (overridable via env / settings).
DEFAULT_TASK_MODEL_MAP: dict[LLMTaskType, str] = {
    LLMTaskType.INTENT_CLASSIFICATION: "gpt-5.4-mini",
    LLMTaskType.QA_DOCUMENTATION: "gpt-5.4-mini",
    LLMTaskType.REGRESSION_SELECTION: "gpt-5.4-mini",
    LLMTaskType.BUG_REPORT: "gpt-5.6-luna",
    LLMTaskType.TEST_CASE_GENERATION: "gpt-5.6-luna",
    LLMTaskType.TARGETED_TEST_GENERATION: "gpt-5.6-luna",
    LLMTaskType.TEST_CASE_REVISION: "gpt-5.6-luna",
    LLMTaskType.MISSING_SCENARIO_GENERATION: "gpt-5.6-luna",
    LLMTaskType.TEST_SUITE_REVIEW: "gpt-5.6-luna",
    LLMTaskType.REVIEWER_VERIFICATION: "gpt-5.6-terra",
    LLMTaskType.EXPLORATORY_SCENARIO: "gpt-5.6-sol",
    LLMTaskType.REVIEWER_PASS: "gpt-5.6-terra",
    LLMTaskType.GRAPH_EXTRACTION: "gpt-5.4-mini",
    LLMTaskType.ENTITY_EXTRACTION: "gpt-5.4-mini",
    LLMTaskType.OUTPUT_REPAIR: "gpt-5.4-mini",
    LLMTaskType.CRITIC_NOTES: "gpt-5.4-mini",
    LLMTaskType.TEST_REVIEW_AUTOMATION: "gpt-5.6-luna",
    LLMTaskType.TEST_VALIDITY_REVIEW: "gpt-5.6-luna",
    LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW: "gpt-5.6-luna",
    LLMTaskType.BDD_EXPORT_CONVERSION: "gpt-5.4-mini",
}


class ModelRoutingContext(BaseModel):
    """Runtime signals used for model selection and escalation. Do not invent precision."""

    project_id: str | None = None
    task_type: LLMTaskType | None = None
    user_intent: str | None = None
    selected_feature: str | None = None
    requirement_complexity: RequirementComplexity | None = None
    input_token_estimate: int = 0
    graph_path_count: int = 0
    retrieved_document_count: int = 0
    business_rule_count: int = 0
    failure_path_count: int = 0
    alternate_flow_count: int = 0
    dependency_count: int = 0
    ambiguity_score: float = 0.0
    security_sensitive: bool = False
    release_blocking: bool = False
    financial_impact: bool = False
    criticality: str | None = None
    initial_validation_failed: bool = False
    user_requested_review: bool = False
    regeneration_round: int = 0
    query: str | None = None


class ModelSelection(BaseModel):
    requested_task_type: LLMTaskType
    selected_model: str
    base_model: str
    escalated: bool = False
    escalation_reason: str | None = None
    reviewer_required: bool = False
    reviewer_reasons: list[str] = Field(default_factory=list)
    fallback_model: str | None = None
    routing_enabled_for_task: bool = True
    routing_policy_version: str = ROUTING_POLICY_VERSION


class ReviewerDecision(BaseModel):
    required: bool
    reasons: list[str] = Field(default_factory=list)


class ComplexityAssessment(BaseModel):
    category: RequirementComplexity
    score: int = 0
    signals: list[str] = Field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Explainable, not calibrated."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def assess_requirement_complexity(context: ModelRoutingContext) -> ComplexityAssessment:
    """Deterministic complexity heuristic for test-case generation routing.

    Signals (additive points):
    - input length / estimated tokens
    - retrieved documents, graph paths, dependencies, business rules
    - failure / alternate paths
    - security / financial / release-blocking flags
    - ambiguity score
    Categories: low (0–3), medium (4–7), high (8+)
    """
    score = 0
    signals: list[str] = []

    tokens = context.input_token_estimate or estimate_tokens(context.query or "")
    if tokens >= 2500:
        score += 3
        signals.append(f"large_input_tokens={tokens}")
    elif tokens >= 800:
        score += 2
        signals.append(f"medium_input_tokens={tokens}")
    elif tokens >= 300:
        score += 1
        signals.append(f"modest_input_tokens={tokens}")

    if context.retrieved_document_count >= 6:
        score += 2
        signals.append(f"many_docs={context.retrieved_document_count}")
    elif context.retrieved_document_count >= 3:
        score += 1
        signals.append(f"docs={context.retrieved_document_count}")

    if context.graph_path_count >= 12:
        score += 2
        signals.append(f"many_paths={context.graph_path_count}")
    elif context.graph_path_count >= 6:
        score += 1
        signals.append(f"paths={context.graph_path_count}")

    if context.dependency_count >= 3:
        score += 1
        signals.append(f"deps={context.dependency_count}")
    if context.business_rule_count >= 2:
        score += 1
        signals.append(f"rules={context.business_rule_count}")
    if context.failure_path_count >= 2:
        score += 1
        signals.append(f"failures={context.failure_path_count}")
    if context.alternate_flow_count >= 2:
        score += 1
        signals.append(f"alternates={context.alternate_flow_count}")

    if context.security_sensitive:
        score += 2
        signals.append("security_sensitive")
    if context.financial_impact:
        score += 2
        signals.append("financial_impact")
    if context.release_blocking:
        score += 1
        signals.append("release_blocking")
    if context.ambiguity_score >= 0.6:
        score += 2
        signals.append(f"ambiguity={context.ambiguity_score:.2f}")
    elif context.ambiguity_score >= 0.3:
        score += 1
        signals.append(f"ambiguity={context.ambiguity_score:.2f}")

    if score >= 8:
        category = RequirementComplexity.HIGH
    elif score >= 4:
        category = RequirementComplexity.MEDIUM
    else:
        category = RequirementComplexity.LOW

    return ComplexityAssessment(category=category, score=score, signals=signals)


def infer_sensitivity_flags(query: str | None, feature: str | None = None) -> dict[str, bool]:
    """Cheap keyword heuristics for routing flags — not a security classifier."""
    blob = f"{query or ''} {feature or ''}".lower()
    security = any(
        k in blob
        for k in (
            "security",
            "oauth",
            "sso",
            "auth",
            "permission",
            "role",
            "mfa",
            "pci",
            "encrypt",
            "token",
            "jwt",
        )
    )
    financial = any(
        k in blob
        for k in ("payment", "checkout", "billing", "refund", "invoice", "pricing", "cart")
    )
    release = any(k in blob for k in ("release", "blocker", "production", "p0", "sev-1", "sev1"))
    return {
        "security_sensitive": security,
        "financial_impact": financial,
        "release_blocking": release,
    }


def build_routing_context_from_fused(
    *,
    project_id: str,
    task_type: LLMTaskType,
    query: str,
    user_intent: str | None = None,
    fused: Any = None,
    regeneration_round: int = 0,
    initial_validation_failed: bool = False,
    user_requested_review: bool = False,
) -> ModelRoutingContext:
    feature = None
    path_count = 0
    docs = 0
    rules = 0
    failures = 0
    alternates = 0
    deps = 0
    if fused is not None:
        feature = (fused.feature_context or {}).get("name")
        path_count = len(fused.flow_paths or [])
        docs = len(fused.semantic_context or [])
        for item in fused.graph_context or []:
            t = str(item.get("type") or "").lower()
            if "businessrule" in t or "business_rule" in t:
                rules += 1
            if item.get("is_failure_path") or "failure" in t:
                failures += 1
            if "alternate" in t:
                alternates += 1
            if item.get("includes_external_dependency") or "external" in t:
                deps += 1
    flags = infer_sensitivity_flags(query, feature)
    ctx = ModelRoutingContext(
        project_id=project_id,
        task_type=task_type,
        user_intent=user_intent,
        selected_feature=feature,
        input_token_estimate=estimate_tokens(query),
        graph_path_count=path_count,
        retrieved_document_count=docs,
        business_rule_count=rules,
        failure_path_count=failures,
        alternate_flow_count=alternates,
        dependency_count=deps,
        security_sensitive=flags["security_sensitive"],
        financial_impact=flags["financial_impact"],
        release_blocking=flags["release_blocking"],
        regeneration_round=regeneration_round,
        initial_validation_failed=initial_validation_failed,
        user_requested_review=user_requested_review,
        query=query,
    )
    assessment = assess_requirement_complexity(ctx)
    ctx.requirement_complexity = assessment.category
    return ctx


def decide_reviewer(context: ModelRoutingContext, *, quality_failed: bool = False) -> ReviewerDecision:
    """Conditional expensive reviewer — off by default via settings.model_reviewer_enabled."""
    settings = get_settings()
    if not settings.model_reviewer_enabled:
        return ReviewerDecision(required=False, reasons=["reviewer_disabled"])

    reasons: list[str] = []
    if context.release_blocking:
        reasons.append("release_blocking")
    if context.security_sensitive:
        reasons.append("security_sensitive")
    if context.financial_impact:
        reasons.append("financial_impact")
    if context.user_requested_review:
        reasons.append("user_requested_review")
    if quality_failed or context.initial_validation_failed:
        reasons.append("quality_check_failed")
    if context.requirement_complexity == RequirementComplexity.HIGH and (
        context.security_sensitive or context.release_blocking or context.financial_impact
    ):
        reasons.append("high_complexity_critical_context")

    return ReviewerDecision(required=bool(reasons), reasons=reasons)


class ModelRouter:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def global_default(self) -> str:
        return self.settings.openai_model or "gpt-4o-mini"

    def configured_task_model(self, task_type: LLMTaskType) -> str | None:
        mapping = {
            LLMTaskType.INTENT_CLASSIFICATION: self.settings.openai_model_intent_classification,
            LLMTaskType.QA_DOCUMENTATION: self.settings.openai_model_qa_documentation,
            LLMTaskType.REGRESSION_SELECTION: self.settings.openai_model_regression_selection,
            LLMTaskType.BUG_REPORT: self.settings.openai_model_bug_report,
            LLMTaskType.TEST_CASE_GENERATION: self.settings.openai_model_test_case_generation,
            LLMTaskType.TARGETED_TEST_GENERATION: self.settings.openai_model_targeted_test_generation,
            LLMTaskType.EXPLORATORY_SCENARIO: self.settings.openai_model_exploratory_scenario,
            LLMTaskType.REVIEWER_PASS: self.settings.openai_model_reviewer_pass,
            LLMTaskType.GRAPH_EXTRACTION: self.settings.openai_model_graph_extraction,
            LLMTaskType.ENTITY_EXTRACTION: self.settings.openai_model_entity_extraction,
            LLMTaskType.OUTPUT_REPAIR: self.settings.openai_model_output_repair,
            LLMTaskType.CRITIC_NOTES: self.settings.openai_model_critic_notes,
            LLMTaskType.TEST_REVIEW_AUTOMATION: self.settings.openai_model_test_review_automation,
            LLMTaskType.TEST_VALIDITY_REVIEW: self.settings.openai_model_test_validity_review,
            LLMTaskType.AUTOMATION_FEASIBILITY_REVIEW: self.settings.openai_model_automation_feasibility_review,
            LLMTaskType.BDD_EXPORT_CONVERSION: self.settings.openai_model_bdd_export_conversion,
        }
        value = (mapping.get(task_type) or "").strip()
        return value or None

    def task_routing_enabled(self, task_type: LLMTaskType) -> bool:
        if not self.settings.model_routing_enabled:
            return False
        allow = (self.settings.model_routing_enabled_tasks or "").strip()
        if not allow or allow.lower() in {"*", "all"}:
            return True
        allowed = {t.strip().lower() for t in allow.split(",") if t.strip()}
        return task_type.value.lower() in allowed

    def resolve_model(
        self,
        task_type: LLMTaskType,
        context: ModelRoutingContext | None = None,
    ) -> ModelSelection:
        context = context or ModelRoutingContext(task_type=task_type)
        fallback = self.global_default

        if not self.task_routing_enabled(task_type):
            return ModelSelection(
                requested_task_type=task_type,
                selected_model=fallback,
                base_model=fallback,
                fallback_model=fallback,
                routing_enabled_for_task=False,
            )

        env_override = self.configured_task_model(task_type)
        map_default = DEFAULT_TASK_MODEL_MAP.get(task_type)
        base = env_override or map_default or fallback

        selected = base
        escalated = False
        escalation_reason: str | None = None

        if (
            self.settings.model_escalation_enabled
            and task_type == LLMTaskType.TEST_CASE_GENERATION
        ):
            complexity = context.requirement_complexity
            if complexity is None:
                complexity = assess_requirement_complexity(context).category
                context.requirement_complexity = complexity

            escalate_target = (
                self.settings.openai_model_escalation_target
                or self.configured_task_model(LLMTaskType.REVIEWER_PASS)
                or DEFAULT_TASK_MODEL_MAP[LLMTaskType.REVIEWER_PASS]
            )

            reasons: list[str] = []
            if complexity == RequirementComplexity.HIGH:
                reasons.append("high requirement complexity")
            if context.security_sensitive and self.settings.model_escalate_on_security:
                reasons.append("security_sensitive")
            if context.release_blocking and self.settings.model_escalate_on_release_blocking:
                reasons.append("release_blocking")
            if context.financial_impact and self.settings.model_escalate_on_financial:
                reasons.append("financial_impact")
            if context.initial_validation_failed and self.settings.model_escalate_on_validation_failure:
                reasons.append("initial structured generation failed")
            if context.user_requested_review:
                reasons.append("user requested deep review")
            if context.ambiguity_score >= 0.7 and self.settings.model_escalate_on_ambiguity:
                reasons.append("severe ambiguity")

            if reasons:
                selected = escalate_target
                escalated = True
                escalation_reason = "; ".join(reasons)

        # Targeted generation: stay on base unless critical gap signals
        if (
            self.settings.model_escalation_enabled
            and task_type == LLMTaskType.TARGETED_TEST_GENERATION
            and (
                (context.security_sensitive and self.settings.model_escalate_on_security)
                or (context.release_blocking and self.settings.model_escalate_on_release_blocking)
            )
        ):
            escalate_target = (
                self.settings.openai_model_escalation_target
                or DEFAULT_TASK_MODEL_MAP[LLMTaskType.REVIEWER_PASS]
            )
            selected = escalate_target
            escalated = True
            escalation_reason = "critical targeted gap (security/release)"

        reviewer = decide_reviewer(context)

        selection = ModelSelection(
            requested_task_type=task_type,
            selected_model=selected,
            base_model=base,
            escalated=escalated,
            escalation_reason=escalation_reason,
            reviewer_required=reviewer.required,
            reviewer_reasons=reviewer.reasons,
            fallback_model=fallback,
            routing_enabled_for_task=True,
        )

        if self.settings.model_routing_log_enabled:
            logger.info(
                "model_routed",
                task_type=task_type.value,
                selected_model=selected,
                base_model=base,
                escalated=escalated,
                escalation_reason=escalation_reason,
                reviewer_required=reviewer.required,
                routing_policy_version=ROUTING_POLICY_VERSION,
            )
        return selection

    def intent_to_task_type(self, intent: str) -> LLMTaskType | None:
        """Map known user intents to LLM task types without an extra classifier call."""
        mapping = {
            "test_generation": LLMTaskType.TEST_CASE_GENERATION,
            "exploratory": LLMTaskType.EXPLORATORY_SCENARIO,
            "bug_report": LLMTaskType.BUG_REPORT,
            "regression": LLMTaskType.REGRESSION_SELECTION,
            "documentation": LLMTaskType.QA_DOCUMENTATION,
            "coverage_gap": LLMTaskType.TARGETED_TEST_GENERATION,
            "impact_analysis": LLMTaskType.REGRESSION_SELECTION,
            "requirements_analysis": LLMTaskType.QA_DOCUMENTATION,
        }
        return mapping.get(intent)


_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_model_router() -> None:
    global _router
    _router = None
