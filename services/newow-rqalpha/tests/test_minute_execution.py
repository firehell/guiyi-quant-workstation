from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from frozen_market import ASIA_SHANGHAI, DailyFacts, FrozenMarket, Minute, Session
from runner import Signal, run_proof

D = Decimal
DAY_1 = date(2026, 1, 5)
DAY_2 = date(2026, 1, 6)


def clock(day, hhmmss):
    return datetime.fromisoformat(f"{day}T{hhmmss}").replace(tzinfo=ASIA_SHANGHAI)


def market(days=(DAY_1,), *, changes=None, close_today_fee="2", contract="FU2603"):
    changes = changes or {}
    minutes, sessions, facts = [], [], []
    for day in days:
        start = clock(day, "09:00:00")
        sessions.append(Session(day, start, start + timedelta(minutes=20)))
        for index in range(1, 21):
            end = start + timedelta(minutes=index)
            price = D(changes.get((day, index), "103" if index >= 12 else "100"))
            minutes.append(Minute(day, end, price, price, price, price, D("8")))
        facts.append(DailyFacts(day, D("99" if day == DAY_1 else "101"), D("101" if day == DAY_1 else "104"),
                               D("90"), D("110"), "by_volume", D("2"), D("3"), D(close_today_fee), D("0.1"), D("0.2")))
    return FrozenMarket(contract, "SHFE", DAY_1, date(2026, 2, 5), D("1"), 10,
                        tuple(sessions), tuple(minutes), tuple(facts))


def signal(minute, action="BUILD", direction="LONG", day=DAY_1, *, contract="FU2603"):
    return Signal(f"{contract}/{day}/{minute}/{action}", contract, day,
                  clock(day, f"09:{minute:02d}:00"), action, direction)


def names(run):
    return [item["position_effect"] for item in run["fills"]]


def test_next_native_bar_open_and_decimal_long_oracle():
    run = run_proof(market(changes={(DAY_1, 5): "98", (DAY_1, 6): "109"}), (signal(5), signal(10, "CLEAR")), D("1000"))
    assert [(row["side"], row["quantity"], row["price"], row["commission"]) for row in run["fills"]] == [
        ("BUY", 1, 100.0, 2.0), ("SELL", 1, 103.0, 2.0),
    ]
    opening = run["attempts"][0]
    assert opening["signal_available_at"] == clock(DAY_1, "09:05:02")
    assert opening["candidate_open_at"] == opening["native_order_at"] == clock(DAY_1, "09:06:00")
    assert run["fills"][0]["native_event_at"] == clock(DAY_1, "09:07:00")
    assert opening["order_reference_price"] == D("98")
    assert opening["native_frozen_price"] == 98.0
    assert opening["frozen_candidate"]["open"] == D("100")
    assert run["settlements"][-1]["after"]["cash"] == run["settlements"][-1]["after"]["equity"] == 1026.0
    assert run["terminal_status"] == "FLAT"


def test_short_and_nonzero_close_today_fee():
    run = run_proof(market(changes={(DAY_1, 7): "103", (DAY_1, 12): "100"}, close_today_fee="4"),
                    (signal(5, direction="SHORT"), signal(10, "CLEAR")), D("1000"))
    assert [(row["side"], row["direction"], row["price"], row["commission"]) for row in run["fills"]] == [
        ("SELL", "SHORT", 103.0, 2.0), ("BUY", "SHORT", 100.0, 4.0),
    ]
    assert names(run) == ["OPEN", "CLOSE_TODAY"]
    assert [row["close_today_quantity"] for row in run["fills"]] == [0, 1]
    assert [row["native_close_today_amount"] for row in run["fills"]] == [1, 1]
    assert run["settlements"][-1]["after"]["equity"] == 1024.0


def test_native_settlement_and_next_day_close_yesterday_fee():
    run = run_proof(market((DAY_1, DAY_2), close_today_fee="4", changes={(DAY_2, 7): "103"}),
                    (signal(5), signal(5, "CLEAR", day=DAY_2)), D("1000"))
    day1 = run["settlements"][0]
    assert day1["before"]["equity"] == 1028.0
    assert day1["after"]["equity"] == 1008.0
    assert day1["after"]["cash"] == 907.0
    assert day1["after"]["positions"][0]["average_price"] == 101.0
    assert names(run) == ["OPEN", "CLOSE"]
    assert [row["close_today_quantity"] for row in run["fills"]] == [0, 0]
    assert [row["native_close_today_amount"] for row in run["fills"]] == [1, 0]
    assert run["fills"][1]["commission"] == 3.0
    assert run["settlements"][-1]["after"]["equity"] == 1025.0


@pytest.mark.parametrize("candidate_price,volume,style,fragment,status", [
    ("110", "8", None, "limit_up", "REJECTED"),
    ("100", "0", None, "no volume", "CANCELLED"),
    ("105", "8", "101", "FIRST_CANDIDATE_EXPIRED", "CANCELLED"),
])
def test_first_candidate_fails_without_deferral(candidate_price, volume, style, fragment, status):
    source = market(changes={(DAY_1, 7): candidate_price, (DAY_1, 8): "100"})
    source = replace(source, minutes=tuple(
        replace(row, volume=D(volume)) if row.end.minute == 7 else row for row in source.minutes
    ))
    opening = replace(signal(5), limit_price=D(style) if style else None)
    run = run_proof(source, (opening, signal(10, "CLEAR")), D("1000"))
    assert run["fills"] == []
    assert fragment in run["attempts"][0]["reason"]
    assert run["attempts"][0]["native_status"] == status
    assert run["attempts"][1]["reason"] == "NO_OPEN_POSITION"
    assert run["settlements"][-1]["after"]["equity"] == 1000.0


def test_missing_candidate_or_settlement_blocks_input():
    source = market()
    with pytest.raises(ValueError, match="M1_COVERAGE_MISMATCH"):
        replace(source, minutes=source.minutes[:6] + source.minutes[7:])
    with pytest.raises(ValueError, match="DAILY_FACTS_MISSING"):
        replace(source, daily=())


def test_no_order_on_session_boundary_or_new_contract_hold():
    source = market()
    run = run_proof(source, (signal(20),), D("1000"))
    assert run["fills"] == []
    assert run["attempts"][0]["reason"] == "NO_SAME_SESSION_CANDIDATE"

    old = run_proof(source, (signal(5),), D("1000"), rollover_boundary=True)
    new = run_proof(market(contract="FU2605"), (signal(5, "HOLD", contract="FU2605"),), D("1000"))
    assert old["terminal_status"] == "ROLLOVER_INTERRUPTED"
    assert len(old["fills"]) == 1
    assert new["fills"] == []
    assert new["terminal_status"] == "FLAT"
    with pytest.raises(ValueError, match="SIGNAL_CONTRACT_MISMATCH"):
        run_proof(source, (signal(5, contract="FU2605"),), D("1000"))


def test_open_position_terminal_valuation_is_not_a_fill():
    run = run_proof(market(), (signal(5),), D("1000"))
    close = run["settlements"][-1]
    assert len(run["fills"]) == 1
    assert close["before"]["positions"][0]["position_equity"] == 30.0
    assert close["after"]["positions"][0]["quantity"] == 1
    assert close["after"]["equity"] == 1008.0
    assert run["terminal_status"] == "OPEN_MARKED_AT_SETTLEMENT"


def test_submission_uses_confirmed_price_for_native_cash_validation():
    source = market(changes={(DAY_1, 5): "98", (DAY_1, 6): "109"})
    run = run_proof(source, (signal(5),), D("103"))
    assert run["attempts"][0]["native_frozen_price"] == 98.0
    assert run["fills"][0]["price"] == 100.0


def test_failed_exit_does_not_defer_or_force_liquidate():
    source = market(changes={(DAY_1, 12): "90"})
    run = run_proof(source, (signal(5), signal(10, "CLEAR")), D("1000"))
    assert names(run) == ["OPEN"]
    assert "limit_down" in run["attempts"][1]["reason"]
    assert run["attempts"][1]["native_status"] == "REJECTED"
    assert run["terminal_status"] == "OPEN_MARKED_AT_SETTLEMENT"


def test_session_break_cannot_move_candidate_to_later_continuous_session():
    source = market()
    second = Session(DAY_1, clock(DAY_1, "10:30:00"), clock(DAY_1, "10:35:00"))
    source = replace(source, sessions=source.sessions + (second,), minutes=source.minutes + tuple(
        replace(source.minutes[0], end=end) for end in second.minute_ends()
    ))
    run = run_proof(source, (signal(20),), D("1000"))
    assert run["fills"] == []
    assert run["attempts"][0]["candidate_open_at"] is None
    assert run["attempts"][0]["reason"] == "NO_SAME_SESSION_CANDIDATE"


def test_causal_provider_uses_confirmed_fill_and_preserves_boundary_signal():
    seen = []

    def decide(at, positions, fills):
        if at == clock(DAY_1, "09:06:00"):
            assert not positions and not fills
            seen.append("BUILD")
            return (replace(signal(5), available_at=clock(DAY_1, "09:05:02")),)
        if at == clock(DAY_1, "09:11:00"):
            assert [(p.order_book_id, p.quantity) for p in positions] == [("FU2603", 1)]
            assert fills[-1]["native_event_at"] == clock(DAY_1, "09:07:00")
            seen.append("CLEAR")
            return (replace(signal(10, "CLEAR"), available_at=clock(DAY_1, "09:10:02")),)
        if at.time().hour == 15:
            seen.append("SESSION_END")
            return (replace(signal(20), available_at=clock(DAY_1, "09:20:02")),)
        return ()

    def choose(available, opens):
        return next((opening for opening in opens if opening > available), None)

    result = run_proof(market(), (), D("1000"), decide=decide, minute_selector=choose)
    assert seen == ["BUILD", "CLEAR", "SESSION_END"]
    assert names(result) == ["OPEN", "CLOSE_TODAY"]
    assert result["attempts"][-1]["reason"] == "NO_SAME_SESSION_CANDIDATE"
    assert result["settlements"][0]["last_bar_close"] == D("103")


def test_availability_equal_to_open_uses_strict_successor():
    signal_at_open = replace(signal(5), available_at=clock(DAY_1, "09:06:00"))

    def decide(at, positions, fills):
        return (signal_at_open,) if at == signal_at_open.available_at else ()

    run = run_proof(market(), (), D("1000"), decide=decide)
    assert run["fills"][0]["modeled_fill_at"] == clock(DAY_1, "09:07:00")
    assert run["fills"][0]["native_event_at"] == clock(DAY_1, "09:08:00")


def test_night_signal_uses_authoritative_trading_day_and_same_session():
    previous = date(2026, 1, 2)
    start = clock(previous, "21:00:00")
    night = Session(DAY_1, start, start + timedelta(minutes=40))
    rows = tuple(Minute(DAY_1, end, D("100"), D("100"), D("100"), D("100"), D("8"))
                 for end in night.minute_ends())
    base = market()
    source = replace(base, sessions=(night, *base.sessions), minutes=(*rows, *base.minutes))
    entry = Signal("night", "FU2603", DAY_1, start + timedelta(minutes=15), "BUILD", frequency="15m")
    exit_signal = Signal("short-h1", "FU2603", DAY_1, night.end, "CLEAR", frequency="60m")
    run = run_proof(source, (entry, exit_signal), D("1000"))
    assert run["fills"][0]["modeled_fill_at"] == start + timedelta(minutes=16)
    assert run["fills"][0]["native_trading_at"].date() == DAY_1
    assert run["attempts"][1]["reason"] == "NO_SAME_SESSION_CANDIDATE"
    assert run["settlements"][0]["day"] == DAY_1
