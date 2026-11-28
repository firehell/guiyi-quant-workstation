from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest_center.errors import BacktestError
from app.backtest_center import native_plus
from app.backtest_center.native_plus import NativeRun, _bar_input, _candidate
from app.backtest_center.plus_inputs import Day, Minute, NativeConfig, Session, SHANGHAI, _minute, _sessions
from app.backtest_center.plus_reconcile import AccountWitness, raw_money, trade_amounts
from guiyi_quant.newow.decision_adapter import ExecutionContext, MarketSource, V2Strategy, seed_decision_state, step_completed
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import ProductBar
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2

DEC = Decimal
JAN5 = date(2026, 1, 5)
JAN6 = date(2026, 1, 6)


def clock(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), SHANGHAI)


def minute(session, at, price=DEC("2485"), volume=100):
    return Minute(at, session, price, price, price, price, volume, DEC(0), 100)


def config():
    return NativeConfig("FU2603", date(2025, 12, 31), JAN5, JAN6, DEC("10000"), DEC(1), 0, "historical")


def test_first_clock_and_holiday_coverage_fail_closed():
    day_sessions = _sessions(JAN5, date(2025, 12, 31))
    next_day = _sessions(JAN6, JAN5)
    assert len(day_sessions) == 3
    assert next_day[0].start == clock(JAN5, 21)
    assert next_day[0].day == JAN6
    monday = date(2025, 12, 29)
    assert _sessions(monday, date(2025, 12, 26))[0].start == clock(date(2025, 12, 26), 21)
    assert sum(len(list(session.minute_ends())) for session in day_sessions) == 225
    assert sum(len(list(session.minute_ends())) for session in next_day) == 345
    session = day_sessions[0]
    row = {"datetime": 20260105090200, "trading_date": 20260105}
    with pytest.raises(BacktestError, match="PLUS_EXECUTION_MINUTE_COVERAGE_MISSING"):
        _minute(clock(JAN5, 9, 1), session, row, None)


def test_5m_information_is_strictly_before_modeled_open_and_stays_in_session():
    session = Session(JAN5, clock(JAN5, 9), clock(JAN5, 9, 10))
    rows = [minute(session, stamp) for stamp in session.minute_ends()]
    payload = _bar_input(rows[:5], SimpleNamespace(dataset_revision="data"), config(), "owner")
    assert payload.source is MarketSource.RQALPHA_PLUS
    assert payload.bar.series_kind == "physical_futures"
    assert payload.available_at.isoformat() == "2026-01-05T09:05:02+08:00"
    assert _candidate(payload) == clock(JAN5, 9, 6)
    assert _candidate(payload, 3) == clock(JAN5, 9, 9)
    assert payload.observed_at == clock(JAN5, 9, 5) and payload.confirmed_at == payload.available_at
    nearly_closed = replace(payload, session=(session.start, clock(JAN5, 9, 9)))
    assert _candidate(nearly_closed, 3) is None
    tail = _bar_input(rows[5:], SimpleNamespace(dataset_revision="data"), config(), "owner")
    assert _candidate(tail) is None


def test_plus_calculation_agrees_with_legacy_batch_formula_on_same_price_prefix():
    session = Session(JAN5, clock(JAN5, 9), clock(JAN5, 14))
    prices = [2720 + (i % 31) * (2 if (i // 31) % 2 == 0 else -3) for i in range(300)]
    minutes = [minute(session, stamp, DEC(price)) for stamp, price in zip(session.minute_ends(), prices, strict=True)]
    packet = SimpleNamespace(dataset_revision="revision")
    payloads = [
        _bar_input(minutes[begin:begin + 5], packet, config(), "fu:FU2603:research")
        for begin in range(0, len(minutes), 5)
    ]
    context = ExecutionContext("run", "config", (V2Strategy.TREND,))
    state = seed_decision_state()
    trace = []
    for payload in payloads:
        state, (decision,) = step_completed(state, payload.completed_input(), context)
        trace.append((decision.state.value, decision.main_action.value if decision.main_action else None))

    legacy_bars = [
        ProductBar(replace(item.bar.bar, series_kind="actual_dominant"), item.bar.frequency)
        for item in payloads
    ]
    legacy = replay_strategy(build_product_identity("fu", "trend", "5m"), tuple(legacy_bars))
    assert trace == [
        (frame.main_state.value, frame.actions[-1].kind.value if frame.actions else None)
        for frame in legacy.frames
    ]
    suffix = seed_decision_state()
    for payload, decision in zip(payloads[:32], trace[:32], strict=True):
        suffix, (prefix,) = step_completed(suffix, payload.completed_input(), context)
        assert decision == (prefix.state.value, prefix.main_action.value if prefix.main_action else None)
    with pytest.raises(ValueError, match="V2_DECISION_COMPLETED_INPUT_INVALID"):
        replace(payloads[0], source=MarketSource.CANONICAL)


def test_p1_decimal_hand_pair_matches_research_cost_and_closed_equity():
    # Independent P1 arithmetic: 2485→2480 × 10 minus 1.2425 open fee and zero same-day close fee.
    session = _sessions(JAN5, date(2025, 12, 31))[0]
    daily = Day(JAN5, DEC(2800), DEC(2300), DEC(2490), DEC(2485), DEC(2495))
    rates = {"OPEN": DEC(".00005"), "CLOSE": DEC(".00005"), "CLOSE_TODAY": DEC(0), "scheme": "BY_MONEY"}
    open_bar = minute(session, clock(JAN5, 9, 32))
    close_bar = minute(session, clock(JAN5, 9, 37), DEC(2480))
    opening, open_fee = trade_amounts(
        rates, "OPEN", open_bar, daily, DEC(1), 10, slippage=0, commission_multiplier=DEC(1)
    )
    closing, close_fee = trade_amounts(
        rates, "CLOSE_TODAY", close_bar, daily, DEC(1), 10, slippage=0, commission_multiplier=DEC(1)
    )
    assert (opening, open_fee, closing, close_fee) == (DEC(2485), DEC("1.2425"), DEC(2480), DEC(0))
    assert raw_money(open_fee, 1.2425000000000002)["hex"] == float(1.2425000000000002).hex()
    witness = AccountWitness(DEC("10000"), "FU2603", 10)
    base = {"signal_id": "one", "modeled_fill_at": clock(JAN5, 9, 6).isoformat(),
            "native_trade_id": "1", "position_effect": "OPEN", "price": "2485"}
    witness.trade(base, JAN5, opening, open_fee)
    witness.trade({**base, "native_trade_id": "2", "signal_id": "two", "position_effect": "CLOSE_TODAY"},
                  JAN5, closing, close_fee)
    cash = 9948.7575
    account = SimpleNamespace(get_positions=list, cash=cash, total_value=cash, margin=0., frozen_cash=0.)
    _, result = witness.account(account, JAN5, daily.settlement, DEC(".20"), settled=True)
    assert result == DEC("9948.7575")
    assert witness.trades[0]["net_pnl"] == "-51.24250000"
    assert witness.trades[0]["native_exit_id"] == "2"


def test_zero_volume_or_limit_does_not_accept_inferred_fill():
    session = _sessions(JAN5, date(2025, 12, 31))[0]
    daily = Day(JAN5, DEC(2800), DEC(2300), DEC(2490), DEC(2485), DEC(2495))
    rates = {"OPEN": DEC(".00005"), "CLOSE": DEC(".00005"), "CLOSE_TODAY": DEC(0), "scheme": "BY_MONEY"}
    for bar, slippage in (
        (minute(session, clock(JAN5, 9, 7), volume=0), 0),
        (minute(session, clock(JAN5, 9, 7), DEC(2800)), 0),
        (minute(session, clock(JAN5, 9, 7), DEC(2799)), 2),
    ):
        with pytest.raises(BacktestError, match="PLUS_NATIVE_INELIGIBLE_FILL"):
            trade_amounts(rates, "OPEN", bar, daily, DEC(1), 10, slippage=slippage,
                          commission_multiplier=DEC(1))


def test_cost_mismatch_and_at_expiry_mark_never_look_like_a_closed_trade():
    witness = AccountWitness(DEC("10000"), "FU2603", 10)
    entry = {"signal_id": "open", "modeled_fill_at": clock(JAN5, 9, 6).isoformat(),
             "native_trade_id": "1", "position_effect": "OPEN", "price": "2485"}
    witness.trade(entry, JAN5, DEC(2485), DEC("1.2425"))
    terminal = witness.terminal(clock(JAN6, 15), DEC(2475), expired=True)
    assert (terminal["status"], terminal["exit_at"], terminal["unrealized_pnl"]) == (
        "ROLLOVER_INTERRUPTED", None, "-100.00000000"
    )
    with pytest.raises(BacktestError, match="PLUS_DECIMAL_RECONCILIATION_FAILED"):
        raw_money(DEC("1.2425"), 1.2)



def test_prematch_slippage_outside_daily_limit_cancels_only_on_candidate_callback():
    session = _sessions(JAN5, date(2025, 12, 31))[0]
    at = clock(JAN5, 9, 7)
    daily = Day(JAN5, DEC(2800), DEC(2300), DEC(2490), DEC(2485), DEC(2495))
    packet = SimpleNamespace(minutes={at: minute(session, at, DEC(2799))}, days={JAN5: daily})
    run = NativeRun.__new__(NativeRun)
    run.config, run.packet, run.tick = replace(config(), slippage_ticks=2), packet, DEC(1)
    order = SimpleNamespace(is_final=lambda: False)
    attempt = {"action": "BUILD", "candidate_bar_end": at.isoformat()}
    canceled = []
    run.outstanding = (order, attempt)
    run.env = SimpleNamespace(calendar_dt=clock(JAN5, 9, 6),
                              broker=SimpleNamespace(cancel_order=canceled.append))
    with pytest.raises(BacktestError, match="PLUS_NATIVE_ORDER_EXPIRY_CLOCK_MISMATCH"):
        run.guard_candidate(None)
    assert canceled == []
    run.env.calendar_dt = at
    run.guard_candidate(None)
    assert canceled == [order]
    assert attempt["candidate_guard"] == "FIRST_CANDIDATE_SLIPPAGE_LIMIT"


def test_account_binary_tolerance_preserves_exact_fee_and_rejects_real_discrepancy():
    capital = DEC("1000000000")
    exact_cost = DEC("1.242500003")
    witness = AccountWitness(capital, "FU2603", 10)
    clock_at = clock(JAN5, 9, 31).isoformat()
    base = {"signal_id": "one", "modeled_fill_at": clock_at, "native_trade_id": "1", "price": "2485"}
    witness.trade({**base, "position_effect": "OPEN"}, JAN5, DEC(2485), exact_cost)
    witness.trade({**base, "position_effect": "CLOSE_TODAY"}, JAN5, DEC(2485), exact_cost)
    assert witness.cash_basis == capital - 2 * exact_cost
    expected = capital - 2 * exact_cost
    report = raw_money(expected, float(expected), account=True)
    assert DEC(report["binary_delta"]) != 0
    with pytest.raises(BacktestError, match="PLUS_DECIMAL_RECONCILIATION_FAILED"):
        raw_money(expected, float(expected - DEC("0.00002")), account=True)



def test_pinned_offline_future_info_does_not_qualify_historical_fee_basis(monkeypatch):
    monkeypatch.setenv("RQSDK_LICENSE", "placeholder-not-a-license")
    monkeypatch.setattr(native_plus, "preflight", lambda *_: SimpleNamespace(
        compatibility={"rqalpha-mod-ricequant-data": "2.6.3"},
    ))
    config = {
        "strategy_id": "newow_trend", "formula_version": NEWOW_TREND_D1_PAGE_V2.trend_band_formula,
        "profile_id": NEWOW_TREND_D1_PAGE_V2.profile_id, "contract": "FU2603", "contract_selection": "physical",
        "rollover_policy": "interrupt", "parameters": {}, "benchmark": "cash",
        "warmup_start": "2025-12-31", "start": "2026-01-05", "end": "2026-01-05",
        "signal_frequency": "5m", "execution_frequency": "1m",
        "initial_capital": "10000", "commission_multiplier": "1", "slippage_ticks": 0, "sample_type": "historical",
    }
    with pytest.raises(BacktestError, match="PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE"):
        native_plus.execute(config, "run", Path("unused"), None, lambda *_: pytest.fail("Unexpected admission"))
