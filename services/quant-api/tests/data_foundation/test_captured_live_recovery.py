"""Offline source recovery: exact frozen input, one commit, no provider surface."""

import copy
import json
from contextlib import nullcontext, contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.live_market import RedisLiveStore, _bar_payload, _compact_json
from app.market_data.live_recovery import LiveRecoveryRequest, _FREQUENCIES
from tests.data_foundation.test_live_market import FakeRedis, _bar


def captured_setup(redis=None):
    redis = redis or FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2026, 9, 8)
    sessions = tuple(
        SessionWindow(
            datetime(2026, 9, 8, h, m, tzinfo=UTC),
            datetime(2026, 9, 8, eh, em, tzinfo=UTC),
        )
        for h, m, eh, em in [(1, 0, 2, 15), (2, 30, 3, 30), (5, 30, 7, 0)]
    )
    request = LiveRecoveryRequest(
        day,
        "rs",
        "RS2609",
        (("rs", "RS2609"),),
        sessions,
        datetime(2026, 9, 8, 10, 30, tzinfo=UTC),
    )
    bars = tuple(
        replace(_bar(1), bar_end=end, trading_day=day) for end in request.endpoints()
    )
    store.set_subscriptions(day, dict(request.snapshot))
    for frequency in _FREQUENCIES:
        sequence = (
            bars
            if frequency == "1m"
            else aggregate_from_1m(bars, target_frequency=frequency, sessions=sessions)
        )
        for bar in sequence[1:]:
            store.put_bar(day, "rs", frequency, bar, contract="RS2609")
    budget = (
        store._recovery_key(day, "rs", "RS2609")
        + ":attempt:"
        + sessions[-1].start.isoformat()
    )
    redis.set(budget, '{"count":3,"last_at":1788845523423}', ex=250000)
    rows = []
    for bar in bars:
        row = _bar_payload(bar)
        row.update(
            datetime=row.pop("bar_end"),
            trading_date=row.pop("trading_day"),
            order_book_id="RS2609",
        )
        rows.append(row)
    return redis, store, request, json.dumps(rows).encode(), budget


def test_captured_full_apply_and_readonly_noop_at_exhausted_budget(monkeypatch):
    from app.market_data.captured_live_recovery import (
        plan_captured_recovery,
        apply_captured_recovery,
    )

    monkeypatch.setattr(
        "app.market_data.rqdata_adapter.RQDataClient",
        lambda: pytest.fail("provider constructed"),
    )
    redis, store, request, source, budget = captured_setup()
    original_budget = redis.get(budget)
    plan = plan_captured_recovery(
        store,
        request,
        source,
        runtime_identity="test-runtime",
        clock=lambda: request.cutoff,
    )
    assert len(plan["targets"]) == 5
    assert store.recovery_state(request.trading_day, "rs", "RS2609") is None
    result = apply_captured_recovery(
        store,
        request,
        source,
        plan,
        runtime_identity="test-runtime",
        clock=lambda: request.cutoff,
        commit_guard=nullcontext,
    )
    assert result["status"] == "RECOVERED"
    assert [
        len(store.bars_after(request.trading_day, "rs", f, None)) for f in _FREQUENCIES
    ] == [225, 45, 15, 8, 5]
    assert redis.get(budget) == original_budget
    assert redis.published == []
    state = store.recovery_state(request.trading_day, "rs", "RS2609")
    assert state.revision == 1 and state.recovered_through == request.cutoff
    before = copy.deepcopy((redis.values, redis.zsets, redis.ttls))
    result = apply_captured_recovery(
        store,
        request,
        source,
        plan,
        runtime_identity="test-runtime",
        clock=lambda: request.cutoff,
        commit_guard=lambda: pytest.fail("NOOP locked"),
    )
    assert result["status"] == "NOOP"
    assert (redis.values, redis.zsets, redis.ttls) == before


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "duplicate",
        "extra",
        "contract",
        "day",
        "ohlcv",
        "nan",
        "bytes",
        "circuit",
        "ttl",
        "missing_key",
        "score",
        "runtime",
        "source_hash",
        "plan_hash",
        "crossday",
        "future",
        "stale",
        "partial",
    ],
)
def test_captured_rejects_invalid_source_or_frozen_facts_without_mutation(failure):
    from app.market_data.captured_live_recovery import (
        plan_captured_recovery,
        apply_captured_recovery,
    )

    redis, store, request, source, budget = captured_setup()
    plan = plan_captured_recovery(
        store,
        request,
        source,
        runtime_identity="test-runtime",
        clock=lambda: request.cutoff,
    )
    rows = json.loads(source)
    runtime = "test-runtime"

    def clock():
        return request.cutoff

    if failure == "missing":
        rows.pop(0)
    elif failure == "duplicate":
        rows[0] = rows[1]
    elif failure == "extra":
        rows.append(rows[-1])
    elif failure == "contract":
        rows[0]["order_book_id"] = "RS2611"
    elif failure == "day":
        rows[0]["trading_date"] = "2026-09-07"
    elif failure == "ohlcv":
        rows[0]["high"] = "0"
    elif failure == "nan":
        rows[0]["volume"] = "NaN"
    elif failure == "bytes":
        source = b" " * (512 * 1024 + 1)
    elif failure == "circuit":
        redis.set("live:recovery:circuit:2026-09-08", "STOPPED", ex=259200)
    elif failure == "ttl":
        redis.ttls[store._bars_key(request.trading_day, "rs", "15m")] = -1
    elif failure == "missing_key":
        redis.zsets.pop(store._bars_key(request.trading_day, "rs", "15m"))
    elif failure == "score":
        values = redis.zsets[store._bars_key(request.trading_day, "rs", "15m")]
        values[next(iter(values))] += 1
    elif failure == "runtime":
        runtime = "different-runtime"
    elif failure == "source_hash":
        source += b" "
    elif failure == "plan_hash":
        plan["source_sha256"] = "0" * 64
    elif failure == "crossday":

        def clock():
            return request.cutoff + timedelta(days=1)
    elif failure == "future":

        def clock():
            return request.cutoff - timedelta(seconds=1)
    elif failure == "stale":

        def clock():
            return request.cutoff + timedelta(seconds=61)
    elif failure == "partial":
        target = plan["targets"][0]
        redis.zadd(
            store._bars_key(request.trading_day, "rs", "1m"),
            {target["payload"]: target["score"]},
        )
    if failure in ("missing", "duplicate", "extra", "contract", "day", "ohlcv", "nan"):
        source = json.dumps(rows).encode()
    before = copy.deepcopy((redis.values, redis.zsets, redis.ttls))
    with pytest.raises((ValueError, RuntimeError)):
        apply_captured_recovery(
            store,
            request,
            source,
            plan,
            runtime_identity=runtime,
            clock=clock,
            commit_guard=nullcontext,
        )
    assert (redis.values, redis.zsets, redis.ttls) == before


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "duplicate",
        "future",
        "ohlcv",
        "optional_nan",
        "extra",
        "bytecap",
        "rowtype",
        "bad_json",
        "extra_live",
        "wrong_type",
        "empty_budget",
        "lock",
        "clock_in_lock",
    ],
)
def test_plan_and_lock_validation_fail_closed(failure):
    from app.market_data.captured_live_recovery import (
        plan_captured_recovery,
        apply_captured_recovery,
    )

    redis, store, request, source, budget = captured_setup()
    rows = json.loads(source)
    if failure == "missing":
        rows.pop(0)
    elif failure == "duplicate":
        rows[0] = rows[1]
    elif failure == "future":
        rows[0]["datetime"] = (request.cutoff + timedelta(minutes=1)).isoformat()
    elif failure == "ohlcv":
        rows[0]["low"] = "9999999"
    elif failure == "optional_nan":
        rows[0]["open_interest"] = float("nan")
    elif failure == "extra":
        rows.append(rows[0])
    elif failure == "rowtype":
        rows[0] = []
    elif failure == "extra_live":
        key = store._bars_key(request.trading_day, "rs", "1m")
        value = json.loads(next(iter(redis.zsets[key])))
        value["bar_end"] = (request.cutoff + timedelta(minutes=1)).isoformat()
        redis.zadd(
            key,
            {
                _compact_json(value): int(
                    (request.cutoff + timedelta(minutes=1)).timestamp() * 1000
                )
            },
        )
    elif failure == "wrong_type":
        redis.zsets[budget] = {"bad": 1}
    elif failure == "empty_budget":
        redis.set(budget, "{}", ex=259200)
    source = json.dumps(rows).encode()
    if failure == "bytecap":
        source = b" " * (512 * 1024 + 1)
    elif failure == "bad_json":
        source = b"{"
    before = copy.deepcopy((redis.values, redis.zsets, redis.ttls))
    if failure in ("lock", "clock_in_lock"):
        plan = plan_captured_recovery(
            store,
            request,
            source,
            runtime_identity="test",
            clock=lambda: request.cutoff,
        )

        @contextmanager
        def guard():
            if failure == "lock":
                raise ValueError("LOCK_FAILURE")
            yield

        times = iter([request.cutoff, request.cutoff + timedelta(seconds=61)])
        with pytest.raises(ValueError):
            apply_captured_recovery(
                store,
                request,
                source,
                plan,
                runtime_identity="test",
                clock=lambda: next(times),
                commit_guard=guard,
            )
    else:
        with pytest.raises((ValueError, RuntimeError)):
            plan_captured_recovery(
                store,
                request,
                source,
                runtime_identity="test",
                clock=lambda: request.cutoff,
            )
    assert (redis.values, redis.zsets, redis.ttls) == before


@pytest.fixture
def isolated_captured_redis():
    import os
    import redis as redis_module

    port = os.getenv("GUIYI_TEST_REDIS_PORT")
    if port is None:
        pytest.skip("requires explicitly created disposable Redis container")
    assert int(port) != 6379
    # DB 14 is exclusively owned by this fixture on the disposable test instance.
    client = redis_module.Redis(
        host="127.0.0.1", port=int(port), db=14, decode_responses=True
    )
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


@pytest.mark.parametrize(
    "drift",
    [
        "none",
        "budget",
        "expired_budget",
        "circuit",
        "subscription",
        "state",
        "sequence",
        "score",
        "type",
        "ttl",
        "missing",
    ],
)
def test_isolated_lua_all_guards_precede_any_write(isolated_captured_redis, drift):
    from app.market_data.captured_live_recovery import (
        plan_captured_recovery,
        apply_captured_recovery,
        _keys,
    )

    client, store, request, source, budget = captured_setup(isolated_captured_redis)
    keys = _keys(store, request)
    plan = plan_captured_recovery(
        store, request, source, runtime_identity="test", clock=lambda: request.cutoff
    )
    baseline_after_drift = []

    @contextmanager
    def guard():
        if drift == "budget":
            client.set(budget, '{"count":2,"last_at":1788845523423}', ex=250000)
        elif drift == "expired_budget":
            client.delete(budget)
        elif drift == "circuit":
            client.set(keys[-1], "STOPPED", ex=250000)
        elif drift == "subscription":
            client.set(keys[0], '{"rs":"RS2611"}', ex=250000)
        elif drift == "state":
            client.set(keys[1], '{"revision":1}', ex=250000)
        elif drift == "sequence":
            client.zadd(
                keys[2], {plan["targets"][0]["payload"]: plan["targets"][0]["score"]}
            )
        elif drift == "score":
            value, score = client.zrange(keys[6], 0, 0, withscores=True)[0]
            client.zadd(keys[6], {value: score + 1})
        elif drift == "type":
            client.delete(keys[6])
            client.set(keys[6], "wrong type", ex=250000)
        elif drift == "ttl":
            client.persist(keys[6])
        elif drift == "missing":
            client.delete(keys[6])
        baseline_after_drift.extend(client.dump(key) for key in keys)
        yield

    if drift == "none":
        result = apply_captured_recovery(
            store,
            request,
            source,
            plan,
            runtime_identity="test",
            clock=lambda: request.cutoff,
            commit_guard=guard,
        )
        assert result["status"] == "RECOVERED"
        assert [client.zcard(key) for key in keys[2:7]] == [225, 45, 15, 8, 5]
        assert client.get(budget) == plan["baseline"]["values"][-2]
        assert all(0 < client.ttl(key) <= 259200 for key in keys[1:7])
        dumps = [client.dump(key) for key in keys]
        ttls = [client.pttl(key) for key in keys]
        result = apply_captured_recovery(
            store,
            request,
            source,
            json.loads(json.dumps(plan, sort_keys=True)),
            runtime_identity="test",
            clock=lambda: request.cutoff,
            commit_guard=lambda: pytest.fail("NOOP must not lock"),
        )
        assert result["status"] == "NOOP"
        assert [client.dump(key) for key in keys] == dumps
        assert all(client.pttl(key) <= ttl for key, ttl in zip(keys, ttls) if ttl > 0)
    else:
        with pytest.raises(ValueError, match="SNAPSHOT_DRIFT"):
            apply_captured_recovery(
                store,
                request,
                source,
                plan,
                runtime_identity="test",
                clock=lambda: request.cutoff,
                commit_guard=guard,
            )
        assert [client.dump(key) for key in keys] == baseline_after_drift


def test_dry_run_only_reads_and_unknown_commit_never_retries():
    from app.market_data.captured_live_recovery import (
        plan_captured_recovery,
        apply_captured_recovery,
    )

    redis, store, request, source, _ = captured_setup()

    class Boundary:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def call(*args, **kwargs):
                self.calls.append(name)
                if name == "eval":
                    redis.eval(*args, **kwargs)
                    raise ConnectionError("unknown committed outcome")
                return getattr(redis, name)(*args, **kwargs)

            return call

    boundary = Boundary()
    store = RedisLiveStore(boundary)
    plan = plan_captured_recovery(
        store, request, source, runtime_identity="test", clock=lambda: request.cutoff
    )
    assert set(boundary.calls) == {"get", "zrange", "ttl", "type"}
    with pytest.raises(ConnectionError):
        apply_captured_recovery(
            store,
            request,
            source,
            plan,
            runtime_identity="test",
            clock=lambda: request.cutoff,
            commit_guard=nullcontext,
        )
    assert boundary.calls.count("eval") == 1
    assert redis.published == []


@pytest.mark.parametrize(
    "failure",
    [
        "unproven_full",
        "wrong_proof",
        "derived_extra",
        "duplicate_json_key",
        "submicrosecond",
        "naive_plan_time",
        "future_plan_time",
    ],
)
def test_exact_provenance_is_required(failure):
    from app.market_data.captured_live_recovery import (
        plan_captured_recovery,
        apply_captured_recovery,
        _digest,
    )

    redis, store, request, source, _ = captured_setup()
    plan = plan_captured_recovery(
        store, request, source, runtime_identity="test", clock=lambda: request.cutoff
    )
    if failure in ("unproven_full", "wrong_proof"):
        for target in plan["targets"]:
            redis.zadd(
                store._bars_key(request.trading_day, "rs", target["frequency"]),
                {target["payload"]: target["score"]},
            )
        if failure == "wrong_proof":
            redis.set(
                store._recovery_key(request.trading_day, "rs", "RS2609"),
                _compact_json(
                    {"revision": 1, "recovered_through": request.cutoff.isoformat()}
                ),
                ex=259200,
            )
    elif failure == "derived_extra":
        value = json.loads(plan["targets"][1]["payload"])
        value["bar_end"] = "2026-09-08T01:06:00+00:00"
        redis.zadd(
            store._bars_key(request.trading_day, "rs", "5m"),
            {
                _compact_json(value): int(
                    datetime(2026, 9, 8, 1, 6, tzinfo=UTC).timestamp() * 1000
                )
            },
        )
    elif failure == "duplicate_json_key":
        source = source.replace(
            b'"order_book_id": "RS2609"',
            b'"order_book_id": "RS2609", "order_book_id": "RS2609"',
            1,
        )
    elif failure == "submicrosecond":
        source = source.replace(
            b"2026-09-08T01:01:00+00:00", b"2026-09-08T01:01:00.000000001+00:00", 1
        )
    elif failure in ("naive_plan_time", "future_plan_time"):
        plan["planned_at"] = (
            "2026-09-08T10:30:00"
            if failure == "naive_plan_time"
            else "2026-09-09T10:30:00+00:00"
        )
        plan["plan_sha256"] = _digest(
            {k: v for k, v in plan.items() if k != "plan_sha256"}
        )
    before = copy.deepcopy((redis.values, redis.zsets, redis.ttls))
    with pytest.raises((ValueError, RuntimeError)):
        if failure in ("derived_extra", "duplicate_json_key", "submicrosecond"):
            plan_captured_recovery(
                store,
                request,
                source,
                runtime_identity="test",
                clock=lambda: request.cutoff,
            )
        else:
            apply_captured_recovery(
                store,
                request,
                source,
                plan,
                runtime_identity="test",
                clock=lambda: request.cutoff,
                commit_guard=lambda: pytest.fail("invalid proof must not lock"),
            )
    assert (redis.values, redis.zsets, redis.ttls) == before


@pytest.mark.parametrize(
    ("primary", "alias"),
    [
        ("turnover", "total_turnover"),
        ("turnover", "amount"),
        ("open_interest", "open_oi"),
        ("open_interest", "close_oi"),
    ],
)
@pytest.mark.parametrize("invalid", ["negative", "different_positive", "nan"])
def test_plan_rejects_invalid_or_conflicting_numeric_aliases(primary, alias, invalid):
    from app.market_data.captured_live_recovery import plan_captured_recovery

    redis, store, request, source, _ = captured_setup()
    rows = json.loads(source)
    rows[0][alias] = {
        "negative": "-1",
        "different_positive": str(Decimal(rows[0][primary]) + 1),
        "nan": "NaN",
    }[invalid]
    before = copy.deepcopy((redis.values, redis.zsets, redis.ttls))
    with pytest.raises((ValueError, RuntimeError)):
        plan_captured_recovery(
            store,
            request,
            json.dumps(rows).encode(),
            runtime_identity="test",
            clock=lambda: request.cutoff,
        )
    assert (redis.values, redis.zsets, redis.ttls) == before


@pytest.mark.parametrize(
    "mode", ["equal_aliases", "optional_null", "provider_alias_only"]
)
def test_plan_accepts_consistent_numeric_aliases_and_optional_null(mode):
    from app.market_data.captured_live_recovery import plan_captured_recovery

    _, store, request, source, _ = captured_setup()
    rows = json.loads(source)
    for row in rows:
        row["total_turnover"] = row["turnover"]
        row["amount"] = row["turnover"]
        row["open_oi"] = row["open_interest"]
        row["close_oi"] = row["open_interest"]
        if mode == "optional_null":
            row["amount"] = None
            row["close_oi"] = None
        elif mode == "provider_alias_only":
            del row["turnover"]
            del row["amount"]
            del row["open_oi"]
            del row["close_oi"]
    plan = plan_captured_recovery(
        store,
        request,
        json.dumps(rows).encode(),
        runtime_identity="test",
        clock=lambda: request.cutoff,
    )
    assert len(plan["targets"]) == 5


def test_online_normalization_preserves_existing_alias_precedence():
    from app.market_data.rqdata_adapter import normalize_live_recovery_rows

    _, _, request, source, _ = captured_setup()
    rows = json.loads(source)
    original = normalize_live_recovery_rows(request, rows)
    rows[0].update(total_turnover="-1", amount="NaN", open_oi="-1", close_oi="NaN")
    assert normalize_live_recovery_rows(request, rows) == original
