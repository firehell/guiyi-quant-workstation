"""HTDY read-only admission of exact Tick-origin minutes and H1 on disposable services."""

from contextlib import nullcontext
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
import json
import os
from time import monotonic, sleep
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.alerts.composition import StreamAlertMessageSource
from app.db.base import Base
from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, SeriesPageQuery
from app.market_data.htdy_input_admission import current_minute_input
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_feed import DurableLiveMarketService, FeedLiveStore, MarketFeedService, StreamLiveProvider
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.market_read_service import MarketReadService
from app.market_data.observation_stream import ObservationStream
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.models import Contract, Exchange, Instrument, MainContractMap, TradingCalendar, TradingSession
from app.simnow_portfolio_market import PortfolioMarket
from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _phase
from tests.data_foundation.test_tick_market import DAY, MINUTE

pytestmark = pytest.mark.isolated_postgresql

PRODUCT = "rb"
CONTRACT = "RB2701"
TOPIC = f"live:bar:{PRODUCT}:60m"
OPEN = datetime.combine(DAY, time(1), tzinfo=UTC)
CUTOFF = OPEN + timedelta(hours=1)


@pytest.fixture
def disposable_market():
    pg_target = os.environ.get("GUIYI_MARKET_FOUNDATION_TEST_DATABASE_URL")
    redis_port = os.environ.get("GUIYI_TEST_REDIS_PORT")
    if not pg_target or not redis_port:
        pytest.skip("requires explicit disposable Market Foundation PostgreSQL and Redis")
    url = make_url(pg_target)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert url.database == "guiyi_market_foundation" and url.port and url.port != 5432
    assert 1024 <= int(redis_port) <= 65535 and int(redis_port) != 6379

    engine = create_engine(url)
    schema = "tick_htdy_test_" + uuid4().hex
    redis = Redis(host="127.0.0.1", port=int(redis_port), db=12, decode_responses=True)
    assert redis.dbsize() == 0, "dedicated Redis DB 12 must be empty"
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_database()")) == url.database
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        yield scoped, redis
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        for key in redis.scan_iter():
            redis.delete(key)
        redis.close()
        engine.dispose()


def _seed_history(engine, root):
    store = CanonicalMonthlyStore(root)
    first = DAY - timedelta(days=6)
    with Session(engine) as session:
        session.add(Exchange(code="SHFE", name="SHFE"))
        session.add(Instrument(symbol=PRODUCT, name="RB", exchange_code="SHFE", is_active=True))
        session.flush()
        session.add(Contract(
            contract_code=CONTRACT, instrument_symbol=PRODUCT, exchange_code="SHFE",
            listed_date=first, expired_date=DAY + timedelta(days=10), provider="rqdata",
        ))
        for offset in range(8):
            day = first + timedelta(days=offset)
            session.add(TradingSession(
                exchange_code="SHFE", instrument_symbol=PRODUCT, session_name="day",
                start_time=time(9), end_time=time(15), effective_from=day, effective_to=day, provider="rqdata",
            ))
            session.add(TradingCalendar(
                exchange_code="SHFE", trade_date=day, is_trading_day=True,
                has_night_session=False, provider="rqdata",
            ))
            session.add(MainContractMap(symbol=PRODUCT, trade_date=day, contract_code=CONTRACT))
        session.flush()

        minutes, hours = [], []
        for offset in range(6):
            day = first + timedelta(days=offset)
            begin = datetime.combine(day, time(1), tzinfo=UTC)
            source = tuple(
                CanonicalBar(begin + minute * MINUTE, day, price, price, price, price,
                             Decimal(1), Decimal(100), Decimal(51))
                for minute in range(1, 361)
                for price in (Decimal(100 + offset),)
            )
            minutes.extend(source)
            hours.extend(aggregate_from_1m(
                source, target_frequency=BarFrequency.H1,
                sessions=(SessionWindow(begin, begin + timedelta(hours=6)),),
            ))
        for frequency, bars in ((BarFrequency.M1, minutes), (BarFrequency.H1, hours)):
            key = DatasetKey("contract", PRODUCT, CONTRACT, frequency)
            published = store.publish(PublishRequest(
                key, DAY.year, DAY.month, tuple(bars), tuple(bar.bar_end for bar in bars),
            ))
            MarketCatalog(session, root).register_partition(published)
        session.commit()


def _wait_for_subscriber(redis):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if redis.pubsub_numsub(TOPIC) == [(TOPIC, 1)]:
            return
        sleep(0.01)
    pytest.fail("expected exactly one HTDY subscription")


@pytest.mark.parametrize("delayed_completion", (False, True), ids=("normal", "late-restart"))
def test_tick_completed_h1_and_m1_admit_to_htdy_without_replay_after_restart(
    disposable_market, tmp_path, monkeypatch, delayed_completion,
):
    engine, redis = disposable_market
    _seed_history(engine, tmp_path)
    clock_now = [OPEN]

    def clock():
        return clock_now[0]

    def market_data(db):
        return MarketDataService(MarketCatalog(db, tmp_path), CanonicalMonthlyStore(tmp_path))

    def scoped_market_read(db, *, redis):
        return MarketReadService(
            market_data=market_data(db), phase_resolver=MarketPhaseResolver(db),
            operational_products=(PRODUCT,), live_store=RedisLiveStore(redis),
            after_market_status_path=tmp_path / "absent-status.json",
        )

    monkeypatch.setattr("app.simnow_portfolio_market.build_market_read_service", scoped_market_read)
    class Client:
        def subscribe(self, channels):
            assert channels == [f"tick_{CONTRACT}"]

        def listen(self, *, handler):
            self.handler = handler

        def close(self):
            pass

    client = Client()
    preview = TickPreviewStore()
    store = RedisLiveStore(redis)
    store.set_subscriptions(DAY, {PRODUCT: CONTRACT})
    source = ObservationStream(redis, kind="source")
    source.initialize("live", DAY, cursor="0-0")
    completed = ObservationStream(redis, kind="completed")
    completed.initialize("alert", DAY, cursor="0-0")
    window = SessionWindow(OPEN, OPEN + timedelta(hours=6))
    args = dict(
        dominant_source=FakeDominants({(PRODUCT, DAY): CONTRACT}),
        phase_resolver=FakePhases({PRODUCT: _phase(PRODUCT, DAY, window)}),
        coverage_sessions=lambda *_: (window,), operational_products=(PRODUCT,),
        authoritative_dominants=True, clock=clock,
    )
    feed = MarketFeedService(
        source_stream=source, store=FeedLiveStore(redis), tick_source=True,
        provider_factory=lambda: TickMarketDataProvider(
            client, connection_identity=lambda: client, preview=preview, clock=clock,
        ),
        shutdown_guard_factory=nullcontext, **args,
    )

    def live():
        return DurableLiveMarketService(source_provider=StreamLiveProvider(source), store=store, **args)

    def portfolio_market():
        return PortfolioMarket((PRODUCT,), redis=redis, session_factory=lambda: Session(engine),
                               receipt_clock=clock, require_completed_journal=True)

    compute = live()
    assert feed.poll(OPEN) is None and compute.poll(OPEN) is None
    inlet = portfolio_market()
    try:
        _wait_for_subscriber(redis)
        inlet.activate(OPEN)
        for minute in range(61):
            seen = OPEN + minute * MINUTE
            clock_now[0] = seen + timedelta(milliseconds=10)
            client.handler({
                "channel": f"tick_{CONTRACT}", "action": "feed", "order_book_id": CONTRACT,
                "datetime": seen, "volume": minute, "last": 101 + minute,
                "total_turnover": 100 * minute, "open_interest": 51,
            })
            clock_now[0] = seen + timedelta(seconds=3)
            assert feed.poll(clock()) is None
            if minute == 35:
                compute = live()
            if not delayed_completion or minute < 59:
                assert compute.poll(clock()) is None

        if delayed_completion:
            # The source journal accepted the last two Tick-derived minutes,
            # then the completion process stopped. The HTDY inlet stays active.
            clock_now[0] += timedelta(seconds=31)
            assert live().poll(clock()) is None
        events = completed.read("alert", DAY)
        original = events[-1]
        assert original.channel == TOPIC
        assert original.source_generation.startswith("rqdata-tick:")
        assert original.confirmed_at == clock()
        assert original.notification_eligible is not delayed_completion
        with inlet.reader() as (db, read):
            phase = MarketPhaseResolver(db).resolve(PRODUCT, clock())
            minute = current_minute_input(read, PRODUCT, phase, clock())
        assert minute["status"] == "CONTINUITY_VERIFIED", minute
        assert minute["expected_endpoint"] == CUTOFF and minute["actual_count"] == 60
        signals = inlet.poll(clock(), {PRODUCT: OPEN})
        if delayed_completion:
            assert signals == ()
        else:
            assert minute["recovery_fenced"] is False
            assert [(signal.product, signal.contract, signal.bar_end) for signal in signals] == [
                (PRODUCT.upper(), CONTRACT, CUTOFF),
            ], inlet.issues
            assert inlet.issues == {}
            assert inlet.poll(clock(), {PRODUCT: CUTOFF}) == ()

        recovery_key = store._recovery_key(DAY, PRODUCT, CONTRACT)
        if not delayed_completion:
            from app.alerts.runtime import _parse_live_bar_trigger

            trigger = _parse_live_bar_trigger(original.channel, original.data)
            view = inlet._views[PRODUCT.upper()]
            index_key = completed.identity_key(DAY)
            index = redis.hget(index_key, original.observation_id)
            assert index is not None
            redis.hdel(index_key, original.observation_id)
            try:
                with pytest.raises(ValueError, match="HTDY_COMPLETED_ORIGINAL_UNPROVEN"):
                    view.signal_from_trigger(trigger, clock(), OPEN)
                mismatched = json.loads(index)
                mismatched["payload"] += " "
                redis.hset(index_key, original.observation_id, json.dumps(mismatched))
                with pytest.raises(ValueError, match="HTDY_COMPLETED_ORIGINAL_UNPROVEN"):
                    view.signal_from_trigger(trigger, clock(), OPEN)
            finally:
                redis.hset(index_key, original.observation_id, index)
            _assert_recovery_fence(redis, store, inlet, recovery_key, clock)
    finally:
        inlet.close()

    alert = StreamAlertMessageSource(redis)
    try:
        observed = []
        for expected in events:
            message = alert.get_message(timeout_seconds=0)
            if not expected.notification_eligible:
                assert message is None and alert.current_observation is None
                continue
            assert message is not None and message[0] == expected.channel
            assert alert.current_observation == expected
            observed.append(message[0])
            alert.ack_current()
        assert (TOPIC in observed) is not delayed_completion
        assert completed.cursor("alert", DAY) == original.stream_id
    finally:
        alert.close()

    tail = completed.tail(DAY)
    restarted = portfolio_market()
    try:
        _wait_for_subscriber(redis)
        restarted.activate(clock())
        assert live().poll(clock()) is None
        assert completed.tail(DAY) == tail
        assert restarted.poll(clock(), {PRODUCT: CUTOFF}) == ()
        restarted_alert = StreamAlertMessageSource(redis)
        try:
            assert restarted_alert.get_message(timeout_seconds=0) is None
        finally:
            restarted_alert.close()
    finally:
        restarted.close()


def _assert_recovery_fence(redis, store, inlet, recovery_key, clock):
    redis.set(recovery_key, json.dumps({"revision": 1, "recovered_through": CUTOFF.isoformat()}))
    try:
        with inlet.reader() as (db, read):
            phase = MarketPhaseResolver(db).resolve(PRODUCT, clock())
            repaired = current_minute_input(read, PRODUCT, phase, clock())
            # A recovered input may warm the indicator but cannot open a new order.
            assert repaired["status"] == "CONTINUITY_VERIFIED" and repaired["recovery_fenced"]
            retained = read.bars_until(
                SeriesPageQuery("actual_dominant", PRODUCT, BarFrequency.H1),
                trading_day=DAY, end=CUTOFF, limit=32,
            ).bars[-1]
        store.publish_bar(PRODUCT, BarFrequency.H1, retained, contract=CONTRACT)
        # Redis Pub/Sub delivers on a different connection from the publisher.
        # Poll until the actual frame is observed, asserting no execution on
        # every poll while the recovery fence remains in place.
        deadline = monotonic() + 3
        while monotonic() < deadline and not inlet.issues:
            assert inlet.poll(clock(), {PRODUCT: OPEN}) == ()
            if not inlet.issues:
                sleep(0.01)
        assert inlet.issues == {PRODUCT.upper(): "HTDY_EXECUTION_REQUIRES_FIRST_SEEN"}
    finally:
        redis.delete(recovery_key)
