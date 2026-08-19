"""SuBing Factor Observation 的 current-rank1 薄只读编排层。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    DominantContractSummary,
    MarketDataError,
)
from app.market_data.market_read_service import MarketReadState
from app.market_data.subing_calibration import SubingCalibration
from app.market_data.subing_lifecycle import (
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleSnapshot,
    evaluate_subing_lifecycle,
)
from app.market_data.subing_lifecycle_policy import SubingLifecyclePolicy
from app.market_data.subing_research import (
    SubingDirection,
    SubingFactorResult,
    SubingFactorStatus,
    SubingSignalEvaluation,
    SubingSignalStatus,
    calculate_subing_factor_series,
    evaluate_subing_signal,
    resolve_same_boundary_subing_signals,
)


SUPPORTED_SUBING_FREQUENCIES = frozenset(
    {BarFrequency.M5, BarFrequency.M15, BarFrequency.D1}
)
_COMPANION_FREQUENCY = {
    BarFrequency.M5: BarFrequency.M15,
    BarFrequency.M15: BarFrequency.M5,
}


class SubingMarketDataReader(Protocol):
    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]: ...

    def latest_dominant_segment(
        self, symbol: str
    ) -> DominantContractSegmentSummary: ...


class SubingMarketRead(Protocol):
    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult: ...

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState: ...

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]: ...


class _SignalCalibrationView(Protocol):
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]


@dataclass(frozen=True, slots=True)
class _AlignedIntradaySeries:
    bars_5m: tuple[CanonicalBar, ...]
    bars_15m: tuple[CanonicalBar, ...]
    latest_5m_source: str
    latest_15m_source: str
    live_ends_5m: frozenset[datetime]
    live_ends_15m: frozenset[datetime]
    live_observation: str
    live_reason: str | None


@dataclass(frozen=True, slots=True)
class SubingReadRequest:
    symbol: str
    frequency: BarFrequency

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        normalized_symbol = self.symbol.strip()
        if not normalized_symbol.isascii() or not normalized_symbol.isalpha():
            raise ValueError("invalid SuBing symbol")
        try:
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported SuBing frequency") from exc
        if frequency not in SUPPORTED_SUBING_FREQUENCIES:
            raise ValueError("unsupported SuBing frequency")
        object.__setattr__(self, "symbol", normalized_symbol.lower())
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class SubingReadSnapshot:
    symbol: str
    product_name: str
    frequency: BarFrequency
    actual_contract: str
    dominant_mapping_date: date
    segment_start_trading_day: date
    source_mode: str
    live_observation: str
    live_reason: str | None
    macd_policy_id: str
    signal_macd_policy_id: str
    calibration_state: str
    calibration_id: str | None
    primary: SubingFactorResult
    companion: SubingFactorResult | None
    primary_signal: SubingSignalEvaluation
    resolved_signal: SubingSignalEvaluation | None
    lifecycle: SubingLifecycleSnapshot = field(
        default_factory=lambda: _unavailable_lifecycle(
            "SUBING_LIFECYCLE_POLICY_INVALID",
            observed_at=None,
        )
    )


class SubingReadService:
    """组合 current segment Historical 与可用的 completed Live Factor。"""

    def __init__(
        self,
        *,
        market_data: SubingMarketDataReader,
        market_read: SubingMarketRead,
        calibration: SubingCalibration,
        lifecycle_policy: SubingLifecyclePolicy | None = None,
    ) -> None:
        self._market_data = market_data
        self._market_read = market_read
        self._calibration = calibration
        self._lifecycle_policy = lifecycle_policy

    def snapshot(self, request: SubingReadRequest, now: datetime) -> SubingReadSnapshot:
        if not isinstance(request, SubingReadRequest):
            raise TypeError("request must be SubingReadRequest")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        dominant = self._latest_dominant(request.symbol)
        segment = self._market_data.latest_dominant_segment(request.symbol)
        if (
            segment.symbol != dominant.symbol
            or segment.contract != dominant.actual_contract
            or segment.end_trading_day != dominant.dominant_mapping_date
        ):
            raise MarketDataError("DOMINANT_CONTEXT_INCONSISTENT")

        companion_frequency = _COMPANION_FREQUENCY.get(request.frequency)
        source_mode: str
        live_observation: str
        live_reason: str | None
        if companion_frequency is None:
            primary_bars = self._historical_segment(
                _identity(request.symbol, request.frequency, dominant.actual_contract),
                segment.start_trading_day,
                segment.end_trading_day,
            )
            primary_series = calculate_subing_factor_series(
                primary_bars,
                timeframe=request.frequency,
                contract=dominant.actual_contract,
                segment_start_trading_day=segment.start_trading_day,
                latest_bar_source="canonical",
            )
            primary = _latest_factor(primary_series)
            companion = None
            source_mode = "canonical"
            live_observation = "not_applicable"
            live_reason = "daily_historical_only"
            lifecycle = _unavailable_lifecycle(
                "SUBING_LIFECYCLE_INTRADAY_ONLY",
                observed_at=(
                    primary.snapshot.bar_end if primary.snapshot is not None else None
                ),
            )
        else:
            aligned = self._aligned_intraday_series(
                symbol=request.symbol,
                contract=dominant.actual_contract,
                segment_start=segment.start_trading_day,
                segment_end=segment.end_trading_day,
                now=now,
            )
            factors_5m = calculate_subing_factor_series(
                aligned.bars_5m,
                timeframe=BarFrequency.M5,
                contract=dominant.actual_contract,
                segment_start_trading_day=segment.start_trading_day,
                latest_bar_source=aligned.latest_5m_source,
            )
            factors_15m = calculate_subing_factor_series(
                aligned.bars_15m,
                timeframe=BarFrequency.M15,
                contract=dominant.actual_contract,
                segment_start_trading_day=segment.start_trading_day,
                latest_bar_source=aligned.latest_15m_source,
            )
            bars_by_frequency = {
                BarFrequency.M5: aligned.bars_5m,
                BarFrequency.M15: aligned.bars_15m,
            }
            factors_by_frequency = {
                BarFrequency.M5: factors_5m,
                BarFrequency.M15: factors_15m,
            }
            live_ends_by_frequency = {
                BarFrequency.M5: aligned.live_ends_5m,
                BarFrequency.M15: aligned.live_ends_15m,
            }
            primary_bars = bars_by_frequency[request.frequency]
            primary = _latest_factor(factors_by_frequency[request.frequency])
            primary_cutoff = primary_bars[-1].bar_end if primary_bars else None
            companion = _factor_at_or_before(
                bars_by_frequency[companion_frequency],
                factors_by_frequency[companion_frequency],
                cutoff=primary_cutoff,
                live_ends=live_ends_by_frequency[companion_frequency],
            )
            primary_source = (
                "live"
                if primary_bars
                and primary_bars[-1].bar_end
                in live_ends_by_frequency[request.frequency]
                else "canonical"
            )
            companion_source = (
                companion.snapshot.bar_source
                if companion.snapshot is not None
                else "canonical"
            )
            source_mode = (
                "canonical_live"
                if primary_source == "live" or companion_source == "live"
                else "canonical"
            )
            live_observation = aligned.live_observation
            live_reason = aligned.live_reason
            lifecycle_cutoff = (
                aligned.bars_5m[-1].bar_end if aligned.bars_5m else None
            )
            lifecycle_15m_count = (
                sum(
                    bar.bar_end <= lifecycle_cutoff
                    for bar in aligned.bars_15m
                )
                if lifecycle_cutoff is not None
                else 0
            )
            if self._lifecycle_policy is None:
                lifecycle = _unavailable_lifecycle(
                    "SUBING_LIFECYCLE_POLICY_INVALID",
                    observed_at=lifecycle_cutoff,
                )
            else:
                lifecycle = evaluate_subing_lifecycle(
                    symbol=request.symbol,
                    contract=dominant.actual_contract,
                    segment_start_trading_day=segment.start_trading_day,
                    bars_5m=aligned.bars_5m,
                    factors_5m=factors_5m,
                    bars_15m=aligned.bars_15m[:lifecycle_15m_count],
                    factors_15m=factors_15m[:lifecycle_15m_count],
                    calibration=self._calibration,
                    policy=self._lifecycle_policy,
                ).current_snapshot

        primary_signal = evaluate_subing_signal(
            primary,
            companion=companion,
            calibration=cast(_SignalCalibrationView, self._calibration),
        )
        resolved_signal = self._resolve_matched_signal(
            primary,
            companion,
            primary_signal,
        )

        return SubingReadSnapshot(
            symbol=request.symbol,
            product_name=dominant.product_name,
            frequency=request.frequency,
            actual_contract=dominant.actual_contract,
            dominant_mapping_date=dominant.dominant_mapping_date,
            segment_start_trading_day=segment.start_trading_day,
            source_mode=source_mode,
            live_observation=live_observation,
            live_reason=live_reason,
            macd_policy_id="web_macd_legacy_v1",
            signal_macd_policy_id="subing_macd_sma_window_scale2_v1",
            calibration_state=(
                "accepted"
                if self._calibration.calibration_id is not None
                else "pending"
            ),
            calibration_id=self._calibration.calibration_id,
            primary=primary,
            companion=companion,
            primary_signal=primary_signal,
            resolved_signal=resolved_signal,
            lifecycle=lifecycle,
        )

    def _aligned_intraday_series(
        self,
        *,
        symbol: str,
        contract: str,
        segment_start: date,
        segment_end: date,
        now: datetime,
    ) -> _AlignedIntradaySeries:
        identities = {
            frequency: _identity(symbol, frequency, contract)
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }
        historical = {
            frequency: self._historical_segment(
                identities[frequency],
                segment_start,
                segment_end,
            )
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }
        states = tuple(
            self._market_read.state(identities[frequency], now)
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        )
        live_reason: str | None = None
        if any(
            state.live_contract is not None and state.live_contract != contract
            for state in states
        ):
            live_reason = "contract_mismatch"
        elif any(
            state.trading_day is not None and state.trading_day != segment_end
            for state in states
        ):
            live_reason = "live_unavailable"
        elif not all(
            state.live_available and state.live_contract == contract for state in states
        ):
            live_reason = "live_unavailable"

        if live_reason is not None:
            return _AlignedIntradaySeries(
                bars_5m=historical[BarFrequency.M5],
                bars_15m=historical[BarFrequency.M15],
                latest_5m_source="canonical",
                latest_15m_source="canonical",
                live_ends_5m=frozenset(),
                live_ends_15m=frozenset(),
                live_observation="unavailable",
                live_reason=live_reason,
            )

        merged: dict[
            BarFrequency,
            tuple[tuple[CanonicalBar, ...], str, frozenset[datetime]],
        ] = {}
        for frequency in (BarFrequency.M5, BarFrequency.M15):
            merged[frequency] = self._merge_live(
                identities[frequency],
                historical[frequency],
                segment_start,
                segment_end,
                now,
            )
        bars_5m, latest_5m_source, live_ends_5m = merged[BarFrequency.M5]
        bars_15m, latest_15m_source, live_ends_15m = merged[BarFrequency.M15]
        return _AlignedIntradaySeries(
            bars_5m=bars_5m,
            bars_15m=bars_15m,
            latest_5m_source=latest_5m_source,
            latest_15m_source=latest_15m_source,
            live_ends_5m=live_ends_5m,
            live_ends_15m=live_ends_15m,
            live_observation="available",
            live_reason=None,
        )

    def _resolve_matched_signal(
        self,
        primary: SubingFactorResult,
        companion: SubingFactorResult | None,
        primary_signal: SubingSignalEvaluation,
    ) -> SubingSignalEvaluation | None:
        if not _same_ready_boundary(primary, companion):
            return (
                primary_signal
                if primary_signal.status is SubingSignalStatus.MATCHED
                else None
            )
        assert companion is not None
        reciprocal = evaluate_subing_signal(
            companion,
            companion=primary,
            calibration=cast(_SignalCalibrationView, self._calibration),
        )
        if (
            primary_signal.status is SubingSignalStatus.MATCHED
            and reciprocal.status is SubingSignalStatus.MATCHED
        ):
            return resolve_same_boundary_subing_signals(primary_signal, reciprocal)
        if primary_signal.status is SubingSignalStatus.MATCHED:
            return primary_signal
        if reciprocal.status is SubingSignalStatus.MATCHED:
            return reciprocal
        return None

    def _latest_dominant(self, symbol: str) -> DominantContractSummary:
        for dominant in self._market_data.list_latest_dominants():
            if dominant.symbol == symbol:
                return dominant
        raise MarketDataError("DOMINANT_CONTEXT_MISSING")

    def _historical_segment(
        self,
        identity: SeriesPageQuery,
        segment_start: date,
        segment_end: date,
    ) -> tuple[CanonicalBar, ...]:
        page = self._market_read.history_page(identity)
        if any(bar.trading_day > segment_end for bar in page.bars):
            raise MarketDataError("DOMINANT_SEGMENT_HISTORY_INCONSISTENT")
        return tuple(
            sorted(
                (
                    bar
                    for bar in page.bars
                    if segment_start <= bar.trading_day <= segment_end
                ),
                key=lambda bar: bar.bar_end,
            )
        )

    def _merge_live(
        self,
        identity: SeriesPageQuery,
        historical: tuple[CanonicalBar, ...],
        segment_start: date,
        segment_end: date,
        now: datetime,
    ) -> tuple[tuple[CanonicalBar, ...], str, frozenset[datetime]]:
        historical_end = historical[-1].bar_end if historical else None
        live = self._market_read.live_snapshot(identity, historical_end, now)
        by_end = {bar.bar_end: (bar, "canonical") for bar in historical}
        for bar in live:
            if segment_start <= bar.trading_day <= segment_end:
                by_end.setdefault(bar.bar_end, (bar, "live"))
        ordered = tuple(by_end[key] for key in sorted(by_end))
        bars = tuple(item[0] for item in ordered)
        latest_source = ordered[-1][1] if ordered else "canonical"
        live_ends = frozenset(
            bar.bar_end for bar, source in ordered if source == "live"
        )
        return bars, latest_source, live_ends


def _identity(
    symbol: str,
    frequency: BarFrequency,
    contract: str,
) -> SeriesPageQuery:
    return SeriesPageQuery(
        series_kind=SeriesKind.CONTRACT,
        symbol=symbol,
        frequency=frequency,
        limit=300,
        contract=contract,
    )


def _same_ready_boundary(
    primary: SubingFactorResult,
    companion: SubingFactorResult | None,
) -> bool:
    return (
        primary.status is SubingFactorStatus.READY
        and primary.snapshot is not None
        and companion is not None
        and companion.status is SubingFactorStatus.READY
        and companion.snapshot is not None
        and primary.snapshot.bar_end == companion.snapshot.bar_end
    )


def _latest_factor(
    factors: tuple[SubingFactorResult, ...],
) -> SubingFactorResult:
    if factors:
        return factors[-1]
    return SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)


def _factor_at_or_before(
    bars: tuple[CanonicalBar, ...],
    factors: tuple[SubingFactorResult, ...],
    *,
    cutoff: datetime | None,
    live_ends: frozenset[datetime],
) -> SubingFactorResult:
    if cutoff is None:
        return SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)
    selected_index = next(
        (
            index
            for index in range(len(bars) - 1, -1, -1)
            if bars[index].bar_end <= cutoff
        ),
        None,
    )
    if selected_index is None:
        return SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)
    result = factors[selected_index]
    if result.snapshot is None:
        return result
    source = "live" if bars[selected_index].bar_end in live_ends else "canonical"
    return replace(result, snapshot=replace(result.snapshot, bar_source=source))


def _unavailable_lifecycle(
    reason: str,
    *,
    observed_at: datetime | None,
) -> SubingLifecycleSnapshot:
    return SubingLifecycleSnapshot(
        formula_version="subing_lifecycle_v2",
        policy_id="subing_lifecycle_v2_research_v1",
        research_only=True,
        observed_at=observed_at,
        anchor_bar_end=None,
        availability=LifecycleAvailability.UNAVAILABLE,
        unavailable_reason=reason,
        direction=SubingDirection.NONE,
        stage=LifecycleStage.IDLE,
        opportunity_key=None,
        entry_progress=None,
    )
