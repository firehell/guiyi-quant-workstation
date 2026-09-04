"""Typed reproduction of Newow v3.2.82 composite page decisions.

The page-exact identity intentionally preserves the observed unreachable
``warning-*`` branches.  The clean-room identity corrects that control-flow
defect without changing the page-parity result type.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

from .research_backtest import NewowResearchBar, validate_research_bars


COMPOSITE_DECISION_PAGE_V3282 = "newow_composite_decision_page_v3_2_82"
COMPOSITE_DECISION_CLEANROOM_V1 = "newow_composite_decision_cleanroom_v1"
FIRST_ACTION_PRINCIPLE_PAGE_V3263 = (
    "newow_first_action_principle_page_v3_2_63"
)
PAGE_UNREACHABLE_DECISION_KEYS = (
    "warning-bullish",
    "warning-bearish",
    "warning-neutral",
)


class TrendSignal(StrEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    WAIT = "wait"
    IDLE = "idle"


class OscillationStatus(StrEnum):
    HOLDING = "holding"
    CLEARED = "cleared"
    IDLE = "idle"


class TrendBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    CAUTIOUS = "cautious"
    WARNING = "warning"
    NEUTRAL = "neutral"


class OscillationBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class CompositeAction(StrEnum):
    BUILD_OR_ADD = "BUILD_OR_ADD"
    HOLD_AND_WAIT = "HOLD_AND_WAIT"
    REDUCE_AND_WAIT = "REDUCE_AND_WAIT"
    CLEAR = "CLEAR"
    CAUTIOUS_HOLD = "CAUTIOUS_HOLD"
    WAIT_FOR_SIGNAL = "WAIT_FOR_SIGNAL"


class DirectionToken(StrEnum):
    WEEKLY_BEARISH_REBOUND = "weekly_bearish_rebound"
    WEEKLY_BEARISH = "weekly_bearish"
    DAILY_PULLBACK = "daily_pullback"
    SIXTY_MINUTE_PULLBACK = "sixty_minute_pullback"
    MULTIPERIOD_BULLISH = "multiperiod_bullish"
    INSUFFICIENT = "insufficient"


class VolatilityLevel(StrEnum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class PrincipleLevel(StrEnum):
    VIOLATE = "violate"
    WARN = "warn"
    OK = "ok"


@dataclass(frozen=True, slots=True)
class PositionRange:
    minimum: Decimal | None
    maximum: Decimal | None

    def __post_init__(self) -> None:
        if self.minimum is None or self.maximum is None:
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("NEWOW_COMPOSITE_POSITION_RANGE_INVALID")
            return
        if not all(
            isinstance(value, Decimal) and value.is_finite()
            for value in (self.minimum, self.maximum)
        ):
            raise ValueError("NEWOW_COMPOSITE_POSITION_RANGE_INVALID")
        if not Decimal("0") <= self.minimum <= self.maximum <= Decimal("1"):
            raise ValueError("NEWOW_COMPOSITE_POSITION_RANGE_INVALID")


@dataclass(frozen=True, slots=True)
class MultiPeriodTrendState:
    weekly: TrendSignal
    daily: TrendSignal
    sixty_minute: TrendSignal

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, TrendSignal)
            for value in (self.weekly, self.daily, self.sixty_minute)
        ) or self.sixty_minute not in (
            TrendSignal.HOLD,
            TrendSignal.WAIT,
            TrendSignal.IDLE,
        ):
            raise ValueError("NEWOW_COMPOSITE_STATE_INVALID")


@dataclass(frozen=True, slots=True)
class WeeklyDailyTrendState:
    weekly: TrendSignal
    daily: TrendSignal

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, TrendSignal)
            for value in (self.weekly, self.daily)
        ):
            raise ValueError("NEWOW_COMPOSITE_STATE_INVALID")


@dataclass(frozen=True, slots=True)
class MultiPeriodOscillationState:
    weekly: OscillationStatus
    daily: OscillationStatus
    sixty_minute: OscillationStatus

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, OscillationStatus)
            for value in (self.weekly, self.daily, self.sixty_minute)
        ):
            raise ValueError("NEWOW_COMPOSITE_STATE_INVALID")


@dataclass(frozen=True, slots=True)
class CertaintyBreakdown:
    trend: int
    oscillation: int
    alignment: int
    direction: int
    total: int


@dataclass(frozen=True, slots=True)
class CompositeVolatility:
    value_pct: Decimal
    level: VolatilityLevel
    sample_size: int


@dataclass(frozen=True, slots=True)
class DecisionRule:
    action_token: CompositeAction
    position_range: PositionRange


@dataclass(frozen=True, slots=True)
class CompositeDecision:
    trend_bias: TrendBias
    oscillation_bias: OscillationBias
    direction_token: DirectionToken
    decision_key: str
    action_token: CompositeAction
    position_range: PositionRange
    certainty: CertaintyBreakdown
    volatility: CompositeVolatility
    risk_tokens: tuple[str, ...]
    unreachable_decision_keys: tuple[str, ...] = PAGE_UNREACHABLE_DECISION_KEYS
    formula_version: str = COMPOSITE_DECISION_PAGE_V3282


@dataclass(frozen=True, slots=True)
class CleanroomCompositeDecision:
    trend_bias: TrendBias
    oscillation_bias: OscillationBias
    direction_token: DirectionToken
    decision_key: str
    action_token: CompositeAction
    position_range: PositionRange
    certainty: CertaintyBreakdown
    volatility: CompositeVolatility
    risk_tokens: tuple[str, ...]
    page_difference_reason: str | None
    formula_version: str = COMPOSITE_DECISION_CLEANROOM_V1


@dataclass(frozen=True, slots=True)
class FirstActionPrinciple:
    level: PrincipleLevel
    rule_token: str
    fact_tokens: tuple[str, ...]
    formula_version: str = FIRST_ACTION_PRINCIPLE_PAGE_V3263


def _range(minimum: str | None, maximum: str | None) -> PositionRange:
    return PositionRange(
        Decimal(minimum) if minimum is not None else None,
        Decimal(maximum) if maximum is not None else None,
    )


PAGE_DECISION_MATRIX: Mapping[str, DecisionRule] = MappingProxyType(
    {
        "bullish-bullish": DecisionRule(
            CompositeAction.BUILD_OR_ADD, _range("0.5", "1")
        ),
        "bullish-bearish": DecisionRule(
            CompositeAction.HOLD_AND_WAIT, _range("0.3", "0.5")
        ),
        "bullish-neutral": DecisionRule(
            CompositeAction.BUILD_OR_ADD, _range("0.5", "1")
        ),
        "bearish-bullish": DecisionRule(
            CompositeAction.REDUCE_AND_WAIT, _range("0.3", "0.5")
        ),
        "bearish-bearish": DecisionRule(
            CompositeAction.CLEAR, _range("0", "0")
        ),
        "bearish-neutral": DecisionRule(
            CompositeAction.CLEAR, _range("0", "0")
        ),
        "cautious-bullish": DecisionRule(
            CompositeAction.CAUTIOUS_HOLD, _range("0.3", "0.5")
        ),
        "cautious-bearish": DecisionRule(
            CompositeAction.REDUCE_AND_WAIT, _range("0.1", "0.3")
        ),
        "cautious-neutral": DecisionRule(
            CompositeAction.CAUTIOUS_HOLD, _range("0.1", "0.3")
        ),
        "warning-bullish": DecisionRule(
            CompositeAction.REDUCE_AND_WAIT, _range("0.1", "0.3")
        ),
        "warning-bearish": DecisionRule(
            CompositeAction.REDUCE_AND_WAIT, _range("0.1", "0.3")
        ),
        "warning-neutral": DecisionRule(
            CompositeAction.REDUCE_AND_WAIT, _range("0.1", "0.3")
        ),
        "neutral-neutral": DecisionRule(
            CompositeAction.WAIT_FOR_SIGNAL, _range(None, None)
        ),
    }
)


def _bullish(signal: TrendSignal) -> bool:
    return signal in (TrendSignal.BUY, TrendSignal.HOLD)


def _bearish(signal: TrendSignal) -> bool:
    return signal in (TrendSignal.SELL, TrendSignal.WAIT)


def _page_trend_bias(trend: MultiPeriodTrendState) -> TrendBias:
    if _bearish(trend.weekly):
        return TrendBias.BEARISH
    if _bullish(trend.weekly) and _bearish(trend.daily):
        return TrendBias.CAUTIOUS
    if _bullish(trend.weekly) and _bullish(trend.daily):
        if _bearish(trend.sixty_minute):
            return TrendBias.CAUTIOUS
        return TrendBias.BULLISH
    # This is intentionally unreachable because the page's broad weekly
    # bearish branch appears above the narrower warning branch.
    if _bearish(trend.weekly) and _bullish(trend.daily):
        return TrendBias.WARNING
    return TrendBias.NEUTRAL


def _cleanroom_trend_bias(trend: MultiPeriodTrendState) -> TrendBias:
    if _bearish(trend.weekly) and _bullish(trend.daily):
        return TrendBias.WARNING
    return _page_trend_bias(trend)


def _oscillation_bias(
    state: MultiPeriodOscillationState,
) -> OscillationBias:
    statuses = (state.weekly, state.daily, state.sixty_minute)
    if all(status is OscillationStatus.HOLDING for status in statuses):
        return OscillationBias.BULLISH
    if all(status is OscillationStatus.CLEARED for status in statuses):
        return OscillationBias.BEARISH
    if (
        state.daily is OscillationStatus.HOLDING
        and state.sixty_minute is not OscillationStatus.CLEARED
    ):
        return OscillationBias.BULLISH
    if state.daily is OscillationStatus.CLEARED:
        return OscillationBias.BEARISH
    if state.sixty_minute is OscillationStatus.HOLDING:
        return OscillationBias.BULLISH
    if state.sixty_minute is OscillationStatus.CLEARED:
        return OscillationBias.BEARISH
    return OscillationBias.NEUTRAL


def _direction(trend: MultiPeriodTrendState) -> DirectionToken:
    if _bearish(trend.weekly) and (
        _bullish(trend.daily) or _bullish(trend.sixty_minute)
    ):
        return DirectionToken.WEEKLY_BEARISH_REBOUND
    if _bearish(trend.weekly):
        return DirectionToken.WEEKLY_BEARISH
    if _bullish(trend.weekly) and _bearish(trend.daily):
        return DirectionToken.DAILY_PULLBACK
    if (
        _bullish(trend.weekly)
        and _bullish(trend.daily)
        and _bearish(trend.sixty_minute)
    ):
        return DirectionToken.SIXTY_MINUTE_PULLBACK
    if (
        _bullish(trend.weekly)
        and _bullish(trend.daily)
        and _bullish(trend.sixty_minute)
    ):
        return DirectionToken.MULTIPERIOD_BULLISH
    return DirectionToken.INSUFFICIENT


_DIRECTION_CERTAINTY = {
    DirectionToken.WEEKLY_BEARISH_REBOUND: 5,
    DirectionToken.WEEKLY_BEARISH: 3,
    DirectionToken.DAILY_PULLBACK: 10,
    DirectionToken.SIXTY_MINUTE_PULLBACK: 10,
    DirectionToken.MULTIPERIOD_BULLISH: 20,
    DirectionToken.INSUFFICIENT: 5,
}


def _certainty(
    trend: MultiPeriodTrendState,
    oscillation: MultiPeriodOscillationState,
    trend_bias: TrendBias,
    oscillation_bias: OscillationBias,
    direction: DirectionToken,
) -> CertaintyBreakdown:
    trend_score = (
        (12 if _bullish(trend.weekly) else 0)
        + (12 if _bullish(trend.daily) else 0)
        + (6 if trend.sixty_minute is TrendSignal.HOLD else 0)
    )
    oscillation_score = (
        (10 if oscillation.weekly is OscillationStatus.HOLDING else 0)
        + (12 if oscillation.daily is OscillationStatus.HOLDING else 0)
        + (
            8
            if oscillation.sixty_minute is OscillationStatus.HOLDING
            else 0
        )
    )
    if (
        trend_bias is TrendBias.BULLISH
        and oscillation_bias is OscillationBias.BULLISH
    ) or (
        trend_bias is TrendBias.BEARISH
        and oscillation_bias is OscillationBias.BEARISH
    ):
        alignment = 20
    elif (
        trend_bias is TrendBias.NEUTRAL
        or oscillation_bias is OscillationBias.NEUTRAL
    ):
        alignment = 10
    else:
        alignment = 0
    direction_score = _DIRECTION_CERTAINTY[direction]
    total = trend_score + oscillation_score + alignment + direction_score
    if alignment == 0:
        total = min(total, 60)
    elif alignment == 10:
        total = min(total, 85)
    return CertaintyBreakdown(
        trend_score,
        oscillation_score,
        alignment,
        direction_score,
        total,
    )


def _validated_daily_bars(
    bars: Sequence[NewowResearchBar],
) -> tuple[NewowResearchBar, ...]:
    materialized = tuple(bars)
    if not materialized:
        return materialized
    validate_research_bars(materialized)
    identities = {
        (bar.product, bar.physical_contract, bar.segment_id)
        for bar in materialized
    }
    if (
        any(bar.frequency != "1d" for bar in materialized)
        or len(identities) != 1
    ):
        raise ValueError("NEWOW_COMPOSITE_DAILY_BARS_INVALID")
    return materialized


def calculate_composite_volatility(
    daily_bars: Sequence[NewowResearchBar],
) -> CompositeVolatility | None:
    """Return the page's rounded ATR20/close percentage and bucket."""

    bars = _validated_daily_bars(daily_bars)
    if len(bars) < 6:
        return None
    sample_size = min(20, len(bars) - 1)
    true_ranges: list[Decimal] = []
    for index in range(len(bars) - sample_size, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].close
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    if len(true_ranges) < 5:
        return None
    atr = sum(true_ranges, Decimal("0")) / Decimal(len(true_ranges))
    latest_close = bars[-1].close
    value = (atr / latest_close * Decimal("100")).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    level = (
        VolatilityLevel.LOW
        if value < Decimal("2.0")
        else VolatilityLevel.MID
        if value < Decimal("4.0")
        else VolatilityLevel.HIGH
    )
    return CompositeVolatility(value, level, len(true_ranges))


def _risk_tokens(
    volatility: CompositeVolatility, certainty: CertaintyBreakdown
) -> tuple[str, ...]:
    if volatility.level is VolatilityLevel.HIGH:
        return ("volatility_high",)
    if volatility.level is VolatilityLevel.LOW and certainty.total >= 75:
        return ("volatility_low_high_certainty",)
    return ()


def _decision_facts(
    *,
    trend: MultiPeriodTrendState,
    oscillation: MultiPeriodOscillationState,
    daily_bars: Sequence[NewowResearchBar],
    corrected: bool,
) -> tuple[
    TrendBias,
    OscillationBias,
    DirectionToken,
    str,
    DecisionRule,
    CertaintyBreakdown,
    CompositeVolatility,
    tuple[str, ...],
]:
    trend_bias = (
        _cleanroom_trend_bias(trend) if corrected else _page_trend_bias(trend)
    )
    oscillation_bias = _oscillation_bias(oscillation)
    direction = _direction(trend)
    decision_key = f"{trend_bias.value}-{oscillation_bias.value}"
    rule = PAGE_DECISION_MATRIX.get(decision_key)
    if rule is None:
        raise ValueError("NEWOW_COMPOSITE_STATE_UNSUPPORTED")
    volatility = calculate_composite_volatility(daily_bars)
    if volatility is None:
        raise ValueError("NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT")
    certainty = _certainty(
        trend,
        oscillation,
        trend_bias,
        oscillation_bias,
        direction,
    )
    return (
        trend_bias,
        oscillation_bias,
        direction,
        decision_key,
        rule,
        certainty,
        volatility,
        _risk_tokens(volatility, certainty),
    )


def calculate_composite_decision(
    *,
    trend: MultiPeriodTrendState,
    oscillation: MultiPeriodOscillationState,
    daily_bars: Sequence[NewowResearchBar],
) -> CompositeDecision:
    facts = _decision_facts(
        trend=trend,
        oscillation=oscillation,
        daily_bars=daily_bars,
        corrected=False,
    )
    return CompositeDecision(
        facts[0],
        facts[1],
        facts[2],
        facts[3],
        facts[4].action_token,
        facts[4].position_range,
        facts[5],
        facts[6],
        facts[7],
    )


def calculate_cleanroom_composite_decision(
    *,
    trend: MultiPeriodTrendState,
    oscillation: MultiPeriodOscillationState,
    daily_bars: Sequence[NewowResearchBar],
) -> CleanroomCompositeDecision:
    facts = _decision_facts(
        trend=trend,
        oscillation=oscillation,
        daily_bars=daily_bars,
        corrected=True,
    )
    difference = (
        "weekly_bearish_daily_bullish_reclassified"
        if _bearish(trend.weekly) and _bullish(trend.daily)
        else None
    )
    return CleanroomCompositeDecision(
        facts[0],
        facts[1],
        facts[2],
        facts[3],
        facts[4].action_token,
        facts[4].position_range,
        facts[5],
        facts[6],
        facts[7],
        difference,
    )


def _oscillation_holding(
    oscillation: MultiPeriodOscillationState,
) -> tuple[str, ...]:
    return tuple(
        f"oscillation.{period}.holding"
        for period, status in (
            ("weekly", oscillation.weekly),
            ("daily", oscillation.daily),
        )
        if status is OscillationStatus.HOLDING
    )


def calculate_first_action_principle(
    *,
    trend: WeeklyDailyTrendState,
    oscillation: MultiPeriodOscillationState,
) -> FirstActionPrinciple:
    weekly_bearish = _bearish(trend.weekly)
    daily_bearish = _bearish(trend.daily)
    weekly_bullish = _bullish(trend.weekly)
    daily_bullish = _bullish(trend.daily)
    holding_facts = _oscillation_holding(oscillation)

    if weekly_bearish and daily_bearish:
        return FirstActionPrinciple(
            PrincipleLevel.VIOLATE,
            "weekly_daily_bearish_hard_flat",
            (
                "trend.weekly.bearish",
                "trend.daily.bearish",
                *holding_facts,
            ),
        )
    if weekly_bearish and daily_bullish:
        return FirstActionPrinciple(
            PrincipleLevel.WARN,
            "weekly_bearish_daily_bullish_rebound_risk",
            (
                "trend.weekly.bearish",
                "trend.daily.bullish",
                *holding_facts,
            ),
        )
    if weekly_bullish and daily_bearish:
        return FirstActionPrinciple(
            PrincipleLevel.WARN,
            "weekly_bullish_daily_bearish_wait_for_daily_stability",
            ("trend.weekly.bullish", "trend.daily.bearish"),
        )
    if weekly_bearish or daily_bearish:
        return FirstActionPrinciple(
            PrincipleLevel.VIOLATE,
            "single_bearish_unknown_counterpart_hard_flat",
            (
                "trend.weekly.bearish"
                if weekly_bearish
                else "trend.daily.bearish",
                *holding_facts,
            ),
        )
    if oscillation.sixty_minute is OscillationStatus.CLEARED:
        return FirstActionPrinciple(
            PrincipleLevel.WARN,
            "sixty_minute_oscillation_cleared",
            ("oscillation.sixty_minute.cleared",),
        )
    if oscillation.daily is OscillationStatus.CLEARED:
        return FirstActionPrinciple(
            PrincipleLevel.WARN,
            "daily_oscillation_cleared",
            ("oscillation.daily.cleared",),
        )
    if oscillation.weekly is OscillationStatus.CLEARED:
        return FirstActionPrinciple(
            PrincipleLevel.WARN,
            "weekly_oscillation_cleared",
            ("oscillation.weekly.cleared",),
        )
    return FirstActionPrinciple(
        PrincipleLevel.OK,
        "normal_observation",
        ("trend.weekly.not_bearish", "trend.daily.not_bearish"),
    )
