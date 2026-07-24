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
};

export type EvidenceReference = {
  source_type: string;
  source_id?: string | null;
  source_title?: string | null;
  relevance?: string | null;
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
  bug_reports: Array<{ bug_id: string; title: string; severity: string; graph_path: string[] }>;
  regression_recommendations: Array<{
    test_case_id: string;
    title: string;
    reason: string;
    graph_path: string[];
    changed_node?: string | null;
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
  execution_trace: AgentTraceStep[];
  narrative: string;
  initial_test_cases?: TestCase[];
  selected_coverage_gaps?: CoverageGap[];
  targeted_test_cases?: TestCase[];
  coverage_before?: CoverageSnapshot | null;
  coverage_after?: CoverageSnapshot | null;
  regeneration_rounds?: number;
  unresolved_gaps?: CoverageGap[];
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
  | "copilot"
  | "flow"
  | "explorer"
  | "knowledge"
  | "tests"
  | "exploratory"
  | "bugs"
  | "regression"
  | "coverage"
  | "trace"
  | "evidence";