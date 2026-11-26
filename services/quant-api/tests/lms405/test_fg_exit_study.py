from datetime import datetime
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_fg_exit_study import compare_plan_intents, minute_context, pressure_timeline, range_recapture
from lms405_right_side_study import ONE, at


def test_software_row_minute_uses_bar_start_not_bar_end():
    row_time = "2026-10-27T14:08"
    start = at(row_time)
    prior = Bar("FG2701", start, Decimal(833), Decimal(836), Decimal(831), Decimal(834),
                start=start - ONE)
    containing = Bar("FG2701", start + ONE, Decimal(844), Decimal(847), Decimal(844), Decimal(847),
                     start=start)

    result = minute_context([prior, containing], row_time, ("831", "832"))

    assert result["last_bar_ending_at_minute"]["close"] == Decimal(834)
    assert result["containing_bar"]["low"] == Decimal(844)
    assert result["containing_bar"]["high"] == Decimal(847)
    assert result["reference_opening_averages"]["832"] == {
        "inside_bar": False, "strictly_above_all_prices": False, "strictly_below_all_prices": True,
    }


def test_two_close_recapture_requires_earlier_down_cross_in_same_segment():
    start = at("2026-09-14T09:00")
    px = [101, 99, 98, 101, 102]
    bars = [Bar("FG2701", start + i * ONE, *([Decimal(close)] * 4), start=start + (i - 1) * ONE)
            for i, close in enumerate(px, 1)]
    assert pressure_timeline(bars, Decimal(100))["up_after_down_in_same_segment"] == {
        "down_two_closes_at": bars[2].end, "recapture_two_closes_at": bars[4].end,
    }
    assert range_recapture(bars, Decimal(100), Decimal(101)) is None
    last = Bar("FG2701", start + 6 * ONE, *([Decimal(103)] * 4), start=start + 5 * ONE)
    assert range_recapture([*bars, last], Decimal(100), Decimal(101)) == {
        "down_two_closes_at": bars[2].end, "recapture_two_closes_at": last.end,
    }

    reopen = start + 10 * ONE
    renewed = [Bar("FG2701", reopen + i * ONE, *([Decimal(close)] * 4), start=reopen + (i - 1) * ONE)
               for i, close in enumerate([100, 101, 102], 1)]
    split = pressure_timeline(bars[:3] + renewed, Decimal(100))
    assert split["first_up_two_closes_at"] == renewed[-1].end
    assert split["up_after_down_in_same_segment"] is None


def test_same_price_pressure_requires_distinct_plan_purpose_and_permission():
    def case(contract, published_at, close_at, edge):
        return {
            "contract": contract, "source_id": published_at,
            "source": {"published_at": published_at},
            "edges": {edge: {"first_up_two_closes_at": close_at}},
            "cutoff_exclusive": published_at,
        }

    pressure = {"cases": {
        "july_4_0_5_protection": case("FG2609", "2026-07-08T15:10:00+08:00", "2026-07-08T11:11:00+08:00", "960"),
        "september_4_0_5_take_profit": case(
            "FG2701", "2026-09-14T15:10:00+08:00", "2026-09-14T09:31:00+08:00", "946",
        ),
        "october_software_buy_close": case(
            "FG2701", "2026-10-27T14:08:00+08:00", "2026-10-27T05:49:00+00:00", "836",
        ),
    }}
    source_reads = {row["source_id"]: {"observed_at": datetime.fromisoformat(row["source_id"]) + ONE}
                    for row in pressure["cases"].values()}
    result = compare_plan_intents(pressure, source_reads)

    assert result["fixtures"]["protection"]["approved"]["after"] == {"long": "1", "short": "1"}
    assert result["fixtures"]["exit_original_short"]["approved"]["after"] == {"long": "0", "short": "0"}
    assert result["pressure_at"].isoformat() == "2026-10-27T13:49:00+08:00"
    for scenario in result["fixtures"].values():
        for key in ("price_only", "before_close_known", "before_plan_known", "at_approval_known", "simultaneous",
                    "wrong_purpose", "denied", "plan_learned_after_approval", "plan_learned_after_pressure",
                    "approval_without_plan"):
            assert scenario[key]["after"] is None
        assert scenario["wrong_purpose"]["status"] == "NOT_PERMITTED"
        assert scenario["denied"]["status"] == "NOT_PERMITTED"
    for routes in result["public"].values():
        for route in routes.values():
            before = route["before_disclosure"]
            assert before["after"] is None and route["archived_readback"]["after"] is None
            assert before["sources"] == ["FROZEN_MARKET_PRICE_ONLY"]
            assert "case_version_405" in before["unknown"]
    assert result["admitted_author_samples"] == 0
