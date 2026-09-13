from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

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


_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "trend-channel-v3.2.82-30-bars.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text())
_GOLDEN = tuple(tuple(row) for row in _FIXTURE["bars"])


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


def test_frozen_v3_2_82_channel_matches_all_30_page_values() -> None:
    assert _FIXTURE["source"] == {
        "product_version": "v3.2.82",
        "stock_detail_sha256": "cd962170085dc2145fbaebf28a47ce6764b9f519e6032b54a896e37f0c9d0cf9",
        "strategy_calc_sha256": "80dcfa39afe5511b073ec66858e697243a3e4e994cd610a00568e602610a6192",
        "upper_expression": "HHV(high,10)",
        "lower_expression": "LLV(low,10)",
    }
    actual = calculate_channel_series(golden_bars(), period=10)

    assert [(point.upper, point.lower) for point in actual] == [
        (Decimal(upper), Decimal(lower)) for upper, lower in _FIXTURE["expected"]
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


def test_batch_channel_rejects_cross_contract_segment_input() -> None:
    bars = golden_bars()
    mixed = bars[:10] + (
        replace(
            bars[10],
            physical_contract="RB0001",
            segment_id="rb:RB0001:research",
        ),
    )

    with pytest.raises(ValueError, match="NEWOW_CHANNEL_MIXED_SEGMENT"):
        calculate_channel_series(mixed, period=10)
