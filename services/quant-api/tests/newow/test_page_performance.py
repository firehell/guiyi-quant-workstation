import json
from decimal import Decimal
from pathlib import Path

import pytest

from guiyi_quant.newow.page_performance import (
    PageAction,
    PageBar,
    PageSegment,
    compute_page_performance,
)

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures/v3379-manual-oracle.json").read_text()
)


def bar(row):
    return PageBar(
        row["date"], *(Decimal(str(row[k])) for k in ("high", "low", "close"))
    )


def numeric(value):
    if isinstance(value, dict):
        return {
            k: numeric(v)
            for k, v in value.items()
            if k not in ("segment_ids", "trading_days", "segment_id")
        }
    if isinstance(value, list):
        return [numeric(v) for v in value]
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    return value


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda c: c["name"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
def test_full_source_projection(case, strategy):
    segment = PageSegment("owner", tuple(map(bar, case["bars"])), True)
    result = compute_page_performance([segment], strategy)
    for mode in ("ordinary", "ideal"):
        assert numeric(result[mode]) == numeric(case[mode][strategy])
    result = compute_page_performance(
        [segment], strategy, since=case["bars"][len(case["bars"]) // 2]["date"]
    )
    for mode in ("ordinary", "ideal"):
        assert numeric(result[mode]) == numeric(case["windows"][mode][strategy])


def test_fusion_source_full_projection():
    case = ORACLE["fusion_witness"]
    actions = tuple(
        PageAction(s["date"], s["type"], Decimal(str(s["price"])))
        for s in case["signals"]
    )
    segment = PageSegment("owner", tuple(map(bar, case["bars"])), True, actions)
    result = compute_page_performance([segment], "fusion")
    for mode in ("ordinary", "ideal"):
        assert numeric(result[mode]) == numeric(case[mode])
    result = compute_page_performance(
        [PageSegment("owner", segment.bars, True, actions[:1])], "fusion"
    )
    assert numeric(result["ordinary"]) == numeric(case["terminal"])


def test_no_terminal_realization_on_boundary_and_no_owner_pairing():
    case = ORACLE["fusion_witness"]
    rows = tuple(map(bar, case["bars"]))
    buy = PageAction(rows[0].date, "buy", Decimal("100"))
    result = compute_page_performance(
        [PageSegment("first", rows, False, (buy,))], "fusion"
    )
    assert result["ordinary"]["trades"] == []
    assert result["ordinary_interrupted_count"] == 1
    assert result["ordinary"]["summary"]["cumReturn"] == "0"


def test_invalid_owner_prices_actions_fail_closed():
    rows = tuple(map(bar, ORACLE["fusion_witness"]["bars"]))
    with pytest.raises(ValueError, match="NEWOW_DATA_IDENTITY_INVALID"):
        compute_page_performance(
            [PageSegment("same", rows), PageSegment("same", rows)], "trend"
        )
    with pytest.raises(ValueError, match="NEWOW_DATA_IDENTITY_INVALID"):
        compute_page_performance(
            [
                PageSegment(
                    "owner", rows, True, (PageAction("missing", "buy", Decimal("100")),)
                )
            ],
            "fusion",
        )


def test_fusion_sell_before_buy_first_signal_price_and_exit_high_exclusion():
    case = ORACLE["fusion_order_witness"]
    actions = tuple(
        PageAction(s["date"], s["type"], Decimal(str(s["price"])))
        for s in case["signals"]
    )
    result = compute_page_performance(
        [PageSegment("owner", tuple(map(bar, case["bars"])), True, actions)], "fusion"
    )
    for mode in ("ordinary", "ideal"):
        assert numeric(result[mode]) == numeric(case[mode])
    assert result["ordinary"]["trades"][0]["buyPrice"] == "100"
    assert (
        result["ideal"]["trades"][0]["sellPrice"] == "111"
    )  # exit bar high=999 excluded
    assert result["ideal"]["trades"][1]["buyPrice"] == "90"


def test_ordinary_and_ideal_oscillation_pair_independently_on_same_bar():
    case = next(c for c in ORACLE["cases"] if c["name"] == "oscillation-same-bar")
    result = compute_page_performance(
        [PageSegment("owner", tuple(map(bar, case["bars"])), True)], "oscillation"
    )
    assert (
        result["ideal"]["trades"][0]["buyDate"]
        == result["ideal"]["trades"][0]["sellDate"]
    )
    assert (
        result["ordinary"]["trades"][0]["buyDate"]
        != result["ordinary"]["trades"][0]["sellDate"]
    )


def test_warm_prefix_cannot_enter_or_terminal_realize():
    rows = tuple(map(bar, ORACLE["fusion_witness"]["bars"]))
    warm = PageBar(rows[0].date, rows[0].high, rows[0].low, rows[0].close, False)
    buy = PageAction(rows[0].date, "buy", Decimal("100"))
    result = compute_page_performance(
        [PageSegment("owner", (warm, rows[1]), True, (buy,))], "fusion"
    )
    assert result["ordinary"]["trades"] == []
    assert result["ordinary"]["dates"] == [rows[1].date]
    assert result["ordinary"]["segment_ids"] == ["owner"]


def test_minute_window_uses_trading_day_and_keeps_owner_identity():
    rows = (
        PageBar(
            "2026-01-05T21:00:00+08:00",
            Decimal("110"),
            Decimal("90"),
            Decimal("100"),
            True,
            "2026-01-06",
        ),
        PageBar(
            "2026-01-06T09:00:00+08:00",
            Decimal("120"),
            Decimal("90"),
            Decimal("110"),
            True,
            "2026-01-06",
        ),
        PageBar(
            "2026-01-06T21:00:00+08:00",
            Decimal("130"),
            Decimal("90"),
            Decimal("120"),
            True,
            "2026-01-07",
        ),
    )
    buy = PageAction(rows[0].date, "buy", Decimal("100"))
    sell = PageAction(rows[1].date, "sell", Decimal("110"))
    result = compute_page_performance(
        [PageSegment("owner", rows, True, (buy, sell))],
        "fusion",
        since="2026-01-06",
        through="2026-01-06",
    )
    assert result["ordinary"]["dates"] == [b.date for b in rows[:2]]
    assert result["ordinary"]["trades"][0]["segment_id"] == "owner"
    assert result["ordinary"]["trading_days"] == ["2026-01-06"] * 2


def test_gap_boundary_discards_open_pair_and_next_owner_cannot_sell_it():
    rows = tuple(map(bar, ORACLE["fusion_witness"]["bars"]))
    later = tuple(
        PageBar(b.date.replace("2026-01", "2026-02"), b.high, b.low, b.close)
        for b in rows
    )
    result = compute_page_performance(
        [
            PageSegment(
                "one", rows, True, (PageAction(rows[0].date, "buy", Decimal("100")),)
            ),
            PageSegment(
                "two", later, True, (PageAction(later[0].date, "sell", Decimal("110")),)
            ),
        ],
        "fusion",
    )
    assert result["ordinary"]["trades"] == []
    assert result["ordinary_interrupted_count"] == 1
    assert result["ordinary"]["segment_ids"] == ["one", "one", "two", "two"]
    assert result["ordinary"]["summary"]["cumReturn"] == "0"


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("0"), Decimal("1e-400")]
)
def test_prices_fail_closed_including_binary64_underflow(bad):
    rows = (PageBar("2026-01-01", bad, bad, bad),)
    with pytest.raises(ValueError, match="NEWOW_DATA_IDENTITY_INVALID"):
        compute_page_performance([PageSegment("owner", rows)], "trend")


def test_javascript_sequential_sum_not_python_compensated_sum():
    from guiyi_quant.newow.page_performance import _ma

    witness = ORACLE["ma_sum_witness"]
    assert _ma(witness["values"], 3) == witness["expected"]


def test_interrupted_floating_peak_does_not_create_cross_owner_drawdown():
    first = (
        PageBar("2026-01-01", Decimal("110"), Decimal("90"), Decimal("100")),
        PageBar("2026-01-02", Decimal("160"), Decimal("90"), Decimal("150")),
    )
    flat = (
        PageBar("2026-02-01", Decimal("110"), Decimal("90"), Decimal("100")),
        PageBar("2026-02-02", Decimal("110"), Decimal("90"), Decimal("100")),
    )
    result = compute_page_performance(
        [
            PageSegment(
                "interrupted",
                first,
                False,
                (PageAction(first[0].date, "buy", Decimal("100")),),
            ),
            PageSegment(
                "flat", flat, True, (PageAction(flat[0].date, "sell", Decimal("100")),)
            ),
        ],
        "fusion",
    )
    assert result["ordinary"]["equity"] == ["0", "50", "0", "0"]
    assert result["ordinary"]["segment_ids"] == ["interrupted"] * 2 + ["flat"] * 2
    assert result["ordinary"]["trades"] == []
    assert result["ordinary"]["summary"]["maxDrawdown"] == "0"
    assert result["ordinary"]["summary"]["cumReturn"] == "0"


def test_later_owner_overlapping_physical_warm_prefix_is_retained():
    from datetime import date, timedelta

    def rows(start, count, eligible_after=0):
        return tuple(
            PageBar(
                (start + timedelta(days=i)).isoformat(),
                Decimal("105"),
                Decimal("95"),
                Decimal("100"),
                i >= eligible_after,
            )
            for i in range(count)
        )

    first = rows(date(2026, 5, 1), 12)
    # 100 physical-contract warm bars precede the old owner's end; eligible
    # bars begin strictly after it. All 100 must still warm the new indicators.
    second = rows(date(2026, 2, 12), 104, 100)
    result = compute_page_performance(
        [PageSegment("one", first), PageSegment("two", second, True)], "oscillation"
    )
    assert result["ordinary"]["dates"] == [b.date for b in first[9:]] + [
        b.date for b in second[100:]
    ]
    assert result["ordinary"]["segment_ids"] == ["one"] * 3 + ["two"] * 4
    assert result["ordinary"]["trades"][-1]["segment_id"] == "two"
    assert result["ordinary"]["trades"][-1]["buyDate"] >= second[100].date


def test_overlapping_eligible_owners_still_fail_closed():
    rows = tuple(map(bar, ORACLE["fusion_witness"]["bars"]))
    with pytest.raises(ValueError, match="NEWOW_DATA_IDENTITY_INVALID"):
        compute_page_performance(
            [PageSegment("one", rows), PageSegment("two", rows)], "fusion"
        )


def test_exit_window_excludes_ended_owner_instead_of_per_owner_no_match_fallback():
    def segment(owner, year, first_high, exit_price):
        dates = tuple(f"{year}-01-0{day}" for day in (1, 2, 3))
        rows = (PageBar(dates[0], Decimal(first_high), Decimal("90"), Decimal("100")),
                PageBar(dates[1], Decimal("150"), Decimal("90"), Decimal("100")),
                PageBar(dates[2], Decimal("110"), Decimal("90"), Decimal("100")))
        return PageSegment(owner, rows, True, (
            PageAction(dates[0], "buy", Decimal("100")),
            PageAction(dates[1], "sell", Decimal(exit_price)),
        ))
    old = segment("old-owner", 2025, "120", "110")
    current = segment("current-owner", 2026, "105", "105")
    actual = compute_page_performance([old, current], "fusion", since="2026-01-01", through="2026-01-03")
    expected = compute_page_performance([current], "fusion", since="2026-01-01", through="2026-01-03")
    for mode in ("ordinary", "ideal"):
        assert actual[mode] == expected[mode]
        assert actual[mode]["summary"]["tradeCount"] == 1
        assert actual[mode]["summary"]["cumReturn"] == "5"
        assert set(actual[mode]["segment_ids"]) == {"current-owner"}


def _window_owner(owner, year, *, eligible=True, open_only=False):
    dates = tuple(f"{year}-01-0{day}" for day in (1, 2, 3))
    bars = tuple(PageBar(d, Decimal("105"), Decimal("90"), Decimal("100"), eligible) for d in dates)
    actions = (PageAction(dates[0], "buy", Decimal("100")),)
    if not open_only:
        actions += (PageAction(dates[1], "sell", Decimal("105")),)
    return PageSegment(owner, bars, True, actions)


@pytest.mark.parametrize("since,through", [
    ("2025-06-01", "2026-01-03"),
    ("2026-01-03", "2026-01-03"),
    ("2025-06-01", "2025-12-31"),
])
def test_cross_owner_window_boundaries_match_current_owner_only(since, through):
    old, current = _window_owner("old", 2025), _window_owner("current", 2026)
    actual = compute_page_performance([old, current], "fusion", since=since, through=through)
    expected = compute_page_performance([current], "fusion", since=since, through=through)
    for mode in ("ordinary", "ideal"):
        assert actual[mode] == expected[mode]


def test_full_sequence_no_start_match_retains_public_fallback():
    segments = [_window_owner("old", 2025), _window_owner("current", 2026)]
    actual = compute_page_performance(segments, "fusion", since="2027-01-01")
    expected = compute_page_performance(segments, "fusion")
    for mode in ("ordinary", "ideal"):
        assert actual[mode] == expected[mode]


def test_warmup_only_owner_does_not_prove_global_start_match():
    old, warmup = _window_owner("old", 2025), _window_owner("warmup", 2026, eligible=False)
    actual = compute_page_performance([old, warmup], "fusion", since="2026-01-01")
    expected = compute_page_performance([old], "fusion")
    for mode in ("ordinary", "ideal"):
        assert actual[mode] == expected[mode]


def test_ended_owner_open_pairing_does_not_enter_window_interruption_counts():
    old, current = _window_owner("old", 2025, open_only=True), _window_owner("current", 2026)
    actual = compute_page_performance([old, current], "fusion", since="2026-01-01")
    assert actual["ordinary_interrupted_count"] == 0
    assert actual["ideal_open_count"] == 0
