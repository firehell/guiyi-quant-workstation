from datetime import date
from pathlib import Path

import pytest

from app.backtest_center import plus_costs
from app.backtest_center.codec import digest, encode
from app.backtest_center.errors import BacktestError


def test_cost_snapshot_rejects_changes_to_terms_and_requires_window_coverage(tmp_path, monkeypatch):
    first, second = date(2026, 1, 5), date(2026, 1, 6)
    terms = {
        "contract": "FU2603", "commission_type": "by_money", "long_margin_ratio": "0.09",
        "short_margin_ratio": "0.09", "open_commission": "0.00005", "close_commission": "0.00005",
        "close_commission_today": "0.0",
    }
    rows = [{**terms, "trading_date": day.isoformat()} for day in (first, second)]
    monkeypatch.setattr(plus_costs, "ROWS_SHA256", digest(rows))
    path = tmp_path / "costs.json"
    path.write_text(encode({"source": plus_costs.SOURCE, "rows": rows}))
    costs = plus_costs.DatedCosts.load(path, "FU2603", (second,))
    assert tuple(costs.rows) == (second,)
    assert costs.snapshot()["cost_rows_sha256"] == digest(rows)
    costs.verify_unchanged()
    with pytest.raises(BacktestError, match="PLUS_COST_PROFILE_COVERAGE_MISSING"):
        plus_costs.DatedCosts.load(path, "FU2603", (date(2026, 1, 7),))
    with pytest.raises(BacktestError, match="PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE"):
        plus_costs.DatedCosts.load(Path("relative"), "FU2603", (second,))
    rows[-1]["open_commission"] = "0.00006"
    path.write_text(encode({"source": plus_costs.SOURCE, "rows": rows}))
    with pytest.raises(BacktestError, match="PLUS_COST_PROFILE_NOT_VERIFIED"):
        plus_costs.DatedCosts.load(path, "FU2603", (second,))
    with pytest.raises(BacktestError, match="PLUS_COST_PROFILE_CHANGED_DURING_RUN"):
        costs.verify_unchanged()


def test_settlement_uses_verifiable_next_margin_even_when_run_ends_before_the_next_session(tmp_path, monkeypatch):
    from decimal import Decimal

    first, second = date(2026, 1, 15), date(2026, 1, 16)
    rows = [
        {"contract": "FU2603", "trading_date": day.isoformat(), "long_margin_ratio": margin}
        for day, margin in ((first, "0.09"), (second, "0.10"))
    ]
    monkeypatch.setattr(plus_costs, "ROWS_SHA256", digest(rows))
    path = tmp_path / "costs.json"
    path.write_text(encode({"source": plus_costs.SOURCE, "rows": rows}))
    costs = plus_costs.DatedCosts.load(path, "FU2603", (first,))
    assert tuple(costs.rows) == (first,)
    assert costs.rows[first]["long_margin_ratio"] == "0.09"
    assert costs.settlement_long_margin(first) == Decimal("0.10")
    assert costs.snapshot()["margin_change_at_preceding_settlement"] == {"2026-01-15": "2026-01-16"}


def test_adjacent_cost_profiles_record_their_own_settlement_effective_days(tmp_path, monkeypatch):
    rows = [
        {"contract": contract, "trading_date": trading_day, "long_margin_ratio": margin}
        for contract, trading_day, margin in (
            ("FU2603", "2026-02-05", "0.10"), ("FU2603", "2026-02-06", "0.11"),
            ("FU2604", "2026-02-12", "0.11"), ("FU2604", "2026-02-13", "0.14"),
        )
    ]
    monkeypatch.setattr(plus_costs, "ADJACENT_ROWS_SHA256", digest(rows))
    profile = tmp_path / "adjacent.json"
    profile.write_text(encode({"source": plus_costs.SOURCE, "rows": rows}))
    for contract, previous, effective in (
        ("FU2603", "2026-02-05", "2026-02-06"), ("FU2604", "2026-02-12", "2026-02-13"),
    ):
        day = date.fromisoformat(previous)
        costs = plus_costs.DatedCosts.load(profile, contract, (day,))
        assert costs.rows[day] != costs.margin_at_settlement[day]
        assert costs.margin_at_settlement[day]["trading_date"] == effective
        assert costs.snapshot()["margin_change_at_preceding_settlement"] == {previous: effective}
        assert costs.snapshot()["cost_profile_id"] == plus_costs.ADJACENT_COST_PROFILE
