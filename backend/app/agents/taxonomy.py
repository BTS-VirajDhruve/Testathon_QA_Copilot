"""Multi-axis test taxonomy normalization, tags, feature stories, and sections."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.models.enums import (
    AutomationSuitability,
    ExecutionStatus,
    Priority,
    QualityAttribute,
    SuiteType,
    TestBehavior,
    TestLevel,
    TestNature,
    TestSource,
)
from app.models.schemas import (
    FeatureTestSpecification,
    TestCase,
    TestClassification,
    UserStory,
)

# Stable Gherkin section order for export/UI grouping
SECTION_ORDER = [
    "FUNCTIONAL",
    "NEGATIVE",
    "EDGE AND BOUNDARY",
    "SECURITY",
    "PERFORMANCE",
    "ACCESSIBILITY",
    "RELIABILITY AND RECOVERY",
    "COMPATIBILITY",
    "CONCURRENCY",
    "DATA VALIDATION",
    "OTHER NON-FUNCTIONAL",
]


def _enum_val(v: Any) -> str:
    return str(v.value if hasattr(v, "value") else v).lower()


def infer_source(tc: TestCase) -> TestSource:
    method = (tc.generation_method or "").lower()
    if tc.human_edited or method == "manual":
        return TestSource.MANUAL
    if method == "critic" or tc.closes_gap_id:
        return TestSource.TARGETED
    if method in {"imported", "import"}:
        return TestSource.IMPORTED
    if method in {"existing", "seed"}:
        return TestSource.EXISTING
    return TestSource.GENERATED


def infer_nature(category: str, title: str = "") -> TestNature:
    blob = f"{category} {title}".lower()
    nf_keys = (
        "security",
        "performance",
        "accessibility",
        "usability",
        "reliability",
        "resilience",
        "compatibility",
        "localization",
        "scalability",
        "privacy",
        "non.functional",
        "non-functional",
        "non_functional",
    )
    if any(k in blob for k in nf_keys):
        return TestNature.NON_FUNCTIONAL
    return TestNature.FUNCTIONAL


def infer_behaviors(category: str, title: str = "") -> list[TestBehavior]:
    blob = f"{category} {title}".lower()
    found: list[TestBehavior] = []

    def add(b: TestBehavior) -> None:
        if b not in found:
            found.append(b)

    if any(k in blob for k in ("negative", "reject", "invalid", "denied", "blank", "empty name")):
        add(TestBehavior.NEGATIVE)
    if any(k in blob for k in ("boundary", "limit", "max ", "min ")):
        add(TestBehavior.BOUNDARY)
    if "edge" in blob:
        add(TestBehavior.EDGE_CASE)
    if any(k in blob for k in ("alternate", "alternative")):
        add(TestBehavior.ALTERNATE)
    if any(k in blob for k in ("failure", "fail path", "error path")):
        add(TestBehavior.FAILURE)
    if "recover" in blob:
        add(TestBehavior.RECOVERY)
    if any(k in blob for k in ("concurrent", "race", "stale", "conflict")):
        add(TestBehavior.CONCURRENCY)
    if any(k in blob for k in ("state transition", "reorder", "status")):
        add(TestBehavior.STATE_TRANSITION)
    if any(k in blob for k in ("validation", "validate", "required field")):
        add(TestBehavior.DATA_VALIDATION)
    if any(k in blob for k in ("positive", "successful", "happy", "valid ")) and TestBehavior.NEGATIVE not in found:
        add(TestBehavior.POSITIVE)
    if not found:
        if "negative" in (category or "").lower():
            add(TestBehavior.NEGATIVE)
        elif (category or "").lower() in {"functional", "regression", "smoke"}:
            add(TestBehavior.POSITIVE)
        else:
            add(TestBehavior.UNKNOWN)
    return found


def infer_quality_attributes(category: str, title: str = "") -> list[QualityAttribute]:
    blob = f"{category} {title}".lower()
    mapping = [
        (("security", "auth", "permission", "access denied"), QualityAttribute.SECURITY),
        (("performance", "latency", "throughput"), QualityAttribute.PERFORMANCE),
        (("accessibility", "a11y", "screen reader"), QualityAttribute.ACCESSIBILITY),
        (("usability",), QualityAttribute.USABILITY),
        (("reliability",), QualityAttribute.RELIABILITY),
        (("resilience", "failover"), QualityAttribute.RESILIENCE),
        (("compatibility", "browser"), QualityAttribute.COMPATIBILITY),
        (("localization", "i18n", "language"), QualityAttribute.LOCALIZATION),
        (("scalability",), QualityAttribute.SCALABILITY),
        (("privacy", "pii", "gdpr"), QualityAttribute.PRIVACY),
    ]
    out: list[QualityAttribute] = []
    for keys, attr in mapping:
        if any(k in blob for k in keys) and attr not in out:
            out.append(attr)
    return out


def infer_suite_types(category: str, priority: Priority | str) -> list[SuiteType]:
    suites: list[SuiteType] = [SuiteType.REGRESSION]
    cat = (category or "").lower()
    pri = _enum_val(priority)
    if "smoke" in cat or pri == "critical":
        suites.append(SuiteType.SMOKE)
    if "sanity" in cat:
        suites.append(SuiteType.SANITY)
    if "exploratory" in cat:
        suites.append(SuiteType.EXPLORATORY)
    if "acceptance" in cat:
        suites.append(SuiteType.ACCEPTANCE)
    if "release" in cat:
        suites.append(SuiteType.RELEASE)
    if pri in {"critical", "high"}:
        suites.append(SuiteType.CRITICAL_PATH)
    # dedupe preserve order
    seen: set[str] = set()
    out: list[SuiteType] = []
    for s in suites:
        if s.value not in seen:
            seen.add(s.value)
            out.append(s)
    return out


def execution_from_automation_suitability(suit: str | None) -> ExecutionStatus:
    s = (suit or "").lower()
    mapping = {
        "automate": ExecutionStatus.RECOMMENDED_FOR_AUTOMATION,
        "automate_with_conditions": ExecutionStatus.AUTOMATE_WITH_CONDITIONS,
        "hybrid": ExecutionStatus.HYBRID,
        "manual": ExecutionStatus.MANUAL,
        "not_ready_for_automation": ExecutionStatus.NOT_READY,
        "not_evaluated": ExecutionStatus.NOT_EVALUATED,
        "automated": ExecutionStatus.AUTOMATED,
    }
    return mapping.get(s, ExecutionStatus.NOT_REVIEWED)


def normalize_classification(
    tc: TestCase,
    *,
    automation_suitability: str | None = None,
    already_automated: bool = False,
) -> TestClassification:
    """Lazy-normalize taxonomy for old or partial records. Never invent automated."""
    if tc.classification is not None:
        cls = tc.classification.model_copy(deep=True)
        if already_automated:
            cls.execution_status = ExecutionStatus.AUTOMATED
        elif automation_suitability and cls.execution_status in {
            ExecutionStatus.NOT_REVIEWED,
            ExecutionStatus.NOT_EVALUATED,
        }:
            cls.execution_status = execution_from_automation_suitability(automation_suitability)
        return cls

    pri = tc.priority if isinstance(tc.priority, Priority) else Priority(_enum_val(tc.priority) or "medium")
    execution = ExecutionStatus.NOT_REVIEWED
    if already_automated:
        execution = ExecutionStatus.AUTOMATED
    elif automation_suitability:
        execution = execution_from_automation_suitability(automation_suitability)

    return TestClassification(
        nature=infer_nature(tc.category, tc.title),
        behavior=infer_behaviors(tc.category, tc.title),
        quality_attributes=infer_quality_attributes(tc.category, tc.title),
        test_levels=[],
        suite_types=infer_suite_types(tc.category, pri),
        execution_status=execution,
        priority=pri,
        source=infer_source(tc),
    )


def sync_legacy_category(classification: TestClassification) -> str:
    """Keep single category string coherent for older consumers."""
    if TestBehavior.NEGATIVE in classification.behavior:
        return "negative"
    if QualityAttribute.SECURITY in classification.quality_attributes:
        return "security"
    if SuiteType.EXPLORATORY in classification.suite_types:
        return "exploratory"
    if SuiteType.REGRESSION in classification.suite_types and classification.nature == TestNature.FUNCTIONAL:
        if TestBehavior.POSITIVE in classification.behavior:
            return "functional"
        return "regression"
    if classification.nature == TestNature.NON_FUNCTIONAL:
        if classification.quality_attributes:
            return classification.quality_attributes[0].value
        return "non_functional"
    return "functional"


def build_normalized_tags(
    classification: TestClassification,
    *,
    extra: list[str] | None = None,
) -> list[str]:
    tags: list[str] = []

    def add(raw: str) -> None:
        text = (raw or "").strip().lower().replace(" ", "-")
        if not text.startswith("@"):
            text = f"@{text}"
        text = re.sub(r"[^a-z0-9@\-_]+", "", text)
        if text in {"@", "@-"}:
            return
        if text not in tags:
            tags.append(text)

    add(f"@{classification.nature.value.replace('_', '-')}")
    for b in classification.behavior:
        if b != TestBehavior.UNKNOWN:
            add(f"@{b.value.replace('_', '-')}")
    for q in classification.quality_attributes:
        add(f"@{q.value}")
    for level in classification.test_levels:
        add(f"@{level.value.replace('_', '-')}")
    for suite in classification.suite_types:
        add(f"@{suite.value.replace('_', '-')}")
    add(f"@priority-{classification.priority.value}")

    exec_map = {
        ExecutionStatus.AUTOMATED: "@automated",
        ExecutionStatus.RECOMMENDED_FOR_AUTOMATION: "@automation-yes",
        ExecutionStatus.AUTOMATE_WITH_CONDITIONS: "@automation-partial",
        ExecutionStatus.HYBRID: "@automation-partial",
        ExecutionStatus.MANUAL: "@automation-no",
        ExecutionStatus.NOT_READY: "@automation-no",
        ExecutionStatus.NOT_REVIEWED: "@automation-yes",
        ExecutionStatus.NOT_EVALUATED: "@automation-no",
    }
    add(exec_map.get(classification.execution_status, "@automation-yes"))

    if classification.source == TestSource.TARGETED:
        add("@targeted")
    if classification.source == TestSource.MANUAL:
        add("@manual")

    for e in extra or []:
        add(e)
    return tags[:16]


def build_user_story(
    feature: str,
    *,
    actor: str | None = None,
    goal: str | None = None,
    business_value: str | None = None,
    role_hint: str | None = None,
) -> UserStory:
    """Structured As/Want/So — never fabricate ticket IDs."""
    clean = (feature or "the feature").split("[")[0].strip() or "the feature"
    inferred_actor = actor or role_hint
    if not inferred_actor:
        lower = clean.lower()
        if any(k in lower for k in ("admin", "editor", "studio", "builder", "author", "manage")):
            inferred_actor = "admin"
        else:
            inferred_actor = "user"
    return UserStory(
        actor=inferred_actor,
        goal=goal or f"to use {clean}",
        business_value=business_value or "I can complete related workflows correctly",
    )


def parse_feature_reference(feature: str) -> tuple[str, str | None]:
    """Split 'Name [TICKET]' when present; do not invent tickets."""
    m = re.match(r"^(.*?)\s*\[([^\]]+)\]\s*$", (feature or "").strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return (feature or "").strip(), None


def section_for_classification(classification: TestClassification) -> str:
    if TestBehavior.NEGATIVE in classification.behavior:
        return "NEGATIVE"
    if QualityAttribute.SECURITY in classification.quality_attributes:
        return "SECURITY"
    if QualityAttribute.PERFORMANCE in classification.quality_attributes:
        return "PERFORMANCE"
    if QualityAttribute.ACCESSIBILITY in classification.quality_attributes:
        return "ACCESSIBILITY"
    if QualityAttribute.COMPATIBILITY in classification.quality_attributes:
        return "COMPATIBILITY"
    if TestBehavior.CONCURRENCY in classification.behavior:
        return "CONCURRENCY"
    if TestBehavior.DATA_VALIDATION in classification.behavior and classification.nature == TestNature.FUNCTIONAL:
        if TestBehavior.NEGATIVE in classification.behavior:
            return "NEGATIVE"
    if any(
        b in classification.behavior
        for b in (TestBehavior.EDGE_CASE, TestBehavior.BOUNDARY)
    ):
        return "EDGE AND BOUNDARY"
    if any(
        b in classification.behavior for b in (TestBehavior.RECOVERY, TestBehavior.FAILURE)
    ) or QualityAttribute.RELIABILITY in classification.quality_attributes or QualityAttribute.RESILIENCE in classification.quality_attributes:
        return "RELIABILITY AND RECOVERY"
    if classification.nature == TestNature.NON_FUNCTIONAL:
        return "OTHER NON-FUNCTIONAL"
    return "FUNCTIONAL"


def ensure_test_classified(
    tc: TestCase,
    *,
    automation_suitability: str | None = None,
) -> TestCase:
    cls = normalize_classification(tc, automation_suitability=automation_suitability)
    return tc.model_copy(
        update={
            "classification": cls,
            "category": sync_legacy_category(cls),
            "priority": cls.priority,
        }
    )


def build_feature_specifications(
    test_cases: list[TestCase],
    *,
    feature_fallback: str | None = None,
    feature_reference: str | None = None,
    user_story: UserStory | None = None,
) -> list[FeatureTestSpecification]:
    groups: dict[str, list[TestCase]] = {}
    for tc in test_cases:
        name = feature_fallback or (tc.graph_path[0] if tc.graph_path else "Generated Feature")
        groups.setdefault(name, []).append(tc)

    specs: list[FeatureTestSpecification] = []
    for name, cases in groups.items():
        fname, fref = parse_feature_reference(name)
        ref = feature_reference or fref
        story = user_story or build_user_story(fname)
        specs.append(
            FeatureTestSpecification(
                feature_name=fname,
                feature_reference=ref,
                description=story.to_description() or None,
                user_story=story,
                scenario_ids=[c.test_case_id for c in cases],
            )
        )
    return specs


def category_counts(test_cases: list[TestCase]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    counts["all"] = len(test_cases)
    for tc in test_cases:
        cls = tc.classification or normalize_classification(tc)
        counts[cls.nature.value] += 1
        section = section_for_classification(cls)
        key = section.lower().replace(" ", "_")
        counts[key] += 1
        if TestBehavior.NEGATIVE in cls.behavior:
            counts["negative"] += 1
        if cls.execution_status == ExecutionStatus.RECOMMENDED_FOR_AUTOMATION:
            counts["recommended_for_automation"] += 1
        if cls.execution_status == ExecutionStatus.AUTOMATED:
            counts["automated"] += 1
        if cls.execution_status == ExecutionStatus.MANUAL:
            counts["manual"] += 1
        if QualityAttribute.SECURITY in cls.quality_attributes:
            counts["security"] += 1
        if SuiteType.REGRESSION in cls.suite_types:
            counts["regression"] += 1
    return dict(counts)


def classification_summary(test_cases: list[TestCase]) -> dict[str, Any]:
    return {
        "total": len(test_cases),
        "counts": category_counts(test_cases),
        "natures": dict(Counter(_enum_val((t.classification or normalize_classification(t)).nature) for t in test_cases)),
        "execution": dict(
            Counter(_enum_val((t.classification or normalize_classification(t)).execution_status) for t in test_cases)
        ),
    }
