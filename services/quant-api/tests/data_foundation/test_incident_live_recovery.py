"""Isolated evidence for the exact dependency-restart extra attempt."""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.market_data import incident_live_recovery as incident
from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore
from app.market_data.live_recovery import LiveRecoveryRequest, recover_product
from tests.data_foundation.test_live_market import FakeRedis, _bar


class IncidentRedis(FakeRedis):
    def eval(self, script, numkeys, *args):
        keys, argv = args[:numkeys], args[numkeys:]
        if script == incident.START_INCIDENT:
            if (
                self.get(keys[0]) is not None
                or self.get(keys[1]) is not None
                or self.get(keys[2]) != argv[1]
            ):
                return 0
            for i, key in enumerate(keys[3:], 2):
                if self.get(key) != argv[i] or json.loads(argv[i]) != {
                    "count": 3,
                    "last_at": incident.ORIGINAL_LAST_AT,
                }:
                    return 0
            self.set(keys[0], argv[0], ex=argv[-1])
            return 1
        if script == incident.CLAIM_EXTRA:
            if (
                self.get(keys[2]) != argv[1]
                or self.get(keys[1]) is not None
                or self.get(keys[3]) is not None
                or self.get(keys[0]) != argv[0]
                or self.get(keys[4]) != argv[2]
            ):
                return 0
            old = json.loads(argv[0])
            if (
                old != {"count": 3, "last_at": incident.ORIGINAL_LAST_AT}
                or argv[3] < old["last_at"] + 60000
            ):
                return 0
            self.set(keys[0], json.dumps({"count": 4, "last_at": argv[3]}), ex=argv[4])
            self.set(keys[3], argv[1], ex=argv[4])
            return 1
        return super().eval(script, numkeys, *args)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    from app.market_data.live_recovery_guard import recovery_guard

    monkeypatch.setattr(
        incident, "after_market_recovery_guard", lambda **_: nullcontext()
    )
    monkeypatch.setattr(
        incident,
        "recovery_guard",
        lambda symbol, **_: recovery_guard(
            symbol, root=tmp_path / "guards", legacy_root=True
        ),
    )
    redis = IncidentRedis()
    store = RedisLiveStore(redis)
    start = datetime(2026, 11, 3, 15, 30, tzinfo=UTC)
    now = start + timedelta(minutes=3, seconds=3)
    window = SessionWindow(start, start + timedelta(hours=1))
    snapshot = {s: f"{s.upper()}2612" for s in incident.SYMBOLS}
    snapshot.update({f"fixture{i}": f"FIXTURE{i}2612" for i in range(49)})
    store.set_subscriptions(incident.DAY, snapshot)
    requests, sources, budgets = [], {}, {}
    for symbol in incident.SYMBOLS:
        contract = snapshot[symbol]
        request = LiveRecoveryRequest(
            incident.DAY, symbol, contract, tuple(snapshot.items()), (window,), now
        )
        requests.append(request)
        bars = tuple(
            replace(
                _bar(1), trading_day=incident.DAY, bar_end=start + timedelta(minutes=i)
            )
            for i in (1, 2, 3)
        )
        sources[symbol] = bars
        for bar in bars[1:]:
            store.put_bar(incident.DAY, symbol, "1m", bar, contract=contract)
        key = f"{store._recovery_key(incident.DAY, symbol, contract)}:attempt:{start.isoformat()}"
        budgets[symbol] = key
        redis.set(key, json.dumps({"count": 3, "last_at": incident.ORIGINAL_LAST_AT}))
    authority = {
        "runtime_identity": incident.RUNTIME_IDENTITY,
        "trading_day": incident.DAY.isoformat(),
        "snapshot": snapshot,
        "sessions": {s: (window,) for s in incident.SYMBOLS},
    }
    return redis, store, tuple(requests), sources, budgets, now, authority


def run(setup, fetch=None, authority=None, clock=None):
    redis, store, requests, sources, budgets, now, facts = setup
    return incident.recover_incident(
        store,
        requests,
        fetch or (lambda r: sources[r.symbol]),
        clock=clock or (lambda: now),
        authority=authority or (lambda: facts),
    )


def test_exact_eleven_recover_once_without_publish_and_regular_limit_stays_three(setup):
    redis, store, requests, sources, budgets, now, _ = setup
    result = run(setup)
    assert (
        result["status"] == "LIVE_INCIDENT_COMPLETE" and len(result["outcomes"]) == 11
    )
    assert redis.published == []
    assert all(json.loads(redis.get(k))["count"] == 4 for k in budgets.values())
    assert all(
        store.bars_after(incident.DAY, r.symbol, "1m", None) == sources[r.symbol]
        for r in requests
    )
    with pytest.raises(ValueError, match="ALREADY_CLAIMED"):
        run(setup, fetch=lambda _: pytest.fail("no repeat fetch"))
    # The existing public worker still cannot make a fourth/fifth provider call.
    r = requests[0]
    redis.zsets[store._bars_key(incident.DAY, r.symbol, "1m")].clear()
    assert (
        recover_product(
            store, r, lambda _: pytest.fail("ordinary limit changed"), clock=lambda: now
        )
        == "RETRY_BUDGET_BLOCKED"
    )


@pytest.mark.parametrize(
    "failure", ["provider", "wrong_source", "overlap", "authority", "clock", "circuit"]
)
def test_after_claim_errors_stop_without_refund_or_next_product(setup, failure):
    redis, store, requests, sources, budgets, now, facts = setup
    calls = []
    authority = dict(facts)
    instant = [now]
    original = {k: dict(v) for k, v in redis.zsets.items()}

    def fetch(r):
        calls.append(r.symbol)
        if failure == "provider":
            raise RuntimeError("fixture provider failed")
        if failure == "wrong_source":
            return sources[r.symbol][1:]
        if failure == "overlap":
            return (*sources[r.symbol][:-1], replace(sources[r.symbol][-1], volume=999))
        if failure == "authority":
            authority["runtime_identity"] = "drift"
        if failure == "clock":
            instant[0] += timedelta(seconds=61)
        if failure == "circuit":
            redis.set(incident.CIRCUIT_KEY, "STOPPED")
        return sources[r.symbol]

    with pytest.raises((ValueError, RuntimeError)):
        run(setup, fetch=fetch, authority=lambda: authority, clock=lambda: instant[0])
    assert calls == ["ag"] and redis.zsets == original and redis.published == []
    assert json.loads(redis.get(budgets["ag"]))["count"] == 4
    assert all(
        json.loads(redis.get(budgets[s]))["count"] == 3 for s in incident.SYMBOLS[1:]
    )
    assert redis.get(incident.CLAIM_KEY) is not None
    with pytest.raises(ValueError):
        run(setup, fetch=lambda _: pytest.fail("unknown is terminal"))


@pytest.mark.parametrize(
    "change",
    ["symbol", "day", "snapshot", "session", "budget", "last_at", "circuit", "runtime"],
)
def test_preclaim_invalid_scope_never_fetches_or_spends(setup, change):
    redis, store, requests, sources, budgets, now, facts = setup
    requests = list(requests)
    if change == "symbol":
        requests[0] = replace(requests[0], symbol="bc")
    if change == "day":
        requests[0] = replace(requests[0], trading_day=incident.DAY + timedelta(days=1))
    if change == "snapshot":
        requests[0] = replace(requests[0], snapshot=requests[0].snapshot[:-1])
    if change == "session":
        requests[0] = replace(
            requests[0],
            sessions=(
                SessionWindow(now + timedelta(minutes=1), now + timedelta(hours=1)),
            ),
        )
    if change in {"budget", "last_at"}:
        value = json.loads(redis.get(budgets["ag"]))
        value["count" if change == "budget" else "last_at"] -= 1
        redis.set(budgets["ag"], json.dumps(value))
    if change == "circuit":
        redis.set(incident.CIRCUIT_KEY, "STOPPED")
    if change == "runtime":
        facts["runtime_identity"] = "drift"
    with pytest.raises(ValueError):
        incident.recover_incident(
            store,
            requests,
            lambda _: pytest.fail("no preclaim fetch"),
            clock=lambda: now,
            authority=lambda: facts,
        )
    assert redis.get(incident.CLAIM_KEY) is None
    assert all(json.loads(redis.get(k))["count"] <= 3 for k in budgets.values())


def test_unknown_start_claim_is_not_retried(setup, monkeypatch):
    redis, *_ = setup
    evaluate = redis.eval

    def unknown(script, *args):
        result = evaluate(script, *args)
        if script == incident.START_INCIDENT:
            raise ConnectionError("fixture response lost")
        return result

    monkeypatch.setattr(redis, "eval", unknown)
    with pytest.raises(ConnectionError):
        run(setup, fetch=lambda _: pytest.fail("start result unknown"))
    assert redis.get(incident.CLAIM_KEY) is not None
    monkeypatch.setattr(redis, "eval", evaluate)
    with pytest.raises(ValueError, match="ALREADY_CLAIMED"):
        run(setup, fetch=lambda _: pytest.fail("no replay"))


@pytest.fixture
def isolated_redis():
    # Same explicit nonproduction-port contract as test_observation_stream.
    import os
    from redis import Redis

    port = os.environ.get("GUIYI_TEST_REDIS_PORT")
    if not port:
        pytest.skip("requires disposable Redis on explicit nonproduction port")
    assert 1024 <= int(port) <= 65535 and int(port) != 6379
    client = Redis(host="127.0.0.1", port=int(port), db=11, decode_responses=True)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


@pytest.fixture
def real_setup(setup, isolated_redis):
    fake, unused, requests, sources, budgets, now, facts = setup
    for key, value in fake.values.items():
        isolated_redis.set(key, value, ex=259200)
    for key, values in fake.zsets.items():
        isolated_redis.zadd(key, values)
        isolated_redis.expire(key, 259200)
    return (
        isolated_redis,
        RedisLiveStore(isolated_redis),
        requests,
        sources,
        budgets,
        now,
        facts,
    )


def test_real_lua_eleven_extra_claims_and_no_repeat(real_setup):
    redis, store, requests, sources, budgets, unused, facts = real_setup
    result = run(real_setup)
    assert result["status"] == "LIVE_INCIDENT_COMPLETE"
    assert all(json.loads(redis.get(k))["count"] == 4 for k in budgets.values())
    assert all(
        redis.get(f"{incident.CLAIM_KEY}:{s}") == redis.get(incident.CLAIM_KEY)
        for s in incident.SYMBOLS
    )
    assert all(
        store.bars_after(incident.DAY, r.symbol, "1m", None) == sources[r.symbol]
        for r in requests
    )
    with pytest.raises(ValueError, match="ALREADY_CLAIMED"):
        run(real_setup, fetch=lambda _: pytest.fail("real Lua repeated"))


@pytest.mark.parametrize("phase", ["start", "extra"])
def test_real_lua_unknown_after_eval_is_terminal(real_setup, monkeypatch, phase):
    redis, store, requests, sources, budgets, unused, facts = real_setup
    before = tuple(
        store.bars_after(incident.DAY, r.symbol, "1m", None) for r in requests
    )
    evaluate = redis.eval
    target = incident.START_INCIDENT if phase == "start" else incident.CLAIM_EXTRA

    def lost_response(script, *args):
        result = evaluate(script, *args)
        if script == target:
            raise ConnectionError("fixture unknown-after-real-EVAL")
        return result

    monkeypatch.setattr(redis, "eval", lost_response)
    with pytest.raises(ConnectionError):
        run(real_setup, fetch=lambda _: pytest.fail("claim response was unknown"))
    monkeypatch.setattr(redis, "eval", evaluate)
    assert redis.get(incident.CLAIM_KEY) is not None
    assert json.loads(redis.get(budgets["ag"]))["count"] == (
        3 if phase == "start" else 4
    )
    assert all(
        json.loads(redis.get(budgets[s]))["count"] == 3 for s in incident.SYMBOLS[1:]
    )
    assert (
        tuple(store.bars_after(incident.DAY, r.symbol, "1m", None) for r in requests)
        == before
    )
    with pytest.raises(ValueError, match="ALREADY_CLAIMED"):
        run(real_setup, fetch=lambda _: pytest.fail("unknown real claim was replayed"))


def test_real_lua_overlap_rejects_without_any_bar_or_revision_change(real_setup):
    redis, store, requests, sources, budgets, unused, facts = real_setup
    before = {
        key: redis.zrange(key, 0, -1, withscores=True)
        for key in redis.scan_iter(match="live:bars:*")
    }

    def conflicting(request):
        bars = sources[request.symbol]
        return (*bars[:-1], replace(bars[-1], volume=bars[-1].volume + 1))

    with pytest.raises(ValueError, match="LIVE_BAR_CONFLICT"):
        run(real_setup, fetch=conflicting)
    assert {key: redis.zrange(key, 0, -1, withscores=True) for key in before} == before
    assert json.loads(redis.get(budgets["ag"]))["count"] == 4
    assert all(
        store.recovery_state(incident.DAY, r.symbol, r.contract) is None
        for r in requests
    )


def test_real_lua_start_rejects_one_drifted_budget_atomically(real_setup):
    redis, store, requests, sources, budgets, now, facts = real_setup
    expected, claim = incident._scope(requests, now)
    keys = [budgets[s] for s in incident.SYMBOLS]
    raw = [redis.get(k) for k in keys]
    redis.set(keys[-1], json.dumps({"count": 2, "last_at": incident.ORIGINAL_LAST_AT}))
    subscription_key = store._subscription_key(incident.DAY)
    assert (
        redis.eval(
            incident.START_INCIDENT,
            14,
            incident.CLAIM_KEY,
            incident.CIRCUIT_KEY,
            subscription_key,
            *keys,
            claim,
            redis.get(subscription_key),
            *raw,
            259200,
        )
        == 0
    )
    assert redis.get(incident.CLAIM_KEY) is None
    assert [redis.get(k) for k in keys[:-1]] == raw[:-1]
