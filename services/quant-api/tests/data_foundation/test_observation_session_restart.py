from dataclasses import replace
from datetime import timedelta
import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.observation_restore import (
    build_projection_restore_plan,
    restore_missing_projections,
)
from tests.data_foundation.test_observation_restore import fixture
from tests.data_foundation import test_observation_stream as stream_tests
from tests.data_foundation.test_live_market import FakeDominants, _phase


@pytest.fixture
def isolated_redis():
    yield from stream_tests.isolated_redis.__wrapped__()


def test_restart_next_day_retains_authoritative_old_session_end_grace(isolated_redis):
    base, mapping, _, source, completed, args = fixture(isolated_redis)
    old = SessionWindow(
        base.bar_end - timedelta(minutes=1), base.bar_end + timedelta(minutes=4)
    )
    args["session_for_bar"] = lambda *_: old
    plan = build_projection_restore_plan(isolated_redis, **args)
    restore_missing_projections(
        isolated_redis, plan, expected_sha256=plan.sha256, assert_owned=lambda: None
    )
    new = SessionWindow(old.start + timedelta(days=1), old.end + timedelta(days=1))
    now = new.start + timedelta(minutes=2)
    calls = []

    class Phases:
        def resolve(self, symbol, when):
            if when >= new.start:
                return _phase(symbol, new.start.date(), new)
            if old.start <= when < old.end:
                return _phase(symbol, base.trading_day, old)
            return ProductMarketPhase(
                symbol, MarketPhase.BREAK, base.trading_day, None, new.start
            )

    def sessions(symbol, day):
        calls.append((symbol, day))
        return (old,) if day == base.trading_day else (new,)

    service = DurableLiveMarketService(
        source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants(
            {(p, base.trading_day): c for p, c in mapping.items()}
        ),
        phase_resolver=Phases(),
        store=RedisLiveStore(isolated_redis),
        operational_products=tuple(mapping),
        coverage_sessions=sessions,
        authoritative_dominants=True,
    )
    raw = isolated_redis.dump(source.key(base.trading_day))
    prefix = isolated_redis.xrange(completed.key(base.trading_day))
    assert service.poll(now) is None
    assert source.cursor("live", base.trading_day) == source.tail(base.trading_day)
    assert isolated_redis.dump(source.key(base.trading_day)) == raw
    assert (
        isolated_redis.xrange(completed.key(base.trading_day))[: len(prefix)] == prefix
    )
    assert {(p, day) for p, day in calls if day == base.trading_day} == {
        (p, base.trading_day) for p in mapping
    }
    assert all(
        event.raw_received_at == event.source_observed_at
        for event in completed.read("alert", base.trading_day)
    )
    assert service.poll(now + timedelta(seconds=1)) == "OBSERVATION_DAY_AWAITING_FEED"
    assert source.registered_day("live") == base.trading_day
    # Hydration does not widen the Session-end grace or admit a later raw.
    assert (
        service.ingest(
            "RB2505",
            replace(base, bar_end=old.end),
            now=old.end + timedelta(seconds=61),
        )
        == "LIVE_BAR_OUTSIDE_SESSION"
    )


def test_missing_old_authority_failclosed_before_ack(isolated_redis):
    base, mapping, _, source, _, _ = fixture(isolated_redis)
    before = source.cursor("live", base.trading_day)

    class Phases:
        def resolve(self, symbol, when):
            return ProductMarketPhase(
                symbol,
                MarketPhase.BREAK,
                base.trading_day,
                None,
                when + timedelta(hours=1),
            )

    def missing(*_):
        raise ValueError("SESSION_MISSING")

    service = DurableLiveMarketService(
        source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants(
            {(p, base.trading_day): c for p, c in mapping.items()}
        ),
        phase_resolver=Phases(),
        store=RedisLiveStore(isolated_redis),
        operational_products=tuple(mapping),
        coverage_sessions=missing,
    )
    RedisLiveStore(isolated_redis).set_subscriptions(base.trading_day, mapping)
    assert (
        service.poll(base.bar_end + timedelta(days=1))
        == "LIVE_SESSION_AUTHORITY_UNAVAILABLE"
    )
    assert source.cursor("live", base.trading_day) == before
