"""Account execution safety fixtures, never provider/live evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import pytest
from guiyi_quant import htdy_execution as h
from guiyi_quant import htdy_account_execution as a

T = datetime(2026, 10, 26, 1, tzinfo=UTC)


def readback(
    at=T,
    balance="100000",
    available="100000",
    used="0",
    frozen="0",
    fee="0",
    positions=(),
    orders=(),
    settled=(),
    trades=(),
    coverage=(),
    complete=True,
    source=None,
):
    return a.Readback(
        h.AccountSnapshot(
            "simnow-test", at, D(balance), D(available), positions, orders, settled
        ),
        D(used),
        D(frozen),
        D(fee),
        coverage,
        trades,
        source or f"funds-{at.isoformat()}",
        at + timedelta(days=2),
        complete,
    )


def initial(products=("RB", "JM")):
    s = a.start("simnow-test", products, T, readback())
    for p in products:
        s = step(s, h.Owner(p, p + "2701", T, "owner-" + p)).state
    return s


def step(state, cmd, key=None):
    return a.apply(state, key or f"cmd-{len(state.receipts)}", cmd)


def sig(product="RB", direction="buy", minute=60, previous=None):
    end = T + timedelta(minutes=minute)
    return h.Signal(
        f"sig-{product}-{minute}",
        product,
        product + "2701",
        end,
        end + timedelta(seconds=2),
        previous,
        () if direction is None else (direction,),
        "a" * 64,
    )


def facts(
    at,
    product="RB",
    price="1000",
    close=None,
    tradable=True,
    cancel=True,
    quote=True,
    rate="0.1",
):
    c = product + "2701"
    return a.ExecutionInput(
        a.Instrument(
            product,
            c,
            T,
            T + timedelta(days=2),
            "instrument-" + product,
            D("1"),
            D("10"),
            D(rate),
            D(rate),
            D("3"),
        ),
        a.Session(
            c,
            T,
            T + timedelta(days=2),
            "session-" + product,
            close or T + timedelta(hours=6),
            tradable,
            cancel,
        ),
        a.Quote(
            c,
            at,
            at + timedelta(seconds=10),
            "quote-" + at.isoformat(),
            D(price) - 1,
            D(price),
            1,
            1,
            D("1"),
            D("1000000"),
        )
        if quote
        else None,
    )


def tick(state, minute=61, second=0, price="1000", close=None, inputs=None):
    at = T + timedelta(minutes=minute, seconds=second)
    return step(
        state,
        a.Tick(
            at, inputs if inputs is not None else (facts(at, price=price, close=close),)
        ),
    )


def accepted(state, order, at=None):
    at = at or order.created_at + timedelta(seconds=1)
    return step(
        state,
        a.OrderUpdate(
            "simnow-test",
            order.order_id,
            at,
            "accepted-" + order.order_id,
            "WORKING",
            at,
        ),
    ).state


def test_account_exact_70_percent_and_reserves_before_submission():
    s = step(initial(), sig()).state
    tx = tick(s, price="70000")
    assert len(tx.effects) == 1
    assert tx.effects[0].order.price == D("70000")
    assert tx.state.reservations[0].margin == D("70000")
    assert tx.state.positions == ()


def test_risk_rejection_is_permanent_even_after_funds_increase():
    s = step(initial(), sig()).state
    tx = tick(s, price="70001")
    assert tx.effects == () and sig().source_id in tx.state.abandoned
    s = step(
        tx.state,
        readback(T + timedelta(minutes=62), balance="200000", available="200000"),
    ).state
    assert tick(s, 63).effects == ()
    s = step(s, sig(minute=120, previous=T + timedelta(minutes=60))).state
    assert tick(s, 121).effects[0].kind == "SUBMIT"


def test_simultaneous_products_cannot_overspend_and_tie_is_product_sorted():
    s = initial()
    s = step(s, sig("RB")).state
    s = step(s, sig("JM")).state
    at = T + timedelta(minutes=61)
    tx = tick(s, inputs=(facts(at, "RB", "40000"), facts(at, "JM", "40000")))
    assert [e.order.product for e in tx.effects] == ["JM"]
    assert sig("RB").source_id in tx.state.abandoned


def test_duplicate_tick_and_signal_do_not_double_reserve():
    s = step(initial(), sig()).state
    cmd = a.Tick(T + timedelta(minutes=61), (facts(T + timedelta(minutes=61)),))
    tx = step(s, cmd, "once")
    assert step(tx.state, cmd, "once").effects == ()
    s = step(tx.state, sig()).state
    assert len(tick(s, 62).state.reservations) == 1


def test_timeout_starts_at_native_acceptance_and_needs_cancel_readback():
    s = step(initial(), sig()).state
    tx = tick(s)
    order = tx.effects[0].order
    assert (
        tick(tx.state, 65).effects == ()
    )  # no accepted timestamp: never pretend failure
    s = accepted(tx.state, order)
    assert tick(s, 64, second=0).effects == ()
    tx = tick(s, 64, second=1)
    assert [e.kind for e in tx.effects] == ["CANCEL"]
    s = step(
        tx.state,
        a.OrderUpdate(
            "simnow-test",
            order.order_id,
            T + timedelta(minutes=64, seconds=2),
            "cancelled",
            "CANCELLED",
        ),
    ).state
    assert not s.reservations[0].released
    assert tick(s, 65).effects == ()
    proof = readback(
        T + timedelta(minutes=66),
        orders=(h.OrderReport(order.order_id, "CANCELLED"),),
        settled=(order.order_id,),
    )
    s = step(s, proof).state
    assert s.reservations[0].released
    retry = tick(s, 67, price="1001")
    assert retry.effects[0].order.predecessor_id == order.order_id
    assert retry.effects[0].order.price == D("1001")


def test_final_minute_beats_timeout_and_never_backfills():
    s = step(initial(), sig()).state
    tx = tick(s)
    order = tx.effects[0].order
    s = accepted(tx.state, order)
    close = T + timedelta(minutes=65, seconds=1)
    tx = tick(s, 64, second=1, close=close)
    assert tx.effects[0].kind == "CANCEL"
    assert sig().source_id in tx.state.abandoned
    s = step(
        tx.state,
        a.OrderUpdate(
            "simnow-test",
            order.order_id,
            T + timedelta(minutes=64, seconds=2),
            "cancelled",
            "CANCELLED",
        ),
    ).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=66),
            orders=(h.OrderReport(order.order_id, "CANCELLED"),),
            settled=(order.order_id,),
        ),
    ).state
    assert tick(s, 70).effects == ()


def test_snapshot_frozen_coverage_is_not_counted_twice():
    s = step(initial(), sig()).state
    tx = tick(s, price="40000")
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    rb = readback(
        T + timedelta(minutes=62),
        available="59997",
        frozen="40000",
        fee="3",
        orders=(h.OrderReport(o.order_id, "WORKING"),),
        coverage=(a.Coverage(o.order_id, D("40000"), D("3")),),
    )
    s = step(s, rb).state
    s = step(s, sig("JM", minute=63)).state
    at = T + timedelta(minutes=64)
    tx = tick(s, 64, inputs=(facts(at, "RB", "40000"), facts(at, "JM", "30000")))
    assert any(e.kind == "SUBMIT" and e.order.product == "JM" for e in tx.effects)


def test_restart_keeps_reservations_but_requires_native_recovery():
    s = step(initial(), sig()).state
    s = tick(s).state
    restored = a.restore(a.checkpoint(s))
    assert restored.reservations == s.reservations
    assert restored.phase == "RECOVERY_REQUIRED"
    assert tick(restored, 65).effects == ()


def test_wrong_account_readback_is_rejected():
    s = initial()
    rb = readback(T + timedelta(seconds=1))
    with pytest.raises(ValueError):
        step(s, replace(rb, snapshot=replace(rb.snapshot, account_id="other")))


def open_position(direction="buy", price="1000"):
    s = step(initial(), sig(direction=direction)).state
    tx = tick(s, price=price)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    fill = h.Fill(
        "fill-open",
        o.order_id,
        "simnow-test",
        o.contract,
        o.created_at + timedelta(seconds=2),
        o.created_at + timedelta(seconds=3),
        o.price,
        D("3"),
        1,
    )
    s = step(s, fill).state
    return s, o, fill


def settle_position(
    s, o, fill, at=None, balance="100000", available="99000", used="1000"
):
    at = at or T + timedelta(minutes=62)
    return step(
        s,
        readback(
            at,
            balance=balance,
            available=available,
            used=used,
            positions=s.positions,
            orders=(h.OrderReport(o.order_id, "FILLED"),),
            trades=(fill.trade_id,),
        ),
    ).state


@pytest.mark.parametrize(
    "initial_side,reverse,close_side", [("buy", "sell", "SELL"), ("sell", "buy", "BUY")]
)
def test_reversal_only_opens_after_close_fill_and_fresh_account(
    initial_side, reverse, close_side
):
    s, o, f = open_position(initial_side)
    s = settle_position(s, o, f)
    s = step(
        s, sig(direction=reverse, minute=120, previous=T + timedelta(minutes=60))
    ).state
    tx = tick(s, 121)
    close = tx.effects[0].order
    assert close.offset == "CLOSE" and close.side == close_side
    assert tick(tx.state, 122).effects == ()
    cf = h.Fill(
        "close-fill",
        close.order_id,
        "simnow-test",
        close.contract,
        T + timedelta(minutes=123),
        T + timedelta(minutes=123, seconds=1),
        D("1000"),
        D("3"),
        1,
    )
    s = step(tx.state, cf).state
    assert tick(s, 124).effects == ()  # stale available is never reused after a fill
    s = step(
        s,
        readback(
            T + timedelta(minutes=125),
            orders=(h.OrderReport(close.order_id, "FILLED"),),
            trades=(f.trade_id, cf.trade_id),
        ),
    ).state
    tx = tick(s, 126)
    assert tx.effects[0].order.offset == "OPEN"
    assert tx.effects[0].order.side == close_side


def test_close_is_not_blocked_by_negative_equity_or_margin_cap():
    s, o, f = open_position()
    s = settle_position(s, o, f, balance="-100", available="-500", used="1000")
    s = step(
        s, sig(direction="sell", minute=120, previous=T + timedelta(minutes=60))
    ).state
    assert tick(s, 121).effects[0].order.offset == "CLOSE"


def test_cutoff_cancels_reverse_open_but_keeps_pending_close_obligation():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = step(
        s, sig(direction="sell", minute=120, previous=T + timedelta(minutes=60))
    ).state
    tx = tick(s, 121)
    close = tx.effects[0].order
    s = accepted(tx.state, close)
    final = T + timedelta(minutes=123)
    s = tick(s, 122, close=final).state
    # Even while the close is pending, the reverse OPEN signal must expire at cutoff.
    assert sig(direction="sell", minute=120).source_id in s.abandoned
    cf = h.Fill(
        "close-after-cutoff",
        close.order_id,
        "simnow-test",
        close.contract,
        T + timedelta(minutes=123),
        T + timedelta(minutes=123, seconds=1),
        D("1000"),
        D("3"),
        1,
    )
    s = step(s, cf).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=124),
            orders=(h.OrderReport(close.order_id, "FILLED"),),
            trades=(f.trade_id, cf.trade_id),
        ),
    ).state
    assert tick(s, 125).effects == ()
    assert s.positions == ()


def test_close_order_still_reprices_after_cutoff_in_next_session():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = step(
        s, sig(direction="sell", minute=120, previous=T + timedelta(minutes=60))
    ).state
    tx = tick(s, 121)
    close = tx.effects[0].order
    s = accepted(tx.state, close)
    tx = tick(s, 124, second=1, close=T + timedelta(minutes=125))
    assert tx.effects[0].kind == "CANCEL"
    s = step(
        tx.state,
        a.OrderUpdate(
            "simnow-test",
            close.order_id,
            T + timedelta(minutes=124, seconds=2),
            "close-cancel",
            "CANCELLED",
        ),
    ).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=126),
            available="99000",
            used="1000",
            positions=s.positions,
            orders=(h.OrderReport(close.order_id, "CANCELLED"),),
            settled=(close.order_id,),
            trades=(f.trade_id,),
        ),
    ).state
    tx = tick(s, 127)
    assert tx.effects[0].order.offset == "CLOSE"
    assert tx.effects[0].order.side == "SELL"


def test_order_in_last_minute_is_never_proposed_and_old_signal_does_not_resume():
    s = step(initial(), sig()).state
    tx = tick(s, close=T + timedelta(minutes=62))
    assert tx.effects == () and sig().source_id in tx.state.abandoned
    assert tick(tx.state, 63).effects == ()


def test_wall_clock_timeout_runs_during_break_and_cancel_waits_for_permission():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    at = T + timedelta(minutes=65)
    tx = tick(s, 65, inputs=(facts(at, tradable=False, cancel=False),))
    assert tx.effects == () and tx.state.orders[0].cancel_required
    at = T + timedelta(minutes=66)
    tx = tick(tx.state, 66, inputs=(facts(at, tradable=False, cancel=True),))
    assert tx.effects[0].kind == "CANCEL"


def test_cancel_unknown_keeps_full_reservation_and_stops_new_orders():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    s = step(
        s,
        a.OrderUpdate(
            "simnow-test", o.order_id, T + timedelta(minutes=62), "unknown", "UNKNOWN"
        ),
    ).state
    assert s.phase == "RECOVERY_REQUIRED"
    assert not s.reservations[0].released
    assert (
        tick(s, 65).effects[0].kind == "CANCEL"
    )  # readback was already valid before unknown report
    assert not any(o.product == "JM" for o in s.orders)


def test_fill_missing_from_native_report_blocks_release():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = step(
        tx.state,
        a.OrderUpdate(
            "simnow-test",
            o.order_id,
            T + timedelta(minutes=62),
            "filled-without-trade",
            "FILLED",
        ),
    ).state
    rb = readback(
        T + timedelta(minutes=63), orders=(h.OrderReport(o.order_id, "FILLED"),)
    )
    s = step(s, rb).state
    assert not s.readback_valid and not s.reservations[0].released


def test_external_round_trip_trade_is_not_silently_accepted():
    s = step(
        initial(), readback(T + timedelta(seconds=1), trades=("foreign-trade",))
    ).state
    assert s.phase == "BLOCKED" and not s.readback_valid


def test_late_fill_after_reconciled_cancel_is_retained_and_relocks_reservation():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    tx = tick(s, 64, second=1)
    s = step(
        tx.state,
        a.OrderUpdate(
            "simnow-test", o.order_id, T + timedelta(minutes=65), "cancel", "CANCELLED"
        ),
    ).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=66),
            orders=(h.OrderReport(o.order_id, "CANCELLED"),),
            settled=(o.order_id,),
        ),
    ).state
    assert s.reservations[0].released
    late = h.Fill(
        "late-fill",
        o.order_id,
        "simnow-test",
        o.contract,
        T + timedelta(minutes=62),
        T + timedelta(minutes=67),
        D("1000"),
        D("3"),
        1,
    )
    s = step(s, late).state
    assert s.fills[-1] == late and s.positions[0].quantity == 1
    assert not s.reservations[0].released and s.phase == "RECOVERY_REQUIRED"


def test_unknown_fill_is_preserved_without_fabricating_position():
    s = initial()
    f = h.Fill(
        "unknown-fill",
        "unknown-order",
        "simnow-test",
        "RB2701",
        T + timedelta(seconds=1),
        T + timedelta(seconds=2),
        D("1000"),
        D("3"),
        1,
    )
    s = step(s, f).state
    assert s.phase == "BLOCKED" and s.fills == (f,) and s.positions == ()
    assert a.restore(a.checkpoint(s)).unresolved_fill_ids == (f.trade_id,)


def test_stale_quote_cannot_open_but_cutoff_cancellation_does_not_need_quote():
    s = step(initial(), sig()).state
    at = T + timedelta(minutes=61)
    stale = replace(
        facts(at),
        quote=replace(
            facts(at).quote,
            at=at - timedelta(seconds=20),
            valid_until=at - timedelta(seconds=1),
        ),
    )
    assert tick(s, inputs=(stale,)).effects == ()
    tx = tick(s)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    at = T + timedelta(minutes=62)
    tx = tick(s, 62, inputs=(facts(at, close=at + timedelta(seconds=60), quote=False),))
    assert tx.effects[0].kind == "CANCEL"


def test_no_fixed_product_count_or_sector_gate_but_each_product_one_lot():
    s = initial(("RB", "JM", "CU", "AL"))
    for p in ("RB", "JM", "CU", "AL"):
        s = step(s, sig(p)).state
    at = T + timedelta(minutes=61)
    tx = tick(s, inputs=tuple(facts(at, p) for p in ("RB", "JM", "CU", "AL")))
    assert len(tx.effects) == 4 and all(e.order.quantity == 1 for e in tx.effects)
    assert (
        len(
            tick(
                tx.state,
                62,
                inputs=tuple(
                    facts(T + timedelta(minutes=62), p)
                    for p in ("RB", "JM", "CU", "AL")
                ),
            ).state.orders
        )
        == 4
    )


def test_fresh_snapshot_does_not_allow_resubmission_after_disconnect_recovery():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    s = step(s, a.Disconnect(T + timedelta(minutes=62))).state
    assert tick(s, 65).effects == ()
    rb = readback(
        T + timedelta(minutes=66), orders=(h.OrderReport(o.order_id, "WORKING"),)
    )
    s = step(
        s,
        a.Recover(
            rb,
            (
                h.RecoveryInput(
                    "RB", "RB2701", 1, T + timedelta(minutes=60), "complete"
                ),
                h.RecoveryInput(
                    "JM", "JM2701", 0, T + timedelta(minutes=60), "complete-jm"
                ),
            ),
        ),
    ).state
    tx = tick(s, 67)
    assert tx.effects[0].kind == "CANCEL"
    assert sig().source_id in tx.state.abandoned


@pytest.mark.parametrize("value", ["0", "-100"])
def test_nonpositive_equity_rejects_open_and_preserves_native_balance(value):
    s = a.start("simnow-test", ("RB",), T, readback(balance=value, available="0"))
    s = step(s, h.Owner("RB", "RB2701", T, "owner")).state
    s = step(s, sig()).state
    tx = tick(s)
    assert tx.effects == () and tx.state.readback.snapshot.balance == D(value)
    assert sig().source_id in tx.state.abandoned


def test_available_cash_reserves_fees_in_addition_to_margin():
    s = a.start("simnow-test", ("RB",), T, readback(available="1002"))
    s = step(s, h.Owner("RB", "RB2701", T, "owner")).state
    s = step(s, sig()).state
    tx = tick(s)
    assert tx.effects == ()
    assert tx.state.risk_decisions[-1].reason == "AVAILABLE_FUNDS"


def test_unreflected_native_coverage_does_not_release_local_occupancy():
    s = step(initial(), sig()).state
    tx = tick(s, price="40000")
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    # Broker has not yet frozen the first accepted order: local reserve still covers it.
    s = step(
        s,
        readback(
            T + timedelta(minutes=62), orders=(h.OrderReport(o.order_id, "WORKING"),)
        ),
    ).state
    s = step(s, sig("JM", minute=63)).state
    at = T + timedelta(minutes=64)
    tx = tick(s, 64, inputs=(facts(at, "RB", "40000"), facts(at, "JM", "40000")))
    assert not any(e.kind == "SUBMIT" for e in tx.effects)
    assert sig("JM", minute=63).source_id in tx.state.abandoned


def test_incomplete_snapshot_never_releases_cancelled_order():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = accepted(tx.state, o)
    s = step(
        s,
        a.OrderUpdate(
            "simnow-test", o.order_id, T + timedelta(minutes=62), "cancel", "CANCELLED"
        ),
    ).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=63),
            complete=False,
            orders=(h.OrderReport(o.order_id, "CANCELLED"),),
            settled=(o.order_id,),
        ),
    ).state
    assert not s.readback_valid and not s.reservations[0].released


def test_foreign_order_even_when_terminal_blocks_account():
    s = step(
        initial(),
        readback(
            T + timedelta(seconds=1), orders=(h.OrderReport("foreign", "FILLED"),)
        ),
    ).state
    assert s.phase == "BLOCKED"


def test_forged_coverage_cannot_cover_another_order_or_exceed_native_freeze():
    with pytest.raises(ValueError, match="COVERAGE_EXCEEDS_NATIVE_FROZEN"):
        readback(coverage=(a.Coverage("other", D("1"), D("0")),))
    s = step(initial(), sig()).state
    tx = tick(s)
    rb = readback(
        T + timedelta(minutes=62),
        frozen="1000",
        coverage=(a.Coverage("other", D("1000"), D("0")),),
    )
    with pytest.raises(ValueError, match="COVERAGE_IDENTITY_INVALID"):
        step(tx.state, rb)


def test_unknown_native_readback_does_not_release_reservation():
    s = step(initial(), sig()).state
    tx = tick(s)
    o = tx.effects[0].order
    s = step(
        tx.state,
        readback(
            T + timedelta(minutes=62), orders=(h.OrderReport(o.order_id, "UNKNOWN"),)
        ),
    ).state
    assert not s.readback_valid and not s.reservations[0].released


def test_fill_without_post_fill_native_readback_retains_reservation():
    s, o, f = open_position()
    assert not s.reservations[0].released
    assert s.positions[0].quantity == 1
    assert settle_position(s, o, f).reservations[0].released


def test_late_second_open_fill_is_retained_and_blocked_instead_of_two_lot_projection():
    s = step(initial(), sig()).state
    tx = tick(s)
    old = tx.effects[0].order
    s = accepted(tx.state, old)
    s = tick(s, 64, second=1).state
    s = step(
        s,
        a.OrderUpdate(
            "simnow-test",
            old.order_id,
            T + timedelta(minutes=65),
            "cancel",
            "CANCELLED",
        ),
    ).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=66),
            orders=(h.OrderReport(old.order_id, "CANCELLED"),),
            settled=(old.order_id,),
        ),
    ).state
    tx = tick(s, 67)
    new = tx.effects[0].order
    f = h.Fill(
        "new-fill",
        new.order_id,
        "simnow-test",
        new.contract,
        T + timedelta(minutes=68),
        T + timedelta(minutes=68, seconds=1),
        new.price,
        D("3"),
        1,
    )
    s = step(tx.state, f).state
    late = h.Fill(
        "late-over-capacity",
        old.order_id,
        "simnow-test",
        old.contract,
        T + timedelta(minutes=62),
        T + timedelta(minutes=69),
        old.price,
        D("3"),
        1,
    )
    s = step(s, late).state
    assert (
        s.phase == "BLOCKED"
        and late in s.fills
        and late.trade_id in s.unresolved_fill_ids
    )
    assert (
        s.positions[0].quantity == 1
    )  # only the explained projection, not an invented net of two
    assert a.restore(a.checkpoint(s)).phase == "BLOCKED"


def test_missing_recovery_input_blocks_that_product_and_no_historical_open():
    s = step(initial(), a.Disconnect(T + timedelta(seconds=1))).state
    s = step(s, a.Recover(readback(T + timedelta(minutes=60, seconds=3)), ())).state
    assert set(s.blocked_products) == {"RB", "JM"}
    assert tick(s, 61).effects == ()


def test_account_freshness_expiry_blocks_even_close_until_native_readback():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = step(
        s, sig(direction="sell", minute=120, previous=T + timedelta(minutes=60))
    ).state
    s = replace(
        s,
        readback=replace(
            s.readback, valid_until=T + timedelta(minutes=120, seconds=10)
        ),
    )
    tx = tick(s, 121)
    assert tx.effects == () and not tx.state.readback_valid


def test_updated_direction_during_close_controls_next_open():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = step(
        s, sig(direction="sell", minute=120, previous=T + timedelta(minutes=60))
    ).state
    tx = tick(s, 121)
    close = tx.effects[0].order
    s = step(
        tx.state, sig(direction="buy", minute=180, previous=T + timedelta(minutes=120))
    ).state
    cf = h.Fill(
        "closed-after-update",
        close.order_id,
        "simnow-test",
        close.contract,
        T + timedelta(minutes=181),
        T + timedelta(minutes=181, seconds=1),
        close.price,
        D("3"),
        1,
    )
    s = step(s, cf).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=182),
            orders=(h.OrderReport(close.order_id, "FILLED"),),
            trades=(f.trade_id, cf.trade_id),
        ),
    ).state
    assert tick(s, 183).effects[0].order.side == "BUY"


def test_recovery_opposite_direction_only_closes_and_never_reverse_opens():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = a.restore(a.checkpoint(s))
    rb = readback(
        T + timedelta(minutes=120, seconds=3),
        available="99000",
        used="1000",
        positions=s.positions,
        orders=(h.OrderReport(o.order_id, "FILLED"),),
        trades=(f.trade_id,),
    )
    s = step(
        s,
        a.Recover(
            rb,
            (
                h.RecoveryInput(
                    "RB", "RB2701", -1, T + timedelta(minutes=120), "latest"
                ),
                h.RecoveryInput(
                    "JM", "JM2701", 0, T + timedelta(minutes=120), "latest-jm"
                ),
            ),
        ),
    ).state
    tx = tick(s, 121)
    close = tx.effects[0].order
    assert close.offset == "CLOSE"
    cf = h.Fill(
        "recovery-close",
        close.order_id,
        "simnow-test",
        close.contract,
        T + timedelta(minutes=122),
        T + timedelta(minutes=122, seconds=1),
        close.price,
        D("3"),
        1,
    )
    s = step(tx.state, cf).state
    s = step(
        s,
        readback(
            T + timedelta(minutes=123),
            orders=(h.OrderReport(close.order_id, "FILLED"),),
            trades=(f.trade_id, cf.trade_id),
        ),
    ).state
    assert tick(s, 124).effects == ()


def test_rollover_closes_actual_old_contract_never_new_contract_price():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = step(s, h.Owner("RB", "RB2705", T + timedelta(minutes=63), "new-owner")).state
    at = T + timedelta(minutes=64)
    oldfacts = facts(at, price="1000")
    newer = a.ExecutionInput(
        replace(oldfacts.instrument, contract="RB2705"),
        replace(oldfacts.session, contract="RB2705"),
        replace(oldfacts.quote, contract="RB2705", bid=D("5000"), ask=D("5001")),
    )
    tx = tick(s, 64, inputs=(oldfacts, newer))
    assert tx.effects[0].order.contract == "RB2701" and tx.effects[0].order.price == D(
        "999"
    )
    assert tx.effects[0].order.offset == "CLOSE"
    assert (
        tick(tx.state, 65).effects == () and tx.state.positions[0].contract == "RB2701"
    )


def test_quote_and_instrument_require_decimal_no_float_and_valid_tick():
    at = T + timedelta(minutes=61)
    with pytest.raises(ValueError):
        replace(facts(at).instrument, tick_size=0.5)
    with pytest.raises(ValueError):
        replace(facts(at).quote, ask=D("NaN"))
    s = step(initial(), sig()).state
    f = replace(facts(at), instrument=replace(facts(at).instrument, tick_size=D("3")))
    assert tick(s, inputs=(f,)).effects == ()


def test_command_identity_conflict_is_rejected_without_mutating_original():
    s = initial()
    tx = step(s, sig(), "same")
    with pytest.raises(ValueError, match="COMMAND_IDENTITY_CONFLICT"):
        step(tx.state, sig(direction="sell"), "same")
    assert tx.state.signals == (sig(),)


def test_checkpoint_damage_and_version_drift_fail_closed():
    import json

    s = step(initial(), sig()).state
    payload = a.checkpoint(s)
    packet = json.loads(payload)
    packet["body"]["risk"] = "other"
    with pytest.raises(ValueError, match="ACCOUNT_CHECKPOINT_INVALID"):
        a.restore(json.dumps(packet))


def test_time_regression_is_not_hidden_as_new_signal():
    s = step(initial(), sig(minute=120)).state
    with pytest.raises(ValueError, match="COMMAND_TIME_REGRESSION"):
        step(s, sig(minute=60))


def test_mismatched_recovery_contract_cannot_create_close_obligation():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = a.restore(a.checkpoint(s))
    rb = readback(
        T + timedelta(minutes=120, seconds=3),
        available="99000",
        used="1000",
        positions=s.positions,
        orders=(h.OrderReport(o.order_id, "FILLED"),),
        trades=(f.trade_id,),
    )
    s = step(
        s,
        a.Recover(
            rb,
            (
                h.RecoveryInput(
                    "RB", "RB2705", -1, T + timedelta(minutes=120), "wrong-contract"
                ),
            ),
        ),
    ).state
    assert "RB" in s.blocked_products
    assert not next(p for p in s.products if p.product == "RB").must_close
    assert tick(s, 121).effects == ()


def test_normal_filled_callback_is_not_a_fault_or_historical_reversal_recovery():
    s, o, f = open_position()
    s = settle_position(s, o, f)
    s = step(
        s, sig(direction="sell", minute=120, previous=T + timedelta(minutes=60))
    ).state
    tx = tick(s, 121)
    closing = tx.effects[0].order
    now = T + timedelta(minutes=122)
    s = step(
        tx.state,
        a.OrderUpdate(
            "simnow-test", closing.order_id, now, "native-close-filled", "FILLED"
        ),
    ).state
    assert not s.readback_valid
    actual = h.Fill(
        "close-native",
        closing.order_id,
        "simnow-test",
        closing.contract,
        now,
        now + timedelta(seconds=1),
        closing.price,
        D(3),
        1,
    )
    s = step(s, actual).state
    s = step(
        s,
        readback(
            now + timedelta(seconds=2),
            orders=(
                h.OrderReport(o.order_id, "FILLED"),
                h.OrderReport(closing.order_id, "FILLED"),
            ),
            trades=(f.trade_id, actual.trade_id),
        ),
    ).state
    assert s.phase == "READY" and s.readback_valid
    assert tick(s, 123).effects[0].order.offset == "OPEN"
