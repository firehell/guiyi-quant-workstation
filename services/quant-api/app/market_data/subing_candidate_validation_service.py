from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
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
from .candidate_validation_policy import (
    CandidateManifest,
    CandidateValidationProtocol,
)
from .subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class CandidateValidationIdentityError(ValueError):
    code = "CANDIDATE_VALIDATION_IDENTITY_MISMATCH"

    def __init__(self) -> None:
        super().__init__(self.code)


class CandidateValidationWindowError(ValueError):
    code = "CANDIDATE_VALIDATION_WINDOW_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class CandidateValidationSourceError(ValueError):
    code = "CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

    def __post_init__(self) -> None:
        candidate_id = _normalize_identifier(self.candidate_id)
        protocol_id = _normalize_identifier(self.protocol_id)
        symbol = self.symbol.strip().lower() if isinstance(self.symbol, str) else ""
        if (
            candidate_id is None
            or protocol_id is None
            or not symbol
            or not symbol.isascii()
            or not symbol.isalpha()
            or type(self.through) is not date
        ):
            raise ValueError("CANDIDATE_VALIDATION_REQUEST_INVALID")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "protocol_id", protocol_id)
        object.__setattr__(self, "symbol", symbol)


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
        test_since = self._protocol.first_test_since
        index = 1
        while test_since <= self._protocol.last_test_through:
            test_through = _add_months(
                test_since, self._protocol.test_months
            ) - timedelta(days=1)
            if test_through > self._protocol.last_test_through:
                raise CandidateValidationWindowError()
            fold_id = f"fold_{index:02d}"
            reference_since = _add_months(
                test_since, -self._protocol.reference_months
            )
            reference_through = test_since - timedelta(days=1)
            folds.append(
                RollingCandidateFold(
                    fold_id=fold_id,
                    reference=self._window(
                        window_id=f"{fold_id}_reference",
                        window_kind=CandidateWindowKind.ROLLING_REFERENCE,
                        since=reference_since,
                        through=reference_through,
                        symbol=symbol,
                    ),
                    test=self._window(
                        window_id=f"{fold_id}_test",
                        window_kind=CandidateWindowKind.ROLLING_TEST,
                        since=test_since,
                        through=test_through,
                        symbol=symbol,
                    ),
                )
            )
            test_since = _add_months(test_since, self._protocol.step_months)
            index += 1
        return tuple(folds)

    def _prospective(self, symbol: str, through: date) -> ProspectiveOosResult:
        first_day = self._protocol.prospective_oos_first_trading_day
        if through < first_day:
            return ProspectiveOosResult(
                status=ProspectiveOosStatus.PENDING,
                first_trading_day=first_day,
                through=through,
                result=None,
            )
        result = self._window(
            window_id="prospective_oos",
            window_kind=CandidateWindowKind.PROSPECTIVE_OOS,
            since=first_day,
            through=through,
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
            if (
                not isinstance(result, SubingLifecycleResearchResult)
                or result.products != (symbol,)
            ):
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


def _normalize_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _IDENTIFIER.fullmatch(value) else None


def _add_months(value: date, months: int) -> date:
    start = date(value.year, value.month, 1)
    absolute = start.year * 12 + (start.month - 1) + months
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)
