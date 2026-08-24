from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from .actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from .domain import BarFrequency, MarketSeriesResult, ResolvedContractSegment
from .market_data_service import MarketDataError
from .subing_ema_trend import (
    PriceSide,
    SubingEmaTrendResult,
    SubingEmaTrendSnapshot,
    SubingEmaTrendStatus,
    calculate_subing_ema_trend,
)


class SubingDailyWatchDecision(StrEnum):
    LONG_WATCH = "long_watch"
    SHORT_WATCH = "short_watch"
    EXCLUDED = "excluded"
    UNAVAILABLE = "unavailable"


class SubingDailyWatchError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SubingDailyWatchProduct:
    symbol: str
    product_name: str
    sector: str


@dataclass(frozen=True, slots=True)
class SubingDailyWatchClassification:
    decision: SubingDailyWatchDecision
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubingDailyWatchItem:
    symbol: str
    product_name: str
    sector: str
    decision: SubingDailyWatchDecision
    reason_codes: tuple[str, ...]
    daily: SubingEmaTrendSnapshot | None
    hourly: SubingEmaTrendSnapshot | None
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.symbol:
            raise SubingDailyWatchError("SNAPSHOT_INVALID")
        has_complete_facts = self.daily is not None and self.hourly is not None
        if self.decision is SubingDailyWatchDecision.UNAVAILABLE:
            if self.reason_codes or not self.unavailable_reasons:
                raise SubingDailyWatchError("SNAPSHOT_INVALID")
        elif (
            not has_complete_facts
            or not self.reason_codes
            or self.unavailable_reasons
        ):
            raise SubingDailyWatchError("SNAPSHOT_INVALID")


@dataclass(frozen=True, slots=True)
class SubingDailyWatchSnapshot:
    source_trading_day: date
    target_trading_day: date
    generated_at: datetime
    items: tuple[SubingDailyWatchItem, ...]

    def __post_init__(self) -> None:
        symbols = tuple(item.symbol for item in self.items)
        if (
            not self.items
            or len(set(symbols)) != len(symbols)
            or self.target_trading_day <= self.source_trading_day
            or self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() is None
        ):
            raise SubingDailyWatchError("SNAPSHOT_INVALID")

    @property
    def counts(self) -> dict[str, int]:
        decisions = Counter(item.decision.value for item in self.items)
        return {
            "universe": len(self.items),
            "long_watch": decisions[SubingDailyWatchDecision.LONG_WATCH.value],
            "short_watch": decisions[SubingDailyWatchDecision.SHORT_WATCH.value],
            "excluded": decisions[SubingDailyWatchDecision.EXCLUDED.value],
            "unavailable": decisions[SubingDailyWatchDecision.UNAVAILABLE.value],
        }


class _SegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


def classify_daily_watch(
    daily: SubingEmaTrendSnapshot,
    hourly: SubingEmaTrendSnapshot,
) -> SubingDailyWatchClassification:
    daily_direction = _trend_direction(daily)
    hourly_direction = _trend_direction(hourly)
    if daily_direction == "neutral":
        return SubingDailyWatchClassification(
            SubingDailyWatchDecision.EXCLUDED,
            ("D1_TREND_NEUTRAL",),
        )
    if hourly_direction == "neutral":
        return SubingDailyWatchClassification(
            SubingDailyWatchDecision.EXCLUDED,
            ("H1_TREND_NEUTRAL",),
        )
    if daily_direction != hourly_direction:
        return SubingDailyWatchClassification(
            SubingDailyWatchDecision.EXCLUDED,
            ("D1_H1_DIRECTION_MISMATCH",),
        )
    if daily_direction == "long":
        return SubingDailyWatchClassification(
            SubingDailyWatchDecision.LONG_WATCH,
            ("D1_H1_LONG_ALIGNED",),
        )
    return SubingDailyWatchClassification(
        SubingDailyWatchDecision.SHORT_WATCH,
        ("D1_H1_SHORT_ALIGNED",),
    )


class SubingDailyWatchBuilder:
    def __init__(
        self,
        *,
        segment_loader: _SegmentLoader,
        products: tuple[str, ...],
        product_metadata: Mapping[str, SubingDailyWatchProduct],
        expected_universe_size: int = 60,
    ) -> None:
        if (
            expected_universe_size <= 0
            or len(products) != expected_universe_size
            or len(set(products)) != len(products)
            or any(
                not symbol
                or symbol != symbol.strip().lower()
                or not symbol.isascii()
                or not symbol.isalpha()
                for symbol in products
            )
        ):
            raise SubingDailyWatchError("ACTIVE_OPERATIONAL_SCOPE_MISMATCH")
        self._segment_loader = segment_loader
        self._products = products
        self._product_metadata = product_metadata
        self._expected_universe_size = expected_universe_size

    def build(
        self,
        *,
        source_trading_day: date,
        target_trading_day: date,
        generated_at: datetime,
    ) -> SubingDailyWatchSnapshot:
        items = tuple(
            self._build_item(symbol, source_trading_day=source_trading_day)
            for symbol in self._products
        )
        if len(items) != self._expected_universe_size:
            raise SubingDailyWatchError("SNAPSHOT_INVALID")
        return SubingDailyWatchSnapshot(
            source_trading_day=source_trading_day,
            target_trading_day=target_trading_day,
            generated_at=generated_at,
            items=items,
        )

    def _build_item(
        self,
        symbol: str,
        *,
        source_trading_day: date,
    ) -> SubingDailyWatchItem:
        metadata = self._product_metadata.get(symbol)
        if metadata is None or metadata.symbol != symbol:
            return _unavailable_item(
                symbol,
                metadata=None,
                reasons=("PRODUCT_METADATA_UNAVAILABLE",),
            )
        try:
            loaded = self._segment_loader.load(
                symbol=symbol,
                frequencies=(BarFrequency.D1, BarFrequency.H1),
                since=source_trading_day,
                through=source_trading_day,
            )
        except ActualDominantResearchSegmentIdentityError:
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=("DATA_IDENTITY_MISMATCH",),
            )
        except MarketDataError:
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=("DOMINANT_SEGMENT_UNAVAILABLE",),
            )

        identity = _validate_loaded_identity(
            loaded,
            source_trading_day=source_trading_day,
        )
        if identity is None:
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=("DATA_IDENTITY_MISMATCH",),
            )
        segment, daily_result, hourly_result = identity
        daily_bars = daily_result.bars
        hourly_bars = hourly_result.bars
        if (
            not daily_bars
            or not hourly_bars
            or daily_bars[-1].trading_day != source_trading_day
            or hourly_bars[-1].trading_day != source_trading_day
        ):
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=("SOURCE_TRADING_DAY_MISSING",),
            )

        daily = calculate_subing_ema_trend(
            daily_bars,
            timeframe=BarFrequency.D1,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
        )
        hourly = calculate_subing_ema_trend(
            hourly_bars,
            timeframe=BarFrequency.H1,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
        )
        unavailable_reasons = _history_unavailable_reasons(daily, hourly)
        if unavailable_reasons:
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=unavailable_reasons,
                daily=daily.snapshot,
                hourly=hourly.snapshot,
            )
        assert daily.snapshot is not None
        assert hourly.snapshot is not None
        classification = classify_daily_watch(daily.snapshot, hourly.snapshot)
        return SubingDailyWatchItem(
            symbol=symbol,
            product_name=metadata.product_name,
            sector=metadata.sector,
            decision=classification.decision,
            reason_codes=classification.reason_codes,
            daily=daily.snapshot,
            hourly=hourly.snapshot,
            unavailable_reasons=(),
        )


def _trend_direction(snapshot: SubingEmaTrendSnapshot) -> str:
    if (
        snapshot.price_side is PriceSide.ABOVE
        and snapshot.close > snapshot.ema21
        and snapshot.slope_5_bps_per_bar > 0
        and snapshot.slope_10_bps_per_bar > 0
    ):
        return "long"
    if (
        snapshot.price_side is PriceSide.BELOW
        and snapshot.close < snapshot.ema21
        and snapshot.slope_5_bps_per_bar < 0
        and snapshot.slope_10_bps_per_bar < 0
    ):
        return "short"
    return "neutral"


def _validate_loaded_identity(
    loaded: ActualDominantResearchSeries,
    *,
    source_trading_day: date,
) -> tuple[
    ResolvedContractSegment,
    MarketSeriesResult,
    MarketSeriesResult,
] | None:
    if len(loaded.segments) != 1:
        return None
    segment = loaded.segments[0]
    if not (
        segment.start_trading_day
        <= source_trading_day
        <= segment.end_trading_day
    ):
        return None
    daily = loaded.results.get(BarFrequency.D1)
    hourly = loaded.results.get(BarFrequency.H1)
    if daily is None or hourly is None:
        return None
    for result in (daily, hourly):
        if result.resolved_contract_segments != loaded.segments or any(
            not (
                segment.start_trading_day
                <= bar.trading_day
                <= source_trading_day
            )
            for bar in result.bars
        ):
            return None
    return segment, daily, hourly


def _history_unavailable_reasons(
    daily: SubingEmaTrendResult,
    hourly: SubingEmaTrendResult,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if daily.status is not SubingEmaTrendStatus.READY:
        reasons.append("D1_HISTORY_INSUFFICIENT")
    if hourly.status is not SubingEmaTrendStatus.READY:
        reasons.append("H1_HISTORY_INSUFFICIENT")
    return tuple(reasons)


def _unavailable_item(
    symbol: str,
    *,
    metadata: SubingDailyWatchProduct | None,
    reasons: tuple[str, ...],
    daily: SubingEmaTrendSnapshot | None = None,
    hourly: SubingEmaTrendSnapshot | None = None,
) -> SubingDailyWatchItem:
    return SubingDailyWatchItem(
        symbol=symbol,
        product_name=metadata.product_name if metadata is not None else "",
        sector=metadata.sector if metadata is not None else "",
        decision=SubingDailyWatchDecision.UNAVAILABLE,
        reason_codes=(),
        daily=daily,
        hourly=hourly,
        unavailable_reasons=reasons,
    )
