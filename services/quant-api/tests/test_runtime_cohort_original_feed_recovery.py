"""A verified-phase original cohort can close Feed once, then recover separately."""

from copy import deepcopy
import json

import pytest

from app import runtime_cohort_recovery as recovery
from app.runtime_handover import _write
from tests.test_runtime_cohort_forward_recovery import fixture


@pytest.mark.parametrize(
    "damage", (None, "wrong_next", "started", "missing", "invalid")
)
def test_closed_day_only_registered_future_session_is_proven_without_day_write(
    tmp_path, damage
):
    from datetime import timedelta
    from types import SimpleNamespace
    from app.market_data.market_phase import MarketPhase
    from tests.test_runtime_cohort import Host

    now = Host(tmp_path).now()
    day = now.date() + timedelta(days=2)
    start = now + timedelta(days=2)
    windows = (SimpleNamespace(start=start, end=start + timedelta(hours=1)),)
    if damage == "started":
        windows = (SimpleNamespace(start=now - timedelta(seconds=1), end=start),)
    elif damage == "missing":
        windows = ()
    elif damage == "invalid":
        windows = (object(),)
    resolver = SimpleNamespace(
        resolve=lambda *args: SimpleNamespace(
            symbol="ap",
            phase=MarketPhase.CLOSED,
            trading_day=None,
            current_session=None,
            next_session_start=start + timedelta(seconds=1)
            if damage == "wrong_next"
            else start,
        ),
        completed_observation_trading_day=lambda *args: now.date(),
    )
    kwargs = dict(
        now=now,
        products=("ap",),
        resolver=resolver,
        registered_day=day,
        subscriptions={"ap": "AP2701"},
        dominant=lambda *args: "AP2701",
        sessions=lambda *args: windows,
    )
    if damage:
        with pytest.raises(ValueError):
            recovery.prove_same_generation_startup(**kwargs)
    else:
        proof = recovery.prove_same_generation_startup(**kwargs)
        assert proof["registered_trading_day"] == str(day)
        assert proof["closed_idle"] is True
        assert proof["natural_bar_verified"] is False


@pytest.mark.parametrize("tag", ("v1.16.53", "not-a-release"))
def test_controller_uses_exact_tag_authority_in_managed_worktree(
    tmp_path, monkeypatch, tag
):
    from app import runtime_bindings

    calls = []

    def git(root, *args):
        calls.append(args)
        return "a" * 40 if args == ("rev-parse", "HEAD") else tag

    monkeypatch.setattr(runtime_bindings, "_git", git)
    monkeypatch.setattr(
        runtime_bindings,
        "_tracked",
        lambda root: {
            "services/quant-api/app/runtime_cohort_recovery.py": "b" * 40,
            "services/quant-api/app/reference_trading/receiving_liveness.py": "c" * 40,
        },
    )
    host = object.__new__(recovery.ForwardRecoveryHost)
    host.directory = tmp_path
    verified = []
    host.verify_release = lambda root, actual_tag, commit: verified.append(
        (root, actual_tag, commit)
    )
    if tag == "not-a-release":
        with pytest.raises(ValueError, match="CONTROLLER_RELEASE_REQUIRED"):
            host._controller()
        assert not verified
    else:
        result = host._controller()
        assert result["tag"] == tag
        assert verified == [(recovery.Path(result["root"]), tag, "a" * 40)]
        assert calls[0] == ("describe", "--exact-match", "--match", "v[0-9]*", "HEAD")


def original_fixture(tmp_path, monkeypatch):
    host, source, path, attempt, _old_state, base_audit = fixture(tmp_path)
    _write(attempt / "plan.json", source)
    services = host.registry.services
    effects = {
        "prewarm": {name: {} for name in recovery.CONTINUOUS},
        "calendars_off": {"idle_unloaded": list(recovery.CALENDARS)},
        "drain": {
            "feed_close": {},
            "owners": {},
            "progress": {name: {} for name in ("market-feed", "live", "alert")},
            "reference_receiving_handover": {},
        },
        "old_exited": {"old_pids_exited": True, "bootout_requests": {}},
        "preserve": {"history_retained": True},
        "install": {"installed": sorted(services)},
        "consumers": {"started": "consumers"},
        "consumers_ready": {
            name: "active" for name in recovery.CONTINUOUS if name != "market-feed"
        },
        "feed": {"started": "market-feed"},
        "bootout_requests": {},
    }
    state = {
        "schema_version": 1,
        "plan_sha256": source["plan_sha256"],
        "phase": "outcome_unknown",
        "failed_phase": "verified",
        "error_type": "ReceivingLivenessError",
        "effects": effects,
    }
    _write(attempt / "state.json", state)
    _write(host.directory / "cohort-release.json", state)
    original_bytes = (attempt / "state.json").read_bytes()
    monkeypatch.setattr(
        recovery, "validate_cohort", lambda *_args, **_kwargs: (host.old, host.registry)
    )
    monkeypatch.setattr(recovery, "registry", lambda *_args, **_kwargs: host.registry)
    monkeypatch.setattr(
        recovery, "_verify_historical_release", lambda *_args, **_kwargs: None
    )
    identity = recovery._source(host, path, allow_original=True)[2]
    intent = {
        "kind": "parked_feed_close_intent_v1",
        "observed_pids": [1234],
        "binding_sha256": "a" * 64,
        "owners_sha256": "b" * 64,
        "controls_sha256": "c" * 64,
        "frontiers_sha256": "d" * 64,
    }
    closed = {
        "kind": "feed_closed_v1",
        "intent_sha256": recovery.digest(intent),
        "observed_pids": [1234],
        "label_absent": True,
        "observed_pids_exited": True,
        "owner_lock_available": True,
        "frontiers_sha256": intent["frontiers_sha256"],
        "observed_at": host.now().isoformat(),
    }
    close_descriptor = None

    def audit_forward(_source, _budget, **kwargs):
        nonlocal close_descriptor
        assert kwargs["original_identity"] == identity
        assert kwargs["predecessor"] is None
        audit = deepcopy(base_audit)
        if kwargs["close_feed_only"]:
            feed_close = intent
        else:
            close_descriptor = recovery._original_feed_close_attempt(
                host,
                kwargs["feed_close_plan"],
                identity,
            )[0]
            feed_close = {
                "kind": "feed_close_readback_v1",
                "attempt": close_descriptor,
                "proof": closed,
            }
        proof = {
            "source_plan_sha256": source["plan_sha256"],
            "owners_sha256": recovery.digest(audit["owners"]),
            "controls_sha256": recovery.digest(audit["controls"]),
            "receiving_context": "e" * 64,
            "feed_close_sha256": recovery.digest(feed_close),
            "all_consumers_parked": True,
            "current_tail_reached": True,
        }
        proof["proof_sha256"] = recovery.digest(proof)
        audit.update(
            receiving_context="e" * 64,
            feed_close=feed_close,
            original_verified_feed_halt=proof,
        )
        return audit

    host.audit_forward = audit_forward

    def stop_feed(_source, audit, _budget, record):
        assert audit["feed_close"] == intent
        record(
            {
                "phase": "bootout_requested",
                "intent": intent,
                "observed_pids": intent["observed_pids"],
            }
        )
        host.calls.append("bootout")
        return closed

    host.stop_parked_feed = stop_feed
    return host, source, path, attempt, original_bytes, identity


def test_original_verified_feed_halt_closes_once_then_normal_recovery(
    tmp_path,
    monkeypatch,
):
    host, source, source_path, attempt, original_bytes, identity = original_fixture(
        tmp_path,
        monkeypatch,
    )
    with pytest.raises(ValueError, match="FORWARD_SOURCE_INVALID"):
        recovery.freeze_forward_recovery(host, source_path)
    close_plan = recovery.freeze_forward_recovery(
        host,
        source_path,
        original_verified_feed_halt=True,
        close_feed_only=True,
    )
    assert close_plan["mode"] == recovery.ORIGINAL_FEED_MODE
    close_path = tmp_path / "close.json"
    _write(close_path, close_plan)
    result = recovery.apply_forward_recovery(host, close_path)
    assert result["status"] == "feed_closed"
    assert host.calls == ["bootout"]
    assert (attempt / "state.json").read_bytes() == original_bytes
    assert (
        json.loads((host.directory / "cohort-release.json").read_bytes())["phase"]
        == "outcome_unknown"
    )
    with pytest.raises(ValueError, match="ATTEMPT_ALREADY_EXISTS"):
        recovery.apply_forward_recovery(host, close_path)
    normal = recovery.freeze_forward_recovery(
        host,
        source_path,
        original_verified_feed_halt=True,
        feed_close_plan=close_path,
    )
    assert normal["original_close"]["plan_sha256"] == close_plan["plan_sha256"]
    normal_path = tmp_path / "normal.json"
    _write(normal_path, normal)
    final = recovery.apply_forward_recovery(host, normal_path)
    assert final["status"] == "recovered"
    assert host.calls == [
        "bootout",
        "consumers",
        "intake",
        "feed",
        "verified",
        "calendars",
    ]
    assert (attempt / "state.json").read_bytes() == original_bytes
    receipt = json.loads(
        (
            host.directory
            / "cohort-forward-recoveries"
            / normal["plan_sha256"]
            / "receipt.json"
        ).read_bytes()
    )
    assert receipt["original_feed_halt_resolution"]["source"] == identity
    assert (
        receipt["original_feed_halt_resolution"]["feed_close"]
        == normal["original_close"]
    )
    assert (
        json.loads((host.directory / "cohort-release.json").read_bytes())["phase"]
        == "switched"
    )
    recovery._no_unresolved_recovery(host)


@pytest.mark.parametrize(
    "mutation",
    (
        "phase",
        "failed_phase",
        "error_type",
        "missing_effect",
        "private_plan",
        "global_bytes",
    ),
)
def test_original_source_requires_exact_failure_and_all_retained_bytes(
    tmp_path,
    monkeypatch,
    mutation,
):
    host, source, path, attempt, _original_bytes, _identity = original_fixture(
        tmp_path,
        monkeypatch,
    )
    state = json.loads((attempt / "state.json").read_bytes())
    if mutation == "phase":
        state["phase"] = "switched"
    elif mutation == "failed_phase":
        state["failed_phase"] = "feed"
    elif mutation == "error_type":
        state["error_type"] = "OtherError"
    elif mutation == "missing_effect":
        del state["effects"]["consumers_ready"]
    elif mutation == "private_plan":
        private = deepcopy(source)
        private["protected"] = {}
        _write(attempt / "plan.json", private)
    else:
        _write(host.directory / "cohort-release.json", {"phase": "unknown"})
    if mutation not in {"private_plan", "global_bytes"}:
        _write(attempt / "state.json", state)
        _write(host.directory / "cohort-release.json", state)
    with pytest.raises(ValueError, match="FORWARD_SOURCE_INVALID"):
        recovery.freeze_forward_recovery(
            host,
            path,
            original_verified_feed_halt=True,
            close_feed_only=True,
        )


@pytest.mark.parametrize(
    "old_tail,ack,valid",
    ((False, "1-0", False), (True, "0-0", False), (True, "1-0", True)),
)
def test_original_host_audit_requires_old_tail_and_current_complete_ack(
    tmp_path,
    monkeypatch,
    old_tail,
    ack,
    valid,
):
    from app.reference_trading import receiving_liveness

    host, source, _path, _attempt, _bytes, identity = original_fixture(
        tmp_path,
        monkeypatch,
    )
    intent = host.audit_forward(
        source,
        lambda: None,
        original_identity=identity,
        close_feed_only=True,
        predecessor=None,
    )["feed_close"]
    host._fixed = lambda *_args: {"installed": "matched"}
    host._old_exited = lambda *_args: "a" * 64
    host._controls = lambda *_args: {"live": {}}
    phases = []

    def parked(_source, **kwargs):
        phases.append(kwargs.get("feed_parked"))
        return {name: {"phase": "parked"} for name in recovery.CONTINUOUS}

    host._parked_owners = parked
    host.definition_absent = lambda _binding: True
    host._calculation_boundary = lambda *_args, **_kwargs: None
    host._snapshot = lambda *_args, **_kwargs: {
        "old_tail_reached": old_tail,
        "days": {
            "2026-10-25": {"ack": ack, "current_tail": "1-0", "final_tail": "1-0"}
        },
    }
    host.recovery_window = lambda: {"window": "verified"}
    host._new_protected = {"scope": "new-frozen"}
    host.feed_close_intent = lambda *_args: intent
    monkeypatch.setattr(recovery, "observation_progress", lambda _name: {})
    monkeypatch.setattr(recovery, "progress_reached", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        receiving_liveness, "receiving_context_identity", lambda _snapshot: "e" * 64
    )
    monkeypatch.setattr(
        receiving_liveness, "receiving_snapshot_identity", lambda _snapshot: "f" * 64
    )
    if valid:
        result = recovery.ForwardRecoveryHost.audit_forward(
            host,
            source,
            lambda: None,
            original_identity=identity,
            close_feed_only=True,
        )
        assert result["feed_close"] == intent
    else:
        with pytest.raises(ValueError, match="LEGACY_FRONTIER_UNPROVEN"):
            recovery.ForwardRecoveryHost.audit_forward(
                host,
                source,
                lambda: None,
                original_identity=identity,
                close_feed_only=True,
            )
    assert phases == [True]


def test_unrelated_unknown_recovery_blocks_original_second_stage(tmp_path, monkeypatch):
    host, _source, source_path, _attempt, _bytes, _identity = original_fixture(
        tmp_path,
        monkeypatch,
    )
    close = recovery.freeze_forward_recovery(
        host,
        source_path,
        original_verified_feed_halt=True,
        close_feed_only=True,
    )
    close_path = tmp_path / "close.json"
    _write(close_path, close)
    assert recovery.apply_forward_recovery(host, close_path)["status"] == "feed_closed"
    unrelated = host.directory / "cohort-forward-recoveries" / ("f" * 64)
    unrelated.mkdir(mode=0o700)
    _write(unrelated / "state.json", {"phase": "outcome_unknown"})
    with pytest.raises(ValueError, match="RECOVERY_READBACK_REQUIRED"):
        recovery.freeze_forward_recovery(
            host,
            source_path,
            original_verified_feed_halt=True,
            feed_close_plan=close_path,
        )
