from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from .candidate_validation import (
    CandidateValidationReport,
    CandidateWindowKind,
    CandidateWindowResult,
    ProspectiveOosResult,
    ProspectiveOosStatus,
    RollingCandidateFold,
    project_lifecycle_window,
    summarize_rolling_stability,
)
from .candidate_validation_schedule import (
    CandidateValidationIdentityError,
    CandidateValidationRequest,
    CandidateValidationSourceError,
    CandidateValidationWindowError,
    build_rolling_validation_windows,
    prospective_window,
)
from .candidate_validation_policy import (
    CandidateManifest,
    CandidateValidationProtocol,
)
from .subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)


class _LifecycleResearchRunner(Protocol):
    def run(
        self,
        request: LifecycleResearchRequest,
    ) -> SubingLifecycleResearchResult: ...


class SubingCandidateValidationService:
    """Project frozen Candidate windows from the existing Lifecycle service."""

    def __init__(
        self,
        lifecycle_research: _LifecycleResearchRunner,
        *,
        manifest: CandidateManifest,
        protocol: CandidateValidationProtocol,
    ) -> None:
        if not isinstance(manifest, CandidateManifest) or not isinstance(
            protocol, CandidateValidationProtocol
        ):
            raise TypeError("manifest and protocol must use Candidate contracts")
        self._lifecycle_research = lifecycle_research
        self._manifest = manifest
        self._protocol = protocol

    def run(self, request: CandidateValidationRequest) -> CandidateValidationReport:
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
            window_kind=CandidateWindowKind.RETROSPECTIVE,
            since=self._protocol.retrospective_since,
            through=self._protocol.retrospective_through,
            symbol=request.symbol,
        )
        folds = self._rolling_folds(request.symbol)
        prospective = self._prospective(request.symbol, request.through)
        quality_flags = self._quality_flags(retrospective, folds, prospective)

        return CandidateValidationReport(
            schema_version=1,
            candidate_id=self._manifest.candidate_id,
            policy_id=self._manifest.policy_id,
            formula_version=self._manifest.formula_version,
            protocol_id=self._protocol.protocol_id,
            research_only=True,
            symbol=request.symbol,
            retrospective=retrospective,
            rolling_folds=folds,
            rolling_stability=summarize_rolling_stability(folds),
            prospective_oos=prospective,
            quality_flags=quality_flags,
        )

    def _rolling_folds(self, symbol: str) -> tuple[RollingCandidateFold, ...]:
        folds: list[RollingCandidateFold] = []
        windows = build_rolling_validation_windows(
            reference_months=self._protocol.reference_months,
            test_months=self._protocol.test_months,
            step_months=self._protocol.step_months,
            first_test_since=self._protocol.first_test_since,
            last_test_through=self._protocol.last_test_through,
        )
        for window in windows:
            folds.append(
                RollingCandidateFold(
                    fold_id=window.fold_id,
                    reference=self._window(
                        window_id=f"{window.fold_id}_reference",
                        window_kind=CandidateWindowKind.ROLLING_REFERENCE,
                        since=window.reference_since,
                        through=window.reference_through,
                        symbol=symbol,
                    ),
                    test=self._window(
                        window_id=f"{window.fold_id}_test",
                        window_kind=CandidateWindowKind.ROLLING_TEST,
                        since=window.test_since,
                        through=window.test_through,
                        symbol=symbol,
                    ),
                )
            )
        return tuple(folds)

    def _prospective(self, symbol: str, through: date) -> ProspectiveOosResult:
        first_day = self._protocol.prospective_oos_first_trading_day
        window = prospective_window(
            through=through,
            first_trading_day=first_day,
        )
        if window is None:
            return ProspectiveOosResult(
                status=ProspectiveOosStatus.PENDING,
                first_trading_day=first_day,
                through=through,
                result=None,
            )
        since, prospective_through = window
        result = self._window(
            window_id="prospective_oos",
            window_kind=CandidateWindowKind.PROSPECTIVE_OOS,
            since=since,
            through=prospective_through,
            symbol=symbol,
        )
        return ProspectiveOosResult(
            status=ProspectiveOosStatus.EVALUATED,
            first_trading_day=first_day,
            through=through,
            result=result,
        )

    def _window(
        self,
        *,
        window_id: str,
        window_kind: CandidateWindowKind,
        since: date,
        through: date,
        symbol: str,
    ) -> CandidateWindowResult:
        source = self._run_source(
            LifecycleResearchRequest(since=since, through=through, symbol=symbol),
            symbol=symbol,
        )
        return project_lifecycle_window(
            window_id=window_id,
            window_kind=window_kind,
            since=since,
            through=through,
            source=source,
        )

    def _run_source(
        self,
        request: LifecycleResearchRequest,
        *,
        symbol: str,
    ) -> SubingLifecycleResearchResult:
        try:
            result = self._lifecycle_research.run(request)
            if not isinstance(
                result, SubingLifecycleResearchResult
            ) or result.products != (symbol,):
                raise ValueError("lifecycle result identity is invalid")
            return result
        except Exception as exc:
            raise CandidateValidationSourceError() from exc

    @staticmethod
    def _quality_flags(
        retrospective: CandidateWindowResult,
        folds: Sequence[RollingCandidateFold],
        prospective: ProspectiveOosResult,
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if prospective.status is ProspectiveOosStatus.PENDING:
            flags.append("PROSPECTIVE_OOS_PENDING")
        if any(fold.test.funnel_counts["ENTRY_CONFIRMED"] == 0 for fold in folds):
            flags.append("ROLLING_FOLD_WITHOUT_ENTRY")
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
