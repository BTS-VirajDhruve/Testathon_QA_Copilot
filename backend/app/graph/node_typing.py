"""Shared node-type / relationship inference for flow graphs."""

from __future__ import annotations

from app.models.enums import NodeType, RelationshipType
from app.models.schemas import GraphNode

TYPE_HINTS: dict[str, NodeType] = {
    "email": NodeType.AUTHENTICATION_METHOD,
    "password": NodeType.AUTHENTICATION_METHOD,
    "oauth": NodeType.AUTHENTICATION_METHOD,
    "google": NodeType.AUTHENTICATION_METHOD,
    "sso": NodeType.AUTHENTICATION_METHOD,
    "saml": NodeType.AUTHENTICATION_METHOD,
    "oidc": NodeType.AUTHENTICATION_METHOD,
    "mfa": NodeType.SUB_FEATURE,
    "forgot": NodeType.ALTERNATE_FLOW,
    "lockout": NodeType.FAILURE_PATH,
    "failure": NodeType.FAILURE_PATH,
    "timeout": NodeType.FAILURE_PATH,
    "decline": NodeType.FAILURE_PATH,
    "callback": NodeType.USER_FLOW,
    "consent": NodeType.USER_FLOW,
    "session": NodeType.STATE,
    "provider": NodeType.THIRD_PARTY_PROVIDER,
    "gateway": NodeType.EXTERNAL_DEPENDENCY,
    "api": NodeType.API,
    "database": NodeType.DATABASE,
    "db": NodeType.DATABASE,
    "service": NodeType.SERVICE,
    "validation": NodeType.VALIDATION,
    "rule": NodeType.BUSINESS_RULE,
}


def infer_node_type(name: str, explicit: NodeType | None = None, *, is_failure: bool = False) -> NodeType:
    if explicit:
        return explicit
    if is_failure:
        return NodeType.FAILURE_PATH
    lower = name.lower()
    for needle, ntype in TYPE_HINTS.items():
        if needle in lower:
            return ntype
    return NodeType.SUB_FEATURE


def rel_for_child(parent: GraphNode, child: GraphNode) -> RelationshipType:
    if child.type == NodeType.AUTHENTICATION_METHOD:
        return RelationshipType.HAS_AUTHENTICATION_METHOD
    if child.type == NodeType.FAILURE_PATH or child.is_failure_path:
        return RelationshipType.HAS_FAILURE_PATH
    if child.type == NodeType.ALTERNATE_FLOW:
        return RelationshipType.HAS_ALTERNATE_FLOW
    if child.type == NodeType.SUB_FEATURE:
        return RelationshipType.HAS_SUBFEATURE
    if child.type == NodeType.USER_FLOW:
        return RelationshipType.HAS_FLOW
    if child.type == NodeType.STATE:
        return RelationshipType.HAS_STATE
    if child.type == NodeType.BUSINESS_RULE:
        return RelationshipType.HAS_BUSINESS_RULE
    if child.type == NodeType.VALIDATION:
        return RelationshipType.HAS_VALIDATION
    if child.type in (NodeType.EXTERNAL_DEPENDENCY, NodeType.THIRD_PARTY_PROVIDER):
        return RelationshipType.DEPENDS_ON
    if child.type == NodeType.COMPONENT:
        return RelationshipType.IMPLEMENTED_BY
    if child.type == NodeType.SERVICE:
        return RelationshipType.CALLS
    if child.type == NodeType.API:
        return RelationshipType.EXPOSES
    return RelationshipType.HAS_CHILD
