"""Local-only transaction tests; no production DB, credentials or broker I/O."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import sqlite3
import pytest
from guiyi_quant import htdy_account_execution as a
from guiyi_quant import htdy_execution as h
from test_account_execution import T, facts, initial, readback, sig


def test_local_commit_replays_and_duplicate_returns_no_effects(tmp_path):
    store = a.LocalStore(tmp_path / "account.sqlite", initial())
    store.execute("signal", sig())
    at = T + timedelta(minutes=61)
    tick = a.Tick(at, (facts(at),))
    tx = store.execute("tick", tick)
    assert len(tx.effects) == 1 and tx.state.reservations
    assert store.execute("tick", tick).effects == ()
    assert store.replay() == tx.state
    assert store.receipt("tick")["sequence"] == 2
    assert (tmp_path / "account.sqlite").stat().st_mode & 0o777 == 0o600
    store.close()


def test_restart_never_reemits_effects_and_requires_complete_recovery(tmp_path):
    path = tmp_path / "account.sqlite"
    store = a.LocalStore(path, initial())
    store.execute("signal", sig())
    at = T + timedelta(minutes=61)
    cmd = a.Tick(at, (facts(at),))
    store.execute("tick", cmd)
    store.close()
    store = a.LocalStore(path)
    assert store.current().phase == "RECOVERY_REQUIRED"
    assert store.execute("tick", cmd).effects == ()
    with pytest.raises(a.StoreError, match="NATIVE_RECOVERY_REQUIRED"):
        store.execute("later", a.Tick(at + timedelta(minutes=1), ()))
    store.close()


def test_invalid_command_rolls_back_state_and_reservation(tmp_path):
    store = a.LocalStore(tmp_path / "account.sqlite", initial())
    before = store.current()
    with pytest.raises(ValueError):
        store.execute("wrong", h.Owner("CU", "CU2701", T, "foreign"))
    assert store.current() == before and store.receipt("wrong") is None
    assert store.replay() == before
    store.close()


def test_two_serialized_writers_share_margin_and_product_capacity(tmp_path):
    path = tmp_path / "account.sqlite"
    one = a.LocalStore(path, initial())
    two = a.LocalStore(path)
    proof = a.Recover(
        readback(T + timedelta(seconds=1)),
        (
            h.RecoveryInput("RB", "RB2701", 0, T, "r"),
            h.RecoveryInput("JM", "JM2701", 0, T, "j"),
        ),
    )
    two.execute("recover", proof)
    one.execute("rb", sig(previous=T))
    one.execute("jm", sig("JM", previous=T))
    at = T + timedelta(minutes=61)
    cmd = a.Tick(at, (facts(at, "RB", "40000"), facts(at, "JM", "40000")))
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda pair: pair[0].execute(pair[1], cmd),
                [(one, "tick-one"), (two, "tick-two")],
            )
        )
    assert sum(len(r.effects) for r in results) == 1
    assert len(one.current().reservations) == 1
    assert one.replay() == one.current()
    one.close()
    two.close()


def test_unknown_commit_allows_read_only_receipt_not_blind_retry(tmp_path):
    store = a.LocalStore(tmp_path / "account.sqlite", initial())

    def unknown():
        store._conn.execute("COMMIT")
        raise sqlite3.OperationalError("private database diagnostic")

    store._commit = unknown
    with pytest.raises(a.StoreError, match="COMMIT_OUTCOME_UNKNOWN"):
        store.execute("accepted-unknown", sig())
    assert store.receipt("accepted-unknown") is not None
    with pytest.raises(a.StoreError, match="COMMIT_OUTCOME_REQUIRES_READ_ONLY_CHECK"):
        store.execute("accepted-unknown", sig())


def test_command_rows_are_append_only_and_corrupt_projection_is_rejected(tmp_path):
    path = tmp_path / "account.sqlite"
    store = a.LocalStore(path, initial())
    store.execute("signal", sig())
    store.close()
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM commands")
        conn.execute("UPDATE projection SET sequence=100")
    with pytest.raises(a.StoreError, match="LOCAL_STORE_INVALID"):
        a.LocalStore(path)


def test_restart_records_offline_fill_before_recovery_and_replays(tmp_path):
    from decimal import Decimal

    path = tmp_path / "offline-fill.sqlite"
    store = a.LocalStore(path, initial())
    store.execute("signal", sig())
    at = T + timedelta(minutes=61)
    tx = store.execute("propose", a.Tick(at, (facts(at),)))
    order = tx.effects[0].order
    store.close()
    store = a.LocalStore(path)
    fill = h.Fill(
        "offline-trade",
        order.order_id,
        "simnow-test",
        order.contract,
        T + timedelta(minutes=62),
        T + timedelta(minutes=62, seconds=1),
        order.price,
        Decimal("3"),
        1,
    )
    tx = store.execute("offline-fill", fill)
    assert tx.effects == () and tx.state.phase == "RECOVERY_REQUIRED"
    assert store.receipt("offline-fill") is not None
    assert store.replay() == tx.state
    proof = a.Recover(
        readback(
            T + timedelta(minutes=63),
            available="99000",
            used="1000",
            positions=tx.state.positions,
            orders=(h.OrderReport(order.order_id, "FILLED"),),
            trades=(fill.trade_id,),
        ),
        (h.RecoveryInput("RB", "RB2701", 1, T + timedelta(minutes=60), "valid"),),
    )
    tx = store.execute("recover", proof)
    assert tx.state.readback_valid and tx.state.phase == "READY"
    assert store.replay() == tx.state
    store.close()


def test_recovered_fill_can_arrive_after_a_later_blocking_readback(tmp_path):
    from decimal import Decimal

    path = tmp_path / "offline-late-record.sqlite"
    store = a.LocalStore(path, initial())
    store.execute("signal", sig())
    at = T + timedelta(minutes=61)
    tx = store.execute("propose", a.Tick(at, (facts(at),)))
    order = tx.effects[0].order
    store.close()
    store = a.LocalStore(path)
    pos = (h.Position("RB", "RB2701", 1),)
    rb = readback(
        T + timedelta(minutes=70),
        available="99000",
        used="1000",
        positions=pos,
        orders=(h.OrderReport(order.order_id, "FILLED"),),
        trades=("offline-trade",),
    )
    proof = a.Recover(
        rb, (h.RecoveryInput("RB", "RB2701", 1, T + timedelta(minutes=60), "valid"),)
    )
    tx = store.execute("recover-before-facts", proof)
    assert tx.state.phase == "BLOCKED"
    fill = h.Fill(
        "offline-trade",
        order.order_id,
        "simnow-test",
        order.contract,
        T + timedelta(minutes=62),
        T + timedelta(minutes=62, seconds=1),
        order.price,
        Decimal("3"),
        1,
    )
    tx = store.execute("offline-fill-after-readback", fill)
    assert tx.effects == () and fill in tx.state.fills
    assert tx.state.clock == rb.at
    proof = a.Recover(
        readback(
            T + timedelta(minutes=71),
            available="99000",
            used="1000",
            positions=pos,
            orders=(h.OrderReport(order.order_id, "FILLED"),),
            trades=("offline-trade",),
        ),
        proof.inputs,
    )
    tx = store.execute("recover-after-facts", proof)
    assert tx.state.phase == "READY" and store.replay() == tx.state
    store.close()


def test_restart_retains_consecutive_unknown_fills_and_replays(tmp_path):
    path = tmp_path / "account.sqlite"
    store = a.LocalStore(path, initial())
    store.close()
    store = a.LocalStore(path)
    for index in (1, 2):
        fill = h.Fill(
            f"external-{index}",
            f"unknown-{index}",
            store.current().account_id,
            "RB2701",
            T + timedelta(minutes=index),
            T + timedelta(minutes=index, seconds=1),
            h.Decimal("1000"),
            h.Decimal("0"),
            1,
        )
        tx = store.execute(f"unknown-fill-{index}", fill)
        assert tx.state.phase == "BLOCKED" and not tx.effects
    assert len(tx.state.unresolved_fill_ids) == 2
    assert store.replay() == tx.state
    store.close()
    store = a.LocalStore(path)
    assert len(store.current().unresolved_fill_ids) == 2
    assert store.current().phase == "BLOCKED"
    store.close()
