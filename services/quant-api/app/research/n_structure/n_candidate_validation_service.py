from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from app.research.common.candidate_validation_schedule import (
    CandidateValidationIdentityError,
    CandidateValidationRequest,
    CandidateValidationSourceError,
    CandidateValidationWindowError,
    build_rolling_validation_windows,
    prospective_window,
)
from app.research.n_structure.n_candidate_validation import (
    NCandidateWindowKind,
    NCandidateWindowResult,
    NProspectiveOosResult,
    NProspectiveOosStatus,
    NRollingCandidateFold,
    NStructureCandidateValidationReport,
    project_n_structure_window,
    summarize_n_rolling_stability,
)
from .n_candidate_validation_policy import (
    NCandidateManifest,
    NCandidateValidationProtocol,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureResearchResult,
)


class _NStructureResearchRunner(Protocol):
    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult: ...


class NStructureCandidateValidationService:
    """Project frozen N metrics from the MDS-only N research service."""

    def __init__(
        self,
        n_structure_research: _NStructureResearchRunner,
        *,
        manifest: NCandidateManifest,
        protocol: NCandidateValidationProtocol,
    ) -> None:
        if not isinstance(manifest, NCandidateManifest) or not isinstance(
            protocol, NCandidateValidationProtocol
        ):
            raise TypeError("manifest and protocol must use N Candidate contracts")
        self._n_structure_research = n_structure_research
        self._manifest = manifest
        self._protocol = protocol

    def run(
        self,
        request: CandidateValidationRequest,
    ) -> NStructureCandidateValidationReport:
        if not isinstance(request, CandidateValidationRequest):
            raise TypeError("request must be CandidateValidationRequest")
        if (
            request.candidate_id != self._manifest.candidate_id
            or request.protocol_id != self._protocol.protocol_id
        ):
            raise CandidateValidationIdentityError()
        if request.through < self._protocol.retrospective_through:
            raise CandidateValidationWindowError()

        retrospective = self._window(
            window_id="retrospective",
            window_kind=NCandidateWindowKind.RETROSPECTIVE,
            since=self._protocol.retrospective_since,
            through=self._protocol.retrospective_through,
            symbol=request.symbol,
        )
        folds = self._rolling_folds(request.symbol)
        prospective = self._prospective(request.symbol, request.through)
        quality_flags = self._quality_flags(retrospective, folds, prospective)
        return NStructureCandidateValidationReport(
            schema_version=1,
            candidate_id=self._manifest.candidate_id,
            policy_id=self._manifest.policy_id,
            formula_version=self._manifest.formula_version,
            protocol_id=self._protocol.protocol_id,
            research_only=True,
            symbol=request.symbol,
            retrospective=retrospective,
            rolling_folds=folds,
            rolling_stability=summarize_n_rolling_stability(folds),
            prospective_oos=prospective,
            quality_flags=quality_flags,
        )

    def _rolling_folds(self, symbol: str) -> tuple[NRollingCandidateFold, ...]:
        folds: list[NRollingCandidateFold] = []
        windows = build_rolling_validation_windows(
            reference_months=self._protocol.reference_months,
            test_months=self._protocol.test_months,
            step_months=self._protocol.step_months,
            first_test_since=self._protocol.first_test_since,
            last_test_through=self._protocol.last_test_through,
        )
        for window in windows:
            folds.append(
                NRollingCandidateFold(
                    fold_id=window.fold_id,
                    reference=self._window(
                        window_id=f"{window.fold_id}_reference",
                        window_kind=NCandidateWindowKind.ROLLING_REFERENCE,
                        since=window.reference_since,
                        through=window.reference_through,
                        symbol=symbol,
                    ),
                    test=self._window(
                        window_id=f"{window.fold_id}_test",
                        window_kind=NCandidateWindowKind.ROLLING_TEST,
                        since=window.test_since,
                        through=window.test_through,
                        symbol=symbol,
                    ),
                )
            )
        return tuple(folds)

    def _prospective(self, symbol: str, through: date) -> NProspectiveOosResult:
        first_day = self._protocol.prospective_oos_first_trading_day
        window = prospective_window(through=through, first_trading_day=first_day)
        if window is None:
            return NProspectiveOosResult(
                status=NProspectiveOosStatus.PENDING,
                first_trading_day=first_day,
                through=through,
                result=None,
            )
        since, prospective_through = window
        result = self._window(
            window_id="prospective_oos",
            window_kind=NCandidateWindowKind.PROSPECTIVE_OOS,
            since=since,
            through=prospective_through,
            symbol=symbol,
        )
        return NProspectiveOosResult(
            status=NProspectiveOosStatus.EVALUATED,
            first_trading_day=first_day,
            through=through,
            result=result,
        )

    def _window(
        self,
        *,
        window_id: str,
        window_kind: NCandidateWindowKind,
        since: date,
        through: date,
        symbol: str,
    ) -> NCandidateWindowResult:
        if any(since <= day <= through for day in self._protocol.embargo_trading_days):
            raise CandidateValidationWindowError()
        source = self._run_source(
            NStructureResearchRequest(since=since, through=through, symbol=symbol),
            symbol=symbol,
        )
        return project_n_structure_window(
            window_id=window_id,
            window_kind=window_kind,
            since=since,
            through=through,
            source=source,
        )

    def _run_source(
        self,
        request: NStructureResearchRequest,
        *,
        symbol: str,
    ) -> NStructureResearchResult:
        try:
            result = self._n_structure_research.run(request)
            if not isinstance(result, NStructureResearchResult) or result.products != (
                symbol,
            ):
                raise ValueError("N research result identity is invalid")
            return result
        except Exception as exc:
            raise CandidateValidationSourceError() from exc

    @staticmethod
    def _quality_flags(
        retrospective: NCandidateWindowResult,
        folds: Sequence[NRollingCandidateFold],
        prospective: NProspectiveOosResult,
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if prospective.status is NProspectiveOosStatus.PENDING:
            flags.append("PROSPECTIVE_OOS_PENDING")
        if any(sum(fold.test.completed_n_counts.values()) == 0 for fold in folds):
            flags.append("ROLLING_FOLD_WITHOUT_COMPLETED_N")
        windows = (
            retrospective,
            *(window for fold in folds for window in (fold.reference, fold.test)),
            *((prospective.result,) if prospective.result is not None else ()),
        )
        if any(
            horizon.sample_count == 0
            for window in windows
            for horizon in window.horizon_summary.values()
        ):
            flags.append("HORIZON_WITHOUT_SAMPLE")
        return tuple(flags)
