from decimal import Decimal
import pytest
from scripts.newow_candidate_tools.curves import (
    expected_curve,
    curve_matches,
    validate_curve_ui,
    record_ids_match,
)


def value(returns=("1.25", "-0.20", "0.125")):
    trades = [
        dict(
            reference_trade_id=f"t{i}",
            status="CLOSED",
            statistics_membership="entry_in_window_v1",
            reference_return_pct=r,
            exit_bar_end=f"2026-09-{21 + i}T07:00:00Z",
            exit_trading_day=f"2026-09-{21 + i}",
        )
        for i, r in enumerate(returns)
    ]
    return dict(
        summary=dict(
            closed_count=len(trades),
            membership_policy="entry_in_window_v1",
            sum_return_percentage_points=str(sum(map(Decimal, returns), Decimal(0))),
        ),
        curve_trades=trades,
        performance_since="2026-09-01",
        performance_through="2026-09-24",
        actual_available_through="2026-09-24",
    )


def test_every_interior_svg_point_is_checked():
    expected, proof = expected_curve(value())
    actual = " ".join(f"{x},{y}" for x, y in expected)
    assert proof["sum_decimal"] == "1.175" and curve_matches(actual, expected)
    wrong = actual.split()
    wrong[2] = "10,10"
    assert not curve_matches(" ".join(wrong), expected)


def test_duplicate_closed_identity_and_missing_record_are_rejected():
    v = value()
    v["curve_trades"][1]["reference_trade_id"] = "t0"
    with pytest.raises(ValueError):
        expected_curve(v)
    assert not record_ids_match(value()["curve_trades"], ["row-t0", "row-t1"])


def test_empty_curve_requires_native_empty_status_without_fabricated_line():
    v = value(())
    v["summary"]["sum_return_percentage_points"] = None
    assert (
        validate_curve_ui(v, [], ["暂无已完成参考交易；未清仓与中断结果不计入曲线。"])[
            "closed_count"
        ]
        == 0
    )
    with pytest.raises(ValueError):
        validate_curve_ui(
            v, ["0,140 712,140"], ["暂无已完成参考交易；未清仓与中断结果不计入曲线。"]
        )
    with pytest.raises(ValueError):
        validate_curve_ui(v, [], [])


def test_complete_array_uses_declared_count_and_summary():
    for field, new in [("closed_count", 2), ("sum_return_percentage_points", "9.99")]:
        v = value()
        v["summary"][field] = new
        with pytest.raises(ValueError):
            expected_curve(v)
