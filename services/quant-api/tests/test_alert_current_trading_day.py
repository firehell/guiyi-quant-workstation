from __future__ import annotations

from datetime import date, datetime

import pytest

from app.alerts.current_trading_day import (
    CurrentTradingDayStatus,
    resolve_current_trading_day,
)
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


class FakePhases:
    def __init__(self, phases: dict[str, ProductMarketPhase]) -> None:
        self._phases = phases

    def resolve(self, symbol: str, _now: datetime) -> ProductMarketPhase:
        return self._phases[symbol]


def aware(value: str) -> datetime:
    return datetime.fromisoformat(value)


def phase(
    symbol: str,
    state: MarketPhase,
    trading_day: date | None,
) -> ProductMarketPhase:
    return ProductMarketPhase(symbol, state, trading_day, None, None)


def test_resolver_prefers_unique_trading_break_day() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.TRADING, date(2026, 8, 15)),
                "rb": phase("rb", MarketPhase.BREAK, date(2026, 8, 15)),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.READY
    assert result.trading_day == date(2026, 8, 15)


def test_resolver_conflicting_active_days_is_unavailable() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.TRADING, date(2026, 8, 15)),
                "rb": phase("rb", MarketPhase.TRADING, date(2026, 8, 14)),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None


def test_resolver_prefers_active_day_over_closed_day() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.BREAK, date(2026, 8, 15)),
                "rb": phase("rb", MarketPhase.CLOSED, date(2026, 8, 14)),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.READY
    assert result.trading_day == date(2026, 8, 15)


def test_resolver_uses_unique_closed_day_when_no_product_is_active() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.CLOSED, date(2026, 8, 14)),
                "rb": phase("rb", MarketPhase.CLOSED, date(2026, 8, 14)),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T16:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.READY
    assert result.trading_day == date(2026, 8, 14)


def test_resolver_unknown_only_is_unavailable() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.UNKNOWN, None),
                "rb": phase("rb", MarketPhase.UNKNOWN, None),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None


@pytest.mark.parametrize("known_phase", (MarketPhase.TRADING, MarketPhase.CLOSED))
def test_resolver_unknown_product_invalidates_known_product_day(
    known_phase: MarketPhase,
) -> None:
    """Catches one unresolved operational product being hidden by a known peer."""
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", known_phase, date(2026, 8, 15)),
                "rb": phase("rb", MarketPhase.UNKNOWN, None),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None


def test_resolver_active_phase_without_day_does_not_fall_back_to_closed_day() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.TRADING, None),
                "rb": phase("rb", MarketPhase.CLOSED, date(2026, 8, 14)),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None


def test_resolver_active_day_is_unavailable_when_another_active_phase_has_no_day() -> (
    None
):
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.TRADING, date(2026, 8, 15)),
                "rb": phase("rb", MarketPhase.BREAK, None),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None


def test_resolver_weekend_without_trading_day_is_unavailable() -> None:
    result = resolve_current_trading_day(
        FakePhases(
            {
                "jm": phase("jm", MarketPhase.CLOSED, None),
                "rb": phase("rb", MarketPhase.UNKNOWN, None),
            }
        ),
        products=("jm", "rb"),
        now=aware("2026-08-16T10:00:00+08:00"),
    )

    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None
