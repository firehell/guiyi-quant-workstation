"""HTDY read-only admission of exact Tick-origin minutes and H1 on disposable services."""

from contextlib import contextmanager, nullcontext
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
    yield from _disposable_market(os.environ.get("GUIYI_MARKET_FOUNDATION_TEST_DATABASE_URL"),
                                  os.environ.get("GUIYI_TEST_REDIS_PORT"), formal=False)


@pytest.fixture
def disposable_htdy_market():
    formal = os.environ.get("GUIYI_C6_FORMAL_MARKET_TEST_DATABASE_URL")
    if formal:
        yield from _disposable_market(formal, os.environ.get("GUIYI_C6_FORMAL_MARKET_REDIS_PORT"), formal=True)
    else:
        yield from disposable_market.__wrapped__()


def _disposable_market(pg_target, redis_port, *, formal):
    if not pg_target or not redis_port:
        pytest.skip("requires explicit disposable Market Foundation PostgreSQL and Redis")
    url = make_url(pg_target)
    assert url.get_backend_name() == "postgresql" and not url.query
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert url.database == ("guiyi_quant" if formal else "guiyi_market_foundation")
    assert url.port and url.port != 5432
    assert 1024 <= int(redis_port) <= 65535 and int(redis_port) != 6379

    engine = create_engine(url)
    schema = "tick_htdy_test_" + uuid4().hex
    redis = Redis(host="127.0.0.1", port=int(redis_port), db=0 if formal else 12, decode_responses=True)
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


def _seed_history(engine, root, scope=((PRODUCT, CONTRACT, "SHFE"),)):
    store = CanonicalMonthlyStore(root)
    first = DAY - timedelta(days=6)
    exchanges = sorted({exchange for _, _, exchange in scope})
    with Session(engine) as session:
        session.add_all(Exchange(code=exchange, name=exchange) for exchange in exchanges)
        session.add_all(
            Instrument(symbol=product, name=product.upper(), exchange_code=exchange, is_active=True)
            for product, _, exchange in scope
        )
        session.flush()
        for product, contract, exchange in scope:
            session.add(Contract(
                contract_code=contract, instrument_symbol=product, exchange_code=exchange,
                listed_date=first, expired_date=DAY + timedelta(days=10), provider="rqdata",
            ))
        for offset in range(8):
            day = first + timedelta(days=offset)
            session.add_all(
                TradingCalendar(
                    exchange_code=exchange, trade_date=day, is_trading_day=True,
                    has_night_session=False, provider="rqdata",
                ) for exchange in exchanges
            )
            for product, contract, exchange in scope:
                session.add(TradingSession(
                    exchange_code=exchange, instrument_symbol=product, session_name="day",
                    start_time=time(9), end_time=time(15), effective_from=day, effective_to=day, provider="rqdata",
                ))
                session.add(MainContractMap(symbol=product, trade_date=day, contract_code=contract))
        session.flush()

        for index, (product, contract, _) in enumerate(scope):
            minutes, hours = [], []
            for offset in range(6):
                day = first + timedelta(days=offset)
                begin = datetime.combine(day, time(1), tzinfo=UTC)
                price = Decimal(100 + index + offset)
                bars = tuple(
                    CanonicalBar(begin + minute * MINUTE, day, price, price, price, price,
                                 Decimal(1), Decimal(100), Decimal(51))
                    for minute in range(1, 361)
                )
                minutes.extend(bars)
                hours.extend(aggregate_from_1m(
                    bars, target_frequency=BarFrequency.H1,
                    sessions=(SessionWindow(begin, begin + timedelta(hours=6)),),
                ))
            for frequency, bars in ((BarFrequency.M1, minutes), (BarFrequency.H1, hours)):
                published = store.publish(PublishRequest(
                    DatasetKey("contract", product, contract, frequency), DAY.year, DAY.month,
                    tuple(bars), tuple(bar.bar_end for bar in bars),
                ))
                MarketCatalog(session, root).register_partition(published)
        session.commit()


def _wait_for_subscriber(redis, topics=(TOPIC,)):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if dict(redis.pubsub_numsub(*topics)) == dict.fromkeys(topics, 1):
            return
        sleep(0.01)
    pytest.fail("expected exactly one HTDY subscriber for each topic")


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


def test_isolated_htdy_live_restarts_all_trading_products(disposable_htdy_market, tmp_path, monkeypatch):
    from app.simnow_controlled_market import MarketBridge
    from guiyi_quant import htdy_account_execution as account_api, htdy_execution as execution
    from guiyi_quant.htdy_account_execution.model import TqKqObservedSignalV1
    from guiyi_quant.trading_universe import TRADING_PRODUCTS
    from tests.unit.htdy_execution.test_account_execution import readback

    exchange_products = {
        "DCE": ("jm", "v", "i"), "GFEX": ("lc",), "SHFE": ("rb",), "INE": ("ec", "sc"),
        "CZCE": ("sa", "fg", "ma", "pr", "ta", "ur", "sh", "cj", "oi"),
    }
    exchanges = {product: exchange for exchange, items in exchange_products.items() for product in items}
    assert len(TRADING_PRODUCTS) == 16 and set(exchanges) == set(TRADING_PRODUCTS)
    products = tuple(product.upper() for product in TRADING_PRODUCTS)
    contracts = {product: product.upper() + ("2702" if product == "ec" else "2701") for product in TRADING_PRODUCTS}
    scope = tuple((product, contracts[product], exchanges[product]) for product in TRADING_PRODUCTS)
    topics = tuple(f"live:bar:{product}:60m" for product in TRADING_PRODUCTS)
    engine, redis = disposable_htdy_market
    root = tmp_path / "canonical"
    root.mkdir()
    _seed_history(engine, root, scope)
    formal = engine.url.database == "guiyi_quant"
    if formal:
        from app.market_data.market_foundation_scope import formal_tick_fingerprint

        redis.set("live:market-foundation:formal-binding", formal_tick_fingerprint(redis, engine.url, root))
        monkeypatch.setenv("GUIYI_MARKET_SOURCE", "rqdata_tick")
        monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(root))
        monkeypatch.setattr("app.market_data.market_archive.formal_after_market_status_path",
                            lambda: tmp_path / "after-market-status.json")
        monkeypatch.setattr("app.redis_connections.get_redis_connection", lambda: redis)
    else:
        bind_market_redis(redis, tmp_path, engine.url)
    bind_tick_source(redis)
    store = RedisLiveStore(redis)
    store.set_subscriptions(DAY, contracts)
    source = ObservationStream(redis, kind="source")
    source.initialize("live", DAY, cursor="0-0")
    completed = ObservationStream(redis, kind="completed")
    clock_now = OPEN

    def clock():
        return clock_now

    class TickClient:
        def subscribe(self, channels):
            assert set(channels) == {f"tick_{contract}" for contract in contracts.values()}

        def listen(self, *, handler):
            self.handler = handler

        def close(self):
            pass

    client = TickClient()
    preview = TickPreviewStore()
    window = SessionWindow(OPEN, OPEN + timedelta(hours=6))
    market_args = dict(
        dominant_source=FakeDominants({(product, DAY): contract for product, contract in contracts.items()}),
        phase_resolver=FakePhases({product: _phase(product, DAY, window) for product in TRADING_PRODUCTS}),
        coverage_sessions=lambda *_: (window,),
        operational_products=TRADING_PRODUCTS, authoritative_dominants=True, clock=clock,
    )
    feed = MarketFeedService(
        source_stream=source, store=FeedLiveStore(redis), tick_source=True,
        provider_factory=lambda: TickMarketDataProvider(
            client, connection_identity=lambda: client, preview=preview, clock=clock,
        ),
        shutdown_guard_factory=nullcontext, **market_args,
    )
    publisher = DurableLiveMarketService(source_provider=StreamLiveProvider(source), store=store, **market_args)

    def replay_minutes(start, stop, market, watermarks):
        nonlocal clock_now
        signals = []
        for minute in range(start, stop):
            seen = OPEN + minute * MINUTE
            clock_now = seen + timedelta(milliseconds=10)
            for index, contract in enumerate(contracts.values()):
                price = 101 + index + minute
                client.handler({
                    "channel": f"tick_{contract}", "action": "feed", "order_book_id": contract,
                    "datetime": seen, "volume": minute, "last": price,
                    "total_turnover": price * minute, "open_interest": 51,
                })
            clock_now = seen + timedelta(seconds=3)
            assert feed.poll(clock()) is None
            assert publisher.poll(clock()) is None
            signals.extend(market.poll(clock(), watermarks))
        return tuple(signals)

    @contextmanager
    def inlet():
        if formal:
            from app.tq_simulation_market import compose_market

            with compose_market(products, session_factory=lambda: Session(engine), receipt_clock=clock) as market:
                yield market, lambda: next(iter(market._views.values())).owned_live_compute._days[DAY]
        else:
            scopes = tuple(OwnedLiveScope("htdy_simulation", p, c, "60m", DAY) for p, c, _ in scope)
            with ComputeRuntime(REGISTRY, owned_live_scopes=scopes) as runtime:
                market = PortfolioMarket(
                    products, redis=redis, session_factory=lambda: Session(engine), receipt_clock=clock,
                    require_completed_journal=True, isolated_live_compute=runtime, isolated_canonical_root=root,
                )
                try:
                    yield market, lambda: runtime
                finally:
                    market.close()

    def originals(end):
        events = tuple(completed.read_original(DAY, f"{DAY}:{contract}:60m:{end.isoformat()}")
                       for contract in contracts.values())
        assert {event.channel for event in events} == set(topics)
        assert len({event.stream_id for event in events}) == 16
        assert all(event.notification_eligible and event.source_generation.startswith("rqdata-tick:") for event in events)
        return events

    observed_triggers = []
    signal_from_trigger = MarketBridge.signal_from_trigger

    def record_trigger(view, trigger, observed_at, after):
        observed_triggers.append((view.product, trigger.bar.bar_end))
        return signal_from_trigger(view, trigger, observed_at, after)

    monkeypatch.setattr(MarketBridge, "signal_from_trigger", record_trigger)

    def verify_duplicate_originals(market, events, watermarks, end):
        observed_triggers.clear()
        tail = completed.tail(DAY)
        for event in events:
            assert completed.append(event) == event.stream_id
            assert redis.publish(event.channel, json.dumps(event.data)) == 1
        assert completed.tail(DAY) == tail
        # Subscribe ACKs can yield empty nonblocking polls. Wait for all
        # duplicated originals to actually reach their product's inlet.
        deadline = monotonic() + 2
        while len(observed_triggers) < len(products) and monotonic() < deadline:
            assert market.poll(clock(), watermarks) == ()
            if len(observed_triggers) < len(products):
                sleep(0.01)
        assert sorted(observed_triggers) == sorted((product, end) for product in products)
        assert market.issues == {}

    def verify_signals(signals, end):
        assert len(signals) == len(products)
        assert {signal.product: signal.contract for signal in signals} == {
            product.upper(): contract for product, contract in contracts.items()
        }
        assert len({signal.source_id for signal in signals}) == 16
        assert all(signal.bar_end == end for signal in signals)

    def floors(state):
        return {item.product: item.last_bar for item in state.products}

    def command(signal):
        return TqKqObservedSignalV1(signal, signal.observed_at)

    account = tmp_path / "fast-simulation.sqlite"
    native_identity = "TQKQ:simnow-test:htdy_tqkq_v1"
    initial = account_api.start("simnow-test", products, OPEN, readback(OPEN))
    assert feed.poll(OPEN) is None and publisher.poll(OPEN) is None
    with inlet() as (market, compute_runtime):
        try:
            _wait_for_subscriber(redis, topics)
            market.activate(clock())
            first = replay_minutes(0, 61, market, dict.fromkeys(products, OPEN))
            first_originals = originals(CUTOFF)
            assert market.issues == {}
            verify_signals(first, CUTOFF)
            assert compute_runtime().queue_load()["live"]["peak_pending"] == 1
        finally:
            market.close()

    ledger = account_api.LocalStore(account, initial, execution_identity=native_identity)
    try:
        for product in products:
            key = "owner:" + product
            ledger.execute(key, execution.Owner(product, contracts[product.lower()], OPEN, key))
        for signal in first:
            commit = ledger.execute("tq-signal:" + signal.source_id, command(signal))
            assert not commit.duplicate and not commit.effects
    finally:
        ledger.close()

    settled = account_api.LocalStore.inspect_tip(account)
    assert floors(settled) == dict.fromkeys(products, CUTOFF)
    clock_now = CUTOFF + timedelta(seconds=4)
    with inlet() as (market, compute_runtime):
        ledger = account_api.LocalStore(account, execution_identity=native_identity)
        try:
            _wait_for_subscriber(redis, topics)
            market.activate(clock())
            assert floors(ledger.current()) == floors(settled)
            assert ledger.current().phase == "RECOVERY_REQUIRED"
            proofs = market.recovery(ledger.current(), clock())
            assert market.issues == {}
            assert len(proofs) == 16
            assert {proof.product: (proof.contract, proof.bar_end) for proof in proofs} == {
                product.upper(): (contract, CUTOFF) for product, contract in contracts.items()
            }
            recovery = account_api.Recover(readback(clock()), proofs)
            recovered = ledger.execute("recover", recovery)
            assert recovered.state.phase == "READY" and floors(recovered.state) == floors(settled)
            verify_duplicate_originals(market, first_originals, floors(recovered.state), CUTOFF)
            assert account_api.LocalStore.inspect_tip(account) == recovered.state
            for signal in first:
                duplicate = ledger.execute("tq-signal:" + signal.source_id, command(signal))
                assert duplicate.duplicate and duplicate.sequence == recovered.sequence

            next_end = CUTOFF + timedelta(hours=1)
            following = replay_minutes(61, 121, market, floors(recovered.state))
            next_originals = originals(next_end)
            assert market.issues == {}
            verify_signals(following, next_end)
            assert all(signal.previous_bar_end == CUTOFF for signal in following)
            for number, signal in enumerate(following, start=1):
                expected = floors(ledger.current())
                expected[signal.product] = next_end
                commit = ledger.execute("tq-signal:" + signal.source_id, command(signal))
                assert not commit.duplicate and not commit.effects
                assert commit.sequence == recovered.sequence + number
                assert floors(commit.state) == expected
            finished = ledger.current()
            assert floors(finished) == dict.fromkeys(products, next_end)
            verify_duplicate_originals(market, next_originals, floors(finished), next_end)
            for signal in following:
                duplicate = ledger.execute("tq-signal:" + signal.source_id, command(signal))
                assert duplicate.duplicate and duplicate.sequence == recovered.sequence + 16
            assert ledger.current() == finished and compute_runtime().queue_load()["live"]["peak_pending"] == 1
        finally:
            ledger.close()
            market.close()
    assert account_api.LocalStore.inspect(account) == finished
