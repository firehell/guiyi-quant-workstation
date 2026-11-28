from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path

import pytest

from app.research_center.inputs import backtest_input, comparison_differences
from app.research_center.journal import execution_path


def test_partial_close_with_native_trading_day_and_costs():
    def fill(native_id, quantity, action, day):
        return {"native_id": native_id, "source": "SIMNOW", "scope": "account", "trading_day": day,
                "occurred_at": day.isoformat(),
                "evidence": {"direction": "LONG", "contract": "FU2603", "action": action,
                             "quantity": quantity, "price": "2500", "fee": "1.2"}}
    first, second = date(2026, 1, 6), date(2026, 1, 7)
    evidence = [fill("A", 2, "OPEN", first), fill("B", 1, "CLOSETODAY", first),
                fill("C", 1, "CLOSEYESTERDAY", second)]
    rows, reason = execution_path(evidence, "LONG", "FU2603")
    assert reason is None
    assert [row["remaining"] for row in rows] == ["2", "1", "0"]
    assert rows[-1]["trading_day"] == second
    assert rows[-1]["fees_to_date"] == "3.6"
    assert execution_path([evidence[0]] * 2, "LONG", "FU2603")[1] == "EXECUTION_LINKS_INCOMPLETE"


def test_settlement_gap_leaves_closed_trade_statistics_from_actual_run():
    path = os.environ.get("GUIYI_RESEARCH_TEST_EXPORT")
    if path is None:
        pytest.skip("frozen Plus publication required")
    publication = json.loads(Path(path).read_text())
    copy = deepcopy(publication)
    copy["equity"].pop()
    data = backtest_input(copy)
    assert data["coverage"]["reason"] == "EVALUATION_COVERAGE_UNPROVEN"
    assert data["trades"]["closed"] == 78
    assert all(row["record_type"] == "trade" for row in data["samples"])


def test_excursion_keeps_realized_gains_after_partial_exit():
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from types import SimpleNamespace

    from app.research_center.journal import excursions

    opened = datetime(2026, 1, 6, 1, 0, tzinfo=timezone.utc)
    rows = [
        {"at": opened + timedelta(minutes=clock), "remaining": quantity,
         "remaining_average_price": "100", "gross_realized_points_contracts": realized}
        for clock, quantity, realized in ((0, "2", "0"), (10, "1", "10"), (20, "0", "20"))
    ]
    bars = [
        SimpleNamespace(bar_end=opened + timedelta(minutes=clock), high=Decimal(high),
                        low=Decimal(low), is_strict_no_trade=False)
        for clock, high, low in ((5, "110", "97"), (15, "120", "110"))
    ]
    path = excursions(rows, bars, "LONG")
    assert path["mfe"] == "30"
    assert path["mae"] == "-6"
    assert path["used_bars"] == 2


def test_comparison_rejects_hidden_cost_and_execution_parameter_changes():
    left = {"source": {}, "policy": {}, "performance": {"cumulative": .1},
            "comparison_identity": {"commission_multiplier": "1", "slippage_ticks": 0, "execution_frequency": "1m"}}
    right = {**left, "comparison_identity": {"commission_multiplier": "2", "slippage_ticks": 1}}
    result = comparison_differences(left, right)
    assert {"commission_multiplier", "slippage_ticks", "execution_frequency"} <= set(result)
