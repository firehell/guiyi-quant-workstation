from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy.engine import make_url

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_foundation_scope import (
    bind_market_redis, bind_tick_source, formal_tick_fingerprint,
    require_bar_writer_namespace, require_formal_tick_binding, stage_empty_formal_tick_namespace,
)
from app.market_data.tick_market import MarketTick, TickMinuteUpdate
from app.market_data.tick_preview_redis import RedisTickPreviewPublisher, RedisTickPreviewReader
from tests.data_foundation.test_tick_htdy_integration import disposable_market as native_market_fixture


@pytest.fixture
def disposable_market():
    yield from native_market_fixture.__wrapped__()


DAY = date(2026, 11, 26)
OPEN = datetime(2026, 11, 25, 13, tzinfo=UTC)
GEN = "rqdata-tick:" + "a" * 32


def test_formal_binding_cannot_use_candidate_redis(disposable_market, tmp_path):
    from redis import Redis

    engine, isolated = disposable_market
    bind_market_redis(isolated, tmp_path, engine.url)
    bind_tick_source(isolated)
    port = isolated.connection_pool.connection_kwargs["port"]
    with Redis(host="127.0.0.1", port=port, db=0, decode_responses=True) as formal:
        assert formal.dbsize() == 0
        database = make_url("postgresql+psycopg://operator@127.0.0.1:5432/guiyi_quant")
        fingerprint = formal_tick_fingerprint(formal, database, tmp_path)
        with pytest.raises(ValueError, match="MARKET_FORMAL_BINDING_INVALID"):
            require_formal_tick_binding(isolated, database, tmp_path)
        with pytest.raises(ValueError, match="MARKET_FORMAL_BINDING_UNPROVEN"):
            require_formal_tick_binding(formal, database, tmp_path)
        try:
            from app.market_data.observation_stream import ObservationStream
            from app.market_data.operational_universe import load_operational_products

            mapping = {product: f"{product.upper()}2701" for product in load_operational_products()}
            with pytest.raises(ValueError, match="MARKET_TICK_INITIAL_NAMESPACE_NOT_EMPTY"):
                stage_empty_formal_tick_namespace(
                    formal, database, tmp_path, day=DAY, subscriptions=mapping, alert_enabled=True,
                )
            isolated.delete("live:market-foundation:binding", "live:market-foundation:source")
            assert stage_empty_formal_tick_namespace(
                formal, database, tmp_path, day=DAY, subscriptions=mapping, alert_enabled=True,
            ) == fingerprint
            assert require_formal_tick_binding(formal, database, tmp_path) == fingerprint
            assert RedisLiveStore(formal).subscriptions(DAY) == mapping
            assert ObservationStream(formal, kind="source").cursor("live", DAY) == "0-0"
            assert ObservationStream(formal, kind="completed").cursor("alert", DAY) == "0-0"
            assert not formal.exists("live:observations:registered:completed:reference")
            with pytest.raises(ValueError, match="MARKET_FOUNDATION_REDIS_BINDING_CONFLICT"):
                bind_market_redis(isolated, tmp_path, engine.url)
            with pytest.raises(ValueError, match="MARKET_TICK_INITIAL_NAMESPACE_NOT_EMPTY"):
                stage_empty_formal_tick_namespace(
                    formal, database, tmp_path, day=DAY, subscriptions=mapping, alert_enabled=True,
                )
            with pytest.raises(ValueError, match="MARKET_BAR_WRITER_NAMESPACE_CONFLICT"):
                require_bar_writer_namespace(formal)
            with pytest.raises(ValueError, match="MARKET_FORMAL_BINDING_UNPROVEN"):
                require_formal_tick_binding(formal, database, tmp_path / "wrong")
        finally:
            # The test uses a dedicated disposable instance and verified an empty DB.
            for key in formal.scan_iter():
                formal.delete(key)


def test_tick_preview_reconnect_and_owner_change_are_display_only(disposable_market):
    _engine, redis = disposable_market
    store = RedisLiveStore(redis)
    store.set_subscriptions(DAY, {"rb": "RB2701", "au": "AU2702"})
    calls = []
    publisher = RedisTickPreviewPublisher(redis, assert_owned=lambda: calls.append("owned"))
    reader = RedisTickPreviewReader(redis, sessions=lambda **_: ())
    end = OPEN + timedelta(minutes=1)
    price = Decimal("10.005")
    tick = MarketTick(
        contract="RB2701", trading_day=DAY, observed_at=OPEN, received_at=OPEN,
        last=price, volume=Decimal(1), turnover=price, open_interest=Decimal(2),
        connection=1, bid=((Decimal("10.000"), Decimal(5)),), ask=(),
    )
    active = CanonicalBar(end, DAY, price, price, price, price, Decimal(1), price, Decimal(2))
    update = TickMinuteUpdate(active=active)
    read_rb = dict(trading_day=DAY, symbol="rb", contract="RB2701", frequency=BarFrequency.M1)
    publisher.publish("rb", tick, update, (), generation=GEN + ":1")
    assert reader.snapshot(**read_rb).quote is None
    publisher.flush()
    initial = reader.snapshot(**read_rb)
    assert initial.quote.last_price == price
    assert initial.quote.bids == tick.bid
    assert initial.activity.bar == active
    assert store.bars_after(DAY, "rb", BarFrequency.M1, None) == ()
    assert redis.xlen("live:observations:completed:2026-11-26") == 0

    from dataclasses import replace

    publisher.clear_activity(DAY, stale=True)
    publisher.publish("au", replace(tick, contract="AU2702", connection=2), update, (), generation=GEN + ":2")
    publisher.flush()
    assert reader.snapshot(**read_rb).quote is None
    read_au = dict(read_rb, symbol="au", contract="AU2702")
    assert reader.snapshot(**read_au).quote.generation == GEN + ":2"
    store.set_subscriptions(DAY, {"rb": "RB2701", "au": "AU2704"})
    assert reader.snapshot(**read_au).quote is None
    assert calls == ["owned", "owned"]


@pytest.mark.parametrize(("changes", "reason"), [
    ({"overflow": True}, "queue_overflow"),
    ({"listener_alive": False}, "listener_stopped"),
    ({"count": 100_000}, "message_limit"),
    ({"now": 10}, "window_elapsed"),
    ({}, None),
])
def test_capture_stops_with_explicit_reason(changes, reason):
    from scripts.market_foundation.capture_tick import _termination

    arguments = dict(overflow=False, listener_alive=True, count=0, now=0, deadline=10)
    assert _termination(**(arguments | changes)) == reason


def test_compare_capture_reports_missing_session_endpoints_and_scope_drift(tmp_path):
    from scripts.market_foundation.compare_tick import replay

    def shard(name, *, day, note, footer=True):
        path = tmp_path / name
        header = dict(symbol="rb", contract="RB2701", trading_day=day,
                      sessions=[[OPEN.isoformat(), (OPEN + timedelta(minutes=2)).isoformat()]])
        with path.open("w") as file:
            file.write(json.dumps(header) + "\n")
            if footer:
                file.write(json.dumps({"capture_end": {"reason": note}}) + "\n")
        return path

    first = shard("first.jsonl", day=str(DAY), note="message_limit")
    second = shard("second.jsonl", day=str(DAY), note="listener_stopped")
    result = replay(first, additional_captures=(second,))
    assert result["endpoint_coverage"]["expected"] == 2
    assert result["endpoint_coverage"]["tick"]["covered"] == 0
    assert result["endpoint_coverage"]["live"]["missing"] == [
        (OPEN + timedelta(minutes=offset)).isoformat() for offset in (1, 2)
    ]
    assert [item["end"]["reason"] for item in result["captures"]] == ["message_limit", "listener_stopped"]
    with pytest.raises(ValueError, match="CAPTURE_DUPLICATE_SHARD"):
        replay(first, additional_captures=(first,))
    with pytest.raises(ValueError, match="CAPTURE_SCOPE_MISMATCH"):
        replay(first, additional_captures=(shard("drift.jsonl", day="2026-11-27", note=None, footer=False),))



def test_ordinary_cohort_cannot_switch_source(monkeypatch):
    from app.runtime_cohort import CohortError, apply_cohort, freeze_cohort

    monkeypatch.setenv("GUIYI_MARKET_SOURCE", "rqdata_tick")
    code = "COHORT_MARKET_SOURCE_HANDOVER_REQUIRED"
    with pytest.raises(CohortError, match=code):
        freeze_cohort(None, candidate_root=None, tag=None, commit=None)
    with pytest.raises(CohortError, match=code):
        apply_cohort(None, None)



def test_complete_day_display_is_bounded_by_authoritative_sessions():
    from app.market_data.aggregation import SessionWindow
    from scripts.market_foundation.run_display import natural_window_seconds

    close = OPEN + timedelta(hours=18)
    windows = (SessionWindow(OPEN, OPEN + timedelta(hours=3)),
               SessionWindow(close - timedelta(hours=6), close))
    assert natural_window_seconds(windows, now=OPEN - timedelta(seconds=30)) == 64950
    with pytest.raises(ValueError, match="DISPLAY_NATURAL_WINDOW_INVALID"):
        natural_window_seconds(windows, now=OPEN)
    overlong = (windows[0], SessionWindow(close, OPEN + timedelta(hours=24)))
    with pytest.raises(ValueError, match="DISPLAY_NATURAL_WINDOW_INVALID"):
        natural_window_seconds(overlong, now=OPEN - timedelta(seconds=30))


def test_archive_revision_ignores_next_day_session(disposable_market, tmp_path):
    from datetime import time

    from sqlalchemy.orm import Session

    from app.market_data.market_archive import reference_catalog_revision
    from app.models import TradingSession
    from tests.data_foundation.test_tick_htdy_integration import _seed_history

    engine, _redis = disposable_market
    _seed_history(engine, tmp_path)
    with Session(engine) as session:
        frozen = reference_catalog_revision(session, "rb", DAY, archive_scope=True)
        broad = reference_catalog_revision(session, "rb", DAY)
        session.add(TradingSession(
            exchange_code="SHFE", instrument_symbol="rb", session_name="later",
            start_time=time(9), end_time=time(15), effective_from=DAY + timedelta(days=1),
        ))
        session.commit()

    with Session(engine) as session:
        assert reference_catalog_revision(session, "rb", DAY, archive_scope=True) == frozen
        assert reference_catalog_revision(session, "rb", DAY) != broad
