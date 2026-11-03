"""Offline native recovery: successful settlement must not age takeover evidence."""

from dataclasses import replace
from datetime import timedelta
import json
import sqlite3

import pytest

from guiyi_quant.simnow_execution.supervisor import Supervisor
from test_trade_end_to_end import Driver, Gateway, seeded_account


def run_case(tmp_path, *, damage=None, monkeypatch=None, mode="trade", pending=True):
    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = pending
    settings.mode = mode
    gateway = Gateway(clock)
    gateway.inventory_diagnostics = lambda: {}
    query = gateway.query
    attached = []
    attach = gateway.attach

    def slow_settlement(kind, *args, **kwargs):
        if kind in {"settlement", "confirm"}:
            # Gateway pacing plus a successful response inside its 15s wait.
            clock.advance(1.1 + 14.5)
        return query(kind, *args, **kwargs)

    def record_attach(adapter, snapshot):
        assert adapter._correlated_snapshot[0] is snapshot
        assert adapter.session.at >= snapshot.at
        with sqlite3.connect(folder / "native-evidence.sqlite") as db:
            assert db.execute(
                "SELECT 1 FROM snapshots WHERE source=?", (snapshot.source_id,)
            ).fetchone()
        attached.append(snapshot)
        attach(adapter, snapshot)

    gateway.query, gateway.attach = slow_settlement, record_attach
    if damage == "strategy_validation":
        from guiyi_quant.simnow_execution import strategy_native

        validate = strategy_native.validate_strategy_events

        def reject_new_snapshot(snapshot, *args):
            validate(snapshot, *args)
            if gateway.confirmed:
                raise ValueError("NATIVE_EVENT_SESSION_UNPROVEN")

        monkeypatch.setattr(
            strategy_native, "validate_strategy_events", reject_new_snapshot
        )
    if damage == "retention_failed":
        from guiyi_quant.simnow_execution.evidence import Evidence

        append = Evidence.append

        def reject_retention(evidence, snapshot):
            if gateway.confirmed:
                raise ValueError("NATIVE_EVIDENCE_CONFLICT")
            return append(evidence, snapshot)

        monkeypatch.setattr(Evidence, "append", reject_retention)
    snapshots, adapter_inputs = [], []
    unstable_once = [damage == "refresh_changed_once"]

    class TrackedDriver(Driver):
        def connect(self):
            gateway.calls.append("fixture_connect")
            return super().connect()

        def snapshot(self):
            if gateway.confirmed and not attached:
                if unstable_once[0]:
                    unstable_once[0] = False
                    raise ValueError("NATIVE_SNAPSHOT_CHANGED")
                if damage == "refresh_failed":
                    raise ValueError("NATIVE_STABLE_SNAPSHOT_REQUIRED")
                if damage == "unknown_position":
                    gateway.positions = {"rb2701": (1, 100)}
            result = super().snapshot()
            if gateway.confirmed and not attached:
                if damage == "day_drift":
                    result = replace(result, trading_day="20261028")
                elif damage == "account_drift":
                    result = replace(result, account_id="f" * 64)
            snapshots.append(result)
            return result

        def adapter(self, store, journal, snapshot, *args, **kwargs):
            adapter_inputs.append(snapshot)
            return super().adapter(store, journal, snapshot, *args, **kwargs)

    runtime = Supervisor(
        settings,
        ("RB", "JM"),
        market,
        lambda *args: TrackedDriver(*args, clock, gateway),
        clock=clock.now,
        sleep=lambda _: None,
    )
    accepted = []
    publish = runtime.status

    def capture(code, **kwargs):
        if code in {"TRADING", "MANAGING_EXISTING_ONLY"}:
            accepted.append(
                (
                    runtime.account_takeover_pending,
                    runtime.host.account_takeover_pending,
                    runtime.host.adapter.account_takeover_pending,
                    runtime.store.current().readback_valid,
                )
            )
        publish(code, **kwargs)

    runtime.status = capture
    runtime.run(max_cycles=3 if damage else 1)
    return runtime, folder, gateway, snapshots, adapter_inputs, attached, accepted


@pytest.mark.parametrize("mode", ["trade", "manage"])
@pytest.mark.parametrize("pending", [True, False])
def test_successful_slow_settlement_refreshes_before_session_and_attach(
    tmp_path, mode, pending
):
    _, folder, gateway, snapshots, adapter_inputs, attached, accepted = run_case(
        tmp_path, mode=mode, pending=pending
    )
    assert accepted == [(False, False, False, True)]
    assert gateway.calls.count("settlement") == gateway.calls.count("confirm") == 1
    assert gateway.confirmed
    assert not {"insert", "cancel"} & set(gateway.calls)
    assert len(snapshots) == 4  # Initial, ownership, post-settlement, ordinary cycle.
    fresh = snapshots[2]
    assert adapter_inputs == attached == [fresh]
    assert attached[0].at > snapshots[1].at + timedelta(seconds=30)
    with sqlite3.connect(folder / "native-evidence.sqlite") as db:
        assert db.execute(
            "SELECT 1 FROM snapshots WHERE source=?", (fresh.source_id,)
        ).fetchone()
    assert not list(folder.glob("failure-*.json"))


@pytest.mark.parametrize(
    "damage,error",
    [
        ("refresh_failed", "RECOVERY_ERROR_UNCLASSIFIED"),
        ("unknown_position", "UNEXPLAINED_NATIVE_POSITION"),
        ("strategy_validation", "NATIVE_EVENT_SESSION_UNPROVEN"),
        ("retention_failed", "NATIVE_EVIDENCE_CONFLICT"),
        ("day_drift", "NATIVE_SESSION_IDENTITY_MISMATCH"),
        ("account_drift", "NATIVE_SESSION_IDENTITY_MISMATCH"),
    ],
)
def test_post_settlement_refresh_failure_never_attaches_or_clears_pending(
    tmp_path, monkeypatch, damage, error
):
    runtime, folder, gateway, _, adapter_inputs, attached, accepted = run_case(
        tmp_path, damage=damage, monkeypatch=monkeypatch
    )
    assert not accepted and runtime.account_takeover_pending
    assert not adapter_inputs and not attached
    assert gateway.calls.count("settlement") == gateway.calls.count("confirm") == 1
    assert not {"insert", "cancel"} & set(gateway.calls)
    failure = json.loads(next(folder.glob("failure-*.json")).read_bytes())
    assert failure["diagnostic"]["recovery_error_code"] == error
    with sqlite3.connect(folder / "signals.sqlite") as db:
        assert db.execute(
            "SELECT code FROM blocks WHERE day='20261027'"
        ).fetchone() == (
            "NATIVE_SESSION_IDENTITY_MISMATCH"
            if error == "NATIVE_SESSION_IDENTITY_MISMATCH"
            else "CONTINUOUS_RECOVERY_REQUIRED",
        )


def test_unstable_post_settlement_snapshot_reuses_login_without_reconfirming(tmp_path):
    _, folder, gateway, _, _, attached, accepted = run_case(
        tmp_path, damage="refresh_changed_once"
    )
    assert accepted and all(row == (False, False, False, True) for row in accepted)
    assert gateway.calls.count("fixture_connect") == 1
    assert gateway.calls.count("settlement") == gateway.calls.count("confirm") == 1
    assert len(attached) == 1
    assert not {"insert", "cancel"} & set(gateway.calls)
    assert not list(folder.glob("failure-*.json"))
