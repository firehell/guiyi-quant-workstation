from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import numpy as np
import pytest


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


def test_state_readiness_retains_no_task_2_or_3_outputs() -> None:
    result = _compute(make_valid_inputs(31))

    assert result.reason[20] is None
    assert result.caution_availability_reason[20] == "MFM_FUTURES_V1_CAUTION_WARMUP"
    assert result.state[20] is None
    assert np.isnan(result.signed_score[20])
    assert np.isnan(result.strength[20])
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


def test_seed_readiness_helpers_use_exact_first_indices() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        _ema_sma_seed,
        _wilder_atr14,
    )

    payload = make_valid_inputs(22)
    atr = _wilder_atr14(
        np.asarray(payload["high"], dtype=float),
        np.asarray(payload["low"], dtype=float),
        np.asarray(payload["close"], dtype=float),
    )
    oi_delta = np.diff(np.asarray(payload["open_interest"], dtype=float))
    oi_baseline = _ema_sma_seed(np.abs(oi_delta), 20)

    assert np.isnan(atr[12])
    assert atr[13] == 2.0
    assert np.isnan(oi_baseline[18])
    assert oi_baseline[19] == 10.0
