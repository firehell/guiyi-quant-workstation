"""Active-session interleavings using real guards and optional disposable Redis."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from functools import partial
from threading import Event

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import LiveMarketService, RedisLiveStore, RQDataLiveProvider
from app.market_data.live_recovery import LiveRecoveryRequest, recover_product
from app.market_data.live_recovery_guard import recovery_guard
from app.market_data.market_read_service import MarketReadWindow
from tests.data_foundation.test_live_market import (
    FakeDominants, FakeLiveClient, FakePhases, FakeRedis, _bar as _base_bar, _phase,
)


def _bar(minute):
    return replace(_base_bar(1), bar_end=_base_bar(1).bar_end + timedelta(minutes=minute - 1))


@pytest.fixture(params=("memory", "isolated_redis"))
def live_store(request):
    if request.param == "memory":
        return RedisLiveStore(FakeRedis())
    port = os.getenv("GUIYI_TEST_REDIS_PORT")
    if port is None:
        pytest.skip("requires explicitly created disposable Redis container")
    assert 1024 <= int(port) <= 65535 and int(port) != 6379
    from redis import Redis

    # DB 9 is owned exclusively by this test on the explicitly isolated instance.
    client = Redis(host="127.0.0.1", port=int(port), db=9, decode_responses=True)
    client.flushdb()
    request.addfinalizer(client.close)
    return RedisLiveStore(client)


def _fixture(store, tmp_path, *, symbol="rb", minute=15, fetch=None):
    start = _bar(1).bar_end - timedelta(minutes=1)
    day = _bar(1).trading_day
    contract = f"{symbol.upper()}2505"
    window = SessionWindow(start, start + timedelta(minutes=75))
    cutoff = start + timedelta(minutes=minute, seconds=3)
    guard = partial(recovery_guard, root=tmp_path / "guards")
    service = LiveMarketService(
        provider_factory=lambda: RQDataLiveProvider(FakeLiveClient()),
        dominant_source=FakeDominants({(symbol, day): contract}),
        phase_resolver=FakePhases({symbol: _phase(symbol, day, window)}),
        store=store, operational_products=(symbol,), clock=lambda: cutoff,
        recovery_fetch_factory=lambda: fetch or (lambda _: pytest.fail("unexpected provider")),
        recovery_sessions=lambda *_: (window,), recovery_guard_factory=guard,
    )
    store.set_subscriptions(day, {symbol: contract})
    service._trading_day = day
    service._contracts = {symbol: contract}
    request = LiveRecoveryRequest(day, symbol, contract, ((symbol, contract),), (window,), cutoff)
    return service, request, guard


def _seed(service, store, request, minutes, *, derived=False):
    for minute in minutes:
        bar = _bar(minute)
        store.put_bar(request.trading_day, request.symbol, "1m", bar, contract=request.contract)
        if derived:
            service._derive(request.symbol, bar, request.sessions[0], contract=request.contract)


def _attempts(store):
    redis = store._redis
    keys = redis.values if isinstance(redis, FakeRedis) else redis.scan_iter(match="*:attempt:*")
    return [json.loads(redis.get(key))["count"] for key in keys if ":attempt:" in key]


def test_fetch_overlap_with_normal_flush_recovers_old_gap_once(live_store, tmp_path):
    entered, release = Event(), Event()
    calls = []

    def fetch(request):
        calls.append(request)
        entered.set()
        assert release.wait(3)
        return tuple(_bar(m) for m in range(1, 16))

    service, request, guard = _fixture(live_store, tmp_path, fetch=fetch)
    _seed(service, live_store, request, range(2, 15))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(recover_product, live_store, request, fetch,
                             clock=lambda: request.cutoff,
                             commit_guard=lambda: guard(request.symbol))
        try:
            assert entered.wait(3)
            assert service.ingest(request.contract, _bar(15), now=request.cutoff) is None
            assert service.flush_due(request.cutoff) == (_bar(15),)
        finally:
            release.set()
        assert future.result(timeout=3) == "RECOVERED"
    assert len(calls) == 1 and _attempts(live_store) == [1]
    assert live_store.bars_after(request.trading_day, "rb", "1m", None) == tuple(_bar(m) for m in range(1, 16))
    state = live_store.recovery_state(request.trading_day, "rb", request.contract)
    assert state.revision == 1 and state.recovered_through == request.cutoff
    assert recover_product(live_store, request, fetch, clock=lambda: request.cutoff,
                           commit_guard=lambda: guard("rb")) == "NO_GAP"
    assert len(calls) == 1 and _attempts(live_store) == [1]
    service._recovery_worker._executor.shutdown(wait=True)


def test_frontend_fills_all_gaps_during_fetch_does_not_create_watermark(live_store, tmp_path):
    service, request, guard = _fixture(live_store, tmp_path)
    _seed(service, live_store, request, range(1, 15), derived=True)

    def fetch(_):
        assert service.ingest(request.contract, _bar(15), now=request.cutoff) is None
        assert service.flush_due(request.cutoff) == (_bar(15),)
        return tuple(_bar(m) for m in range(1, 16))

    try:
        assert recover_product(live_store, request, fetch, clock=lambda: request.cutoff,
                               commit_guard=lambda: guard("rb")) == "NO_GAP"
        assert live_store.recovery_state(request.trading_day, "rb", request.contract) is None
        assert _attempts(live_store) == [1]
    finally:
        service._recovery_worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("symbol,frequency,minute", (("jm", "5m", 5), ("jm", "15m", 15), ("rb", "60m", 60), ("rb", "15m", 15)))
def test_normal_derived_transition_cannot_advance_recovery_watermark(
    live_store, tmp_path, monkeypatch, symbol, frequency, minute,
):
    service, request, guard = _fixture(live_store, tmp_path, symbol=symbol, minute=minute)
    _seed(service, live_store, request, range(1, minute), derived=True)
    original_put = live_store.put_bar
    original_publish = live_store.publish_bar
    publications = []
    probes = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        def put_then_probe(day, product, freq, bar, **kwargs):
            result = original_put(day, product, freq, bar, **kwargs)
            if freq == "1m" and bar.bar_end == _bar(minute).bar_end:
                future = pool.submit(recover_product, live_store, request,
                                     lambda _: pytest.fail("source 1m complete"),
                                     clock=lambda: request.cutoff,
                                     commit_guard=lambda: guard(symbol))
                try:
                    probes.append(future.result(timeout=3))
                except RuntimeError as exc:
                    assert str(exc) == "LIVE_RECOVERY_BUSY"
                    probes.append("BUSY")
            return result

        def publish(product, freq, bar, **kwargs):
            result = original_publish(product, freq, bar, **kwargs)
            publications.append((product, freq, bar.bar_end))
            return result

        monkeypatch.setattr(live_store, "put_bar", put_then_probe)
        monkeypatch.setattr(live_store, "publish_bar", publish)
        try:
            service.ingest(request.contract, _bar(minute), now=request.cutoff)
            assert service.flush_due(request.cutoff) == (_bar(minute),)
            assert probes == ["BUSY"]
            assert publications.count((symbol, frequency, _bar(minute).bar_end)) == 1
            state = live_store.recovery_state(request.trading_day, symbol, request.contract)
            assert state is None
            assert MarketReadWindow(symbol, "actual_dominant", frequency, request.trading_day,
                                    request.contract, _bar(minute).bar_end, (), (), state).notification_eligible
            assert recover_product(live_store, request, lambda _: pytest.fail("complete input"),
                                   clock=lambda: request.cutoff,
                                   commit_guard=lambda: guard(symbol)) == "NO_GAP"
            assert _attempts(live_store) == []
        finally:
            service._recovery_worker._executor.shutdown(wait=True)


def test_poll_finishes_pending_natural_bar_before_scheduling_recovery(live_store, tmp_path, monkeypatch):
    calls = []
    service, request, _ = _fixture(live_store, tmp_path, fetch=lambda req: calls.append(req) or tuple(_bar(m) for m in range(1, 16)))
    _seed(service, live_store, request, range(1, 15), derived=True)
    worker = service._recovery_worker
    # Select the earliest legal worker start; correctness cannot rely on it losing a race.
    monkeypatch.setattr(worker, "schedule", lambda requests, now: worker._run(requests))
    try:
        service.ingest(request.contract, _bar(15), now=request.cutoff)
        assert service.poll(request.cutoff) is None
        assert worker.outcomes == (("rb", "NO_GAP"),)
        assert calls == [] and _attempts(live_store) == []
        assert live_store.recovery_state(request.trading_day, "rb", request.contract) is None
    finally:
        worker._executor.shutdown(wait=True)


def test_guard_busy_keeps_pending_and_does_not_block_other_product(live_store, tmp_path):
    service, request, guard = _fixture(live_store, tmp_path)
    service._contracts["jm"] = "JM2505"
    live_store.set_subscriptions(request.trading_day, dict(service._contracts))
    service._pending[("rb", _bar(15).bar_end)] = (_bar(15), request.sessions[0], "RB2505")
    service._pending[("jm", _bar(15).bar_end)] = (_bar(15), request.sessions[0], "JM2505")
    try:
        with guard("rb"):
            assert service.flush_due(request.cutoff) == (_bar(15),)
            assert ("rb", _bar(15).bar_end) in service._pending
            assert ("jm", _bar(15).bar_end) not in service._pending
            assert not service._last_flush_failed
            assert live_store.bars_after(request.trading_day, "rb", "1m", None) == ()
        assert service.flush_due(request.cutoff) == (_bar(15),)
        assert service._pending == {}
    finally:
        service._recovery_worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("mutation", ("removed", "rewritten", "subscription", "state"))
def test_recheck_rejects_changed_original_facts(live_store, tmp_path, mutation):
    service, request, guard = _fixture(live_store, tmp_path)
    _seed(service, live_store, request, range(2, 15))
    redis = live_store._redis

    def fetch(_):
        if mutation in ("removed", "rewritten"):
            key = live_store._bars_key(request.trading_day, "rb", "1m")
            original = next(raw for raw in redis.zrange(key, 0, -1)
                            if json.loads(raw)["bar_end"] == _bar(2).bar_end.isoformat())
            if isinstance(redis, FakeRedis):
                redis.zsets[key].pop(original)
            else:
                redis.zrem(key, original)
            if mutation == "rewritten":
                live_store.put_bar(request.trading_day, "rb", "1m", replace(_bar(2), volume=999), contract=request.contract)
        elif mutation == "subscription":
            live_store.set_subscriptions(request.trading_day, {"rb": "RB2510"})
        else:
            redis.set(live_store._recovery_key(request.trading_day, "rb", request.contract),
                      json.dumps({"revision": 1, "recovered_through": request.cutoff.isoformat()}))
        return tuple(_bar(m) for m in range(1, 16))

    try:
        with pytest.raises(ValueError):
            recover_product(live_store, request, fetch, clock=lambda: request.cutoff,
                            commit_guard=lambda: guard("rb"))
        assert _attempts(live_store) == [1]
        assert live_store.bars_after(request.trading_day, "rb", "15m", None) == ()
    finally:
        service._recovery_worker._executor.shutdown(wait=True)


def test_busy_pending_bar_is_not_recovered_if_lock_releases_after_final_flush(live_store, tmp_path, monkeypatch):
    from contextlib import ExitStack

    calls = []
    service, request, guard = _fixture(live_store, tmp_path, fetch=lambda req: calls.append(req) or tuple(_bar(m) for m in range(1, 16)))
    _seed(service, live_store, request, range(1, 15), derived=True)
    worker = service._recovery_worker
    monkeypatch.setattr(worker, "schedule", lambda requests, now: worker._run(requests))
    original_flush = service.flush_due
    flush_count = 0
    with ExitStack() as held:
        held.enter_context(guard("rb"))

        def flush_then_release(*args, **kwargs):
            nonlocal flush_count
            result = original_flush(*args, **kwargs)
            flush_count += 1
            if flush_count == 2:
                held.close()
            return result

        monkeypatch.setattr(service, "flush_due", flush_then_release)
        try:
            service.ingest(request.contract, _bar(15), now=request.cutoff)
            assert service.poll(request.cutoff) is None
            assert calls == []
            assert live_store.recovery_state(request.trading_day, "rb", request.contract) is None
            assert ("rb", _bar(15).bar_end) in service._pending
            assert service.poll(request.cutoff + timedelta(seconds=1)) is None
            assert service._pending == {}
            assert live_store.recovery_state(request.trading_day, "rb", request.contract) is None
        finally:
            worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("arrival", ("pending", "provider"))
@pytest.mark.parametrize("error", (RuntimeError, OSError))
def test_guard_failure_is_unavailable_without_discarding_provider(
    live_store, tmp_path, monkeypatch, arrival, error,
):
    from contextlib import contextmanager

    service, request, _ = _fixture(live_store, tmp_path)
    service.reconcile(request.cutoff)
    provider = service._provider

    @contextmanager
    def unsafe_guard(_):
        raise error("LIVE_RECOVERY_GUARD_UNSAFE")
        yield

    monkeypatch.setattr(service, "_recovery_guard_factory", unsafe_guard)
    if arrival == "pending":
        service.ingest(request.contract, _bar(15), now=request.cutoff)
    else:
        monkeypatch.setattr(provider, "poll", lambda: ((request.contract, _bar(15)),))
    try:
        assert service.poll(request.cutoff) == "LIVE_REDIS_UNAVAILABLE"
        assert service._last_flush_failed and not service._available
        assert service._provider is provider and service.next_provider_retry_at is None
        assert ("rb", _bar(15).bar_end) in service._pending
        assert live_store.bars_after(request.trading_day, "rb", "1m", None) == ()
        assert _attempts(live_store) == []
    finally:
        service._recovery_worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("path", ("normal", "no_channels", "provider_failure"))
@pytest.mark.parametrize("failure", ("authority", "worker"))
def test_recovery_schedule_failure_stays_in_unavailable_boundary(
    live_store, tmp_path, monkeypatch, path, failure,
):
    service, request, _ = _fixture(live_store, tmp_path)
    service.reconcile(request.cutoff)
    provider = service._provider

    def fail(*args):
        raise RuntimeError("LIVE_RECOVERY_AUTHORITY_UNAVAILABLE")

    if failure == "authority":
        monkeypatch.setattr(service, "_recovery_sessions", fail)
    else:
        monkeypatch.setattr(service._recovery_worker, "schedule", fail)
    if path == "no_channels":
        service._channels.clear()
        monkeypatch.setattr(service, "reconcile", lambda now: None)
    elif path == "provider_failure":
        monkeypatch.setattr(provider, "poll", fail)
    try:
        assert service.poll(request.cutoff) == "LIVE_REDIS_UNAVAILABLE"
        assert not service._available
        if path != "provider_failure":
            assert service._provider is provider and service.next_provider_retry_at is None
        assert _attempts(live_store) == []
    finally:
        service._recovery_worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("arrival", ("pending", "provider", "cooldown", "break"))
@pytest.mark.parametrize("closed_before_error", (False, True))
def test_real_guard_release_failure_preserves_completed_bars_without_provider_retry(
    live_store, tmp_path, monkeypatch, arrival, closed_before_error,
):
    from pathlib import Path
    from app.market_data.market_phase import MarketPhase

    service, request, guard = _fixture(live_store, tmp_path)
    service.reconcile(request.cutoff)
    _seed(service, live_store, request, range(1, 15), derived=True)
    provider = service._provider
    publications = []
    original_publish = live_store.publish_bar

    def publish(product, frequency, bar, **kwargs):
        original_publish(product, frequency, bar, **kwargs)
        publications.append((frequency, bar.bar_end))

    monkeypatch.setattr(live_store, "publish_bar", publish)
    if arrival == "provider":
        monkeypatch.setattr(provider, "poll", lambda: ((request.contract, _bar(15)),))
    else:
        service.ingest(request.contract, _bar(15), now=request.cutoff)
    if arrival == "cooldown":
        service.next_provider_retry_at = request.cutoff + timedelta(seconds=10)
    elif arrival == "break":
        monkeypatch.setattr(service._phase_resolver, "resolve", lambda *_:
                            _phase("rb", request.trading_day, None, MarketPhase.BREAK))
    expected_retry = service.next_provider_retry_at
    original_open, original_close = os.open, os.close
    owned_fd = None
    fd_closed = False

    def capture_open(path, *args, **kwargs):
        nonlocal owned_fd
        fd = original_open(path, *args, **kwargs)
        if Path(path) == tmp_path / "guards" / "rb.lock":
            owned_fd = fd
        return fd

    def fail_guard_close(fd):
        nonlocal fd_closed
        if fd == owned_fd:
            if closed_before_error:
                original_close(fd)
                fd_closed = True
            raise OSError("injected lock release failure")
        return original_close(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", capture_open)
            patch.setattr(os, "close", fail_guard_close)
            assert service.poll(request.cutoff) == "LIVE_REDIS_UNAVAILABLE"
            assert service._last_flush_failed and not service._available
            assert service._provider is provider
            assert service.next_provider_retry_at == expected_retry
            assert service._pending == {}
            assert publications == [("1m", _bar(15).bar_end), ("5m", _bar(15).bar_end),
                                    ("15m", _bar(15).bar_end)]
            assert len(live_store.bars_after(request.trading_day, "rb", "1m", None)) == 15
            assert live_store.recovery_state(request.trading_day, "rb", request.contract) is None
            assert _attempts(live_store) == []
            assert json.loads(live_store._redis.get("live:heartbeat"))["available"] is False
        # Do not let fixture cleanup conceal a lock left held by a failed close.
        with guard("rb"):
            pass
        monkeypatch.setattr(service._phase_resolver, "resolve", lambda *_:
                            _phase("rb", request.trading_day, request.sessions[0]))
        # Once the OS boundary is healthy, duplicate input must not republish.
        assert service.ingest(request.contract, _bar(15), now=request.cutoff) == "LIVE_BAR_FINALIZED"
        assert service.flush_due(request.cutoff) == ()
        assert len(publications) == 3
        with guard("rb"):
            pass
        assert service.ingest(request.contract, _bar(16), now=request.cutoff + timedelta(minutes=1)) is None
        assert service.flush_due(request.cutoff + timedelta(minutes=1)) == (_bar(16),)
        assert not service._last_flush_failed and service._available
        assert publications[-1] == ("1m", _bar(16).bar_end)
        assert len(publications) == 4
    finally:
        if owned_fd is not None and not fd_closed:
            original_close(owned_fd)
        service._recovery_worker._executor.shutdown(wait=True)
