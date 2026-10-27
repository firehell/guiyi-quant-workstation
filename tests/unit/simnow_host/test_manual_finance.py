"""Two actual-typed fills and native equity must reconcile before success."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import importlib.util
import json
import pytest

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution.inventory import Snapshot
from guiyi_quant.simnow_execution.manual_host import acceptance

spec = importlib.util.spec_from_file_location(
    "manual_policy_fixtures",
    Path(__file__).parents[1] / "htdy_execution/test_manual_policy.py",
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def completed():
    state, opening = f.opened()
    state, fill = f.confirmed_open(state, opening)
    due = a.manual_status(state, f.TEST_ID).due_at
    tx = f.manual_tick(state, due)
    closing = tx.effects[0].order
    fill2 = f.native_fill(closing, due + timedelta(seconds=2), trade_id="native-close")
    state = f.apply(tx.state, fill2).state
    rb = f.readback(
        due + timedelta(seconds=5),
        orders=(
            h.OrderReport(opening.order_id, "FILLED"),
            h.OrderReport(closing.order_id, "FILLED"),
        ),
        trades=(fill.trade_id, fill2.trade_id),
    )
    rb = replace(
        rb,
        snapshot=replace(
            rb.snapshot, balance=Decimal("99984"), available=Decimal("99984")
        ),
    )
    return f.apply(state, rb).state


def snapshot(state, balance, fees, closed, *, cashflow="0"):
    payload = dict(
        positions=[],
        orders=[],
        funds=[
            dict(
                Balance=balance,
                Commission=fees,
                CloseProfit=closed,
                PositionProfit="0",
                Deposit=cashflow,
                Withdraw="0",
            )
        ],
    )
    return Snapshot(
        state.account_id,
        "20261027",
        state.readback.at - timedelta(seconds=1),
        state.readback.at,
        state.readback.source_id,
        json.dumps(payload),
    )


def test_actual_roundtrip_requires_native_equity_and_fee_readback():
    state = completed()
    baseline = snapshot(state, "100000", "0", "0")
    final = snapshot(state, "99984", "6", "-10")
    result = acceptance(state, final, f.TEST_ID, baseline=baseline)
    assert result["broker_roundtrip_passed"]
    assert result["equity_reconciled"] and result["fees_reconciled"]
    assert result["expected_net_profit"] == "-16"
    for bad in (
        snapshot(state, "99985", "6", "-10"),
        snapshot(state, "99984", "5", "-10"),
        snapshot(state, "99984", "6", "-9"),
        snapshot(state, "99984", "6", "-10", cashflow="1"),
    ):
        assert not acceptance(state, bad, f.TEST_ID, baseline=baseline)[
            "broker_roundtrip_passed"
        ]
    assert not acceptance(state, final, f.TEST_ID)["broker_roundtrip_passed"]
    encumbered = replace(
        state, readback=replace(state.readback, frozen_margin=Decimal("1"))
    )
    assert not acceptance(encumbered, final, f.TEST_ID, baseline=baseline)[
        "broker_roundtrip_passed"
    ]


@pytest.mark.parametrize(
    "noise,allowed",
    [
        ("0.0000000001", True),
        ("-0.0000000001", True),
        ("0.00000001", True),
        ("-0.00000001", True),
        ("0.0000001", False),
        ("-0.0000001", False),
        ("0.01", False),
        ("-0.01", False),
    ],
)
def test_native_counter_binary_residual_does_not_rewrite_money(noise, allowed):
    state = completed()
    baseline = snapshot(state, "100000", "0", "0")
    balance = Decimal("99984") + Decimal(noise)
    rb = replace(
        state.readback,
        snapshot=replace(state.readback.snapshot, balance=balance, available=balance),
    )
    state = replace(state, readback=rb)
    final = snapshot(state, str(balance), "6", "-10")
    result = acceptance(state, final, f.TEST_ID, baseline=baseline)
    assert result["broker_roundtrip_passed"] is allowed
    assert Decimal(result["equity_residual"]) == Decimal(noise)
    assert result["equity"] == str(balance) and result["actual_fees"] == "6"
    assert result["expected_net_profit"] == "-16"
    available_state = replace(
        state,
        readback=replace(
            rb,
            snapshot=replace(rb.snapshot, balance=Decimal("99984"), available=balance),
        ),
    )
    result2 = acceptance(
        available_state,
        snapshot(available_state, "99984", "6", "-10"),
        f.TEST_ID,
        baseline=baseline,
    )
    assert result2["broker_roundtrip_passed"] is allowed
    assert Decimal(result2["available_residual"]) == Decimal(noise)
