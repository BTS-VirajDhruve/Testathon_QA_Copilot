"""Phase 4 + 11 — lightweight node-type classification with cache."""

from __future__ import annotations

import re
from collections.abc import Callable

from app.graph.nl.models import IntermediateNode, IntermediateTree
from app.graph.node_typing import TYPE_HINTS, infer_node_type
from app.models.enums import LLMTaskType, NodeType
from app.services.model_router import ModelRoutingContext
from app.services.openai_service import OpenAIService, get_openai_service

# Allowed classifier output types (subset requested by architecture).
CLASSIFIABLE_TYPES: dict[str, NodeType] = {
    "feature": NodeType.FEATURE,
    "subfeature": NodeType.SUB_FEATURE,
    "sub_feature": NodeType.SUB_FEATURE,
    "userflow": NodeType.USER_FLOW,
    "user_flow": NodeType.USER_FLOW,
    "validation": NodeType.VALIDATION,
    "failurepath": NodeType.FAILURE_PATH,
    "failure_path": NodeType.FAILURE_PATH,
    "externaldependency": NodeType.EXTERNAL_DEPENDENCY,
    "external_dependency": NodeType.EXTERNAL_DEPENDENCY,
    "businessrule": NodeType.BUSINESS_RULE,
    "business_rule": NodeType.BUSINESS_RULE,
    "state": NodeType.STATE,
    "api": NodeType.API,
    "service": NodeType.SERVICE,
    "database": NodeType.DATABASE,
    "alternateflow": NodeType.ALTERNATE_FLOW,
    "alternate_flow": NodeType.ALTERNATE_FLOW,
    "risk": NodeType.RISK,
    "authenticationmethod": NodeType.AUTHENTICATION_METHOD,
    "authentication_method": NodeType.AUTHENTICATION_METHOD,
    "component": NodeType.COMPONENT,
    "thirdpartyprovider": NodeType.THIRD_PARTY_PROVIDER,
}

DEFAULT_CONFIDENCE_THRESHOLD = 0.65
_CLASS_CACHE: dict[str, tuple[NodeType, float]] = {}

_RULE_PATTERNS: list[tuple[re.Pattern[str], NodeType, float]] = [
    (
        re.compile(r"\b(timeout|decline|lockout|failure|invalid|error|reject)\b", re.I),
        NodeType.FAILURE_PATH,
        0.92,
    ),
    (
        re.compile(r"\b(gateway|provider|external|third[- ]party|upi|oauth)\b", re.I),
        NodeType.EXTERNAL_DEPENDENCY,
        0.88,
    ),
    (
        re.compile(r"\b(validat|billing form|address)\b", re.I),
        NodeType.VALIDATION,
        0.82,
    ),
    (
        re.compile(r"\b(rule|promo|discount|gst|policy)\b", re.I),
        NodeType.BUSINESS_RULE,
        0.8,
    ),
    (
        re.compile(r"\b(session|logged\s*in|authenticated)\b", re.I),
        NodeType.STATE,
        0.85,
    ),
    (re.compile(r"\b(api|endpoint|rest|graphql)\b", re.I), NodeType.API, 0.9),
    (re.compile(r"\b(service|microservice)\b", re.I), NodeType.SERVICE, 0.88),
    (
        re.compile(r"\b(database|db|postgres|mongo|redis)\b", re.I),
        NodeType.DATABASE,
        0.9,
    ),
    (
        re.compile(r"\b(forgot|alternate|fallback)\b", re.I),
        NodeType.ALTERNATE_FLOW,
        0.8,
    ),
    (
        re.compile(r"\b(email|password|oauth|sso|saml|oidc|mfa)\b", re.I),
        NodeType.AUTHENTICATION_METHOD,
        0.85,
    ),
    (
        re.compile(
            r"\b(guest|registered|checkout|login|sign\s*in|payment|cart)\b", re.I
        ),
        NodeType.USER_FLOW,
        0.7,
    ),
]


ProgressCallback = Callable[[str, str, dict], None]


class NodeClassifier:
    """Rule-first classifier; LLM only for low-confidence nodes."""

    def __init__(
        self,
        openai: OpenAIService | None = None,
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        cache: dict[str, tuple[NodeType, float]] | None = None,
    ) -> None:
        self.openai = openai or get_openai_service()
        self.threshold = confidence_threshold
        self.cache = cache if cache is not None else _CLASS_CACHE

    def classify_tree(
        self,
        tree: IntermediateTree,
        *,
        project_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, int]:
        """Classify all nodes in-place. Returns stats."""
        nodes = [n for n in tree.all_nodes() if n is not tree.root]
        # Root is always Feature
        tree.root.type = NodeType.FEATURE
        tree.root.type_confidence = 1.0

        needs_llm: list[IntermediateNode] = []
        rule_hits = 0
        cache_hits = 0

        for node in nodes:
            key = _cache_key(node.name)
            if key in self.cache and node.type is None:
                ntype, conf = self.cache[key]
                node.type = ntype
                node.type_confidence = conf
                cache_hits += 1
                _apply_flags(node)
                continue

            ntype, conf = self.classify_rules(node)
            if node.type is None:
                node.type = ntype
                node.type_confidence = conf
            else:
                # Keep explicit type; bump confidence if rules agree
                node.type_confidence = max(
                    node.type_confidence,
                    conf if ntype == node.type else node.type_confidence,
                )

            if node.type_confidence >= self.threshold:
                rule_hits += 1
                self.cache[key] = (node.type, node.type_confidence)
                _apply_flags(node)
            else:
                needs_llm.append(node)

        llm_calls = 0
        if needs_llm:
            if on_progress:
                on_progress(
                    "classifying",
                    f"Classifying {len(needs_llm)} uncertain node(s)...",
                    {"uncertain": len(needs_llm)},
                )
            # Batch into chunks of ~20 to keep prompts small
            chunk_size = 20
            for i in range(0, len(needs_llm), chunk_size):
                chunk = needs_llm[i : i + chunk_size]
                mapping = self.classify_with_llm(chunk, project_id=project_id)
                llm_calls += 1
                for node in chunk:
                    mapped = mapping.get(node.name.strip().lower())
                    if mapped:
                        node.type, node.type_confidence = mapped
                    else:
                        # Final deterministic fallback
                        node.type = infer_node_type(
                            node.name,
                            None,
                            is_failure=node.is_failure_path,
                        )
                        node.type_confidence = max(node.type_confidence, 0.55)
                    self.cache[_cache_key(node.name)] = (
                        node.type,
                        node.type_confidence,
                    )
                    _apply_flags(node)

        return {
            "nodes": len(nodes),
            "rule_hits": rule_hits,
            "cache_hits": cache_hits,
            "llm_calls": llm_calls,
            "llm_nodes": len(needs_llm),
        }

    def classify_rules(self, node: IntermediateNode) -> tuple[NodeType, float]:
        if node.is_failure_path:
            return NodeType.FAILURE_PATH, 0.95
        if node.is_external_dependency:
            return NodeType.EXTERNAL_DEPENDENCY, 0.9

        name = node.name
        lower = name.lower()

        for pat, ntype, conf in _RULE_PATTERNS:
            if pat.search(name):
                return ntype, conf

        for needle, ntype in TYPE_HINTS.items():
            if needle in lower:
                return ntype, 0.78

        # Default soft SubFeature
        return NodeType.SUB_FEATURE, 0.4

    def classify_with_llm(
        self,
        nodes: list[IntermediateNode],
        *,
        project_id: str | None = None,
    ) -> dict[str, tuple[NodeType, float]]:
        if not nodes:
            return {}

        listing = "\n".join(f"- {n.name}" for n in nodes)
        system = (
            "Classify each software-flow node.\n"
            "Return ONLY a table with rows: Node Name | Node Type\n"
            "Allowed types: Feature, UserFlow, Validation, FailurePath, "
            "ExternalDependency, BusinessRule, State, API, Service, Database, "
            "AlternateFlow, Risk, SubFeature, AuthenticationMethod.\n"
            "Do not generate JSON.\n"
            "Do not generate IDs.\n"
            "Do not create relationships.\n"
            "No explanations."
        )
        user = f"Classify each node.\n\n{listing}"

        # Prefer plain chat (table) — also works with demo fallback via _demo_classify
        raw = self.openai.chat(
            system,
            user,
            temperature=0.0,
            json_mode=False,
            task_type=LLMTaskType.GRAPH_EXTRACTION,
            routing_context=ModelRoutingContext(
                project_id=project_id,
                task_type=LLMTaskType.GRAPH_EXTRACTION,
                query=f"classify {len(nodes)} nodes",
            ),
        )
        return parse_classification_table(raw)


def parse_classification_table(raw: str) -> dict[str, tuple[NodeType, float]]:
    """Parse 'Node | Type' lines from LLM (or demo) output."""
    out: dict[str, tuple[NodeType, float]] = {}
    if not raw:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("node"):
            continue
        # Strip markdown pipes / bullets
        line = line.lstrip("-* ").strip()
        if "|" not in line:
            # "Name: Type" or "Name — Type"
            m = re.match(r"^(.+?)\s*[:=\-–—]\s*([A-Za-z_]+)\s*$", line)
            if not m:
                continue
            name, typ = m.group(1), m.group(2)
        else:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 2:
                continue
            name, typ = parts[0], parts[1]
        name = name.strip().strip("`* ")
        ntype = _parse_type(typ)
        if name and ntype:
            out[name.lower()] = (ntype, 0.75)
    return out


def _parse_type(raw: str) -> NodeType | None:
    key = re.sub(r"[^a-z0-9]+", "", raw.strip().lower())
    if key in CLASSIFIABLE_TYPES:
        return CLASSIFIABLE_TYPES[key]
    # Try enum values
    for nt in NodeType:
        if re.sub(r"[^a-z0-9]+", "", nt.value.lower()) == key:
            return nt
    return None


def _cache_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _apply_flags(node: IntermediateNode) -> None:
    if node.type == NodeType.FAILURE_PATH:
        node.is_failure_path = True
    if node.type in (NodeType.EXTERNAL_DEPENDENCY, NodeType.THIRD_PARTY_PROVIDER):
        node.is_external_dependency = True


def clear_classification_cache() -> None:
    _CLASS_CACHE.clear()
