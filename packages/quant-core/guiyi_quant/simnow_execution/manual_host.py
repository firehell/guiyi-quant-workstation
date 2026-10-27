"""One owner-requested manual round trip, distinct from strategy signals."""

from datetime import timedelta
from decimal import Decimal
import json
import os
import re

from .. import htdy_account_execution as a
from .inventory import number

# CTP counters are binary doubles, retained verbatim as Decimal strings. This
# comparison bound is one millionth of a cent; no monetary fact is rounded.
COUNTER_RESIDUAL_BOUND = Decimal("0.00000001")


def admission(authority, now):
    """Require one continuous window long enough for holding and exit work."""
    if (
        authority.product != "RB"
        or authority.contract != authority.owner
        or not authority.session.can_trade
        or authority.contiguous_session_end is None
        or authority.contiguous_session_end - now < timedelta(seconds=900)
        or not authority.session.at <= now < authority.session.valid_until
    ):
        raise ValueError("MANUAL_CONTIGUOUS_SESSION_REQUIRED")


def claim_login(folder, test_id, at, account_id):
    """A separate owner task budget, never resets observer attempts or blocks."""
    if (
        re.fullmatch(r"manual:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", test_id)
        is None
    ):
        raise ValueError("MANUAL_TEST_ID_INVALID")
    path = folder / (test_id.replace(":", "-") + "-login.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            dict(
                policy="simnow_manual_roundtrip_v1",
                test_id=test_id,
                account_id=account_id,
                at=at.isoformat(),
                connections=1,
                max_connections=1,
                product="RB",
                side=1,
                quantity=1,
                hold_seconds=600,
            ),
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())


def manual_effects(host, facts, bindings, now, test_id):
    """Persist the manual decision before native action; use existing dispatcher."""
    tx = host.store.execute(
        "manual-tick:" + test_id + ":" + now.isoformat(),
        a.ManualTickV1(now, tuple(facts), test_id),
    )
    pending = tuple(
        a.Effect("CANCEL", order)
        for order in tx.state.orders
        if order.signal_id == test_id
        and order.status == "CANCEL_PENDING"
        and order.cancel_sent
        and not order.reconciled
        and not host.journal.claimed(order.order_id, "CANCEL")
        and all(e.order.order_id != order.order_id for e in tx.effects)
    )
    return host.submit_effects(tx.effects + pending, bindings, facts, now)


def acceptance(state, snapshot, test_id, *, baseline=None):
    """Never infer success from request return codes, timers or empty queries."""
    status = a.manual_status(state, test_id)
    orders = tuple(o for o in state.orders if o.signal_id == test_id)
    opened = tuple(o for o in orders if o.offset == "OPEN")
    closed = tuple(o for o in orders if o.offset == "CLOSE")
    fills = tuple(f for f in state.fills if f.order_id in {o.order_id for o in orders})
    opening_fills = tuple(
        f for f in fills if f.order_id in {o.order_id for o in opened}
    )
    closing_fills = tuple(
        f for f in fills if f.order_id in {o.order_id for o in closed}
    )
    native = snapshot.data
    native_flat = not any(
        p["Position"] or p["LongFrozen"] or p["ShortFrozen"]
        for p in native["positions"]
    )
    no_working = all(o["OrderStatus"] in ("0", "2", "4", "5") for o in native["orders"])
    fee_total = sum((f.fee for f in fills), Decimal(0))
    available_residual = (
        state.readback.snapshot.available - state.readback.snapshot.balance
    )
    capital_released = (
        state.readback.used_margin
        == state.readback.frozen_margin
        == state.readback.frozen_fee
        == 0
        and abs(available_residual) <= COUNTER_RESIDUAL_BOUND
    )
    funds = native["funds"][0]
    fee_matches = False
    equity_matches = False
    expected_net = None
    equity_residual = None
    equity = number(funds["Balance"], True)
    if (
        baseline is not None
        and baseline.account_id == snapshot.account_id
        and baseline.trading_day == snapshot.trading_day
    ):
        before = baseline.data["funds"][0]
        fee_matches = fee_total == number(funds["Commission"]) - number(
            before["Commission"]
        )
        multipliers = {
            fact.instrument.multiplier
            for item in state.audit
            if type(item.command) is a.ManualTickV1 and item.command.test_id == test_id
            for fact in item.command.inputs
            if fact.instrument.contract in {o.contract for o in opened}
        }
        if len(multipliers) == 1 and len(opening_fills) == len(closing_fills) == 1:
            gross = (closing_fills[0].price - opening_fills[0].price) * next(
                iter(multipliers)
            )
            expected_net = gross - fee_total
            equity_residual = equity - number(before["Balance"], True) - expected_net
            equity_matches = (
                all(
                    number(funds[k]) == number(before[k])
                    for k in ("Deposit", "Withdraw")
                )
                and abs(equity_residual) <= COUNTER_RESIDUAL_BOUND
                and state.readback.snapshot.balance == equity
                and number(funds["CloseProfit"], True)
                - number(before["CloseProfit"], True)
                == gross
                and number(funds["PositionProfit"], True) == 0
            )
    passed = bool(
        status.complete
        and state.phase == "READY"
        and state.readback_valid
        and state.readback.source_id == snapshot.source_id
        and not state.positions
        and not state.unresolved_fill_ids
        and all(o.reconciled for o in state.orders)
        and all(r.released for r in state.reservations)
        and len(opened) == 1
        and len(opening_fills) == len(closing_fills) == 1
        and all(type(f) is a.NativeFill for f in fills)
        and status.due_at is not None
        and closed
        and min(o.created_at for o in closed) >= status.due_at
        and native_flat
        and no_working
        and fee_matches
        and equity_matches
        and capital_released
    )
    return dict(
        policy="simnow_manual_roundtrip_v1",
        origin="OWNER_MANUAL_ACCEPTANCE",
        test_id=test_id,
        product="RB",
        broker_roundtrip_passed=passed,
        strategy_signal_e2e_passed=False,
        phase=status.phase,
        due_at=status.due_at.isoformat() if status.due_at else None,
        confirmed_at=status.confirmed_at.isoformat() if status.confirmed_at else None,
        position_projection_complete=state.phase == "READY" and state.readback_valid,
        native_flat_observed=native_flat,
        no_working_orders_observed=no_working,
        actual_fees=str(fee_total),
        fees_reconciled=fee_matches,
        capital_released=capital_released,
        equity=str(equity),
        expected_net_profit=str(expected_net) if expected_net is not None else None,
        equity_reconciled=equity_matches,
        equity_residual=str(equity_residual) if equity_residual is not None else None,
        available_residual=str(available_residual),
        counter_residual_bound=str(COUNTER_RESIDUAL_BOUND),
        native_source_id=snapshot.source_id,
        native_at=snapshot.at.isoformat(),
        orders=[
            dict(
                order_id=o.order_id,
                contract=o.contract,
                side=o.side,
                offset=o.offset,
                status=o.status,
                reconciled=o.reconciled,
                created_at=o.created_at.isoformat(),
            )
            for o in orders
        ],
        fills=[
            dict(
                order_id=f.order_id,
                trade_id=f.trade_id,
                price=str(f.price),
                fee=str(f.fee),
                filled_at=f.filled_at.isoformat(),
                recorded_at=f.recorded_at.isoformat(),
            )
            for f in fills
        ],
    )
