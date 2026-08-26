from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Protocol

from .actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSourceTradingDayMissingError,
    ActualDominantStitchedResearchSeries,
)
from .domain import BarFrequency, MarketSeriesPageResult, ResolvedContractSegment
from .market_data_service import MarketDataError
from .subing_ema_trend import (
    PriceSide,
    SubingStitchedEmaTrendResult,
    SubingStitchedEmaTrendSnapshot,
    SubingEmaTrendStatus,
    calculate_subing_ema_trend_stitched,
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
    daily: SubingStitchedEmaTrendSnapshot | None
    hourly: SubingStitchedEmaTrendSnapshot | None
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.symbol:
            raise SubingDailyWatchError("SNAPSHOT_INVALID")
        if any(
            not _price_side_matches_close(trend)
            for trend in (self.daily, self.hourly)
            if trend is not None
        ):
            raise SubingDailyWatchError("SNAPSHOT_INVALID")
        has_complete_facts = self.daily is not None and self.hourly is not None
        if self.decision is SubingDailyWatchDecision.UNAVAILABLE:
            if (
                self.reason_codes
                or not self.unavailable_reasons
                or has_complete_facts
                or len(set(self.unavailable_reasons)) != len(self.unavailable_reasons)
                or any(
                    reason not in _UNAVAILABLE_REASON_CODES
                    for reason in self.unavailable_reasons
                )
                or not _unavailable_reasons_match_facts(
                    self.unavailable_reasons,
                    daily=self.daily,
                    hourly=self.hourly,
                )
            ):
                raise SubingDailyWatchError("SNAPSHOT_INVALID")
        elif (
            not has_complete_facts or not self.reason_codes or self.unavailable_reasons
        ):
            raise SubingDailyWatchError("SNAPSHOT_INVALID")
        else:
            assert self.daily is not None
            assert self.hourly is not None
            classification = classify_daily_watch(self.daily, self.hourly)
            if (
                self.decision is not classification.decision
                or self.reason_codes != classification.reason_codes
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


@dataclass(frozen=True, slots=True)
class SubingDailyWatchWebSnapshot:
    source_trading_day: date
    target_trading_day: date
    generated_at: datetime
    counts: Mapping[str, int]
    long_watch: tuple[SubingDailyWatchItem, ...]
    short_watch: tuple[SubingDailyWatchItem, ...]
    unavailable: tuple[SubingDailyWatchItem, ...]


@dataclass(frozen=True, slots=True)
class SubingDailyWatchCurrentResult:
    status: Literal["ready", "unavailable"]
    expected_target_trading_day: date | None
    latest_target_trading_day: date | None
    error_code: str | None
    snapshot: SubingDailyWatchWebSnapshot | None


class _StitchedLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        through: date,
        limit: int = 30,
    ) -> ActualDominantStitchedResearchSeries: ...


class _PublishResult(Protocol):
    @property
    def status(self) -> Literal["published", "idempotent"]: ...

    @property
    def target_trading_day(self) -> date: ...


class _DailyWatchStore(Protocol):
    def publish(
        self,
        snapshot: SubingDailyWatchSnapshot,
        *,
        started_at: datetime,
    ) -> _PublishResult: ...

    def read_current(self) -> SubingDailyWatchSnapshot | None: ...

    def record_failure(
        self,
        *,
        source_trading_day: date,
        target_trading_day: date | None,
        started_at: datetime,
        finished_at: datetime,
        error_code: str,
    ) -> None: ...


_GENERATION_FAILURE_CODES = frozenset(
    {
        "ACTIVE_OPERATIONAL_SCOPE_MISMATCH",
        "NEXT_TRADING_DAY_UNAVAILABLE",
        "OBSERVATION_ROOT_UNCONFIGURED",
        "OBSERVATION_ROOT_UNAVAILABLE",
        "OBSERVATION_ROOT_NOT_WRITABLE",
        "SNAPSHOT_INVALID",
        "SNAPSHOT_IDENTITY_CONFLICT",
        "CURRENT_TARGET_REGRESSION",
        "OBSERVATION_ATOMIC_WRITE_FAILED",
    }
)

_UNAVAILABLE_REASON_CODES = frozenset(
    {
        "D1_HISTORY_INSUFFICIENT",
        "H1_HISTORY_INSUFFICIENT",
        "SOURCE_TRADING_DAY_MISSING",
        "DOMINANT_SEGMENT_UNAVAILABLE",
        "DATA_IDENTITY_MISMATCH",
        "PRODUCT_METADATA_UNAVAILABLE",
    }
)

_FACTLESS_UNAVAILABLE_REASON_CODES = frozenset(
    {
        "SOURCE_TRADING_DAY_MISSING",
        "DOMINANT_SEGMENT_UNAVAILABLE",
        "DATA_IDENTITY_MISMATCH",
        "PRODUCT_METADATA_UNAVAILABLE",
    }
)


def classify_daily_watch(
    daily: SubingStitchedEmaTrendSnapshot,
    hourly: SubingStitchedEmaTrendSnapshot,
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
        stitched_loader: _StitchedLoader,
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
        self._stitched_loader = stitched_loader
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
        items = self._build_items(source_trading_day)
        return self._snapshot(
            source_trading_day=source_trading_day,
            target_trading_day=target_trading_day,
            generated_at=generated_at,
            items=items,
        )

    def build_at_completion(
        self,
        *,
        source_trading_day: date,
        target_trading_day: date,
        generated_at: Callable[[], datetime],
    ) -> SubingDailyWatchSnapshot:
        """Build the complete ledger before sampling its generation time."""
        items = self._build_items(source_trading_day)
        return self._snapshot(
            source_trading_day=source_trading_day,
            target_trading_day=target_trading_day,
            generated_at=generated_at(),
            items=items,
        )

    def _build_items(
        self,
        source_trading_day: date,
    ) -> tuple[SubingDailyWatchItem, ...]:
        return tuple(
            self._build_item(symbol, source_trading_day=source_trading_day)
            for symbol in self._products
        )

    def _snapshot(
        self,
        *,
        source_trading_day: date,
        target_trading_day: date,
        generated_at: datetime,
        items: tuple[SubingDailyWatchItem, ...],
    ) -> SubingDailyWatchSnapshot:
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
            loaded = self._stitched_loader.load(
                symbol=symbol,
                frequencies=(BarFrequency.D1, BarFrequency.H1),
                through=source_trading_day,
                limit=30,
            )
        except ActualDominantResearchSourceTradingDayMissingError:
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=("SOURCE_TRADING_DAY_MISSING",),
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

        if _source_trading_day_missing(
            loaded,
            source_trading_day=source_trading_day,
        ):
            return _unavailable_item(
                symbol,
                metadata=metadata,
                reasons=("SOURCE_TRADING_DAY_MISSING",),
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
        current_segment, daily_result, hourly_result = identity
        daily_bars = daily_result.bars
        hourly_bars = hourly_result.bars
        daily = calculate_subing_ema_trend_stitched(
            daily_bars,
            timeframe=BarFrequency.D1,
            current_contract=current_segment.contract,
            current_segment_start_trading_day=(current_segment.start_trading_day),
            resolved_contract_segments=(daily_result.resolved_contract_segments),
        )
        hourly = calculate_subing_ema_trend_stitched(
            hourly_bars,
            timeframe=BarFrequency.H1,
            current_contract=current_segment.contract,
            current_segment_start_trading_day=(current_segment.start_trading_day),
            resolved_contract_segments=(hourly_result.resolved_contract_segments),
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


class SubingDailyWatchGenerator:
    def __init__(
        self,
        *,
        builder: SubingDailyWatchBuilder,
        store: _DailyWatchStore,
        target_day: Callable[[date], date],
        clock: Callable[[], datetime],
    ) -> None:
        self.builder = builder
        self._store = store
        self._target_day = target_day
        self._clock = clock

    def run(self, source_trading_day: date) -> _PublishResult:
        started_at = self._clock()
        target_trading_day: date | None = None
        try:
            target_trading_day = self._target_day(source_trading_day)
            snapshot = self.builder.build_at_completion(
                source_trading_day=source_trading_day,
                target_trading_day=target_trading_day,
                generated_at=self._clock,
            )
            return self._store.publish(snapshot, started_at=started_at)
        except Exception as exc:
            error_code = getattr(exc, "code", None)
            if error_code in _GENERATION_FAILURE_CODES:
                finished_at = self._clock()
                try:
                    self._store.record_failure(
                        source_trading_day=source_trading_day,
                        target_trading_day=target_trading_day,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_code=error_code,
                    )
                except Exception:
                    pass
            raise


class SubingDailyWatchCurrentService:
    def __init__(
        self,
        *,
        products: tuple[str, ...],
        operational_products: tuple[str, ...],
        store_factory: Callable[[], _DailyWatchStore],
        expected_day: Callable[[datetime], date],
    ) -> None:
        self._products = products
        self._operational_products = operational_products
        self._store_factory = store_factory
        self._expected_day = expected_day

    def current(self, now: datetime) -> SubingDailyWatchCurrentResult:
        from .subing_daily_watch_calendar import SubingDailyWatchCalendarError
        from .subing_daily_watch_store import SubingDailyWatchStoreError

        if not _is_complete_scope(self._products, self._operational_products):
            return _current_unavailable("SUBING_DAILY_WATCH_INVALID")

        try:
            expected = self._expected_day(now)
        except SubingDailyWatchCalendarError as exc:
            if exc.code not in {
                "EXPECTED_TRADING_DAY_UNAVAILABLE",
                "OPERATIONAL_PRODUCT_EXCHANGE_UNAVAILABLE",
            }:
                raise
            return _current_unavailable("SUBING_DAILY_WATCH_EXPECTED_DAY_UNAVAILABLE")

        try:
            snapshot = self._store_factory().read_current()
        except SubingDailyWatchStoreError as exc:
            if exc.code in {
                "OBSERVATION_ROOT_UNCONFIGURED",
                "OBSERVATION_ROOT_UNAVAILABLE",
                "OBSERVATION_ROOT_NOT_WRITABLE",
            }:
                return _current_unavailable(
                    "SUBING_OBSERVATION_ROOT_UNAVAILABLE",
                    expected=expected,
                )
            if exc.code == "SNAPSHOT_INVALID":
                return _current_unavailable(
                    "SUBING_DAILY_WATCH_INVALID",
                    expected=expected,
                )
            raise

        if snapshot is None:
            return _current_unavailable(
                "SUBING_DAILY_WATCH_NOT_GENERATED",
                expected=expected,
            )
        if (
            len(snapshot.items) != 60
            or tuple(item.symbol for item in snapshot.items) != self._products
        ):
            return _current_unavailable(
                "SUBING_DAILY_WATCH_INVALID",
                expected=expected,
                latest=snapshot.target_trading_day,
            )
        if snapshot.target_trading_day != expected:
            return _current_unavailable(
                "SUBING_DAILY_WATCH_STALE",
                expected=expected,
                latest=snapshot.target_trading_day,
            )

        projection = SubingDailyWatchWebSnapshot(
            source_trading_day=snapshot.source_trading_day,
            target_trading_day=snapshot.target_trading_day,
            generated_at=snapshot.generated_at,
            counts=snapshot.counts,
            long_watch=tuple(
                item
                for item in snapshot.items
                if item.decision is SubingDailyWatchDecision.LONG_WATCH
            ),
            short_watch=tuple(
                item
                for item in snapshot.items
                if item.decision is SubingDailyWatchDecision.SHORT_WATCH
            ),
            unavailable=tuple(
                item
                for item in snapshot.items
                if item.decision is SubingDailyWatchDecision.UNAVAILABLE
            ),
        )
        return SubingDailyWatchCurrentResult(
            status="ready",
            expected_target_trading_day=expected,
            latest_target_trading_day=snapshot.target_trading_day,
            error_code=None,
            snapshot=projection,
        )


def _trend_direction(snapshot: SubingStitchedEmaTrendSnapshot) -> str:
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


def _price_side_matches_close(snapshot: SubingStitchedEmaTrendSnapshot) -> bool:
    if snapshot.close > snapshot.ema21:
        return snapshot.price_side is PriceSide.ABOVE
    if snapshot.close < snapshot.ema21:
        return snapshot.price_side is PriceSide.BELOW
    return snapshot.price_side is PriceSide.EQUAL


def _unavailable_reasons_match_facts(
    reasons: tuple[str, ...],
    *,
    daily: SubingStitchedEmaTrendSnapshot | None,
    hourly: SubingStitchedEmaTrendSnapshot | None,
) -> bool:
    reason_set = frozenset(reasons)
    if reason_set & _FACTLESS_UNAVAILABLE_REASON_CODES:
        return daily is None and hourly is None
    return (daily is None) == ("D1_HISTORY_INSUFFICIENT" in reason_set) and (
        hourly is None
    ) == ("H1_HISTORY_INSUFFICIENT" in reason_set)


def _validate_loaded_identity(
    loaded: ActualDominantStitchedResearchSeries,
    *,
    source_trading_day: date,
) -> (
    tuple[
        ResolvedContractSegment,
        MarketSeriesPageResult,
        MarketSeriesPageResult,
    ]
    | None
):
    current_segment = loaded.current_segment
    if not (
        current_segment.start_trading_day
        <= source_trading_day
        <= current_segment.end_trading_day
    ):
        return None
    daily = loaded.results.get(BarFrequency.D1)
    hourly = loaded.results.get(BarFrequency.H1)
    if daily is None or hourly is None:
        return None
    for result in (daily, hourly):
        if (
            not result.bars
            or result.bars[-1].trading_day != source_trading_day
            or any(bar.trading_day > source_trading_day for bar in result.bars)
        ):
            return None
        final_day = result.bars[-1].trading_day
        final_segments = tuple(
            segment
            for segment in result.resolved_contract_segments
            if segment.start_trading_day <= final_day <= segment.end_trading_day
        )
        if final_segments != (current_segment,):
            return None
    return current_segment, daily, hourly


def _source_trading_day_missing(
    loaded: ActualDominantStitchedResearchSeries,
    *,
    source_trading_day: date,
) -> bool:
    daily = loaded.results.get(BarFrequency.D1)
    hourly = loaded.results.get(BarFrequency.H1)
    return (
        daily is not None
        and hourly is not None
        and any(
            not result.bars or result.bars[-1].trading_day != source_trading_day
            for result in (daily, hourly)
        )
    )


def _history_unavailable_reasons(
    daily: SubingStitchedEmaTrendResult,
    hourly: SubingStitchedEmaTrendResult,
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
    daily: SubingStitchedEmaTrendSnapshot | None = None,
    hourly: SubingStitchedEmaTrendSnapshot | None = None,
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


def _current_unavailable(
    error_code: str,
    *,
    expected: date | None = None,
    latest: date | None = None,
) -> SubingDailyWatchCurrentResult:
    return SubingDailyWatchCurrentResult(
        status="unavailable",
        expected_target_trading_day=expected,
        latest_target_trading_day=latest,
        error_code=error_code,
        snapshot=None,
    )


def _is_complete_scope(
    products: tuple[str, ...],
    operational_products: tuple[str, ...],
) -> bool:
    return (
        len(products) == 60
        and len(operational_products) == 60
        and len(set(products)) == 60
        and len(set(operational_products)) == 60
        and set(products) == set(operational_products)
    )
