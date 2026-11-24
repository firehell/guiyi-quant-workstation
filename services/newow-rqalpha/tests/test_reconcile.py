from dataclasses import replace

import pytest

from reconcile import ReconciliationError, reconcile
from runner import run_proof
from test_minute_execution import D, DAY_1, DAY_2, market, signal


def replay(source, signals, initial="1000", **kwargs):
    result = run_proof(source, signals, D(initial), **kwargs)
    for settlement in result["settlements"]:
        settlement["last_bar_close"] = next(
            bar.close for bar in reversed(source.minutes) if bar.day == settlement["day"]
        )
    decisions = {item.signal_id: {"decision_id": item.signal_id} for item in signals}
    return result, decisions


def fu_market():
    source = market()
    minutes = tuple(
        replace(row, open=price, high=price, low=price, close=price)
        for row in source.minutes
        for price in (D("2485") if row.end.minute < 12 else D("2480"),)
    )
    facts = replace(
        source.daily[0], prev_settlement=D("2456"), settlement=D("2461"),
        limit_down=D("2284"), limit_up=D("2627"), fee_type="by_money",
        open_fee=D("0.00005"), close_fee=D("0.00005"), close_today_fee=D("0"),
        long_margin=D("0.09"), short_margin=D("0.09"),
    )
    return replace(source, daily=(facts,), minutes=minutes)


def test_fu_open_fee_matches_the_native_bits_and_decimal_economics():
    result, decisions = replay(fu_market(), (signal(5), signal(10, "CLEAR")), initial="10000")
    ledger = reconcile(result, decisions=decisions)
    opening, closing = ledger["trades"]
    assert opening["price"] == "2485.00000000"
    assert opening["fee"] == "1.24250000"
    assert opening["native_amounts"]["commission"] == {
        "repr": "1.2425000000000002", "hex": "0x1.3e147ae147ae2p+0",
    }
    assert opening["close_today_quantity"] == 0
    assert opening["native_close_today_amount"] == 1
    assert closing["fee"] == "0.00000000"
    assert closing["entry_seq"] == 1
    assert closing["gross_pnl"] == "-50.00000000"
    assert closing["net_pnl"] == "-51.24250000"
    assert opening["signal_bar_end"].endswith("09:05:00+08:00")
    assert opening["signal_available_at"].endswith("09:05:02+08:00")
    assert opening["modeled_fill_at"].endswith("09:06:00+08:00")
    assert opening["native_fill_event_at"].endswith("09:07:00+08:00")
    assert opening["decision"] == {"decision_id": opening["signal_id"]}
    assert ledger["summary"]["final_equity"] == "9948.75750000"
    assert ledger["summary"]["net_equity_change"] == "-51.24250000"
    assert [row["equity"] for row in ledger["equity"]] == ["10000.00000000", "9948.75750000"]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda raw: raw["fills"][0].update(commission=1.2425), "NATIVE_TRADE_MISMATCH"),
        (lambda raw: raw["daily_facts"][0].update(open_fee=D("0.00005001")), "NATIVE_TRADE_MISMATCH"),
        (lambda raw: raw["fills"][1].update(price=2480.01), "NATIVE_TRADE_MISMATCH"),
        (lambda raw: raw["settlements"][0]["after"].update(equity=9948.75750001), "NATIVE_MONEY_MISMATCH"),
        (lambda raw: raw["settlements"][0].pop("last_bar_close"), "SETTLEMENT_TRACE_MISSING"),
        (lambda raw: raw["daily_facts"][0].pop("close_today_fee"), "DAILY_FACTS_MISSING"),
    ],
)
def test_native_or_frozen_fact_mismatch_is_not_absorbed_by_tolerance(mutation, code):
    result, decisions = replay(fu_market(), (signal(5), signal(10, "CLEAR")), initial="10000")
    mutation(result)
    with pytest.raises(ReconciliationError, match=code):
        reconcile(result, decisions=decisions)


def test_fee_precision_must_be_lossless_at_the_published_quantum():
    source = fu_market()
    source = replace(source, daily=(replace(source.daily[0], open_fee=D("0.000050000001")),))
    result, decisions = replay(source, (signal(5), signal(10, "CLEAR")), initial="10000")
    with pytest.raises(ReconciliationError, match="MONEY_SCALE_UNSUPPORTED"):
        reconcile(result, decisions=decisions)


def test_cross_day_settlement_then_close_uses_original_entry_for_lifetime_pnl():
    source = market((DAY_1, DAY_2), close_today_fee="4", changes={(DAY_2, 7): "103"})
    result, decisions = replay(source, (signal(5), signal(5, "CLEAR", day=DAY_2)))
    ledger = reconcile(result, decisions=decisions)
    day_1, day_2 = ledger["equity"][1:]
    assert (day_1["equity"], day_1["cash"], day_1["margin"]) == (
        "1008.00000000", "907.00000000", "101.00000000",
    )
    assert day_1["unrealized_pnl"] == "10.00000000"
    assert day_2["unrealized_pnl"] == "0.00000000"
    close = ledger["trades"][-1]
    assert close["position_effect"] == "CLOSE"
    assert close["fee"] == "3.00000000"
    assert close["gross_pnl"] == "30.00000000"
    assert close["net_pnl"] == "25.00000000"
    assert day_2["equity"] == "1025.00000000"


def test_failed_exit_and_initial_clear_do_not_add_a_fill():
    source = market(changes={(DAY_1, 17): "90"})
    result, decisions = replay(source, (signal(5, "CLEAR"), signal(10), signal(15, "CLEAR")))
    ledger = reconcile(result, decisions=decisions)
    assert len(ledger["trades"]) == 1
    assert ledger["trades"][0]["position_effect"] == "OPEN"
    assert ledger["summary"]["terminal_status"] == "OPEN_MARKED_AT_SETTLEMENT"
    assert ledger["summary"]["terminal_position"]["settlement_price"] == "101.00000000"
    assert ledger["summary"]["terminal_position"]["quantity"] == 1
    assert ledger["summary"]["closed_trade_count"] == 0
    assert len(ledger["summary"]["attempts"]) == 3


def test_short_round_trip_and_rollover_interrupt_remain_distinct():
    source = market(changes={(DAY_1, 7): "103", (DAY_1, 12): "100"}, close_today_fee="4")
    result, decisions = replay(source, (signal(5, direction="SHORT"), signal(10, "CLEAR")))
    assert reconcile(result, decisions=decisions)["trades"][-1]["net_pnl"] == "24.00000000"

    interrupted, decisions = replay(source, (signal(5),), rollover_boundary=True)
    with pytest.raises(ReconciliationError, match="ROLLOVER_INTERRUPTED"):
        reconcile(interrupted, decisions=decisions)
