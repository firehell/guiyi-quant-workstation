from datetime import date
from decimal import Decimal

from scripts.research.four_unity_jm_daily import (
    contiguous_groups,
    maximum_drawdown,
    wire,
)


def test_failed_day_splits_even_when_adjacent_dates_have_data():
    rows = [
        {"day": d, "status": s}
        for d, s in [
            ("2025-01-01", "INPUTS_VERIFIED"),
            ("2025-01-02", "EXECUTION_FACTS_MISSING"),
            ("2025-01-03", "INPUTS_VERIFIED"),
            ("2025-01-06", "INPUTS_VERIFIED"),
        ]
    ]
    assert contiguous_groups(rows) == [["2025-01-01"], ["2025-01-03", "2025-01-06"]]


def test_mtm_drawdown_includes_opening_fee_and_unrealized_loss():
    assert maximum_drawdown(
        [{"pnl": Decimal(x)} for x in ["-2", "50", "-30", "0"]]
    ) == Decimal("80")


def test_json_keeps_decimal_exact_and_missing_numeric_null():
    assert wire(
        {"a": Decimal("0.000001"), "b": float("nan"), "d": date(2025, 1, 1)}
    ) == {"a": "0.000001", "b": None, "d": "2025-01-01"}


def test_dated_facts_returns_validated_execution_facts():
    from scripts.research.four_unity_jm_daily import dated_facts

    raw = {
        "schema_version": 1,
        "source": "rqdata",
        "plan_hash": "a" * 64,
        "captured_at": "2026-01-01T00:00:00+00:00",
        "contracts": {
            "JM2605": {
                "instrument": {
                    "order_book_id": "JM2605",
                    "tick_size": "0.5",
                    "contract_multiplier": "60",
                },
                "parameters": [
                    {
                        "date": "2025-12-01",
                        "long_margin_ratio": "0.2",
                        "short_margin_ratio": "0.3",
                        "commission_type": "by_money",
                        "open_commission": "0.0001",
                        "close_commission": "0.0002",
                        "close_commission_today": "0.0003",
                    }
                ],
                "daily": [
                    {
                        "date": "2025-12-01",
                        "prev_settlement": "1000",
                        "limit_up": "1100",
                        "limit_down": "900",
                    }
                ],
            }
        },
    }
    f = dated_facts(raw, "JM2605", date(2025, 12, 1))
    assert f.tick_size == Decimal("0.5") and f.multiplier == Decimal("60")
    assert f.fees.amount("close_today", Decimal("1000"), f.multiplier) == Decimal("18")
