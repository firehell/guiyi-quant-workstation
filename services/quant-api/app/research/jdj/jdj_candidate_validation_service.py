"""Orchestrate exact JDJ Candidate Validation without widening source errors."""

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
from .jdj_candidate_validation import (
    JdjCandidateValidationReport,
    JdjCandidateWindowKind,
    JdjCandidateWindowResult,
    JdjProspectiveOosResult,
    JdjProspectiveOosStatus,
    JdjRollingCandidateFold,
    project_jdj_window,
    summarize_jdj_rolling_stability,
)
from .jdj_candidate_validation_policy import (
    JdjCandidateManifest,
    JdjCandidateValidationProtocol,
)
from .jdj_context import JdjContextError
from .jdj_research import (
    JdjResearchRequest,
    JdjResearchResult,
    JdjSourceUnavailableError,
)


class _JdjResearchRunner(Protocol):
    def run(self, request: JdjResearchRequest) -> JdjResearchResult: ...


class JdjCandidateValidationService:
    """Project frozen JDJ metrics from the MDS-only research service."""

    def __init__(
        self,
        jdj_research: _JdjResearchRunner,
        *,
        manifest: JdjCandidateManifest,
        protocol: JdjCandidateValidationProtocol,
    ) -> None:
        if not isinstance(manifest, JdjCandidateManifest) or not isinstance(
            protocol,
            JdjCandidateValidationProtocol,
        ):
            raise TypeError("manifest and protocol must use JDJ Candidate contracts")
        source_event_kinds = {
            item.candidate_id: item.source_event_kind
            for item in protocol.candidates
        }
        source_event_kind = source_event_kinds.get(manifest.candidate_id)
        if source_event_kind is None:
            raise ValueError("JDJ Candidate manifest/protocol pairing is invalid")
        self._jdj_research = jdj_research
        self._manifest = manifest
        self._protocol = protocol
        self._source_event_kind = source_event_kind

    def run(
        self,
        request: CandidateValidationRequest,
    ) -> JdjCandidateValidationReport:
        if not isinstance(request, CandidateValidationRequest):
            raise TypeError("request must be CandidateValidationRequest")
        if (
            request.candidate_id != self._manifest.candidate_id
            or request.protocol_id != self._protocol.protocol_id
            or request.symbol != self._protocol.anchor_symbol
        ):
            raise CandidateValidationIdentityError()
        if request.through < self._protocol.baseline_request_through:
            raise CandidateValidationWindowError()

        retrospective = self._window(
            window_id="retrospective",
            window_kind=JdjCandidateWindowKind.RETROSPECTIVE,
            since=self._protocol.retrospective_since,
            through=self._protocol.retrospective_through,
            symbol=request.symbol,
        )
        folds = self._rolling_folds(request.symbol)
        prospective = self._prospective(request.symbol, request.through)
        return JdjCandidateValidationReport(
            schema_version=1,
            candidate_id=self._manifest.candidate_id,
            source_event_kind=self._source_event_kind,
            policy_id=self._manifest.policy_id,
            formula_version=self._manifest.formula_version,
            protocol_id=self._protocol.protocol_id,
            research_only=True,
            symbol=request.symbol,
            retrospective=retrospective,
            rolling_folds=folds,
            rolling_stability=summarize_jdj_rolling_stability(folds),
            prospective_oos=prospective,
            quality_flags=self._quality_flags(retrospective, folds, prospective),
        )

    def _rolling_folds(self, symbol: str) -> tuple[JdjRollingCandidateFold, ...]:
        folds: list[JdjRollingCandidateFold] = []
        windows = build_rolling_validation_windows(
            reference_months=self._protocol.reference_months,
            test_months=self._protocol.test_months,
            step_months=self._protocol.step_months,
            first_test_since=self._protocol.first_test_since,
            last_test_through=self._protocol.last_test_through,
        )
        for window in windows:
            folds.append(
                JdjRollingCandidateFold(
                    fold_id=window.fold_id,
                    reference=self._window(
                        window_id=f"{window.fold_id}_reference",
                        window_kind=JdjCandidateWindowKind.ROLLING_REFERENCE,
                        since=window.reference_since,
                        through=window.reference_through,
                        symbol=symbol,
                    ),
                    test=self._window(
                        window_id=f"{window.fold_id}_test",
                        window_kind=JdjCandidateWindowKind.ROLLING_TEST,
                        since=window.test_since,
                        through=window.test_through,
                        symbol=symbol,
                    ),
                )
            )
        return tuple(folds)

    def _prospective(
        self,
        symbol: str,
        through: date,
    ) -> JdjProspectiveOosResult:
        first_day = self._protocol.prospective_oos_first_trading_day
        window = prospective_window(through=through, first_trading_day=first_day)
        if window is None:
            return JdjProspectiveOosResult(
                status=JdjProspectiveOosStatus.PENDING,
                first_trading_day=first_day,
                through=through,
                result=None,
            )
        since, prospective_through = window
        result = self._window(
            window_id="prospective_oos",
            window_kind=JdjCandidateWindowKind.PROSPECTIVE_OOS,
            since=since,
            through=prospective_through,
            symbol=symbol,
        )
        return JdjProspectiveOosResult(
            status=JdjProspectiveOosStatus.EVALUATED,
            first_trading_day=first_day,
            through=through,
            result=result,
        )

    def _window(
        self,
        *,
        window_id: str,
        window_kind: JdjCandidateWindowKind,
        since: date,
        through: date,
        symbol: str,
    ) -> JdjCandidateWindowResult:
        if any(
            since <= day <= through
            for day in self._protocol.embargo_trading_days
        ):
            raise CandidateValidationWindowError()
        source = self._run_source(
            JdjResearchRequest(
                since=since,
                through=through,
                symbol=symbol,
                candidate_id=self._manifest.candidate_id,
            ),
            symbol=symbol,
        )
        return project_jdj_window(
            window_id=window_id,
            window_kind=window_kind,
            since=since,
            through=through,
            source=source,
        )

    def _run_source(
        self,
        request: JdjResearchRequest,
        *,
        symbol: str,
    ) -> JdjResearchResult:
        try:
            result = self._jdj_research.run(request)
        except (JdjSourceUnavailableError, JdjContextError):
            raise CandidateValidationSourceError() from None
        if (
            not isinstance(result, JdjResearchResult)
            or result.candidate_id != self._manifest.candidate_id
            or result.source_event_kind != self._source_event_kind
            or result.products != (symbol,)
        ):
            raise ValueError("JDJ research result identity is invalid")
        return result

    @staticmethod
    def _quality_flags(
        retrospective: JdjCandidateWindowResult,
        folds: Sequence[JdjRollingCandidateFold],
        prospective: JdjProspectiveOosResult,
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if prospective.status is JdjProspectiveOosStatus.PENDING:
            flags.append("PROSPECTIVE_OOS_PENDING")
        if any(
            fold.test.trigger_count_long + fold.test.trigger_count_short == 0
            for fold in folds
        ):
            flags.append("ROLLING_FOLD_WITHOUT_EVENT")
        windows = (
            retrospective,
            *(
                window
                for fold in folds
                for window in (fold.reference, fold.test)
            ),
            *((prospective.result,) if prospective.result is not None else ()),
        )
        if any(
            horizon.sample_count == 0
            for window in windows
            for horizon in window.horizon_summary.values()
        ):
            flags.append("HORIZON_WITHOUT_SAMPLE")
        return tuple(flags)
