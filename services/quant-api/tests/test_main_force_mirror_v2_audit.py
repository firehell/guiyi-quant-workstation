from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import guiyi_quant.indicators as indicators
from guiyi_quant.indicators import main_force_mirror_v2 as mfm_v2


compute_main_force_mirror_v2 = mfm_v2.compute_main_force_mirror_v2


def test_audit_entry_is_available_from_the_indicator_kernel() -> None:
    """Catches leaving the research entry inaccessible at the kernel boundary."""
    assert (
        indicators.compute_main_force_mirror_v2_with_audit
        is mfm_v2.compute_main_force_mirror_v2_with_audit
    )


_REPO_ROOT = Path(__file__).resolve().parents[3]
_V2_GOLDEN_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "main_force_mirror_v2_golden.json"
)


def _load_golden_inputs() -> dict[str, list[object]]:
    fixture = json.loads(_V2_GOLDEN_PATH.read_text(encoding="utf-8"))
    bars = fixture["bars"]
    parsed = [
        datetime.fromisoformat(str(bar["time"]).replace("Z", "+00:00"))
        for bar in bars
    ]
    return {
        "bar_end": parsed,
        "trading_day": [value.date() for value in parsed],
        "physical_contract": [bar["physical_contract"] for bar in bars],
        "open_": [bar["open"] for bar in bars],
        "high": [bar["high"] for bar in bars],
        "low": [bar["low"] for bar in bars],
        "close": [bar["close"] for bar in bars],
        "volume": [bar["volume"] for bar in bars],
        "open_interest": [bar["open_interest"] for bar in bars],
    }


def _latch_inputs() -> dict[str, list[object]]:
    count = 70
    bar_end = [
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
        for index in range(count)
    ]
    close = [
        100.0 + index if index <= 29 else 200.0 + (index - 30)
        for index in range(count)
    ]
    inputs: dict[str, list[object]] = {
        "bar_end": bar_end,
        "trading_day": [value.date() for value in bar_end],
        "physical_contract": ["JM2609"] * count,
        "open_": [value - 0.5 for value in close],
        "high": [value + 1.0 for value in close],
        "low": [value - 1.0 for value in close],
        "close": close,
        "volume": [1000.0 + index for index in range(count)],
        "open_interest": [
            5000.0 + 10.0 * index
            if index <= 29
            else 5150.0 - 10.0 * (index - 30)
            for index in range(count)
        ],
    }
    _replace_bar(
        inputs,
        30,
        open_=150.0,
        high=250.0,
        low=128.0,
        close=200.0,
        volume=5000.0,
        open_interest=5150.0,
    )
    _replace_bar(
        inputs,
        68,
        open_=237.5,
        high=239.0,
        low=237.0,
        close=238.0,
        volume=3000.0,
        open_interest=4830.0,
    )
    _replace_bar(
        inputs,
        69,
        open_=238.5,
        high=243.0,
        low=232.0,
        close=239.0,
        volume=5000.0,
        open_interest=4730.0,
    )
    return inputs


def _replace_bar(
    inputs: dict[str, list[object]],
    index: int,
    **values: float,
) -> None:
    for name, value in values.items():
        inputs[name][index] = value


def test_audit_preserves_golden_result_and_unrounded_caution_evidence() -> None:
    """Catches audit mode recomputing or rounding the frozen V2 result/evidence."""
    inputs = _load_golden_inputs()

    default = compute_main_force_mirror_v2(**inputs)
    audited = mfm_v2.compute_main_force_mirror_v2_with_audit(**inputs)

    assert asdict(audited.result) == asdict(default)
    assert len(audited.trace) == len(default.points)
    assert [item.bar_end for item in audited.trace] == [
        point.bar_end for point in default.points
    ]
    assert [item.physical_contract for item in audited.trace] == [
        point.physical_contract for point in default.points
    ]

    item = audited.trace[30]
    assert item.atr14 == pytest.approx(35.20618272770096)
    assert item.volume_mean20 == pytest.approx(1219.0)
    assert item.range_high20 == pytest.approx(1000.0)
    assert item.range_low20 == pytest.approx(110.0)
    assert item.oi_baseline20 == pytest.approx(15.567444299696426)
    assert item.price_impulse == pytest.approx(2.1871158425651975)
    assert item.clv == pytest.approx(0.18032786885245902)
    assert item.direction == pytest.approx(1.5850794504513759)
    assert item.long_open_pressure == 0.0
    assert item.short_open_pressure == 0.0
    assert item.prior_long_open_pressure_max == pytest.approx(0.32822859363205464)
    assert item.prior_short_open_pressure_max == pytest.approx(0.35883807715390914)
    assert item.prior_high_max == 124.0
    assert item.prior_low_min == 117.0
    assert item.upper_wick_ratio == pytest.approx(50.0 / 122.0)
    assert item.lower_wick_ratio == pytest.approx(22.0 / 122.0)
    assert item.long_score == 70.0
    assert item.short_score == 45.0
    assert item.long_candidate is True
    assert item.short_candidate is False
    assert item.components.long_short_cover_dominated is True
    assert item.components.long_open_pressure_divergence is True
    assert item.components.long_high_volume_exhaustion is True
    assert item.trigger == "long_chase_caution"
    assert item.latch_before.long_armed is True
    assert item.latch_after.long_armed is False

    conflict = audited.trace[36]
    assert conflict.long_candidate is True
    assert conflict.short_candidate is True
    assert conflict.conflict is True
    assert conflict.trigger is None
    assert conflict.latch_after == conflict.latch_before


def test_audit_explains_range_rearm_and_disarmed_candidate_suppression() -> None:
    """Catches hiding the state transitions that distinguish score from latch."""
    golden = mfm_v2.compute_main_force_mirror_v2_with_audit(
        **_load_golden_inputs()
    )

    assert golden.trace[33].rearm_reasons == ("long_range",)
    assert golden.trace[33].latch_before.long_armed is False
    assert golden.trace[33].latch_after.long_armed is True
    assert golden.trace[34].trigger == "long_chase_caution"

    suppressed = mfm_v2.compute_main_force_mirror_v2_with_audit(**_latch_inputs())
    item = suppressed.trace[69]
    assert item.long_score == 70.0
    assert item.long_candidate is True
    assert item.latch_before.long_armed is False
    assert item.long_disarmed_suppressed is True
    assert item.trigger is None


def test_audit_explains_build_rearm_without_lowering_the_frozen_threshold() -> None:
    """Catches losing the build-streak rearm path or conflating it with range reset."""
    inputs = _latch_inputs()
    for index in range(63, 69):
        _replace_bar(
            inputs,
            index,
            open_=247.0,
            high=249.0,
            low=240.0,
            close=248.0,
            open_interest=5000.0 + 100.0 * (index - 63),
        )
    _replace_bar(
        inputs,
        69,
        open_=280.0,
        high=350.0,
        low=240.0,
        close=300.0,
        volume=5000.0,
        open_interest=4800.0,
    )

    audited = mfm_v2.compute_main_force_mirror_v2_with_audit(**inputs)

    assert audited.trace[65].long_score == 30.0
    assert audited.trace[65].rearm_reasons == ("long_build",)
    assert audited.trace[65].latch_after.long_armed is True
    assert audited.trace[69].long_score == 70.0
    assert audited.trace[69].trigger == "long_chase_caution"


def test_audit_marks_contract_and_invalid_input_reset_boundaries() -> None:
    """Catches latch state leaking across a roll or an invalid input gap."""
    inputs = _latch_inputs()
    inputs["physical_contract"][31:] = ["JM2701"] * 39
    audited_roll = mfm_v2.compute_main_force_mirror_v2_with_audit(**inputs)

    assert audited_roll.trace[0].reset_boundary == "series_start"
    assert audited_roll.trace[31].reset_boundary == "physical_contract_change"
    assert audited_roll.trace[31].latch_before.long_armed is False
    assert audited_roll.trace[31].latch_after.long_armed is True

    inputs = _latch_inputs()
    inputs["volume"][31] = -1.0
    audited_invalid = mfm_v2.compute_main_force_mirror_v2_with_audit(**inputs)

    assert audited_invalid.trace[31].reset_boundary == "invalid_input"
    assert audited_invalid.trace[31].unavailable_reason == "MFM_V2_INPUT_INVALID"
    assert audited_invalid.trace[31].latch_before.long_armed is False
    assert audited_invalid.trace[31].latch_after.long_armed is True
