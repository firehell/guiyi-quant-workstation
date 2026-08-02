from __future__ import annotations

from decimal import Decimal

import pytest


def _generate(equity_curve: list[dict]) -> dict:
    from app.backtest.drawdown_curve_generator import generate_drawdown_curve

    return generate_drawdown_curve(equity_curve)


def test_generates_drawdown_curve_from_running_peak() -> None:
    result = _generate(
        [
            {"point_index": 0, "time": None, "equity": Decimal("100000")},
            {"point_index": 1, "time": "2024-01-02T10:00:00+00:00", "trade_id": "T1", "equity": 101000},
            {"point_index": 2, "time": "2024-01-02T10:05:00+00:00", "trade_id": "T2", "equity": 99000},
            {"point_index": 3, "time": "2024-01-02T10:10:00+00:00", "trade_id": "T3", "equity": 98000},
        ]
    )

    assert result["drawdown_curve"] == [
        {
            "point_index": 0,
            "time": None,
            "equity": Decimal("100000"),
            "peak_equity": Decimal("100000"),
            "drawdown": Decimal("0"),
            "drawdown_pct": Decimal("0"),
            "source_trade_id": None,
        },
        {
            "point_index": 1,
            "time": "2024-01-02T10:00:00+00:00",
            "equity": Decimal("101000"),
            "peak_equity": Decimal("101000"),
            "drawdown": Decimal("0"),
            "drawdown_pct": Decimal("0"),
            "source_trade_id": "T1",
        },
        {
            "point_index": 2,
            "time": "2024-01-02T10:05:00+00:00",
            "equity": Decimal("99000"),
            "peak_equity": Decimal("101000"),
            "drawdown": Decimal("2000"),
            "drawdown_pct": Decimal("2000") / Decimal("101000"),
            "source_trade_id": "T2",
        },
        {
            "point_index": 3,
            "time": "2024-01-02T10:10:00+00:00",
            "equity": Decimal("98000"),
            "peak_equity": Decimal("101000"),
            "drawdown": Decimal("3000"),
            "drawdown_pct": Decimal("3000") / Decimal("101000"),
            "source_trade_id": "T3",
        },
    ]
    assert result["max_drawdown_amount"] == Decimal("3000")
    assert result["max_drawdown_pct"] == Decimal("3000") / Decimal("101000")
    assert result["max_drawdown"] == result["max_drawdown_pct"]


def test_new_high_resets_drawdown_before_later_loss() -> None:
    result = _generate(
        [
            {"point_index": 0, "time": None, "equity": 1000},
            {"point_index": 1, "time": "t1", "trade_id": "T1", "equity": 900},
            {"point_index": 2, "time": "t2", "trade_id": "T2", "equity": 1100},
            {"point_index": 3, "time": "t3", "trade_id": "T3", "equity": 1045},
        ]
    )

    assert [point["peak_equity"] for point in result["drawdown_curve"]] == [
        Decimal("1000"), Decimal("1000"), Decimal("1100"), Decimal("1100")
    ]
    assert [point["drawdown"] for point in result["drawdown_curve"]] == [
        Decimal("0"), Decimal("100"), Decimal("0"), Decimal("55")
    ]
    assert result["max_drawdown_amount"] == Decimal("100")
    assert result["max_drawdown_pct"] == Decimal("0.1")


def test_max_drawdown_matches_pointwise_maxima() -> None:
    result = _generate(
        [
            {"point_index": 0, "time": None, "equity": 1000},
            {"point_index": 1, "time": "t1", "trade_id": "T1", "equity": 960},
            {"point_index": 2, "time": "t2", "trade_id": "T2", "equity": 1200},
            {"point_index": 3, "time": "t3", "trade_id": "T3", "equity": 900},
        ]
    )
    points = result["drawdown_curve"]

    assert result["max_drawdown_amount"] == max(point["drawdown"] for point in points)
    assert result["max_drawdown_pct"] == max(point["drawdown_pct"] for point in points)
    assert result["max_drawdown"] == result["max_drawdown_pct"]


def test_preserves_input_order_time_point_index_and_trade_id_mapping() -> None:
    result = _generate(
        [
            {"point_index": 10, "time": "later", "trade_id": "B", "equity": 1000},
            {"point_index": 7, "time": "earlier", "trade_id": "A", "equity": 900},
        ]
    )

    assert [point["point_index"] for point in result["drawdown_curve"]] == [10, 7]
    assert [point["time"] for point in result["drawdown_curve"]] == ["later", "earlier"]
    assert [point["source_trade_id"] for point in result["drawdown_curve"]] == ["B", "A"]


def test_empty_equity_curve_returns_zero_drawdown() -> None:
    assert _generate([]) == {
        "drawdown_curve": [],
        "max_drawdown": 0.0,
        "max_drawdown_amount": 0.0,
        "max_drawdown_pct": 0.0,
    }


def test_missing_equity_raises_value_error() -> None:
    with pytest.raises(ValueError, match="equity"):
        _generate([{"point_index": 0, "time": None}])


def test_invalid_equity_raises_value_error() -> None:
    with pytest.raises(ValueError, match="equity"):
        _generate([{"point_index": 0, "time": None, "equity": "not-number"}])
