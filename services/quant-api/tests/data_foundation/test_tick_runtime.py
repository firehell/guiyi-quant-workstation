"""Requested isolated Market runtime and display paths on native services."""
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.market_data.live_market import RedisLiveStore
from app.market_data.market_foundation_scope import bind_market_redis, bind_tick_source
from app.market_data.observation_stream import ObservationStream
from app.market_data.tick_runtime import build_isolated_tick_display, open_isolated_tick_market
from tests.data_foundation.test_tick_htdy_integration import (
    CONTRACT, DAY, MINUTE, OPEN, PRODUCT, _seed_history,
    disposable_market as native_market_fixture,
)


@pytest.fixture
def disposable_market():
    yield from native_market_fixture.__wrapped__()


def test_tick_writer_and_display_share_exact_isolated_runtime(disposable_market, tmp_path, monkeypatch):
    engine, redis = disposable_market
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _seed_history(engine, canonical)
    redis_url = f"redis://127.0.0.1:{redis.connection_pool.connection_kwargs['port']}/12"
    monkeypatch.setenv("GUIYI_NEWOW_REFERENCE_MODE", "market_foundation_isolated")
    monkeypatch.setenv("GUIYI_MARKET_FOUNDATION_SANDBOX", str(tmp_path))
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(canonical))
    now = [OPEN]

    class TickSocket:
        _client = object()

        def subscribe(self, channels):
            assert channels == [f"tick_{CONTRACT}"]

        def listen(self, *, handler):
            self.handler = handler

        def close(self):
            pass

    socket = TickSocket()
    with Session(engine) as session, open_isolated_tick_market(
        session=session, database_url=engine.url, redis_url=redis_url, canonical_root=canonical,
        products=(PRODUCT,), client_factory=lambda: socket, clock=lambda: now[0],
    ) as market:
        market.bind_day(DAY)
        with pytest.raises(RuntimeError, match="LIVE_RECOVERY_BUSY"), Session(engine) as other, open_isolated_tick_market(
            session=other, database_url=engine.url, redis_url=redis_url, canonical_root=canonical,
            products=(PRODUCT,), client_factory=lambda: socket,
        ):
            pytest.fail("second writer unexpectedly acquired the namespace")

        assert market.poll(now[0]) == (None, None)
        for offset, volume in ((0, 0), (1, 2), (60, 3)):
            observed = OPEN + timedelta(seconds=offset)
            now[0] = observed + timedelta(milliseconds=25)
            socket.handler({"action": "feed", "channel": f"tick_{CONTRACT}", "order_book_id": CONTRACT,
                            "datetime": observed, "last": 100 + volume,
                            "volume": volume, "total_turnover": 100 * volume})
        now[0] = OPEN + MINUTE + timedelta(seconds=3)
        assert market.poll(now[0]) == (None, None)
        stream = ObservationStream(redis, kind="completed")
        assert redis.xlen(stream.key(DAY)) == 1

        app = build_isolated_tick_display(
            market, redis_url=redis_url, canonical_root=canonical,
            after_market_status_path=tmp_path / "after-market-status.json",
        )
        with TestClient(app) as client:
            response = client.get("/api/v1/market/bars/page", params={
                "series_kind": "contract", "frequency": "1m", "symbol": PRODUCT,
                "contract": CONTRACT, "limit": "500",
            })
            assert response.status_code == 200, response.json()
            bars = response.json()["bars"]
            assert len(bars) == 500 and bars[-1]["trading_day"] != DAY.isoformat()
            assert bars[-1]["source_bar_sha256"]
            assert client.post("/api/v1/broker/orders").status_code == 404
        with pytest.raises(ValueError, match="MARKET_FOUNDATION_REDIS_BINDING_CONFLICT"):
            bind_market_redis(redis, tmp_path / "different", engine.url)
    assert redis.xlen(stream.key(DAY)) == 1

    # A real day cleanup removes the overlay but intentionally preserves
    # the native observation journal and its cursor.
    RedisLiveStore(redis).cleanup_trading_day(DAY)
    following = DAY + timedelta(days=1)
    now[0] = OPEN + timedelta(days=1)
    with Session(engine) as session, open_isolated_tick_market(
        session=session, database_url=engine.url, redis_url=redis_url, canonical_root=canonical,
        products=(PRODUCT,), client_factory=TickSocket, clock=lambda: now[0],
        closed_cleanup_evidence=lambda day, _at: (
            {"trading_day": str(DAY), "cleanup_verified": True} if day == DAY else None
        ),
    ) as resumed:
        resumed.bind_day(following)
        assert resumed.poll(now[0]) == (None, None)
        assert resumed.feed.source_stream.registered_day("live") == following
    assert redis.xlen(stream.key(DAY)) == 1
    assert RedisLiveStore(redis).subscriptions(DAY) is None


def test_tick_source_refuses_existing_legacy_minute_cursor(disposable_market):
    _engine, redis = disposable_market
    source = ObservationStream(redis, kind="source")
    source.initialize("live", DAY, cursor="0-0")
    with pytest.raises(ValueError, match="MARKET_FOUNDATION_TICK_SOURCE_CONFLICT"):
        bind_tick_source(redis)
    assert source.cursor("live", DAY) == "0-0"


@pytest.mark.manual_acceptance
def test_isolated_runtime_replays_real_tick_capture(disposable_market, tmp_path, monkeypatch):
    """Replay native RQData messages without another supplier call."""
    from datetime import date, datetime
    import json
    import os
    from pathlib import Path

    from app.market_data.live_market import _canonical_bar_from_raw_feed, _bar_from_payload
    from app.market_data.session_clock import SHANGHAI
    from app.models import TradingCalendar, TradingSession
    from sqlalchemy import delete, select

    selected = os.environ.get("GUIYI_MARKET_FOUNDATION_CAPTURE")
    if not selected:
        pytest.skip("requires a bounded real RQData capture")
    capture = Path(selected)
    assert capture.is_relative_to("/private/tmp") and capture.is_file()
    assert capture.stat().st_size < 16 * 1024 * 1024
    with capture.open() as source:
        header = json.loads(next(source))
        records = tuple(record for line in source if "payload" in (record := json.loads(line)))
    assert header["contract"] == CONTRACT and date.fromisoformat(header["trading_day"]) == DAY

    engine, redis = disposable_market
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _seed_history(engine, canonical)
    sessions = [tuple(datetime.fromisoformat(point).astimezone(SHANGHAI) for point in period)
                for period in header["sessions"]]
    with Session(engine) as session:
        session.execute(delete(TradingSession).where(TradingSession.effective_from == DAY))
        for index, (start, end) in enumerate(sessions):
            session.add(TradingSession(
                exchange_code="SHFE", instrument_symbol=PRODUCT,
                session_name="night" if start.date() != DAY else f"day{index}",
                start_time=start.time(), end_time=end.time(),
                effective_from=DAY, effective_to=DAY, provider="rqdata",
            ))
        calendar = session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY, TradingCalendar.exchange_code == "SHFE",
        ))
        assert calendar is not None
        calendar.has_night_session = True
        session.commit()

    redis_url = f"redis://127.0.0.1:{redis.connection_pool.connection_kwargs['port']}/12"
    monkeypatch.setenv("GUIYI_NEWOW_REFERENCE_MODE", "market_foundation_isolated")
    monkeypatch.setenv("GUIYI_MARKET_FOUNDATION_SANDBOX", str(tmp_path))
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(canonical))

    class CaptureSocket:
        _client = object()
        handler = None

        def subscribe(self, channels):
            assert channels == [f"tick_{CONTRACT}"]

        def unsubscribe(self, _channels):
            self.handler = None

        def listen(self, *, handler):
            self.handler = handler

        def close(self):
            self.handler = None

    socket = CaptureSocket()
    now = [datetime.fromisoformat(header["started_at"])]
    direct = {}
    with Session(engine) as session, open_isolated_tick_market(
        session=session, database_url=engine.url, redis_url=redis_url, canonical_root=canonical,
        products=(PRODUCT,), client_factory=lambda: socket, clock=lambda: now[0],
    ) as market:
        market.bind_day(DAY)
        for item in records:
            now[0] = datetime.fromisoformat(item["received_at"])
            payload = item["payload"]
            if payload["channel"] == f"bar_{CONTRACT}":
                parsed = _canonical_bar_from_raw_feed(payload)
                assert parsed is not None
                direct[parsed[1].bar_end] = parsed[1]
                continue
            if socket.handler is None:
                assert market.poll(now[0]) == (None, None)
            assert socket.handler is not None
            socket.handler(payload)
            assert market.poll(now[0]) == (None, None)
        now[0] += timedelta(seconds=3)
        assert market.poll(now[0]) == (None, None)
        stream = ObservationStream(redis, kind="completed")
        rows = redis.xrange(stream.key(DAY))
        actual = {}
        from app.market_data.observation_stream import ObservationEnvelope

        for _identifier, fields in rows:
            event = ObservationEnvelope.from_json(fields["envelope"])
            if event.channel.endswith(":1m"):
                bar = _bar_from_payload(json.dumps(event.data))
                actual[bar.bar_end] = bar
        assert len(actual) == 3 and len(direct) == 4
        assert actual == {end: direct[end] for end in actual}
