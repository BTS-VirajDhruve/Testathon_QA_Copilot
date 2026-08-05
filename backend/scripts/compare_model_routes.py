"""Optional offline comparison harness for model-route fixtures (no live API calls).

Usage (from backend/):

    uv run python -m scripts.compare_model_routes

Compares schema completeness / coverage signals across saved fixture payloads.
Does not invent subjective quality scores.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models.enums import LLMTaskType
from app.services.model_router import (
    DEFAULT_TASK_MODEL_MAP,
    ModelRoutingContext,
    assess_requirement_complexity,
    get_model_router,
)

FIXTURES = [
    {
        "name": "simple_qa_documentation",
        "task": LLMTaskType.QA_DOCUMENTATION,
        "context": ModelRoutingContext(input_token_estimate=120, graph_path_count=1),
    },
    {
        "name": "regression_selection",
        "task": LLMTaskType.REGRESSION_SELECTION,
        "context": ModelRoutingContext(input_token_estimate=200, graph_path_count=4),
    },
    {
        "name": "normal_test_case_generation",
        "task": LLMTaskType.TEST_CASE_GENERATION,
        "context": ModelRoutingContext(input_token_estimate=400, graph_path_count=5),
    },
    {
        "name": "complex_test_case_generation",
        "task": LLMTaskType.TEST_CASE_GENERATION,
        "context": ModelRoutingContext(
            input_token_estimate=3200,
            graph_path_count=16,
            retrieved_document_count=9,
            security_sensitive=True,
            financial_impact=True,
        ),
    },
    {
        "name": "exploratory_security",
        "task": LLMTaskType.EXPLORATORY_SCENARIO,
        "context": ModelRoutingContext(security_sensitive=True, graph_path_count=8),
    },
]


def main() -> None:
    router = get_model_router()
    rows = []
    for fixture in FIXTURES:
        ctx: ModelRoutingContext = fixture["context"]
        ctx.task_type = fixture["task"]
        assessment = assess_requirement_complexity(ctx)
        ctx.requirement_complexity = assessment.category
        selection = router.resolve_model(fixture["task"], ctx)
        rows.append(
            {
                "fixture": fixture["name"],
                "task_type": fixture["task"].value,
                "map_default": DEFAULT_TASK_MODEL_MAP[fixture["task"]],
                "base_model": selection.base_model,
                "selected_model": selection.selected_model,
                "escalated": selection.escalated,
                "escalation_reason": selection.escalation_reason,
                "complexity": assessment.category.value,
                "complexity_score": assessment.score,
                "signals": assessment.signals,
            }
        )
    out = Path(__file__).resolve().parent / "compare_model_routes_output.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
