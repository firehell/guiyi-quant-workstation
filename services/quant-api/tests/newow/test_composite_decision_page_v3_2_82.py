import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from itertools import product
from pathlib import Path

import pytest

from guiyi_quant.newow.composite_decision import (
    COMPOSITE_DECISION_CLEANROOM_V1,
    COMPOSITE_DECISION_PAGE_V3282,
    FIRST_ACTION_PRINCIPLE_PAGE_V3263,
    PAGE_DECISION_MATRIX,
    PAGE_UNREACHABLE_DECISION_KEYS,
    CleanroomCompositeDecision,
    CompositeAction,
    DirectionToken,
    MultiPeriodOscillationState,
    MultiPeriodTrendState,
    OscillationStatus,
    PositionRange,
    PrincipleLevel,
    TrendBias,
    TrendSignal,
    VolatilityLevel,
    WeeklyDailyTrendState,
    calculate_cleanroom_composite_decision,
    calculate_composite_decision,
    calculate_composite_volatility,
    calculate_first_action_principle,
)
from guiyi_quant.newow.research_backtest import NewowResearchBar


UTC = timezone.utc
GOLDEN = (
    Path(__file__).parent / "golden" / "newow_v3_2_82_page_facts.json"
)


def _bar(
    index: int,
    *,
    open_: str = "100",
    high: str = "101",
    low: str = "99",
    close: str = "100",
    segment: str = "rb-2701-a",
    frequency: str = "1d",
) -> NewowResearchBar:
    return NewowResearchBar(
        product="rb",
        physical_contract="RB2701",
        segment_id=segment,
        trading_day=date(2026, 1, 1) + timedelta(days=index),
        bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=100,
        open_interest=1000,
        source_identity=f"composite-{index}-{segment}",
        observation_eligible=True,
        completed=True,
        frequency=frequency,
    )


def daily_bars() -> tuple[NewowResearchBar, ...]:
    return tuple(_bar(index) for index in range(21))


def _trend(
    weekly: TrendSignal,
    daily: TrendSignal,
    sixty: TrendSignal = TrendSignal.IDLE,
) -> MultiPeriodTrendState:
    return MultiPeriodTrendState(weekly, daily, sixty)


def _osc(
    weekly: OscillationStatus = OscillationStatus.IDLE,
    daily: OscillationStatus = OscillationStatus.IDLE,
    sixty: OscillationStatus = OscillationStatus.IDLE,
) -> MultiPeriodOscillationState:
    return MultiPeriodOscillationState(weekly, daily, sixty)


def cartesian_states():
    for weekly, daily, sixty, osc_week, osc_day, osc_sixty in product(
        tuple(TrendSignal),
        tuple(TrendSignal),
        (TrendSignal.HOLD, TrendSignal.WAIT, TrendSignal.IDLE),
        tuple(OscillationStatus),
        tuple(OscillationStatus),
        tuple(OscillationStatus),
    ):
        yield (
            _trend(weekly, daily, sixty),
            _osc(osc_week, osc_day, osc_sixty),
        )


EXPECTED_MATRIX = {
    "bullish-bullish": (CompositeAction.BUILD_OR_ADD, "0.5", "1"),
    "bullish-bearish": (CompositeAction.HOLD_AND_WAIT, "0.3", "0.5"),
    "bullish-neutral": (CompositeAction.BUILD_OR_ADD, "0.5", "1"),
    "bearish-bullish": (CompositeAction.REDUCE_AND_WAIT, "0.3", "0.5"),
    "bearish-bearish": (CompositeAction.CLEAR, "0", "0"),
    "bearish-neutral": (CompositeAction.CLEAR, "0", "0"),
    "cautious-bullish": (CompositeAction.CAUTIOUS_HOLD, "0.3", "0.5"),
    "cautious-bearish": (CompositeAction.REDUCE_AND_WAIT, "0.1", "0.3"),
    "cautious-neutral": (CompositeAction.CAUTIOUS_HOLD, "0.1", "0.3"),
    "warning-bullish": (CompositeAction.REDUCE_AND_WAIT, "0.1", "0.3"),
    "warning-bearish": (CompositeAction.REDUCE_AND_WAIT, "0.1", "0.3"),
    "warning-neutral": (CompositeAction.REDUCE_AND_WAIT, "0.1", "0.3"),
    "neutral-neutral": (CompositeAction.WAIT_FOR_SIGNAL, None, None),
}


def test_page_matrix_has_thirteen_keys_but_warning_keys_are_unreachable() -> None:
    assert len(PAGE_DECISION_MATRIX) == 13
    assert PAGE_UNREACHABLE_DECISION_KEYS == (
        "warning-bullish",
        "warning-bearish",
        "warning-neutral",
    )
    reached: set[str] = set()
    rejected = 0
    for trend, oscillation in cartesian_states():
        try:
            result = calculate_composite_decision(
                trend=trend,
                oscillation=oscillation,
                daily_bars=daily_bars(),
            )
        except ValueError as exc:
            assert str(exc) == "NEWOW_COMPOSITE_STATE_UNSUPPORTED"
            rejected += 1
            continue
        reached.add(result.decision_key)
    assert rejected > 0
    assert reached == set(PAGE_DECISION_MATRIX) - set(
        PAGE_UNREACHABLE_DECISION_KEYS
    )


@pytest.mark.parametrize(
    ("decision_key", "action", "minimum", "maximum"),
    [
        (key, action, minimum, maximum)
        for key, (action, minimum, maximum) in EXPECTED_MATRIX.items()
    ],
)
def test_page_matrix_preserves_action_and_decimal_position_ranges(
    decision_key: str,
    action: CompositeAction,
    minimum: str | None,
    maximum: str | None,
) -> None:
    rule = PAGE_DECISION_MATRIX[decision_key]

    assert rule.action_token is action
    assert rule.position_range == PositionRange(
        Decimal(minimum) if minimum is not None else None,
        Decimal(maximum) if maximum is not None else None,
    )
    assert rule.position_range.minimum != "--"
    assert rule.position_range.maximum != "--"


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        (Decimal("0.5"), None),
        (Decimal("0.6"), Decimal("0.5")),
        (Decimal("-0.1"), Decimal("0.5")),
        (Decimal("0.5"), Decimal("1.1")),
    ],
)
def test_position_range_fails_closed_on_invalid_bounds(
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> None:
    with pytest.raises(
        ValueError,
        match="NEWOW_COMPOSITE_POSITION_RANGE_INVALID",
    ):
        PositionRange(minimum, maximum)


def test_page_preserves_warning_defect_and_cleanroom_reclassifies_it() -> None:
    trend = _trend(TrendSignal.WAIT, TrendSignal.HOLD, TrendSignal.HOLD)
    oscillation = _osc(
        OscillationStatus.HOLDING,
        OscillationStatus.HOLDING,
        OscillationStatus.HOLDING,
    )

    page = calculate_composite_decision(
        trend=trend,
        oscillation=oscillation,
        daily_bars=daily_bars(),
    )
    corrected = calculate_cleanroom_composite_decision(
        trend=trend,
        oscillation=oscillation,
        daily_bars=daily_bars(),
    )

    assert page.formula_version == COMPOSITE_DECISION_PAGE_V3282
    assert page.trend_bias is TrendBias.BEARISH
    assert page.decision_key == "bearish-bullish"
    assert type(corrected) is CleanroomCompositeDecision
    assert corrected.formula_version == COMPOSITE_DECISION_CLEANROOM_V1
    assert corrected.trend_bias is TrendBias.WARNING
    assert corrected.decision_key == "warning-bullish"
    assert (
        corrected.page_difference_reason
        == "weekly_bearish_daily_bullish_reclassified"
    )


def test_certainty_matches_page_components_caps_and_direction_tokens() -> None:
    bullish = calculate_composite_decision(
        trend=_trend(
            TrendSignal.HOLD,
            TrendSignal.HOLD,
            TrendSignal.HOLD,
        ),
        oscillation=_osc(
            OscillationStatus.HOLDING,
            OscillationStatus.HOLDING,
            OscillationStatus.HOLDING,
        ),
        daily_bars=daily_bars(),
    )
    conflict = calculate_composite_decision(
        trend=_trend(
            TrendSignal.HOLD,
            TrendSignal.HOLD,
            TrendSignal.HOLD,
        ),
        oscillation=_osc(
            OscillationStatus.CLEARED,
            OscillationStatus.CLEARED,
            OscillationStatus.CLEARED,
        ),
        daily_bars=daily_bars(),
    )

    assert bullish.direction_token is DirectionToken.MULTIPERIOD_BULLISH
    assert bullish.certainty.trend == 30
    assert bullish.certainty.oscillation == 30
    assert bullish.certainty.alignment == 20
    assert bullish.certainty.direction == 20
    assert bullish.certainty.total == 100
    assert conflict.certainty.alignment == 0
    assert conflict.certainty.total == 50


def _constant_tr_bars(
    value: str, *, count: int = 6
) -> tuple[NewowResearchBar, ...]:
    high = str(Decimal("100") + Decimal(value))
    return tuple(
        _bar(index, open_="100", high=high, low="100", close="100")
        for index in range(count)
    )


@pytest.mark.parametrize(
    ("true_range_pct", "expected_value", "expected_level"),
    [
        ("1.94", "1.9", VolatilityLevel.LOW),
        ("1.95", "2.0", VolatilityLevel.MID),
        ("2.0", "2.0", VolatilityLevel.MID),
        ("3.94", "3.9", VolatilityLevel.MID),
        ("3.95", "4.0", VolatilityLevel.HIGH),
        ("4.0", "4.0", VolatilityLevel.HIGH),
    ],
)
def test_volatility_uses_page_half_up_boundaries(
    true_range_pct: str,
    expected_value: str,
    expected_level: VolatilityLevel,
) -> None:
    volatility = calculate_composite_volatility(
        _constant_tr_bars(true_range_pct)
    )

    assert volatility is not None
    assert volatility.value_pct == Decimal(expected_value)
    assert volatility.level is expected_level
    assert volatility.sample_size == 5


def test_volatility_true_range_includes_gap_and_caps_at_twenty() -> None:
    gap_bars = list(_constant_tr_bars("1"))
    gap_bars[-1] = _bar(
        5,
        open_="110",
        high="112",
        low="109",
        close="110",
    )

    gap_volatility = calculate_composite_volatility(tuple(gap_bars))
    capped_volatility = calculate_composite_volatility(
        _constant_tr_bars("1", count=22)
    )

    assert gap_volatility is not None
    assert gap_volatility.sample_size == 5
    assert gap_volatility.value_pct == Decimal("2.9")
    assert capped_volatility is not None
    assert capped_volatility.sample_size == 20


def test_volatility_returns_none_when_fewer_than_five_true_ranges() -> None:
    assert calculate_composite_volatility(daily_bars()[:5]) is None
    with pytest.raises(
        ValueError,
        match="NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT",
    ):
        calculate_composite_decision(
            trend=_trend(TrendSignal.HOLD, TrendSignal.HOLD),
            oscillation=_osc(),
            daily_bars=daily_bars()[:5],
        )


@pytest.mark.parametrize(
    "bars",
    [
        (*daily_bars()[:-1], _bar(20, segment="rb-2701-b")),
        tuple(_bar(index, frequency="60m") for index in range(6)),
    ],
)
def test_volatility_rejects_non_daily_or_mixed_segment_series(
    bars: tuple[NewowResearchBar, ...],
) -> None:
    with pytest.raises(
        ValueError,
        match="NEWOW_COMPOSITE_DAILY_BARS_INVALID",
    ):
        calculate_composite_volatility(bars)


def test_high_and_low_volatility_are_structured_risk_tokens() -> None:
    high = calculate_composite_decision(
        trend=_trend(TrendSignal.HOLD, TrendSignal.HOLD, TrendSignal.HOLD),
        oscillation=_osc(
            OscillationStatus.HOLDING,
            OscillationStatus.HOLDING,
            OscillationStatus.HOLDING,
        ),
        daily_bars=_constant_tr_bars("4"),
    )
    low = calculate_composite_decision(
        trend=_trend(TrendSignal.HOLD, TrendSignal.HOLD, TrendSignal.HOLD),
        oscillation=_osc(
            OscillationStatus.HOLDING,
            OscillationStatus.HOLDING,
            OscillationStatus.HOLDING,
        ),
        daily_bars=_constant_tr_bars("1"),
    )

    assert high.risk_tokens == ("volatility_high",)
    assert low.risk_tokens == ("volatility_low_high_certainty",)


@pytest.mark.parametrize(
    ("weekly", "daily", "oscillation", "level", "rule_token"),
    [
        (
            TrendSignal.WAIT,
            TrendSignal.SELL,
            _osc(OscillationStatus.HOLDING),
            PrincipleLevel.VIOLATE,
            "weekly_daily_bearish_hard_flat",
        ),
        (
            TrendSignal.WAIT,
            TrendSignal.HOLD,
            _osc(OscillationStatus.HOLDING),
            PrincipleLevel.WARN,
            "weekly_bearish_daily_bullish_rebound_risk",
        ),
        (
            TrendSignal.HOLD,
            TrendSignal.WAIT,
            _osc(),
            PrincipleLevel.WARN,
            "weekly_bullish_daily_bearish_wait_for_daily_stability",
        ),
        (
            TrendSignal.IDLE,
            TrendSignal.WAIT,
            _osc(),
            PrincipleLevel.VIOLATE,
            "single_bearish_unknown_counterpart_hard_flat",
        ),
        (
            TrendSignal.HOLD,
            TrendSignal.HOLD,
            _osc(sixty=OscillationStatus.CLEARED),
            PrincipleLevel.WARN,
            "sixty_minute_oscillation_cleared",
        ),
        (
            TrendSignal.HOLD,
            TrendSignal.HOLD,
            _osc(daily=OscillationStatus.CLEARED),
            PrincipleLevel.WARN,
            "daily_oscillation_cleared",
        ),
        (
            TrendSignal.HOLD,
            TrendSignal.HOLD,
            _osc(weekly=OscillationStatus.CLEARED),
            PrincipleLevel.WARN,
            "weekly_oscillation_cleared",
        ),
        (
            TrendSignal.HOLD,
            TrendSignal.HOLD,
            _osc(),
            PrincipleLevel.OK,
            "normal_observation",
        ),
    ],
)
def test_first_action_principle_has_exact_priority_without_advice_copy(
    weekly: TrendSignal,
    daily: TrendSignal,
    oscillation: MultiPeriodOscillationState,
    level: PrincipleLevel,
    rule_token: str,
) -> None:
    result = calculate_first_action_principle(
        trend=WeeklyDailyTrendState(weekly, daily),
        oscillation=oscillation,
    )

    assert result.formula_version == FIRST_ACTION_PRINCIPLE_PAGE_V3263
    assert result.level is level
    assert result.rule_token == rule_token
    assert result.fact_tokens
    assert not hasattr(result, "advice")


def test_first_action_preserves_rebound_warning_when_page_is_bearish() -> None:
    trend = _trend(TrendSignal.WAIT, TrendSignal.HOLD, TrendSignal.IDLE)
    oscillation = _osc()
    composite = calculate_composite_decision(
        trend=trend,
        oscillation=oscillation,
        daily_bars=daily_bars(),
    )
    principle = calculate_first_action_principle(
        trend=WeeklyDailyTrendState(trend.weekly, trend.daily),
        oscillation=oscillation,
    )

    assert composite.trend_bias is TrendBias.BEARISH
    assert principle.level is PrincipleLevel.WARN
    assert (
        principle.rule_token
        == "weekly_bearish_daily_bullish_rebound_risk"
    )


def test_golden_fixture_preserves_six_individual_stock_composite_samples() -> None:
    payload = json.loads(GOLDEN.read_text())
    stocks = [item for item in payload["symbols"] if item["kind"] == "stock"]

    assert {item["code"] for item in stocks} >= {
        "601233.SH",
        "600519.SH",
        "600036.SH",
        "002594.SZ",
        "300750.SZ",
        "000651.SZ",
    }
    for stock in stocks:
        daily = next(
            period for period in stock["periods"] if period["period"] == "day"
        )
        assert daily["page_output"]["composite_decision"]
        assert daily["page_output"]["composite_score"].endswith("分")
        assert len(daily["source_response_sha256"]) == 64


def test_golden_composite_witnesses_match_page_control_flow() -> None:
    payload = json.loads(GOLDEN.read_text())
    trend_signal = {
        None: TrendSignal.IDLE,
        "buy": TrendSignal.BUY,
        "hold": TrendSignal.HOLD,
        "sell": TrendSignal.SELL,
        "wait": TrendSignal.WAIT,
    }
    trend_sixty = {
        "holding": TrendSignal.HOLD,
        "cleared": TrendSignal.WAIT,
        "idle": TrendSignal.IDLE,
    }

    for witness in payload["composite_cases"]:
        source = witness["synthetic_input"]
        result = calculate_composite_decision(
            trend=_trend(
                trend_signal[source["weekly"]],
                trend_signal[source["daily"]],
                trend_sixty[source["trend_60m"]],
            ),
            oscillation=_osc(
                OscillationStatus(source["osc_weekly"]),
                OscillationStatus(source["osc_daily"]),
                OscillationStatus(source["osc_60m"]),
            ),
            daily_bars=daily_bars(),
        )

        assert result.decision_key == witness["selected_key"]
        assert (
            witness["page_reachable"]
            is (witness["branch_key"] == result.decision_key)
        )
