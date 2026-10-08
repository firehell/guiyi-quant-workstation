from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.live_market import LiveBarObservation
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.market_read_service import MarketReadService

DAY = date(2026, 10, 9)
END = datetime(2026, 10, 8, 15, tzinfo=UTC)
BAR = CanonicalBar(
    END,
    DAY,
    Decimal("1"),
    Decimal("2"),
    Decimal("1"),
    Decimal("2"),
    Decimal("1"),
    None,
    None,
)


class Phase:
    def resolve(self, *args):
        return ProductMarketPhase(
            "rb", MarketPhase.CLOSED, date(2026, 10, 8), None, None
        )

    def completed_observation_trading_day(self, *args):
        return DAY


class Market:
    def query_page(self, q):
        return SimpleNamespace(bars=())

    def dominant_segment_for_day(self, *args):
        return SimpleNamespace(contract="RB2611")

    def expected_contract_replay_endpoints(self, **kw):
        return ((END, DAY),)


class Store:
    def __init__(self):
        self.bars = (LiveBarObservation(BAR, "RB2611"),)

    def subscriptions(self, day):
        assert day == DAY
        return {"rb": "RB2611"}

    def heartbeat(self):
        return {"available": False}

    def bar_observations(self, *args, **kw):
        return self.bars


def service(store=None, market=None):
    return MarketReadService(
        market_data=market or Market(),
        phase_resolver=Phase(),
        operational_products=("rb",),
        live_store=store or Store(),
    )


def query(freq=BarFrequency.H1):
    return SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, "rb", freq, limit=2)


def test_terminal_completed_read_uses_session_day_not_closed_civil_day_and_preserves_strict_reader():
    s = service()
    now = END + timedelta(minutes=10)
    assert (
        s.observation_snapshot(query(), END - timedelta(hours=1), now).source == "none"
    )
    got = s.newow_completed_observation_snapshot(query(), END - timedelta(hours=1), now)
    assert got.source == "realtime" and got.trading_day == DAY and got.bars == (BAR,)


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "wrong_contract",
        "wrong_day",
        "future",
        "missing_session",
        "wrong_owner",
    ],
)
def test_terminal_completed_read_rejects_unproven_saved_bar(defect):
    from dataclasses import replace

    store = Store()
    market = Market()
    if defect == "duplicate":
        store.bars = store.bars * 2
    if defect == "wrong_contract":
        store.bars = (LiveBarObservation(BAR, "RB2612"),)
    if defect == "wrong_day":
        store.bars = (
            LiveBarObservation(replace(BAR, trading_day=date(2026, 10, 8)), "RB2611"),
        )
    if defect == "future":
        store.bars = (
            LiveBarObservation(
                replace(BAR, bar_end=END + timedelta(hours=1)), "RB2611"
            ),
        )
    if defect == "missing_session":
        market.expected_contract_replay_endpoints = lambda **kw: ()
    if defect == "wrong_owner":
        market.dominant_segment_for_day = lambda *args: SimpleNamespace(
            contract="RB2612"
        )
    assert (
        service(store, market)
        .newow_completed_observation_snapshot(
            query(), END - timedelta(hours=1), END + timedelta(minutes=10)
        )
        .source
        == "unavailable"
    )


def test_terminal_reader_does_not_open_other_strategy_frequencies():
    with pytest.raises(ValueError):
        service().newow_completed_observation_snapshot(
            query(BarFrequency.M15), None, END
        )


def test_terminal_reader_restart_does_not_repeat_completed_bar():
    store = Store()
    store.bar_observations = lambda *args, **kw: ()
    assert (
        service(store)
        .newow_completed_observation_snapshot(query(), END, END + timedelta(minutes=10))
        .bars
        == ()
    )


def test_expected_terminal_endpoint_survives_missing_saved_last_bar():
    store = Store()
    store.bars = ()
    assert service(store).newow_completed_observation_endpoint(
        query(), END + timedelta(minutes=10)
    ) == (END, DAY, "RB2611")


def test_expected_endpoint_returns_none_when_session_has_no_completed_hour():
    market = Market()
    market.expected_contract_replay_endpoints = lambda **kw: ()
    assert service(market=market).newow_completed_observation_endpoint(
        query(), END - timedelta(minutes=30)
    ) == (None, DAY, "RB2611")


def test_expected_endpoint_rejects_unknown_session_instead_of_canonical_fallback():
    s = service()
    s._phase_resolver.completed_observation_trading_day = lambda *args: None
    with pytest.raises(ValueError, match="NEWOW_SESSION_DAY_UNAVAILABLE"):
        s.newow_completed_observation_endpoint(query(), END)
