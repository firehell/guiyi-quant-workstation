from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace as NS

from guiyi_quant.paper import FeeSchedule
from scripts.research.four_unity_execution import run_segment, summarize


T = datetime(2025, 1, 1, 15, tzinfo=timezone.utc)
DAY = date(2025, 1, 2)
FEES = FeeSchedule(D("0"), D("2"), D("0"), D("3"), D("0"), D("7"), "fixture")


def minute(at, price="100", low=None, volume=10, down="50", day=DAY):
    p = D(price)
    bar = NS(
        bar_end=at + timedelta(minutes=1),
        trading_day=day,
        open=p,
        high=p + 1,
        low=D(low) if low else p - 1,
        close=p,
        volume=D(volume),
        physical_contract="JM2505",
    )
    facts = NS(
        tick_size=D("1"),
        multiplier=D("60"),
        fees=FEES,
        limit_up=D("200"),
        limit_down=D(down),
        source_id="fixture",
    )
    return NS(bar=bar, facts=facts)


def signal(at=T, exit=False):
    return {
        "at": at,
        "low": D("98"),
        "entries": {"trend_breakout": not exit},
        "exit": exit,
        "ready": {"trend_breakout": True},
        "block_reasons": {},
    }


def test_next_time_stop_and_today_fee():
    minutes = [
        minute(T),
        minute(T + timedelta(minutes=2)),
        minute(T + timedelta(minutes=3), "95"),
    ]
    r = run_segment([signal()], minutes, "trend_breakout", 1)
    trade = r["trades"][0]
    assert trade["entry_at"] == (T + timedelta(minutes=2)).isoformat()
    assert trade["entry_price"] == D("101")
    assert trade["exit_price"] == D("94")
    assert trade["exit_reason"] == "STOP"
    assert trade["fees"] == D("9")
    assert trade["net_pnl"] == D("-429")


def test_intraminute_stop_observed_then_next_strict_open():
    minutes = [
        minute(T + timedelta(minutes=2), low="96"),
        minute(T + timedelta(minutes=3), "99"),
        minute(T + timedelta(minutes=4), "98"),
    ]
    r = run_segment([signal()], minutes, "trend_breakout", 0)
    assert r["trades"][0]["exit_at"] == (T + timedelta(minutes=4)).isoformat()


def test_zero_volume_and_limit_no_fabricated_fill():
    minutes = [
        minute(T + timedelta(minutes=2), volume=0),
        minute(T + timedelta(minutes=3), "200"),
    ]
    r = run_segment([signal()], minutes, "trend_breakout", 1)
    assert not r["trades"] and not r["unclosed"]
    assert r["unfilled_entries"] == 1


def test_exit_signal_and_interruption_are_separate():
    minutes = [
        minute(T + timedelta(minutes=2)),
        minute(T + timedelta(minutes=5), "110"),
    ]
    r = run_segment(
        [signal(), signal(T + timedelta(minutes=3), exit=True)],
        minutes,
        "trend_breakout",
        1,
    )
    assert r["trades"][0]["exit_reason"] == "SIGNAL_EXIT"
    interrupted = run_segment(
        [signal()], minutes, "trend_breakout", 1, terminal="ROLLOVER_INTERRUPTED"
    )
    assert interrupted["unclosed"][0]["status"] == "ROLLOVER_INTERRUPTED"
    assert not interrupted["trades"]


def test_wins_exclude_open_and_include_breakeven_in_denominator():
    rows = [
        {
            "net_pnl": D(x),
            "gross_pnl": D(x),
            "fees": D("0"),
            "exit_at": "2025-01-02T00:00:00+00:00",
        }
        for x in ["10", "-5", "0"]
    ]
    result = summarize(rows, [])
    assert result["closed_trades"] == 3
    assert result["wins"] == 1
    assert result["net_profit_factor"] == D("2")
    assert summarize([], [])["win_rate_pct"] is None


def test_cannot_fill_other_contract():
    m = minute(T + timedelta(minutes=2))
    m.bar.physical_contract = "JM2509"
    import pytest

    with pytest.raises(ValueError, match="PHYSICAL_CONTRACT"):
        run_segment(
            [signal()], [minute(T + timedelta(minutes=1)), m], "trend_breakout", 1
        )


def test_limit_down_exit_waits_and_next_day_charges_close_fee():
    minutes = [
        minute(T + timedelta(minutes=2)),
        minute(T + timedelta(minutes=3), "97", down="97"),
        minute(T + timedelta(minutes=4), "96", day=date(2025, 1, 3)),
    ]
    r = run_segment([signal()], minutes, "trend_breakout", 1)
    t = r["trades"][0]
    assert t["exit_price"] == D("95")
    assert t["exit_fee_kind"] == "close"
    assert t["fees"] == D("5")
    assert r["rejections"]["EXIT_NOT_EXECUTABLE"] == 1


def test_signal_at_cutoff_is_not_a_completed_fill():
    r = run_segment([signal()], [minute(T - timedelta(minutes=1))], "trend_breakout", 1)
    assert not r["trades"] and not r["unclosed"]
    assert len(r["signals_without_later_minute"]) == 1


def test_exit_dominates_same_day_entry_and_no_reentry_after_stop():
    s = signal()
    s["exit"] = True
    r = run_segment([s], [minute(T + timedelta(minutes=1))], "trend_breakout", 0)
    assert not r["unclosed"]
    r = run_segment(
        [signal()],
        [
            minute(T + timedelta(minutes=1)),
            minute(T + timedelta(minutes=2), "95"),
            minute(T + timedelta(minutes=3)),
        ],
        "trend_breakout",
        0,
    )
    assert len(r["trades"]) == 1 and not r["unclosed"]
