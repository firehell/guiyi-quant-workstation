"""Pure, read-only Market Trend Focus V1 domain and snapshot reducer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from app.market_data.domain import BarFrequency, CanonicalBar


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
    five_minute_confirmed: bool = False
    entry_confirmed_at: datetime | None = None
    running_at: datetime | None = None
    weakened_at: datetime | None = None
    latest_swing_high: SwingPivot | None = None
    latest_swing_low: SwingPivot | None = None
    last_transition_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LifecycleReplay:
    state: TrendFocusState | None
    transitions: tuple[TrendTransition, ...]


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


def replay_lifecycle(
    direction: TrendDirection,
    bars_15m: Sequence[FocusBar],
    pivots_15m: Sequence[SwingPivot],
) -> LifecycleReplay:
    """Replay the exact 15m Range lifecycle from causal bars and confirmed pivots."""
    bars = tuple(bars_15m)
    pivots = tuple(pivots_15m)
    if not bars:
        return LifecycleReplay(None, ())
    contract = bars[0].physical_contract
    _validate_lifecycle_input(bars, pivots, contract)
    pivots_at: dict[datetime, list[SwingPivot]] = {}
    for pivot in pivots:
        pivots_at.setdefault(pivot.confirmed_at, []).append(pivot)

    known_pivots: list[SwingPivot] = []
    transitions: list[TrendTransition] = []
    state: TrendFocusState | None = None
    eligible_after: datetime | None = None
    for index, bar in enumerate(bars):
        for pivot in pivots_at.get(bar.bar.bar_end, ()):
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
    return LifecycleReplay(state, tuple(transitions))


def _validate_lifecycle_input(
    bars: tuple[FocusBar, ...],
    pivots: tuple[SwingPivot, ...],
    contract: str,
) -> None:
    previous_end: datetime | None = None
    bar_ends = {bar.bar.bar_end for bar in bars}
    for bar in bars:
        if bar.frequency is not BarFrequency.M15:
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
