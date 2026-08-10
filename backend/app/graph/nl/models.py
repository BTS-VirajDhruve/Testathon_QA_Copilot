"""Intermediate tree models for NL → graph (no IDs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import NodeType, Priority


@dataclass
class IntermediateNode:
    """Hierarchy node before deterministic ID / edge assignment."""

    name: str
    type: NodeType | None = None
    description: str = ""
    children: list[IntermediateNode] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    criticality: Priority | None = None
    is_failure_path: bool = False
    is_external_dependency: bool = False
    is_critical: bool = False
    type_confidence: float = 0.0

    def walk(self) -> list[IntermediateNode]:
        out = [self]
        for child in self.children:
            out.extend(child.walk())
        return out

    def find_by_name(self, name: str) -> IntermediateNode | None:
        target = name.strip().lower()
        for node in self.walk():
            if node.name.strip().lower() == target:
                return node
        # Soft prefix match only (avoid "Checkout" matching "guest checkout")
        for node in self.walk():
            n = node.name.strip().lower()
            shorter, longer = (target, n) if len(target) <= len(n) else (n, target)
            if (
                len(shorter) >= 4
                and longer.startswith(shorter)
                and (len(longer) == len(shorter) or longer[len(shorter)] in " \t+-/(:|")
            ):
                return node
        return None


@dataclass
class IntermediateTree:
    root: IntermediateNode
    description: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    def all_nodes(self) -> list[IntermediateNode]:
        return self.root.walk()


@dataclass
class PreprocessResult:
    text: str
    lines: list[str]
    paragraph_count: int = 0
    heading_count: int = 0
    bullet_depth: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
