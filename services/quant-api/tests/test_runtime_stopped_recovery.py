"""A verified parked frontier replaces recursive failed-attempt special cases."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app import runtime_cohort_recovery as recovery
from app.runtime_handover import _write
from tests.test_runtime_feed_halt_recovery import feed_halt_case, close_plan


def original_failed_consumers(tmp_path, monkeypatch):
    from tests.test_runtime_cohort_original_feed_recovery import original_fixture

    host, _, source, _, _, _ = original_fixture(tmp_path, monkeypatch)
    close = recovery.freeze_forward_recovery(
        host, source, original_verified_feed_halt=True, close_feed_only=True
    )
    close_path = tmp_path / "original-close.json"
    _write(close_path, close)
    recovery.apply_forward_recovery(host, close_path)
    frozen = recovery.freeze_forward_recovery(
        host, source, original_verified_feed_halt=True, feed_close_plan=close_path
    )
    generation = recovery.registry(frozen["new"]).services["live"].generation
    host.resume_consumers = lambda *args: {"resumed_generation": generation}
    path = tmp_path / "original-failed.json"
    _write(path, frozen)

    def fail(*args):
        raise recovery.CohortError("COHORT_FORWARD_READY_TIMEOUT")

    host.await_consumers = fail
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        recovery.apply_forward_recovery(host, path)
    audit = {
        key: deepcopy(value)
        for key, value in frozen["audit"].items()
        if key not in {"feed_close", "original_verified_feed_halt"}
    }
    audit.update(
        feed_exited_pids=[1234],
        controls={"fresh": "halt-controls"},
        owners={"current": "parked"},
    )
    host.audit_stopped = lambda *args, **kwargs: deepcopy(audit)
    return host, path, frozen, audit


def test_original_consumer_only_timeout_reuses_stopped_frontier_without_replay(
    tmp_path, monkeypatch
):
    from app.runtime_stopped_recovery import reconcile_stopped, read_confirmation

    host, failed_path, failed, _ = original_failed_consumers(tmp_path, monkeypatch)
    folder = host.directory / "cohort-forward-recoveries" / failed["plan_sha256"]
    original = (folder / "state.json").read_bytes()
    pointer = (host.directory / "cohort-release.json").read_bytes()
    result = reconcile_stopped(host, failed_path)
    assert result == reconcile_stopped(host, failed_path)
    selected = result["confirmation"]
    confirmation = read_confirmation(host, selected)
    assert set(confirmation["attempts"]) == {
        failed["plan_sha256"],
        failed["original_close"]["plan_sha256"],
    }
    assert (folder / "state.json").read_bytes() == original
    assert (host.directory / "cohort-release.json").read_bytes() == pointer
    fresh = recovery.freeze_forward_recovery(
        host, failed["source"]["plan_path"], stopped_confirmation=selected["path"]
    )
    assert fresh["mode"] == "reconciled_stopped"
    fresh_path = tmp_path / "original-fresh.json"
    _write(fresh_path, fresh)
    host.await_consumers = lambda *args: {"kind": "typed_receiver"}
    assert recovery.apply_forward_recovery(host, fresh_path)["status"] == "recovered"
    recovery._no_unresolved_recovery(host)
    assert (folder / "state.json").read_bytes() == original


@pytest.mark.parametrize("damage", ("feed", "error", "other_unknown", "close_receipt"))
def test_original_stopped_frontier_rejects_unproven_work(tmp_path, monkeypatch, damage):
    from app.runtime_stopped_recovery import reconcile_stopped

    host, failed_path, failed, _ = original_failed_consumers(tmp_path, monkeypatch)
    folder = host.directory / "cohort-forward-recoveries" / failed["plan_sha256"]
    if damage == "other_unknown":
        extra = folder.parent / ("f" * 64)
        extra.mkdir(mode=0o700)
        _write(extra / "state.json", {"phase": "outcome_unknown"})
    elif damage == "close_receipt":
        close_dir = folder.parent / failed["original_close"]["plan_sha256"]
        (close_dir / "receipt.json").write_text("{}")
    else:
        state = json.loads((folder / "state.json").read_text())
        if damage == "feed":
            state["effects"]["feed"] = {"bootstrapped": True}
        else:
            state["error_type"] = "OtherError"
        _write(folder / "state.json", state)
    with pytest.raises(ValueError):
        reconcile_stopped(host, failed_path)


def failed_consumers(tmp_path):
    host, source, c_path, _ = feed_halt_case(tmp_path)
    _, close = close_plan(host, source, c_path, tmp_path)
    recovery.apply_forward_recovery(host, close)
    host.calls.clear()
    frozen = recovery.freeze_forward_recovery(
        host, source, predecessor_recovery_plan=c_path, feed_close_plan=close
    )
    generation = recovery.registry(frozen["new"]).services["live"].generation
    host.resume_consumers = lambda *args: (
        host.calls.append("consumers") or {"resumed_generation": generation}
    )
    path = tmp_path / "failed.json"
    _write(path, frozen)

    def fail(*args):
        raise recovery.CohortError("COHORT_FORWARD_READY_TIMEOUT")

    host.await_consumers = fail
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        recovery.apply_forward_recovery(host, path)
    host.calls.clear()
    audit = {
        key: deepcopy(value)
        for key, value in frozen["audit"].items()
        if key not in ("feed_close", "confirmed_feed_halt")
    }
    audit["feed_exited_pids"] = [40577]
    audit["controls"] = {"fresh": "halt-controls"}
    audit["owners"] = {"current": "parked"}
    host.audit_stopped = lambda *args, **kwargs: deepcopy(audit)
    return host, path, frozen, audit


def test_reconcile_preserves_failed_bytes_and_reuses_same_confirmation(tmp_path):
    from app.runtime_stopped_recovery import reconcile_stopped

    host, path, frozen, _ = failed_consumers(tmp_path)
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    before = (attempt / "state.json").read_bytes()
    pointer = (host.directory / "cohort-release.json").read_bytes()
    first = reconcile_stopped(host, path)
    assert first == reconcile_stopped(host, path)
    assert first["status"] == "stopped_confirmed"
    assert (attempt / "state.json").read_bytes() == before
    assert (host.directory / "cohort-release.json").read_bytes() == pointer
    assert host.calls == []


@pytest.mark.parametrize("change", ["effect", "state", "other_unknown", "controls"])
def test_reconcile_rejects_unproven_or_changed_frontier(tmp_path, change):
    from app.runtime_stopped_recovery import reconcile_stopped

    host, path, frozen, audit = failed_consumers(tmp_path)
    reconcile_stopped(host, path)
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    if change == "controls":
        audit["controls"]["fresh"] = "different"
    elif change == "other_unknown":
        extra = attempt.parent / ("e" * 64)
        extra.mkdir(mode=0o700)
        _write(extra / "state.json", {"phase": "outcome_unknown"})
    else:
        state = json.loads((attempt / "state.json").read_text())
        if change == "effect":
            state["effects"]["feed"] = {"bootstrapped": True}
        else:
            state["error_code"] = "CHANGED"
        _write(attempt / "state.json", state)
    with pytest.raises(ValueError):
        reconcile_stopped(host, path)


def test_confirmed_stopped_can_recover_and_close_all_failed_attempts(tmp_path):
    from app.runtime_stopped_recovery import reconcile_stopped

    host, path, frozen, _ = failed_consumers(tmp_path)
    result = reconcile_stopped(host, path)
    source = frozen["source"]["plan_path"]
    plan = recovery.freeze_forward_recovery(
        host, source, stopped_confirmation=result["confirmation"]["path"]
    )
    assert plan["mode"] == "reconciled_stopped"
    assert "predecessor" not in plan
    target = tmp_path / "fresh.json"
    _write(target, plan)
    host.await_consumers = lambda *args: {"kind": "typed_receiver"}
    host.resume_feed = lambda *args: host.calls.append("feed") or {"started": True}
    result = recovery.apply_forward_recovery(host, target)
    assert result["status"] == "recovered"
    assert host.calls == ["consumers", "feed", "verified", "calendars"]
    recovery._no_unresolved_recovery(host)


def test_failed_successor_is_flattened_not_a_recursive_predecessor(tmp_path):
    from app.runtime_stopped_recovery import reconcile_stopped, read_confirmation

    host, path, frozen, _ = failed_consumers(tmp_path)
    first = reconcile_stopped(host, path)
    plan = recovery.freeze_forward_recovery(
        host,
        frozen["source"]["plan_path"],
        stopped_confirmation=first["confirmation"]["path"],
    )
    target = tmp_path / "fresh.json"
    _write(target, plan)
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        recovery.apply_forward_recovery(host, target)
    second = reconcile_stopped(host, target)
    value = read_confirmation(host, second["confirmation"])
    assert len(value["attempts"]) == 6
    assert "predecessor" not in value
    assert first["confirmation"]["path"] in value["files"]


def test_confirmation_atomic_write_failure_never_returns_success(tmp_path, monkeypatch):
    from app import runtime_stopped_recovery as stopped

    host, path, _, _ = failed_consumers(tmp_path)
    monkeypatch.setattr(
        recovery,
        "_exclusive_json",
        lambda *args: (_ for _ in ()).throw(OSError("private")),
    )
    with pytest.raises(OSError):
        stopped.reconcile_stopped(host, path)


@pytest.mark.parametrize(
    "field", ["installed_sha256", "new_protected", "protected", "receiving_context"]
)
def test_initial_reconciliation_never_rebaselines_protected_or_installed_drift(
    tmp_path, field
):
    from app.runtime_stopped_recovery import reconcile_stopped

    host, path, _, audit = failed_consumers(tmp_path)
    audit[field] = {"drift": "changed"}
    with pytest.raises(ValueError):
        reconcile_stopped(host, path)


def test_a_handcrafted_confirmation_cannot_whitelist_an_extra_unknown(tmp_path):
    from app.runtime_stopped_recovery import (
        reconcile_stopped,
        read_confirmation,
        descriptor,
    )

    host, path, frozen, _ = failed_consumers(tmp_path)
    result = reconcile_stopped(host, path)
    confirmation = Path(result["confirmation"]["path"])
    value = json.loads(confirmation.read_text())
    extra = host.directory / "cohort-forward-recoveries" / ("e" * 64)
    extra.mkdir(mode=0o700)
    _write(extra / "plan.json", frozen)
    _write(extra / "state.json", {"phase": "outcome_unknown", "effects": {"feed": {}}})
    value["attempts"].append(extra.name)
    for leaf in ("plan.json", "state.json"):
        value["files"][str(extra / leaf)] = (
            __import__("hashlib").sha256((extra / leaf).read_bytes()).hexdigest()
        )
    _write(confirmation, value)
    with pytest.raises(ValueError):
        read_confirmation(host, descriptor(confirmation))


@pytest.mark.parametrize(
    "mode", ["confirmed_live_stop", "confirmed_intake_halt", "confirmed_feed_halt"]
)
def test_stopped_confirmation_is_never_an_extra_field_on_legacy_modes(tmp_path, mode):
    host, _, frozen, _ = failed_consumers(tmp_path)
    altered = deepcopy(frozen)
    altered["mode"] = mode
    altered["stopped_confirmation"] = {"path": "/unrelated", "sha256": "a" * 64}
    altered["plan_sha256"] = recovery.digest(
        {k: v for k, v in altered.items() if k != "plan_sha256"}
    )
    with pytest.raises(ValueError, match="PLAN_INVALID"):
        recovery._validate(altered, host.now())


@pytest.mark.parametrize(
    "failure", [None, "feed_reappeared", "owner_changed", "prefix_changed"]
)
def test_native_stopped_observer_pins_kernel_locks_and_rejects_drift(
    tmp_path, monkeypatch, failure
):
    from app import runtime_stopped_recovery as stopped
    import app.reference_trading.receiving_liveness as liveness
    import app.runtime_deployment as deployment
    from tests.test_runtime_cohort_forward_recovery import fixture, native

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    names = recovery.CONTINUOUS
    for name in names:
        path = current.directory / (name + ".owner.lock")
        path.touch(mode=0o600)
    current._fixed = lambda *args: {"installed": "fixed"}
    current._new_protected = {"protected": "fixed"}
    observations = [0]

    def parked(*args, held=False, **kwargs):
        assert held
        assert all(
            not recovery.owner_lock_available(n, runtime_dir=current.directory)
            for n in names
        )
        observations[0] += 1
        return {"owner": observations[0] if failure == "owner_changed" else "exact"}

    current._parked_owners = parked
    current._controls = lambda *args: {"fresh": "current"}
    current.definition_absent = lambda *args: True
    current._feed_exited = lambda *args: failure != "feed_reappeared"
    current._calculation_boundary = lambda: True
    current._snapshot = lambda *args: {
        "old_tail_reached": True,
        "days": {"day": {"ack": "1-0", "current_tail": "1-0", "final_tail": "1-0"}},
    }
    frontiers = [0]

    def frontier(*args):
        frontiers[0] += 1
        return {"sha": frontiers[0] if failure == "prefix_changed" else "fixed"}

    current._feed_frontiers = frontier
    current.binding_hash = lambda: "binding"
    current._old_exited = lambda *args: "old-exited"
    current.recovery_window = lambda: {"session": "valid"}
    current._controller = lambda: {"controller": "exact"}
    monkeypatch.setattr(deployment, "observation_progress", lambda *args: {})
    monkeypatch.setattr(deployment, "progress_reached", lambda *args, **kwargs: True)
    # This native-lock observer case only needs source progress key presence.
    original = (
        current.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
    )
    value = json.loads(original.read_text())
    value["effects"]["drain"]["progress"] = {
        n: {} for n in ("market-feed", "live", "alert")
    }
    _write(original, value)
    monkeypatch.setattr(
        liveness, "receiving_snapshot_identity", lambda *args: "receiving"
    )
    monkeypatch.setattr(liveness, "receiving_context_identity", lambda *args: "context")
    if failure:
        with pytest.raises(ValueError):
            stopped.observe_stopped(current, source, lambda: None, feed_pids=[40577])
    else:
        result = stopped.observe_stopped(
            current, source, lambda: None, feed_pids=[40577]
        )
        assert result["controls"] == {"fresh": "current"}
    assert all(
        recovery.owner_lock_available(n, runtime_dir=current.directory) for n in names
    )
