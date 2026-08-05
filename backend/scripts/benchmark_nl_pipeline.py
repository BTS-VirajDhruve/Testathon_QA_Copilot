"""
Benchmark: legacy LLM-JSON graph extraction vs new deterministic NL pipeline.

Usage (from backend/):
  uv run python -m scripts.benchmark_nl_pipeline
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.graph.nl.classifier import clear_classification_cache
from app.graph.nl.pipeline import NLGraphPipeline
from app.services.openai_service import get_openai_service

SAMPLES = {
    "simple": (
        "Checkout supports guest checkout, registered user, payment, and address validation."
    ),
    "medium": (
        "Sign In supports email password, Google OAuth, enterprise SSO, "
        "and self-registration. Email login supports MFA and forgot password. "
        "Account lockout and provider failure are failure paths."
    ),
}


def _legacy_llm_json(text: str) -> dict[str, Any]:
    """Simulate old architecture: one large graph-generation JSON prompt."""
    openai = get_openai_service()
    system = (
        "You extract software system flow graphs for QA. "
        "Return JSON with keys: root, description, branches. "
        "Each branch: name, type (optional), is_failure_path, children[], inferred. "
        "Do NOT invent unsupported system behavior. Mark inferred=true when guessing."
    )
    user = f"Extract a system flow graph from this description:\n\n{text}"
    return openai.chat_json(system, user)


def _count_branches(branches: list[Any]) -> int:
    total = 0
    for b in branches:
        total += 1
        kids = b.get("children", []) if isinstance(b, dict) else getattr(b, "children", [])
        if kids:
            normalized = []
            for k in kids:
                if isinstance(k, str):
                    normalized.append({"name": k, "children": []})
                elif isinstance(k, dict):
                    normalized.append(k)
                else:
                    normalized.append(k.model_dump() if hasattr(k, "model_dump") else {"name": str(k), "children": []})
            total += _count_branches(normalized)
    return total


def run_benchmark() -> dict[str, Any]:
    clear_classification_cache()
    pipe = NLGraphPipeline()
    report: dict[str, Any] = {"samples": {}}

    for name, text in SAMPLES.items():
        # Legacy
        t0 = time.perf_counter()
        legacy = _legacy_llm_json(text)
        legacy_ms = (time.perf_counter() - t0) * 1000
        legacy_nodes = 1 + _count_branches(legacy.get("branches") or [])

        # New
        clear_classification_cache()
        t1 = time.perf_counter()
        result = pipe.run(text, project_id=f"bench-{name}")
        new_ms = (time.perf_counter() - t1) * 1000
        new_nodes = 1 + result.stats["nested"]["branch_nodes"]

        report["samples"][name] = {
            "legacy": {
                "latency_ms": round(legacy_ms, 2),
                "llm_calls": 1,
                "nodes": legacy_nodes,
                "root": legacy.get("root"),
            },
            "new": {
                "latency_ms": round(new_ms, 2),
                "llm_calls": result.stats.get("llm_calls", 0),
                "nodes": new_nodes,
                "root": result.nested.root,
                "parser": result.stats.get("parser", {}).get("parser"),
            },
            "latency_improvement_ms": round(legacy_ms - new_ms, 2),
            "llm_token_proxy_reduction": {
                "legacy_full_graph_prompt": True,
                "new_classification_only_calls": result.stats.get("llm_calls", 0),
                "estimated_prompt_reduction": (
                    "100%" if result.stats.get("llm_calls", 0) == 0 else "~70-90% (classify vs full JSON)"
                ),
            },
        }

    # Ecommerce sample if present
    ecommerce = Path(__file__).resolve().parents[2] / "sample_data" / "ecommerce" / "ecommerce_natural_language.txt"
    if ecommerce.exists():
        text = ecommerce.read_text(encoding="utf-8")
        clear_classification_cache()
        t0 = time.perf_counter()
        result = pipe.run(text, project_id="bench-ecom")
        new_ms = (time.perf_counter() - t0) * 1000
        report["samples"]["ecommerce"] = {
            "new": {
                "latency_ms": round(new_ms, 2),
                "llm_calls": result.stats.get("llm_calls", 0),
                "nodes": 1 + result.stats["nested"]["branch_nodes"],
                "root": result.nested.root,
                "top_branches": [b.name for b in result.nested.branches],
            }
        }

    return report


def main() -> None:
    report = run_benchmark()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
