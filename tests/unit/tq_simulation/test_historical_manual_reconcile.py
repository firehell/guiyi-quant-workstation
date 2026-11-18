"""Cross-day native history is dated evidence, never fabricated current trades."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from guiyi_quant.htdy_account_execution import model as m, codec
from guiyi_quant.tq_simulation.controller import Controller
from guiyi_quant.tq_simulation.manual_reconcile import (
    HISTORICAL_APPROVAL_SCHEMA, historical_source_unchanged, load_evidence, prepare,
)
from guiyi_quant.tq_simulation.runtime import write_private
from test_execution import A, Transport
from test_manual_reconcile import APPROVAL, PRODUCTS, fixture, seal


def historical_fixture(tmp_path):
    c, folder, retained, old_at = fixture(tmp_path)
    c.journal.event("snapshot", retained, old_at)
    rowid, payload = c.journal.db.execute(
        "SELECT rowid,payload FROM events WHERE kind='snapshot' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    at = old_at + timedelta(days=1)
    current = seal({**deepcopy(retained), "observed_at": at.isoformat(),
                    "trading_day": "20261105", "orders": [], "trades": []})
    approval = dict(
        schema=HISTORICAL_APPROVAL_SCHEMA, account_id_sha256=sha256(A.encode()).hexdigest(),
        evidence_sha256=load_evidence(folder)[0], native_event_rowid=rowid,
        native_payload_sha256=sha256(payload.encode()).hexdigest(),
        historical_trading_day=retained["trading_day"], current_trading_day="20261105",
        gap_start=old_at.isoformat(), owner_confirmed_at=(old_at + timedelta(hours=12)).isoformat(),
        approval_source="owner-confirmed-no-other-operations", no_other_operations=True,
    )
    path = tmp_path / "historical-approval.json"
    write_private(path, approval)
    return c, folder, current, at, path, approval


def test_dated_seven_and_empty_current_are_atomic_and_restart_safe(tmp_path):
    c, folder, current, at, path, _ = historical_fixture(tmp_path)
    old = c.store.current()
    prefix = c.store._conn.execute("SELECT * FROM commands ORDER BY sequence").fetchall()
    claims = c.journal.db.execute("SELECT * FROM claims ORDER BY rowid").fetchall()
    key, cmd, duplicate = prepare(c, folder, current, at, APPROVAL, historical_approval=path)
    assert not duplicate and type(cmd) is m.TqKqHistoricalManualClosesV1
    assert not cmd.readback.confirmed_trade_ids and not cmd.readback.snapshot.orders
    assert cmd.historical_readback.at < at and len(cmd.historical_readback.confirmed_trade_ids) == 7
    assert all(f.recorded_at == at and f.filled_at <= cmd.historical_readback.at for f in cmd.fills)
    assert c.store.current() == old

    def proof(_):
        historical_source_unchanged(c, path, cmd)
        return True

    tx = c.store.execute(key, cmd, manual_close_proof=proof)
    assert not tx.effects and tx.state.positions == (m.Position("CU", "CU2701", 1),)
    assert tx.state.initial_readback == old.initial_readback
    assert tx.state.orders[:8] == old.orders and tx.state.fills[:8] == old.fills
    assert all(o.reconciled for o in tx.state.orders[-7:])
    assert tx.state.phase == "RECOVERY_REQUIRED" and not tx.state.readback_valid
    assert c.store._conn.execute("SELECT * FROM commands ORDER BY sequence").fetchall()[:-1] == prefix
    assert c.journal.db.execute("SELECT * FROM claims ORDER BY rowid").fetchall() == claims
    assert codec.load(codec.checkpoint(tx.state)) == tx.state
    from guiyi_quant.tq_simulation.monitor import projection
    records = [r for r in projection(c, current, at, mode="trade", opening=False)["records"]
               if r["facts"].get("execution_origin") == "OWNER_MANUAL_CLOSE"]
    assert len(records) == 14
    assert all(r["facts"]["gap_continuity_source"] == "OWNER_NO_OTHER_OPERATIONS" for r in records)
    assert all(r["facts"]["historical_native_observed_at"] == cmd.historical_readback.at.isoformat()
               and r["facts"]["current_native_observed_at"] == at.isoformat() for r in records)
    assert all(r["signal_id"] is None for r in records)
    assert prepare(c, folder, current, at, APPROVAL) == (key, cmd, True)
    root = c.root
    c.close()
    c = Controller(root, A, PRODUCTS, Transport())
    assert len(c.manual_orders()) == 7 and len(c.native_mappings()) == 15
    rb = c.synchronize(current, at)
    assert rb.confirmed_trade_ids == ()  # the provider's new-day list remains empty
    assert all(o.reconciled for o in c.store.current().orders)
    c.close()


@pytest.mark.parametrize("drift", ["account", "evidence", "row", "payload", "day", "gap", "owner_time", "approval"])
def test_scope_or_owner_attestation_drift_blocks_without_writes(tmp_path, drift):
    c, folder, current, at, path, approval = historical_fixture(tmp_path)
    field, value = {
        "account": ("account_id_sha256", "0" * 64),
        "evidence": ("evidence_sha256", "0" * 64),
        "row": ("native_event_rowid", 999999),
        "payload": ("native_payload_sha256", "0" * 64),
        "day": ("current_trading_day", "20261106"),
        "gap": ("gap_start", (at - timedelta(seconds=1)).isoformat()),
        "owner_time": ("owner_confirmed_at", (at + timedelta(seconds=1)).isoformat()),
        "approval": ("no_other_operations", False),
    }[drift]
    approval[field] = value
    write_private(path, approval)
    old = c.store.current()
    with pytest.raises(ValueError):
        prepare(c, folder, current, at, APPROVAL, historical_approval=path)
    assert c.store.current() == old
    c.close()


def test_no_automatic_cross_day_fallback_and_no_current_trade_synthesis(tmp_path):
    c, folder, current, at, path, _ = historical_fixture(tmp_path)
    with pytest.raises(ValueError):
        prepare(c, folder, current, at, APPROVAL)
    _, cmd, _ = prepare(c, folder, current, at, APPROVAL, historical_approval=path)
    with pytest.raises(ValueError):
        replace(cmd, readback=replace(cmd.readback, confirmed_trade_ids=cmd.historical_readback.confirmed_trade_ids))
    with pytest.raises(ValueError):
        replace(cmd, historical_readback=replace(cmd.historical_readback, complete=False))
    with pytest.raises(ValueError):
        replace(cmd, historical_readback=replace(cmd.historical_readback,
                                                confirmed_trade_ids=cmd.historical_readback.confirmed_trade_ids[:-1]))
    c.close()


def test_atomic_proof_binds_approval_bytes_and_is_required(tmp_path):
    c, folder, current, at, path, approval = historical_fixture(tmp_path)
    key, cmd, _ = prepare(c, folder, current, at, APPROVAL, historical_approval=path)
    old = c.store.current()
    with pytest.raises(ValueError, match="ATOMIC_MANUAL_CLOSE_PROOF_REQUIRED"):
        c.store.execute(key, cmd)
    # Equivalent JSON still changes the approved original bytes.
    path.write_text(json.dumps(approval, indent=2))

    def proof(_):
        historical_source_unchanged(c, path, cmd)
        return True

    with pytest.raises(ValueError):
        c.store.execute(key, cmd, manual_close_proof=proof)
    assert c.store.current() == old
    c.close()


def test_historical_snapshot_cannot_cover_a_newer_local_checkpoint(tmp_path):
    from guiyi_quant.htdy_account_execution.reducer import apply

    c, folder, current, at, path, _ = historical_fixture(tmp_path)
    key, cmd, _ = prepare(c, folder, current, at, APPROVAL, historical_approval=path)
    newer = replace(c.store.current(), clock=cmd.historical_readback.at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="HISTORICAL_MANUAL_CHECKPOINT_UNPROVEN"):
        apply(newer, key, cmd)
    c.close()
