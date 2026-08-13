"""SuBing Factor Observation 的 current-rank1 薄只读编排层。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

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
from app.market_data.subing_research import SubingFactorResult, calculate_subing_factor


SUPPORTED_SUBING_FREQUENCIES = frozenset(
    {BarFrequency.M5, BarFrequency.M15, BarFrequency.D1}
)
_COMPANION_FREQUENCY = {
    BarFrequency.M5: BarFrequency.M15,
    BarFrequency.M15: BarFrequency.M5,
}


class SubingMarketDataReader(Protocol):
    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]: ...

    def latest_dominant_segment(self, symbol: str) -> DominantContractSegmentSummary: ...


class SubingMarketRead(Protocol):
    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult: ...

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState: ...

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]: ...


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
    calibration_state: str
    primary: SubingFactorResult
    companion: SubingFactorResult | None


class SubingReadService:
    """组合 current segment Historical 与可用的 completed Live Factor。"""

    def __init__(
        self,
        *,
        market_data: SubingMarketDataReader,
        market_read: SubingMarketRead,
    ) -> None:
        self._market_data = market_data
        self._market_read = market_read

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

        primary_identity = _identity(
            request.symbol,
            request.frequency,
            dominant.actual_contract,
        )
        primary_historical = self._historical_segment(
            primary_identity,
            segment.start_trading_day,
        )

        companion_frequency = _COMPANION_FREQUENCY.get(request.frequency)
        companion_identity = (
            _identity(request.symbol, companion_frequency, dominant.actual_contract)
            if companion_frequency is not None
            else None
        )
        companion_historical = (
            self._historical_segment(companion_identity, segment.start_trading_day)
            if companion_identity is not None
            else ()
        )

        if companion_identity is None:
            primary_bars = primary_historical
            companion_bars: tuple[CanonicalBar, ...] = ()
            primary_source = "canonical"
            companion_live_ends: frozenset[datetime] = frozenset()
            source_mode = "canonical"
            live_observation = "not_applicable"
            live_reason = "daily_historical_only"
        else:
            states = (
                self._market_read.state(primary_identity, now),
                self._market_read.state(companion_identity, now),
            )
            if any(
                state.live_contract is not None
                and state.live_contract != dominant.actual_contract
                for state in states
            ):
                primary_bars = primary_historical
                companion_bars = companion_historical
                primary_source = "canonical"
                companion_live_ends = frozenset()
                live_observation = "unavailable"
                live_reason = "contract_mismatch"
            elif not all(
                state.live_available
                and state.live_contract == dominant.actual_contract
                for state in states
            ):
                primary_bars = primary_historical
                companion_bars = companion_historical
                primary_source = "canonical"
                companion_live_ends = frozenset()
                live_observation = "unavailable"
                live_reason = "live_unavailable"
            else:
                primary_bars, primary_source, _ = self._merge_live(
                    primary_identity,
                    primary_historical,
                    segment.start_trading_day,
                    now,
                )
                companion_bars, _, companion_live_ends = self._merge_live(
                    companion_identity,
                    companion_historical,
                    segment.start_trading_day,
                    now,
                )
                live_observation = "available"
                live_reason = None

        primary = calculate_subing_factor(
            primary_bars,
            timeframe=request.frequency,
            contract=dominant.actual_contract,
            segment_start_trading_day=segment.start_trading_day,
            latest_bar_source=primary_source,
        )
        companion = None
        if companion_frequency is not None:
            primary_cutoff = primary_bars[-1].bar_end if primary_bars else None
            aligned_companion = (
                tuple(bar for bar in companion_bars if bar.bar_end <= primary_cutoff)
                if primary_cutoff is not None
                else ()
            )
            aligned_source = (
                "live"
                if aligned_companion
                and aligned_companion[-1].bar_end in companion_live_ends
                else "canonical"
            )
            companion = calculate_subing_factor(
                aligned_companion,
                timeframe=companion_frequency,
                contract=dominant.actual_contract,
                segment_start_trading_day=segment.start_trading_day,
                latest_bar_source=aligned_source,
            )
            source_mode = (
                "canonical_live"
                if primary_source == "live" or aligned_source == "live"
                else "canonical"
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
            calibration_state="pending",
            primary=primary,
            companion=companion,
        )

    def _latest_dominant(self, symbol: str) -> DominantContractSummary:
        for dominant in self._market_data.list_latest_dominants():
            if dominant.symbol == symbol:
                return dominant
        raise MarketDataError("DOMINANT_CONTEXT_MISSING")

    def _historical_segment(
        self,
        identity: SeriesPageQuery,
        segment_start: date,
    ) -> tuple[CanonicalBar, ...]:
        page = self._market_read.history_page(identity)
        return tuple(
            sorted(
                (bar for bar in page.bars if bar.trading_day >= segment_start),
                key=lambda bar: bar.bar_end,
            )
        )

    def _merge_live(
        self,
        identity: SeriesPageQuery,
        historical: tuple[CanonicalBar, ...],
        segment_start: date,
        now: datetime,
    ) -> tuple[tuple[CanonicalBar, ...], str, frozenset[datetime]]:
        historical_end = historical[-1].bar_end if historical else None
        live = self._market_read.live_snapshot(identity, historical_end, now)
        by_end = {bar.bar_end: (bar, "canonical") for bar in historical}
        for bar in live:
            if bar.trading_day >= segment_start:
                by_end.setdefault(bar.bar_end, (bar, "live"))
        ordered = tuple(by_end[key] for key in sorted(by_end))
        bars = tuple(item[0] for item in ordered)
        latest_source = ordered[-1][1] if ordered else "canonical"
        live_ends = frozenset(bar.bar_end for bar, source in ordered if source == "live")
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
