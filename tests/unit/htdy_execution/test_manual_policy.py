"""One-shot manual RB long test, entirely offline and without synthetic signals."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json

import pytest

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.htdy_account_execution import codec


T = datetime(2026, 10, 27, 1, tzinfo=UTC)
TEST_ID = "manual:00000000-0000-4000-8000-000000000001"


def readback(at=T, *, positions=(), orders=(), trades=(), settled=(), used="0"):
    return a.Readback(
        h.AccountSnapshot(
            "account", at, D("100000"), D("100000"), positions, orders, settled
        ),
        D(used),
        D(0),
        D(0),
        (),
        trades,
        "native:" + at.isoformat(),
        at + timedelta(hours=4),
        True,
    )


def apply(state, command, key=None):
    return a.apply(state, key or f"command:{len(state.receipts)}", command)


def base(*, blocked=False):
    state = a.start("account", ("RB",), T, readback())
    state = apply(state, h.Owner("RB", "RB2701", T, "owner:RB")).state
    if blocked:
        state = replace(state, blocked_products=("RB",))
    return state


def begin(state=None):
    state = state or base()
    command = a.ManualBeginV1(
        TEST_ID, "RB", "RB2701", T + timedelta(seconds=1), T + timedelta(minutes=2)
    )
    return apply(state, command).state


def facts(at, *, price="1000"):
    return a.ExecutionInput(
        a.Instrument(
            "RB",
            "RB2701",
            T,
            T + timedelta(hours=3),
            "instrument",
            D(1),
            D(10),
            D("0.1"),
            D("0.1"),
            D(3),
        ),
        a.Session(
            "RB2701",
            T,
            T + timedelta(hours=3),
            "session",
            T + timedelta(hours=3),
            True,
            True,
        ),
        a.Quote(
            "RB2701",
            at,
            at + timedelta(seconds=10),
            "quote:" + at.isoformat(),
            D(price) - 1,
            D(price),
            1,
            1,
            D(1),
            D(100000),
        ),
    )


def manual_tick(state, at, *, price="1000"):
    return apply(state, a.ManualTickV1(at, (facts(at, price=price),), TEST_ID))


def opened(state=None):
    state = begin(state)
    at = T + timedelta(seconds=2)
    tx = manual_tick(state, at)
    assert len(tx.effects) == 1 and tx.effects[0].order.offset == "OPEN"
    return tx.state, tx.effects[0].order


def native_fill(order, at, *, trade_id="native-open"):
    return a.NativeFill(
        trade_id,
        order.order_id,
        "account",
        order.contract,
        at,
        at + timedelta(seconds=1),
        order.price,
        D(3),
        1,
        order.created_at + timedelta(seconds=1),
        "dispatch:" + order.order_id,
        "system:" + trade_id,
    )


def confirmed_open(state, order, *, at=None):
    at = at or T + timedelta(seconds=10)
    fill = native_fill(order, at - timedelta(seconds=3))
    state = apply(state, fill).state
    rb = readback(
        at,
        positions=state.positions,
        orders=(h.OrderReport(order.order_id, "FILLED"),),
        trades=(fill.trade_id,),
        used="1000",
    )
    state = apply(state, rb).state
    return state, fill


def test_manual_open_bypasses_only_strategy_input_block_and_leaves_signals_untouched():
    state, order = opened(base(blocked=True))
    assert state.signals == ()
    assert state.blocked_products == ("RB",)
    assert order.signal_id == TEST_ID and order.side == "BUY" and order.offset == "OPEN"
    assert len(state.reservations) == len(state.risk_decisions) == 1
    assert a.manual_status(state, TEST_ID).phase == "OPEN_PENDING"
    with pytest.raises(ValueError, match="MANUAL_TEST_SCOPED_TICK_REQUIRED"):
        apply(
            state, a.Tick(T + timedelta(seconds=3), (facts(T + timedelta(seconds=3)),))
        )


def test_accepted_manual_open_is_not_cancelled_by_strategy_input_block():
    state, order = opened(base(blocked=True))
    accepted_at = T + timedelta(seconds=3)
    state = apply(
        state,
        a.OrderUpdate(
            "account", order.order_id, accepted_at, "accepted", "WORKING", accepted_at
        ),
    ).state
    next_at = T + timedelta(seconds=4)
    tx = manual_tick(state, next_at)
    assert tx.effects == ()
    assert tx.state.blocked_products == ("RB",)
    assert not tx.state.orders[0].cancel_required
    assert tx.state.orders[0].status == "WORKING"


def test_manual_order_requires_native_fill_fact():
    state, order = opened()
    model_fill = h.Fill(
        "model-fill",
        order.order_id,
        "account",
        "RB2701",
        T + timedelta(seconds=7),
        T + timedelta(seconds=8),
        order.price,
        D(3),
        1,
    )
    with pytest.raises(ValueError, match="MANUAL_NATIVE_FILL_REQUIRED"):
        apply(state, model_fill)


def test_ten_minutes_start_at_first_confirmed_readback_and_close_not_early():
    state, order = opened()
    fill = native_fill(order, T + timedelta(seconds=7))
    state = apply(state, fill).state
    assert a.manual_status(state, TEST_ID).phase == "OPEN_UNCONFIRMED"
    assert a.manual_status(state, TEST_ID).due_at is None
    rb_at = T + timedelta(seconds=10)
    state = apply(
        state,
        readback(
            rb_at,
            positions=state.positions,
            orders=(h.OrderReport(order.order_id, "FILLED"),),
            trades=(fill.trade_id,),
            used="1000",
        ),
    ).state
    status = a.manual_status(state, TEST_ID)
    assert status.confirmed_at == rb_at
    assert status.due_at == rb_at + timedelta(seconds=600)
    just_before = status.due_at - timedelta(seconds=1)
    tx = manual_tick(state, just_before)
    assert tx.effects == () and a.manual_status(tx.state, TEST_ID).phase == "HOLDING"
    due = status.due_at
    tx = manual_tick(tx.state, due)
    assert len(tx.effects) == 1
    assert tx.effects[0].order.offset == "CLOSE"
    assert tx.effects[0].order.signal_id == TEST_ID
    assert tx.state.signals == ()


def test_close_completion_requires_native_fill_and_full_readback():
    state, order = opened()
    state, _ = confirmed_open(state, order)
    due = a.manual_status(state, TEST_ID).due_at
    close_tx = manual_tick(state, due)
    close_order = close_tx.effects[0].order
    close_fill = native_fill(
        close_order, due + timedelta(seconds=2), trade_id="native-close"
    )
    state = apply(close_tx.state, close_fill).state
    assert a.manual_status(state, TEST_ID).phase == "CLOSE_PENDING"
    state = apply(
        state,
        readback(
            due + timedelta(seconds=5),
            positions=(),
            orders=(
                h.OrderReport(order.order_id, "FILLED"),
                h.OrderReport(close_order.order_id, "FILLED"),
            ),
            trades=("native-open", close_fill.trade_id),
        ),
    ).state
    status = a.manual_status(state, TEST_ID)
    assert status.phase == "COMPLETE" and status.complete and status.terminal
    assert status.close_order_ids == (close_order.order_id,)
    assert manual_tick(state, due + timedelta(seconds=6)).effects == ()
    assert (
        apply(
            state,
            a.ManagedTickV1(
                due + timedelta(seconds=6), (facts(due + timedelta(seconds=6)),)
            ),
        ).effects
        == ()
    )


def test_cancelled_open_never_reopens_and_late_fill_reenters_recovery():
    state, order = opened()
    accepted_at = T + timedelta(seconds=3)
    state = apply(
        state,
        a.OrderUpdate(
            "account", order.order_id, accepted_at, "accepted", "WORKING", accepted_at
        ),
    ).state
    deadline = T + timedelta(minutes=2)
    tx = manual_tick(state, deadline)
    assert [effect.kind for effect in tx.effects] == ["CANCEL"]
    state = apply(
        tx.state,
        a.OrderUpdate(
            "account",
            order.order_id,
            deadline + timedelta(seconds=1),
            "cancelled",
            "CANCELLED",
        ),
    ).state
    state = apply(
        state,
        readback(
            deadline + timedelta(seconds=2),
            orders=(h.OrderReport(order.order_id, "CANCELLED"),),
            settled=(order.order_id,),
        ),
    ).state
    assert a.manual_status(state, TEST_ID).phase == "OPEN_NO_FILL"
    assert manual_tick(state, deadline + timedelta(seconds=3)).effects == ()

    late = native_fill(order, deadline + timedelta(seconds=4), trade_id="late-open")
    state = apply(state, late).state
    assert state.phase == "RECOVERY_REQUIRED"
    assert not a.manual_status(state, TEST_ID).terminal
    full = readback(
        deadline + timedelta(seconds=7),
        positions=state.positions,
        orders=(h.OrderReport(order.order_id, "FILLED"),),
        trades=(late.trade_id,),
        used="1000",
    )
    state = apply(
        state, a.Recover(full, (h.RecoveryInput("RB", "RB2701", 1, T, "recovery"),))
    ).state
    status = a.manual_status(state, TEST_ID)
    assert status.phase == "HOLDING"
    assert status.confirmed_at == full.at
    assert status.due_at == full.at + timedelta(seconds=600)
    assert manual_tick(state, full.at + timedelta(seconds=599)).effects == ()


def test_begin_is_one_shot_and_requires_reconciled_flat_account():
    state = begin()
    with pytest.raises(ValueError, match="MANUAL_TEST_ALREADY_STARTED"):
        apply(
            state,
            a.ManualBeginV1(
                "manual:00000000-0000-4000-8000-000000000002",
                "RB",
                "RB2701",
                T + timedelta(seconds=2),
                T + timedelta(minutes=2),
            ),
        )
    state, order = opened()
    with pytest.raises(ValueError, match="MANUAL_TEST_ALREADY_STARTED"):
        apply(
            state,
            a.ManualBeginV1(
                "manual:00000000-0000-4000-8000-000000000002",
                "RB",
                "RB2701",
                T + timedelta(seconds=3),
                T + timedelta(minutes=2),
            ),
        )
    assert order.signal_id == TEST_ID
    with pytest.raises(ValueError, match="MANUAL_ACCOUNT_NOT_FLAT_READY"):
        begin(replace(base(), phase="RECOVERY_REQUIRED", readback_valid=False))


def test_manual_risk_rejection_is_terminal_and_reserves_nothing():
    state = begin()
    tx = manual_tick(state, T + timedelta(seconds=2), price="70001")
    assert tx.effects == () and tx.state.orders == tx.state.reservations == ()
    assert len(tx.state.risk_decisions) == 1
    assert a.manual_status(tx.state, TEST_ID).phase == "OPEN_REJECTED"
    assert manual_tick(tx.state, T + timedelta(seconds=3)).effects == ()
    assert (
        apply(
            tx.state,
            a.ManagedTickV1(
                T + timedelta(seconds=3), (facts(T + timedelta(seconds=3)),)
            ),
        ).effects
        == ()
    )


def test_checkpoint_and_restart_keep_due_and_forbid_reopen(tmp_path):
    state, order = opened()
    state, fill = confirmed_open(state, order)
    due = a.manual_status(state, TEST_ID).due_at
    packet = json.loads(a.checkpoint(state))
    assert packet["body"]["policy"] == "htdy_60m_account_execution_v2"
    assert codec.load(json.dumps(packet)) == state
    restored = a.restore(json.dumps(packet))
    assert restored.phase == "RECOVERY_REQUIRED"
    assert a.manual_status(restored, TEST_ID).due_at == due
    # The reducer records an inert tick, with no effect before full recovery.
    assert manual_tick(restored, due).effects == ()
    later = due + timedelta(seconds=1)
    full = readback(
        later,
        positions=restored.positions,
        orders=(h.OrderReport(order.order_id, "FILLED"),),
        trades=(fill.trade_id,),
        used="1000",
    )
    recovered = apply(
        restored, a.Recover(full, (h.RecoveryInput("RB", "RB2701", 1, T, "restart"),))
    ).state
    assert a.manual_status(recovered, TEST_ID).due_at == due
    tx = manual_tick(recovered, later + timedelta(seconds=1))
    assert [effect.order.offset for effect in tx.effects] == ["CLOSE"]
    assert (
        len(
            [
                o
                for o in tx.state.orders
                if o.offset == "OPEN" and o.signal_id == TEST_ID
            ]
        )
        == 1
    )


def test_local_store_restart_requires_full_recover_before_manual_close(tmp_path):
    path = tmp_path / "account.sqlite"
    store = a.LocalStore(path, base())
    command = a.ManualBeginV1(
        TEST_ID, "RB", "RB2701", T + timedelta(seconds=1), T + timedelta(minutes=2)
    )
    store.execute("begin", command)
    at = T + timedelta(seconds=2)
    opened_tx = store.execute("open", a.ManualTickV1(at, (facts(at),), TEST_ID))
    order = opened_tx.effects[0].order
    fill = native_fill(order, T + timedelta(seconds=7))
    store.execute("native-fill", fill)
    rb_at = T + timedelta(seconds=10)
    store.execute(
        "readback",
        readback(
            rb_at,
            positions=(h.Position("RB", "RB2701", 1),),
            orders=(h.OrderReport(order.order_id, "FILLED"),),
            trades=(fill.trade_id,),
            used="1000",
        ),
    )
    due = a.manual_status(store.current(), TEST_ID).due_at
    assert store.replay() == store.current()
    store.close()

    reopened = a.LocalStore(path)
    assert a.manual_status(reopened.current(), TEST_ID).due_at == due
    with pytest.raises(a.StoreError, match="NATIVE_RECOVERY_REQUIRED"):
        reopened.execute("premature-close", a.ManualTickV1(due, (facts(due),), TEST_ID))
    later = due + timedelta(seconds=1)
    full = readback(
        later,
        positions=(h.Position("RB", "RB2701", 1),),
        orders=(h.OrderReport(order.order_id, "FILLED"),),
        trades=(fill.trade_id,),
        used="1000",
    )
    reopened.execute(
        "full-recover",
        a.Recover(full, (h.RecoveryInput("RB", "RB2701", 1, T, "full"),)),
    )
    close = reopened.execute(
        "close",
        a.ManualTickV1(
            later + timedelta(seconds=1),
            (facts(later + timedelta(seconds=1)),),
            TEST_ID,
        ),
    )
    assert [effect.order.offset for effect in close.effects] == ["CLOSE"]
    assert (
        len(
            [
                order
                for order in close.state.orders
                if order.signal_id == TEST_ID and order.offset == "OPEN"
            ]
        )
        == 1
    )
    assert reopened.replay() == reopened.current()
    reopened.close()
