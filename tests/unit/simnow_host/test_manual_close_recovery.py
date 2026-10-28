"""Management budget and capability fences for an already-claimed manual order."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace as N

import pytest

from guiyi_quant import htdy_account_execution as a
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.inventory import Snapshot, native_hash
from guiyi_quant.simnow_execution.manual_close_recovery import (
    claim_close_only,
    validate_events,
)
from guiyi_quant.simnow_execution.host import Host

T = datetime(2026, 10, 27, 5, 51, tzinfo=UTC)
ID = "manual:1eea688e-3c2d-4091-828a-216a6368b9bf"
PREFIX = ID.replace(":", "-")
ACCOUNT = "a" * 64


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    path.chmod(0o600)


def fixture(folder, monkeypatch):
    for name in ("account.sqlite", "signals.sqlite"):
        (folder / name).write_bytes(b"unchanged")
        (folder / name).chmod(0o600)
    conn = sqlite3.connect(folder / "dispatch.sqlite")
    conn.executescript(
        "CREATE TABLE actions(order_id,kind,payload);CREATE TABLE events(payload);"
    )
    conn.execute(
        "INSERT INTO actions VALUES(?,?,?)",
        (
            "open",
            "SUBMIT",
            json.dumps(
                dict(contract="RB2701", side="BUY", offset="0", account_id=ACCOUNT)
            ),
        ),
    )
    conn.execute(
        "INSERT INTO events VALUES(?)",
        (
            json.dumps(
                dict(
                    kind="trade", order_id="open", trade_id="trade", system_id="system"
                )
            ),
        ),
    )
    conn.commit()
    conn.close()
    (folder / "dispatch.sqlite").chmod(0o600)
    data = dict(funds=[], positions=[], orders=[], trades=[])
    source = "ctp-inventory:20261027:" + native_hash(
        (ACCOUNT, "20261027", data, T.isoformat())
    )
    evidence = Evidence(folder / "native-evidence.sqlite", ACCOUNT)
    evidence.append(Snapshot(ACCOUNT, "20261027", T, T, source, json.dumps(data)))
    evidence.close()
    begin = a.ManualBeginV1(
        ID, "RB", "RB2701", T + timedelta(seconds=1), T + timedelta(seconds=180)
    )
    state = N(
        account_id=ACCOUNT,
        audit=(N(command=begin),),
        orders=(
            N(
                offset="OPEN",
                side="BUY",
                order_id="open",
                signal_id=ID,
                contract="RB2701",
                quantity=1,
                created_at=T + timedelta(seconds=2),
            ),
        ),
    )
    monkeypatch.setattr(a.LocalStore, "inspect", lambda _: state)
    for suffix in ("-login.json", "-diagnostic-login.json", "-recovery-login.json"):
        save(
            folder / (PREFIX + suffix),
            dict(
                test_id=ID,
                account_id=ACCOUNT,
                max_connections=1,
                connections=1,
                cumulative_manual_connections_after_claim=2,
                cumulative_manual_connections=3,
            ),
        )
    plan = dict(
        schema="simnow_manual_close_only_v1",
        test_id=ID,
        account_id=ACCOUNT,
        expires_at=(T + timedelta(minutes=40)).isoformat(),
        preimages={
            n: sha256((folder / n).read_bytes()).hexdigest()
            for n in ("account.sqlite", "dispatch.sqlite", "signals.sqlite")
        },
        order_id="open",
        contract="RB2701",
        trade_id="trade",
        system_id="system",
        baseline_source_id=source,
        max_connections=1,
        max_total_connections=4,
    )
    save(folder / (PREFIX + "-close-only-plan.json"), plan)
    return plan, state


def test_close_recovery_has_its_own_once_only_budget_and_preserves_old_files(
    tmp_path, monkeypatch
):
    _, _ = fixture(tmp_path, monkeypatch)
    originals = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    baseline, plan = claim_close_only(tmp_path, ID, ACCOUNT, T + timedelta(minutes=20))
    assert baseline.at == T and plan["order_id"] == "open"
    assert all(
        (tmp_path / name).read_bytes() == value for name, value in originals.items()
    )
    with pytest.raises(FileExistsError):
        claim_close_only(tmp_path, ID, ACCOUNT, T + timedelta(minutes=20))
    claim = json.loads((tmp_path / (PREFIX + "-close-only-login.json")).read_text())
    assert claim["opening_enabled"] is False and claim["max_connections"] == 1


@pytest.mark.parametrize(
    "bad", ["order", "side", "hash", "trade", "expired", "account"]
)
def test_management_guard_rejects_scope_or_identity_drift(tmp_path, monkeypatch, bad):
    plan, state = fixture(tmp_path, monkeypatch)
    if bad == "order":
        state.orders[0].order_id = "foreign"
    elif bad == "side":
        state.orders[0].side = "SELL"
    elif bad == "hash":
        (tmp_path / "signals.sqlite").write_bytes(b"drift")
    elif bad == "trade":
        plan["system_id"] = "different"
    elif bad == "expired":
        plan["expires_at"] = T.isoformat()
    else:
        plan["account_id"] = "b" * 64
    save(tmp_path / (PREFIX + "-close-only-plan.json"), plan)
    with pytest.raises(ValueError):
        claim_close_only(tmp_path, ID, ACCOUNT, T + timedelta(minutes=20))
    assert not (tmp_path / (PREFIX + "-close-only-login.json")).exists()


def test_raw_native_event_times_need_authoritative_session_without_local_clock_comparison():
    calls = []
    market = N(
        authority=lambda *args: (
            calls.append(args) or N(contract="RB2701", session=N(can_trade=True))
        )
    )
    snapshot = N(
        trading_day="20261027",
        data=dict(
            orders=[dict(InsertDate="20261027", InsertTime="13:51:51")],
            trades=[dict(TradeDate="20261027", TradeTime="13:51:51")],
        ),
    )
    validate_events(market, snapshot, "RB2701")
    assert len(calls) == 2 and calls[0][2].hour == 13
    market.authority = lambda *args: N(contract="RB2701", session=N(can_trade=False))
    with pytest.raises(ValueError, match="SESSION"):
        validate_events(market, snapshot, "RB2701")


def test_host_close_only_rejects_open_before_any_dispatch(monkeypatch):
    state = N(account_id=ACCOUNT, phase="READY", products=(N(product="RB"),), orders=())
    host = Host(
        N(current=lambda: state),
        N(),
        N(snapshots=lambda: ()),
        N(),
        "RB",
        run_id=ID,
        deadline=T,
        manual_test_id=ID,
        close_only=True,
    )
    effect = N(kind="SUBMIT", order=N(product="RB", offset="OPEN"))
    with pytest.raises(ValueError, match="OPEN_FORBIDDEN"):
        host.submit_effects((effect,), (), (), T)


def test_changed_initial_readback_can_wait_on_same_connection_but_timeout_cannot():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "management_reader",
        Path(__file__).parents[3] / "scripts/broker/simnow_manual_roundtrip.py",
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    calls = []

    def snapshot():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("NATIVE_SNAPSHOT_CHANGED")
        return "verified"

    driver = N(snapshot=snapshot, transport_failed=False)
    assert (
        runner.initial_snapshot(driver, lambda: T, lambda _: None, True) == "verified"
    )
    assert len(calls) == 3
    driver.snapshot = lambda: (_ for _ in ()).throw(ValueError("QUERY_TIMEOUT"))
    with pytest.raises(ValueError, match="QUERY_TIMEOUT"):
        runner.initial_snapshot(driver, lambda: T, lambda _: None, True)


def test_close_only_status_preserves_both_preceding_failures(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "management_writer",
        Path(__file__).parents[3] / "scripts/broker/simnow_manual_roundtrip.py",
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    for suffix in ("-status.json", "-recovery-status.json"):
        (tmp_path / (PREFIX + suffix)).write_bytes(b"old failure")
    assert runner.write_status(tmp_path, ID, dict(stage="CLOSE_ONLY"), close_only=True)
    assert all(
        (tmp_path / (PREFIX + s)).read_bytes() == b"old failure"
        for s in ("-status.json", "-recovery-status.json")
    )
