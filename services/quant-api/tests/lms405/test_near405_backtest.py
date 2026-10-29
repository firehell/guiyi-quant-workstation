from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
import pytest
from lms_near405_backtest import execute_reference

T = datetime(2026, 1, 5, 1, tzinfo=UTC)


def minute(i, price, volume="10", flat=False):
    return dict(
        contract="TA2605",
        bar_end=(T + timedelta(minutes=i + 1)).isoformat(),
        trading_day="2026-01-05",
        open=str(price),
        high=str(price if flat else price + 2),
        low=str(price if flat else price - 2),
        close=str(price),
        volume=volume,
    )


def intent(second, long, short, cycle="c1"):
    return dict(
        known_at=(T + timedelta(seconds=second)).isoformat(),
        after=dict(
            long=str(long), short=str(short), cycle_id=cycle if long + short else None
        ),
        before=dict(cycle_id=cycle),
        action="CLEAR" if long + short == 0 else "STATE",
        decision_id=str(second),
    )


def test_strict_time_next_minute_and_costed_roundtrip():
    bars = [
        minute(-1, 98),
        minute(0, 100),
        minute(1, 102),
        minute(2, 104),
        minute(3, 106),
    ]
    r = execute_reference(
        bars, [intent(0, 1, 0), intent(120, 0, 0)], D(5), D(2), D(3), 1
    )
    assert r["fills"][0]["at"] == (T + timedelta(minutes=1)).isoformat()
    assert r["realized_gross"] == "20" and r["net_pnl"] == "-6"
    assert len(r["closed_cycles"]) == 1


def test_lock_unlock_two_legs_and_no_forced_end_close():
    b = [minute(-1, 98)] + [
        minute(i, p) for i, p in enumerate([100, 102, 104, 106, 108, 110])
    ]
    r = execute_reference(
        b,
        [intent(0, 1, 0), intent(60, 1, 1), intent(120, 1, 0), intent(180, 0, 0)],
        D(5),
        D(2),
        D(0),
        0,
    )
    assert len(r["fills"]) == 4
    assert r["realized_gross"] == "20"
    open_r = execute_reference(b, [intent(0, 1, 0)], D(5), D(2), D(0), 0)
    assert not open_r["closed_cycles"] and open_r["unrealized"] == "40"


def test_zero_volume_and_flat_bar_do_not_fill():
    b = [
        minute(-1, 98, "0"),
        minute(0, 100, "0"),
        minute(1, 102, flat=True),
        minute(2, 104),
        minute(3, 106),
        minute(4, 108),
    ]
    r = execute_reference(b, [intent(0, 1, 0)], D(5), D(2), D(0), 0)
    assert r["fills"][0]["at"] == (T + timedelta(minutes=4)).isoformat()
    assert r["blocked_counts"] == {"ZERO_VOLUME": 2, "ONE_PRICE_BAR": 1}


def test_cross_contract_cannot_be_hidden_in_one_execution_segment():
    b = [minute(0, 100), minute(1, 102) | {"contract": "TA2609"}]
    with pytest.raises(ValueError, match="CONTRACT"):
        execute_reference(b, [], D(5), D(2), D(0), 0)


def test_future_minute_liquidity_cannot_change_earlier_open_reference():
    b = [minute(-1, 98), minute(0, 100), minute(1, 102), minute(2, 120)]
    r = execute_reference(b, [intent(0, 1, 0)], D(5), D(2), D(0), 0)
    changed = [dict(x) for x in b]
    changed[2].update(high="102", low="102", volume="0")
    a = execute_reference(changed, [intent(0, 1, 0)], D(5), D(2), D(0), 0)
    assert (
        r["fills"][0]["at"] == a["fills"][0]["at"]
        and r["fills"][0]["reference_price"] == a["fills"][0]["reference_price"]
    )


def test_short_mirror_and_terminal_unexecuted_intent():
    b = [minute(-1, 98), minute(0, 100), minute(1, 102), minute(2, 104), minute(3, 106)]
    r = execute_reference(
        b,
        [intent(0, 0, 1), intent(120, 0, 0), intent(240, 1, 0, "c2")],
        D(5),
        D(2),
        D(0),
        0,
    )
    assert r["realized_gross"] == "-20"
    assert r["unobserved_execution_intents"] == 1 and not r["open_legs"]


def test_partial_cycle_cannot_be_silently_relabelled():
    b = [minute(-1, 98), minute(0, 100), minute(1, 102), minute(2, 104), minute(3, 106)]
    with pytest.raises(ValueError, match="NEW_CYCLE_WHILE_EXECUTION_NOT_FLAT"):
        execute_reference(
            b, [intent(0, 1, 0), intent(120, 1, 0, "new")], D(5), D(2), D(0), 0
        )


def test_aggregate_reconciles_closed_open_costs_and_monthly():
    from lms_near405_backtest import aggregate

    b = [minute(-1, 98), minute(0, 100), minute(1, 102), minute(2, 104), minute(3, 106)]
    a = execute_reference(b, [intent(0, 1, 0), intent(120, 0, 0)], D(5), D(2), D(3), 1)
    open_r = execute_reference(b, [intent(0, 0, 1)], D(5), D(2), D(3), 1)
    total = aggregate([a, open_r])
    assert D(total["net_pnl"]) == D(total["realized_gross"]) + D(
        total["unrealized"]
    ) - D(total["fees"]) - D(total["slippage_cost"])
    assert sum(map(D, total["monthly_pnl"].values())) == D(total["net_pnl"])
    assert total["closed_cycles"] == 1 and D(total["max_drawdown"]) >= 0
