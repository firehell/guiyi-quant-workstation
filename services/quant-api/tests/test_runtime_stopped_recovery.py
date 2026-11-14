"""A verified parked frontier replaces recursive failed-attempt special cases."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app import runtime_cohort_recovery as recovery
from app.runtime_handover import _write
from tests.test_runtime_feed_halt_recovery import feed_halt_case, close_plan


def typed_intake():
    return {
        "schema_version": 2,
        "kind": "reference_receiving_liveness_v1",
        "mode": "durable_receiving_caught_up_idle",
        "calculation_ready": False,
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "advanced_count": 0,
        "remaining_count": 0,
        "old_tail_reached": True,
    }


def complete_stopped_outputs(host):
    host.await_consumers = lambda *args: typed_intake()
    host.resume_feed = lambda *args: host.calls.append("feed") or {
        "bootstrapped": True, "label": "com.guiyi.quant-market-feed",
    }
    host.verify_forward = lambda *args: host.calls.append("verified") or {
        "continuous_identity": "matched", "calculation_ready": False,
        "intake": typed_intake(), "natural_acceptance": "pending",
    }
    host.forward_calendars = lambda *args: host.calls.append("calendars") or {
        "calendar_registration_only": True, "identity": "matched",
    }


def failed_after_feed(tmp_path, monkeypatch, *, calendars=False, original=False):
    from app import runtime_stopped_recovery as stopped

    if original:
        from tests.test_runtime_cohort_original_feed_recovery import original_fixture

        host, _, source, _, _, _ = original_fixture(tmp_path, monkeypatch)
        close = recovery.freeze_forward_recovery(
            host, source, original_verified_feed_halt=True, close_feed_only=True
        )
        close_path = tmp_path / "original-close.json"
        _write(close_path, close)
        recovery.apply_forward_recovery(host, close_path)
        plan = recovery.freeze_forward_recovery(
            host, source, original_verified_feed_halt=True, feed_close_plan=close_path
        )
    else:
        host, failed_path, failed, _ = original_failed_consumers(tmp_path, monkeypatch)
        selected = stopped.reconcile_stopped(host, failed_path)["confirmation"]
        plan = recovery.freeze_forward_recovery(
            host, failed["source"]["plan_path"], stopped_confirmation=selected["path"]
        )
    generation = plan["new"]["services"]["live"]["generation"]
    host.resume_consumers = lambda *args: {"resumed_generation": generation}
    host.await_consumers = lambda *args: typed_intake()
    host.resume_feed = lambda *args: {
        "bootstrapped": True,
        "label": "com.guiyi.quant-market-feed",
    }

    def fail(*args):
        raise recovery.CohortError("REFERENCE_RECEIVING_LIVENESS_UNPROVEN")

    if calendars:
        host.verify_forward = lambda *args: {
            "continuous_identity": "matched",
            "calculation_ready": False,
            "intake": typed_intake(),
            "natural_acceptance": "pending",
        }

        class UnclassifiedCalendarFailure(Exception):
            pass

        def fail_calendar(*args):
            host.calls.append("calendar_registration_attempted")
            raise UnclassifiedCalendarFailure("private failure text")

        host.forward_calendars = fail_calendar
    else:
        host.verify_forward = fail
    path = tmp_path / "failed-after-feed.json"
    _write(path, plan)
    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        recovery.apply_forward_recovery(host, path)
    generation = plan["new"]["services"]["market-feed"]["generation"]
    parked = {
        k: deepcopy(v)
        for k, v in plan["audit"].items()
        if k not in {
            "stopped_confirmation", "feed_exited_pids", "original_verified_feed_halt"
        }
    }
    parked.update(
        feed_state="parked",
        feed_observed_pids=[2222],
        frontiers_sha256="f" * 64,
        owners={
            "current": "parked",
            "market-feed": {"phase": "parked", "generation": generation, "pid": 2222},
        },
        controls={"fresh": "post-feed-halt"},
    )
    intent = {
        "kind": "parked_feed_close_intent_v1",
        "observed_pids": [2222],
        "binding_sha256": recovery.digest(plan["new"]["services"]["market-feed"]),
        "owners_sha256": recovery.digest(parked["owners"]),
        "controls_sha256": recovery.digest(parked["controls"]),
        "frontiers_sha256": parked["frontiers_sha256"],
    }
    parked["feed_close"] = intent
    closed = [False]

    def audit_stopped(_source, _budget, **kwargs):
        if kwargs.get("feed_parked"):
            assert not closed[0]
            return deepcopy(parked)
        assert closed[0]
        result = {
            k: deepcopy(v)
            for k, v in parked.items()
            if k not in {"feed_state", "feed_observed_pids", "feed_close"}
        }
        result["feed_exited_pids"] = [2222]
        result["owners"]["market-feed"] = {"phase": "absent", "generation": generation}
        return result

    def stop(_source, audit, _budget, record):
        assert not closed[0] and audit["feed_close"] == intent
        record(
            {"phase": "bootout_requested", "intent": intent, "observed_pids": [2222]}
        )
        host.calls.append("close_stopped_feed")
        closed[0] = True
        return {
            "kind": "feed_closed_v1",
            "intent_sha256": recovery.digest(intent),
            "observed_pids": [2222],
            "label_absent": True,
            "observed_pids_exited": True,
            "owner_lock_available": True,
            "frontiers_sha256": intent["frontiers_sha256"],
            "observed_at": host.now().isoformat(),
        }

    host.audit_stopped = audit_stopped
    host.stop_parked_feed = stop
    return host, path, plan, parked, closed


def recover_after_feed_failure(tmp_path, monkeypatch, *, calendars=False, original=False, interrupt=False):
    from app import runtime_stopped_recovery as stopped

    host, path, failed, _, closed = failed_after_feed(
        tmp_path, monkeypatch, calendars=calendars, original=original
    )
    folder = host.directory / "cohort-forward-recoveries" / failed["plan_sha256"]
    original = (folder / "state.json").read_bytes()
    selected = stopped.reconcile_stopped(host, path)["confirmation"]
    assert stopped.read_confirmation(host, selected)["audit"]["feed_state"] == "parked"
    source = failed["source"]["plan_path"]
    with pytest.raises(ValueError):
        recovery.freeze_forward_recovery(
            host, source, stopped_confirmation=selected["path"]
        )
    close = recovery.freeze_forward_recovery(
        host, source, stopped_confirmation=selected["path"], close_feed_only=True
    )
    close_path = tmp_path / "stopped-close.json"
    _write(close_path, close)
    host.calls.clear()
    assert recovery.apply_forward_recovery(host, close_path)["status"] == "feed_closed"
    assert host.calls == ["close_stopped_feed"] and closed[0]
    with pytest.raises(ValueError, match="ATTEMPT_ALREADY_EXISTS"):
        recovery.apply_forward_recovery(host, close_path)
    fresh = recovery.freeze_forward_recovery(
        host, source, stopped_confirmation=selected["path"], feed_close_plan=close_path
    )
    assert fresh["closed_feed"]["plan_sha256"] == close["plan_sha256"]
    target = tmp_path / "stopped-after-feed-fresh.json"
    recovery._exclusive_json(target, fresh)
    host.verify_forward = lambda *args: {
        "continuous_identity": "matched",
        "calculation_ready": False,
        "intake": typed_intake(),
        "natural_acceptance": "pending",
    }
    host.forward_calendars = lambda *args: {
        "calendar_registration_only": True,
        "identity": "matched",
    }
    if interrupt:
        checkpoint = recovery._write

        def interrupt_after_intake(path, value):
            checkpoint(path, value)
            if value.get("phase") == "intake_complete":
                raise KeyboardInterrupt

        with monkeypatch.context() as patch:
            patch.setattr(recovery, "_write", interrupt_after_intake)
            with pytest.raises(KeyboardInterrupt):
                recovery.apply_forward_recovery(host, target)
        return host, target, fresh
    assert recovery.apply_forward_recovery(host, target)["status"] == "recovered"
    recovery._no_unresolved_recovery(host)
    assert (folder / "state.json").read_bytes() == original
    return host, failed, fresh


def test_stopped_post_feed_failure_closes_once_then_recovers_same_generation(
    tmp_path, monkeypatch
):
    recover_after_feed_failure(tmp_path, monkeypatch)


@pytest.mark.parametrize("original", (False, True))
def test_calendar_failure_preserves_unknown_then_uses_new_close_and_resume(
    tmp_path, monkeypatch, original
):
    recover_after_feed_failure(
        tmp_path, monkeypatch, calendars=True, original=original
    )


def test_calendar_confirmation_retains_source_closure_and_failure_bytes(tmp_path, monkeypatch):
    from app import runtime_stopped_recovery as stopped

    host, path, plan, _, _ = failed_after_feed(
        tmp_path, monkeypatch, calendars=True, original=True
    )
    folder = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    originals = {
        p: p.read_bytes()
        for p in host.directory.rglob("*.json")
        if p.name != "stopped-confirmation.json"
    }
    originals[path] = path.read_bytes()
    source = Path(plan["source"]["plan_path"])
    originals[source] = source.read_bytes()
    closure = Path(plan["original_close"]["plan_path"])
    originals[closure] = closure.read_bytes()
    calls = list(host.calls)
    result = stopped.reconcile_stopped(host, path)
    assert host.calls == calls  # No claim about historical calendar side effects.
    assert result["original_attempt_preserved"] and not result["recovery_started"]
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    value = stopped.read_confirmation(host, result["confirmation"])
    state = json.loads((folder / "state.json").read_bytes())
    assert state["phase"] == "outcome_unknown"
    assert state["error_type"] == "REDACTED"
    assert state["error_code"] == "COHORT_FORWARD_STEP_FAILED"
    assert set(state["effects"]) == {"consumers", "intake", "feed", "verified"}
    assert str(folder / "state.json") in value["files"]
    assert not (folder / "receipt.json").exists()


def old_recovered_and_new_calendar_failure(tmp_path, monkeypatch):
    from dataclasses import replace
    from app.runtime_bindings import BindingRegistry
    from tests.test_runtime_cohort import Host

    initialize = Host.__init__
    generation = [55]
    shared = tmp_path / "control"

    def shared_inventory(host, directory):
        initialize(host, directory)
        shared.mkdir(mode=0o700, exist_ok=True)
        host.directory = shared
        host.old = BindingRegistry(1, {
            name: replace(binding, generation=generation[0] - 1)
            for name, binding in host.old.services.items()
        })
        host.registry = host.old

    monkeypatch.setattr(Host, "__init__", shared_inventory)
    previous = tmp_path / "previous"
    previous.mkdir(mode=0o700)
    _, _, recovered = recover_after_feed_failure(previous, monkeypatch)
    assert recovered["new"]["services"]["live"]["generation"] == 55
    root = shared / "cohort-forward-recoveries" / recovered["plan_sha256"]
    retained = {p: p.read_bytes() for p in shared.rglob("*.json")
                if p.name != "cohort-release.json"}
    generation[0] = 56
    current = tmp_path / "current"
    current.mkdir(mode=0o700)
    host, path, failed, _, _ = failed_after_feed(
        current, monkeypatch, calendars=True, original=True
    )
    assert failed["new"]["services"]["live"]["generation"] == 56
    return host, path, root, retained


def test_old_successful_stopped_root_can_coexist_with_new_generation_failure(
    tmp_path, monkeypatch
):
    from app import runtime_stopped_recovery as stopped

    host, path, root, retained = old_recovered_and_new_calendar_failure(tmp_path, monkeypatch)
    selected = stopped.reconcile_stopped(host, path)["confirmation"]
    value = stopped.read_confirmation(host, selected)
    assert root.name not in value["attempts"]  # It has its own proven terminal receipt.
    assert all(p.read_bytes() == raw for p, raw in retained.items())


@pytest.mark.parametrize(
    "damage",
    ["receipt_sha", "missing_receipt", "receipt_kind", "effects", "source",
     "verified", "intake", "calendar", "failed_field", "extra_unknown"],
)
def test_old_successful_root_is_not_admitted_without_complete_terminal_proof(
    tmp_path, monkeypatch, damage
):
    from hashlib import sha256
    from app import runtime_stopped_recovery as stopped

    host, path, root, _ = old_recovered_and_new_calendar_failure(tmp_path, monkeypatch)
    state = json.loads((root / "state.json").read_bytes())
    if damage == "missing_receipt":
        (root / "receipt.json").unlink()
    elif damage == "receipt_sha":
        (root / "receipt.json").write_text("{}")
    elif damage == "receipt_kind":
        receipt = json.loads((root / "receipt.json").read_bytes())
        receipt["kind"] = "unproven"
        _write(root / "receipt.json", receipt)
        state["receipt_sha256"] = sha256((root / "receipt.json").read_bytes()).hexdigest()
        _write(root / "state.json", state)
    elif damage == "extra_unknown":
        other = root.parent / ("f" * 64)
        other.mkdir(mode=0o700)
        _write(other / "state.json", {"phase": "outcome_unknown"})
    else:
        if damage == "effects":
            state["effects"]["unproven"] = {}
        elif damage == "source":
            state["source"]["plan_sha256"] = "f" * 64
        elif damage == "verified":
            state["effects"]["verified"]["intake"]["schema_version"] = 1
        elif damage == "intake":
            state["effects"]["intake"]["after_sha256"] = "invalid"
        elif damage == "calendar":
            state["effects"]["calendars"] = {"registered": True}
        else:
            state["failed_stage"] = "calendars"
        _write(root / "state.json", state)
    with pytest.raises((ValueError, OSError)):
        stopped.reconcile_stopped(host, path)


@pytest.mark.parametrize(
    "damage",
    (
        "missing_verified", "intake_schema", "verified_schema", "intake_hash",
        "verified_hash", "extra_effect", "identity", "calculation", "natural",
        "extra_verified", "error_type", "error_code", "receipt",
        "protected", "new_protected",
    ),
)
def test_calendar_failure_rejects_unproven_completion_or_drift(
    tmp_path, monkeypatch, damage
):
    from app import runtime_stopped_recovery as stopped

    host, path, plan, audit, _ = failed_after_feed(
        tmp_path, monkeypatch, calendars=True, original=True
    )
    folder = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    state = json.loads((folder / "state.json").read_bytes())
    if damage in {"protected", "new_protected"}:
        audit[damage] = {"after-market-status.json": "new unexpected output"}
    elif damage == "receipt":
        _write(folder / "receipt.json", {})
    else:
        effects = state["effects"]
        if damage == "missing_verified":
            del effects["verified"]
        elif damage == "intake_schema":
            effects["intake"]["schema_version"] = 1
        elif damage == "verified_schema":
            effects["verified"]["intake"]["schema_version"] = 1
        elif damage == "intake_hash":
            effects["intake"]["before_sha256"] = "bad"
        elif damage == "verified_hash":
            effects["verified"]["intake"]["after_sha256"] = "bad"
        elif damage == "extra_effect":
            effects["calendars"] = {"identity": "matched"}
        elif damage == "identity":
            effects["verified"]["continuous_identity"] = "unknown"
        elif damage == "calculation":
            effects["verified"]["calculation_ready"] = True
        elif damage == "natural":
            effects["verified"]["natural_acceptance"] = "complete"
        elif damage == "extra_verified":
            effects["verified"]["extra"] = True
        elif damage == "error_type":
            state["error_type"] = "CohortError"
        else:
            state["error_code"] = "OTHER_UNKNOWN"
        _write(folder / "state.json", state)
    with pytest.raises(ValueError):
        stopped.reconcile_stopped(host, path)
    assert not (folder / "stopped-confirmation.json").exists()


@pytest.mark.parametrize("damage", ("false_exit", "extra_effect", "wrong_confirmation"))
def test_stopped_close_reader_rejects_resigned_unproven_receipts(
    tmp_path, monkeypatch, damage
):
    from app import runtime_stopped_recovery as stopped
    from hashlib import sha256

    host, failed, fresh = recover_after_feed_failure(tmp_path, monkeypatch)
    selected = fresh["stopped_confirmation"]
    close = fresh["closed_feed"]
    folder = host.directory / "cohort-forward-recoveries" / close["plan_sha256"]
    if damage == "wrong_confirmation":
        selected = failed["stopped_confirmation"]
    else:
        state = json.loads((folder / "state.json").read_text())
        if damage == "false_exit":
            receipt = json.loads((folder / "receipt.json").read_text())
            receipt["feed_close"]["observed_pids_exited"] = False
            state["effects"]["feed_stop"] = receipt["feed_close"]
            _write(folder / "receipt.json", receipt)
            state["receipt_sha256"] = sha256(
                (folder / "receipt.json").read_bytes()
            ).hexdigest()
        else:
            state["effects"]["install"] = {}
        _write(folder / "state.json", state)
    with pytest.raises(ValueError):
        stopped.read_closed_feed(host, close["plan_path"], fresh["source"], selected)


@pytest.mark.parametrize(
    "damage",
    ("unknown_effect", "bad_intake", "wrong_feed", "other_unknown", "false_exit"),
)
def test_stopped_post_feed_confirmation_rejects_unproven_frontier(
    tmp_path, monkeypatch, damage
):
    from app import runtime_stopped_recovery as stopped

    host, path, failed, audit, _ = failed_after_feed(tmp_path, monkeypatch)
    folder = host.directory / "cohort-forward-recoveries" / failed["plan_sha256"]
    if damage == "other_unknown":
        other = folder.parent / ("f" * 64)
        other.mkdir(mode=0o700)
        _write(other / "state.json", {"phase": "outcome_unknown"})
    elif damage == "false_exit":
        audit["feed_state"] = "absent"
    else:
        state = json.loads((folder / "state.json").read_text())
        if damage == "unknown_effect":
            state["effects"]["unproven"] = True
        elif damage == "bad_intake":
            state["effects"]["intake"]["remaining_count"] = 1
        else:
            state["effects"]["feed"]["label"] = "other"
        _write(folder / "state.json", state)
    with pytest.raises(ValueError):
        stopped.reconcile_stopped(host, path)


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
    complete_stopped_outputs(host)
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


@pytest.mark.parametrize("elapsed,expected", [(601, "recovered"), (1200, "deadline")])
def test_confirmed_stopped_can_recover_and_close_all_failed_attempts(tmp_path, elapsed, expected):
    from app.runtime_stopped_recovery import reconcile_stopped

    host, path, frozen, _ = failed_consumers(tmp_path)
    result = reconcile_stopped(host, path)
    source = frozen["source"]["plan_path"]
    plan = recovery.freeze_forward_recovery(
        host, source, stopped_confirmation=result["confirmation"]["path"]
    )
    assert plan["mode"] == "reconciled_stopped"
    assert plan["downtime_seconds"] == 1200
    assert "predecessor" not in plan
    target = tmp_path / "fresh.json"
    _write(target, plan)
    complete_stopped_outputs(host)
    tick = [0]
    host.monotonic = lambda: tick[0]
    verify = host.verify_forward

    def delayed_verify(*args):
        tick[0] += elapsed
        return verify(*args)

    host.verify_forward = delayed_verify
    if expected == "deadline":
        with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
            recovery.apply_forward_recovery(host, target)
        state = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"] / "state.json"
        assert json.loads(state.read_bytes())["error_code"] == "COHORT_FORWARD_DEADLINE_EXCEEDED"
        assert "calendars" not in host.calls
        return
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
    "failure", [None, "feed_reappeared", "owner_changed", "prefix_changed",
                "calendar_loaded", "calculation_pending"]
)
@pytest.mark.parametrize("feed_parked", (False, True))
def test_native_stopped_observer_pins_kernel_locks_and_rejects_drift(
    tmp_path, monkeypatch, failure, feed_parked
):
    from app import runtime_stopped_recovery as stopped
    import app.reference_trading.receiving_liveness as liveness
    import app.runtime_deployment as deployment
    from tests.test_runtime_cohort_forward_recovery import fixture, native

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    current.bindings = host.bindings
    names = recovery.continuous_services(host.bindings())
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
    current.definition_absent = lambda *args: failure != "calendar_loaded"
    current._feed_exited = lambda *args: failure != "feed_reappeared"
    pid_reads = [0]

    def feed_pids(*args):
        pid_reads[0] += 1
        return [40578] if failure == "feed_reappeared" and pid_reads[0] > 1 else [40577]

    current._feed_pids = feed_pids
    current._calculation_boundary = lambda: failure != "calculation_pending"
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
    monkeypatch.setattr(deployment, "recovery_progress_reached", lambda *args, **kwargs: True)
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
            stopped.observe_stopped(
                current,
                source,
                lambda: None,
                feed_pids=[40577],
                feed_parked=feed_parked,
            )
    else:
        result = stopped.observe_stopped(
            current, source, lambda: None, feed_pids=[40577], feed_parked=feed_parked
        )
        assert result["controls"] == {"fresh": "current"}
        if feed_parked:
            assert result["feed_state"] == "parked"
            assert "feed_exited_pids" not in result
    assert all(
        recovery.owner_lock_available(n, runtime_dir=current.directory) for n in names
    )


@pytest.mark.parametrize("case", ("success", "journal_drift", "owner_drift", "feed_cancelled", "feed_loaded", "calendar_partial", "calendar_window"))
def test_continue_from_intake_checkpoint(tmp_path, monkeypatch, case):
    from app import runtime_intake_continuation as continuation

    host, interrupted_path, interrupted = recover_after_feed_failure(
        tmp_path, monkeypatch, calendars=True, original=True, interrupt=True,
    )
    old_folder = host.directory / "cohort-forward-recoveries" / interrupted["plan_sha256"]
    state_path = old_folder / "state.json"
    original = state_path.read_bytes()
    owners = {"api": 123}
    monkeypatch.setattr(continuation, "observe", lambda *args: owners)
    host.recovery_window = lambda: interrupted["audit"]["window"]
    host.check_continuation_calendar_window = lambda *args: None
    plan = continuation.freeze(host, interrupted_path)
    target = tmp_path / "continuation.json"
    _write(target, plan)
    host.calls.clear()

    def feed(*args, record):
        record("feed_cancel_intent")
        host.calls.append("feed_cancel")
        if case == "feed_cancelled":
            raise KeyboardInterrupt
        record("feed_cancel_readback")
        record("feed_start_intent")
        host.calls.append("feed_start")
        record("feed_label_loaded")
        if case == "feed_loaded":
            raise KeyboardInterrupt
        return {"bootstrapped": True, "label": "com.guiyi.quant-market-feed"}

    host.resume_feed = feed
    def calendars(*args, record):
        for name in recovery.CALENDARS:
            if not plan["new"]["services"][name]["enabled"]:
                continue
            stage = f"calendar_{name.replace('-', '_')}"
            record(stage + "_intent")
            record(stage + "_readback")
            if case == "calendar_partial":
                raise KeyboardInterrupt
        return {"calendar_registration_only": True, "identity": "matched"}

    host.forward_calendars = calendars
    if case == "journal_drift":
        state_path.write_bytes(original + b" ")
    if case == "owner_drift":
        owners = {"api": 456}
    if case == "calendar_window":
        def blocked(*args):
            raise ValueError("BOOTSTRAP_RECOVERY_CALENDAR_DUE")
        host.check_continuation_calendar_window = blocked
    if case in {"journal_drift", "owner_drift", "calendar_window"}:
        with pytest.raises(ValueError):
            recovery.apply_forward_recovery(host, target)
        assert host.calls == []
        return
    if case in {"feed_cancelled", "feed_loaded", "calendar_partial"}:
        with pytest.raises(KeyboardInterrupt):
            recovery.apply_forward_recovery(host, target)
        new_state = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"] / "state.json"
        actions = json.loads(new_state.read_bytes())["actions"]
        assert actions[0] == "feed_cancel_intent"
        assert actions[-1] == {
            "feed_cancelled": "feed_cancel_intent",
            "feed_loaded": "feed_label_loaded",
            "calendar_partial": "calendar_after_market_readback",
        }[case]
        with pytest.raises(ValueError, match="ATTEMPT_ALREADY_EXISTS"):
            recovery.apply_forward_recovery(host, target)
        return
    assert recovery.apply_forward_recovery(host, target)["status"] == "recovered"
    assert host.calls == ["feed_cancel", "feed_start"]
    assert state_path.read_bytes() == original
    recovery._no_unresolved_recovery(host)
