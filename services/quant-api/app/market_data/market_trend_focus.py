"""Pure, read-only Market Trend Focus V1 domain and snapshot reducer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import DominantContractSummary, MarketDataError
from app.market_data.market_radar import MarketRadarSnapshot, RadarItem
from app.market_data.market_read_service import MarketDisplaySnapshot


TrendDirection = Literal["long", "short"]
DailyTrendState = Literal["long", "short", "neutral"]
HourlyTrendState = Literal["continuation", "pullback", "reversal_block"]
TrendFocusStage = Literal[
    "setup",
    "breakout",
    "retest",
    "ready",
    "running",
    "weakening",
]
SwingKind = Literal["high", "low"]
SwingDirection = Literal["unresolved", "up", "down"]

SMA_PERIOD = 21
SMA_DIRECTION_BARS = SMA_PERIOD + 2
PRICE_HOT_THRESHOLD = Decimal("0.02")
VOLUME_HOT_THRESHOLD = Decimal("1.50")
VOLATILITY_HOT_THRESHOLD = Decimal("0.80")
D1_HISTORY_QUERY_LIMIT = 24
H1_HISTORY_QUERY_LIMIT = 23
M15_HISTORY_QUERY_LIMIT = 2000
M5_HISTORY_QUERY_LIMIT = 2000
MAX_ITEMS_PER_LIST = 10


@dataclass(frozen=True, slots=True)
class HotAdmission:
    available: bool
    current_hot: bool
    hot_count: int
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FocusBar:
    bar: CanonicalBar
    frequency: BarFrequency | str
    physical_contract: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "frequency", BarFrequency(self.frequency))
        object.__setattr__(self, "physical_contract", self.physical_contract.strip().upper())


@dataclass(frozen=True, slots=True)
class SwingPivot:
    kind: SwingKind
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    physical_contract: str
    epoch: int


@dataclass(frozen=True, slots=True)
class SwingResult:
    pivots: tuple[SwingPivot, ...]
    direction: SwingDirection
    epoch: int


@dataclass(frozen=True, slots=True)
class TrendRange:
    upper: Decimal
    lower: Decimal
    created_at: datetime
    epoch: int


@dataclass(frozen=True, slots=True)
class TrendTransition:
    stage: TrendFocusStage | None
    transition_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class TrendFocusState:
    direction: TrendDirection
    stage: TrendFocusStage
    physical_contract: str
    trend_range: TrendRange
    confirmation_count: int = 0
    breakout_at: datetime | None = None
    breakout_confirmed_at: datetime | None = None
    retest_held: bool = False
    retest_pivot: SwingPivot | None = None
    rebreak_reference: Decimal | None = None
    ready_at: datetime | None = None
    ready_invalidation: Decimal | None = None
    volume_confirmed: bool = False
    entry_reference: Decimal | None = None
    five_minute_confirmed: bool = False
    entry_confirmed_at: datetime | None = None
    running_at: datetime | None = None
    weakened_at: datetime | None = None
    recovery_reference: Decimal | None = None
    latest_swing_high: SwingPivot | None = None
    latest_swing_low: SwingPivot | None = None
    last_transition_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LifecycleReplay:
    state: TrendFocusState | None
    transitions: tuple[TrendTransition, ...]


@dataclass(frozen=True, slots=True)
class TrendFocusUnavailable:
    symbol: str | None
    code: str


@dataclass(frozen=True, slots=True)
class TrendFocusItem:
    symbol: str
    product_name: str
    sector: str
    physical_contract: str
    direction: TrendDirection
    stage: TrendFocusStage
    hot_conditions: tuple[str, ...]
    hot_count: int
    price_change_1d: Decimal | None
    volume_ratio20: Decimal | None
    atr14_percentile252: Decimal | None
    daily_volume_support: bool
    hourly_state: HourlyTrendState
    hourly_volume_support: bool
    range_upper: Decimal
    range_lower: Decimal
    confirmation_count: int
    retest_held: bool
    rebreak_reference: Decimal | None
    ready_invalidation: Decimal | None
    volume_confirmed: bool
    five_minute_confirmed: bool
    entry_confirmed_at: datetime | None
    latest_swing_high: Decimal | None
    latest_swing_low: Decimal | None
    next_level: Decimal | None
    invalidation_level: Decimal | None
    last_transition_at: datetime


@dataclass(frozen=True, slots=True)
class TrendFocusSnapshot:
    status: Literal["ready", "degraded"]
    observed_at: datetime
    long_opportunities: tuple[TrendFocusItem, ...]
    short_opportunities: tuple[TrendFocusItem, ...]
    running_trends: tuple[TrendFocusItem, ...]
    weakening_trends: tuple[TrendFocusItem, ...]
    unavailable: tuple[TrendFocusUnavailable, ...]


class MarketPageReader(Protocol):
    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult: ...


class MarketDisplayReader(Protocol):
    def display_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> MarketDisplaySnapshot: ...


class TrendFocusInputError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def daily_trend_state(bars: Sequence[CanonicalBar]) -> DailyTrendState:
    """Classify the latest completed D1 bars using exact SMA21 semantics."""
    if len(bars) < SMA_DIRECTION_BARS:
        return "neutral"
    closes = tuple(bar.close for bar in bars[-SMA_DIRECTION_BARS:])
    averages = tuple(
        sum(closes[offset : offset + SMA_PERIOD], start=Decimal(0)) / SMA_PERIOD
        for offset in range(3)
    )
    latest_close = closes[-1]
    if latest_close > averages[-1] and averages[-1] > averages[-2] > averages[-3]:
        return "long"
    if latest_close < averages[-1] and averages[-1] < averages[-2] < averages[-3]:
        return "short"
    return "neutral"


def hourly_trend_state(
    bars: Sequence[CanonicalBar],
    direction: TrendDirection,
) -> HourlyTrendState:
    """Classify the current 60m environment relative to the D1 direction."""
    state = daily_trend_state(bars)
    if state == direction:
        return "continuation"
    if state != "neutral":
        return "reversal_block"
    return "pullback"


def evaluate_hot_admission(
    *,
    price_change_1d: Decimal | None,
    volume_ratio20: Decimal | None,
    atr14_percentile252: Decimal | None,
) -> HotAdmission:
    """Evaluate the exact price/volume/volatility Hot 2-of-3 gate."""
    if (
        price_change_1d is None
        or volume_ratio20 is None
        or atr14_percentile252 is None
    ):
        return HotAdmission(False, False, 0, ())
    conditions: list[str] = []
    if abs(price_change_1d) >= PRICE_HOT_THRESHOLD:
        conditions.append("price_move_up" if price_change_1d >= 0 else "price_move_down")
    if volume_ratio20 >= VOLUME_HOT_THRESHOLD:
        conditions.append("volume_expansion")
    if atr14_percentile252 >= VOLATILITY_HOT_THRESHOLD:
        conditions.append("high_volatility")
    return HotAdmission(True, len(conditions) >= 2, len(conditions), tuple(conditions))


def volume_support(bars: Sequence[CanonicalBar]) -> bool:
    """Return whether the latest completed volume is no smaller than its predecessor."""
    return len(bars) >= 2 and bars[-1].volume >= bars[-2].volume


def reduce_swings(
    bars: Sequence[FocusBar],
    *,
    observed_at: datetime,
) -> SwingResult:
    """Replay the private causal swing reducer over one exact contract and frequency."""
    values = tuple(bars)
    if not values:
        return SwingResult((), "unresolved", 0)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise TrendFocusInputError("OBSERVED_AT_TIMEZONE_REQUIRED")
    cutoff = observed_at.astimezone(UTC)
    frequency = values[0].frequency
    contract = values[0].physical_contract
    if frequency not in {BarFrequency.M5, BarFrequency.M15}:
        raise TrendFocusInputError("FREQUENCY_UNSUPPORTED")
    previous_end: datetime | None = None
    for value in values:
        if value.frequency != frequency:
            raise TrendFocusInputError("FREQUENCY_MISMATCH")
        if value.physical_contract != contract:
            raise TrendFocusInputError("PHYSICAL_CONTRACT_MISMATCH")
        if previous_end is not None and value.bar.bar_end <= previous_end:
            raise TrendFocusInputError("BAR_ORDER_INVALID")
        if value.bar.bar_end > cutoff:
            raise TrendFocusInputError("INCOMPLETE_BAR")
        previous_end = value.bar.bar_end

    direction: SwingDirection = "unresolved"
    epoch = 0
    running_extreme: FocusBar | None = None
    pivots: list[SwingPivot] = []
    for previous, current in zip(values, values[1:]):
        if current.bar.high > previous.bar.high and current.bar.low < previous.bar.low:
            epoch += 1
            direction = "unresolved"
            running_extreme = None
            continue

        if direction == "unresolved":
            if current.bar.high > previous.bar.high and current.bar.low >= previous.bar.low:
                direction = "up"
                running_extreme = current
            elif current.bar.low < previous.bar.low and current.bar.high <= previous.bar.high:
                direction = "down"
                running_extreme = current
            continue

        if direction == "up":
            if current.bar.low >= previous.bar.low:
                if running_extreme is None or current.bar.high > running_extreme.bar.high:
                    running_extreme = current
                continue
            assert running_extreme is not None
            pivots.append(
                SwingPivot(
                    "high",
                    running_extreme.bar.bar_end,
                    current.bar.bar_end,
                    running_extreme.bar.high,
                    contract,
                    epoch,
                )
            )
            direction = "down"
            running_extreme = current
            continue

        if current.bar.high <= previous.bar.high:
            if running_extreme is None or current.bar.low < running_extreme.bar.low:
                running_extreme = current
            continue
        assert running_extreme is not None
        pivots.append(
            SwingPivot(
                "low",
                running_extreme.bar.bar_end,
                current.bar.bar_end,
                running_extreme.bar.low,
                contract,
                epoch,
            )
        )
        direction = "up"
        running_extreme = current
    return SwingResult(tuple(pivots), direction, epoch)


def replay_trend_focus(
    direction: TrendDirection,
    bars_15m: Sequence[FocusBar],
    bars_5m: Sequence[FocusBar],
    *,
    observed_at: datetime,
) -> LifecycleReplay:
    """Build private causal pivots and replay the complete current lifecycle."""
    fifteen = tuple(bars_15m)
    five = tuple(bars_5m)
    fifteen_swings = reduce_swings(fifteen, observed_at=observed_at)
    five_swings = (
        reduce_swings(five, observed_at=observed_at)
        if five
        else SwingResult((), "unresolved", 0)
    )
    return replay_lifecycle(
        direction,
        fifteen,
        fifteen_swings.pivots,
        bars_5m=five,
        pivots_5m=five_swings.pivots,
    )


def replay_lifecycle(
    direction: TrendDirection,
    bars_15m: Sequence[FocusBar],
    pivots_15m: Sequence[SwingPivot],
    *,
    bars_5m: Sequence[FocusBar] = (),
    pivots_5m: Sequence[SwingPivot] = (),
) -> LifecycleReplay:
    """Replay the exact 15m lifecycle and its bounded 5m entry window."""
    bars = tuple(bars_15m)
    pivots = tuple(pivots_15m)
    if not bars:
        return LifecycleReplay(None, ())
    contract = bars[0].physical_contract
    _validate_lifecycle_input(bars, pivots, contract, BarFrequency.M15)
    five_bars = tuple(bars_5m)
    five_pivots = tuple(pivots_5m)
    if five_bars:
        _validate_lifecycle_input(five_bars, five_pivots, contract, BarFrequency.M5)
    elif five_pivots:
        raise TrendFocusInputError("FIVE_MINUTE_BARS_MISSING")
    pivots_at: dict[datetime, list[SwingPivot]] = {}
    for pivot in pivots:
        pivots_at.setdefault(pivot.confirmed_at, []).append(pivot)
    five_pivots_at: dict[datetime, list[SwingPivot]] = {}
    for pivot in five_pivots:
        five_pivots_at.setdefault(pivot.confirmed_at, []).append(pivot)

    known_pivots: list[SwingPivot] = []
    known_five_pivots: list[SwingPivot] = []
    transitions: list[TrendTransition] = []
    state: TrendFocusState | None = None
    eligible_after: datetime | None = None
    five_index = 0

    def advance_five_before(cutoff: datetime | None) -> None:
        nonlocal five_index, state
        while five_index < len(five_bars) and (
            cutoff is None or five_bars[five_index].bar.bar_end < cutoff
        ):
            five_bar = five_bars[five_index]
            for pivot in five_pivots_at.get(five_bar.bar.bar_end, ()):
                known_five_pivots.append(pivot)
            previous = five_bars[five_index - 1] if five_index > 0 else None
            state = _advance_five_minute_entry(
                state,
                direction=direction,
                bar=five_bar,
                previous=previous,
                known_pivots=known_five_pivots,
                transitions=transitions,
            )
            five_index += 1

    for index, bar in enumerate(bars):
        advance_five_before(bar.bar.bar_end)
        new_pivots = tuple(pivots_at.get(bar.bar.bar_end, ()))
        for pivot in new_pivots:
            known_pivots.append(pivot)
            if state is not None:
                if pivot.kind == "high":
                    state = replace(state, latest_swing_high=pivot)
                else:
                    state = replace(state, latest_swing_low=pivot)

        created_now = False
        if state is None:
            trend_range = _latest_converging_range(known_pivots, eligible_after=eligible_after)
            if trend_range is not None:
                state = TrendFocusState(
                    direction=direction,
                    stage="setup",
                    physical_contract=contract,
                    trend_range=trend_range,
                    latest_swing_high=_latest_pivot(known_pivots, "high"),
                    latest_swing_low=_latest_pivot(known_pivots, "low"),
                    last_transition_at=trend_range.created_at,
                )
                transitions.append(
                    TrendTransition("setup", trend_range.created_at, "range_confirmed")
                )
                created_now = True
        if state is None or created_now:
            continue

        close = bar.bar.close
        upper = state.trend_range.upper
        lower = state.trend_range.lower
        if state.stage == "setup":
            invalid = close < lower if direction == "long" else close > upper
            if invalid:
                transitions.append(
                    TrendTransition(None, bar.bar.bar_end, "setup_invalidated")
                )
                state = None
                eligible_after = bar.bar.bar_end
                continue
            breakout = close > upper if direction == "long" else close < lower
            if breakout:
                state = replace(
                    state,
                    stage="breakout",
                    confirmation_count=0,
                    breakout_at=bar.bar.bar_end,
                    last_transition_at=bar.bar.bar_end,
                )
                transitions.append(
                    TrendTransition("breakout", bar.bar.bar_end, "range_breakout")
                )
            continue

        if state.stage == "breakout":
            assert state.breakout_at is not None
            if bar.bar.bar_end == state.breakout_at:
                continue
            held = close > upper if direction == "long" else close < lower
            if not held:
                transitions.append(
                    TrendTransition(None, bar.bar.bar_end, "breakout_confirmation_failed")
                )
                state = None
                eligible_after = bar.bar.bar_end
                continue
            count = state.confirmation_count + 1
            if count == 3:
                state = replace(
                    state,
                    stage="retest",
                    confirmation_count=3,
                    breakout_confirmed_at=bar.bar.bar_end,
                    last_transition_at=bar.bar.bar_end,
                )
                transitions.append(
                    TrendTransition("retest", bar.bar.bar_end, "breakout_confirmed")
                )
            else:
                state = replace(state, confirmation_count=count)
            continue

        if state.stage == "retest":
            hard_invalid = close <= upper if direction == "long" else close >= lower
            if hard_invalid:
                transitions.append(
                    TrendTransition(None, bar.bar.bar_end, "retest_range_invalidated")
                )
                state = None
                eligible_after = bar.bar.bar_end
                continue
            if not state.retest_held:
                pair = _retest_pair(
                    known_pivots,
                    direction=direction,
                    after=state.breakout_at,
                )
                if pair is not None and pair[1].confirmed_at <= bar.bar.bar_end:
                    reference, retest_pivot = pair
                    state = replace(
                        state,
                        retest_held=True,
                        retest_pivot=retest_pivot,
                        rebreak_reference=reference.price,
                    )
            if (
                state.retest_held
                and state.retest_pivot is not None
                and state.rebreak_reference is not None
                and bar.bar.bar_end > state.retest_pivot.confirmed_at
            ):
                rebroken = (
                    close > state.rebreak_reference
                    if direction == "long"
                    else close < state.rebreak_reference
                )
                if rebroken:
                    previous_volume = bars[index - 1].bar.volume if index > 0 else None
                    state = replace(
                        state,
                        stage="ready",
                        ready_at=bar.bar.bar_end,
                        ready_invalidation=state.retest_pivot.price,
                        volume_confirmed=(
                            previous_volume is not None
                            and bar.bar.volume >= previous_volume * 2
                        ),
                        five_minute_confirmed=False,
                        entry_confirmed_at=None,
                        last_transition_at=bar.bar.bar_end,
                    )
                    transitions.append(
                        TrendTransition("ready", bar.bar.bar_end, "retest_rebreak")
                    )
            continue

        if state.stage == "ready":
            assert state.ready_invalidation is not None
            hard_invalid = close <= upper if direction == "long" else close >= lower
            pivot_invalid = (
                close < state.ready_invalidation
                if direction == "long"
                else close > state.ready_invalidation
            )
            if hard_invalid or pivot_invalid:
                transitions.append(
                    TrendTransition(None, bar.bar.bar_end, "ready_invalidated")
                )
                state = None
                eligible_after = bar.bar.bar_end
                continue
            assert state.ready_at is not None
            closing_kind: SwingKind = "high" if direction == "long" else "low"
            closing_pivot = next(
                (
                    pivot
                    for pivot in new_pivots
                    if pivot.kind == closing_kind
                    and pivot.confirmed_at > state.ready_at
                ),
                None,
            )
            if closing_pivot is not None:
                state = replace(
                    state,
                    stage="running",
                    running_at=closing_pivot.confirmed_at,
                    five_minute_confirmed=False,
                    last_transition_at=closing_pivot.confirmed_at,
                )
                transitions.append(
                    TrendTransition(
                        "running",
                        closing_pivot.confirmed_at,
                        "entry_window_closed_by_15m",
                    )
                )
            continue

        if state.stage == "running":
            defended = (
                state.latest_swing_low
                if direction == "long"
                else state.latest_swing_high
            )
            if defended is None:
                continue
            weakened = close < defended.price if direction == "long" else close > defended.price
            if weakened:
                state = replace(
                    state,
                    stage="weakening",
                    weakened_at=bar.bar.bar_end,
                    last_transition_at=bar.bar.bar_end,
                )
                transitions.append(
                    TrendTransition("weakening", bar.bar.bar_end, "defense_broken")
                )
            continue

        if state.stage == "weakening":
            recovery_reference = _recovery_reference(
                known_pivots,
                direction=direction,
                after=state.weakened_at,
            )
            if recovery_reference is None:
                continue
            state = replace(state, recovery_reference=recovery_reference.price)
            if bar.bar.bar_end <= recovery_reference.confirmed_at:
                continue
            recovered = (
                close > recovery_reference.price
                if direction == "long"
                else close < recovery_reference.price
            )
            if recovered:
                state = replace(
                    state,
                    stage="running",
                    running_at=bar.bar.bar_end,
                    last_transition_at=bar.bar.bar_end,
                )
                transitions.append(
                    TrendTransition("running", bar.bar.bar_end, "trend_recovered")
                )
    advance_five_before(None)
    return LifecycleReplay(state, tuple(transitions))


def _validate_lifecycle_input(
    bars: tuple[FocusBar, ...],
    pivots: tuple[SwingPivot, ...],
    contract: str,
    frequency: BarFrequency,
) -> None:
    previous_end: datetime | None = None
    bar_ends = {bar.bar.bar_end for bar in bars}
    for bar in bars:
        if bar.frequency is not frequency:
            raise TrendFocusInputError("FREQUENCY_UNSUPPORTED")
        if bar.physical_contract != contract:
            raise TrendFocusInputError("PHYSICAL_CONTRACT_MISMATCH")
        if previous_end is not None and bar.bar.bar_end <= previous_end:
            raise TrendFocusInputError("BAR_ORDER_INVALID")
        previous_end = bar.bar.bar_end
    previous_confirmation: datetime | None = None
    for pivot in pivots:
        if pivot.physical_contract != contract:
            raise TrendFocusInputError("PHYSICAL_CONTRACT_MISMATCH")
        if pivot.pivot_time >= pivot.confirmed_at:
            raise TrendFocusInputError("PIVOT_CAUSALITY_INVALID")
        if pivot.confirmed_at not in bar_ends:
            continue
        if previous_confirmation is not None and pivot.confirmed_at < previous_confirmation:
            raise TrendFocusInputError("PIVOT_ORDER_INVALID")
        previous_confirmation = pivot.confirmed_at


def _latest_converging_range(
    pivots: Sequence[SwingPivot],
    *,
    eligible_after: datetime | None,
) -> TrendRange | None:
    eligible = tuple(
        pivot
        for pivot in pivots
        if (eligible_after is None or pivot.confirmed_at > eligible_after)
    )
    if not eligible:
        return None
    epoch = eligible[-1].epoch
    same_epoch = tuple(pivot for pivot in eligible if pivot.epoch == epoch)
    if len(same_epoch) < 4:
        return None
    candidate = same_epoch[-4:]
    kinds = tuple(pivot.kind for pivot in candidate)
    if kinds == ("high", "low", "high", "low"):
        high_one, low_one, high_two, low_two = candidate
    elif kinds == ("low", "high", "low", "high"):
        low_one, high_one, low_two, high_two = candidate
    else:
        return None
    if high_two.price > high_one.price or low_two.price < low_one.price:
        return None
    return TrendRange(
        upper=max(high_one.price, high_two.price),
        lower=min(low_one.price, low_two.price),
        created_at=max(pivot.confirmed_at for pivot in candidate),
        epoch=epoch,
    )


def _latest_pivot(
    pivots: Sequence[SwingPivot],
    kind: SwingKind,
) -> SwingPivot | None:
    return next((pivot for pivot in reversed(pivots) if pivot.kind == kind), None)


def _retest_pair(
    pivots: Sequence[SwingPivot],
    *,
    direction: TrendDirection,
    after: datetime | None,
) -> tuple[SwingPivot, SwingPivot] | None:
    if after is None:
        return None
    eligible = tuple(pivot for pivot in pivots if pivot.confirmed_at > after)
    reference_kind: SwingKind = "high" if direction == "long" else "low"
    retest_kind: SwingKind = "low" if direction == "long" else "high"
    for reference, retest in reversed(tuple(zip(eligible, eligible[1:]))):
        if reference.kind == reference_kind and retest.kind == retest_kind:
            return reference, retest
    return None


def _advance_five_minute_entry(
    state: TrendFocusState | None,
    *,
    direction: TrendDirection,
    bar: FocusBar,
    previous: FocusBar | None,
    known_pivots: Sequence[SwingPivot],
    transitions: list[TrendTransition],
) -> TrendFocusState | None:
    if state is None or state.stage != "ready" or state.ready_at is None:
        return state
    reference_kind: SwingKind = "high" if direction == "long" else "low"
    reference = next(
        (
            pivot
            for pivot in reversed(known_pivots)
            if pivot.kind == reference_kind
            and pivot.pivot_time > state.ready_at
            and pivot.confirmed_at > state.ready_at
            and pivot.confirmed_at <= bar.bar.bar_end
        ),
        None,
    )
    if reference is None or previous is None or bar.bar.bar_end <= reference.confirmed_at:
        return state
    state = replace(state, entry_reference=reference.price)
    price_confirmed = (
        bar.bar.close > reference.price
        if direction == "long"
        else bar.bar.close < reference.price
    )
    if not price_confirmed or bar.bar.volume < previous.bar.volume * 2:
        return state
    transitions.append(
        TrendTransition("running", bar.bar.bar_end, "five_minute_confirmed")
    )
    return replace(
        state,
        stage="running",
        five_minute_confirmed=True,
        entry_confirmed_at=bar.bar.bar_end,
        running_at=bar.bar.bar_end,
        last_transition_at=bar.bar.bar_end,
    )


def _recovery_reference(
    pivots: Sequence[SwingPivot],
    *,
    direction: TrendDirection,
    after: datetime | None,
) -> SwingPivot | None:
    if after is None:
        return None
    eligible = tuple(pivot for pivot in pivots if pivot.confirmed_at > after)
    first_kind: SwingKind = "low" if direction == "long" else "high"
    reference_kind: SwingKind = "high" if direction == "long" else "low"
    for first, reference in reversed(tuple(zip(eligible, eligible[1:]))):
        if first.kind == first_kind and reference.kind == reference_kind:
            return reference
    return None


class _SnapshotSymbolError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_market_trend_focus_snapshot(
    *,
    radar_snapshot: MarketRadarSnapshot,
    market_data: MarketPageReader,
    market_read: MarketDisplayReader,
    dominants: Mapping[str, DominantContractSummary],
    now: datetime,
) -> TrendFocusSnapshot:
    """Recompute the active-universe Trend Focus read model without persistence."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise TrendFocusInputError("OBSERVED_AT_TIMEZONE_REQUIRED")
    observed_at = now.astimezone(UTC)
    if radar_snapshot.freshness_state == "degraded":
        return TrendFocusSnapshot(
            status="degraded",
            observed_at=observed_at,
            long_opportunities=(),
            short_opportunities=(),
            running_trends=(),
            weakening_trends=(),
            unavailable=(TrendFocusUnavailable(None, "RADAR_DEGRADED"),),
        )

    opportunities: dict[TrendDirection, list[TrendFocusItem]] = {
        "long": [],
        "short": [],
    }
    running: list[TrendFocusItem] = []
    weakening: list[TrendFocusItem] = []
    unavailable: list[TrendFocusUnavailable] = []
    for radar_item in sorted(radar_snapshot.items, key=lambda item: item.symbol):
        hot = evaluate_hot_admission(
            price_change_1d=radar_item.metrics.price_change_1d,
            volume_ratio20=radar_item.metrics.volume_ratio20,
            atr14_percentile252=radar_item.metrics.atr14_percentile252,
        )
        if not hot.available:
            unavailable.append(
                TrendFocusUnavailable(radar_item.symbol, "HOT_METRIC_UNAVAILABLE")
            )
        try:
            daily = _daily_bars(
                radar_item,
                radar_snapshot=radar_snapshot,
                market_data=market_data,
                observed_at=observed_at,
            )
            direction = daily_trend_state(daily)
            if direction == "neutral":
                continue
            dominant = dominants.get(radar_item.symbol)
            if dominant is None:
                raise _SnapshotSymbolError("PHYSICAL_CONTRACT_UNAVAILABLE")
            contract = dominant.actual_contract
            hourly = _contract_focus_bars(
                symbol=radar_item.symbol,
                contract=contract,
                frequency=BarFrequency.H1,
                limit=H1_HISTORY_QUERY_LIMIT,
                market_data=market_data,
                market_read=market_read,
                observed_at=observed_at,
            )
            if len(hourly) < SMA_DIRECTION_BARS:
                raise _SnapshotSymbolError("HOURLY_HISTORY_INSUFFICIENT")
            hourly_bars = tuple(item.bar for item in hourly)
            hourly_state = hourly_trend_state(hourly_bars, direction)
            if hourly_state == "reversal_block":
                continue
            fifteen = _contract_focus_bars(
                symbol=radar_item.symbol,
                contract=contract,
                frequency=BarFrequency.M15,
                limit=M15_HISTORY_QUERY_LIMIT,
                market_data=market_data,
                market_read=market_read,
                observed_at=observed_at,
            )
            five = _contract_focus_bars(
                symbol=radar_item.symbol,
                contract=contract,
                frequency=BarFrequency.M5,
                limit=M5_HISTORY_QUERY_LIMIT,
                market_data=market_data,
                market_read=market_read,
                observed_at=observed_at,
            )
            replay = replay_trend_focus(
                direction,
                fifteen,
                five,
                observed_at=observed_at,
            )
            if replay.state is None:
                continue
            item = _focus_item(
                radar_item,
                hot=hot,
                state=replay.state,
                daily_volume_support=volume_support(daily),
                hourly_state=hourly_state,
                hourly_volume_support=volume_support(hourly_bars),
            )
        except _SnapshotSymbolError as exc:
            unavailable.append(TrendFocusUnavailable(radar_item.symbol, exc.code))
            continue
        except (MarketDataError, TrendFocusInputError):
            unavailable.append(
                TrendFocusUnavailable(radar_item.symbol, "BAR_IDENTITY_UNAVAILABLE")
            )
            continue

        if item.stage in {"setup", "breakout", "retest", "ready"}:
            if hot.available and hot.current_hot:
                opportunities[direction].append(item)
        elif item.stage == "running":
            running.append(item)
        elif item.stage == "weakening":
            weakening.append(item)

    return TrendFocusSnapshot(
        status="ready",
        observed_at=observed_at,
        long_opportunities=sort_opportunities(opportunities["long"]),
        short_opportunities=sort_opportunities(opportunities["short"]),
        running_trends=tuple(sorted(running, key=_tracking_sort_key)),
        weakening_trends=tuple(sorted(weakening, key=_tracking_sort_key)),
        unavailable=tuple(
            sorted(unavailable, key=lambda item: (item.symbol or "", item.code))
        ),
    )


def _daily_bars(
    item: RadarItem,
    *,
    radar_snapshot: MarketRadarSnapshot,
    market_data: MarketPageReader,
    observed_at: datetime,
) -> tuple[CanonicalBar, ...]:
    try:
        page = market_data.query_page(
            SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT,
                item.symbol,
                BarFrequency.D1,
                limit=D1_HISTORY_QUERY_LIMIT,
            )
        )
    except MarketDataError as exc:
        raise _SnapshotSymbolError("D1_HISTORY_UNAVAILABLE") from exc
    values = tuple(
        bar for bar in page.bars if bar.trading_day <= radar_snapshot.data_as_of
    )[-SMA_DIRECTION_BARS:]
    if len(values) < SMA_DIRECTION_BARS:
        raise _SnapshotSymbolError("D1_HISTORY_INSUFFICIENT")
    _validate_canonical_bars(values, observed_at=observed_at)
    return values


def _contract_focus_bars(
    *,
    symbol: str,
    contract: str,
    frequency: BarFrequency,
    limit: int,
    market_data: MarketPageReader,
    market_read: MarketDisplayReader,
    observed_at: datetime,
) -> tuple[FocusBar, ...]:
    request = SeriesPageQuery(
        SeriesKind.CONTRACT,
        symbol,
        frequency,
        limit=limit,
        contract=contract,
    )
    try:
        page = market_data.query_page(request)
    except MarketDataError as exc:
        raise _SnapshotSymbolError("INTRADAY_HISTORY_UNAVAILABLE") from exc
    historical = tuple(page.bars)
    if not historical:
        raise _SnapshotSymbolError("INTRADAY_HISTORY_UNAVAILABLE")
    _validate_canonical_bars(historical, observed_at=observed_at)
    display = market_read.display_snapshot(request, historical[-1].bar_end, observed_at)
    phase = display.state.phase
    if phase in {"TRADING", "BREAK"}:
        if display.state.live_contract != contract:
            raise _SnapshotSymbolError("LIVE_CONTRACT_MISMATCH")
        if (
            not display.state.live_eligible
            or not display.state.live_available
            or display.source != "realtime"
        ):
            raise _SnapshotSymbolError("LIVE_UNAVAILABLE")
    elif phase == "UNKNOWN":
        raise _SnapshotSymbolError("MARKET_PHASE_UNAVAILABLE")
    elif phase != "CLOSED":
        raise _SnapshotSymbolError("MARKET_PHASE_UNAVAILABLE")
    if display.source != "none" and display.contract != contract:
        raise _SnapshotSymbolError("LIVE_CONTRACT_MISMATCH")
    _validate_canonical_bars(display.bars, observed_at=observed_at)
    merged = {bar.bar_end: bar for bar in historical}
    for bar in display.bars:
        merged.setdefault(bar.bar_end, bar)
    values = tuple(merged[key] for key in sorted(merged))[-limit:]
    _validate_canonical_bars(values, observed_at=observed_at)
    return tuple(FocusBar(bar, frequency, contract) for bar in values)


def _validate_canonical_bars(
    bars: Sequence[CanonicalBar],
    *,
    observed_at: datetime,
) -> None:
    previous: datetime | None = None
    for bar in bars:
        if previous is not None and bar.bar_end <= previous:
            raise TrendFocusInputError("BAR_ORDER_INVALID")
        if bar.bar_end > observed_at:
            raise TrendFocusInputError("INCOMPLETE_BAR")
        previous = bar.bar_end


def _focus_item(
    radar_item: RadarItem,
    *,
    hot: HotAdmission,
    state: TrendFocusState,
    daily_volume_support: bool,
    hourly_state: HourlyTrendState,
    hourly_volume_support: bool,
) -> TrendFocusItem:
    next_level, invalidation_level = _levels(state)
    assert state.last_transition_at is not None
    return TrendFocusItem(
        symbol=radar_item.symbol,
        product_name=radar_item.product_name,
        sector=radar_item.sector,
        physical_contract=state.physical_contract,
        direction=state.direction,
        stage=state.stage,
        hot_conditions=hot.conditions,
        hot_count=hot.hot_count,
        price_change_1d=radar_item.metrics.price_change_1d,
        volume_ratio20=radar_item.metrics.volume_ratio20,
        atr14_percentile252=radar_item.metrics.atr14_percentile252,
        daily_volume_support=daily_volume_support,
        hourly_state=hourly_state,
        hourly_volume_support=hourly_volume_support,
        range_upper=state.trend_range.upper,
        range_lower=state.trend_range.lower,
        confirmation_count=state.confirmation_count,
        retest_held=state.retest_held,
        rebreak_reference=state.rebreak_reference,
        ready_invalidation=state.ready_invalidation,
        volume_confirmed=state.volume_confirmed,
        five_minute_confirmed=state.five_minute_confirmed,
        entry_confirmed_at=state.entry_confirmed_at,
        latest_swing_high=(state.latest_swing_high.price if state.latest_swing_high else None),
        latest_swing_low=(state.latest_swing_low.price if state.latest_swing_low else None),
        next_level=next_level,
        invalidation_level=invalidation_level,
        last_transition_at=state.last_transition_at,
    )


def _levels(state: TrendFocusState) -> tuple[Decimal | None, Decimal | None]:
    upper = state.trend_range.upper
    lower = state.trend_range.lower
    if state.stage == "setup":
        return (upper, lower) if state.direction == "long" else (lower, upper)
    if state.stage == "breakout":
        return (upper, upper) if state.direction == "long" else (lower, lower)
    if state.stage == "retest":
        return state.rebreak_reference, upper if state.direction == "long" else lower
    if state.stage == "ready":
        assert state.ready_invalidation is not None
        invalidation = (
            max(upper, state.ready_invalidation)
            if state.direction == "long"
            else min(lower, state.ready_invalidation)
        )
        return state.entry_reference, invalidation
    defended = state.latest_swing_low if state.direction == "long" else state.latest_swing_high
    if state.stage == "weakening":
        return state.recovery_reference, defended.price if defended else None
    return None, defended.price if defended else None


def _opportunity_sort_key(item: TrendFocusItem) -> tuple[object, ...]:
    stage_rank = {"ready": 4, "retest": 3, "breakout": 2, "setup": 1}
    stage_specific = (
        int(item.five_minute_confirmed)
        if item.stage == "ready"
        else int(item.retest_held)
        if item.stage == "retest"
        else item.confirmation_count
        if item.stage == "breakout"
        else 0
    )
    return (
        -stage_rank[item.stage],
        -stage_specific,
        -int(item.volume_confirmed),
        -(int(item.daily_volume_support) + int(item.hourly_volume_support)),
        -item.hot_count,
        -abs(item.price_change_1d or Decimal(0)),
        -(item.volume_ratio20 or Decimal(0)),
        -(item.atr14_percentile252 or Decimal(0)),
        item.symbol,
    )


def sort_opportunities(
    items: Sequence[TrendFocusItem],
) -> tuple[TrendFocusItem, ...]:
    """Apply the public deterministic tuple order and exact per-side cap."""
    return tuple(sorted(items, key=_opportunity_sort_key)[:MAX_ITEMS_PER_LIST])


def _tracking_sort_key(item: TrendFocusItem) -> tuple[float, str]:
    return (-item.last_transition_at.timestamp(), item.symbol)
