from __future__ import annotations

from dataclasses import asdict, fields, replace
from datetime import timedelta

import pytest

from guiyi_quant.newow.cup_handle import calculate_cup_handle_series
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import label_calculation_segments, replay_strategy
from guiyi_quant.newow.product_auxiliary import calculate_product_auxiliary
from guiyi_quant.newow.product_contracts import (
    DataInterruption,
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
from guiyi_quant.newow.trend_reversal import calculate_trend_reversal
from tests.newow.fixtures import bullish_true_cup_handle


def _mirror(result):
    (mirror,) = result.retrospective_layers
    assert mirror.name == "zhaoyao_mirror"
    return mirror


def test_d1_auxiliary_restarts_at_price_gap_without_changing_owner(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    split = len(case.bars) // 2
    before = case.bars[split - 1].bar
    after = case.bars[split].bar
    gap_at = before.bar_end + (after.bar_end - before.bar_end) / 2
    gap = DataInterruption(
        case.identity.product, case.identity.frequency, after.physical_contract,
        after.segment_id, gap_at.date(), gap_at, "source-quality:test",
    )
    labeled = label_calculation_segments(case.identity, case.bars, (gap,))
    full = calculate_product_auxiliary(case.identity, labeled)
    suffix = calculate_product_auxiliary(case.identity, case.bars[split:])
    assert len(full.main_force_control.segments) == 2
    assert full.main_force_control.segments[1].segment_id != after.segment_id
    assert full.main_force_control.segments[1].value == suffix.main_force_control.segments[0].value
    assert full.trend_reversal.segments[1].value == suffix.trend_reversal.segments[0].value


@pytest.mark.parametrize(
    ("close", "rebound", "adjust"),
    [(4, False, False), (3.9, True, False), (98, False, False), (98.1, False, True)],
)
def test_trend_reversal_strict_thresholds_and_prefix(product_cases, close, rebound, adjust):
    case = product_cases.primitive_input("trend", "1d")
    template = case.bars[0].bar
    from decimal import Decimal

    bars = tuple(
        replace(template, bar_end=template.bar_end + timedelta(days=index), trading_day=template.trading_day + timedelta(days=index),
                open=Decimal("50"), high=Decimal("101"), low=Decimal("1"),
                close=Decimal(str(close if index == 119 else 50)))
        for index in range(120)
    )
    assert len(bars) == 120
    result = calculate_trend_reversal(bars)
    assert result is not None and result.enough and result.bar_count == 120
    assert (result.rebound[-1] != 0) is rebound
    assert (result.adjust[-1] != 0) is adjust
    prefix = calculate_trend_reversal(bars[:119])
    assert prefix is not None and not prefix.enough
    assert prefix.bias == result.bias[:119]


def test_trend_reversal_flat_range_is_neutral(product_cases):
    from decimal import Decimal

    case = product_cases.primitive_input("trend", "1d")
    flat = tuple(replace(item.bar, open=Decimal(100), high=Decimal(100), low=Decimal(100), close=Decimal(100)) for item in case.bars[:120])
    result = calculate_trend_reversal(flat)
    assert result is not None
    assert result.wr1[-1] == result.wr2[-1] == 50
    assert result.rebound[-1] == result.adjust[-1] == 0


def test_trend_reversal_short_owner_segment_stays_warming(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    result = calculate_product_auxiliary(case.identity, case.bars[:20])
    segment = result.trend_reversal.segments[0]
    assert result.trend_reversal.status == FeatureRuntimeStatus.WARMING
    assert segment.status.status == FeatureRuntimeStatus.WARMING
    assert segment.value is not None
    assert segment.value.bar_count == 20
    assert segment.value.enough is False


def _two_owner_segments(bars: tuple[ProductBar, ...]) -> tuple[ProductBar, ...]:
    split = len(bars) // 2
    return tuple(
        product_bar
        if index < split
        else replace(
            product_bar,
            calculation_segment_id="rb:RB2711:2026-02-01T00:00:00+00:00",
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


def test_single_component_does_not_calculate_unrequested_layers(
    product_cases, monkeypatch
) -> None:
    from guiyi_quant.newow import product_auxiliary as module

    case = product_cases.primitive_input("trend", "1d")
    calls: list[str] = []
    original = module.calculate_main_force_control
    monkeypatch.setattr(
        module,
        "calculate_main_force_control",
        lambda bars: (calls.append("main_force_control"), original(bars))[1],
    )
    monkeypatch.setattr(
        module,
        "calculate_up_down_energy",
        lambda _bars: (_ for _ in ()).throw(AssertionError("unrequested energy")),
    )
    monkeypatch.setattr(
        module,
        "calculate_zhaoyao_mirror",
        lambda _bars: (_ for _ in ()).throw(AssertionError("unrequested mirror")),
    )

    layer = module.calculate_auxiliary_component(
        case.identity, case.bars, "main_force_control", as_of=case.bars[-1].bar.bar_end
    )

    assert layer.name == "main_force_control"
    assert calls
