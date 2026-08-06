from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


def test_new_formal_candidate_without_policy_is_blocked() -> None:
    from guiyi_quant.strategies.indicator_policy import build_formal_strategy_indicator_policy

    with pytest.raises(ValueError, match="STRATEGY_INDICATOR_POLICY_REQUIRED"):
        build_formal_strategy_indicator_policy(
            strategy_code="brand_new_formal_candidate",
            strategy_version="v0.0.1",
            profile_id="intraday_research_v1",
            execution_timing="next_bar_open",
            strategy_parameters={},
        )


def test_frozen_jm_v1b_builds_catalog_snapshot_without_mutating_params() -> None:
    from guiyi_quant.strategies.indicator_policy import (
        JM_V1B_FROZEN_POLICY_ID,
        JM_V1B_STRATEGY_CODE,
        JM_V1B_STRATEGY_VERSION,
        build_formal_strategy_indicator_policy,
    )

    params = {
        "entry_interval": "15m",
        "max_hold_bars_min": 5,
        "max_hold_bars_max": 8,
        "stop_loss_atr_multiple": 1.5,
    }
    snapshot = build_formal_strategy_indicator_policy(
        strategy_code=JM_V1B_STRATEGY_CODE,
        strategy_version=JM_V1B_STRATEGY_VERSION,
        profile_id="intraday_research_v1",
        execution_timing="next_bar_open",
        strategy_parameters=params,
        cost_parameters={"rate": 0.0001, "slippage": 1.0, "size": 60},
    )

    assert snapshot.frozen_legacy is True
    assert snapshot.research_status == "frozen_legacy"
    assert JM_V1B_FROZEN_POLICY_ID in snapshot.formal_policy_ids
    assert params == {
        "entry_interval": "15m",
        "max_hold_bars_min": 5,
        "max_hold_bars_max": 8,
        "stop_loss_atr_multiple": 1.5,
    }


def test_htdy_strict_snapshot_binds_strict_v1_and_rejects_original() -> None:
    from guiyi_quant.strategies.indicator_policy import (
        HTDY_STRICT_INDICATOR,
        HTDY_STRICT_STRATEGY_CODE,
        HTDY_STRICT_STRATEGY_VERSION,
        build_formal_strategy_indicator_policy,
    )

    params = {
        "indicator_versions": [HTDY_STRICT_INDICATOR],
        "formal_policy_ids": [HTDY_STRICT_INDICATOR],
        "research_status": "backtest_candidate",
    }
    snapshot = build_formal_strategy_indicator_policy(
        strategy_code=HTDY_STRICT_STRATEGY_CODE,
        strategy_version=HTDY_STRICT_STRATEGY_VERSION,
        profile_id="intraday_research_v1",
        execution_timing="next_bar_open",
        strategy_parameters=params,
    )
    assert HTDY_STRICT_INDICATOR in snapshot.indicator_versions
    assert HTDY_STRICT_INDICATOR in snapshot.formal_policy_ids
    assert snapshot.research_status == "backtest_candidate"

    bad = dict(params)
    bad["indicator_versions"] = ["huotian_dayou_original_v0"]
    bad["formal_policy_ids"] = ["huotian_dayou_original_v0"]
    with pytest.raises(ValueError, match="original_v0|huotian_dayou_strict_v1"):
        build_formal_strategy_indicator_policy(
            strategy_code=HTDY_STRICT_STRATEGY_CODE,
            strategy_version=HTDY_STRICT_STRATEGY_VERSION,
            profile_id="intraday_research_v1",
            execution_timing="next_bar_open",
            strategy_parameters=bad,
        )

def test_unknown_indicator_version_and_formal_policy_id_are_blocked() -> None:
    from guiyi_quant.strategies.indicator_policy import require_formal_strategy_indicator_policy

    with pytest.raises(ValueError, match="STRATEGY_INDICATOR_POLICY_UNKNOWN_INDICATOR"):
        require_formal_strategy_indicator_policy(
            {
                "strategy_code": "x",
                "strategy_version": "v1",
                "indicator_versions": ["not_a_real_indicator"],
                "formal_policy_ids": ["ema_sma_window_v1"],
                "profile_id": "p",
                "confirmed_only": True,
                "execution_timing": "next_bar_open",
                "cost_model_version": "cost_model_v1_rate_slippage_size",
                "research_status": "formal_candidate",
            }
        )

    with pytest.raises(ValueError, match="STRATEGY_INDICATOR_POLICY_UNKNOWN_POLICY"):
        require_formal_strategy_indicator_policy(
            {
                "strategy_code": "x",
                "strategy_version": "v1",
                "indicator_versions": ["ema21"],
                "formal_policy_ids": ["not_a_real_policy"],
                "profile_id": "p",
                "confirmed_only": True,
                "execution_timing": "next_bar_open",
                "cost_model_version": "cost_model_v1_rate_slippage_size",
                "research_status": "formal_candidate",
            }
        )


def test_web_only_policy_and_frozen_legacy_spoof_are_blocked_for_formal_strategy() -> None:
    from guiyi_quant.strategies.indicator_policy import require_formal_strategy_indicator_policy

    base = {
        "strategy_code": "new_formal_strategy",
        "strategy_version": "v1",
        "profile_id": "intraday_research_v1",
        "confirmed_only": True,
        "execution_timing": "next_bar_open",
        "cost_model_version": "cost_model_v1_rate_slippage_size",
        "research_status": "formal_candidate",
    }

    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_BLOCKED"):
        require_formal_strategy_indicator_policy(
            {
                **base,
                "indicator_versions": ["macd"],
                "formal_policy_ids": ["web_macd_legacy_v1"],
            }
        )

    with pytest.raises(ValueError, match="STRATEGY_INDICATOR_POLICY_NOT_FORMAL_CAPABLE"):
        require_formal_strategy_indicator_policy(
            {
                **base,
                "indicator_versions": ["macd"],
                "formal_policy_ids": ["ema_sma_window_v1"],
            }
        )

    with pytest.raises(ValueError, match="STRATEGY_INDICATOR_POLICY_POLICY_MISMATCH"):
        require_formal_strategy_indicator_policy(
            {
                **base,
                "indicator_versions": ["ema21"],
                "formal_policy_ids": ["huotian_dayou_strict_v1"],
            }
        )

    with pytest.raises(ValueError, match="frozen_legacy is reserved"):
        require_formal_strategy_indicator_policy(
            {
                **base,
                "indicator_versions": ["ema21"],
                "formal_policy_ids": ["ema_first_value_legacy_v1"],
                "frozen_legacy": True,
            }
        )


def test_known_versioned_jm_daily_strategy_uses_frozen_legacy_consumer() -> None:
    from guiyi_quant.strategies.indicator_policy import require_formal_strategy_indicator_policy

    snapshot = require_formal_strategy_indicator_policy(
        {
            "strategy_code": "su_bing_jm_daily_ema21_macd_volume",
            "strategy_version": "v0.2.0-daily",
            "indicator_versions": ["ema21", "macd"],
            "formal_policy_ids": [
                "ema_first_value_legacy_v1",
                "strategy_macd_first_value_scale1_v1",
            ],
            "profile_id": "intraday_research_v1",
            "confirmed_only": True,
            "execution_timing": "next_bar_open",
            "cost_model_version": "cost_model_v1_rate_slippage_size",
            "research_status": "formal_candidate",
        }
    )

    assert snapshot.frozen_legacy is True

    with pytest.raises(ValueError, match="frozen_legacy is reserved"):
        require_formal_strategy_indicator_policy(
            {
                **snapshot.to_dict(),
                "strategy_version": "unregistered-version",
                "frozen_legacy": True,
            }
        )


def test_observation_only_and_unconfirmed_policy_cannot_enter_formal_snapshot() -> None:
    from guiyi_quant.strategies.indicator_policy import require_formal_strategy_indicator_policy

    base = {
        "strategy_code": "x",
        "strategy_version": "v1",
        "indicator_versions": ["huotian_dayou_original_v0"],
        "formal_policy_ids": ["ema_sma_window_v1"],
        "profile_id": "p",
        "confirmed_only": True,
        "execution_timing": "next_bar_open",
        "cost_model_version": "cost_model_v1_rate_slippage_size",
        "research_status": "formal_candidate",
    }
    with pytest.raises(ValueError, match="observation_only"):
        require_formal_strategy_indicator_policy(base)

    for value in (False, "false"):
        with pytest.raises(ValueError, match="confirmed_only"):
            require_formal_strategy_indicator_policy(
                {
                    **base,
                    "indicator_versions": ["ema21"],
                    "confirmed_only": value,
                }
            )


def test_htdy_strict_snapshot_rejects_timing_version_and_context_drift() -> None:
    from guiyi_quant.strategies.indicator_policy import (
        HTDY_STRICT_INDICATOR,
        HTDY_STRICT_STRATEGY_CODE,
        HTDY_STRICT_STRATEGY_VERSION,
        build_formal_strategy_indicator_policy,
        require_formal_strategy_indicator_policy,
    )

    base = {
        "strategy_code": HTDY_STRICT_STRATEGY_CODE,
        "strategy_version": HTDY_STRICT_STRATEGY_VERSION,
        "indicator_versions": [HTDY_STRICT_INDICATOR],
        "formal_policy_ids": [HTDY_STRICT_INDICATOR],
        "profile_id": "intraday_research_v1",
        "confirmed_only": True,
        "execution_timing": "next_bar_open",
        "cost_model_version": "cost_model_v1_rate_slippage_size",
        "research_status": "backtest_candidate",
    }
    with pytest.raises(ValueError, match="next_bar_open"):
        require_formal_strategy_indicator_policy({**base, "execution_timing": "same_bar_close"})
    with pytest.raises(ValueError, match="strategy_version"):
        require_formal_strategy_indicator_policy({**base, "strategy_version": "v9"})
    with pytest.raises(ValueError, match="CONTEXT_MISMATCH"):
        build_formal_strategy_indicator_policy(
            strategy_code="other_strategy",
            strategy_version="v1",
            profile_id="intraday_research_v1",
            execution_timing="next_bar_open",
            explicit_snapshot=base,
        )

def test_report_without_snapshot_returns_legacy_policy_unavailable() -> None:
    from guiyi_quant.strategies.indicator_policy import (
        STATUS_AVAILABLE,
        STATUS_LEGACY_UNAVAILABLE,
        resolve_report_indicator_policy,
    )

    resolved = resolve_report_indicator_policy({"report_metadata": {"profile_id": "intraday_research_v1"}})
    assert resolved["status"] == STATUS_LEGACY_UNAVAILABLE
    assert resolved["snapshot"] is None
    assert "do not infer" in str(resolved["reason"])

    with_snapshot = resolve_report_indicator_policy(
        {
            "report_metadata": {
                "indicator_policy_snapshot": {
                    "strategy_code": "x",
                    "strategy_version": "v1",
                    "indicator_versions": ["ema21"],
                    "formal_policy_ids": ["ema_sma_window_v1"],
                    "profile_id": "intraday_research_v1",
                    "confirmed_only": True,
                    "execution_timing": "next_bar_open",
                    "cost_model_version": "cost_model_v1_rate_slippage_size",
                    "research_status": "formal_candidate",
                }
            }
        }
    )
    assert with_snapshot["status"] == STATUS_AVAILABLE
    assert with_snapshot["snapshot"]["strategy_code"] == "x"

    invalid = resolve_report_indicator_policy(
        {
            "report_metadata": {
                "indicator_policy_snapshot": {
                    "strategy_code": "x",
                    "strategy_version": "v1",
                    "indicator_versions": ["huotian_dayou_original_v0"],
                }
            }
        }
    )
    assert invalid["status"] == "invalid_policy_snapshot"
    assert invalid["snapshot"] is None


def test_report14_style_read_path_does_not_invent_registry_policy() -> None:
    """Legacy report 14 style summaries stay legacy_unavailable; no Registry guess."""

    from guiyi_quant.strategies.indicator_policy import STATUS_LEGACY_UNAVAILABLE, resolve_report_indicator_policy

    report14_like = {
        "report_metadata": {
            "strategy_code": "jm_v1b_daily_direction_fast_entry",
            "strategy_version": "v1b.0",
            "profile_id": "intraday_research_v1",
        }
    }
    resolved = resolve_report_indicator_policy(report14_like)
    assert resolved["status"] == STATUS_LEGACY_UNAVAILABLE
    assert resolved["snapshot"] is None
