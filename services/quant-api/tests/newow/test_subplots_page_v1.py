from __future__ import annotations

from dataclasses import replace

import pytest

from guiyi_quant.newow.subplots import (
    MainForceStatus,
    calculate_main_force_control,
    calculate_up_down_energy,
    calculate_zhaoyao_mirror,
)
from tests.newow.test_oscillation_channel import golden_bars


def test_601233_browser_prefix_matches_all_three_subplot_primitives() -> None:
    bars = golden_bars()
    control = calculate_main_force_control(bars)
    mirror = calculate_zhaoyao_mirror(bars)
    energy = calculate_up_down_energy(bars)

    assert control is not None
    assert [control.kongpan[index] for index in (9, 19, 29)] == pytest.approx(
        [0.847851805854693, -0.4575698295716831, -7.182924058794544]
    )
    assert [control.status[index] for index in (9, 19, 29)] == [
        MainForceStatus.HIGH_CONTROL_DISTRIBUTION,
        MainForceStatus.NO_CONTROL,
        MainForceStatus.NO_CONTROL,
    ]

    assert mirror is not None
    assert [mirror.entry[index] for index in (9, 19, 29)] == [0.0, 0.0, 0.0]
    assert [mirror.wash[index] for index in (9, 19, 29)] == pytest.approx(
        [0.003974010190786347, 10.56425115955706, 11.977081798247873]
    )
    assert [mirror.distribution[index] for index in (9, 19, 29)] == pytest.approx(
        [0.0, 10.96053433342467, 0.0]
    )
    assert [mirror.markup[index] for index in (9, 19, 29)] == pytest.approx(
        [0.008966984021864298, 0.0, 0.01070364680998503]
    )

    assert energy is not None
    assert [energy.var4[index] for index in (11, 19, 29)] == pytest.approx(
        [30.88888888888886, 59.021481662991086, 5.832950083158312]
    )
    assert [energy.ma10[index] for index in (9, 19, 29)] == pytest.approx(
        [14.544, 14.126, 13.935000000000002]
    )
    assert [energy.var3[index] for index in (9, 19, 29)] == pytest.approx(
        [0.014988998899889987, -0.02029996512033475, -0.06658842858819418]
    )


def test_causal_subplots_are_prefix_invariant_but_zhaoyao_is_explicitly_repainting() -> (
    None
):
    bars = golden_bars()
    full_control = calculate_main_force_control(bars)
    prefix_control = calculate_main_force_control(bars[:24])
    full_energy = calculate_up_down_energy(bars)
    prefix_energy = calculate_up_down_energy(bars[:24])
    mirror = calculate_zhaoyao_mirror(bars)

    assert full_control is not None and prefix_control is not None
    assert full_control.kongpan[:24] == prefix_control.kongpan
    assert full_control.status[:24] == prefix_control.status
    assert full_energy is not None and prefix_energy is not None
    assert full_energy.var4[:24] == prefix_energy.var4
    assert full_energy.band_entry[:24] == prefix_energy.band_entry
    assert mirror is not None
    assert mirror.repainting is True
    assert mirror.formal_signal_eligible is False


def test_page_minimum_history_contracts_are_explicit() -> None:
    bars = golden_bars()
    assert calculate_main_force_control(bars[:9]) is None
    assert calculate_up_down_energy(bars[:14]) is None
    assert calculate_zhaoyao_mirror(bars[:19]) is None


@pytest.mark.parametrize(
    "calculator",
    [calculate_main_force_control, calculate_zhaoyao_mirror, calculate_up_down_energy],
)
def test_batch_subplots_reject_cross_contract_segment_input(calculator) -> None:
    bars = golden_bars()
    mixed = bars[:-1] + (
        replace(
            bars[-1],
            physical_contract="RB0001",
            segment_id="rb:RB0001:research",
        ),
    )

    with pytest.raises(ValueError, match="NEWOW_SUBPLOT_MIXED_SEGMENT"):
        calculator(mixed)
