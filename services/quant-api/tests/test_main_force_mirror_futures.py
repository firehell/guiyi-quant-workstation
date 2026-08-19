from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest


_SHARED_GOLDEN_FIELDS = (
    "valid",
    "state_ready",
    "caution_ready",
    "ready",
    "reason",
    "caution_availability_reason",
    "state",
    "signed_score",
    "strength",
    "price_impulse",
    "clv",
    "volume_ratio",
    "delta_oi",
    "oi_impulse",
    "direction",
    "range_position",
    "long_open_pressure",
    "short_open_pressure",
    "long_caution_score",
    "short_caution_score",
    "caution",
    "caution_reason_codes",
)


def _json_safe_golden_value(value: object) -> object:
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return None
        return 0.0 if number == 0.0 else number
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def test_futures_v1_matches_shared_golden_across_python_and_web() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "main_force_mirror_futures_v1_golden.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == 1
    assert fixture["indicator_code"] == "main_force_mirror_futures_v1"
    assert fixture["indicator_version"] == "futures-research-v1"
    assert fixture["parameters_hash"] == "f7fd0c9bce0b08d1"

    bars = fixture["bars"]
    result = _compute(
        {
            "datetimes": [bar["time"] for bar in bars],
            "physical_contract": [bar["physical_contract"] for bar in bars],
            "open_": [bar["open"] for bar in bars],
            "high": [bar["high"] for bar in bars],
            "low": [bar["low"] for bar in bars],
            "close": [bar["close"] for bar in bars],
            "volume": [bar["volume"] for bar in bars],
            "open_interest": [bar["open_interest"] for bar in bars],
        }
    )

    assert result.metadata["indicator_code"] == fixture["indicator_code"]
    assert result.metadata["indicator_version"] == fixture["indicator_version"]
    assert result.metadata["parameters_hash"] == fixture["parameters_hash"]
    actual_points = [
        {
            field: _json_safe_golden_value(getattr(result, field)[index])
            for field in _SHARED_GOLDEN_FIELDS
        }
        for index in range(len(bars))
    ]
    assert actual_points == fixture["expected_points"]

    assert {bar["physical_contract"] for bar in bars} == {"JM2609", "AG2612"}
    assert {point["state"] for point in actual_points if point["state"]} == {
        "long_build",
        "short_build",
        "short_cover",
        "long_liquidation",
        "turnover",
    }
    assert [
        index
        for index, point in enumerate(actual_points)
        if point["caution"] == "long_chase_caution"
    ] == [30, 34]
    assert [
        index
        for index, point in enumerate(actual_points)
        if point["caution"] == "short_chase_caution"
    ] == [37]
    assert [
        index
        for index, point in enumerate(actual_points)
        if point["caution_availability_reason"]
        == "MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT"
    ] == [36]
    assert all(actual_points[index]["long_caution_score"] < 40 for index in (31, 32, 33))
    assert actual_points[33]["range_position"] < 0.65
    assert actual_points[19]["state_ready"] is False
    assert actual_points[20]["state_ready"] is True
    assert actual_points[29]["caution_ready"] is False
    assert actual_points[30]["caution_ready"] is True
    assert bars[38]["open_interest"] is None
    assert actual_points[38]["reason"] == "MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE"
    assert actual_points[40]["reason"] == "MFM_FUTURES_V1_TIMESTAMP_INVALID"


def make_valid_inputs(
    count: int,
    contract: str = "JM2609",
) -> dict[str, list[object]]:
    close = [100.0 + index for index in range(count)]
    return {
        "datetimes": [
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
            for index in range(count)
        ],
        "physical_contract": [contract] * count,
        "open_": [value - 0.5 for value in close],
        "high": [value + 1.0 for value in close],
        "low": [value - 1.0 for value in close],
        "close": close,
        "volume": [1000.0 + index for index in range(count)],
        "open_interest": [5000.0 + 10.0 * index for index in range(count)],
    }


def assert_array_prefix_equal(
    full: np.ndarray,
    prefix: np.ndarray,
    count: int,
) -> None:
    assert len(prefix) == count
    for left, right in zip(full[:count], prefix, strict=True):
        if isinstance(left, (float, np.floating)) and np.isnan(left):
            assert isinstance(right, (float, np.floating)) and np.isnan(right)
        else:
            assert left == right


def test_futures_v1_exact_identity_parameters_and_rounding() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        DEFAULT_PARAMETERS,
        INDICATOR_CODE,
        INDICATOR_VERSION,
        round_half_away_from_zero_binary64,
    )

    assert INDICATOR_CODE == "main_force_mirror_futures_v1"
    assert INDICATOR_VERSION == "futures-research-v1"
    assert isinstance(DEFAULT_PARAMETERS, MappingProxyType)
    assert list(DEFAULT_PARAMETERS.items()) == [
        ("atr_period", 14),
        ("volume_window", 20),
        ("oi_impulse_ema_period", 20),
        ("range_window", 20),
        ("pressure_divergence_window", 10),
        ("direction_price_weight", 0.7),
        ("direction_clv_weight", 0.3),
        ("direction_deadband", 0.15),
        ("oi_deadband", 0.25),
        ("volume_ratio_clip", 3.0),
        ("price_impulse_clip", 3.0),
        ("oi_impulse_clip", 3.0),
        ("strength_scale", 25.0),
        ("turnover_display_cap", 15.0),
        ("upper_location_threshold", 0.85),
        ("lower_location_threshold", 0.15),
        ("liquidation_dominated_oi_threshold", 0.5),
        ("pressure_confirmation_ratio", 0.7),
        ("high_volume_threshold", 1.5),
        ("clv_rejection_threshold", 0.25),
        ("wick_rejection_threshold", 0.35),
        ("caution_threshold", 70),
        ("rearm_score_threshold", 40),
        ("rearm_low_score_bars", 3),
        ("rearm_build_bars", 2),
        ("long_rearm_range_threshold", 0.65),
        ("short_rearm_range_threshold", 0.35),
        ("round_digits", 6),
        ("rounding_policy", "half_away_from_zero_binary64"),
    ]
    assert "closing_dominated_oi_threshold" not in DEFAULT_PARAMETERS
    assert round_half_away_from_zero_binary64(1.25, 1) == 1.3
    assert round_half_away_from_zero_binary64(-1.25, 1) == -1.3
    assert round_half_away_from_zero_binary64(-0.0, 6) == 0.0
    assert np.isnan(round_half_away_from_zero_binary64(float("nan"), 6))
    assert round_half_away_from_zero_binary64(float("inf"), 6) == float("inf")

    result = _compute(make_valid_inputs(1))
    assert result.metadata["parameters"] == dict(DEFAULT_PARAMETERS)
    assert result.metadata["parameters_hash"] == "f7fd0c9bce0b08d1"
    assert result.metadata["rounding_policy"] == DEFAULT_PARAMETERS["rounding_policy"]

    for invalid_digits in (True, -1, 1.5):
        with pytest.raises(ValueError, match="digits must be a non-negative integer"):
            round_half_away_from_zero_binary64(1.0, invalid_digits)  # type: ignore[arg-type]


def _compute(payload: dict[str, list[object]]):
    from guiyi_quant.indicators.main_force_mirror_futures import (
        compute_main_force_mirror_futures,
    )

    return compute_main_force_mirror_futures(**payload)


@pytest.mark.parametrize("bad_oi", [None, float("nan"), float("inf"), -1.0])
def test_oi_failure_is_invalid_and_resets_the_block(bad_oi: object) -> None:
    payload = make_valid_inputs(63)
    payload["open_interest"][31] = bad_oi
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE"
    assert not bool(result.valid[31])
    assert not bool(result.state_ready[31])
    assert not bool(result.caution_ready[31])
    assert bool(result.state_ready[52])
    assert bool(result.caution_ready[62])


def test_physical_contract_missing_is_invalid_and_resets_the_block() -> None:
    payload = make_valid_inputs(63)
    payload["physical_contract"][31] = "  "
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING"
    assert result.physical_contract[31] is None
    assert not bool(result.valid[31])
    assert bool(result.state_ready[52])
    assert bool(result.caution_ready[62])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open_", None),
        ("high", float("nan")),
        ("low", float("inf")),
        ("close", "not-a-number"),
        ("volume", -1.0),
    ],
)
def test_generic_invalid_numeric_input_resets_the_block(field: str, value: object) -> None:
    payload = make_valid_inputs(63)
    payload[field][31] = value
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_INPUT_INVALID"
    assert not bool(result.valid[31])
    assert bool(result.state_ready[52])
    assert bool(result.caution_ready[62])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("high", 129.0),
        ("low", 132.0),
    ],
)
def test_invalid_ohlc_relation_resets_the_block(field: str, value: object) -> None:
    payload = make_valid_inputs(63)
    payload[field][31] = value
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_INPUT_INVALID"
    assert not bool(result.valid[31])
    assert bool(result.caution_ready[62])


def test_invalid_reason_priority_is_contract_then_timestamp_then_oi_then_generic() -> None:
    payload = make_valid_inputs(4)
    payload["physical_contract"][0] = None
    payload["datetimes"][0] = "not-a-timestamp"
    payload["open_interest"][0] = None
    payload["volume"][0] = -1.0
    payload["datetimes"][1] = "not-a-timestamp"
    payload["open_interest"][1] = None
    payload["volume"][1] = -1.0
    payload["open_interest"][2] = None
    payload["volume"][2] = -1.0
    payload["volume"][3] = -1.0

    result = _compute(payload)

    assert result.reason.tolist() == [
        "MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING",
        "MFM_FUTURES_V1_TIMESTAMP_INVALID",
        "MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE",
        "MFM_FUTURES_V1_INPUT_INVALID",
    ]


def test_timestamp_parse_failure_is_invalid_and_not_a_block_seed() -> None:
    payload = make_valid_inputs(63)
    payload["datetimes"][31] = "not-a-timestamp"
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_TIMESTAMP_INVALID"
    assert not bool(result.valid[31])
    assert result.reason[32] == "MFM_FUTURES_V1_WARMUP"
    assert bool(result.state_ready[52])
    assert bool(result.caution_ready[62])


def test_duplicate_timestamp_is_invalid_and_not_a_block_seed() -> None:
    payload = make_valid_inputs(63)
    payload["datetimes"][31] = payload["datetimes"][30]
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_TIMESTAMP_INVALID"
    assert not bool(result.valid[31])
    assert result.reason[32] == "MFM_FUTURES_V1_WARMUP"
    assert bool(result.caution_ready[62])


def test_timestamp_regression_preserves_the_historical_maximum() -> None:
    payload = make_valid_inputs(64)
    payload["datetimes"][31] = payload["datetimes"][10]
    payload["datetimes"][32] = payload["datetimes"][20]
    payload["datetimes"][33] = payload["datetimes"][31] + timedelta(hours=21)
    result = _compute(payload)

    assert result.reason[31] == "MFM_FUTURES_V1_TIMESTAMP_INVALID"
    assert result.reason[32] == "MFM_FUTURES_V1_TIMESTAMP_INVALID"
    assert result.reason[33] == "MFM_FUTURES_V1_WARMUP"
    assert bool(result.valid[33])
    assert not bool(result.state_ready[52])
    assert bool(result.state_ready[53])
    assert bool(result.caution_ready[63])


def test_legal_contract_transition_seeds_a_new_warmup_block() -> None:
    payload = make_valid_inputs(62, contract=" jm2609 ")
    payload["physical_contract"][31:] = [" jm2701 "] * 31
    result = _compute(payload)

    assert result.physical_contract[0] == "JM2609"
    assert result.physical_contract[31] == "JM2701"
    assert bool(result.valid[31])
    assert result.reason[31] == "MFM_FUTURES_V1_WARMUP"
    assert not bool(result.state_ready[50])
    assert bool(result.state_ready[51])
    assert not bool(result.caution_ready[60])
    assert bool(result.caution_ready[61])


def test_readiness_boundaries_are_exact() -> None:
    result = _compute(make_valid_inputs(31))

    assert not bool(result.state_ready[19])
    assert bool(result.state_ready[20])
    assert not bool(result.caution_ready[29])
    assert bool(result.caution_ready[30])
    assert np.array_equal(result.ready, result.caution_ready)


def test_state_readiness_exposes_base_outputs_but_no_task_3_caution() -> None:
    result = _compute(make_valid_inputs(31))

    assert result.reason[20] is None
    assert result.caution_availability_reason[20] == "MFM_FUTURES_V1_CAUTION_WARMUP"
    assert result.state[20] == "long_build"
    assert result.signed_score[20] == 8.791034
    assert result.strength[20] == 8.791034
    assert np.isnan(result.long_caution_score[20])
    assert np.isnan(result.short_caution_score[20])
    assert result.caution[20] is None
    assert result.caution_reason_codes[20] == ()


def test_atr_readiness_invalidity_pauses_without_resetting_the_block() -> None:
    payload = make_valid_inputs(32)
    for field in ("open_", "high", "low", "close"):
        payload[field][:21] = [100.0] * 21
    result = _compute(payload)

    assert result.reason[20] == "MFM_FUTURES_V1_ATR_INVALID"
    assert not bool(result.state_ready[20])
    assert bool(result.state_ready[21])
    assert not bool(result.caution_ready[30])
    assert bool(result.caution_ready[31])


def test_volume_readiness_invalidity_pauses_without_resetting_the_block() -> None:
    payload = make_valid_inputs(37)
    payload["volume"] = [1000.0] * 6 + [0.0] * 20 + [1000.0] * 11
    result = _compute(payload)

    assert bool(result.state_ready[24])
    assert result.reason[25] == "MFM_FUTURES_V1_VOLUME_BASELINE_INVALID"
    assert not bool(result.state_ready[25])
    assert bool(result.state_ready[26])
    assert not bool(result.caution_ready[30])
    assert not bool(result.caution_ready[35])
    assert bool(result.caution_ready[36])


def test_range_readiness_invalidity_has_exact_reason_priority() -> None:
    payload = make_valid_inputs(32)
    payload["open_"][:21] = [100.0] * 21
    payload["high"][:21] = [102.0] + [100.0] * 20
    payload["low"][:21] = [98.0] + [100.0] * 20
    payload["close"][:21] = [100.0] * 21
    result = _compute(payload)

    assert result.reason[20] == "MFM_FUTURES_V1_RANGE_INVALID"
    assert not bool(result.state_ready[20])
    assert bool(result.state_ready[21])
    assert not bool(result.caution_ready[30])
    assert bool(result.caution_ready[31])


def test_volume_and_range_rolling_readiness_boundaries_are_exact() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        _rolling_extreme,
        _rolling_mean,
    )

    volume = np.arange(1.0, 21.0)
    high = np.arange(101.0, 121.0)
    low = np.arange(81.0, 101.0)
    volume_mean = _rolling_mean(volume, 20)
    range_high = _rolling_extreme(high, 20, maximum=True)
    range_low = _rolling_extreme(low, 20, maximum=False)

    assert np.isnan(volume_mean[18])
    assert volume_mean[19] == 10.5
    assert np.isnan(range_high[18])
    assert range_high[19] == 120.0
    assert np.isnan(range_low[18])
    assert range_low[19] == 81.0
    assert (119.0 - 81.0) / (range_high[19] - range_low[19]) == pytest.approx(
        38.0 / 39.0
    )


def test_seed_readiness_helpers_use_exact_first_indices() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        _ema_sma_seed,
        _wilder_atr14,
    )

    payload = make_valid_inputs(22)
    payload["high"][14] = 121.0
    payload["low"][14] = 120.0
    payload["close"][14] = 120.5
    atr = _wilder_atr14(
        np.asarray(payload["high"], dtype=float),
        np.asarray(payload["low"], dtype=float),
        np.asarray(payload["close"], dtype=float),
    )
    oi_delta = np.diff(np.asarray(payload["open_interest"], dtype=float))
    oi_baseline = _ema_sma_seed(np.abs(oi_delta), 20)

    assert np.isnan(atr[12])
    assert atr[13] == 2.0
    assert atr[14] == (2.0 * 13.0 + 8.0) / 14.0
    assert np.isnan(oi_baseline[18])
    assert oi_baseline[19] == 10.0


def test_exact_raw_math_uses_frozen_binary64_operation_order() -> None:
    payload = make_valid_inputs(21)
    payload["open_"][20] = 120.0
    payload["close"][20] = 120.5
    result = _compute(payload)

    assert result.price_impulse[20] == 0.75
    assert result.clv[20] == 0.5
    assert result.direction[20] == 0.675
    assert result.volume_ratio[20] == 1.009401
    assert result.oi_impulse[20] == 1.0
    assert result.range_position[20] == 0.97619
    assert result.long_open_pressure[20] == 0.678166
    assert result.short_open_pressure[20] == 0.0
    assert result.strength[20] == 16.954138


def test_oi_abs_delta_ema_recurses_after_the_sma_seed() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import _ema_sma_seed

    payload = make_valid_inputs(22)
    payload["open_interest"][21] = 5230.0
    oi_delta = np.diff(np.asarray(payload["open_interest"], dtype=float))
    oi_baseline = _ema_sma_seed(np.abs(oi_delta), 20)
    result = _compute(payload)

    assert oi_baseline[19] == 10.0
    assert oi_baseline[20] == pytest.approx(11.904761904761905)
    assert result.oi_impulse[21] == 2.52


def test_zero_oi_baseline_outputs_zero_impulse_and_turnover() -> None:
    payload = make_valid_inputs(21)
    payload["open_interest"] = [5000.0] * 21
    result = _compute(payload)

    assert result.delta_oi[20] == 0.0
    assert result.oi_impulse[20] == 0.0
    assert result.state[20] == "turnover"
    assert result.strength[20] == 0.0
    assert result.signed_score[20] == 0.0


def test_flat_bar_clv_is_zero_while_twenty_bar_range_remains_valid() -> None:
    payload = make_valid_inputs(21)
    payload["open_"][20] = 120.0
    payload["high"][20] = 120.0
    payload["low"][20] = 120.0
    payload["close"][20] = 120.0
    result = _compute(payload)

    assert bool(result.state_ready[20])
    assert result.clv[20] == 0.0
    assert result.range_position[20] == 1.0


def test_volume_ratio_cap_is_applied_before_sqrt_participation() -> None:
    payload = make_valid_inputs(21)
    payload["volume"][20] = 1_000_000_000.0
    result = _compute(payload)

    assert result.volume_ratio[20] == 3.0
    assert result.long_open_pressure[20] == 0.606218
    assert result.short_open_pressure[20] == 0.0
    assert result.strength[20] == 15.155445


def test_public_delta_oi_uses_half_away_rounding() -> None:
    payload = make_valid_inputs(21)
    payload["open_interest"][20] = 5200.1234567
    result = _compute(payload)

    assert result.delta_oi[20] == 10.123457


@pytest.mark.parametrize(
    ("close_value", "open_value", "high_value", "low_value", "expected"),
    [
        (219.0, 218.5, 220.0, 218.0, 3.0),
        (20.0, 19.5, 21.0, 19.0, -3.0),
    ],
)
def test_price_impulse_clips_at_exact_bounds(
    close_value: float,
    open_value: float,
    high_value: float,
    low_value: float,
    expected: float,
) -> None:
    payload = make_valid_inputs(21)
    payload["close"][20] = close_value
    payload["open_"][20] = open_value
    payload["high"][20] = high_value
    payload["low"][20] = low_value

    assert _compute(payload).price_impulse[20] == expected


@pytest.mark.parametrize(
    ("open_interest", "expected"),
    [(6190.0, 3.0), (4190.0, -3.0)],
)
def test_oi_impulse_clips_at_exact_bounds(
    open_interest: float,
    expected: float,
) -> None:
    payload = make_valid_inputs(21)
    payload["open_interest"][20] = open_interest

    assert _compute(payload).oi_impulse[20] == expected


@pytest.mark.parametrize(
    ("direction", "oi_impulse", "expected"),
    [
        (0.149999, 1.0, "turnover"),
        (0.15, 0.25, "long_build"),
        (-0.15, 0.25, "short_build"),
        (0.15, -0.25, "short_cover"),
        (-0.15, -0.25, "long_liquidation"),
        (1.0, 0.249999, "turnover"),
    ],
)
def test_five_state_boundaries_use_strict_deadbands(
    direction: float,
    oi_impulse: float,
    expected: str,
) -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        classify_main_force_mirror_futures_state,
    )

    assert classify_main_force_mirror_futures_state(direction, oi_impulse) == expected


def test_state_decision_uses_raw_value_before_public_rounding() -> None:
    payload = make_valid_inputs(21)
    close_value = 119.42857028571429
    payload["open_"][20] = close_value - 0.5
    payload["high"][20] = close_value + 1.0
    payload["low"][20] = close_value - 1.0
    payload["close"][20] = close_value
    result = _compute(payload)

    assert result.direction[20] == 0.15
    assert result.state[20] == "turnover"


@pytest.mark.parametrize(
    ("close_value", "expected_score"),
    [(119.4, 15.0), (118.6, -15.0)],
)
def test_turnover_signed_score_has_exact_display_cap(
    close_value: float,
    expected_score: float,
) -> None:
    payload = make_valid_inputs(21)
    payload["open_"][20] = close_value - 0.5
    payload["high"][20] = close_value + 1.0
    payload["low"][20] = close_value - 1.0
    payload["close"][20] = close_value
    payload["volume"][20] = 1_000_000_000.0
    payload["open_interest"][20] = 6190.0
    result = _compute(payload)

    assert result.state[20] == "turnover"
    assert result.strength[20] > 15.0
    assert result.signed_score[20] == expected_score


def test_turnover_with_exact_zero_direction_has_zero_signed_score() -> None:
    payload = make_valid_inputs(21)
    payload["open_"][20] = 118.5
    payload["high"][20] = 120.0
    payload["low"][20] = 118.0
    payload["close"][20] = 119.0
    result = _compute(payload)

    assert result.direction[20] == 0.0
    assert result.state[20] == "turnover"
    assert result.signed_score[20] == 0.0


def test_strength_and_signed_score_cap_at_one_hundred() -> None:
    payload = make_valid_inputs(21)
    payload["open_"][20] = 218.5
    payload["high"][20] = 220.0
    payload["low"][20] = 218.0
    payload["close"][20] = 219.0
    payload["volume"][20] = 1_000_000_000.0
    payload["open_interest"][20] = 6190.0
    result = _compute(payload)

    assert result.state[20] == "long_build"
    assert result.strength[20] == 100.0
    assert result.signed_score[20] == 100.0


@pytest.mark.parametrize(
    (
        "close_value",
        "open_interest",
        "expected_state",
        "expected_strength",
        "expected_signed_score",
    ),
    [
        (120.0, 5200.0, "long_build", 8.791034, 8.791034),
        (118.0, 5200.0, "short_build", 8.791034, -8.791034),
        (120.0, 5180.0, "short_cover", 8.791034, 8.791034),
        (118.0, 5180.0, "long_liquidation", 8.791034, -8.791034),
    ],
)
def test_compute_assigns_quadrant_state_and_signed_score(
    close_value: float,
    open_interest: float,
    expected_state: str,
    expected_strength: float,
    expected_signed_score: float,
) -> None:
    payload = make_valid_inputs(21)
    payload["open_"][20] = close_value - 0.5
    payload["high"][20] = close_value + 1.0
    payload["low"][20] = close_value - 1.0
    payload["close"][20] = close_value
    payload["open_interest"][20] = open_interest
    result = _compute(payload)

    assert result.state[20] == expected_state
    assert result.strength[20] == expected_strength
    assert result.signed_score[20] == expected_signed_score
    if open_interest > 5190.0:
        if close_value > 119.0:
            assert result.long_open_pressure[20] > 0.0
            assert result.short_open_pressure[20] == 0.0
        else:
            assert result.long_open_pressure[20] == 0.0
            assert result.short_open_pressure[20] > 0.0
    else:
        assert result.long_open_pressure[20] == 0.0
        assert result.short_open_pressure[20] == 0.0


def test_futures_v1_base_outputs_are_prefix_invariant() -> None:
    full_inputs = make_valid_inputs(80)
    prefix_inputs = {key: values[:60] for key, values in full_inputs.items()}
    full = _compute(full_inputs)
    prefix = _compute(prefix_inputs)

    assert full.state[20] == "long_build"
    for field in (
        "valid",
        "state_ready",
        "caution_ready",
        "ready",
        "reason",
        "state",
        "signed_score",
        "strength",
        "price_impulse",
        "clv",
        "volume_ratio",
        "delta_oi",
        "oi_impulse",
        "direction",
        "range_position",
        "long_open_pressure",
        "short_open_pressure",
    ):
        assert_array_prefix_equal(getattr(full, field), getattr(prefix, field), 60)


def _caution_evidence(**overrides: object):
    from guiyi_quant.indicators.main_force_mirror_futures import (
        _evaluate_main_force_mirror_futures_caution_evidence,
    )

    values: dict[str, object] = {
        "state": "turnover",
        "oi_impulse": 0.0,
        "range_position": 0.5,
        "high": 100.0,
        "low": 90.0,
        "open_": 95.0,
        "close": 95.0,
        "volume_ratio": 1.0,
        "clv": 0.0,
        "long_open_pressure": 1.0,
        "short_open_pressure": 1.0,
        "prior_highs": (110.0,) * 10,
        "prior_lows": (80.0,) * 10,
        "prior_long_open_pressures": (1.0,) * 10,
        "prior_short_open_pressures": (1.0,) * 10,
    }
    values.update(overrides)
    return _evaluate_main_force_mirror_futures_caution_evidence(**values)


@pytest.mark.parametrize(
    ("overrides", "expected_long", "expected_short", "expected_reason"),
    [
        (
            {"range_position": 0.85},
            30.0,
            0.0,
            "LONG_UPPER_EXTREME",
        ),
        (
            {"state": "short_cover", "oi_impulse": -0.5},
            30.0,
            0.0,
            "LONG_SHORT_COVER_DOMINATED",
        ),
        (
            {"high": 111.0, "long_open_pressure": 0.7},
            25.0,
            0.0,
            "LONG_OPEN_PRESSURE_DIVERGENCE",
        ),
        (
            {
                "open_": 90.0,
                "close": 92.0,
                "volume_ratio": 1.5,
                "clv": -0.6,
            },
            15.0,
            0.0,
            "LONG_HIGH_VOLUME_EXHAUSTION",
        ),
        (
            {"range_position": 0.15},
            0.0,
            30.0,
            "SHORT_LOWER_EXTREME",
        ),
        (
            {"state": "long_liquidation", "oi_impulse": -0.5},
            0.0,
            30.0,
            "SHORT_LONG_LIQUIDATION_DOMINATED",
        ),
        (
            {"low": 79.0, "short_open_pressure": 0.7},
            0.0,
            25.0,
            "SHORT_OPEN_PRESSURE_DIVERGENCE",
        ),
        (
            {
                "open_": 98.0,
                "close": 100.0,
                "volume_ratio": 1.5,
                "clv": 0.6,
            },
            0.0,
            15.0,
            "SHORT_LOW_PRICE_ABSORPTION",
        ),
    ],
)
def test_each_caution_reason_contributes_its_exact_frozen_weight(
    overrides: dict[str, object],
    expected_long: float,
    expected_short: float,
    expected_reason: str,
) -> None:
    evidence = _caution_evidence(**overrides)

    assert evidence.long_score == expected_long
    assert evidence.short_score == expected_short
    assert evidence.reason_codes == (expected_reason,)


def test_caution_reason_codes_follow_the_fixed_spec_order() -> None:
    long_evidence = _caution_evidence(
        range_position=0.85,
        state="short_cover",
        oi_impulse=-0.5,
        high=111.0,
        long_open_pressure=0.7,
        open_=90.0,
        close=92.0,
        volume_ratio=1.5,
        clv=-0.6,
    )
    short_evidence = _caution_evidence(
        range_position=0.15,
        state="long_liquidation",
        oi_impulse=-0.5,
        low=79.0,
        short_open_pressure=0.7,
        open_=98.0,
        close=100.0,
        volume_ratio=1.5,
        clv=0.6,
    )

    assert long_evidence.reason_codes == (
        "LONG_UPPER_EXTREME",
        "LONG_SHORT_COVER_DOMINATED",
        "LONG_OPEN_PRESSURE_DIVERGENCE",
        "LONG_HIGH_VOLUME_EXHAUSTION",
    )
    assert long_evidence.long_score == 100.0
    assert short_evidence.reason_codes == (
        "SHORT_LOWER_EXTREME",
        "SHORT_LONG_LIQUIDATION_DOMINATED",
        "SHORT_OPEN_PRESSURE_DIVERGENCE",
        "SHORT_LOW_PRICE_ABSORPTION",
    )
    assert short_evidence.short_score == 100.0


def test_candidate_threshold_uses_raw_score_at_exact_69_70_boundary() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        is_main_force_mirror_futures_candidate,
        round_half_away_from_zero_binary64,
    )

    raw_score_that_displays_as_70 = 69.9999996
    assert round_half_away_from_zero_binary64(raw_score_that_displays_as_70, 6) == 70.0
    assert is_main_force_mirror_futures_candidate(69.0) is False
    assert is_main_force_mirror_futures_candidate(raw_score_that_displays_as_70) is False
    assert is_main_force_mirror_futures_candidate(70.0) is True


def _latch_state(**overrides: object):
    from guiyi_quant.indicators.main_force_mirror_futures import (
        MainForceMirrorFuturesLatchState,
    )

    values: dict[str, object] = {
        "long_armed": True,
        "short_armed": True,
        "long_low_score_streak": 0,
        "short_low_score_streak": 0,
        "long_build_streak": 0,
        "short_build_streak": 0,
    }
    values.update(overrides)
    return MainForceMirrorFuturesLatchState(**values)


def _latch_step(state, **overrides: object):
    from guiyi_quant.indicators.main_force_mirror_futures import (
        step_main_force_mirror_futures_latch,
    )

    values: dict[str, object] = {
        "caution_ready": True,
        "derived_available": True,
        "block_reset": False,
        "long_score": 0.0,
        "short_score": 0.0,
        "position_state": "turnover",
        "range_position": 0.5,
    }
    values.update(overrides)
    return step_main_force_mirror_futures_latch(state, **values)


def test_latch_single_long_event_consumes_only_long_side() -> None:
    step = _latch_step(_latch_state(), long_score=70.0)

    assert step.caution == "long_chase_caution"
    assert step.reason is None
    assert step.state == _latch_state(long_armed=False)


def test_latch_single_short_event_consumes_only_short_side() -> None:
    step = _latch_step(_latch_state(), short_score=70.0)

    assert step.caution == "short_chase_caution"
    assert step.reason is None
    assert step.state == _latch_state(short_armed=False)


def test_conflict_emits_no_event_and_preserves_all_latch_state() -> None:
    before = _latch_state(
        long_armed=False,
        short_armed=False,
        long_low_score_streak=2,
        short_low_score_streak=1,
        long_build_streak=1,
        short_build_streak=2,
    )
    step = _latch_step(
        before,
        long_score=70.0,
        short_score=70.0,
        position_state="long_build",
        range_position=0.1,
    )

    assert step.caution is None
    assert step.reason == "MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT"
    assert step.state == before


def test_conflict_does_not_hide_the_next_legal_latch_event() -> None:
    before = _latch_state()
    conflict = _latch_step(before, long_score=70.0, short_score=70.0)
    legal = _latch_step(conflict.state, long_score=70.0, short_score=0.0)

    assert conflict.state == before
    assert legal.caution == "long_chase_caution"
    assert legal.state.long_armed is False
    assert legal.state.short_armed is True


def test_latch_event_clears_triggered_counters_and_advances_other_side() -> None:
    before = _latch_state(
        short_armed=False,
        long_low_score_streak=2,
        long_build_streak=1,
        short_low_score_streak=2,
    )
    step = _latch_step(
        before,
        long_score=70.0,
        short_score=0.0,
        range_position=0.5,
    )

    assert step.caution == "long_chase_caution"
    assert step.state.long_armed is False
    assert step.state.long_low_score_streak == 0
    assert step.state.long_build_streak == 0
    assert step.state.short_armed is True
    assert step.state.short_low_score_streak == 0
    assert step.state.short_build_streak == 0


def test_long_range_rearm_is_effective_only_after_the_current_bar() -> None:
    before = _latch_state(long_armed=False, long_low_score_streak=2)
    rearmed = _latch_step(before, long_score=0.0, range_position=0.649999)

    assert rearmed.caution is None
    assert rearmed.state == _latch_state()

    next_bar = _latch_step(rearmed.state, long_score=70.0)
    assert next_bar.caution == "long_chase_caution"
    assert next_bar.state.long_armed is False


def test_long_build_rearm_requires_two_consecutive_build_bars() -> None:
    before = _latch_state(
        long_armed=False,
        long_low_score_streak=2,
        long_build_streak=1,
    )
    rearmed = _latch_step(
        before,
        long_score=0.0,
        position_state="long_build",
        range_position=0.65,
    )

    assert rearmed.caution is None
    assert rearmed.state == _latch_state()


def test_short_range_rearm_is_effective_only_after_the_current_bar() -> None:
    before = _latch_state(short_armed=False, short_low_score_streak=2)
    rearmed = _latch_step(before, short_score=0.0, range_position=0.350001)

    assert rearmed.caution is None
    assert rearmed.state == _latch_state()

    next_bar = _latch_step(rearmed.state, short_score=70.0)
    assert next_bar.caution == "short_chase_caution"
    assert next_bar.state.short_armed is False


def test_short_build_rearm_requires_two_consecutive_build_bars() -> None:
    before = _latch_state(
        short_armed=False,
        short_low_score_streak=2,
        short_build_streak=1,
    )
    rearmed = _latch_step(
        before,
        short_score=0.0,
        position_state="short_build",
        range_position=0.35,
    )

    assert rearmed.caution is None
    assert rearmed.state == _latch_state()


def test_rearm_false_conditions_reset_streaks_directly_to_zero() -> None:
    before = _latch_state(
        long_armed=False,
        short_armed=False,
        long_low_score_streak=2,
        short_low_score_streak=2,
        long_build_streak=1,
        short_build_streak=1,
    )
    step = _latch_step(
        before,
        long_score=40.0,
        short_score=40.0,
        position_state="turnover",
    )

    assert step.state == _latch_state(long_armed=False, short_armed=False)


@pytest.mark.parametrize(
    ("overrides", "step_overrides"),
    [
        (
            {
                "long_armed": False,
                "long_low_score_streak": 2,
                "long_build_streak": 1,
            },
            {"derived_available": False},
        ),
        (
            {
                "short_armed": False,
                "short_low_score_streak": 2,
                "short_build_streak": 1,
            },
            {"caution_ready": False},
        ),
    ],
)
def test_rearm_derived_unavailable_and_caution_warmup_pause_all_state(
    overrides: dict[str, object],
    step_overrides: dict[str, object],
) -> None:
    before = _latch_state(**overrides)
    assert _latch_step(before, **step_overrides).state == before


def test_invalid_or_contract_block_change_resets_latch_state() -> None:
    before = _latch_state(
        long_armed=False,
        short_armed=False,
        long_low_score_streak=2,
        short_low_score_streak=2,
        long_build_streak=1,
        short_build_streak=1,
    )

    assert _latch_step(before, block_reset=True).state == _latch_state()


def test_armed_side_rearm_counters_always_remain_zero() -> None:
    before = _latch_state(
        long_low_score_streak=2,
        short_low_score_streak=2,
        long_build_streak=1,
        short_build_streak=1,
    )
    step = _latch_step(before, long_score=0.0, short_score=0.0)

    assert step.state == _latch_state()


def test_compute_integrates_raw_caution_evidence_and_latch_event() -> None:
    payload = make_valid_inputs(31)
    payload["open_"][30] = 129.0
    payload["high"][30] = 134.0
    payload["low"][30] = 128.0
    payload["close"][30] = 131.0
    payload["volume"][30] = 5000.0
    payload["open_interest"][30] = 5270.0

    result = _compute(payload)

    assert result.state[30] == "short_cover"
    assert result.long_caution_score[30] == 100.0
    assert result.short_caution_score[30] == 15.0
    assert result.caution_reason_codes[30] == (
        "LONG_UPPER_EXTREME",
        "LONG_SHORT_COVER_DOMINATED",
        "LONG_OPEN_PRESSURE_DIVERGENCE",
        "LONG_HIGH_VOLUME_EXHAUSTION",
        "SHORT_LOW_PRICE_ABSORPTION",
    )
    assert result.caution[30] == "long_chase_caution"
    assert result.reason[30] is None
    assert result.caution_availability_reason[30] is None
