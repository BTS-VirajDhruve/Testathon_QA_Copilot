"""Shared enums and constants for graph/QA domain."""

from __future__ import annotations

from enum import Enum


class NodeType(str, Enum):
    PROJECT = "Project"
    USER_JOURNEY = "UserJourney"
    FEATURE = "Feature"
    SUB_FEATURE = "SubFeature"
    USER_FLOW = "UserFlow"
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
    HAS_SUBFEATURE = "HAS_SUBFEATURE"
    HAS_FLOW = "HAS_FLOW"
    HAS_AUTHENTICATION_METHOD = "HAS_AUTHENTICATION_METHOD"
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


# Default relationship for parent→child in user flow trees
DEFAULT_FLOW_RELATIONSHIP = RelationshipType.HAS_CHILD