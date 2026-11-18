"""Offline account facts exercise reconciliation; no SDK or production writes."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from guiyi_quant.htdy_account_execution import model as m, codec
from guiyi_quant.htdy_account_execution.store import StoreError
from guiyi_quant.htdy_execution import OrderReport
from guiyi_quant.tq_simulation.controller import Controller
from guiyi_quant.tq_simulation.journal import digest
from guiyi_quant.tq_simulation.manual_reconcile import load_evidence, prepare
from guiyi_quant.tq_simulation.runtime import write_private
from test_execution import A, T, Transport, fact, snapshot

PRODUCTS = ("AG", "AU", "FG", "I", "PB", "RB", "SN", "CU")
APPROVAL = "owner-approved-manual-closes"


def seal(value):
    value["snapshot_id"] = digest({
        k: v for k, v in value.items() if k not in {"snapshot_id", "observed_at"}
    })
    return value


def ns(at):
    return int(at.timestamp()) * 1000000000 + at.microsecond * 1000


def fixture(tmp_path):
    account = tmp_path / "account"
    account.mkdir(mode=0o700)
    c = Controller(account, A, PRODUCTS, Transport())
    for p in PRODUCTS:
        c.bind_symbol("SHFE." + p.lower() + "2701", p, p + "2701")
    c.bootstrap(snapshot(T), T)
    for i, p in enumerate(PRODUCTS):
        at = T + timedelta(seconds=i + 1)
        c.owner(p, p + "2701", at, "owner:" + p)
        at += timedelta(seconds=1)
        c.signal(m.Signal("signal:" + p, p, p + "2701", at - timedelta(seconds=1),
                          at, None, ("buy",), "b" * 64), processed_at=at)
    positions, reports, trades = [], [], []
    for i in range(8):
        at = T + timedelta(seconds=10 + 3 * i)
        inputs = tuple(m.TqKqExecutionInput(
            replace(fact(at).instrument, product=p, contract=p + "2701"),
            replace(fact(at).session, contract=p + "2701"),
            replace(fact(at).quote, contract=p + "2701"),
        ) for p in PRODUCTS)
        tx = c.store.execute("open:" + str(i), m.TqKqTick(at, inputs, True))
        assert len(tx.effects) == 1
        o = tx.effects[0].order
        c.journal.claim("SUBMIT", o.order_id, {"offset": "OPEN", "price": "1000"}, at)
        fill_at = at + timedelta(seconds=1)
        fill = m.TqKqFill("tq-trade:open-" + o.product, o.order_id, A, o.contract,
                         fill_at, fill_at, o.price, None, 1, "open-" + o.product,
                         "open-native-" + o.product, "f" * 64)
        c.store.execute("open-fill:" + o.product, fill)
        positions.append(dict(symbol="SHFE." + o.contract.lower(), pos_long_his=1,
                              pos_long_today=0, pos_short_his=0, pos_short_today=0))
        reports.append(OrderReport(o.order_id, "FILLED"))
        trades.append(fill.trade_id)
        rb = c.readback(snapshot(at + timedelta(seconds=2)), at + timedelta(seconds=2))
        rb = replace(rb, snapshot=replace(rb.snapshot, positions=c.store.current().positions,
                                         orders=tuple(reports)),
                     used_margin=fact(at).instrument.margin_per_lot * (i + 1),
                     confirmed_trade_ids=tuple(trades))
        c.store.execute("open-readback:" + str(i), rb)

    folder = tmp_path / "evidence"
    folder.mkdir(mode=0o700)
    before = seal(snapshot(T + timedelta(seconds=60), positions=positions))
    write_private(folder / "before.json", before)
    native_orders, native_trades = [], []
    for index, p in enumerate(PRODUCTS[:-1], 1):
        created = T + timedelta(seconds=60 + index)
        native = dict(order_id="manual-" + p, exchange_order_id="exchange-" + p,
                      exchange_id="SHFE", instrument_id=(p + "2701").lower(),
                      direction="SELL", offset="CLOSE", volume_orign=1, volume_left=0,
                      status="FINISHED", is_error=False, is_dead=True, is_online=False,
                      insert_date_time=ns(created), limit_price="999", price_type="LIMIT",
                      state="FILLED")
        trade = dict(order_id=native["order_id"], trade_id="close-" + p,
                     exchange_id="SHFE", instrument_id=native["instrument_id"],
                     direction="SELL", offset="CLOSE", volume=1, price="1000",
                     trade_date_time=ns(created + timedelta(microseconds=100)))
        intent = dict(order_id=native["order_id"], symbol="SHFE." + native["instrument_id"],
                      side="SELL", offset="CLOSE", quantity=1, price="999")
        native_orders.append(native)
        native_trades.append(trade)
        positions = [v for v in positions if v["symbol"] != intent["symbol"]]
        current = seal(snapshot(created + timedelta(seconds=1), positions=positions,
                                orders=deepcopy(native_orders), trades=deepcopy(native_trades)))
        current["account"]["margin"] = "1000"
        seal(current)
        write_private(folder / f"{index:02d}-intent.json", intent)
        write_private(folder / f"{index:02d}-readback.json", current)
    write_private(folder / "after.json", current)
    at = T + timedelta(minutes=2)
    fresh = {**deepcopy(current), "observed_at": at.isoformat()}
    return c, folder, fresh, at


def test_seven_atomic_closes_preserve_history_cu_and_restart_mapping(tmp_path):
    c, folder, fresh, at = fixture(tmp_path)
    before = c.store.current()
    commands = c.store._conn.execute("SELECT * FROM commands ORDER BY sequence").fetchall()
    claims = c.journal.db.execute("SELECT * FROM claims ORDER BY rowid").fetchall()
    key, command, duplicate = prepare(c, folder, fresh, at, APPROVAL)
    assert not duplicate and len(command.fills) == 7
    assert c.store.current() == before  # dry-run has no account mutation
    tx = c.store.execute(key, command, manual_close_proof=lambda _: True)
    assert not tx.effects
    assert tx.state.positions == (m.Position("CU", "CU2701", 1),)
    assert tx.state.phase == "RECOVERY_REQUIRED" and not tx.state.readback_valid
    assert tx.state.initial_readback == before.initial_readback
    assert tx.state.orders[:8] == before.orders
    assert tx.state.fills[:8] == before.fills
    assert len(tx.state.fills) == 15 and all(f.fee is None for f in command.fills)
    assert c.store._conn.execute("SELECT * FROM commands ORDER BY sequence").fetchall()[:-1] == commands
    assert c.journal.db.execute("SELECT * FROM claims ORDER BY rowid").fetchall() == claims
    c._manual_orders_cache = None
    updated = {**fresh, "observed_at": (at + timedelta(seconds=1)).isoformat()}
    key2, same, duplicate = prepare(c, folder, updated, at + timedelta(seconds=1), APPROVAL)
    assert duplicate and same == command and key2 == key
    assert c.store.execute(key2, same).duplicate
    assert codec.load(codec.checkpoint(tx.state)) == tx.state
    root = c.root
    c.close()
    c = Controller(root, A, PRODUCTS, Transport())
    assert len(c.manual_orders()) == 7
    assert len(c.native_mappings()) == 15
    rb = c.synchronize(updated, at + timedelta(seconds=1))
    proofs = tuple(m.RecoveryInput(p, p + "2701", 1 if p == "CU" else 0,
                                  T + timedelta(seconds=90), "recovery:" + p) for p in PRODUCTS)
    c.recover(rb, proofs)
    assert c.store.current().phase == "READY"
    assert all(p.opening_consumed and p.wait_after == rb.at for p in c.store.current().products)
    assert c.gateway.calls == []
    c.close()


@pytest.mark.parametrize("failure", ["missing_proof", "false_proof", "position_drift", "commit_failure"])
def test_batch_failure_keeps_every_close_uncommitted(tmp_path, monkeypatch, failure):
    c, folder, fresh, at = fixture(tmp_path)
    key, cmd, _ = prepare(c, folder, fresh, at, APPROVAL)
    original = c.store.current()
    if failure == "position_drift":
        cmd = replace(cmd, readback=replace(cmd.readback, snapshot=replace(cmd.readback.snapshot,
                           positions=(m.Position("CU", "CU2701", -1),))))
    if failure == "commit_failure":
        monkeypatch.setattr(c.store, "_commit", lambda: (_ for _ in ()).throw(OSError("fixture")))
    with pytest.raises((ValueError, StoreError)):
        c.store.execute(key, cmd, manual_close_proof=(None if failure == "missing_proof"
                        else lambda _: failure != "false_proof"))
    if failure == "commit_failure":
        from guiyi_quant.htdy_account_execution.store import LocalStore
        actual = LocalStore.inspect(c.root / "account.sqlite")
    else:
        actual = c.store.current()
    assert actual.positions == original.positions and actual.fills == original.fills
    assert actual.audit == original.audit
    c.close()


@pytest.mark.parametrize("drift", ["extra_trade", "position", "side", "price", "old_snapshot"])
def test_unapproved_or_changed_native_facts_never_import(tmp_path, drift):
    c, folder, fresh, at = fixture(tmp_path)
    if drift == "extra_trade":
        fresh["trades"].append({**fresh["trades"][0], "trade_id": "external-unapproved"})
    elif drift == "position":
        fresh["positions"][0]["pos_long_his"] = 2
    elif drift == "side":
        fresh["trades"][0]["direction"] = "BUY"
    elif drift == "price":
        fresh["orders"][0]["limit_price"] = "1"
    elif drift == "old_snapshot":
        fresh["observed_at"] = (at - timedelta(seconds=11)).isoformat()
    seal(fresh)
    before = c.store.current()
    with pytest.raises(ValueError):
        prepare(c, folder, fresh, at, APPROVAL)
    assert c.store.current() == before
    c.close()


def test_evidence_digest_and_permissions_fail_closed(tmp_path):
    c, folder, _, _ = fixture(tmp_path)
    path = folder / "01-readback.json"
    value = json.loads(path.read_bytes())
    value["trades"][0]["price"] = "2"
    write_private(path, value)
    with pytest.raises(ValueError, match="EVIDENCE_UNPROVEN"):
        load_evidence(folder)
    c.close()


def test_already_committed_is_noop_after_native_history_or_positions_change(tmp_path):
    c, folder, fresh, at = fixture(tmp_path)
    key, command, _ = prepare(c, folder, fresh, at, APPROVAL)
    c.store.execute(key, command, manual_close_proof=lambda _: True)
    # A later trading day need not return yesterday's orders or the same holdings.
    later = seal(snapshot(at + timedelta(days=1)))
    same_key, same_command, duplicate = prepare(c, folder, later, at + timedelta(days=1), APPROVAL)
    assert (same_key, same_command, duplicate) == (key, command, True)
    with pytest.raises(ValueError, match="EVIDENCE_UNPROVEN"):
        prepare(c, folder, later, at + timedelta(days=1), "different-owner-approval")
    c.close()


def host(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from datetime import datetime
    from guiyi_quant.tq_simulation import manual_reconcile, runtime, cli, worker, credentials, gateway

    c, evidence, fresh, at = fixture(tmp_path)
    c.close()
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "accounts").mkdir(mode=0o700)
    (tmp_path / "account").rename(base / "accounts" / A)
    write_private(base / "config.json", {"account_id": A})
    write_private(base / "control.json", {"mode": "stop"})
    monkeypatch.setattr(runtime, "directory", lambda: base)
    monkeypatch.setattr(cli, "launch_state", lambda: None)
    monkeypatch.setattr(worker, "verify_config", lambda _: tmp_path)
    monkeypatch.setattr(credentials, "CredentialStore", lambda: SimpleNamespace(
        load=lambda: SimpleNamespace(account_id=A)))
    monkeypatch.setattr(manual_reconcile, "datetime", SimpleNamespace(
        now=lambda _: at, fromisoformat=datetime.fromisoformat))
    calls = []

    class Gateway:
        def __init__(self, _):
            calls.append("connect")

        def update(self, _):
            assert self.execution_allowed is False
            calls.append("update")

        def snapshot(self, _):
            return fresh

        def close(self):
            calls.append("close")

    monkeypatch.setattr(gateway, "Gateway", Gateway)
    return base, evidence, calls


def test_operator_dry_run_apply_and_repeat_do_not_dispatch(monkeypatch, tmp_path):
    import sqlite3
    from guiyi_quant.tq_simulation.manual_reconcile import run
    from guiyi_quant.tq_simulation import gateway

    base, evidence, calls = host(monkeypatch, tmp_path)
    path = base / "accounts" / A / "account.sqlite"
    with sqlite3.connect(path) as db:
        count = db.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
    assert run(base / "config.json", evidence, APPROVAL)["status"] == "TQ_MANUAL_CLOSE_PLANNED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == count
    report = run(base / "config.json", evidence, APPROVAL, commit=True)
    assert report["status"] == "TQ_MANUAL_CLOSE_RECONCILED" and report["count"] == 7
    assert report["phase"] == "RECOVERY_REQUIRED"
    monkeypatch.setattr(gateway, "Gateway", lambda _: pytest.fail("SDK connected during NOOP"))
    assert run(base / "config.json", evidence, APPROVAL, commit=True)["status"] == "TQ_MANUAL_CLOSE_NOOP"
    assert calls == ["connect", "update", "close"] * 2


@pytest.mark.parametrize("gate", ["pid", "control", "config_drift"])
def test_operator_requires_native_stop_and_unchanged_config(monkeypatch, tmp_path, gate):
    import sqlite3
    from guiyi_quant.tq_simulation import cli, gateway
    from guiyi_quant.tq_simulation.manual_reconcile import run

    base, evidence, calls = host(monkeypatch, tmp_path)
    path = base / "accounts" / A / "account.sqlite"
    with sqlite3.connect(path) as db:
        count = db.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
    if gate == "pid":
        monkeypatch.setattr(cli, "launch_state", lambda: {"pid": 123})
    elif gate == "control":
        write_private(base / "control.json", {"mode": "pause"})
    else:
        original = gateway.Gateway.update

        def changed(instance, seconds):
            original(instance, seconds)
            write_private(base / "config.json", {"account_id": A, "drift": True})

        monkeypatch.setattr(gateway.Gateway, "update", changed)
    with pytest.raises(ValueError, match="EVIDENCE_UNPROVEN"):
        run(base / "config.json", evidence, APPROVAL, commit=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == count
    assert calls == (["connect", "update", "close"] if gate == "config_drift" else [])
