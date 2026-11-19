from dataclasses import replace
from decimal import Decimal as D
from itertools import groupby

import pytest

from guiyi_quant.subing_one_lot.portfolio import Portfolio, Segment, replay
from tests.unit.subing_one_lot.test_policy import fixture


def segment(product, prices, *, multiplier=60, ratio=".1", next_day_at=None):
    xs, observations, schedule, structures = fixture(
        prices,
        {0: {"near_zero_golden": True}},
        next_day_at=next_day_at,
    )
    contract = product.upper() + "2609"
    xs = tuple(
        replace(
            x,
            bar=replace(
                x.bar,
                product=product,
                physical_contract=contract,
                source_identity=f"{product}:{x.bar.source_identity}",
            ),
            facts=replace(
                x.facts,
                physical_contract=contract,
                multiplier=D(multiplier),
                long_margin_ratio=D(ratio),
            ),
        )
        for x in xs
    )
    for row in observations.values():
        row["contract"] = contract
    return Segment(product, xs, observations, structures, schedule)


def test_simultaneous_intents_share_one_account_and_replay_deterministically():
    segments = [segment(p, [100, 101, 102]) for p in ("rb", "jm")]
    result = replay(segments, "combo")
    assert result == replay(list(reversed(segments)), "combo")
    fills = [
        fill for account in result["accounts"].values() for fill in account["fills"]
    ]
    assert len(fills) == 2 and all(fill["quantity"] == 1 for fill in fills)
    assert all(fill["decision_at"] < fill["fill_at"] for fill in fills)
    assert D(result["cash"]) == D("1000000") - sum(D(fill["fee"]) for fill in fills)


def test_shared_margin_reserves_pending_orders_in_fixed_order():
    segments = [
        segment(p, [100, 101, 102], multiplier=60, ratio="1")
        for p in ("rb", "jm", "lc")
    ]
    segments = [
        replace(
            s,
            executions=tuple(
                replace(
                    x,
                    facts=replace(
                        x.facts, prev_settlement=D("5000"), limit_up=D("6000")
                    ),
                )
                for x in s.executions
            ),
        )
        for s in segments
    ]
    result = replay(segments, "margin")
    assert result["accounts"]["JM2609"]["summary"]["fill_count"] == 1
    assert result["accounts"]["LC2609"]["summary"]["fill_count"] == 1
    assert result["accounts"]["RB2609"]["summary"]["fill_count"] == 0
    assert D(result["margin"]) == D("600000")


def test_cross_product_floating_loss_latches_exits_and_does_not_create_fills():
    segments = [segment(p, [200, 201, 10, 9]) for p in ("rb", "jm")]
    portfolio = Portfolio(segments, "halt")
    rows = sorted(
        ((x, s.observations[x.bar.bar_end]) for s in segments for x in s.executions),
        key=lambda row: row[0].bar.bar_end,
    )
    batches = [
        list(batch) for _, batch in groupby(rows, key=lambda row: row[0].bar.bar_end)
    ]
    for batch in batches[:3]:
        portfolio.step_batch(batch)
    assert portfolio.halted
    assert portfolio.exit_owed == {"JM2609", "RB2609"}
    assert all(a.model.pending["kind"] == "CLOSE" for a in portfolio.accounts.values())
    assert all(len(a.fills) == 1 for a in portfolio.accounts.values())
    portfolio.step_batch(batches[-1])
    result = portfolio.snapshot()
    assert not result["pending_exit_contracts"]
    assert all(
        [f["action"] for f in a["fills"]] == ["OPEN", "CLOSE"]
        for a in result["accounts"].values()
    )
    assert result["risk_records"][0]["reason"] == "PORTFOLIO_DAILY_LOSS"


def test_one_trade_budget_rejects_plan_before_order():
    large = segment("rb", [100, 101, 102], multiplier=500)
    result = replay([large], "budget")
    row = result["accounts"]["RB2609"]
    assert not row["fills"]
    assert any(
        "PLANNED_STOP_RISK_OVER_BUDGET" in action["reasons"]
        for decision in row["decisions_with_actions"]
        for action in decision["actions"]
    )


def test_unfilled_portfolio_exit_persists_into_next_trading_day():
    segments = [segment(p, [200, 201, 10, 9, 8], next_day_at=4) for p in ("rb", "jm")]
    segments = [
        replace(
            s,
            executions=tuple(
                replace(x, bar=replace(x.bar, volume=D(0))) if i == 3 else x
                for i, x in enumerate(s.executions)
            ),
        )
        for s in segments
    ]
    result = replay(segments, "overnight")
    assert not result["pending_exit_contracts"]
    for row in result["accounts"].values():
        assert row["execution_events"][0]["kind"] == "UNFILLED"
        assert [f["action"] for f in row["fills"]] == ["OPEN", "CLOSE"]
        assert row["fills"][0]["trading_day"] < row["fills"][1]["trading_day"]


def test_partial_batch_failure_requires_replaying_the_whole_portfolio():
    jm, rb = [segment(p, [100, 101, 102]) for p in ("jm", "rb")]
    portfolio = Portfolio([jm, rb], "failure")
    x, z = jm.executions[0], rb.executions[0]
    invalid = dict(rb.observations[z.bar.bar_end], close="999")
    with pytest.raises(ValueError, match="ACCOUNT_OBSERVATION_IDENTITY"):
        portfolio.step_batch([(x, jm.observations[x.bar.bar_end]), (z, invalid)])
    next_bar = jm.executions[1]
    with pytest.raises(ValueError, match="PORTFOLIO_REPLAY_REQUIRED"):
        portfolio.step_batch([(next_bar, jm.observations[next_bar.bar.bar_end])])
    with pytest.raises(ValueError, match="PORTFOLIO_REPLAY_REQUIRED"):
        portfolio.snapshot()


def test_projected_cost_cannot_cross_remaining_day_budget():
    jm = segment("jm", [100, 101])
    portfolio = Portfolio([jm], "last-budget")
    first, second = jm.executions
    portfolio.step_batch([(first, jm.observations[first.bar.bar_end])])
    portfolio.day_start = portfolio.equity() + D("19990")
    portfolio.step_batch([(second, jm.observations[second.bar.bar_end])])
    result = portfolio.snapshot()
    assert not result["accounts"]["JM2609"]["fills"]
    assert (
        result["accounts"]["JM2609"]["execution_events"][0]["reason"]
        == "OPENING_FINANCIAL_RECHECK"
    )
