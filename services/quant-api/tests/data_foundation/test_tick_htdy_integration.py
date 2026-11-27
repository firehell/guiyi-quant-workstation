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
from app.compute_runtime import ComputeRuntime
from app.compute_runtime.owned_live import OwnedLiveScope
from app.db.base import Base
from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, SeriesPageQuery
from app.market_data.htdy_input_admission import current_minute_input
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_feed import DurableLiveMarketService, FeedLiveStore, MarketFeedService, StreamLiveProvider
from app.market_data.market_foundation_scope import bind_market_redis, bind_tick_source
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.market_read_service import MarketReadService
from app.market_data.observation_stream import ObservationStream
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.models import Contract, Exchange, Instrument, MainContractMap, TradingCalendar, TradingSession
from app.simnow_portfolio_market import PortfolioMarket
from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _phase
from tests.data_foundation.test_tick_market import DAY, MINUTE
from guiyi_quant.compute import REGISTRY

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


@pytest.mark.parametrize(("delayed_completion", "owned_live"), (
    (False, False), (True, False), (False, True),
), ids=("normal", "late-restart", "isolated-live"))
def test_tick_completed_h1_and_m1_admit_to_htdy_without_replay_after_restart(
    disposable_market, tmp_path, monkeypatch, delayed_completion, owned_live, request,
):
    engine, redis = disposable_market
    root = tmp_path / "canonical"
    root.mkdir()
    _seed_history(engine, root)
    clock_now = [OPEN]

    def clock():
        return clock_now[0]

    def market_data(db):
        return MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))

    def scoped_market_read(db, *, redis):
        return MarketReadService(
            market_data=market_data(db), phase_resolver=MarketPhaseResolver(db),
            operational_products=(PRODUCT,), live_store=RedisLiveStore(redis),
            after_market_status_path=tmp_path / "absent-status.json",
        )

    if owned_live:
        def reject_ambient(*_args, **_kwargs):
            pytest.fail("isolated reader must never fall back to the ambient Catalog root")

        monkeypatch.setattr("app.simnow_portfolio_market.build_market_read_service", reject_ambient)
    else:
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
    if owned_live:
        bind_tick_source(redis)
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

    def portfolio_market(runtime=None):
        return PortfolioMarket((PRODUCT,), redis=redis, session_factory=lambda: Session(engine),
                               receipt_clock=clock, require_completed_journal=True, isolated_live_compute=runtime,
                               isolated_canonical_root=root if runtime is not None else None)

    def make_runtime():
        if not owned_live:
            return None
        runtime = ComputeRuntime(REGISTRY, owned_live_scopes=(
            OwnedLiveScope("htdy_simulation", PRODUCT, CONTRACT, "60m", DAY),
        ))
        request.addfinalizer(runtime.close)
        return runtime

    market_compute = live()

    def tick(minute):
        seen = OPEN + minute * MINUTE
        clock_now[0] = seen + timedelta(milliseconds=10)
        client.handler({
            "channel": f"tick_{CONTRACT}", "action": "feed", "order_book_id": CONTRACT,
            "datetime": seen, "volume": minute, "last": 101 + minute,
            "total_turnover": 100 * minute, "open_interest": 51,
        })
        clock_now[0] = seen + timedelta(seconds=3)
        assert feed.poll(clock()) is None

    assert feed.poll(OPEN) is None and market_compute.poll(OPEN) is None
    runtime = make_runtime()
    if owned_live:
        with pytest.raises(ValueError, match="COMPUTE_LIVE_ISOLATION_REQUIRED"):
            portfolio_market(runtime)
        # Prove that Pub/Sub is fenced by a candidate binding and stays
        # unavailable if the same logical DB claims to be a formal source.
        bind_market_redis(redis, tmp_path, engine.url)
        redis.set("live:market-foundation:formal-binding", "f" * 64)
        try:
            with pytest.raises(ValueError, match="COMPUTE_LIVE_ISOLATION_REQUIRED"):
                portfolio_market(runtime)
        finally:
            redis.delete("live:market-foundation:formal-binding")
        port = redis.connection_pool.connection_kwargs["port"]
        with Redis(host="127.0.0.1", port=port, db=0) as shared:
            assert shared.dbsize() == 0
            shared.set("test:another-owner", "present")
            try:
                with pytest.raises(ValueError, match="COMPUTE_LIVE_ISOLATION_REQUIRED"):
                    portfolio_market(runtime)
            finally:
                shared.delete("test:another-owner")
    inlet = portfolio_market(runtime)
    try:
        _wait_for_subscriber(redis)
        inlet.activate(OPEN)
        for minute in range(61):
            tick(minute)
            if minute == 35:
                market_compute = live()
            if not delayed_completion or minute < 59:
                assert market_compute.poll(clock()) is None

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
            if owned_live:
                assert runtime.queue_load()["live"]["peak_pending"] == 1
                assert view.signal_from_trigger(trigger, clock(), OPEN) is signals[0]
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
    account = None
    if owned_live:
        from guiyi_quant import htdy_account_execution as account_api, htdy_execution as execution
        from tests.unit.htdy_execution.test_account_execution import readback

        state = account_api.start("simnow-test", (PRODUCT.upper(),), OPEN, readback(OPEN))
        state = account_api.apply(state, "owner", execution.Owner(PRODUCT.upper(), CONTRACT, OPEN, "owner-rb")).state
        account = tmp_path / "tq-live.sqlite"
        ledger = account_api.LocalStore(account, state)
        try:
            ledger.execute(signals[0].source_id, signals[0])
        finally:
            ledger.close()
        assert account_api.LocalStore.inspect_tip(account).products[0].last_bar == CUTOFF
        runtime.close()

    restarted = portfolio_market(make_runtime())
    try:
        _wait_for_subscriber(redis)
        restarted.activate(clock())
        market_compute = live()
        assert market_compute.poll(clock()) is None
        assert completed.tail(DAY) == tail
        assert restarted.poll(clock(), {PRODUCT: CUTOFF}) == ()
        restarted_alert = StreamAlertMessageSource(redis)
        try:
            assert restarted_alert.get_message(timeout_seconds=0) is None
        finally:
            restarted_alert.close()
        if owned_live:
            # The owner and Live queue have both been recreated. Re-publishing
            # a wake-up for the same retained original cannot update the book.
            settled = account_api.LocalStore.inspect_tip(account)
            floor = {PRODUCT: settled.products[0].last_bar}
            redis.publish(original.channel, json.dumps(original.data))
            assert restarted.poll(clock(), floor) == ()
            assert account_api.LocalStore.inspect_tip(account) == settled
            for minute in range(61, 121):
                tick(minute)
                assert market_compute.poll(clock()) is None
            (next_signal,) = restarted.poll(clock(), floor)
            assert next_signal.bar_end == CUTOFF + timedelta(hours=1)
            assert next_signal.previous_bar_end == CUTOFF
            ledger = account_api.LocalStore(account)
            try:
                recovery = account_api.Recover(
                    readback(CUTOFF + timedelta(seconds=4)),
                    (execution.RecoveryInput(PRODUCT.upper(), CONTRACT, settled.products[0].desired,
                                             CUTOFF, "reopen-from-proven-h1"),),
                )
                ledger.execute("recover", recovery)
                assert ledger.current().products[0].last_bar == CUTOFF
                ledger.execute(next_signal.source_id, next_signal)
            finally:
                ledger.close()
            assert account_api.LocalStore.inspect_tip(account).products[0].last_bar == next_signal.bar_end
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
