"""Deterministic convergence policy for the refinement loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.models.enums import ConvergenceStatus, ObligationStatus, Priority
from app.models.schemas import (
    ConvergenceReport,
    CoverageObligation,
    RefinementIterationSnapshot,
    TestSuiteReview,
)


@dataclass
class RefinementLimits:
    max_iterations: int = 6
    max_tests: int = 250
    min_improvement_percent: float = 1.0
    stagnation_rounds: int = 2
    max_llm_calls: int = 12
    require_all_mandatory: bool = True
    require_zero_invalid: bool = True
    require_zero_needs_revision: bool = True

    @classmethod
    def from_settings(
        cls,
        *,
        max_iterations_override: int | None = None,
    ) -> "RefinementLimits":
        s = get_settings()
        return cls(
            max_iterations=max(
                1,
                min(
                    8,
                    int(
                        max_iterations_override
                        if max_iterations_override is not None
                        else s.test_refinement_max_iterations
                    ),
                ),
            ),
            max_tests=max(1, int(s.test_refinement_max_tests)),
            min_improvement_percent=float(s.test_refinement_min_improvement_percent),
            stagnation_rounds=max(1, int(s.test_refinement_stagnation_rounds)),
            max_llm_calls=max(0, int(s.test_refinement_max_llm_calls)),
            require_all_mandatory=bool(s.test_refinement_require_all_mandatory),
            require_zero_invalid=bool(s.test_refinement_require_zero_invalid),
            require_zero_needs_revision=bool(s.test_refinement_require_zero_needs_revision),
        )


@dataclass
class ConvergenceController:
    limits: RefinementLimits
    history: list[RefinementIterationSnapshot] = field(default_factory=list)
    llm_calls: int = 0

    def record(self, snap: RefinementIterationSnapshot) -> None:
        self.history.append(snap)

    def is_success(
        self,
        *,
        obligations: list[CoverageObligation],
        review: TestSuiteReview,
        modeled_coverage: float,
        invalid_count: int,
        needs_revision_count: int,
    ) -> bool:
        mandatory = [
            o
            for o in obligations
            if o.mandatory and o.status != ObligationStatus.INSUFFICIENT_EVIDENCE
        ]
        uncovered = [o for o in mandatory if o.status != ObligationStatus.COVERED]
        if self.limits.require_all_mandatory and uncovered:
            return False
        if modeled_coverage < 100.0 and mandatory:
            return False
        if self.limits.require_zero_invalid and invalid_count > 0:
            return False
        if self.limits.require_zero_needs_revision and needs_revision_count > 0:
            return False
        # Critical/high blocking findings
        high_findings = [
            f
            for f in review.per_test_findings
            if f.severity in (Priority.CRITICAL, Priority.HIGH) and f.status == "open"
        ]
        if high_findings:
            return False
        if review.duplicate_findings:
            return False
        if review.missing_scenario_findings:
            # only mandatory missing
            return False
        return True

    def should_stop(
        self,
        *,
        iteration: int,
        test_count: int,
        review: TestSuiteReview,
        modeled_coverage: float,
    ) -> tuple[bool, ConvergenceStatus, str]:
        if iteration >= self.limits.max_iterations:
            return True, ConvergenceStatus.LIMIT_REACHED, "maximum_iterations_reached"
        if test_count >= self.limits.max_tests:
            return True, ConvergenceStatus.LIMIT_REACHED, "maximum_test_count_reached"
        if self.llm_calls >= self.limits.max_llm_calls:
            return True, ConvergenceStatus.LIMIT_REACHED, "llm_call_budget_reached"

        if len(self.history) >= self.limits.stagnation_rounds + 1:
            recent = self.history[-(self.limits.stagnation_rounds + 1) :]
            improvements = [
                recent[i].modeled_coverage_pct - recent[i - 1].modeled_coverage_pct
                for i in range(1, len(recent))
            ]
            invalid_flat = all(
                recent[i].invalid_count >= recent[i - 1].invalid_count
                and recent[i].needs_revision_count >= recent[i - 1].needs_revision_count
                for i in range(1, len(recent))
            )
            if all(imp < self.limits.min_improvement_percent for imp in improvements) and invalid_flat:
                return True, ConvergenceStatus.STAGNATED, "no_measurable_improvement"

        # Same blocking finding signatures repeating
        if len(self.history) >= 2:
            if (
                self.history[-1].findings_count == self.history[-2].findings_count
                and self.history[-1].open_mandatory_obligations
                == self.history[-2].open_mandatory_obligations
                and self.history[-1].modeled_coverage_pct
                == self.history[-2].modeled_coverage_pct
            ):
                # one more chance handled by stagnation_rounds; soft signal only
                pass

        if review.convergence_recommendation == "blocked":
            return True, ConvergenceStatus.BLOCKED, "reviewer_blocked"

        return False, ConvergenceStatus.PARTIAL, ""

    def build_report(
        self,
        *,
        status: ConvergenceStatus,
        stop_reason: str,
        initial_test_count: int,
        final_test_count: int,
        initial_coverage: float,
        final_coverage: float,
        obligations: list[CoverageObligation],
        invalid_before: int,
        invalid_after: int,
        needs_before: int,
        needs_after: int,
        totals: dict[str, int],
        remaining_findings: list[str],
        blockers: list[str],
    ) -> ConvergenceReport:
        mandatory = [
            o
            for o in obligations
            if o.mandatory and o.status != ObligationStatus.INSUFFICIENT_EVIDENCE
        ]
        covered = [o for o in mandatory if o.status == ObligationStatus.COVERED]
        remaining = [
            o.obligation_id
            for o in mandatory
            if o.status != ObligationStatus.COVERED
        ]
        return ConvergenceReport(
            status=status,
            iterations_completed=len(self.history),
            initial_test_count=initial_test_count,
            final_test_count=final_test_count,
            initial_modeled_coverage=initial_coverage,
            final_modeled_coverage=final_coverage,
            mandatory_obligations_total=len(mandatory),
            mandatory_obligations_covered=len(covered),
            invalid_before=invalid_before,
            invalid_after=invalid_after,
            needs_revision_before=needs_before,
            needs_revision_after=needs_after,
            tests_created=totals.get("tests_created", 0),
            tests_revised=totals.get("tests_revised", 0),
            tests_split=totals.get("tests_split", 0),
            tests_merged=totals.get("tests_merged", 0),
            tests_retired=totals.get("tests_retired", 0),
            duplicates_removed=totals.get("duplicates_removed", 0),
            remaining_obligations=remaining,
            remaining_findings=remaining_findings,
            blockers=blockers,
            stop_reason=stop_reason,
            modeled_coverage_label="100% of modeled coverage obligations covered"
            if status == ConvergenceStatus.COMPLETE
            else "Modeled graph-and-requirement coverage",
        )
