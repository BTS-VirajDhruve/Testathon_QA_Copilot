"""Deterministic test-case deduplication for critic-targeted regeneration."""

from __future__ import annotations

import re
from typing import Any

from app.models.schemas import TestCase

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s→\-]", re.UNICODE)


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalize_path(path: list[str] | None) -> tuple[str, ...]:
    return tuple(normalize_text(p) for p in (path or []) if normalize_text(p))


def normalize_steps(steps: list[str] | None) -> tuple[str, ...]:
    return tuple(normalize_text(s) for s in (steps or []) if normalize_text(s))


def _fingerprint(case: TestCase | dict[str, Any]) -> tuple[Any, ...]:
    if isinstance(case, TestCase):
        title = case.title
        steps = case.steps
        expected = case.expected_result
        path = case.graph_path
    else:
        title = case.get("title") or ""
        steps = case.get("steps") or []
        expected = case.get("expected_result") or ""
        path = case.get("graph_path") or []
    return (
        normalize_text(title),
        normalize_steps(steps),
        normalize_text(expected),
        normalize_path(path),
    )


def is_duplicate(
    candidate: TestCase | dict[str, Any],
    existing: list[TestCase] | list[dict[str, Any]] | list[Any],
) -> bool:
    """True when title+steps+expected+graph_path all match after normalization.

    Similar titles alone do not count as duplicates — distinct step/path bodies remain.
    """
    cand_fp = _fingerprint(candidate)
    cand_title, cand_steps, cand_expected, cand_path = cand_fp
    if not cand_title and not cand_steps:
        return False

    for other in existing:
        o_title, o_steps, o_expected, o_path = _fingerprint(other)
        # Exact semantic fingerprint match
        if cand_fp == (o_title, o_steps, o_expected, o_path):
            return True
        # Strong overlap: same path + same expected + same steps (title may differ)
        if cand_path and cand_path == o_path and cand_steps and cand_steps == o_steps:
            if cand_expected == o_expected or not cand_expected or not o_expected:
                return True
        # Same normalized title AND same graph path (steps may be paraphrased)
        if cand_title and cand_title == o_title and cand_path and cand_path == o_path:
            return True
    return False


def deduplicate_tests(
    candidates: list[TestCase],
    against: list[TestCase] | None = None,
) -> list[TestCase]:
    """Return candidates that are not duplicates of `against` or earlier candidates."""
    kept: list[TestCase] = []
    baseline: list[Any] = list(against or [])
    for case in candidates:
        if is_duplicate(case, baseline + kept):
            continue
        kept.append(case)
    return kept
