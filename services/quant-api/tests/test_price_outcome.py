from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from app.market_data.price_outcome import (
    PriceDirection,
    PriceDirectionalOutcome,
    PriceHorizonEvaluation,
    PriceOutcomeError,
    build_price_outcomes_at,
    summarize_price_outcomes,
)


def _bar(
    index: int,
    *,
    trading_day: date,
    high: str,
    low: str,
    close: str,
) -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=5 * index),
        trading_day=trading_day,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        turnover=None,
        open_interest=None,
    )


def test_long_price_outcome_uses_exact_decimal_directional_formulas() -> None:
    day = date(2026, 1, 2)
    bars = (
        _bar(0, trading_day=day, high="100", low="100", close="100"),
        _bar(1, trading_day=day, high="103", low="99", close="101"),
        _bar(2, trading_day=day, high="104", low="98", close="102"),
    )

    outcome = build_price_outcomes_at(
        bars,
        index=0,
        direction=PriceDirection.LONG,
        horizons=(2,),
        same_trading_day_only=True,
    )[2]

    assert outcome is not None
    assert outcome.directional_return_bps == Decimal("200")
    assert outcome.mfe_bps == Decimal("400")
    assert outcome.mae_bps == Decimal("-200")


def test_short_price_outcome_uses_exact_decimal_directional_formulas() -> None:
    day = date(2026, 1, 2)
    bars = (
        _bar(0, trading_day=day, high="100", low="100", close="100"),
        _bar(1, trading_day=day, high="101", low="97", close="99"),
        _bar(2, trading_day=day, high="102", low="96", close="98"),
    )

    outcome = build_price_outcomes_at(
        bars,
        index=0,
        direction=PriceDirection.SHORT,
        horizons=(2,),
        same_trading_day_only=True,
    )[2]

    assert outcome is not None
    assert outcome.directional_return_bps == Decimal("200")
    assert outcome.mfe_bps == Decimal("400")
    assert outcome.mae_bps == Decimal("-200")


def test_same_trading_day_boundary_is_caller_selected() -> None:
    first_day = date(2026, 1, 2)
    second_day = date(2026, 1, 5)
    bars = (
        _bar(0, trading_day=first_day, high="100", low="100", close="100"),
        _bar(1, trading_day=first_day, high="101", low="99", close="100"),
        _bar(2, trading_day=second_day, high="103", low="98", close="102"),
    )

    same_day = build_price_outcomes_at(
        bars,
        index=0,
        direction=PriceDirection.LONG,
        horizons=(2,),
        same_trading_day_only=True,
    )
    cross_day = build_price_outcomes_at(
        bars,
        index=0,
        direction=PriceDirection.LONG,
        horizons=(2,),
        same_trading_day_only=False,
    )

    assert same_day == {2: None}
    assert cross_day[2] is not None
    assert cross_day[2].directional_return_bps == Decimal("200")


@pytest.mark.parametrize("entry_close", ("0", "-100"))
def test_nonpositive_entry_close_fails_closed_in_outcome_domain(
    entry_close: str,
) -> None:
    day = date(2026, 1, 2)
    entry = Decimal(entry_close)
    bars = (
        _bar(
            0,
            trading_day=day,
            high=entry_close,
            low=entry_close,
            close=entry_close,
        ),
        _bar(
            1,
            trading_day=day,
            high=str(entry + Decimal("1")),
            low=str(entry - Decimal("1")),
            close=entry_close,
        ),
    )

    with pytest.raises(PriceOutcomeError) as captured:
        build_price_outcomes_at(
            bars,
            index=0,
            direction=PriceDirection.LONG,
            horizons=(1,),
            same_trading_day_only=True,
        )

    assert str(captured.value) == "PRICE_OUTCOME_ENTRY_INVALID"
    assert captured.value.code == "PRICE_OUTCOME_ENTRY_INVALID"
    assert captured.value.__cause__ is None


def test_price_outcome_summary_preserves_empty_identity() -> None:
    assert summarize_price_outcomes(()) == PriceHorizonEvaluation(
        0,
        None,
        None,
        None,
    )


def test_price_outcome_summary_uses_exact_decimal_medians() -> None:
    outcomes = (
        PriceDirectionalOutcome(
            horizon=3,
            directional_return_bps=Decimal("-1"),
            mfe_bps=Decimal("2"),
            mae_bps=Decimal("-5"),
        ),
        PriceDirectionalOutcome(
            horizon=3,
            directional_return_bps=Decimal("4"),
            mfe_bps=Decimal("8"),
            mae_bps=Decimal("-2"),
        ),
    )

    assert summarize_price_outcomes(outcomes) == PriceHorizonEvaluation(
        sample_count=2,
        median_directional_return_bps=Decimal("1.5"),
        median_mfe_bps=Decimal("5"),
        median_mae_bps=Decimal("-3.5"),
    )
