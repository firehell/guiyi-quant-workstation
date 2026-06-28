from __future__ import annotations

from decimal import Decimal

import pytest


def _generate(trades: list[dict], *, initial_capital: Decimal | float | int) -> list[dict]:
    from app.backtest.equity_curve_generator import generate_equity_curve

    return generate_equity_curve(trades, initial_capital=initial_capital)


def test_generates_equity_curve_from_initial_capital_and_explicit_net_pnl() -> None:
    curve = _generate(
        [
            {
                "trade_id": "T1",
                "sequence": 1,
                "exit_time": "2024-01-02T10:00:00",
                "gross_pnl": 120.0,
                "commission": 15.0,
                "slippage": 5.0,
                "net_pnl": 100.0,
            }
        ],
        initial_capital=Decimal("100000"),
    )

    assert curve == [
        {"point_index": 0, "time": None, "equity": 100000.0, "source": "initial_capital"},
        {
            "point_index": 1,
            "time": "2024-01-02T10:00:00+00:00",
            "trade_id": "T1",
            "sequence": 1,
            "gross_pnl": 120.0,
            "commission": 15.0,
            "slippage": 5.0,
            "net_pnl": 100.0,
            "equity": 100100.0,
        },
    ]


def test_explicit_net_pnl_is_not_charged_costs_twice() -> None:
    curve = _generate(
        [
            {
                "trade_id": "T1",
                "sequence": 1,
                "exit_time": "2024-01-02T10:00:00",
                "gross_pnl": 100.0,
                "commission": 3.0,
                "slippage": 2.0,
                "net_pnl": 95.0,
            }
        ],
        initial_capital=10000,
    )

    assert curve[-1]["net_pnl"] == 95.0
    assert curve[-1]["equity"] == 10095.0


def test_derives_net_pnl_from_gross_pnl_commission_and_slippage() -> None:
    curve = _generate(
        [
            {
                "trade_id": "T1",
                "sequence": 1,
                "exit_time": "2024-01-02T10:00:00",
                "gross_pnl": 100.0,
                "commission": Decimal("3.5"),
                "slippage": Decimal("1.5"),
            }
        ],
        initial_capital=10000,
    )

    assert curve[-1]["net_pnl"] == 95.0
    assert curve[-1]["equity"] == 10095.0


def test_sorts_trades_deterministically_by_exit_time_sequence_and_trade_id() -> None:
    trades = [
        {"trade_id": "T3", "sequence": 2, "exit_time": "2024-01-02T10:00:00", "net_pnl": 30},
        {"trade_id": "T1", "sequence": 1, "exit_time": "2024-01-02T09:55:00", "net_pnl": 10},
        {"trade_id": "T2", "sequence": 1, "exit_time": "2024-01-02T10:00:00", "net_pnl": 20},
    ]
    shuffled_trades = [trades[2], trades[0], trades[1]]

    curve = _generate(trades, initial_capital=1000)
    shuffled_curve = _generate(shuffled_trades, initial_capital=1000)

    assert [point.get("trade_id") for point in curve[1:]] == ["T1", "T2", "T3"]
    assert shuffled_curve == curve
    assert [point["equity"] for point in curve] == [1000.0, 1010.0, 1030.0, 1060.0]


def test_supports_legacy_exit_time_and_trade_id_aliases() -> None:
    curve = _generate(
        [
            {"trade_no": "N2", "exit_datetime": "2024-01-02T10:05:00", "sequence": 2, "net_pnl": 20},
            {"id": "N1", "close_time": "2024-01-02T10:00:00", "sequence": 1, "net_pnl": 10},
        ],
        initial_capital=1000,
    )

    assert [point["time"] for point in curve[1:]] == [
        "2024-01-02T10:00:00+00:00",
        "2024-01-02T10:05:00+00:00",
    ]
    assert [point["trade_id"] for point in curve[1:]] == ["N1", "N2"]
    assert curve[-1]["equity"] == 1030.0


def test_empty_trades_returns_initial_capital_point_only() -> None:
    assert _generate([], initial_capital=1000) == [
        {"point_index": 0, "time": None, "equity": 1000.0, "source": "initial_capital"}
    ]


def test_missing_exit_time_raises_value_error() -> None:
    with pytest.raises(ValueError, match="exit_time"):
        _generate([{"trade_id": "T1", "sequence": 1, "net_pnl": 10}], initial_capital=1000)
