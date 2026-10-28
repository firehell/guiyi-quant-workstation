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
@pytest.mark.parametrize("frequency", [BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1])
def test_terminal_completed_read_rejects_unproven_saved_bar(defect, frequency):
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
            query(frequency), END - timedelta(hours=1), END + timedelta(minutes=10)
        )
        .source
        == "unavailable"
    )


def test_terminal_reader_does_not_open_other_strategy_frequencies():
    with pytest.raises(ValueError):
        service().newow_completed_observation_snapshot(
            query(BarFrequency.M1), None, END
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

@pytest.mark.parametrize("frequency", [BarFrequency.M5, BarFrequency.M15, BarFrequency.M30])
def test_short_minute_completed_terminal_observation_and_due_endpoint(frequency):
    reader = service()
    got = reader.newow_completed_observation_snapshot(query(frequency), END - timedelta(hours=1), END + timedelta(minutes=1))
    assert got.source == "realtime" and got.bars == (BAR,)
    assert reader.newow_completed_observation_endpoint(query(frequency), END + timedelta(minutes=1)) == (END, DAY, "RB2611")


def test_batch_completed_endpoints_share_identity_but_revalidate_after_read():
    reader = service()
    calls = []
    original = reader._newow_completed_identity
    def identity(q, at):
        calls.append(q.symbol)
        return original(q, at)
    reader._newow_completed_identity = identity
    queries = tuple(query(f) for f in (BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1))
    result = reader.newow_completed_observation_endpoints(queries, END)
    assert all(result[(q.symbol, q.frequency)] == (END, DAY, 'RB2611') for q in queries)
    assert calls == ['rb', 'rb']


def test_batch_completed_endpoints_does_not_reuse_identity_across_calls():
    reader = service()
    assert reader.newow_completed_observation_endpoints((query(),), END)[('rb', BarFrequency.H1)] == (END, DAY, 'RB2611')
    reader._phase_resolver.completed_observation_trading_day = lambda *_: None
    assert reader.newow_completed_observation_endpoints((query(),), END)[('rb', BarFrequency.H1)] is None


def test_batch_completed_endpoints_rejects_owner_drift_for_whole_product():
    reader = service()
    owners = iter(('RB2611', 'RB2612'))
    reader._market_data.dominant_segment_for_day = lambda *_: SimpleNamespace(contract=next(owners))
    result = reader.newow_completed_observation_endpoints((query(BarFrequency.M5), query()), END)
    assert set(result.values()) == {None}


def test_batch_completed_endpoints_keeps_frequency_failure_local():
    reader = service()
    def endpoints(**kw):
        if kw['frequency'] == BarFrequency.M5:
            raise ValueError('unavailable')
        return ((END, DAY),)
    reader._market_data.expected_contract_replay_endpoints = endpoints
    result = reader.newow_completed_observation_endpoints((query(BarFrequency.M5), query()), END)
    assert result[('rb', BarFrequency.M5)] is None
    assert result[('rb', BarFrequency.H1)] == (END, DAY, 'RB2611')


@pytest.mark.parametrize('frequency', [BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1])
@pytest.mark.parametrize('due', [True, False])
def test_batch_completed_endpoint_matches_single_reader(frequency, due):
    market = Market()
    if not due:
        market.expected_contract_replay_endpoints = lambda **kw: ()
    reader = service(market=market)
    q = query(frequency)
    assert reader.newow_completed_observation_endpoints((q,), END)[('rb', frequency)] == reader.newow_completed_observation_endpoint(q, END)


@pytest.mark.parametrize('defect', ['future', 'wrong_day', 'unsupported', 'nonoperational', 'naive'])
def test_batch_completed_endpoint_never_falls_back_for_invalid_authority(defect):
    reader = service()
    q, now = query(), END
    if defect == 'future':
        reader._market_data.expected_contract_replay_endpoints = lambda **kw: ((END + timedelta(seconds=1), DAY),)
    elif defect == 'wrong_day':
        reader._market_data.expected_contract_replay_endpoints = lambda **kw: ((END, date(2026, 10, 8)),)
    elif defect == 'unsupported':
        q = query(BarFrequency.M1)
    elif defect == 'nonoperational':
        q = SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, 'cu', BarFrequency.H1)
    elif defect == 'naive':
        now = END.replace(tzinfo=None)
    assert reader.newow_completed_observation_endpoints((q,), now)[(q.symbol, q.frequency)] is None


def test_batch_completed_endpoint_has_fixed_work_bound():
    with pytest.raises(ValueError, match='NEWOW_COMPLETED_ENDPOINT_BATCH_LIMIT'):
        service().newow_completed_observation_endpoints((query(),) * 241, END)


def test_batch_completed_endpoint_missing_product_does_not_poison_other_product():
    reader = service()
    reader._operational_products = frozenset(('rb', 'cu'))
    reader._phase_resolver.completed_observation_trading_day = lambda symbol, _: DAY if symbol == 'rb' else None
    other = SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, 'cu', BarFrequency.H1)
    result = reader.newow_completed_observation_endpoints((other, query()), END)
    assert result[('cu', BarFrequency.H1)] is None
    assert result[('rb', BarFrequency.H1)] == (END, DAY, 'RB2611')
