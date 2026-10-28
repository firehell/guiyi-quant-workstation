"""Versioned continuous trade policy, isolated account facts only."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import pytest
from guiyi_quant import htdy_account_execution as a
from guiyi_quant.htdy_account_execution.codec import checkpoint, load
from test_continuous_policy import initial, signal, step, fact, T


def test_trade_tick_opens_one_global_candidate_in_chronological_order():
    state = initial()
    state = step(state, signal("RB", minute=60)).state
    state = step(state, signal("JM", minute=61)).state
    at = T + timedelta(minutes=62)
    tx = step(state, a.ContinuousTradeTickV1(at, (fact("JM", at), fact("RB", at))))
    assert [e.order.product for e in tx.effects] == ["RB"]
    assert len(tx.state.reservations) == 1
    again = step(
        tx.state,
        a.ContinuousTradeTickV1(
            at + timedelta(seconds=1),
            (
                fact("JM", at + timedelta(seconds=1)),
                fact("RB", at + timedelta(seconds=1)),
            ),
        ),
    )
    assert again.effects == () and len(again.state.reservations) == 1
    assert load(checkpoint(again.state)) == again.state


def test_trade_cap_rejection_is_permanent_while_later_product_can_open():
    state = initial()
    state = step(state, signal("RB", minute=60)).state
    state = step(state, signal("JM", minute=61)).state
    at = T + timedelta(minutes=62)
    rb = fact("RB", at)
    rb = replace(rb, instrument=replace(rb.instrument, multiplier=D(1000)))
    tx = step(state, a.ContinuousTradeTickV1(at, (rb, fact("JM", at))))
    assert [e.order.product for e in tx.effects] == ["JM"]
    assert tx.state.risk_decisions[0].reason == "MARGIN_CAP"
    assert "signal:RB:60" in tx.state.abandoned


def test_trade_command_is_fixed_version_and_manage_remains_closed():
    state = step(initial(), signal("RB")).state
    at = T + timedelta(minutes=61)
    assert step(state, a.ManagedTickV1(at, (fact("RB", at),))).effects == ()
    with pytest.raises(ValueError):
        a.ContinuousTradeTickV1(at, (), policy_version="changed")


@pytest.mark.parametrize("multiplier,allowed", [(D(700), True), (D("700.01"), False)])
def test_trade_exact_seventy_percent_boundary(multiplier, allowed):
    state = step(initial(), signal("RB")).state
    at = T + timedelta(minutes=61)
    source = fact("RB", at)
    source = replace(
        source, instrument=replace(source.instrument, multiplier=multiplier)
    )
    tx = step(state, a.ContinuousTradeTickV1(at, (source,)))
    assert bool(tx.effects) is allowed
    assert tx.state.risk_decisions[-1].approved is allowed
    assert bool(tx.state.abandoned) is not allowed
