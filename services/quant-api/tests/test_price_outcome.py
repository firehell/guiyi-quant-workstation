from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import CanonicalBar
from app.market_data.price_outcome import PriceDirection, build_price_outcomes_at


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
