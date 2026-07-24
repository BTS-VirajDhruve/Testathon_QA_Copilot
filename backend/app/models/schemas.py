"""Pydantic schemas for system flow graphs and QA artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.enums import (
    ConfidenceLevel,
    GapType,
    NodeType,
    Priority,
    RelationshipType,
    RiskLevel,
    SourceType,
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


class RegressionRecommendation(BaseModel):
    test_case_id: str
    title: str
    reason: str
    graph_path: list[str] = Field(default_factory=list)
    changed_node: str | None = None
    priority: Priority = Priority.HIGH
    source_references: list[str] = Field(default_factory=list)


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


class QACopilotRequest(BaseModel):
    project_id: str
    query: str
    root_feature: str | None = None
    changed_node: str | None = None
    include_critic: bool = True
    # Phase 4: bounded critic → gap → targeted regeneration (default 1, hard max 2)
    enable_targeted_regeneration: bool = True
    max_regeneration_rounds: int = Field(default=1, ge=0, le=2)
    max_gaps_per_round: int = Field(default=4, ge=0, le=10)


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