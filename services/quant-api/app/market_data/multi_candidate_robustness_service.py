from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Protocol, cast

from .actual_dominant_research import ActualDominantResearchSegmentIdentityError
from .candidate_validation import CandidateValidationReport
from .market_data_service import MarketDataError
from .candidate_validation_schedule import CandidateValidationRequest
from .multi_candidate_robustness import (
    CandidateRelationshipSummary,
    CandidateTemporalDossier,
    CandidateSymbolRobustness,
    CandidateSymbolStatus,
    CommonPriceHorizonSummary,
    CrossSymbolCandidateSummary,
    HorizonSignSummary,
    MultiCandidateRobustnessReport,
)
from .multi_candidate_events import (
    CandidateResearchEvent,
    from_n_completion,
    from_subing_entry,
    summarize_candidate_relationship,
)
from .multi_candidate_robustness_policy import (
    MultiCandidateRobustnessProtocol,
    MultiCandidateRobustnessRequest,
)
from .n_structure_research_service import (
    NStructureCompletionResearchEvent,
    NStructureResearchRequest,
    NStructureResearchResult,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from .n_candidate_validation import NStructureCandidateValidationReport
from .subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleEntryResearchEvent,
    SubingLifecycleResearchResult,
)


class _SubingResearchRunner(Protocol):
    def run(
        self, request: LifecycleResearchRequest
    ) -> SubingLifecycleResearchResult: ...

    def entry_events(
        self, request: LifecycleResearchRequest
    ) -> tuple[SubingLifecycleEntryResearchEvent, ...]: ...


class _NResearchRunner(Protocol):
    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult: ...

    def completion_events(
        self, request: NStructureResearchRequest
    ) -> tuple[NStructureCompletionResearchEvent, ...]: ...


class _ValidationRunner(Protocol):
    def run(
        self, request: CandidateValidationRequest
    ) -> CandidateValidationReport | NStructureCandidateValidationReport: ...


class MultiCandidateRobustnessSourceError(ValueError):
    code = "MULTI_CANDIDATE_SOURCE_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MultiCandidateRobustnessBaselineError(ValueError):
    code = "MULTI_CANDIDATE_BASELINE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MultiCandidateActiveUniverseDriftError(ValueError):
    code = "MULTI_CANDIDATE_ACTIVE_UNIVERSE_DRIFT"

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
        subing_research: _SubingResearchRunner,
        n_research: _NResearchRunner,
        subing_validation: _ValidationRunner,
        n_validation: _ValidationRunner,
        current_active_products: tuple[str, ...],
    ) -> None:
        if current_active_products != protocol.cross_symbol_products:
            raise MultiCandidateActiveUniverseDriftError()
        self._protocol = protocol
        self._subing = subing_research
        self._n = n_research
        self._subing_validation = subing_validation
        self._n_validation = n_validation

    def run(
        self, request: MultiCandidateRobustnessRequest
    ) -> MultiCandidateRobustnessReport:
        if (
            not isinstance(request, MultiCandidateRobustnessRequest)
            or request.protocol_id != self._protocol.protocol_id
        ):
            raise ValueError("MULTI_CANDIDATE_REQUEST_INVALID")
        temporal = self._temporal_dossiers()
        rows, summaries = self._cross_symbol_results()
        lifecycle_request = LifecycleResearchRequest(
            self._protocol.common_since,
            self._protocol.common_through,
            self._protocol.anchor_symbol,
        )
        n_request = NStructureResearchRequest(
            self._protocol.common_since,
            self._protocol.common_through,
            self._protocol.anchor_symbol,
        )
        subing_events = tuple(
            from_subing_entry(event)
            for event in self._subing.entry_events(lifecycle_request)
        )
        n_events = tuple(
            from_n_completion(event) for event in self._n.completion_events(n_request)
        )
        relationships = (
            _relationship(
                subing_events,
                n_events,
                "subing_lifecycle_v2_candidate_v1",
                "n_structure_5m_candidate_v1",
            ),
            _relationship(
                n_events,
                subing_events,
                "n_structure_5m_candidate_v1",
                "subing_lifecycle_v2_candidate_v1",
            ),
        )
        quality_flags: list[str] = []
        if any(row.status is CandidateSymbolStatus.UNAVAILABLE for row in rows):
            quality_flags.append("CROSS_SYMBOL_SOURCE_UNAVAILABLE")
        if temporal[0].prospective_status == "pending":
            quality_flags.append("BASELINE_PROSPECTIVE_PENDING_SUBING")
        if temporal[1].prospective_status == "pending":
            quality_flags.append("BASELINE_PROSPECTIVE_PENDING_N")
        if any(
            row.status is CandidateSymbolStatus.AVAILABLE and row.event_count == 0
            for row in rows
        ):
            quality_flags.append("SYMBOL_WITHOUT_EVENT")
        if any(
            row.status is CandidateSymbolStatus.AVAILABLE
            and row.horizon_summary is not None
            and any(value.sample_count == 0 for value in row.horizon_summary.values())
            for row in rows
        ):
            quality_flags.append("HORIZON_WITHOUT_SAMPLE")
        return MultiCandidateRobustnessReport(
            schema_version=1,
            protocol_id=self._protocol.protocol_id,
            frozen_at=self._protocol.frozen_at,
            research_only=True,
            readonly=True,
            anchor_symbol=self._protocol.anchor_symbol,
            common_since=self._protocol.common_since,
            common_through=self._protocol.common_through,
            temporal_dossiers=temporal,
            cross_symbol_results=rows,
            cross_symbol_summaries=summaries,
            relationships=relationships,
            metric_compatibility_flags=(
                "EVALUABLE_UNIT_DIFFERS",
                "HORIZON_SEMANTICS_DIFFERS",
            ),
            quality_flags=tuple(quality_flags),
        )

    def _temporal_dossiers(self) -> tuple[CandidateTemporalDossier, ...]:
        dossiers: list[CandidateTemporalDossier] = []
        for ref in self._protocol.candidates:
            runner = (
                self._subing_validation
                if ref.source_kind == "subing_lifecycle"
                else self._n_validation
            )
            report = runner.run(
                CandidateValidationRequest(
                    candidate_id=ref.candidate_id,
                    protocol_id=ref.candidate_protocol_id,
                    symbol=self._protocol.anchor_symbol,
                    through=ref.baseline_request_through,
                )
            )
            self._validate_baseline(report, ref.candidate_id, ref.candidate_protocol_id)
            if ref.source_kind == "subing_lifecycle":
                subing_report = cast(CandidateValidationReport, report)
                test_counts = tuple(
                    fold.test.funnel_counts["ENTRY_CONFIRMED"]
                    for fold in subing_report.rolling_folds
                )
                retrospective = subing_report.retrospective
                retrospective_count = retrospective.funnel_counts["ENTRY_CONFIRMED"]
                retrospective_since = retrospective.since
                retrospective_through = retrospective.through
                common_horizon_summary = {
                    horizon: CommonPriceHorizonSummary(
                        value.sample_count,
                        value.median_directional_return_bps,
                        value.median_mfe_bps,
                        value.median_mae_bps,
                    )
                    for horizon, value in retrospective.horizon_summary.items()
                }
            else:
                n_report = cast(NStructureCandidateValidationReport, report)
                test_counts = tuple(
                    sum(fold.test.completed_n_counts.values())
                    for fold in n_report.rolling_folds
                )
                n_retrospective = n_report.retrospective
                retrospective_count = sum(n_retrospective.completed_n_counts.values())
                retrospective_since = n_retrospective.since
                retrospective_through = n_retrospective.through
                common_horizon_summary = {
                    horizon: CommonPriceHorizonSummary(
                        value.sample_count,
                        value.median_directional_return_bps,
                        value.median_mfe_bps,
                        value.median_mae_bps,
                    )
                    for horizon, value in n_retrospective.horizon_summary.items()
                }
            prospective = report.prospective_oos  # type: ignore[attr-defined]
            status = prospective.status.value
            dossiers.append(
                CandidateTemporalDossier(
                    candidate_id=ref.candidate_id,
                    candidate_protocol_id=ref.candidate_protocol_id,
                    source_kind=ref.source_kind,
                    anchor_symbol=self._protocol.anchor_symbol,
                    retrospective_since=retrospective_since,
                    retrospective_through=retrospective_through,
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
                    horizon_summary=common_horizon_summary,
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
        for ref in self._protocol.candidates:
            for symbol in self._protocol.cross_symbol_products:
                try:
                    source = self._run_cross_source(ref.source_kind, symbol)
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

    def _run_cross_source(
        self, source_kind: str, symbol: str
    ) -> SubingLifecycleResearchResult | NStructureResearchResult:
        if source_kind == "subing_lifecycle":
            return self._subing.run(
                LifecycleResearchRequest(
                    self._protocol.common_since,
                    self._protocol.common_through,
                    symbol,
                )
            )
        return self._n.run(
            NStructureResearchRequest(
                self._protocol.common_since,
                self._protocol.common_through,
                symbol,
            )
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


def _relationship(
    source_events: tuple[CandidateResearchEvent, ...],
    target_events: tuple[CandidateResearchEvent, ...],
    source_candidate_id: str,
    target_candidate_id: str,
) -> CandidateRelationshipSummary:
    if source_events or target_events:
        return summarize_candidate_relationship(
            source_events,
            target_events,
            proximity_bars=(3, 5, 8),
        )
    return CandidateRelationshipSummary(
        source_candidate_id=source_candidate_id,
        target_candidate_id=target_candidate_id,
        source_event_count=0,
        target_event_count=0,
        exact_same_direction_count=0,
        exact_opposite_direction_count=0,
        within_3_same_direction_source_count=0,
        within_5_same_direction_source_count=0,
        within_8_same_direction_source_count=0,
        nearest_match_count_within_8=0,
        signed_distance_min=None,
        signed_distance_median=None,
        signed_distance_max=None,
        target_earlier_count=0,
        target_same_boundary_count=0,
        target_later_count=0,
        same_trading_day_count=0,
        cross_trading_day_count=0,
    )
