"""Shared enums and constants for graph/QA domain."""

from __future__ import annotations

from enum import Enum


class NodeType(str, Enum):
    PROJECT = "Project"
    USER_JOURNEY = "UserJourney"
    FEATURE = "Feature"
    SUB_FEATURE = "SubFeature"
    PAGE = "Page"
    SCREEN = "Screen"
    USER_FLOW = "UserFlow"
    ACTION = "Action"
    AUTHENTICATION_METHOD = "AuthenticationMethod"
    COMPONENT = "Component"
    MODULE = "Module"
    SERVICE = "Service"
    API = "API"
    DATABASE = "Database"
    EXTERNAL_DEPENDENCY = "ExternalDependency"
    THIRD_PARTY_PROVIDER = "ThirdPartyProvider"
    BUSINESS_RULE = "BusinessRule"
    VALIDATION = "Validation"
    FAILURE_PATH = "FailurePath"
    ALTERNATE_FLOW = "AlternateFlow"
    STATE = "State"
    ROLE = "Role"
    PERMISSION = "Permission"
    NOTIFICATION = "Notification"
    TEST_CASE = "TestCase"
    TEST_SUITE = "TestSuite"
    BUG = "Bug"
    RISK = "Risk"
    TESTING_TECHNIQUE = "TestingTechnique"
    QA_DOCUMENT = "QA_Document"
    EXTERNAL_SOURCE = "ExternalSource"
    REQUIREMENT = "Requirement"
    EXPLORATORY_MISSION = "ExploratoryMission"


class RelationshipType(str, Enum):
    HAS_USER_JOURNEY = "HAS_USER_JOURNEY"
    HAS_ROOT_FEATURE = "HAS_ROOT_FEATURE"
    HAS_FEATURE = "HAS_FEATURE"
    HAS_SUBFEATURE = "HAS_SUBFEATURE"
    HAS_FLOW = "HAS_FLOW"
    HAS_AUTHENTICATION_METHOD = "HAS_AUTHENTICATION_METHOD"
    NEXT = "NEXT"
    IMPLEMENTED_BY = "IMPLEMENTED_BY"
    BELONGS_TO = "BELONGS_TO"
    EXPOSES = "EXPOSES"
    DEPENDS_ON = "DEPENDS_ON"
    USES = "USES"
    CALLS = "CALLS"
    HAS_ALTERNATE_FLOW = "HAS_ALTERNATE_FLOW"
    HAS_FAILURE_PATH = "HAS_FAILURE_PATH"
    HAS_BUSINESS_RULE = "HAS_BUSINESS_RULE"
    HAS_VALIDATION = "HAS_VALIDATION"
    HAS_STATE = "HAS_STATE"
    DESCRIBES = "DESCRIBES"
    COVERED_BY = "COVERED_BY"
    VALIDATES = "VALIDATES"
    COVERS = "COVERS"
    AFFECTS = "AFFECTS"
    REVEALS_RISK = "REVEALS_RISK"
    REQUIRES = "REQUIRES"
    MITIGATES = "MITIGATES"
    IMPACTS = "IMPACTS"
    HAS_EXPLORATORY_MISSION = "HAS_EXPLORATORY_MISSION"
    INFORMS = "INFORMS"
    HAS_CHILD = "HAS_CHILD"
    TRANSITIONS_TO = "TRANSITIONS_TO"
    RELATED_TO = "RELATED_TO"


class SourceType(str, Enum):
    USER_INPUT = "user_input"
    DOCUMENT = "document"
    LLM_INFERENCE = "llm_inference"
    EXTERNAL_SOURCE = "external_source"


class QAIntent(str, Enum):
    TEST_GENERATION = "test_generation"
    EXPLORATORY = "exploratory"
    BUG_REPORT = "bug_report"
    REGRESSION = "regression"
    REQUIREMENTS_ANALYSIS = "requirements_analysis"
    COVERAGE_GAP = "coverage_gap"
    IMPACT_ANALYSIS = "impact_analysis"
    DEFECT_PATTERN = "defect_pattern"
    DOCUMENTATION = "documentation"
    GENERAL_QA = "general_qa"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GapType(str, Enum):
    """Structured coverage-gap kinds used by prioritization / targeted regeneration."""

    GRAPH_PATH = "graph_path"
    BRANCH = "branch"
    NEGATIVE = "negative"
    FAILURE = "failure"
    BUG = "bug"
    REQUIREMENT = "requirement"
    RISK = "risk"
    ALTERNATE = "alternate"


class LLMTaskType(str, Enum):
    """What kind of LLM operation is being executed (distinct from user QAIntent)."""

    INTENT_CLASSIFICATION = "intent_classification"
    QA_DOCUMENTATION = "qa_documentation"
    REGRESSION_SELECTION = "regression_selection"
    BUG_REPORT = "bug_report"
    TEST_CASE_GENERATION = "test_case_generation"
    TARGETED_TEST_GENERATION = "targeted_test_generation"
    TEST_CASE_REVISION = "test_case_revision"
    MISSING_SCENARIO_GENERATION = "missing_scenario_generation"
    TEST_SUITE_REVIEW = "test_suite_review"
    REVIEWER_VERIFICATION = "reviewer_verification"
    EXPLORATORY_SCENARIO = "exploratory_scenario"
    REVIEWER_PASS = "reviewer_pass"
    GRAPH_EXTRACTION = "graph_extraction"
    ENTITY_EXTRACTION = "entity_extraction"
    OUTPUT_REPAIR = "output_repair"
    CRITIC_NOTES = "critic_notes"
    TEST_REVIEW_AUTOMATION = "test_review_automation"
    TEST_VALIDITY_REVIEW = "test_validity_review"
    AUTOMATION_FEASIBILITY_REVIEW = "automation_feasibility_review"
    BDD_EXPORT_CONVERSION = "bdd_export_conversion"


class TestValidity(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    NEEDS_REVISION = "needs_revision"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class TestReviewStatus(str, Enum):
    APPROVED = "approved"
    APPROVED_WITH_CHANGES = "approved_with_changes"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AutomationSuitability(str, Enum):
    AUTOMATE = "automate"
    AUTOMATE_WITH_CONDITIONS = "automate_with_conditions"
    MANUAL = "manual"
    HYBRID = "hybrid"
    NOT_READY_FOR_AUTOMATION = "not_ready_for_automation"
    NOT_EVALUATED = "not_evaluated"


class AutomationLayer(str, Enum):
    UI = "ui"
    API = "api"
    INTEGRATION = "integration"
    COMPONENT = "component"
    CONTRACT = "contract"
    DATABASE = "database"
    PERFORMANCE = "performance"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    VISUAL = "visual"
    MOBILE = "mobile"
    NONE = "none"
    UNKNOWN = "unknown"


class AutomationPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_RECOMMENDED = "not_recommended"


class AutomationEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class DuplicateRelation(str, Enum):
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    COMPLEMENTARY = "complementary"
    DISTINCT = "distinct"


class RequirementComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TestOutputFormat(str, Enum):
    STANDARD = "standard"
    BDD = "bdd"
    BOTH = "both"


class ObligationType(str, Enum):
    GRAPH_PATH = "graph_path"
    GRAPH_BRANCH = "graph_branch"
    POSITIVE_FLOW = "positive_flow"
    NEGATIVE_FLOW = "negative_flow"
    ALTERNATE_FLOW = "alternate_flow"
    FAILURE_PATH = "failure_path"
    BOUNDARY = "boundary"
    EQUIVALENCE_PARTITION = "equivalence_partition"
    STATE_TRANSITION = "state_transition"
    DECISION_RULE = "decision_rule"
    BUSINESS_RULE = "business_rule"
    VALIDATION = "validation"
    ROLE_PERMISSION = "role_permission"
    HISTORICAL_BUG_REGRESSION = "historical_bug_regression"
    REQUIREMENT = "requirement"
    EXTERNAL_DEPENDENCY = "external_dependency"
    INTEGRATION = "integration"
    API_CONTRACT = "api_contract"
    DATA_INTEGRITY = "data_integrity"
    RECOVERY = "recovery"
    RETRY = "retry"
    IDEMPOTENCY = "idempotency"
    CONCURRENCY = "concurrency"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    RESILIENCE = "resilience"
    COMPATIBILITY = "compatibility"
    LOCALIZATION = "localization"
    PRIVACY = "privacy"
    USABILITY = "usability"
    OBSERVABILITY = "observability"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ObligationStatus(str, Enum):
    OPEN = "open"
    COVERED = "covered"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RETIRED = "retired"


class ConvergenceStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    STAGNATED = "stagnated"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"
    DISABLED = "disabled"


class ReviewFindingType(str, Enum):
    MISSING_TITLE = "missing_title"
    VAGUE_TITLE = "vague_title"
    MISSING_PRECONDITION = "missing_precondition"
    MISSING_STEPS = "missing_steps"
    AMBIGUOUS_ACTION = "ambiguous_action"
    MISSING_EXPECTED_RESULT = "missing_expected_result"
    UNOBSERVABLE_EXPECTED_RESULT = "unobservable_expected_result"
    INVALID_GRAPH_PATH = "invalid_graph_path"
    UNSUPPORTED_BEHAVIOR = "unsupported_behavior"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_REQUIREMENT = "conflicting_requirement"
    WRONG_PROJECT = "wrong_project"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    OVERLY_BROAD_TEST = "overly_broad_test"
    MIXED_SCENARIOS = "mixed_scenarios"
    MISSING_NEGATIVE_SCENARIO = "missing_negative_scenario"
    MISSING_POSITIVE_SCENARIO = "missing_positive_scenario"
    MISSING_BOUNDARY_SCENARIO = "missing_boundary_scenario"
    MISSING_FAILURE_SCENARIO = "missing_failure_scenario"
    MISSING_RECOVERY_SCENARIO = "missing_recovery_scenario"
    MISSING_STATE_TRANSITION = "missing_state_transition"
    MISSING_ROLE_PERMISSION = "missing_role_permission"
    MISSING_SECURITY_SCENARIO = "missing_security_scenario"
    MISSING_ACCESSIBILITY_SCENARIO = "missing_accessibility_scenario"
    MISSING_PERFORMANCE_SCENARIO = "missing_performance_scenario"
    MISSING_CONCURRENCY_SCENARIO = "missing_concurrency_scenario"
    MISSING_BUG_REGRESSION = "missing_bug_regression"
    INVALID_BDD = "invalid_bdd"
    WEAK_TEST_DATA = "weak_test_data"
    INCORRECT_PRIORITY = "incorrect_priority"
    INCOMPLETE_CLASSIFICATION = "incomplete_classification"
    NEEDS_REVISION = "needs_revision"
    INVALID_TEST = "invalid_test"


class GeneratorRevisionMode(str, Enum):
    CREATE = "create"
    REVISE = "revise"
    SPLIT = "split"
    MERGE = "merge"
    RETIRE = "retire"


class BDDScenarioType(str, Enum):
    SCENARIO = "scenario"
    SCENARIO_OUTLINE = "scenario_outline"


class BDDStepKeyword(str, Enum):
    GIVEN = "Given"
    WHEN = "When"
    THEN = "Then"
    AND = "And"
    BUT = "But"


class TestNature(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"


class TestBehavior(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    ALTERNATE = "alternate"
    EDGE_CASE = "edge_case"
    BOUNDARY = "boundary"
    FAILURE = "failure"
    RECOVERY = "recovery"
    STATE_TRANSITION = "state_transition"
    CONCURRENCY = "concurrency"
    DATA_VALIDATION = "data_validation"
    UNKNOWN = "unknown"


class QualityAttribute(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    USABILITY = "usability"
    RELIABILITY = "reliability"
    RESILIENCE = "resilience"
    COMPATIBILITY = "compatibility"
    LOCALIZATION = "localization"
    SCALABILITY = "scalability"
    MAINTAINABILITY = "maintainability"
    PRIVACY = "privacy"


class TestLevel(str, Enum):
    COMPONENT = "component"
    API = "api"
    CONTRACT = "contract"
    INTEGRATION = "integration"
    DATABASE = "database"
    UI = "ui"
    END_TO_END = "end_to_end"
    MOBILE = "mobile"
    SYSTEM = "system"


class SuiteType(str, Enum):
    SMOKE = "smoke"
    SANITY = "sanity"
    REGRESSION = "regression"
    RELEASE = "release"
    ACCEPTANCE = "acceptance"
    EXPLORATORY = "exploratory"
    CRITICAL_PATH = "critical_path"


class ExecutionStatus(str, Enum):
    AUTOMATED = "automated"
    RECOMMENDED_FOR_AUTOMATION = "recommended_for_automation"
    AUTOMATE_WITH_CONDITIONS = "automate_with_conditions"
    HYBRID = "hybrid"
    MANUAL = "manual"
    NOT_READY = "not_ready"
    NOT_REVIEWED = "not_reviewed"
    NOT_EVALUATED = "not_evaluated"


class TestSource(str, Enum):
    EXISTING = "existing"
    GENERATED = "generated"
    TARGETED = "targeted"
    MANUAL = "manual"
    IMPORTED = "imported"


# Default relationship for parent→child in user flow trees
DEFAULT_FLOW_RELATIONSHIP = RelationshipType.HAS_CHILD