from datetime import UTC, date, datetime, timedelta
from dataclasses import replace

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore
from tests.data_foundation.test_live_market import FakeRedis, _bar


def test_recovery_missing_first_minute_rebuilds_completed_buckets_without_publish():
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2025, 1, 2)
    snapshot = {"rb": "RB2505"}
    store.set_subscriptions(day, snapshot)
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    bars = tuple(_bar(m) for m in range(1, 16))
    for bar in bars[1:]:
        store.put_bar(day, "rb", "1m", bar, contract="RB2505")
    request = LiveRecoveryRequest(
        day,
        "rb",
        "RB2505",
        tuple(snapshot.items()),
        (SessionWindow(start, start + timedelta(minutes=60)),),
        start + timedelta(minutes=15, seconds=3),
    )
    calls = []

    def fetch(req):
        calls.append(req)
        return bars

    outcome = recover_product(
        store, request, fetch, clock=lambda: start + timedelta(minutes=16)
    )
    assert outcome == "RECOVERED"
    assert len(store.bars_after(day, "rb", "15m", None)) == 1
    assert len(store.bars_after(day, "rb", "5m", None)) == 3
    assert store.recovery_state(day, "rb", "RB2505").revision == 1
    assert store.recovery_state(
        day, "rb", "RB2505"
    ).recovered_through == start + timedelta(minutes=16)
    assert redis.published == []
    assert (
        recover_product(
            store, request, fetch, clock=lambda: start + timedelta(minutes=17)
        )
        == "NO_GAP"
    )
    assert len(calls) == 1


def test_normal_put_does_not_overwrite_conflicting_completed_bar():
    store = RedisLiveStore(FakeRedis())
    bar = _bar(1)
    store.put_bar(bar.trading_day, "rb", "1m", bar, contract="RB2505")
    with pytest.raises(ValueError, match="LIVE_BAR_CONFLICT"):
        store.put_bar(
            bar.trading_day,
            "rb",
            "1m",
            replace(bar, volume=bar.volume + 1),
            contract="RB2505",
        )
    assert store.bars_after(bar.trading_day, "rb", "1m", None) == (bar,)


def _setup():
    from app.market_data.live_recovery import LiveRecoveryRequest

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    start = datetime(2025, 1, 2, 1, tzinfo=UTC)
    bars = tuple(_bar(m) for m in range(1, 16))
    store.set_subscriptions(bars[0].trading_day, {"rb": "RB2505"})
    for bar in bars[1:]:
        store.put_bar(bar.trading_day, "rb", "1m", bar, contract="RB2505")
    request = LiveRecoveryRequest(
        bars[0].trading_day,
        "rb",
        "RB2505",
        (("rb", "RB2505"),),
        (SessionWindow(start, start + timedelta(hours=1)),),
        start + timedelta(minutes=15, seconds=3),
    )
    return redis, store, request, bars


@pytest.mark.parametrize(
    "failure", ["incomplete", "future", "duplicate", "wrong_day", "conflict", "drift"]
)
def test_invalid_recovery_never_changes_bars_or_barrier(failure):
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    original = {k: dict(v) for k, v in redis.zsets.items()}

    def fetch(req):
        if failure == "incomplete":
            return bars[1:]
        if failure == "future":
            return (
                *bars,
                replace(bars[-1], bar_end=bars[-1].bar_end + timedelta(minutes=1)),
            )
        if failure == "duplicate":
            return (bars[0], *bars[:-1])
        if failure == "wrong_day":
            return (replace(bars[0], trading_day=date(2025, 1, 3)), *bars[1:])
        if failure == "conflict":
            return (*bars[:-1], replace(bars[-1], volume=bars[-1].volume + 1))
        store.set_subscriptions(req.trading_day, {"rb": "RB2510"})
        return bars

    with pytest.raises(ValueError):
        recover_product(store, request, fetch, clock=lambda: request.cutoff)
    assert redis.zsets == original
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None
    assert redis.published == []


def test_retry_budget_survives_store_restart_and_new_session_resets():
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    calls = []

    def fetch(req):
        calls.append(req)
        raise ValueError("PROVIDER_UNAVAILABLE")

    for minute in range(3):
        current = replace(request, cutoff=request.cutoff + timedelta(minutes=minute))
        with pytest.raises(ValueError):
            recover_product(
                RedisLiveStore(redis), current, fetch, clock=lambda: current.cutoff
            )
    assert (
        recover_product(
            RedisLiveStore(redis),
            replace(request, cutoff=request.cutoff + timedelta(minutes=3)),
            fetch,
            clock=lambda: request.cutoff,
        )
        == "RETRY_BUDGET_BLOCKED"
    )
    assert len(calls) == 3


def test_permission_circuit_stops_other_products_and_restart():
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()

    def denied(req):
        raise ValueError("PROVIDER_ACCESS_DENIED")

    with pytest.raises(ValueError):
        recover_product(store, request, denied, clock=lambda: request.cutoff)
    assert (
        recover_product(
            RedisLiveStore(redis),
            replace(request, cutoff=request.cutoff + timedelta(minutes=2)),
            lambda _: pytest.fail("network after circuit"),
            clock=lambda: request.cutoff,
        )
        == "RETRY_BUDGET_BLOCKED"
    )


def test_worker_no_gap_does_not_instantiate_provider():
    from app.market_data.live_recovery import LiveRecoveryWorker

    redis, store, request, bars = _setup()
    store.put_bar(request.trading_day, "rb", "1m", bars[0], contract="RB2505")
    worker = LiveRecoveryWorker(
        store,
        lambda: pytest.fail("provider factory on no gap"),
        clock=lambda: request.cutoff,
    )
    worker._run((request,))
    assert worker.outcomes == (("rb", "RECOVERED"),)
    worker._run((request,))
    assert worker.outcomes == (("rb", "NO_GAP"),)
    worker._executor.shutdown(wait=True)


def test_all_60_products_recover_afternoon_first_minute_and_all_derived_buckets():
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product
    from app.market_data.operational_universe import load_operational_products

    products = load_operational_products()
    assert len(products) == 60
    redis = FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2026, 9, 7)
    start = datetime(2026, 9, 7, 5, 30, tzinfo=UTC)
    snapshot = {symbol: f"{symbol.upper()}2611" for symbol in products}
    store.set_subscriptions(day, snapshot)
    bars = tuple(
        replace(_bar(1), bar_end=start + timedelta(minutes=i), trading_day=day)
        for i in range(1, 61)
    )
    for symbol, contract in snapshot.items():
        request = LiveRecoveryRequest(
            day,
            symbol,
            contract,
            tuple(snapshot.items()),
            (SessionWindow(start, start + timedelta(minutes=60)),),
            start + timedelta(minutes=60, seconds=3),
        )
        for bar in bars[1:]:
            store.put_bar(day, symbol, "1m", bar, contract=contract)
        assert (
            recover_product(
                store, request, lambda _: bars, clock=lambda: request.cutoff
            )
            == "RECOVERED"
        )
        for frequency in ("5m", "15m", "30m", "60m"):
            assert (
                len(store.bars_after(day, symbol, frequency, None))
                == {"5m": 12, "15m": 4, "30m": 2, "60m": 1}[frequency]
            )
    assert redis.published == []


def test_night_endpoints_keep_exchange_trading_day():
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2026, 9, 7)
    start = datetime(2026, 9, 4, 13, tzinfo=UTC)
    store.set_subscriptions(day, {"rb": "RB2611"})
    request = LiveRecoveryRequest(
        day,
        "rb",
        "RB2611",
        (("rb", "RB2611"),),
        (SessionWindow(start, start + timedelta(hours=2)),),
        start + timedelta(minutes=15, seconds=3),
    )
    bars = tuple(
        replace(_bar(1), bar_end=end, trading_day=day) for end in request.endpoints()
    )
    assert (
        recover_product(store, request, lambda _: bars, clock=lambda: request.cutoff)
        == "RECOVERED"
    )
    assert all(
        bar.trading_day == day for bar in store.bars_after(day, "rb", "1m", None)
    )


def test_lua_atomic_commit_and_concurrent_live_conflict_on_isolated_redis():
    import os
    import redis as redis_module
    from app.market_data.live_recovery import recover_product

    port = os.getenv("GUIYI_TEST_REDIS_PORT")
    if port is None:
        pytest.skip("requires explicitly created disposable Redis container")
    assert int(port) != 6379
    client = redis_module.Redis(host="127.0.0.1", port=int(port), decode_responses=True)
    fake, _, request, bars = _setup()
    store = RedisLiveStore(client)
    # Only this known disposable instance is used; no configured app Redis import.
    for key, value in fake.values.items():
        client.set(key, value)
    for key, values in fake.zsets.items():
        client.delete(key)
        client.zadd(key, values)
    state_key = store._recovery_key(
        request.trading_day, request.symbol, request.contract
    )
    for key in client.scan_iter(match=f"{state_key}*"):
        client.delete(key)
    for frequency in ("5m", "15m", "30m", "60m"):
        client.delete(store._bars_key(request.trading_day, request.symbol, frequency))
    original = store.bars_after(request.trading_day, "rb", "1m", None)

    def concurrent(req):
        store.put_bar(req.trading_day, "rb", "1m", bars[0], contract="RB2505")
        return bars

    with pytest.raises(ValueError, match="SNAPSHOT_DRIFT"):
        recover_product(store, request, concurrent, clock=lambda: request.cutoff)
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None
    assert store.bars_after(request.trading_day, "rb", "15m", None) == ()
    # Recreate the gap only in the isolated fixture, then run the successful script.
    client.zremrangebyscore(
        store._bars_key(request.trading_day, "rb", "1m"),
        int(bars[0].bar_end.timestamp() * 1000),
        int(bars[0].bar_end.timestamp() * 1000),
    )
    retry = replace(request, cutoff=request.cutoff + timedelta(minutes=1))
    # Keep expected endpoints at 15m while exercising persisted 60-second retry.
    retry = replace(
        retry, sessions=(SessionWindow(request.sessions[0].start, bars[-1].bar_end),)
    )
    assert (
        recover_product(store, retry, lambda _: bars, clock=lambda: retry.cutoff)
        == "RECOVERED"
    )
    assert (
        len(store.bars_after(request.trading_day, "rb", "1m", None))
        == len(original) + 1
    )
    assert len(store.bars_after(request.trading_day, "rb", "15m", None)) == 1
    assert store.recovery_state(request.trading_day, "rb", "RB2505").revision == 1
    with pytest.raises(ValueError, match="LIVE_BAR_CONFLICT"):
        store.put_bar(
            request.trading_day,
            "rb",
            "1m",
            replace(bars[0], volume=bars[0].volume + 1),
            contract="RB2505",
        )
    assert store.bars_after(request.trading_day, "rb", "1m", None)[0] == bars[0]


def test_default_off_never_schedules_recovery(monkeypatch):
    from app.market_data.live_market import LiveMarketService
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _phase

    _, store, request, _ = _setup()
    monkeypatch.setattr(
        "app.market_data.live_recovery.LiveRecoveryWorker",
        lambda *a, **k: pytest.fail("OFF instantiated worker"),
    )
    service = LiveMarketService(
        provider_factory=lambda: None,
        dominant_source=FakeDominants({("rb", request.trading_day): "RB2505"}),
        phase_resolver=FakePhases(
            {"rb": _phase("rb", request.trading_day, request.sessions[0])}
        ),
        store=store,
        operational_products=("rb",),
    )
    service._schedule_recovery(request.cutoff, {})
    assert service._recovery_worker is None


@pytest.mark.parametrize(
    "failure", ["wrong_contract", "wrong_day", "ohlcv", "duplicate", "missing"]
)
def test_public_adapter_validates_identity_schema_and_prefix(failure):
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from app.market_data.live_market import _bar_payload
    from app.market_data.live_recovery import recover_product

    _, store, request, bars = _setup()
    rows = []
    for bar in bars:
        row = _bar_payload(bar)
        row.update(
            datetime=row.pop("bar_end"),
            trading_date=row.pop("trading_day"),
            order_book_id=request.contract,
        )
        rows.append(row)
    if failure == "wrong_contract":
        rows[0]["order_book_id"] = "RB2510"
    elif failure == "wrong_day":
        rows[0]["trading_date"] = "2025-01-03"
    elif failure == "ohlcv":
        rows[0]["high"] = "0"
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "missing":
        rows.pop(0)

    class Client:
        def price(self, contract, start, end, frequency):
            assert (
                contract == "RB2505"
                and start == end == request.trading_day
                and frequency == "1m"
            )
            return rows

    with pytest.raises((ValueError, RuntimeError)):
        recover_product(
            store,
            request,
            RQDataLiveRecoveryAdapter(Client()),
            clock=lambda: request.cutoff,
        )
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None


def test_full_1m_missing_derived_is_repaired_without_provider_or_attempt():
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    store.put_bar(request.trading_day, "rb", "1m", bars[0], contract="RB2505")
    assert (
        recover_product(
            store,
            request,
            lambda _: pytest.fail("derived repair called provider"),
            clock=lambda: request.cutoff,
        )
        == "RECOVERED"
    )
    assert len(store.bars_after(request.trading_day, "rb", "15m", None)) == 1
    assert store.recovery_state(request.trading_day, "rb", "RB2505").revision == 1
    assert not any(":attempt:" in key for key in redis.values)
    assert redis.published == []
    assert (
        recover_product(
            store,
            request,
            lambda _: pytest.fail("no gap called provider"),
            clock=lambda: request.cutoff,
        )
        == "NO_GAP"
    )


def test_adapter_allows_legal_endpoint_inside_finalization_delay():
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from app.market_data.live_market import _bar_payload

    _, _, request, bars = _setup()
    request = replace(request, cutoff=bars[-1].bar_end + timedelta(seconds=1))
    rows = []
    for bar in bars:
        row = _bar_payload(bar)
        row.update(
            datetime=row.pop("bar_end"),
            trading_date=row.pop("trading_day"),
            order_book_id=request.contract,
        )
        rows.append(row)

    class Client:
        def price(self, *args):
            return rows

    assert RQDataLiveRecoveryAdapter(Client())(request) == bars[:-1]


def test_worker_logs_bounded_codes_with_identity_without_provider_exception(caplog):
    import logging
    from app.market_data.live_recovery import LiveRecoveryWorker

    _, store, request, _ = _setup()

    def factory():
        def fetch(_):
            raise ValueError("secret provider message")

        return fetch

    worker = LiveRecoveryWorker(store, factory, clock=lambda: request.cutoff)
    with caplog.at_level(logging.INFO, logger="app.market_data.live_recovery"):
        worker._run((request,))
    record = caplog.records[-1]
    assert record.getMessage() == "LIVE_RECOVERY_FAILED"
    assert record.diagnostic_fields == {
        "symbol": "rb",
        "contract": "RB2505",
        "trading_day": "2025-01-02",
    }
    assert "secret provider message" not in caplog.text
    worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("kind", ["denied", "quota"])
def test_provider_initialization_failure_opens_persisted_circuit(monkeypatch, kind):
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from app.market_data.live_recovery import recover_product

    redis, store, request, _ = _setup()

    class InitError(RuntimeError):
        code = "RQDATA_QUOTA_EXCEEDED" if kind == "quota" else ""

    def denied():
        raise InitError("quota exhausted" if kind == "quota" else "permission denied")

    monkeypatch.setattr("app.market_data.rqdata_adapter.RQDataClient", denied)
    with pytest.raises(RuntimeError, match="PROVIDER_(QUOTA_EXHAUSTED|ACCESS_DENIED)"):
        recover_product(
            store, request, RQDataLiveRecoveryAdapter(), clock=lambda: request.cutoff
        )
    assert redis.get("live:recovery:circuit:2025-01-02") == "STOPPED"


def test_recovery_samples_clock_and_commits_only_inside_guard():
    from contextlib import contextmanager
    from app.market_data.live_recovery import recover_product

    _, store, request, bars = _setup()
    entered = []

    @contextmanager
    def guard():
        entered.append(True)
        yield
        entered.pop()

    def clock():
        assert entered == [True]
        return request.cutoff

    assert (
        recover_product(store, request, lambda _: bars, clock=clock, commit_guard=guard)
        == "RECOVERED"
    )
    assert entered == []


def test_busy_commit_guard_aborts_bars_and_barrier():
    from contextlib import contextmanager
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    original = {key: dict(value) for key, value in redis.zsets.items()}

    @contextmanager
    def busy():
        raise ValueError("LIVE_RECOVERY_BUSY")
        yield

    with pytest.raises(ValueError, match="LIVE_RECOVERY_BUSY"):
        recover_product(
            store,
            request,
            lambda _: bars,
            clock=lambda: request.cutoff,
            commit_guard=busy,
        )
    assert redis.zsets == original
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None
