"""Orchestrate NL → preprocess → parse → classify → NestedFlowImport."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.graph.nl.builder import nested_import_stats, tree_to_nested_import
from app.graph.nl.classifier import NodeClassifier
from app.graph.nl.parser import parse_to_tree
from app.graph.nl.preprocessor import normalize_text
from app.models.schemas import NestedFlowImport
from app.services.openai_service import get_openai_service


@dataclass
class ProgressEvent:
    stage: str
    message: str
    meta: dict[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class NLPipelineResult:
    nested: NestedFlowImport
    stats: dict[str, Any]
    inferred: bool
    confidence: float


class NLGraphPipeline:
    """Fast, deterministic NL extraction with optional lightweight classification."""

    def __init__(self, classifier: NodeClassifier | None = None) -> None:
        self.classifier = classifier or NodeClassifier(openai=get_openai_service())

    def run(
        self,
        text: str,
        *,
        project_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> NLPipelineResult:
        def emit(stage: str, message: str, **meta: Any) -> None:
            if on_progress:
                on_progress(ProgressEvent(stage=stage, message=message, meta=meta))

        emit("reading", "Reading input...")
        pre = normalize_text(text)
        emit(
            "reading",
            "Input normalized.",
            paragraphs=pre.paragraph_count,
            bullet_depth=pre.bullet_depth,
        )

        emit("hierarchy", "Building hierarchy...")
        tree = parse_to_tree(pre)
        emit(
            "hierarchy",
            "Hierarchy built.",
            nodes=len(tree.all_nodes()),
            parser=tree.stats.get("parser"),
        )

        emit("classifying", "Classifying nodes...")
        class_stats = self.classifier.classify_tree(
            tree,
            project_id=project_id,
            on_progress=lambda stage, msg, meta: emit(stage, msg, **meta),
        )
        emit("classifying", "Classification complete.", **class_stats)

        emit("generating", "Generating graph...")
        nested = tree_to_nested_import(tree)
        stats = {
            "preprocess": pre.stats,
            "parser": tree.stats,
            "classification": class_stats,
            "nested": nested_import_stats(nested),
            "llm_calls": class_stats.get("llm_calls", 0),
        }

        llm_calls = int(class_stats.get("llm_calls", 0))
        inferred = llm_calls > 0 or any(
            n.type_confidence < 0.75 for n in tree.all_nodes() if n is not tree.root
        )
        # Confidence: high when no LLM and good rule coverage
        if llm_calls == 0 and class_stats.get("rule_hits", 0) >= max(1, class_stats.get("nodes", 1) * 0.6):
            confidence = 0.9
        elif llm_calls == 0:
            confidence = 0.75
        else:
            confidence = 0.65

        emit("generating", "Graph structure ready.", **stats["nested"])
        return NLPipelineResult(
            nested=nested,
            stats=stats,
            inferred=inferred,
            confidence=confidence,
        )


def run_nl_to_nested_import(
    text: str,
    *,
    project_id: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> NLPipelineResult:
    return NLGraphPipeline().run(text, project_id=project_id, on_progress=on_progress)
