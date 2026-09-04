from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.oscillation_channel import (
    OscillationAction,
    OscillationState,
    calculate_channel_series,
    calculate_oscillation_series,
    restore_oscillation_state,
    step_oscillation,
)


_GOLDEN = (
    (14.49, 14.78, 14.26, 14.5, 315418),
    (14.49, 14.7, 14.07, 14.22, 315540),
    (14.28, 14.48, 14.01, 14.14, 236589),
    (14.1, 14.27, 13.9, 14.23, 308357),
    (14.23, 14.54, 14.19, 14.54, 312176),
    (14.53, 15.4, 14.25, 15.4, 522845),
    (15.25, 15.38, 14.59, 14.69, 351232),
    (14.7, 14.8, 14.33, 14.5, 262878),
    (14.5, 14.69, 14.32, 14.68, 268597),
    (14.65, 14.75, 14.2, 14.54, 280953),
    (14.51, 14.58, 14.16, 14.23, 241889),
    (14.22, 14.65, 13.96, 14.32, 246079),
    (14.37, 14.38, 14.16, 14.33, 135159),
    (14.34, 14.41, 13.92, 14, 232414),
    (14, 14.23, 13.95, 14.16, 150414),
    (14.08, 14.11, 13.7, 13.86, 259663),
    (13.83, 13.87, 13.21, 13.56, 435883),
    (13.54, 14.03, 13.53, 13.99, 259971),
    (13.94, 14.14, 13.86, 13.98, 200620),
    (14.08, 15.33, 14.07, 14.83, 855038),
    (14.82, 14.88, 14.52, 14.85, 314919),
    (14.84, 14.96, 14.61, 14.89, 231040),
    (15.02, 15.02, 14.16, 14.54, 379864),
    (14.45, 15.02, 14.35, 14.83, 320414),
    (14.28, 14.53, 13.6, 13.96, 472712),
    (13.93, 14.12, 13.22, 13.31, 427408),
    (13.38, 13.58, 13.28, 13.5, 188458),
    (13.5, 13.62, 13.31, 13.37, 166690),
    (13.36, 13.58, 12.94, 12.97, 195587),
    (13.15, 13.37, 13, 13.13, 188252),
)


def make_bar(
    index: int, row, *, contract: str = "RB9999", eligible: bool = True
) -> NewowDailyBar:
    open_, high, low, close, volume = row
    day = date(2025, 9, 1) + timedelta(days=index)
    return NewowDailyBar(
        product="rb",
        physical_contract=contract,
        segment_id=f"rb:{contract}:research",
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
        open_interest=None,
        source_identity="browser:601233.SH",
        observation_eligible=eligible,
        completed=True,
    )


def golden_bars() -> tuple[NewowDailyBar, ...]:
    return tuple(make_bar(index, row) for index, row in enumerate(_GOLDEN))


def test_browser_prefix_reproduces_channel_and_scored_state_machine() -> None:
    bars = golden_bars()
    channel = calculate_channel_series(bars, period=10)
    steps = calculate_oscillation_series(bars)

    assert channel[0].upper == Decimal("14.78")
    assert channel[0].lower == Decimal("14.26")
    assert channel[9].upper == Decimal("15.4")
    assert channel[9].lower == Decimal("13.9")
    assert [
        (index, signal.action, signal.score, signal.break_label)
        for index, step in enumerate(steps)
        for signal in step.signals
    ] == [
        (13, OscillationAction.BUILD, 2, "⚠假突破"),
        (19, OscillationAction.CLEAR, 5, "⚠真突破"),
        (28, OscillationAction.BUILD, 2, "⚠假突破"),
    ]


def test_same_bar_prioritizes_clear_then_allows_new_build() -> None:
    rows = [(95, 100, 90, 95, 100)] * 9
    rows.append((90, 95, 80, 85, 100))
    rows.append((90, 110, 70, 90, 100))
    steps = calculate_oscillation_series(
        tuple(make_bar(i, row) for i, row in enumerate(rows))
    )
    assert [signal.action for signal in steps[9].signals] == [OscillationAction.BUILD]
    assert [signal.action for signal in steps[10].signals] == [
        OscillationAction.CLEAR,
        OscillationAction.BUILD,
    ]
    assert steps[10].state.holding is True


def test_prefix_restore_ineligible_and_rollover_are_safe() -> None:
    bars = golden_bars()
    full = calculate_oscillation_series(bars)
    assert calculate_oscillation_series(bars[:20]) == full[:20]
    state = restore_oscillation_state(asdict(full[19].state))
    resumed = []
    for bar in bars[20:]:
        result = step_oscillation(state, bar)
        resumed.append(result)
        state = result.state
    assert tuple(resumed) == full[20:]

    hidden = replace(bars[28], observation_eligible=False)
    hidden_result = calculate_oscillation_series(bars[:28] + (hidden,))[-1]
    assert hidden_result.signals == ()
    assert hidden_result.state.holding is True

    rollover = make_bar(30, (20, 21, 19, 20, 1), contract="RB0001")
    reset = step_oscillation(full[-1].state, rollover)
    assert reset.state.history_count == 1
    assert reset.signals == ()


@pytest.mark.parametrize("period", [4, 121, True])
def test_channel_rejects_period_outside_page_contract(period) -> None:
    with pytest.raises(ValueError, match="NEWOW_CHANNEL_PERIOD_INVALID"):
        calculate_channel_series(golden_bars(), period=period)


def test_malformed_restored_state_fails_closed() -> None:
    valid = calculate_oscillation_series(golden_bars()[:12])[-1].state
    corrupt = OscillationState(
        **{**asdict(valid), "highs": (float("nan"),) + valid.highs[1:]}
    )
    result = step_oscillation(corrupt, golden_bars()[12])
    assert result.state == OscillationState()
    assert result.signals == ()


def test_restore_oscillation_rejects_malformed_payload_without_raising() -> None:
    valid = calculate_oscillation_series(golden_bars()[:12])[-1].state

    malformed = restore_oscillation_state(
        {**asdict(valid), "history_count": valid.history_count + 1}
    )
    unknown = restore_oscillation_state({**asdict(valid), "unexpected": True})

    assert malformed == OscillationState()
    assert unknown == OscillationState()
