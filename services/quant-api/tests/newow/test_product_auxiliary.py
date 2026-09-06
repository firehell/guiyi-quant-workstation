from __future__ import annotations

from dataclasses import asdict, fields, replace
from datetime import timedelta

import pytest

from guiyi_quant.newow.cup_handle import calculate_cup_handle_series
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import replay_strategy
from guiyi_quant.newow.product_auxiliary import calculate_product_auxiliary
from guiyi_quant.newow.product_contracts import (
    FeatureRuntimeStatus,
    ProductBar,
    ProductFrequency,
)
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector
from guiyi_quant.newow.subplots import (
    calculate_main_force_control,
    calculate_up_down_energy,
    calculate_zhaoyao_mirror,
)
from tests.newow.fixtures import bullish_true_cup_handle


def _mirror(result):
    (mirror,) = result.retrospective_layers
    assert mirror.name == "zhaoyao_mirror"
    return mirror


def _two_owner_segments(bars: tuple[ProductBar, ...]) -> tuple[ProductBar, ...]:
    split = len(bars) // 2
    return tuple(
        product_bar
        if index < split
        else replace(
            product_bar,
            bar=replace(
                product_bar.bar,
                physical_contract="RB2711",
                segment_id="rb:RB2711:2026-02-01T00:00:00+00:00",
            ),
        )
        for index, product_bar in enumerate(bars)
    )


def _raw_segments(
    bars: tuple[ProductBar, ...],
) -> tuple[tuple[NewowDailyBar, ...], ...]:
    split = len(bars) // 2
    return (
        tuple(product_bar.bar for product_bar in bars[:split]),
        tuple(product_bar.bar for product_bar in bars[split:]),
    )


def test_three_subplots_match_original_primitives_per_exact_owner_segment(
    product_cases,
) -> None:
    case = product_cases.primitive_input("trend", "60m")
    bars = _two_owner_segments(case.bars)

    result = calculate_product_auxiliary(case.identity, bars)

    raw_segments = _raw_segments(bars)
    assert tuple(segment.value for segment in result.main_force_control.segments) == (
        calculate_main_force_control(raw_segments[0]),
        calculate_main_force_control(raw_segments[1]),
    )
    assert tuple(segment.value for segment in result.up_down_energy.segments) == (
        calculate_up_down_energy(raw_segments[0]),
        calculate_up_down_energy(raw_segments[1]),
    )
    mirror = _mirror(result)
    assert tuple(segment.value for segment in mirror.segments) == (
        calculate_zhaoyao_mirror(raw_segments[0]),
        calculate_zhaoyao_mirror(raw_segments[1]),
    )
    assert mirror.repainting is True
    assert mirror.formal_signal_eligible is False
    assert not {"actions", "hints"} & {field.name for field in fields(result)}
    assert not hasattr(result, "actions")
    assert not hasattr(result, "hints")


def test_mirror_is_stored_only_in_the_retrospective_dataclass_field(
    product_cases,
) -> None:
    case = product_cases.primitive_input("trend", "60m")

    result = calculate_product_auxiliary(case.identity, case.bars[:20])

    field_names = tuple(field.name for field in fields(result))
    serialized = asdict(result)
    assert "retrospective_layers" in field_names
    assert "retrospective_layers" in serialized
    assert "mirror" not in field_names
    assert "mirror" not in serialized
    assert not hasattr(result, "mirror")
    mirror = _mirror(result)
    assert serialized["retrospective_layers"][0]["name"] == mirror.name
    assert mirror.repainting is True
    assert mirror.formal_signal_eligible is False


@pytest.mark.parametrize(
    ("count", "control", "energy", "mirror"),
    [
        (9, "warming", "warming", "warming"),
        (10, "ready", "warming", "warming"),
        (15, "ready", "ready", "warming"),
        (20, "ready", "ready", "ready"),
    ],
)
def test_each_subplot_keeps_its_own_short_prefix_warming(
    product_cases,
    count: int,
    control: str,
    energy: str,
    mirror: str,
) -> None:
    case = product_cases.primitive_input("oscillation", "1w")

    result = calculate_product_auxiliary(case.identity, case.bars[:count])

    assert result.main_force_control.status == control
    assert result.up_down_energy.status == energy
    assert _mirror(result).status == mirror


def test_cup_handle_is_trend_daily_only_and_honours_confirmation_cutoff(
    product_cases,
) -> None:
    hourly = product_cases.primitive_input("trend", "60m")
    hourly_result = calculate_product_auxiliary(hourly.identity, hourly.bars)
    assert hourly_result.cup_handle.status == FeatureRuntimeStatus.NOT_APPLICABLE
    assert all(
        segment.status.status == FeatureRuntimeStatus.NOT_APPLICABLE
        for segment in hourly_result.cup_handle.segments
    )

    daily = product_cases.primitive_input("trend", "1d")
    raw_bars = bullish_true_cup_handle()
    bars = tuple(ProductBar(bar, ProductFrequency.DAILY) for bar in raw_bars)
    direct = calculate_cup_handle_series(raw_bars)
    witness = next(
        step.state.ready_witness for step in direct if step.state.ready_witness
    )
    before_confirmation = witness.confirmed_at - timedelta(microseconds=1)

    before = calculate_product_auxiliary(
        daily.identity, bars, as_of=before_confirmation
    )
    confirmed = calculate_product_auxiliary(
        daily.identity, bars, as_of=witness.confirmed_at
    )

    assert before.cup_handle.segments[0].value == ()
    assert confirmed.cup_handle.segments[0].value == (witness,)
    exposed = confirmed.cup_handle.segments[0].value[0]
    assert exposed.left_rim.pivot_at == witness.left_rim.pivot_at
    assert exposed.left_rim.confirmed_at == witness.left_rim.confirmed_at
    assert exposed.confirmed_at == witness.confirmed_at
    assert exposed.formula_version == "newow_cup_handle_v1"
    assert confirmed.cup_handle.page_parity is False


def test_cup_handle_is_not_applicable_to_non_trend_daily(product_cases) -> None:
    case = product_cases.primitive_input("main_rise", "1d")

    result = calculate_product_auxiliary(case.identity, case.bars)

    assert result.cup_handle.status == FeatureRuntimeStatus.NOT_APPLICABLE
    assert result.cup_handle.segments[0].value is None


def test_mirror_can_repaint_without_changing_prefix_actions_or_reference_trades(
    product_cases,
) -> None:
    case = product_cases.primitive_input("trend", "60m")
    prefix_length = 28
    cutoff = case.bars[prefix_length - 1].bar.bar_end

    prefix_auxiliary = calculate_product_auxiliary(
        case.identity, case.bars[:prefix_length], as_of=cutoff
    )
    future_auxiliary = calculate_product_auxiliary(
        case.identity, case.bars, as_of=case.bars[-1].bar.bar_end
    )
    prefix_mirror = _mirror(prefix_auxiliary).segments[0].value
    future_mirror = _mirror(future_auxiliary).segments[0].value
    assert prefix_mirror is not None and future_mirror is not None
    assert prefix_mirror.peaks != future_mirror.peaks[:prefix_length]

    prefix_replay = replay_strategy(case.identity, case.bars[:prefix_length])
    full_replay = replay_strategy(case.identity, case.bars)
    assert prefix_replay.actions == tuple(
        action for action in full_replay.actions if action.bar_end <= cutoff
    )
    projector = ReferenceTradeProjector()
    assert projector.project(prefix_replay, (), cutoff) == projector.project(
        full_replay, (), cutoff
    )


def test_auxiliary_does_not_duplicate_main_rise_hints_or_filter_flat_history(
    product_cases,
) -> None:
    case = product_cases.primitive_input("main_rise", "60m")
    before = replay_strategy(case.identity, case.bars)
    flat_hints = tuple(
        hint
        for frame in before.frames
        if frame.main_state == "FLAT"
        for hint in frame.hints
    )
    assert flat_hints

    auxiliary = calculate_product_auxiliary(case.identity, case.bars)
    after = replay_strategy(case.identity, case.bars)

    assert not {"actions", "hints"} & {field.name for field in fields(auxiliary)}
    assert not hasattr(auxiliary, "actions")
    assert not hasattr(auxiliary, "hints")
    assert after == before
    assert (
        tuple(
            hint
            for frame in after.frames
            if frame.main_state == "FLAT"
            for hint in frame.hints
        )
        == flat_hints
    )
