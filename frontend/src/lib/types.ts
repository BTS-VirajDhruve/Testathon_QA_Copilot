export type Provenance = {
  source_type: string;
  source_reference?: string | null;
  confidence: number;
  inferred: boolean;
};

export type GraphNode = {
  id: string;
  type: string;
  name: string;
  description?: string;
  metadata?: Record<string, unknown>;
  criticality?: string | null;
  is_failure_path?: boolean;
  is_external_dependency?: boolean;
  is_critical?: boolean;
  project_id?: string | null;
  provenance?: Provenance;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relationship: string;
  provenance?: Provenance;
};

export type SystemFlowGraph = {
  project_id: string;
  root_node_id?: string | null;
  version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type Project = {
  id: string;
  name: string;
  description?: string;
  root_feature_id?: string | null;
  node_count?: number;
  edge_count?: number;
};

export type AgentTraceStep = {
  step: string;
  status: string;
  detail?: string;
  timestamp?: string;
};

export type HealthStatus = {
  status: string;
  openai: boolean;
  openai_configured?: boolean;
  openai_client_ready?: boolean;
  openai_model?: string | null;
  neo4j_enabled?: boolean;
  demo_fallback?: boolean;
  vector_store_mode?: string;
  graph_store_mode?: string;
  projects?: number;
  data_dir?: string;
  graph_store_path?: string;
  api_base_hint?: string;
};

export type EvidenceReference = {
  source_type: string;
  source_id?: string | null;
  source_title?: string | null;
  relevance?: string | null;
};

export type TestClassification = {
  nature?: string;
  behavior?: string[];
  quality_attributes?: string[];
  test_levels?: string[];
  suite_types?: string[];
  execution_status?: string;
  priority?: string;
  source?: string;
};

export type TestCase = {
  test_case_id: string;
  title: string;
  category: string;
  priority: string;
  risk: string;
  preconditions: string[];
  steps: string[];
  expected_result: string;
  testing_technique: string;
  graph_path: string[];
  graph_reasoning: string;
  source_references: string[];
  confidence: string;
  assumptions: string[];
  generation_method?: string | null;
  reasoning?: string | null;
  evidence?: EvidenceReference[];
  closes_gap_id?: string | null;
  closes_gap_title?: string | null;
  classification?: TestClassification | null;
  objective?: string | null;
  human_edited?: boolean;
};

export type CoverageGap = {
  gap_id: string;
  gap_type: string;
  title: string;
  description?: string;
  priority: string;
  risk: string;
  graph_path: string[];
  source_references?: string[];
  evidence?: EvidenceReference[];
  reason?: string;
  selected_for_regeneration?: boolean;
};

export type CoverageSnapshot = {
  total_paths: number;
  covered_paths: number;
  coverage_percentage: number;
  overall_coverage: number;
  branch_coverage: number;
  gaps: CoverageGap[];
  critical_gaps: string[];
  uncovered_branches: string[];
  calculation_notes: string[];
};

export type SectionStatus = {
  status: "success" | "empty" | "failed" | "skipped" | "partial_success" | string;
  count: number;
  error?: string | null;
  requested_format?: string | null;
  logical_test_count?: number | null;
  standard_count?: number | null;
  bdd_count?: number | null;
  validation_errors?: string[];
};

export type BDDStep = {
  keyword: string;
  text: string;
};

export type BDDScenario = {
  id: string;
  feature: string;
  feature_description?: string | null;
  feature_reference?: string | null;
  rule?: string | null;
  section?: string | null;
  scenario_name: string;
  scenario_type: string;
  tags: string[];
  background: BDDStep[];
  steps: BDDStep[];
  examples: Array<Record<string, string>>;
  priority: string;
  test_type: string;
  classification?: TestClassification | null;
  graph_path: string[];
  requirement_references: string[];
  bug_references: string[];
  evidence_references?: EvidenceReference[];
  assumptions: string[];
  generation_method?: string;
  source_test_id?: string | null;
  conversion_status?: string;
  conversion_notes?: string[];
  gherkin_text?: string;
};

export type GeneratedTestArtifact = {
  id: string;
  format: string;
  logical_test_id: string;
  standard_test_case?: TestCase | null;
  bdd_scenario?: BDDScenario | null;
  source_test_id?: string | null;
  graph_path: string[];
  evidence?: EvidenceReference[];
  priority: string;
  generation_method?: string | null;
};

export type TestValidityReview = {
  test_case_id: string;
  validity: string;
  validity_score: number;
  validity_reasons: string[];
  quality_issues: string[];
  evidence_checked: EvidenceReference[];
  graph_path_valid?: boolean | null;
  requirement_support: string;
  duplicate_status: string;
  missing_information: string[];
  correction_possible: boolean;
  corrections_applied: string[];
  suggested_corrections: string[];
  reviewed_test_case?: TestCase | null;
  generation_method?: string;
  supported_by_project?: boolean;
  supported_by_evidence?: boolean;
  contradiction_detected?: boolean;
  content_hash?: string | null;
};

export type AutomationFeasibilityReview = {
  test_case_id: string;
  automation_suitability: string;
  automation_score: number;
  automation_reasons: string[];
  non_automation_reasons: string[];
  recommended_layer: string;
  automation_priority: string;
  estimated_effort: string;
  confidence: string;
  prerequisites: string[];
  blockers: string[];
  test_data_requirements: string[];
  environment_requirements: string[];
  external_dependencies: string[];
  human_judgment_required: boolean;
  suggested_automation_scope: string;
  recommended_assertions: string[];
  recommended_framework_capabilities: string[];
  generation_method?: string;
};

export type ReviewedTestCase = {
  test_case: TestCase;
  original_test_case?: TestCase | null;
  validity_review: TestValidityReview;
  automation_review?: AutomationFeasibilityReview | null;
  final_review_status: string;
  human_override?: boolean;
  override_reason?: string | null;
  override_timestamp?: string | null;
  test_source?: string;
};

export type ValiditySummary = {
  total_tests: number;
  valid: number;
  invalid: number;
  needs_revision: number;
  insufficient_evidence: number;
};

export type AutomationSummary = {
  total_tests: number;
  valid_tests_evaluated: number;
  automate: number;
  automate_with_conditions: number;
  hybrid: number;
  manual: number;
  not_ready_for_automation: number;
  not_evaluated: number;
  high_priority_automation: number;
  effort_low: number;
  effort_medium: number;
  effort_high: number;
};

export type QACopilotResponse = {
  project_id: string;
  query: string;
  intent: string;
  risk_level: string;
  root_feature?: string | null;
  discovered_branches: string[];
  discovered_graph_paths: string[][];
  graph_coverage?: number | null;
  critical_gaps: string[];
  historical_bug_patterns: string[];
  test_cases: TestCase[];
  exploratory_missions: Array<{
    mission_id: string;
    title: string;
    charter: string;
    focus_areas: string[];
    graph_path: string[];
  }>;
  bug_reports: Array<{
    bug_id: string;
    title: string;
    severity: string;
    graph_path: string[];
    classification?: string;
    generation_method?: string;
  }>;
  regression_recommendations: Array<{
    test_case_id: string;
    title: string;
    reason: string;
    graph_path: string[];
    changed_node?: string | null;
    recommendation_id?: string;
    priority?: string;
    related_bug_references?: string[];
    generation_method?: string;
  }>;
  impact_analysis?: {
    changed_node: string;
    directly_impacted_nodes: string[];
    indirectly_impacted_nodes: string[];
    risk_level: string;
    reasoning_paths: string[];
  } | null;
  coverage?: {
    overall_coverage: number;
    branch_coverage: number;
    covered_branches: string[];
    uncovered_branches: string[];
    critical_gaps: string[];
    calculation_notes: string[];
  } | null;
  retrieval_plan?: {
    use_user_flow_graph: boolean;
    use_vector_rag: boolean;
    use_graph_rag: boolean;
    use_existing_tests: boolean;
    use_historical_bugs: boolean;
    use_external_search: boolean;
    reason: string;
  } | null;
  evidence: string[];
  confidence: string;
  assumptions: string[];
  critic_notes: string[];
  section_status?: Record<string, SectionStatus>;
  execution_trace: AgentTraceStep[];
  narrative: string;
  fused_context_summary?: {
    feature?: string | null;
    flow_paths?: number;
    semantic_hits?: number;
    existing_tests?: number;
    historical_bugs?: number;
    initial_tests?: number;
    targeted_tests?: number;
    regeneration_rounds?: number;
    graph_context_items?: number;
    vector_hits?: number;
  };
  initial_test_cases?: TestCase[];
  selected_coverage_gaps?: CoverageGap[];
  targeted_test_cases?: TestCase[];
  coverage_before?: CoverageSnapshot | null;
  coverage_after?: CoverageSnapshot | null;
  regeneration_rounds?: number;
  unresolved_gaps?: CoverageGap[];
  duplicates_removed?: number;
  generation_backend?: string | null;
  runtime_diagnostics?: Record<string, unknown>;
  model_routing?: {
    task_type?: string;
    base_model?: string;
    selected_model?: string;
    actual_model_used?: string | null;
    escalated?: boolean;
    escalation_reason?: string | null;
    fallback_used?: boolean;
    reviewer_triggered?: boolean;
    reviewer_reasons?: string[];
    complexity?: string;
    complexity_score?: number;
    routing_policy_version?: string;
    events?: Array<Record<string, unknown>>;
  };
  reviewed_test_cases?: ReviewedTestCase[];
  valid_tests?: TestCase[];
  invalid_tests?: TestCase[];
  needs_revision_tests?: TestCase[];
  insufficient_evidence_tests?: TestCase[];
  automation_candidates?: TestCase[];
  manual_tests?: TestCase[];
  hybrid_tests?: TestCase[];
  conditional_automation_tests?: TestCase[];
  not_evaluated_tests?: TestCase[];
  validity_summary?: ValiditySummary | null;
  automation_summary?: AutomationSummary | null;
  test_output_format?: string;
  bdd_scenarios?: BDDScenario[];
  generated_test_artifacts?: GeneratedTestArtifact[];
  category_counts?: Record<string, number>;
  test_classification_summary?: Record<string, unknown>;
  feature_test_specifications?: Array<Record<string, unknown>>;
  coverage_obligations?: Array<Record<string, unknown>>;
  obligation_coverage?: Array<Record<string, unknown>>;
  category_coverage?: Array<{
    category: string;
    required_obligations: number;
    covered_obligations: number;
    coverage_percentage: number;
    missing_obligations?: string[];
    applicability?: string;
  }>;
  iteration_history?: Array<{
    iteration: number;
    test_count: number;
    modeled_coverage_pct: number;
    mandatory_total: number;
    mandatory_covered: number;
    invalid_count: number;
    needs_revision_count: number;
    tests_created?: number;
    tests_revised?: number;
    tests_retired?: number;
    open_mandatory_obligations?: string[];
    findings_count?: number;
    message?: string;
  }>;
  convergence_report?: {
    status: string;
    iterations_completed: number;
    initial_test_count: number;
    final_test_count: number;
    initial_modeled_coverage: number;
    final_modeled_coverage: number;
    mandatory_obligations_total: number;
    mandatory_obligations_covered: number;
    invalid_before: number;
    invalid_after: number;
    needs_revision_before: number;
    needs_revision_after: number;
    tests_created: number;
    tests_revised: number;
    tests_retired: number;
    duplicates_removed: number;
    remaining_obligations: string[];
    remaining_findings: string[];
    blockers: string[];
    stop_reason: string;
    modeled_coverage_label?: string;
  } | null;
  final_suite_review?: Record<string, unknown> | null;
};

export type DashboardStats = {
  risk_level: string;
  graph_coverage: number;
  branch_coverage: number;
  test_case_count: number;
  critical_test_count: number;
  historical_bugs: number;
  impacted_components: number;
  coverage_gaps: string[];
  confidence: string;
  node_count: number;
  edge_count: number;
  uncovered_branches: string[];
  calculation_notes?: string[];
};

export type NodeInsight = {
  node: GraphNode;
  connected_features: string[];
  dependencies: string[];
  flows: string[];
  existing_tests: string[];
  historical_bugs: string[];
  risk: string;
  coverage?: number | null;
  incoming: Array<{ from: string; relationship: string; node_id: string }>;
  outgoing: Array<{ to: string; relationship: string; node_id: string }>;
};

export type AppView =
  | "home"
  | "copilot"
  | "flow"
  | "explorer"
  | "knowledge"
  | "results"
  | "tests"
  | "automation"
  | "exploratory"
  | "bugs"
  | "regression"
  | "coverage"
  | "trace"
  | "evidence";

export type AnalysisProgressEvent = {
  stage: string;
  message: string;
  meta?: {
    status?: string;
    completed_stages?: string[];
    elapsed_ms?: number;
    [key: string]: unknown;
  };
};

export type BDDExportScope =
  | "all_final_generated"
  | "valid_only"
  | "current_filtered"
  | "selected";

export type BDDExportOptions = {
  scope: BDDExportScope;
  test_ids?: string[];
  include_traceability_comments?: boolean;
  include_tags?: boolean;
  include_import_csv?: boolean;
  language?: string;
  strict?: boolean;
};

export type BDDExcludedTest = {
  test_id: string;
  title?: string;
  reason: string;
  suggested_correction?: string | null;
};

export type BDDExportPreview = {
  project_id: string;
  analysis_id: string;
  status: string;
  file_count: number;
  scenario_count: number;
  logical_test_count: number;
  excluded_tests: BDDExcludedTest[];
  warnings: string[];
  files: Array<{
    filename: string;
    feature_name: string;
    content: string;
    scenario_count: number;
    logical_test_ids: string[];
  }>;
  csv_preview?: string | null;
  steps_csv?: string | null;
  manifest: Record<string, unknown>;
};