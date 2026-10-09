"""Same-input source witnesses. Differences are pinned, not repaired or called parity."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from guiyi_quant.newow.ai_analysis import estimate_segments
from guiyi_quant.newow.composite_decision_v2 import compute_cdv2
from guiyi_quant.newow.fusion_reference import fusion_reference_comparison
from guiyi_quant.newow.main_rise import calculate_main_rise_series
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.oscillation_channel import calculate_oscillation_series
from guiyi_quant.newow.product_contracts import (
    ProductBar,
    ProductFrequency,
    ProductStrategy,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.reference_statistics import (
    PerformanceWindow,
    summarize_reference,
)
from guiyi_quant.newow.reference_trades import ReferenceProjection, ReferenceTrade
from guiyi_quant.newow.theoretical_reference import theoretical_reference
from guiyi_quant.newow.trend_band import initial_trend_band_state, step_trend_band

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures/v3379-manual-oracle.json").read_text()
)
CASES = ORACLE["cases"]


@pytest.mark.parametrize("closed", [True, False])
def test_fusion_fixed_signal_ordinary_and_terminal_difference(product_cases, closed):
    case = product_cases.closed()
    witness = ORACLE["fusion_witness"]
    assert [
        (
            b.bar.trading_day.isoformat(),
            *(float(getattr(b.bar, k)) for k in ("open", "high", "low", "close")),
        )
        for b in case.bars
    ] == [
        (b["date"], *(b[k] for k in ("open", "high", "low", "close")))
        for b in witness["bars"]
    ]
    trend = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, case.exit) if closed else (case.entry,),
        ("BUILD", "CLEAR" if closed else "HOLD"),
    )
    osc_case = product_cases.closed(strategy="oscillation")
    osc = product_cases.replay(osc_case.identity, case.bars, (), ("FLAT", "FLAT"))
    result = fusion_reference_comparison(
        trend,
        osc,
        (),
        (),
        PerformanceWindow(case.bars[0].bar.trading_day, case.as_of.date(), case.as_of),
    )
    row = result["items"][0]
    if closed:
        assert (
            Decimal(row["reference_return_pct"])
            == Decimal(str(witness["ordinary"]["trades"][0]["pct"]))
            == 10
        )
        assert witness["ideal"]["trades"][0]["sellPrice"] == 110
        assert Decimal(result["theoretical"]["returns"][0]["ideal_exit_price"]) == 121
    else:
        assert witness["terminal"]["trades"][0]["forceClose"] is True
        assert row["status"] == "OPEN"
        assert row["reference_return_pct"] is None


def test_latest_cdv2_state_cube_numeric_outputs():
    assert len(ORACLE["cdv2_cases"]) == 729
    for case in ORACLE["cdv2_cases"]:
        actual = compute_cdv2(case["trend"], case["oscillation"])
        conflict = actual["period_conflict"]
        expected_conflict = case["period_conflict"]
        assert conflict["hit"] == expected_conflict["hit"]
        assert conflict["code"] == expected_conflict["code"]
        assert conflict["week_state"] == expected_conflict["weekState"]
        assert conflict["day_state"] == expected_conflict["dayState"]
        for field, expected in case["expected"].items():
            assert actual[field] == expected, (
                case["trend"],
                case["oscillation"],
                field,
            )


def test_latest_xp1_matches_public_source():
    witness = next(
        c
        for c in ORACLE["cdv2_cases"]
        if c["trend"] == {"week": "hold", "day": "wait", "m60": "hold"}
    )
    assert witness["period_conflict"]["code"] == "XP1"
    actual = compute_cdv2(witness["trend"], witness["oscillation"])["period_conflict"]
    assert actual["code"] == witness["period_conflict"]["code"]
    assert actual["hit"] == witness["period_conflict"]["hit"]
    assert actual["week_state"] == witness["period_conflict"]["weekState"]
    assert actual["day_state"] == witness["period_conflict"]["dayState"]


def bars(case):
    return tuple(
        NewowDailyBar(
            "rb",
            "RB2601",
            "audit-owned",
            date.fromisoformat(b["date"]),
            datetime.fromisoformat(b["date"]).replace(tzinfo=UTC),
            *(Decimal(str(b[k])) for k in ("open", "high", "low", "close")),
            b["volume"],
            0,
            f"audit-input:{i}",
            True,
            True,
        )
        for i, b in enumerate(case["bars"])
    )


def pair(case, strategy, source_trade):
    source = case["bars"]
    entry = next(
        i for i, b in enumerate(source) if b["date"] == source_trade["buyDate"]
    )
    exit_ = next(
        i for i, b in enumerate(source) if b["date"] == source_trade["sellDate"]
    )
    rows = bars(case)
    price = (
        Decimal(str(case[strategy]["ma45"][entry]))
        if strategy == "main_rise"
        else Decimal(str(case["trend"]["b"][entry]))
        if strategy == "trend"
        else rows[entry].low
    )
    exit_price = rows[exit_].close
    return ReferenceTrade(
        "audit-trade",
        "rb",
        ProductStrategy(strategy),
        ProductFrequency.DAILY,
        "RB2601",
        "audit-owned",
        ("audit-fixed-pair",),
        "audit-model",
        "audit-adapter",
        "audit-entry",
        rows[entry].bar_end,
        rows[entry].trading_day,
        price,
        "audit-exit",
        rows[exit_].bar_end,
        rows[exit_].trading_day,
        exit_price,
        "CLOSED",
        exit_ - entry,
        (exit_price / price - 1) * 100,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_trend_band_same_input(case):
    state = initial_trend_band_state()
    for i, bar in enumerate(bars(case)):
        result = step_trend_band(state, bar, profile=NEWOW_TREND_D1_PAGE_V2)
        state = result.state
        assert result.point.state.value.lower() == case["trend"]["states"][i]
        # Internal legacy names b_value/c_value are the public A7/B10 respectively.
        assert result.point.b_value == pytest.approx(case["trend"]["a"][i], abs=1e-10)
        assert result.point.c_value == pytest.approx(case["trend"]["b"][i], abs=1e-10)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_main_rise_band_same_input(case):
    for i, result in enumerate(calculate_main_rise_series(bars(case))):
        assert result.band_state.value.lower() == case["main_rise"]["states"][i]
        assert result.ma35 == pytest.approx(case["main_rise"]["ma35"][i], abs=1e-10)
        assert result.ma45 == pytest.approx(case["main_rise"]["ma45"][i], abs=1e-10)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_main_rise_signal_dates_and_reference_prices_same_input(case):
    actual = [
        (
            i,
            "buy" if r.band_signal.action.value == "BUILD" else "sell",
            float(r.band_signal.price),
        )
        for i, r in enumerate(calculate_main_rise_series(bars(case)))
        if r.band_signal
    ]
    expected = [
        (s["index"], s["type"], s["price"])
        for s in case["main_rise"]["signals"]
        if s["type"] in ("buy", "sell")
    ]
    assert [(i, kind) for i, kind, _ in actual] == [
        (i, kind) for i, kind, _ in expected
    ]
    assert [p for _, _, p in actual] == pytest.approx(
        [p for _, _, p in expected], abs=1e-10
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_main_rise_j_dates_and_reference_prices_same_input(case):
    actual = [
        (i, float(r.reduce_signal.price))
        for i, r in enumerate(calculate_main_rise_series(bars(case)))
        if r.reduce_signal
    ]
    expected = [
        (s["index"], s["price"])
        for s in case["main_rise"]["signals"]
        if s["type"] == "reduce"
    ]
    assert [i for i, _ in actual] == [i for i, _ in expected]
    assert [p for _, p in actual] == pytest.approx([p for _, p in expected], abs=1e-10)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_all_trend_signal_dates_and_reference_prices_same_input(case):
    state = initial_trend_band_state()
    actual = []
    for i, bar in enumerate(bars(case)):
        result = step_trend_band(state, bar, profile=NEWOW_TREND_D1_PAGE_V2)
        state = result.state
        if result.marker:
            actual.append(
                (
                    i,
                    "buy" if result.marker.marker_type.value == "BUILD" else "sell",
                    float(result.marker.price),
                )
            )
    expected = [(r["index"], r["type"], r["price"]) for r in case["trend"]["signals"]]
    assert [(i, kind) for i, kind, _ in actual] == [
        (i, kind) for i, kind, _ in expected
    ]
    assert [p for _, _, p in actual] == pytest.approx(
        [p for _, _, p in expected], abs=1e-10
    )


def test_initial_trend_clear_has_a_display_marker_without_entry():
    case = CASES[6]
    index = case["trend"]["signals"][0]["index"]
    assert case["trend"]["signals"][0]["type"] == "sell"
    state = initial_trend_band_state()
    for bar in bars(case)[: index + 1]:
        result = step_trend_band(state, bar, profile=NEWOW_TREND_D1_PAGE_V2)
        state = result.state
    assert result.point.state_before.value == "YELLOW"
    assert result.point.state.value == "BLUE"
    assert result.marker is not None
    assert result.marker.marker_type.value == "CLEAR"
    assert result.marker.related_marker_ids == ()
    assert result.marker.price == Decimal(str(case["trend"]["b"][index]))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation"])
def test_ordinary_ai_backtest_summary_same_input(case, strategy):
    rows = [
        tuple(Decimal(str(b[k])) for k in ("high", "low", "close"))
        for b in case["bars"]
    ]
    actual = estimate_segments([rows], strategy)
    expected = case["ordinary"][strategy]
    if expected is None:
        assert actual is None
    else:
        assert actual.cumulative_return == Decimal(
            str(expected["summary"]["cumReturn"])
        )
        assert actual.max_drawdown == Decimal(str(expected["summary"]["maxDrawdown"]))
        assert actual.trade_count == expected["summary"]["tradeCount"]
        assert actual.win_rate == expected["summary"]["accuracy"]


def test_chart_same_bar_matches_source_without_changing_ai_order():
    case = CASES[4]  # Repeated touching of both channel edges.
    local = [
        {
            "date": bar.trading_day.isoformat(),
            "type": "buy" if s.action.value == "BUILD" else "sell",
            "price": float(s.price),
        }
        for bar, step in zip(bars(case), calculate_oscillation_series(bars(case)))
        for s in step.signals
    ]
    assert local == case["chart"]
    day = case["bars"][10]["date"]
    assert [s["type"] for s in local if s["date"] == day] == ["sell"]
    assert [s["type"] for s in case["chart"] if s["date"] == day] == ["sell"]


def test_oscillation_theory_can_include_a_pre_entry_high():
    case = CASES[7]
    source_trade = case["ideal"]["oscillation"]["trades"][0]
    trade = pair(case, "oscillation", source_trade)
    actual = theoretical_reference(
        (trade,), tuple(ProductBar(b, ProductFrequency.DAILY) for b in bars(case))
    )
    assert source_trade["sellPrice"] == 200
    assert Decimal(actual["returns"][0]["ideal_exit_price"]) == 199


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c["ideal"]["trend"] and c["ideal"]["trend"]["trades"]],
    ids=lambda c: c["name"],
)
def test_trend_theory_fixed_pair_peak_and_return_same_input(case):
    for source_trade in case["ideal"]["trend"]["trades"]:
        trade = pair(case, "trend", source_trade)
        actual = theoretical_reference(
            (trade,), tuple(ProductBar(b, ProductFrequency.DAILY) for b in bars(case))
        )
        assert round(Decimal(actual["returns"][0]["ideal_exit_price"]), 2) == Decimal(
            str(source_trade["sellPrice"])
        )
        assert round(Decimal(actual["sum_return_percentage_points"]), 2) == Decimal(
            str(source_trade["pct"])
        )


def test_main_rise_theory_uses_different_entry_price():
    case = CASES[6]
    source_trade = case["ideal"]["main_rise"]["trades"][0]
    trade = pair(case, "main_rise", source_trade)
    actual = theoretical_reference(
        (trade,), tuple(ProductBar(b, ProductFrequency.DAILY) for b in bars(case))
    )
    entry = next(b for b in case["bars"] if b["date"] == source_trade["buyDate"])
    assert source_trade["buyPrice"] == round(entry["close"], 2)
    assert abs(trade.entry_reference_price - Decimal(str(entry["close"]))) > Decimal(
        "0.1"
    )
    assert round(Decimal(actual["sum_return_percentage_points"]), 2) != Decimal(
        str(source_trade["pct"])
    )


def test_exit_window_and_entry_window_are_different():
    case = {
        "bars": [
            {
                "date": f"2025-01-0{i}",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 110 if i == 3 else 100,
                "volume": 100,
            }
            for i in (1, 2, 3)
        ]
    }
    trade = pair(
        case, "oscillation", {"buyDate": "2025-01-01", "sellDate": "2025-01-03"}
    )
    # Same explicit entry/exit prices and dates as the public window witness.
    from dataclasses import replace

    trade = replace(
        trade, entry_reference_price=Decimal(100), reference_return_pct=Decimal(10)
    )
    cutoff = datetime(2025, 1, 3, tzinfo=UTC)
    result = summarize_reference(
        ReferenceProjection((trade,), (), (), (), cutoff),
        PerformanceWindow(date(2025, 1, 2), date(2025, 1, 3), cutoff),
    )
    assert ORACLE["window_witness"]["summary"]["tradeCount"] == 1
    assert ORACLE["window_witness"]["summary"]["cumReturn"] == 10
    assert result.closed_count == 0
    assert result.initial_count == 1
