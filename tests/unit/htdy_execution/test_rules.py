"""Behavioral checks for the offline HTDY execution policy, never a broker test."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant import htdy_execution as h


T = datetime(2026, 10, 26, 1, tzinfo=UTC)


def snapshot(account="simnow-test", positions=(), orders=(), at=T):
    return h.AccountSnapshot(account, at, Decimal("100000"), Decimal("90000"), positions, orders)


def started():
    return h.start("simnow-test", ("RB", "JM"), T, snapshot())


def step(state, command, key=None):
    return h.apply(state, key or f"cmd-{len(state.receipts)}", command)


def owner(state, contract="RB2701", at=T):
    return step(state, h.Owner("RB", contract, at, "mapping-proof")).state


def signal(state, direction="buy", minute=60, contract="RB2701", previous=None, product="RB"):
    at = T + timedelta(minutes=minute)
    return h.Signal(f"source-{product}-{minute}", product, contract, at, at + timedelta(seconds=2),
                    previous, () if direction is None else (direction,), "a" * 64)


def advance(state, minute=61, allowed=True, tradable=True):
    return step(state, h.Advance("RB", T + timedelta(minutes=minute), tradable, allowed, "funding-proof"))


def opened(direction="buy"):
    state = owner(started())
    state = step(state, signal(state, direction)).state
    tx = advance(state)
    order = tx.effects[0].order
    fill = h.Fill("trade-1", order.order_id, "simnow-test", order.contract,
                  T + timedelta(minutes=62), T + timedelta(minutes=62, seconds=1),
                  Decimal("3500"), Decimal("3.2"), 1)
    return step(tx.state, fill).state


@pytest.mark.parametrize("direction,target", [("buy", 1), ("sell", -1)])
def test_new_signal_opens_exactly_one_from_flat(direction, target):
    state = owner(started())
    state = step(state, signal(state, direction)).state
    tx = advance(state)
    assert len(tx.effects) == 1
    assert (tx.effects[0].kind, tx.effects[0].order.side, tx.effects[0].order.quantity) == (
        "SUBMIT", "BUY" if target == 1 else "SELL", 1)
    assert tx.state.products[0].quantity == 0  # an intent is not a fill


def test_same_direction_and_no_signal_hold_without_stop_or_add():
    state = opened()
    state = step(state, signal(state, "buy", 120, previous=T + timedelta(minutes=60))).state
    assert advance(state, 121).effects == ()
    state = step(state, signal(state, None, 180, previous=T + timedelta(minutes=120))).state
    assert advance(state, 181).effects == ()
    assert state.products[0].quantity == 1


@pytest.mark.parametrize("initial,reverse,close_side,open_side", [
    ("buy", "sell", "SELL", "SELL"), ("sell", "buy", "BUY", "BUY")])
def test_reverse_waits_for_actual_close_fill(initial, reverse, close_side, open_side):
    state = opened(initial)
    state = step(state, signal(state, reverse, 120, previous=T + timedelta(minutes=60))).state
    close_tx = advance(state, 121)
    close = close_tx.effects[0].order
    assert (close.offset, close.side) == ("CLOSE", close_side)
    assert advance(close_tx.state, 122).effects == ()
    state = step(close_tx.state, h.Fill("close-1", close.order_id, "simnow-test", close.contract,
        T + timedelta(minutes=123), T + timedelta(minutes=123, seconds=1),
        Decimal("3490"), Decimal("2"), 1)).state
    tx = advance(state, 124)
    assert (tx.effects[0].order.offset, tx.effects[0].order.side) == ("OPEN", open_side)


def test_updated_signal_during_close_supersedes_old_reverse():
    state = opened()
    state = step(state, signal(state, "sell", 120, previous=T + timedelta(minutes=60))).state
    tx = advance(state, 121)
    close = tx.effects[0].order
    state = step(tx.state, signal(tx.state, "buy", 180, previous=T + timedelta(minutes=120))).state
    state = step(state, h.Fill("close", close.order_id, "simnow-test", close.contract,
        T + timedelta(minutes=181), T + timedelta(minutes=181, seconds=1),
        Decimal("3500"), Decimal("1"), 1)).state
    assert advance(state, 182).effects[0].order.side == "BUY"


def test_repainting_same_bar_cannot_change_frozen_direction():
    state = owner(started())
    first = signal(state)
    state = step(state, first).state
    from dataclasses import replace
    state = step(state, replace(first, source_id="repaint", directions=("sell",), input_hash="b" * 64)).state
    assert advance(state).effects[0].order.side == "BUY"
    assert state.audit[-1].reason == "FROZEN_BAR_IGNORED"


def test_conflict_cancels_unfilled_open_but_does_not_liquidate_position():
    from dataclasses import replace
    state = opened()
    conflict = replace(signal(state, "buy", 120, previous=T + timedelta(minutes=60)), directions=("buy", "sell"))
    state = step(state, conflict).state
    assert advance(state, 121).effects == ()
    assert state.products[0].quantity == 1


def test_waits_for_new_bar_after_activation_and_rejects_wrong_account():
    state = owner(started())
    old = signal(state, minute=0)
    state = step(state, old).state
    assert advance(state).effects == ()
    with pytest.raises(ValueError, match="ACCOUNT"):
        h.start("simnow-test", ("RB",), T, snapshot(account="different"))
    with pytest.raises(ValueError, match="FLAT"):
        h.start("simnow-test", ("RB",), T, snapshot(positions=(h.Position("RB", "RB2701", 1),)))


def test_duplicate_command_is_idempotent_and_conflicting_payload_fails():
    from dataclasses import replace
    state = owner(started())
    event = signal(state)
    tx = step(state, event, "same-id")
    assert step(tx.state, event, "same-id").state == tx.state
    assert step(tx.state, event, "same-id").effects == ()
    with pytest.raises(ValueError, match="IDENTITY"):
        step(tx.state, replace(event, directions=("sell",)), "same-id")


def test_no_open_when_closed_or_funding_denied_and_no_duplicate_pending():
    state = owner(started())
    state = step(state, signal(state)).state
    assert advance(state, tradable=False).effects == ()
    assert advance(state, allowed=False).effects == ()
    tx = advance(state)
    assert advance(tx.state, 62).effects == ()


def test_missing_bar_requires_recovery_and_does_not_trade():
    state = owner(started())
    state = step(state, signal(state, None)).state
    state = step(state, signal(state, "buy", 180, previous=T + timedelta(minutes=120))).state
    assert "RB" in state.blocked_products
    assert advance(state, 181).effects == ()


def test_rollover_closes_old_contract_and_never_moves_position():
    state = opened()
    state = owner(state, "RB2705", T + timedelta(minutes=120))
    tx = advance(state, 121)
    close = tx.effects[0].order
    assert (close.contract, close.offset) == ("RB2701", "CLOSE")
    assert tx.state.products[0].quantity == 1
    assert advance(tx.state, 122).effects == ()
    state = step(tx.state, h.Fill("roll-close", close.order_id, "simnow-test", close.contract,
        T + timedelta(minutes=123), T + timedelta(minutes=123, seconds=1),
        Decimal("3490"), Decimal("3"), 1)).state
    assert advance(state, 124).effects == ()
    assert state.products[0].quantity == 0


def test_recovery_closes_opposite_without_reopening_and_requires_complete_inputs():
    state = opened()
    state = step(state, h.Disconnect(T + timedelta(minutes=100))).state
    snap = snapshot(positions=(h.Position("RB", "RB2701", 1),), at=T + timedelta(minutes=180, seconds=3))
    state = step(state, h.Recover(snap, (h.RecoveryInput("RB", "RB2701", -1,
        T + timedelta(minutes=180), "complete-proof"),))).state
    assert "JM" in state.blocked_products
    tx = advance(state, 181)
    assert tx.effects[0].order.offset == "CLOSE"
    close = tx.effects[0].order
    state = step(tx.state, h.Fill("recovery-close", close.order_id, "simnow-test", close.contract,
        T + timedelta(minutes=182), T + timedelta(minutes=182, seconds=1),
        Decimal("3490"), Decimal("1"), 1)).state
    assert advance(state, 183).effects == ()


def test_checkpoint_restore_requires_account_readback_and_detects_tampering():
    state = opened()
    data = h.checkpoint(state)
    restored = h.restore(data)
    assert restored.phase == "RECOVERY_REQUIRED"
    assert restored.fills == state.fills
    assert advance(restored, 121).effects == ()
    with pytest.raises(ValueError, match="CHECKPOINT"):
        h.restore(data.replace("100000", "100001"))


def test_unknown_order_blocks_entire_account_until_readback():
    state = owner(started())
    state = step(state, signal(state)).state
    tx = advance(state)
    state = step(tx.state, h.Report("simnow-test", T + timedelta(minutes=62),
        h.OrderReport(tx.effects[0].order.order_id, "UNKNOWN"))).state
    assert state.phase == "RECOVERY_REQUIRED"
    assert advance(state, 63).effects == ()


def test_rejected_open_is_not_automatically_retried():
    state = owner(started())
    state = step(state, signal(state)).state
    tx = advance(state)
    state = step(tx.state, h.Report("simnow-test", T + timedelta(minutes=62),
        h.OrderReport(tx.effects[0].order.order_id, "REJECTED"))).state
    assert advance(state, 63).effects == ()


def test_recovery_cancels_pending_open_instead_of_backfilling():
    state = owner(started())
    state = step(state, signal(state)).state
    tx = advance(state)
    order = tx.effects[0].order
    state = step(tx.state, h.Disconnect(T + timedelta(minutes=90))).state
    state = step(state, h.Recover(snapshot(orders=(h.OrderReport(order.order_id, "WORKING"),),
        at=T + timedelta(minutes=120, seconds=3)),
        (h.RecoveryInput("RB", "RB2701", 1, T + timedelta(minutes=120), "complete"),))).state
    tx = advance(state, 121)
    assert tx.effects[0].kind == "CANCEL"
    state = step(tx.state, h.Report("simnow-test", T + timedelta(minutes=122),
        h.OrderReport(order.order_id, "CANCELLED"))).state
    assert advance(state, 123).effects == ()


def test_rollover_cancels_open_and_accounts_for_late_fill_before_flattening():
    state = owner(started())
    state = step(state, signal(state)).state
    tx = advance(state)
    opening = tx.effects[0].order
    state = owner(tx.state, "RB2705", T + timedelta(minutes=120))
    tx = advance(state, 121)
    assert tx.effects[0].kind == "CANCEL"
    state = step(tx.state, h.Fill("late-open", opening.order_id, "simnow-test", opening.contract,
        T + timedelta(minutes=119), T + timedelta(minutes=122),
        Decimal("3500"), Decimal("1"), 1)).state
    tx = advance(state, 123)
    assert (tx.effects[0].order.contract, tx.effects[0].order.offset) == ("RB2701", "CLOSE")


def test_filled_report_without_trade_does_not_free_order_capacity():
    state = owner(started())
    state = step(state, signal(state)).state
    tx = advance(state)
    state = step(tx.state, h.Report("simnow-test", T + timedelta(minutes=62),
        h.OrderReport(tx.effects[0].order.order_id, "FILLED"))).state
    assert advance(state, 63).effects == ()
    assert state.products[0].quantity == 0


def test_recovery_missing_or_foreign_order_never_unblocks_account():
    state = owner(started())
    state = step(state, signal(state)).state
    state = advance(state).state
    state = step(state, h.Disconnect(T + timedelta(minutes=90))).state
    state = step(state, h.Recover(snapshot(at=T + timedelta(minutes=120)), ())).state
    assert state.phase == "RECOVERY_REQUIRED"
    foreign = snapshot(orders=(h.OrderReport("foreign", "WORKING"),), at=T + timedelta(minutes=121))
    state = step(state, h.Recover(foreign, ())).state
    assert state.phase == "BLOCKED"


def test_duplicate_fill_does_not_charge_or_add_position_twice():
    state = opened()
    tx = step(state, state.fills[0])
    assert len(tx.state.fills) == 1
    assert tx.state.products[0].quantity == 1


@pytest.mark.parametrize("quantity", [0, 2, True, Decimal("1")])
def test_native_fill_requires_exact_integer_one(quantity):
    with pytest.raises(ValueError, match="FILL"):
        h.Fill("t", "o", "simnow-test", "RB2701", T, T, Decimal("1"), Decimal("0"), quantity)


def test_same_instant_order_is_never_proposed():
    state = owner(started())
    event = signal(state)
    state = step(state, event).state
    tx = step(state, h.Advance("RB", event.observed_at, True, True, "funding"))
    assert tx.effects == ()


def test_independent_products_can_have_one_lot_each():
    state = owner(started())
    state = step(state, h.Owner("JM", "JM2701", T, "jm-proof")).state
    state = step(state, signal(state)).state
    state = step(state, signal(state, "sell", product="JM", contract="JM2701")).state
    state = advance(state).state
    tx = step(state, h.Advance("JM", T + timedelta(minutes=61), True, True, "jm-funding"))
    assert len(tx.state.orders) == 2
    assert {o.side for o in tx.state.orders} == {"BUY", "SELL"}


def test_recovery_same_direction_preserves_held_position_without_opening():
    state = opened()
    state = h.restore(h.checkpoint(state))
    snap = snapshot(positions=(h.Position("RB", "RB2701", 1),), at=T + timedelta(minutes=120, seconds=3))
    state = step(state, h.Recover(snap, (h.RecoveryInput("RB", "RB2701", 1,
        T + timedelta(minutes=120), "complete"),))).state
    assert state.products[0].quantity == 1
    assert advance(state, 121).effects == ()


def test_signal_during_rollover_does_not_move_old_target_to_new_contract():
    state = opened()
    state = owner(state, "RB2705", T + timedelta(minutes=120))
    state = step(state, signal(state, "sell", 180, contract="RB2705",
                              previous=T + timedelta(minutes=60))).state
    tx = advance(state, 181)
    assert tx.effects[0].order.offset == "CLOSE"


def test_damaged_checkpoint_with_recomputed_hash_cannot_exceed_one_lot():
    import hashlib
    import json
    packet = json.loads(h.checkpoint(opened()))
    packet["body"]["state"]["fields"]["products"][0]["fields"]["quantity"] = 2
    packet["sha256"] = hashlib.sha256(json.dumps(packet["body"], sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ValueError, match="CHECKPOINT"):
        h.restore(json.dumps(packet))


def test_duplicate_native_trade_after_later_signal_is_still_idempotent():
    state = opened()
    original = state.fills[0]
    state = step(state, signal(state, "buy", 120, previous=T + timedelta(minutes=60))).state
    tx = step(state, original)
    assert tx.state.fills == state.fills
    assert tx.state.products[0].quantity == 1


def test_reconnect_during_pending_close_does_not_reopen_after_late_close_fill():
    state = opened()
    state = step(state, signal(state, "sell", 120, previous=T + timedelta(minutes=60))).state
    tx = advance(state, 121)
    closing = tx.effects[0].order
    state = step(tx.state, h.Disconnect(T + timedelta(minutes=130))).state
    snap = snapshot(positions=(h.Position("RB", "RB2701", 1),),
        orders=(h.OrderReport(closing.order_id, "WORKING"),), at=T + timedelta(minutes=180, seconds=3))
    state = step(state, h.Recover(snap, (h.RecoveryInput("RB", "RB2701", 1,
        T + timedelta(minutes=180), "complete"),))).state
    state = step(state, h.Fill("pending-close", closing.order_id, "simnow-test", closing.contract,
        T + timedelta(minutes=181), T + timedelta(minutes=181, seconds=1),
        Decimal("3500"), Decimal("1"), 1)).state
    assert advance(state, 182).effects == ()
