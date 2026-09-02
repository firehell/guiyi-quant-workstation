from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from guiyi_quant.newow.cup_handle import initial_cup_handle_state, step_cup_handle
from guiyi_quant.newow.models import NewowDailyBar


def _bar(index: int, close: int, *, eligible: bool = True) -> NewowDailyBar:
    bar_day = date(2026, 1, 5) + timedelta(days=index)
    close_value = Decimal(close)
    return NewowDailyBar(
        product="rb",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        trading_day=bar_day,
        bar_end=datetime.combine(bar_day, datetime.min.time(), tzinfo=UTC),
        open=close_value,
        high=close_value + Decimal("1"),
        low=close_value - Decimal("1"),
        close=close_value,
        volume=100,
        open_interest=200,
        source_identity="fixture:rb:RB2701:1d",
        observation_eligible=eligible,
        completed=True,
    )


def test_confirmed_pivot_is_not_visible_before_its_reversal_bar() -> None:
    """Removing causal confirmation would leak the extreme into an earlier prefix."""

    state = initial_cup_handle_state()
    results = []
    for index, close in enumerate([100] * 14 + [102, 104, 106, 108, 110, 106, 105, 104]):
        result = step_cup_handle(state, _bar(index, close))
        results.append(result)
        state = result.state

    assert all(pivot.kind.value != "HIGH" for pivot in results[-2].state.confirmed_pivots)
    high = results[-1].state.confirmed_pivots[-1]
    assert high.pivot_at == _bar(18, 110).bar_end
    assert high.confirmed_at == _bar(21, 104).bar_end
