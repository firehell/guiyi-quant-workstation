"""Deterministic queue latency regressions; no provider or production Redis."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore
from app.market_data.live_recovery import (
    LiveRecoveryRequest,
    LiveRecoveryWorker,
    recover_product,
)
from app.market_data.operational_universe import load_operational_products
from tests.data_foundation.test_live_market import FakeRedis
from tests.data_foundation.test_live_recovery import _setup


@pytest.mark.parametrize("clock_kind", ["stale", "future_cutoff", "naive"])
def test_invalid_queued_clock_never_claims_budget_or_initializes_provider(clock_kind):
    redis, store, request, _ = _setup()
    now = {
        "stale": request.cutoff + timedelta(seconds=60, microseconds=1),
        "future_cutoff": request.cutoff - timedelta(microseconds=1),
        "naive": request.cutoff.astimezone().replace(tzinfo=None),
    }[clock_kind]
    before = deepcopy((redis.values, redis.zsets, redis.ttls))
    factory_calls = []
    fetch_calls = []

    def factory():
        factory_calls.append(True)

        def fetch(req):
            fetch_calls.append(req)
            raise ValueError("PROVIDER_ACCESS_DENIED")

        return fetch

    worker = LiveRecoveryWorker(store, factory, clock=lambda: now)
    try:
        worker._run((request,))
        assert worker.outcomes == ((request.symbol, "LIVE_RECOVERY_CLOCK_INVALID"),)
        assert factory_calls == []
        assert fetch_calls == []
        assert (redis.values, redis.zsets, redis.ttls) == before
        assert redis.published == []
    finally:
        worker._executor.shutdown(wait=True)


def test_exact_60_second_clock_boundary_remains_eligible():
    redis, store, request, bars = _setup()
    now = request.cutoff + timedelta(seconds=60)
    assert (
        recover_product(store, request, lambda _: bars, clock=lambda: now)
        == "RECOVERED"
    )
    state = store.recovery_state(request.trading_day, request.symbol, request.contract)
    assert state.recovered_through == now
    assert redis.published == []


@pytest.mark.parametrize("commit_clock_kind", ["stale", "future_cutoff", "naive"])
def test_actual_provider_attempt_is_counted_when_commit_clock_becomes_invalid(
    commit_clock_kind,
):
    redis, store, request, bars = _setup()
    now = request.cutoff
    before_bars = deepcopy(redis.zsets)
    calls = []

    def fetch(req):
        nonlocal now
        calls.append(req)
        now = {
            "stale": request.cutoff + timedelta(seconds=61),
            "future_cutoff": request.cutoff - timedelta(seconds=1),
            "naive": request.cutoff.astimezone().replace(tzinfo=None),
        }[commit_clock_kind]
        return bars

    with pytest.raises(ValueError, match="^LIVE_RECOVERY_CLOCK_INVALID$"):
        recover_product(store, request, fetch, clock=lambda: now)
    assert calls == [request]
    budgets = [
        json.loads(value) for key, value in redis.values.items() if ":attempt:" in key
    ]
    assert [budget["count"] for budget in budgets] == [1]
    assert redis.zsets == before_bars
    assert (
        store.recovery_state(request.trading_day, request.symbol, request.contract)
        is None
    )
    assert redis.published == []


def test_all_60_slow_queue_converges_45_gaps_without_spending_stale_request_budget():
    _, _, base, bars = _setup()
    products = load_operational_products()
    assert len(products) == 60
    redis = FakeRedis()
    store = RedisLiveStore(redis)
    snapshot = {symbol: f"{symbol.upper()}2505" for symbol in products}
    store.set_subscriptions(base.trading_day, snapshot)
    # One fully completed 15-minute session keeps the fixture small and freezes
    # the missing historical prefix while later foreground rounds get fresh cutoffs.
    session = SessionWindow(base.sessions[0].start, bars[-1].bar_end)
    requests = tuple(
        LiveRecoveryRequest(
            base.trading_day,
            symbol,
            contract,
            tuple(snapshot.items()),
            (session,),
            base.cutoff,
        )
        for symbol, contract in snapshot.items()
    )
    for index, request in enumerate(requests):
        for bar in bars if index < 15 else bars[1:]:
            store.put_bar(
                base.trading_day, request.symbol, "1m", bar, contract=request.contract
            )
        if index < 15:
            assert (
                recover_product(
                    store,
                    request,
                    lambda _: pytest.fail("complete prefix called provider"),
                    clock=lambda: base.cutoff,
                )
                == "RECOVERED"
            )

    now = base.cutoff
    calls = []
    outcomes = []

    def fetch(request):
        nonlocal now
        calls.append(request)
        now += timedelta(seconds=7)
        return bars

    worker = LiveRecoveryWorker(store, lambda: fetch, clock=lambda: now)
    try:
        # Each round commits eight slow responses, rejects the ninth at commit,
        # and leaves queued stale products' attempt budgets untouched.
        for _ in range(6):
            cutoff = now
            fresh = tuple(replace(request, cutoff=cutoff) for request in requests)
            worker.schedule(fresh, cutoff)
            worker._future.result(timeout=5)
            outcomes.extend(worker.outcomes)
            now = max(now, cutoff + timedelta(seconds=60))
        assert sum(result == "RECOVERED" for _, result in outcomes) == 45
        assert all(result != "RETRY_BUDGET_BLOCKED" for _, result in outcomes)
        assert len(calls) == 50  # 45 commits plus five genuinely slow attempts.
        budgets = [
            json.loads(value)
            for key, value in redis.values.items()
            if ":attempt:" in key
        ]
        assert len(budgets) == 45
        assert sum(budget["count"] for budget in budgets) == 50
        assert max(budget["count"] for budget in budgets) == 2
        for request in requests:
            assert (
                store.bars_after(base.trading_day, request.symbol, "1m", None) == bars
            )
            assert (
                store.recovery_state(base.trading_day, request.symbol, request.contract)
                is not None
            )
        assert redis.published == []
    finally:
        worker._executor.shutdown(wait=True)
