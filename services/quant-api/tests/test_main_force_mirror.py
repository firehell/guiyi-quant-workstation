from __future__ import annotations

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


def test_main_force_mirror_registry_is_web_observation_only() -> None:
    from guiyi_quant.indicators import get_indicator, require_formal_policy

    definition = get_indicator("main_force_mirror_v0")
    assert definition.display_type == "subpane"
    assert definition.status == "observation_only"
    assert definition.repainting_risk == "none"
    assert definition.web_capable is True
    assert definition.backtest_capable is False
    assert definition.live_capable is False
    assert definition.alert_capable is False
    assert definition.supported_intervals == ("1m", "5m", "15m", "30m", "60m", "1d", "1w")

    policy = require_formal_policy(definition.formal_policy_id, consumer="Web_manual_observation")
    assert policy.policy_id == "main_force_mirror_observation_v0"

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
    assert all(value is None for value in result.state.tolist())
    assert all(not bool(value) for value in result.ready)
