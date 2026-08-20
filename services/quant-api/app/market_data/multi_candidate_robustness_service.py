from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Protocol

from .actual_dominant_research import ActualDominantResearchSegmentIdentityError
from .market_data_service import MarketDataError
from .candidate_validation_schedule import CandidateValidationRequest
from .multi_candidate_robustness import (
    CandidateTemporalDossier,
    CandidateSymbolRobustness,
    CandidateSymbolStatus,
    CommonPriceHorizonSummary,
    CrossSymbolCandidateSummary,
    HorizonSignSummary,
)
from .multi_candidate_robustness_policy import MultiCandidateRobustnessProtocol
from .n_structure_research_service import (
    NStructureResearchRequest,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from .subing_lifecycle_research_service import LifecycleResearchRequest


class _Runner(Protocol):
    def run(self, request: object) -> object: ...


class MultiCandidateRobustnessSourceError(ValueError):
    code = "MULTI_CANDIDATE_SOURCE_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MultiCandidateRobustnessBaselineError(ValueError):
    code = "MULTI_CANDIDATE_BASELINE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


_ROLLING_WINDOWS = (
    (
        "fold_01",
        date(2023, 1, 1),
        date(2023, 12, 31),
        date(2024, 1, 1),
        date(2024, 3, 31),
    ),
    (
        "fold_02",
        date(2023, 4, 1),
        date(2024, 3, 31),
        date(2024, 4, 1),
        date(2024, 6, 30),
    ),
    (
        "fold_03",
        date(2023, 7, 1),
        date(2024, 6, 30),
        date(2024, 7, 1),
        date(2024, 9, 30),
    ),
    (
        "fold_04",
        date(2023, 10, 1),
        date(2024, 9, 30),
        date(2024, 10, 1),
        date(2024, 12, 31),
    ),
    (
        "fold_05",
        date(2024, 1, 1),
        date(2024, 12, 31),
        date(2025, 1, 1),
        date(2025, 3, 31),
    ),
    (
        "fold_06",
        date(2024, 4, 1),
        date(2025, 3, 31),
        date(2025, 4, 1),
        date(2025, 6, 30),
    ),
    (
        "fold_07",
        date(2024, 7, 1),
        date(2025, 6, 30),
        date(2025, 7, 1),
        date(2025, 9, 30),
    ),
    (
        "fold_08",
        date(2024, 10, 1),
        date(2025, 9, 30),
        date(2025, 10, 1),
        date(2025, 12, 31),
    ),
    (
        "fold_09",
        date(2025, 1, 1),
        date(2025, 12, 31),
        date(2026, 1, 1),
        date(2026, 3, 31),
    ),
    (
        "fold_10",
        date(2025, 4, 1),
        date(2026, 3, 31),
        date(2026, 4, 1),
        date(2026, 6, 30),
    ),
)


class MultiCandidateRobustnessService:
    def __init__(
        self,
        protocol: MultiCandidateRobustnessProtocol,
        *,
        subing_research: _Runner,
        n_research: _Runner,
        subing_validation: _Runner,
        n_validation: _Runner,
    ) -> None:
        self._protocol = protocol
        self._subing = subing_research
        self._n = n_research
        self._subing_validation = subing_validation
        self._n_validation = n_validation

    def _temporal_dossiers(self) -> tuple[CandidateTemporalDossier, ...]:
        dossiers: list[CandidateTemporalDossier] = []
        for ref, runner in zip(
            self._protocol.candidates,
            (self._subing_validation, self._n_validation),
            strict=True,
        ):
            report = runner.run(
                CandidateValidationRequest(
                    candidate_id=ref.candidate_id,
                    protocol_id=ref.candidate_protocol_id,
                    symbol=self._protocol.anchor_symbol,
                    through=ref.baseline_request_through,
                )
            )
            self._validate_baseline(report, ref.candidate_id, ref.candidate_protocol_id)
            subing = ref.source_kind == "subing_lifecycle"
            test_counts = tuple(
                fold.test.funnel_counts["ENTRY_CONFIRMED"]
                if subing
                else sum(fold.test.completed_n_counts.values())
                for fold in report.rolling_folds  # type: ignore[attr-defined]
            )
            retrospective = report.retrospective  # type: ignore[attr-defined]
            retrospective_count = (
                retrospective.funnel_counts["ENTRY_CONFIRMED"]
                if subing
                else sum(retrospective.completed_n_counts.values())
            )
            prospective = report.prospective_oos  # type: ignore[attr-defined]
            status = prospective.status.value
            dossiers.append(
                CandidateTemporalDossier(
                    candidate_id=ref.candidate_id,
                    candidate_protocol_id=ref.candidate_protocol_id,
                    source_kind=ref.source_kind,
                    anchor_symbol=self._protocol.anchor_symbol,
                    retrospective_since=retrospective.since,
                    retrospective_through=retrospective.through,
                    event_unit=ref.source_event_kind,
                    retrospective_event_count=retrospective_count,
                    rolling_fold_count=len(test_counts),
                    folds_with_events=sum(count > 0 for count in test_counts),
                    test_event_count_min=min(test_counts),
                    test_event_count_median=_decimal_median(test_counts),
                    test_event_count_max=max(test_counts),
                    prospective_status=status,
                    prospective_first_trading_day=prospective.first_trading_day,
                    prospective_through=prospective.through,
                    horizon_semantics=ref.horizon_semantics,
                    horizon_summary={
                        horizon: CommonPriceHorizonSummary(
                            value.sample_count,
                            value.median_directional_return_bps,
                            value.median_mfe_bps,
                            value.median_mae_bps,
                        )
                        for horizon, value in retrospective.horizon_summary.items()
                    },
                    source_quality_flags=tuple(report.quality_flags),  # type: ignore[attr-defined]
                )
            )
        return tuple(dossiers)

    @staticmethod
    def _validate_baseline(report: object, candidate_id: str, protocol_id: str) -> None:
        try:
            folds = tuple(report.rolling_folds)  # type: ignore[attr-defined]
            observed = tuple(
                (
                    fold.fold_id,
                    fold.reference.since,
                    fold.reference.through,
                    fold.test.since,
                    fold.test.through,
                )
                for fold in folds
            )
            retrospective = report.retrospective  # type: ignore[attr-defined]
            prospective = report.prospective_oos  # type: ignore[attr-defined]
            expected_retrospective_through = (
                date(2026, 8, 18)
                if candidate_id == "subing_lifecycle_v2_candidate_v1"
                else date(2026, 8, 19)
            )
            expected_first = (
                date(2026, 8, 20)
                if candidate_id == "subing_lifecycle_v2_candidate_v1"
                else date(2026, 8, 21)
            )
            valid = (
                report.candidate_id == candidate_id  # type: ignore[attr-defined]
                and report.protocol_id == protocol_id  # type: ignore[attr-defined]
                and report.symbol == "jm"  # type: ignore[attr-defined]
                and retrospective.since == date(2023, 1, 1)
                and retrospective.through == expected_retrospective_through
                and observed == _ROLLING_WINDOWS
                and prospective.status.value == "pending"
                and prospective.first_trading_day == expected_first
                and prospective.through
                == expected_first.fromordinal(expected_first.toordinal() - 1)
            )
        except (AttributeError, KeyError, TypeError):
            valid = False
        if not valid:
            raise MultiCandidateRobustnessBaselineError()

    def _cross_symbol_results(
        self,
    ) -> tuple[
        tuple[CandidateSymbolRobustness, ...], tuple[CrossSymbolCandidateSummary, ...]
    ]:
        rows: list[CandidateSymbolRobustness] = []
        for ref, runner in zip(
            self._protocol.candidates,
            (self._subing, self._n),
            strict=True,
        ):
            for symbol in self._protocol.cross_symbol_products:
                request: object = (
                    LifecycleResearchRequest(
                        self._protocol.common_since,
                        self._protocol.common_through,
                        symbol,
                    )
                    if ref.source_kind == "subing_lifecycle"
                    else NStructureResearchRequest(
                        self._protocol.common_since,
                        self._protocol.common_through,
                        symbol,
                    )
                )
                try:
                    source = runner.run(request)
                except (
                    MarketDataError,
                    ActualDominantResearchSegmentIdentityError,
                    NStructureSourceUnavailableError,
                    NStructureSegmentIdentityError,
                ):
                    rows.append(
                        self._unavailable(
                            ref.candidate_id,
                            ref.source_kind,
                            symbol,
                            ref.evaluable_unit,
                            ref.horizon_semantics,
                        )
                    )
                    continue
                if getattr(source, "products", None) != (symbol,):
                    raise MultiCandidateRobustnessSourceError()
                rows.append(
                    self._available(
                        ref.candidate_id,
                        ref.source_kind,
                        symbol,
                        ref.evaluable_unit,
                        ref.horizon_semantics,
                        source,
                    )
                )
        normalized = tuple(rows)
        return normalized, tuple(
            self._summarize(candidate_id, normalized)
            for candidate_id in (ref.candidate_id for ref in self._protocol.candidates)
        )

    @staticmethod
    def _available(
        candidate_id: str,
        source_kind: str,
        symbol: str,
        unit: str,
        semantics: str,
        source: object,
    ) -> CandidateSymbolRobustness:
        if source_kind == "subing_lifecycle":
            event_count = source.funnel_counts["ENTRY_CONFIRMED"]  # type: ignore[attr-defined]
            evaluable_count = source.evaluable_boundary_count  # type: ignore[attr-defined]
        else:
            event_count = sum(source.completed_n_counts.values())  # type: ignore[attr-defined]
            evaluable_count = source.evaluable_bar_count  # type: ignore[attr-defined]
        horizons = {
            horizon: CommonPriceHorizonSummary(
                value.sample_count,
                value.median_directional_return_bps,
                value.median_mfe_bps,
                value.median_mae_bps,
            )
            for horizon, value in source.horizon_summary.items()  # type: ignore[attr-defined]
        }
        rate = (
            None
            if evaluable_count == 0
            else Decimal(event_count) * Decimal(1000) / Decimal(evaluable_count)
        )
        return CandidateSymbolRobustness(
            candidate_id,
            source_kind,
            symbol,
            CandidateSymbolStatus.AVAILABLE,
            None,
            event_count,
            evaluable_count,
            unit,
            rate,
            semantics,
            horizons,
        )

    @staticmethod
    def _unavailable(
        candidate_id: str, source_kind: str, symbol: str, unit: str, semantics: str
    ) -> CandidateSymbolRobustness:
        return CandidateSymbolRobustness(
            candidate_id,
            source_kind,
            symbol,
            CandidateSymbolStatus.UNAVAILABLE,
            "MULTI_CANDIDATE_SOURCE_UNAVAILABLE",
            None,
            None,
            unit,
            None,
            semantics,
            None,
        )

    @staticmethod
    def _summarize(
        candidate_id: str, rows: Sequence[CandidateSymbolRobustness]
    ) -> CrossSymbolCandidateSummary:
        selected = tuple(row for row in rows if row.candidate_id == candidate_id)
        available = tuple(
            row for row in selected if row.status is CandidateSymbolStatus.AVAILABLE
        )
        rates = sorted(
            row.event_rate_per_1000_evaluable
            for row in available
            if row.event_rate_per_1000_evaluable is not None
        )
        signs = {}
        for horizon in (3, 5, 8):
            values = tuple(
                metric
                for row in available
                if row.horizon_summary is not None
                and row.horizon_summary[horizon].sample_count > 0
                and (
                    metric := row.horizon_summary[horizon].median_directional_return_bps
                )
                is not None
            )
            signs[horizon] = HorizonSignSummary(
                len(values),
                sum(value > 0 for value in values),
                sum(value == 0 for value in values),
                sum(value < 0 for value in values),
            )
        return CrossSymbolCandidateSummary(
            candidate_id,
            60,
            len(available),
            60 - len(available),
            sum((row.event_count or 0) > 0 for row in available),
            sum(row.event_count == 0 for row in available),
            len(rates),
            min(rates) if rates else None,
            median(rates) if rates else None,
            max(rates) if rates else None,
            signs,
        )


def _decimal_median(values: Sequence[int]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[middle])
    return (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal(2)
