"""Pydantic schemas for system flow graphs and QA artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.enums import (
    ConfidenceLevel,
    ConvergenceStatus,
    ExecutionStatus,
    GapType,
    GeneratorRevisionMode,
    NodeType,
    ObligationStatus,
    ObligationType,
    Priority,
    QualityAttribute,
    RelationshipType,
    ReviewFindingType,
    RiskLevel,
    SourceType,
    SuiteType,
    TestBehavior,
    TestLevel,
    TestNature,
    TestOutputFormat,
    TestSource,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Provenance(BaseModel):
    source_type: SourceType = SourceType.USER_INPUT
    source_reference: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    inferred: bool = False


class GraphNode(BaseModel):
    id: str = Field(default_factory=lambda: new_id("node"))
    type: NodeType = NodeType.FEATURE
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    criticality: Priority | None = None
    is_failure_path: bool = False
    is_external_dependency: bool = False
    is_critical: bool = False
    project_id: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def display_label(self) -> str:
        return self.name


class GraphEdge(BaseModel):
    id: str = Field(default_factory=lambda: new_id("edge"))
    source: str
    target: str
    relationship: RelationshipType | str = RelationshipType.HAS_CHILD
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)
    created_at: datetime = Field(default_factory=utc_now)


class SystemFlowGraph(BaseModel):
    project_id: str
    root_node_id: str | None = None
    version: int = 1
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def node_map(self) -> dict[str, GraphNode]:
        return {n.id: n for n in self.nodes}

    def children_of(self, node_id: str) -> list[GraphNode]:
        targets = {e.target for e in self.edges if e.source == node_id}
        nm = self.node_map()
        return [nm[t] for t in targets if t in nm]

    def parents_of(self, node_id: str) -> list[GraphNode]:
        sources = {e.source for e in self.edges if e.target == node_id}
        nm = self.node_map()
        return [nm[s] for s in sources if s in nm]


class NestedBranch(BaseModel):
    name: str
    type: NodeType | None = None
    description: str = ""
    children: list[NestedBranch | str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_failure_path: bool = False
    is_external_dependency: bool = False
    is_critical: bool = False
    criticality: Priority | None = None


class NestedFlowImport(BaseModel):
    """Simplified JSON import format for system flows."""

    root: str
    description: str = ""
    branches: list[NestedBranch] = Field(default_factory=list)
    project_id: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    root_feature: str | None = None


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("project"))
    name: str
    description: str = ""
    root_feature_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentChunk(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chunk"))
    document_id: str
    project_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_reference: str | None = None


class DocumentRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    project_id: str
    filename: str
    content_type: str = "text/plain"
    text: str = ""
    chunk_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class EvidenceReference(BaseModel):
    """Structured evidence link for explainability — never invent IDs."""

    source_type: str  # graph | requirement | existing_test | historical_bug | risk | coverage_gap
    source_id: str | None = None
    source_title: str | None = None
    relevance: str | None = None


class TestClassification(BaseModel):
    """Multi-axis test taxonomy — additive; older clients ignore unknown fields."""

    nature: TestNature = TestNature.FUNCTIONAL
    behavior: list[TestBehavior] = Field(default_factory=list)
    quality_attributes: list[QualityAttribute] = Field(default_factory=list)
    test_levels: list[TestLevel] = Field(default_factory=list)
    suite_types: list[SuiteType] = Field(default_factory=list)
    execution_status: ExecutionStatus = ExecutionStatus.NOT_REVIEWED
    priority: Priority = Priority.MEDIUM
    source: TestSource = TestSource.GENERATED


class UserStory(BaseModel):
    actor: str | None = None
    goal: str | None = None
    business_value: str | None = None

    def to_gherkin_lines(self) -> list[str]:
        lines: list[str] = []
        if self.actor:
            article = "an" if self.actor[0].lower() in "aeiou" else "a"
            lines.append(f"As {article} {self.actor}")
        if self.goal:
            lines.append(f"I want {self.goal}")
        if self.business_value:
            lines.append(f"So that {self.business_value}")
        return lines

    def to_description(self) -> str:
        return "\n".join(self.to_gherkin_lines())


class FeatureTestSpecification(BaseModel):
    feature_name: str
    feature_reference: str | None = None
    description: str | None = None
    user_story: UserStory | None = None
    scenario_ids: list[str] = Field(default_factory=list)

    def display_feature_title(self) -> str:
        if self.feature_reference:
            return f"{self.feature_name} [{self.feature_reference}]"
        return self.feature_name


class TestCase(BaseModel):
    test_case_id: str = Field(default_factory=lambda: new_id("TC"))
    title: str
    category: str = "functional"
    priority: Priority = Priority.MEDIUM
    risk: RiskLevel = RiskLevel.MEDIUM
    preconditions: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    testing_technique: str = ""
    graph_path: list[str] = Field(default_factory=list)
    graph_reasoning: str = ""
    source_references: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    assumptions: list[str] = Field(default_factory=list)
    project_id: str | None = None
    feature_id: str | None = None
    # Additive metadata — optional for API compatibility with older clients
    generation_method: str | None = None  # "llm" | "deterministic_fallback" | "critic"
    # Short "why this test exists" — prefers explicit reasoning; may mirror graph_reasoning
    reasoning: str | None = None
    # Structured evidence (preferred). source_references remains the legacy string list.
    evidence: list[EvidenceReference] = Field(default_factory=list)
    # Phase 4: which coverage gap this critic-targeted test closes (when applicable)
    closes_gap_id: str | None = None
    closes_gap_title: str | None = None
    # Multi-axis taxonomy (optional; normalized on load when missing)
    classification: TestClassification | None = None
    human_edited: bool = False
    postconditions: list[str] = Field(default_factory=list)
    objective: str | None = None
    # Coverage-closure refinement metadata (additive)
    obligation_ids: list[str] = Field(default_factory=list)
    generation_round: int = 0
    revision_version: int = 1
    previous_version_snapshot: dict[str, Any] | None = None
    reviewer_finding_ids: list[str] = Field(default_factory=list)
    revision_summary: str | None = None
    retired: bool = False
    do_not_edit: bool = False


class ExploratoryMission(BaseModel):
    mission_id: str = Field(default_factory=lambda: new_id("EM"))
    title: str
    charter: str
    focus_areas: list[str] = Field(default_factory=list)
    graph_path: list[str] = Field(default_factory=list)
    risks_to_probe: list[str] = Field(default_factory=list)
    heuristics: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class BugReport(BaseModel):
    bug_id: str = Field(default_factory=lambda: new_id("BUG"))
    title: str
    severity: RiskLevel = RiskLevel.MEDIUM
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected_result: str = ""
    actual_result: str = ""
    environment: str = ""
    graph_path: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    # Additive fields — older clients ignore unknown keys; defaults keep payloads valid
    classification: str = "candidate"  # historical | candidate
    generation_method: str = "deterministic_fallback"
    business_impact: str = ""
    missing_information: str = ""


class RegressionRecommendation(BaseModel):
    test_case_id: str
    title: str
    reason: str
    graph_path: list[str] = Field(default_factory=list)
    changed_node: str | None = None
    priority: Priority = Priority.HIGH
    source_references: list[str] = Field(default_factory=list)
    recommendation_id: str = Field(default_factory=lambda: new_id("RR"))
    generation_method: str = "deterministic_fallback"
    related_bug_references: list[str] = Field(default_factory=list)

class ImpactAnalysisResult(BaseModel):
    changed_node: str
    directly_impacted_nodes: list[str] = Field(default_factory=list)
    indirectly_impacted_nodes: list[str] = Field(default_factory=list)
    impacted_user_flows: list[str] = Field(default_factory=list)
    impacted_features: list[str] = Field(default_factory=list)
    impacted_test_cases: list[str] = Field(default_factory=list)
    historical_bugs: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reasoning_paths: list[str] = Field(default_factory=list)


class CoverageGapResult(BaseModel):
    root_feature: str
    covered_branches: list[str] = Field(default_factory=list)
    uncovered_branches: list[str] = Field(default_factory=list)
    uncovered_failure_paths: list[str] = Field(default_factory=list)
    uncovered_dependencies: list[str] = Field(default_factory=list)
    uncovered_states: list[str] = Field(default_factory=list)
    uncovered_business_rules: list[str] = Field(default_factory=list)
    critical_gaps: list[str] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    root_feature_coverage: float = 0.0
    branch_coverage: float = 0.0
    failure_path_coverage: float = 0.0
    dependency_coverage: float = 0.0
    overall_coverage: float = 0.0
    calculation_notes: list[str] = Field(default_factory=list)


class CoverageGap(BaseModel):
    """Structured coverage gap for prioritization and targeted regeneration."""

    gap_id: str = Field(default_factory=lambda: new_id("GAP"))
    gap_type: GapType | str = GapType.BRANCH
    title: str
    description: str = ""
    priority: Priority = Priority.MEDIUM
    risk: RiskLevel = RiskLevel.MEDIUM
    graph_path: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    reason: str = ""
    selected_for_regeneration: bool = False


class CoverageSnapshot(BaseModel):
    """Deterministic before/after coverage view for the regeneration loop."""

    total_paths: int = 0
    covered_paths: int = 0
    coverage_percentage: float = 0.0
    overall_coverage: float = 0.0
    branch_coverage: float = 0.0
    gaps: list[CoverageGap] = Field(default_factory=list)
    critical_gaps: list[str] = Field(default_factory=list)
    uncovered_branches: list[str] = Field(default_factory=list)
    calculation_notes: list[str] = Field(default_factory=list)


class RetrievalPlan(BaseModel):
    use_user_flow_graph: bool = True
    use_vector_rag: bool = True
    use_graph_rag: bool = True
    use_existing_tests: bool = True
    use_historical_bugs: bool = True
    use_external_search: bool = False
    reason: str = ""


class FusedContext(BaseModel):
    feature_context: dict[str, Any] = Field(default_factory=dict)
    flow_paths: list[list[str]] = Field(default_factory=list)
    graph_context: list[dict[str, Any]] = Field(default_factory=list)
    semantic_context: list[dict[str, Any]] = Field(default_factory=list)
    existing_coverage: list[dict[str, Any]] = Field(default_factory=list)
    historical_risks: list[dict[str, Any]] = Field(default_factory=list)
    external_context: list[dict[str, Any]] = Field(default_factory=list)


class AgentTraceStep(BaseModel):
    step: str
    status: str = "pending"  # pending | running | complete | skipped | error
    detail: str = ""
    timestamp: datetime = Field(default_factory=utc_now)


class AutomationCapabilityProfile(BaseModel):
    """Optional project-level automation capabilities. Do not invent missing tools."""

    supported_layers: list[str] = Field(default_factory=list)
    ui_frameworks: list[str] = Field(default_factory=list)
    api_testing_available: bool = False
    stable_test_ids_available: bool = False
    test_data_api_available: bool = False
    database_access_available: bool = False
    service_virtualization_available: bool = False
    mock_services_available: bool = False
    sandbox_integrations_available: bool = False
    ci_execution_available: bool = False
    mobile_device_lab_available: bool = False
    visual_testing_available: bool = False
    accessibility_scanning_available: bool = False
    performance_environment_available: bool = False


class TestValidityReview(BaseModel):
    """Validity / executability decision before automation feasibility."""

    test_case_id: str
    validity: str = "needs_revision"
    validity_score: int = Field(default=70, ge=0, le=100)
    validity_reasons: list[str] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    evidence_checked: list[EvidenceReference] = Field(default_factory=list)
    graph_path_valid: bool | None = None
    requirement_support: str = "unknown"
    duplicate_status: str = "distinct"
    missing_information: list[str] = Field(default_factory=list)
    correction_possible: bool = False
    corrections_applied: list[str] = Field(default_factory=list)
    suggested_corrections: list[str] = Field(default_factory=list)
    reviewed_test_case: TestCase | None = None
    generation_method: str = "deterministic_fallback"
    supported_by_project: bool = True
    supported_by_evidence: bool = False
    contradiction_detected: bool = False
    content_hash: str | None = None


class AutomationFeasibilityReview(BaseModel):
    """Automation feasibility; only meaningful for valid tests."""

    test_case_id: str
    automation_suitability: str = "not_evaluated"
    automation_score: int = Field(default=0, ge=0, le=100)
    automation_reasons: list[str] = Field(default_factory=list)
    non_automation_reasons: list[str] = Field(default_factory=list)
    recommended_layer: str = "unknown"
    automation_priority: str = "not_recommended"
    estimated_effort: str = "unknown"
    confidence: str = "low"
    prerequisites: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    test_data_requirements: list[str] = Field(default_factory=list)
    environment_requirements: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    human_judgment_required: bool = False
    suggested_automation_scope: str = ""
    recommended_assertions: list[str] = Field(default_factory=list)
    recommended_framework_capabilities: list[str] = Field(default_factory=list)
    generation_method: str = "deterministic_fallback"


class ReviewedTestCase(BaseModel):
    """Original test plus validity-first review artifacts."""

    test_case: TestCase
    original_test_case: TestCase | None = None
    validity_review: TestValidityReview
    automation_review: AutomationFeasibilityReview | None = None
    final_review_status: str = "needs_revision"
    human_override: bool = False
    override_reason: str | None = None
    override_timestamp: datetime | None = None
    test_source: str = "generated"  # existing | generated | targeted


class ValiditySummary(BaseModel):
    total_tests: int = 0
    valid: int = 0
    invalid: int = 0
    needs_revision: int = 0
    insufficient_evidence: int = 0


class AutomationSummary(BaseModel):
    total_tests: int = 0
    valid_tests_evaluated: int = 0
    automate: int = 0
    automate_with_conditions: int = 0
    hybrid: int = 0
    manual: int = 0
    not_ready_for_automation: int = 0
    not_evaluated: int = 0
    high_priority_automation: int = 0
    effort_low: int = 0
    effort_medium: int = 0
    effort_high: int = 0


class AutomationReviewOverrideRequest(BaseModel):
    validity: str | None = None
    automation_suitability: str | None = None
    automation_layer: str | None = None
    automation_priority: str | None = None
    automation_effort: str | None = None
    review_status: str | None = None
    override_reason: str = ""


class BDDStep(BaseModel):
    keyword: str  # Given | When | Then | And | But
    text: str


class BDDScenario(BaseModel):
    id: str = Field(default_factory=lambda: new_id("BDD"))
    feature: str
    feature_description: str | None = None
    feature_reference: str | None = None
    rule: str | None = None
    section: str | None = None  # FUNCTIONAL | NEGATIVE | NON-FUNCTIONAL | SECURITY | …
    scenario_name: str
    scenario_type: str = "scenario"  # scenario | scenario_outline
    tags: list[str] = Field(default_factory=list)
    background: list[BDDStep] = Field(default_factory=list)
    steps: list[BDDStep] = Field(default_factory=list)
    examples: list[dict[str, str]] = Field(default_factory=list)
    priority: str = "medium"
    test_type: str = "functional"
    classification: TestClassification | None = None
    graph_path: list[str] = Field(default_factory=list)
    requirement_references: list[str] = Field(default_factory=list)
    bug_references: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    generation_method: str = "deterministic_fallback"
    source_test_id: str | None = None
    conversion_status: str = "ok"  # ok | needs_revision
    conversion_notes: list[str] = Field(default_factory=list)
    gherkin_text: str = ""


class GeneratedTestArtifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ART"))
    format: str = "standard"
    logical_test_id: str
    standard_test_case: TestCase | None = None
    bdd_scenario: BDDScenario | None = None
    source_test_id: str | None = None
    graph_path: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    priority: str = "medium"
    generation_method: str | None = None


class CoverageObligation(BaseModel):
    obligation_id: str = Field(default_factory=lambda: new_id("OBL"))
    project_id: str
    feature_id: str | None = None
    obligation_type: ObligationType = ObligationType.GRAPH_PATH
    title: str
    description: str = ""
    priority: Priority = Priority.MEDIUM
    mandatory: bool = True
    graph_path: list[str] = Field(default_factory=list)
    graph_node_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    bug_ids: list[str] = Field(default_factory=list)
    risk_ids: list[str] = Field(default_factory=list)
    dependency_ids: list[str] = Field(default_factory=list)
    role: str | None = None
    state_from: str | None = None
    state_to: str | None = None
    classification_requirements: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    status: ObligationStatus = ObligationStatus.OPEN
    covered_by_test_ids: list[str] = Field(default_factory=list)
    coverage_reason: str | None = None
    unsupported_reason: str | None = None
    evidence_basis: str = ""


class ObligationCoverageMatch(BaseModel):
    obligation_id: str
    test_case_id: str
    covered: bool = False
    match_score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    conflicting_elements: list[str] = Field(default_factory=list)


class TestReviewFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: new_id("FIND"))
    test_case_id: str
    severity: Priority = Priority.MEDIUM
    finding_type: ReviewFindingType = ReviewFindingType.NEEDS_REVISION
    status: str = "open"
    explanation: str = ""
    affected_fields: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    required_action: GeneratorRevisionMode = GeneratorRevisionMode.REVISE
    revision_instruction: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)


class MissingScenarioFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: new_id("MISS"))
    obligation_ids: list[str] = Field(default_factory=list)
    category: str = "functional"
    priority: Priority = Priority.HIGH
    title: str
    explanation: str = ""
    required_graph_path: list[str] = Field(default_factory=list)
    required_behavior: str = ""
    required_expected_outcome: str = ""
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    generation_instruction: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)


class RevisionPlan(BaseModel):
    revise_test_ids: list[str] = Field(default_factory=list)
    reject_test_ids: list[str] = Field(default_factory=list)
    retain_test_ids: list[str] = Field(default_factory=list)
    create_for_obligation_ids: list[str] = Field(default_factory=list)
    merge_candidates: list[list[str]] = Field(default_factory=list)
    split_candidates: list[str] = Field(default_factory=list)
    priority_order: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class TestSuiteReview(BaseModel):
    review_id: str = Field(default_factory=lambda: new_id("REV"))
    project_id: str
    analysis_id: str | None = None
    iteration: int = 1
    overall_status: str = "open"
    suite_quality_score: float = 0.0
    obligation_coverage: list[ObligationCoverageMatch] = Field(default_factory=list)
    per_test_findings: list[TestReviewFinding] = Field(default_factory=list)
    missing_scenario_findings: list[MissingScenarioFinding] = Field(default_factory=list)
    duplicate_findings: list[TestReviewFinding] = Field(default_factory=list)
    contradiction_findings: list[TestReviewFinding] = Field(default_factory=list)
    revision_plan: RevisionPlan = Field(default_factory=RevisionPlan)
    blocking_findings: list[str] = Field(default_factory=list)
    convergence_recommendation: str = "continue"


class CategoryCoverage(BaseModel):
    category: str
    required_obligations: int = 0
    covered_obligations: int = 0
    coverage_percentage: float = 0.0
    missing_obligations: list[str] = Field(default_factory=list)
    evidence_basis: str = ""
    applicability: str = "applicable"


class RefinementIterationSnapshot(BaseModel):
    iteration: int
    test_count: int = 0
    modeled_coverage_pct: float = 0.0
    mandatory_total: int = 0
    mandatory_covered: int = 0
    invalid_count: int = 0
    needs_revision_count: int = 0
    tests_created: int = 0
    tests_revised: int = 0
    tests_retired: int = 0
    duplicates_removed: int = 0
    open_mandatory_obligations: list[str] = Field(default_factory=list)
    findings_count: int = 0
    message: str = ""


class ConvergenceReport(BaseModel):
    status: ConvergenceStatus = ConvergenceStatus.PARTIAL
    iterations_completed: int = 0
    initial_test_count: int = 0
    final_test_count: int = 0
    initial_modeled_coverage: float = 0.0
    final_modeled_coverage: float = 0.0
    mandatory_obligations_total: int = 0
    mandatory_obligations_covered: int = 0
    invalid_before: int = 0
    invalid_after: int = 0
    needs_revision_before: int = 0
    needs_revision_after: int = 0
    tests_created: int = 0
    tests_revised: int = 0
    tests_split: int = 0
    tests_merged: int = 0
    tests_retired: int = 0
    duplicates_removed: int = 0
    remaining_obligations: list[str] = Field(default_factory=list)
    remaining_findings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    modeled_coverage_label: str = "Modeled graph-and-requirement coverage"


class QACopilotRequest(BaseModel):
    project_id: str
    query: str
    root_feature: str | None = None
    changed_node: str | None = None
    include_critic: bool = True
    enable_targeted_regeneration: bool = True
    max_regeneration_rounds: int = Field(default=2, ge=0, le=2)
    max_gaps_per_round: int = Field(default=8, ge=0, le=10)
    requested_outputs: list[str] = Field(default_factory=list)
    automation_strategy: str | None = None
    include_test_review: bool = True
    test_output_format: TestOutputFormat = TestOutputFormat.STANDARD
    enable_test_refinement: bool | None = None
    test_refinement_max_iterations: int | None = Field(default=None, ge=1, le=8)
    resume_refinement: bool = False


class SectionStatus(BaseModel):
    status: str = "empty"
    count: int = 0
    error: str | None = None
    requested_format: str | None = None
    logical_test_count: int | None = None
    standard_count: int | None = None
    bdd_count: int | None = None
    validation_errors: list[str] = Field(default_factory=list)
    iterations: int | None = None
    modeled_coverage: float | None = None
    invalid: int | None = None
    needs_revision: int | None = None
    remaining_mandatory_obligations: int | None = None


class QACopilotResponse(BaseModel):
    project_id: str
    query: str
    intent: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    root_feature: str | None = None
    discovered_branches: list[str] = Field(default_factory=list)
    discovered_graph_paths: list[list[str]] = Field(default_factory=list)
    graph_coverage: float | None = None
    critical_gaps: list[str] = Field(default_factory=list)
    historical_bug_patterns: list[str] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    exploratory_missions: list[ExploratoryMission] = Field(default_factory=list)
    bug_reports: list[BugReport] = Field(default_factory=list)
    regression_recommendations: list[RegressionRecommendation] = Field(default_factory=list)
    impact_analysis: ImpactAnalysisResult | None = None
    coverage: CoverageGapResult | None = None
    retrieval_plan: RetrievalPlan | None = None
    fused_context_summary: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    assumptions: list[str] = Field(default_factory=list)
    critic_notes: list[str] = Field(default_factory=list)
    execution_trace: list[AgentTraceStep] = Field(default_factory=list)
    narrative: str = ""
    # Phase 4 additive fields — optional for older clients
    initial_test_cases: list[TestCase] = Field(default_factory=list)
    selected_coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    targeted_test_cases: list[TestCase] = Field(default_factory=list)
    coverage_before: CoverageSnapshot | None = None
    coverage_after: CoverageSnapshot | None = None
    regeneration_rounds: int = 0
    unresolved_gaps: list[CoverageGap] = Field(default_factory=list)
    # Phase 5 additive demo/reliability fields
    duplicates_removed: int = 0
    generation_backend: str | None = None  # openai | deterministic_fallback | mixed
    runtime_diagnostics: dict[str, Any] = Field(default_factory=dict)
    model_routing: dict[str, Any] = Field(default_factory=dict)
    section_status: dict[str, SectionStatus] = Field(default_factory=dict)
    # Test review + automation feasibility (additive — original test_cases preserved)
    reviewed_test_cases: list[ReviewedTestCase] = Field(default_factory=list)
    valid_tests: list[TestCase] = Field(default_factory=list)
    invalid_tests: list[TestCase] = Field(default_factory=list)
    needs_revision_tests: list[TestCase] = Field(default_factory=list)
    insufficient_evidence_tests: list[TestCase] = Field(default_factory=list)
    automation_candidates: list[TestCase] = Field(default_factory=list)
    manual_tests: list[TestCase] = Field(default_factory=list)
    hybrid_tests: list[TestCase] = Field(default_factory=list)
    conditional_automation_tests: list[TestCase] = Field(default_factory=list)
    not_evaluated_tests: list[TestCase] = Field(default_factory=list)
    validity_summary: ValiditySummary | None = None
    automation_summary: AutomationSummary | None = None
    # BDD / dual-format generation (additive)
    test_output_format: str = "standard"
    bdd_scenarios: list[BDDScenario] = Field(default_factory=list)
    generated_test_artifacts: list[GeneratedTestArtifact] = Field(default_factory=list)
    # Feature-level stories + taxonomy aggregates (additive)
    feature_test_specifications: list[FeatureTestSpecification] = Field(default_factory=list)
    feature_story: UserStory | None = None
    test_classification_summary: dict[str, Any] = Field(default_factory=dict)
    category_counts: dict[str, int] = Field(default_factory=dict)
    coverage_obligations: list[CoverageObligation] = Field(default_factory=list)
    obligation_coverage: list[ObligationCoverageMatch] = Field(default_factory=list)
    category_coverage: list[CategoryCoverage] = Field(default_factory=list)
    iteration_history: list[RefinementIterationSnapshot] = Field(default_factory=list)
    convergence_report: ConvergenceReport | None = None
    final_suite_review: TestSuiteReview | None = None


class GraphPath(BaseModel):
    node_ids: list[str]
    node_names: list[str]
    relationships: list[str] = Field(default_factory=list)
    is_failure_path: bool = False
    includes_external_dependency: bool = False


class NodeInsight(BaseModel):
    node: GraphNode
    connected_features: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    flows: list[str] = Field(default_factory=list)
    existing_tests: list[str] = Field(default_factory=list)
    historical_bugs: list[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.MEDIUM
    coverage: float | None = None
    incoming: list[dict[str, Any]] = Field(default_factory=list)
    outgoing: list[dict[str, Any]] = Field(default_factory=list)