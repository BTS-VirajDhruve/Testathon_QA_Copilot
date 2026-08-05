"""Coverage-closure package: obligations, matching, review, revision, convergence."""

from app.agents.coverage_closure.convergence import ConvergenceController, RefinementLimits
from app.agents.coverage_closure.loop import RefinementLoopResult, run_refinement_loop
from app.agents.coverage_closure.matching import evaluate_obligation_coverage, match_test_to_obligation
from app.agents.coverage_closure.obligations import build_coverage_obligations, category_coverage_summary
from app.agents.coverage_closure.revision import apply_revision_plan
from app.agents.coverage_closure.suite_review import build_suite_review

__all__ = [
    "ConvergenceController",
    "RefinementLimits",
    "RefinementLoopResult",
    "apply_revision_plan",
    "build_coverage_obligations",
    "build_suite_review",
    "category_coverage_summary",
    "evaluate_obligation_coverage",
    "match_test_to_obligation",
    "run_refinement_loop",
]
