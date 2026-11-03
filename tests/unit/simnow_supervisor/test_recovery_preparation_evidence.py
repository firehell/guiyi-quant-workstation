"""Offline recovery evidence must not become permission to trade or retry."""

import hashlib
import json
import sqlite3

import pytest

from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.inventory import read_snapshot
from guiyi_quant.simnow_execution.native_portfolio import session_diagnostic
from guiyi_quant.simnow_execution.supervisor import Supervisor
from test_trade_end_to_end import Driver, Gateway, seeded_account


def protected(folder):
    return {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in ("account.sqlite", "dispatch.sqlite")
    }


def history(folder):
    db = sqlite3.connect(
        (folder / "native-evidence.sqlite").as_uri() + "?mode=ro", uri=True
    )
    try:
        return db.execute(
            "SELECT source,payload FROM snapshots ORDER BY rowid"
        ).fetchall()
    finally:
        db.close()


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"front_id": True},
        {
            "front_id": 1,
            "session_id": -1,
            "max_order_ref": 0,
            "secret": "private-password",
        },
    ],
)
def test_session_classification_is_bounded_and_contains_no_values(value):
    result = session_diagnostic(value)
    assert set(result) == {"schema", "exact_fields", "fields"}
    assert set(result["fields"]) == {"front_id", "session_id", "max_order_ref"}
    assert all(
        type(v) is bool for flags in result["fields"].values() for v in flags.values()
    )
    assert "private-password" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "case,stage,error",
    [
        ("session", "SESSION_CONSTRUCTION", "NATIVE_SESSION_ID_INVALID"),
        ("adapter", "ADAPTER_CONSTRUCTION", "INVESTOR_FORMAT_INVALID"),
        ("correlation", "NATIVE_SNAPSHOT_CORRELATION", "RECOVERY_ERROR_UNCLASSIFIED"),
    ],
)
def test_failed_preparation_retains_native_source_and_original_account_without_retry(
    tmp_path, monkeypatch, case, stage, error
):
    from guiyi_quant.simnow_execution.adapter import Adapter

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = True
    before, originals = protected(folder), history(folder)
    gateway = Gateway(clock)
    gateway.inventory_diagnostics = lambda: {"status": "READ_ONLY_COMPLETE"}
    if case == "session":
        gateway.native_session["session_id"] = 0
    if case == "correlation":

        def fail(*args):
            raise RuntimeError("private-password")

        monkeypatch.setattr(Adapter, "correlate_snapshot", fail)
    drivers = []

    class InvalidDriver(Driver):
        def adapter(self, *args, **kwargs):
            if case == "adapter":
                self.gateway.user = "private-password"
            return super().adapter(*args, **kwargs)

    def factory(*args):
        driver = InvalidDriver(*args, clock, gateway)
        drivers.append(driver)
        return driver

    runtime = Supervisor(
        settings, ("RB", "JM"), market, factory, clock=clock.now, sleep=clock.sleep
    )
    runtime.run(max_cycles=2)
    failure = json.loads(next(folder.glob("failure-*.json")).read_text())
    assert failure["diagnostic"]["stage"] == stage
    assert failure["diagnostic"]["recovery_error_code"] == error
    assert "private-password" not in json.dumps(failure)
    assert len(drivers) == 1 and runtime.account_takeover_pending
    assert protected(folder) == before
    after = history(folder)
    assert after[: len(originals)] == originals and len(after) == len(originals) + 2
    assert after[-1][0] == read_snapshot(drivers[0].report).source_id
    assert not {"insert", "cancel"} & set(gateway.calls)
    assert "confirm" in gateway.calls
    if case == "session":
        flags = failure["diagnostic"]["adapter_preparation"]["fields"]["session_id"]
        assert (
            flags["integer"]
            and flags["signed_int32"]
            and flags["nonnegative"]
            and not flags["positive"]
        )
    with sqlite3.connect(folder / "signals.sqlite") as db:
        assert db.execute("SELECT count FROM attempts").fetchall() == [(1,)]
        assert db.execute("SELECT code FROM blocks").fetchall() == [
            ("CONTINUOUS_RECOVERY_REQUIRED",)
        ]


@pytest.mark.parametrize("kind", ["validation", "conflict", "write"])
def test_unproven_or_unretained_snapshot_stops_before_settlement_and_adapter(
    tmp_path, monkeypatch, kind
):
    from guiyi_quant.simnow_execution import strategy_native

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = True
    before, originals = protected(folder), history(folder)
    gateway = Gateway(clock)
    gateway.inventory_diagnostics = lambda: {"status": "READ_ONLY_COMPLETE"}
    calls = []
    if kind == "validation":

        def reject(*args):
            calls.append("validation")
            raise ValueError("NATIVE_EVENT_SESSION_UNPROVEN")

        monkeypatch.setattr(strategy_native, "validate_strategy_events", reject)
    else:

        def reject(*args):
            calls.append("retention")
            if kind == "conflict":
                raise ValueError("NATIVE_EVIDENCE_CONFLICT")
            raise OSError("private-password")

        monkeypatch.setattr(Evidence, "append", reject)
    drivers = []

    def factory(*args):
        value = Driver(*args, clock, gateway)
        drivers.append(value)
        return value

    runtime = Supervisor(
        settings, ("RB", "JM"), market, factory, clock=clock.now, sleep=clock.sleep
    )
    runtime.run(max_cycles=2)
    assert len(drivers) == 1 and len(calls) == 1
    assert protected(folder) == before and history(folder) == originals
    assert gateway.calls == [] and runtime.account_takeover_pending
    failure = json.loads(next(folder.glob("failure-*.json")).read_text())
    assert failure["diagnostic"]["recovery_stage"] == (
        "RECOVERY_SNAPSHOT_VALIDATION"
        if kind == "validation"
        else "RECOVERY_SNAPSHOT_RETENTION"
    )
    assert "private-password" not in json.dumps(failure)


def test_successful_reconciliation_reuses_retained_source_once(tmp_path, monkeypatch):
    from guiyi_quant import htdy_account_execution as a

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = True
    originals = history(folder)
    from guiyi_quant.simnow_execution.host import Host

    reconcile = Host.reconcile
    witnessed = []

    def checked(host, report, *args, **kwargs):
        source = read_snapshot(report).source_id
        before = history(folder)
        result = reconcile(host, report, *args, **kwargs)
        witnessed.append(
            (any(row[0] == source for row in before), len(before), len(history(folder)))
        )
        return result

    monkeypatch.setattr(Host, "reconcile", checked)
    complete = Host.complete_takeover
    completed = []

    def record_complete(host, *args):
        result = complete(host, *args)
        completed.append(not host.account_takeover_pending)
        return result

    monkeypatch.setattr(Host, "complete_takeover", record_complete)
    runtime = Supervisor(
        settings,
        ("RB", "JM"),
        market,
        lambda *args: Driver(*args, clock),
        clock=clock.now,
        sleep=clock.sleep,
    )
    runtime.run(max_cycles=1)
    after = history(folder)
    assert witnessed[0] == (True, len(originals) + 2, len(originals) + 2)
    assert after[: len(originals)] == originals
    assert len(after) == len({row[0] for row in after})
    assert completed == [True]
    assert runtime.account_takeover_pending  # Disconnect restores the barrier.
    final = a.LocalStore.inspect(folder / "account.sqlite")
    assert not final.orders and not final.fills and not final.positions
