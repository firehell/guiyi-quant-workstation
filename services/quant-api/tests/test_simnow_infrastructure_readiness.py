"""Market recovery admission is a read-only, current-owner check."""

from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from types import SimpleNamespace as NS

import pytest

from app import simnow_infrastructure_readiness as module

NOW = datetime(2026, 11, 3, 14, 20, tzinfo=UTC)


@pytest.fixture
def ready(tmp_path, monkeypatch):
    from app.db import session, readonly
    from app.market_data import market_phase, operational_universe
    from app import (
        runtime_bindings,
        runtime_handover,
        runtime_deployment,
        simnow_takeover_window,
    )

    products = tuple("P" + str(n) for n in range(60))
    phases = {
        p: NS(
            phase=market_phase.MarketPhase.TRADING
            if n < 45
            else market_phase.MarketPhase.CLOSED,
            trading_day=date(2026, 11, 4),
        )
        for n, p in enumerate(products)
    }
    registry = tmp_path / "registry"
    registry.write_bytes(b"actual runtime bindings")
    binding = NS(
        generation=56, commit="a" * 40, root="/fixture/runtime", tag="v1.16.73"
    )
    bindings = NS(
        services={
            name: binding
            for name in ("market-feed", "live", *[str(n) for n in range(8)])
        }
    )
    states = {
        name: dict(
            service=name,
            pid=100 if name == "market-feed" else 200,
            phase="active",
            generation=56,
            ready=True,
            at=NOW.isoformat(),
            proof={"cycle_ok": True}
            if name == "market-feed"
            else {"input_read_frontier": "42-0", "trading_day": "2026-11-04"},
        )
        for name in ("market-feed", "live")
    }
    elapsed = [0.0]
    tick = [lambda: None]
    heartbeats = {
        name: dict(
            generated_at=NOW.isoformat(),
            available=True,
            operational_count=60,
            runtime_generation=56,
            runtime_commit=binding.commit,
            runtime_root=binding.root,
            runtime_tag=binding.tag,
            metadata_preparation_error=None,
            phase_by_product={p: v.phase.value for p, v in phases.items()},
        )
        for name in states
    }
    heartbeats["market-feed"].update(input_failure=None, input_pending_count=0)
    heartbeats["live"]["coverage"] = {
        p: dict(state="ok", trading_day="2026-11-04", first_missing_bar_end=None)
        for p in products[:45]
    }

    class Redis:
        def get(self, key):
            return json.dumps(
                heartbeats["market-feed" if key == "live:feed:heartbeat" else "live"]
            )

        def close(self):
            raise AssertionError("caller Redis ownership must be retained")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(seconds=elapsed[0])

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(module, "monotonic", lambda: elapsed[0])

    def sleep(seconds):
        elapsed[0] += seconds
        tick[0]()

    monkeypatch.setattr(module, "sleep", sleep)
    monkeypatch.setattr(session, "SessionLocal", lambda: nullcontext(NS()))
    monkeypatch.setattr(readonly, "readonly_transaction", lambda *a, **k: nullcontext())
    monkeypatch.setattr(
        operational_universe, "load_operational_products", lambda: products
    )
    monkeypatch.setattr(
        market_phase,
        "MarketPhaseResolver",
        lambda db: NS(resolve=lambda p, now: phases[p]),
    )
    monkeypatch.setattr(runtime_bindings, "read_bindings", lambda: bindings)
    monkeypatch.setattr(runtime_bindings, "registry_path", lambda: registry)
    monkeypatch.setattr(runtime_handover, "read_service_state", lambda p: states[p])
    monkeypatch.setattr(runtime_handover, "_read", lambda p: None)
    monkeypatch.setattr(runtime_handover, "owner_lock_available", lambda p: False)
    monkeypatch.setattr(runtime_deployment, "owner_process_matches", lambda s, b: True)
    window = dict(
        trading_day="20261104",
        sessions=[
            dict(
                start=(NOW - timedelta(hours=1)).isoformat(),
                end=(NOW + timedelta(hours=1)).isoformat(),
            )
        ],
        session_facts_sha256="f" * 64,
    )
    monkeypatch.setattr(
        simnow_takeover_window, "authoritative_window", lambda *a, **k: window
    )
    return NS(
        redis=Redis(),
        phases=phases,
        states=states,
        hb=heartbeats,
        window=window,
        registry=registry,
        elapsed=elapsed,
        tick=tick,
    )


def test_all_sixty_known_and_forty_five_active_are_complete(ready):
    f = ready
    assert module.recovery_window("20261104", NOW, redis=f.redis) == {
        **f.window,
        "active": True,
        "runtime_registry_sha256": sha256(f.registry.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize(
    "damage",
    [
        "feed_unavailable",
        "live_unavailable",
        "pending",
        "coverage",
        "phase",
        "future",
        "stale",
        "owner",
        "identity",
        "metadata",
    ],
)
def test_any_unproven_market_fact_prevents_recovery(ready, damage):
    f = ready
    if damage == "feed_unavailable":
        f.hb["market-feed"]["available"] = False
    elif damage == "live_unavailable":
        f.hb["live"]["available"] = False
    elif damage == "pending":
        f.hb["market-feed"]["input_pending_count"] = 1
    elif damage == "coverage":
        f.hb["live"]["coverage"]["P0"]["state"] = "unknown"
    elif damage == "phase":
        f.hb["live"]["phase_by_product"]["P0"] = "CLOSED"
    elif damage == "future":
        f.hb["live"]["generated_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif damage == "stale":
        f.hb["market-feed"]["generated_at"] = (NOW - timedelta(seconds=31)).isoformat()
    elif damage == "owner":
        f.states["live"]["ready"] = False
        f.states["live"]["proof"] = {}
    elif damage == "identity":
        f.hb["live"]["runtime_commit"] = "b" * 40
    else:
        f.hb["live"]["metadata_preparation_error"] = "unproven"
    with pytest.raises(ValueError, match="INFRASTRUCTURE_RECOVERY_MARKET_UNPROVEN"):
        module.recovery_window("20261104", NOW, redis=f.redis)


def test_normal_poll_false_to_true_is_only_resampled_readonly(ready):
    f = ready
    proof = f.states["live"]["proof"]
    f.states["live"].update(ready=False, proof={})
    f.tick[0] = lambda: f.states["live"].update(ready=True, proof=proof)
    assert module.recovery_window("20261104", NOW, redis=f.redis)["active"]
    assert 0 < f.elapsed[0] <= 3


def test_poll_permanently_false_is_bounded_to_three_seconds(ready):
    f = ready
    f.states["live"].update(ready=False, proof={})
    with pytest.raises(ValueError):
        module.recovery_window("20261104", NOW, redis=f.redis)
    assert f.elapsed[0] == pytest.approx(3)


def test_explicit_poll_failure_is_not_waited_or_retried(ready):
    f = ready
    f.states["live"].update(ready=False, proof={"failure_code": "EXPLICIT_FAILURE"})
    with pytest.raises(ValueError):
        module.recovery_window("20261104", NOW, redis=f.redis)
    assert f.elapsed[0] == 0


def test_replacement_pid_cannot_supply_the_waited_ready_proof(ready):
    f = ready
    proof = f.states["live"]["proof"]
    f.states["live"].update(ready=False, proof={})
    f.tick[0] = lambda: f.states["live"].update(pid=201, ready=True, proof=proof)
    with pytest.raises(ValueError):
        module.recovery_window("20261104", NOW, redis=f.redis)
    assert f.elapsed[0] < 3


def test_final_normal_poll_start_keeps_prior_fresh_completed_cycle(ready, monkeypatch):
    from app import runtime_handover

    f = ready
    calls = {name: 0 for name in f.states}

    def state(name):
        calls[name] += 1
        value = dict(f.states[name])
        if calls[name] > 1:
            value.update(ready=False, proof={})
        return value

    monkeypatch.setattr(runtime_handover, "read_service_state", state)
    assert module.recovery_window("20261104", NOW, redis=f.redis)["active"]
    assert f.elapsed[0] == 0


def test_preview_pending_must_actually_drain_within_same_bounded_wait(ready):
    f = ready
    f.hb["market-feed"]["input_pending_count"] = 1
    f.tick[0] = lambda: f.hb["market-feed"].update(input_pending_count=0)
    assert module.recovery_window("20261104", NOW, redis=f.redis)["active"]
    assert 0 < f.elapsed[0] <= 3


def test_pending_does_not_mask_explicit_input_failure_or_coverage_gap(ready):
    f = ready
    f.hb["market-feed"].update(input_pending_count=1, input_failure="EXPLICIT_FAILURE")
    with pytest.raises(ValueError):
        module.recovery_window("20261104", NOW, redis=f.redis)
    assert f.elapsed[0] == 0


@pytest.mark.parametrize("drift", ["coverage", "control", "provider"])
def test_explicit_drift_during_normal_wait_is_terminal(ready, monkeypatch, drift):
    from app import runtime_handover

    f = ready
    f.states["live"].update(ready=False, proof={})
    changed = [False]

    def tick():
        changed[0] = True
        if drift == "coverage":
            f.hb["live"]["coverage"]["P0"]["state"] = "unknown"
        elif drift == "provider":
            f.hb["market-feed"]["input_failure"] = "EXPLICIT_FAILURE"

    f.tick[0] = tick
    if drift == "control":
        monkeypatch.setattr(
            runtime_handover,
            "_read",
            lambda path: {"phase": "drain"} if changed[0] else None,
        )
    with pytest.raises(ValueError):
        module.recovery_window("20261104", NOW, redis=f.redis)
    assert 0 < f.elapsed[0] < 3


def test_completed_cycle_observed_after_wait_deadline_does_not_extend_it(
    ready, monkeypatch
):
    from app import runtime_deployment

    f = ready
    proof = f.states["live"]["proof"]
    f.states["live"].update(ready=False, proof={})
    f.tick[0] = lambda: f.states["live"].update(ready=True, proof=proof)
    delayed = [False]

    def kernel(state, binding):
        if f.elapsed[0] > 0 and not delayed[0]:
            f.elapsed[0] += 3
            delayed[0] = True
        return True

    monkeypatch.setattr(runtime_deployment, "owner_process_matches", kernel)
    with pytest.raises(ValueError):
        module.recovery_window("20261104", NOW, redis=f.redis)
    assert f.elapsed[0] > 3
