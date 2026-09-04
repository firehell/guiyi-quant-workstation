from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from guiyi_quant.newow.magic11 import (
    Magic11Anchor,
    Magic11Label,
    Magic11State,
    calculate_magic11_series,
    initial_magic11_state,
    step_magic11,
)
from guiyi_quant.newow.models import NewowDailyBar


def make_bar(
    index: int,
    *,
    high: float,
    low: float,
    physical_contract: str = "RB2701",
    segment_id: str = "rb:RB2701:2026-01-01",
    eligible: bool = True,
) -> NewowDailyBar:
    day = date(2026, 1, 1) + timedelta(days=index)
    close = (high + low) / 2
    return NewowDailyBar(
        product="rb",
        physical_contract=physical_contract,
        segment_id=segment_id,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal(str(close)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=1,
        open_interest=None,
        source_identity="fixture:magic11",
        observation_eligible=eligible,
        completed=True,
    )


def low_then_high_cycle() -> tuple[NewowDailyBar, ...]:
    bars = [make_bar(0, high=100, low=90)]
    bars.extend(make_bar(index, high=99, low=91) for index in range(1, 12))
    bars.append(make_bar(12, high=110, low=95))
    bars.extend(make_bar(index, high=109, low=96) for index in range(13, 24))
    return tuple(bars)


def marker_facts(results):
    return tuple(
        (index, result.active_anchor, result.marker.label)
        for index, result in enumerate(results)
        if result.marker is not None
    )


def test_page_cycle_tie_prefers_low_and_emits_exact_4_7_11_sequence() -> None:
    results = calculate_magic11_series(low_then_high_cycle())

    assert results[0].low_point is True
    assert results[0].high_point is True
    assert results[0].active_anchor is Magic11Anchor.LOW
    assert marker_facts(results) == (
        (4, Magic11Anchor.LOW, Magic11Label.HIGH4),
        (7, Magic11Anchor.LOW, Magic11Label.LOW7),
        (11, Magic11Anchor.LOW, Magic11Label.TURN11),
        (16, Magic11Anchor.HIGH, Magic11Label.LOW4),
        (19, Magic11Anchor.HIGH, Magic11Label.HIGH7),
        (23, Magic11Anchor.HIGH, Magic11Label.TURN11),
    )
    assert [result.count_line_color for result in results[:12]] == [
        "newow-magic11-yellow"
    ] * 12
    assert [result.count_line_color for result in results[12:]] == [
        "newow-magic11-red"
    ] * 12


def test_current_bar_is_in_60_bar_extreme_and_reference_windows_are_exact() -> None:
    history = tuple(
        make_bar(index, high=100 + index / 100, low=90 + index / 100)
        for index in range(60)
    )
    new_low = make_bar(60, high=99, low=80)
    result = step_magic11(calculate_magic11_series(history)[-1].state, new_low)

    assert result.low_point is True
    assert result.high_point is False
    assert result.active_anchor is Magic11Anchor.LOW
    assert result.age == 0


def test_prefix_incremental_restore_rollover_and_ineligible_output_are_safe() -> None:
    bars = low_then_high_cycle()
    full = calculate_magic11_series(bars)
    assert calculate_magic11_series(bars[:15]) == full[:15]

    restored = Magic11State(**asdict(full[14].state))
    resumed = []
    for bar in bars[15:]:
        result = step_magic11(restored, bar)
        resumed.append(result)
        restored = result.state
    assert tuple(resumed) == full[15:]

    suppressed_bar = replace(bars[4], observation_eligible=False)
    suppressed = calculate_magic11_series(bars[:4] + (suppressed_bar,))[-1]
    assert suppressed.marker is None
    assert suppressed.count_line_color is None

    rollover = make_bar(
        24,
        high=120,
        low=100,
        physical_contract="RB2705",
        segment_id="rb:RB2705:2026-06-01",
    )
    reset = step_magic11(full[-1].state, rollover)
    assert reset.state.history_count == 1
    assert reset.active_anchor is Magic11Anchor.LOW
    assert reset.marker is None


def test_invalid_restored_state_fails_closed() -> None:
    bars = low_then_high_cycle()[:5]
    valid = calculate_magic11_series(bars)[-2].state
    corrupt = replace(valid, highs=(float("nan"),) + valid.highs[1:])
    result = step_magic11(corrupt, bars[-1])

    assert result.state == initial_magic11_state()
    assert result.marker is None
    assert result.count_line_color is None
