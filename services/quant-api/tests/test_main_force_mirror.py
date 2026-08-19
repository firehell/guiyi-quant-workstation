from __future__ import annotations

import math
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


def _mirror_api():
    import guiyi_quant.indicators as indicators

    compute = getattr(indicators, "compute_main_force_mirror", None)
    classify = getattr(indicators, "classify_main_force_mirror_state", None)
    assert callable(compute)
    assert callable(classify)
    return compute, classify


def _golden_inputs(count: int = 28):
    datetimes: list[str] = []
    open_values: list[float] = []
    high_values: list[float] = []
    low_values: list[float] = []
    close_values: list[float] = []
    volume_values: list[float] = []
    for index in range(count):
        base = 100 + index * 0.6 + 4 * math.sin(index / 2.2)
        open_value = base + 0.7 * math.sin(index * 1.7)
        close_value = base + 1.1 * math.sin(index * 1.1)
        high_value = max(open_value, close_value) + 1.5 + (index % 3) * 0.2
        low_value = min(open_value, close_value) - 1.2 - (index % 4) * 0.15
        datetimes.append(f"golden-{index}")
        open_values.append(open_value)
        high_values.append(high_value)
        low_values.append(low_value)
        close_values.append(close_value)
        volume_values.append(1000 + (index % 5) * 250 + index * 15)
    return datetimes, open_values, high_values, low_values, close_values, volume_values


def test_main_force_mirror_exposes_six_designed_observation_states() -> None:
    _, classify = _mirror_api()

    assert classify(0.20, 0.50, 0.10, 0.20) == "entry"
    assert classify(0.20, 0.50, -0.10, 0.20) == "wash"
    assert classify(0.70, 0.50, 0.10, 0.20) == "pull_up"
    assert classify(0.70, 0.50, -0.10, 0.20) == "distribute"
    assert classify(0.70, -0.50, 0.10, 0.20) == "lure"
    assert classify(0.30, -0.50, -0.10, -0.20) == "exit"


def test_caution_matches_barslast_hhv5_less_than_10_rising_edge() -> None:
    compute, _ = _mirror_api()
    highs = [1, 2, 3, 4, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -5, 6]
    result = compute(
        [f"bar-{index}" for index in range(len(highs))],
        [high - 1.2 for high in highs],
        highs,
        [high - 2 for high in highs],
        [high - 1 for high in highs],
        [1_000] * len(highs),
    )

    caution_indexes = [index for index, value in enumerate(result.caution) if bool(value)]
    assert caution_indexes == [4, 15]
    assert result.caution_level.tolist()[4] == 50.0
    assert result.caution_level.tolist()[15] == 50.0
    assert "outflow_ratio" not in result.metadata
    assert result.metadata["interpretation"] == "structural_warning_not_measured_fund_flow"


def test_caution_does_not_repeat_while_equal_hhv5_events_keep_state_active() -> None:
    compute, _ = _mirror_api()
    highs = [1, 2, 3, 4, 5, 5, 5, 4, 3, 2, 1, 0]
    result = compute(
        [f"tie-{index}" for index in range(len(highs))],
        [value - 1.0 for value in highs],
        highs,
        [value - 2.0 for value in highs],
        [value - 0.5 for value in highs],
        [1_000] * len(highs),
    )

    assert [index for index, flag in enumerate(result.caution) if bool(flag)] == [4]


def test_caution_stays_active_at_barslast_nine() -> None:
    compute, _ = _mirror_api()
    highs = [1, 2, 3, 4, 5, 4, 3, 2, 1, 0, -1, -2, -3, 6]
    result = compute(
        [f"barslast-nine-{index}" for index in range(len(highs))],
        [value - 1.0 for value in highs],
        highs,
        [value - 2.0 for value in highs],
        [value - 0.5 for value in highs],
        [1_000] * len(highs),
    )

    assert [index for index, flag in enumerate(result.caution) if bool(flag)] == [4]


def test_main_force_mirror_matches_shared_golden_observation_sample() -> None:
    compute, _ = _mirror_api()
    result = compute(*_golden_inputs())

    expected = [
        (20, -0.654814, "distribute"),
        (21, 0.697117, "exit"),
        (22, 1.896099, "exit"),
        (23, -2.603149, "lure"),
        (24, -0.181907, "lure"),
        (25, -2.923248, "pull_up"),
        (26, -0.584624, "lure"),
        (27, -2.445683, "lure"),
    ]
    actual = [
        (index, round(float(result.score[index]), 6), result.state[index])
        for index in range(len(result.score))
        if bool(result.ready[index])
    ]

    assert actual == expected
    assert [index for index, value in enumerate(result.caution) if bool(value)] == [4]


def test_main_force_mirror_registry_is_web_observation_only() -> None:
    from guiyi_quant.indicators import get_indicator, require_formal_policy

    definition = get_indicator("main_force_mirror_v0")
    assert definition.indicator_version == "designed-v0"
    assert definition.display_type == "subpane"
    assert definition.status == "observation_only"
    assert definition.repainting_risk == "none"
    assert definition.web_capable is True
    assert definition.backtest_capable is False
    assert definition.live_capable is False
    assert definition.alert_capable is False
    assert definition.supported_intervals == ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
    assert definition.default_parameters == {
        "volume_window": 20,
        "flow_ema_period": 5,
        "range_window": 20,
        "caution_high_window": 5,
        "caution_quiet_window": 10,
        "flow_clip": 3.0,
        "score_scale": 50.0,
        "exit_lure_scale": 0.35,
        "caution_level": 50.0,
    }

    policy = require_formal_policy(definition.formal_policy_id, consumer="Web_manual_observation")
    assert policy.policy_id == "main_force_mirror_observation_v0"
    assert policy.allowed_consumers == ("Web_manual_observation",)
    assert policy.blocked_consumers == (
        "formal_backtest",
        "live",
        "alert",
        "notification",
    )

    for consumer in ("formal_backtest", "live", "alert", "notification"):
        try:
            require_formal_policy(definition.formal_policy_id, consumer=consumer)
        except ValueError as exc:
            assert "FORMAL_POLICY_CONSUMER_BLOCKED" in str(exc)
        else:
            raise AssertionError(f"consumer should be blocked: {consumer}")


def test_main_force_mirror_warmup_remains_unavailable() -> None:
    compute, _ = _mirror_api()
    count = 19
    result = compute(
        [f"warmup-{index}" for index in range(count)],
        [100 + index for index in range(count)],
        [102 + index for index in range(count)],
        [98 + index for index in range(count)],
        [101 + index for index in range(count)],
        [1_000 + index for index in range(count)],
    )

    assert len(result.score) == count
    assert all(math.isnan(float(value)) for value in result.score)
    assert all(value is None for value in result.state.tolist())
    assert all(not bool(value) for value in result.ready)
