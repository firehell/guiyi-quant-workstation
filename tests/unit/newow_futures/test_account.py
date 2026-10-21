from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.new_subing import ExecutionFacts
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.newow_futures.account import Account


AT = datetime(2026, 10, 9, 2, tzinfo=timezone.utc)


def facts(day=date(2026, 10, 9), margin=".1", multiplier="10"):
    return ExecutionFacts("RB2701", day, D("1"), D(multiplier), D("100"),
                          D(margin), D(margin), D("150"), D("50"),
                          FeeSchedule(open_rate=D(0), close_rate=D(0), close_today_rate=D(0),
                                      open_per_contract=D("2"), close_per_contract=D("3"),
                                      close_today_per_contract=D("4"), source_id="fee"), "facts")


def test_risk_budget_integer_lots_and_expensive_product_refusal():
    a = Account()
    f = facts()
    assert a.open_quantity(1, D("100"), D("90"), f) == 3  # 500/(100+20+6)
    assert a.open_quantity(1, D("100"), D("90"), facts(multiplier="10000")) == 0
    assert a.cash == D("100000") and a.qty == 0


@pytest.mark.parametrize("side,exit_price,gross", [(1, "110", "300"), (-1, "90", "300")])
def test_both_directions_cash_fees_equity_reconcile(side, exit_price, gross):
    a = Account()
    f = facts()
    a.open(side, 3, D("100"), f, AT, D("90") if side == 1 else D("110"), action="ENTER")
    assert a.cash == D("99994")
    assert a.equity(D(exit_price), f) == D("99994") + D(gross)
    a.close(3, D(exit_price), f, AT, reason="EXIT")
    assert a.cash == D("100282") and a.qty == 0
    assert a.closed_trades[-1]["net_pnl"] == "282"
    assert a.total_fees == D("18")


def test_reduce_latest_added_layer_and_no_fractional_core():
    a = Account()
    f = facts()
    a.open(1, 1, D("100"), f, AT, D("90"), action="ENTER")
    a.open(1, 1, D("110"), f, AT, D("100"), action="ADD")
    assert a.reduce_quantity() == 1
    a.close(1, D("115"), f, AT, reason="LOWER_TIMEFRAME_WEAKNESS", reduce=True)
    assert len(a.layers) == 1 and a.layers[0].entry_price == D("100")
    assert a.reduce_quantity() == 0 and a.round_reduced
    assert a.open_quantity(1, D("115"), D("100"), f, add=True) == 0


def test_close_previous_day_uses_dated_fee_and_round_budget_not_reset():
    a = Account()
    a.open(1, 1, D("100"), facts(), AT, D("90"), action="ENTER")
    a.close(1, D("100"), facts(day=date(2026, 10, 12)), AT, reason="EXIT")
    assert a.cash == D("99995")
    assert a.closed_trades[0]["net_pnl"] == "-5"


def test_invalid_stop_and_oversized_open_fail_closed():
    a = Account()
    assert a.open_quantity(1, D("100"), D("101"), facts()) == 0
    with pytest.raises(ValueError):
        a.open(1, 100, D("100"), facts(), AT, D("90"), action="ENTER")
    assert a.cash == D("100000") and not a.layers
