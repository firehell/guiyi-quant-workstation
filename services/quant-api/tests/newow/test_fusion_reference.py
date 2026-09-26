from dataclasses import replace
from decimal import Decimal
import pytest
from guiyi_quant.newow.fusion_reference import fusion_reference_comparison
from guiyi_quant.newow.reference_statistics import PerformanceWindow
from guiyi_quant.newow.product_contracts import TradeEligibility


def sources(cases, trend_actions, oscillation_actions):
    trend = cases.closed()
    osc = cases.closed(strategy="oscillation")
    t = trend_actions(trend)
    o = oscillation_actions(osc)
    return cases.replay(
        trend.identity, trend.bars, t, ("BUILD", "CLEAR")
    ), cases.replay(osc.identity, trend.bars, o, ("BUILD", "CLEAR"))


def project(t, o, cutoff=None, boundaries=(), interruptions=()):
    end = cutoff or t.frames[-1].bar.bar.bar_end
    return fusion_reference_comparison(
        t,
        o,
        boundaries,
        interruptions,
        PerformanceWindow(t.frames[0].bar.bar.trading_day, end.date(), end),
    )


def test_oscillation_price_priority_and_decimal(product_cases):
    t, o = sources(
        product_cases,
        lambda c: (c.entry, c.exit),
        lambda c: (
            replace(c.entry, reference_price=Decimal("90")),
            replace(c.exit, reference_price=Decimal("108")),
        ),
    )
    result = project(t, o)
    row = result["items"][0]
    assert row["entry_source"] == row["exit_source"] == "oscillation"
    assert Decimal(row["reference_return_pct"]) == Decimal("20")
    assert row["entry_reference_price"] == "90"
    assert (
        result["groups"][0]["sum_return_percentage_points"]
        != result["groups"][2]["sum_return_percentage_points"]
    )


def test_cross_strategy_clear_without_own_entry(product_cases):
    t, o = sources(
        product_cases,
        lambda c: (c.entry,),
        lambda c: (
            replace(c.entry, trade_eligibility=TradeEligibility.WARMUP_ONLY),
            replace(
                c.exit,
                related_build_id=replace(
                    c.entry, trade_eligibility=TradeEligibility.WARMUP_ONLY
                ).signal_id,
                trade_eligibility=TradeEligibility.NO_ELIGIBLE_ENTRY,
            ),
        ),
    )
    row = project(t, o)["items"][0]
    assert row["status"] == "CLOSED"
    assert (row["entry_source"], row["exit_source"]) == ("trend", "oscillation")
    assert Decimal(row["reference_return_pct"]) == 10


def test_same_bar_clear_then_build_and_no_terminal_force_close(product_cases):
    t, o = sources(
        product_cases,
        lambda c: (c.entry, c.exit),
        lambda c: (
            replace(
                c.entry,
                bar_end=c.exit.bar_end,
                trading_day=c.exit.trading_day,
                reference_price=Decimal("105"),
            ),
        ),
    )
    result = project(t, o)
    assert [r["status"] for r in result["items"]] == ["OPEN", "CLOSED"]
    assert result["items"][0]["entry_source"] == "oscillation"
    assert result["groups"][2]["closed_count"] == 1
    assert result["groups"][2]["open_count"] == 1


def test_initial_clear_is_not_a_trade(product_cases):
    t, o = sources(
        product_cases,
        lambda c: (),
        lambda c: (
            replace(c.entry, trade_eligibility=TradeEligibility.WARMUP_ONLY),
            replace(
                c.exit,
                related_build_id=replace(
                    c.entry, trade_eligibility=TradeEligibility.WARMUP_ONLY
                ).signal_id,
                trade_eligibility=TradeEligibility.NO_ELIGIBLE_ENTRY,
            ),
        ),
    )
    assert project(t, o)["items"] == []


def test_cutoff_does_not_use_future_clear(product_cases):
    t, o = sources(product_cases, lambda c: (c.entry, c.exit), lambda c: ())
    row = project(t, o, t.actions[0].bar_end)["items"][0]
    assert row["status"] == "OPEN"
    assert row["reference_trade_id"] == project(t, o)["items"][0]["reference_trade_id"]


def test_mismatched_input_rejected(product_cases):
    t, o = sources(product_cases, lambda c: (c.entry, c.exit), lambda c: ())
    bad = replace(o, frames=o.frames[:1])
    with pytest.raises(ValueError, match="INPUT_CONFLICT"):
        project(t, bad)


def test_overlapping_new_owner_prewarm_does_not_interrupt_old_trade(product_cases):
    from datetime import timedelta

    t, o = sources(product_cases, lambda c: (c.entry, c.exit), lambda c: ())
    frame = t.frames[0]
    prewarm = replace(
        frame,
        actions=(),
        bar=replace(
            frame.bar,
            bar=replace(
                frame.bar.bar,
                physical_contract="RB2610",
                segment_id="new-owner",
                bar_end=frame.bar.bar.bar_end + timedelta(hours=1),
                observation_eligible=False,
            ),
            calculation_segment_id="new-owner",
        ),
    )
    t = replace(t, frames=(*t.frames, prewarm))
    o = replace(o, frames=(*o.frames, prewarm))
    row = project(t, o, t.actions[-1].bar_end)["items"][0]
    assert row["status"] == "CLOSED"
    assert row["holding_bars"] == 1
    assert Decimal(row["reference_return_pct"]) == 10


def test_authoritative_rollover_interrupts_without_realized_return(product_cases):
    from guiyi_quant.newow.product_adapters import build_product_identity

    c = product_cases.interrupted()
    o = product_cases.replay(
        build_product_identity("rb", "oscillation", "1d"), c.bars, (), ("FLAT", "FLAT")
    )
    r = project(c.replay, o, c.as_of, c.boundaries)["items"][0]
    assert r["status"] == "ROLLOVER_INTERRUPTED"
    assert r["reference_return_pct"] is None
    assert Decimal(r["mark_change_pct"]) == -10


def test_data_interruption_separates_mark_from_realized_return(product_cases):
    from guiyi_quant.newow.product_contracts import DataInterruption
    from datetime import timedelta

    t, o = sources(product_cases, lambda c: (c.entry,), lambda c: ())
    bar = t.frames[0].bar.bar
    gap = DataInterruption(
        "rb",
        "1d",
        bar.physical_contract,
        bar.segment_id,
        bar.trading_day,
        bar.bar_end + timedelta(hours=1),
        "proven-gap",
    )
    r = project(t, o, interruptions=(gap,))["items"][0]
    assert r["status"] == "DATA_INTERRUPTED"
    assert r["reference_return_pct"] is None
    assert r["mark_bar_end"] == bar.bar_end.isoformat()


def test_pagination_and_window_do_not_repair_single_trade_returns(product_cases):
    t, o = sources(product_cases, lambda c: (c.entry, c.exit), lambda c: ())
    whole = project(t, o)
    end = t.actions[-1].bar_end
    narrowed = fusion_reference_comparison(
        t, o, (), (), PerformanceWindow(end.date(), end.date(), end)
    )
    assert (
        narrowed["items"][0]["reference_return_pct"]
        == whole["items"][0]["reference_return_pct"]
    )
    assert (
        narrowed["items"][0]["reference_trade_id"]
        == whole["items"][0]["reference_trade_id"]
    )
    assert narrowed["groups"][2]["closed_count"] == 0
    assert narrowed["items"][0]["statistics_membership"] == "initial_before_window"
