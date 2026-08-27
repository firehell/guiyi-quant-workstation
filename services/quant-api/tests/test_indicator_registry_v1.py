from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


def _base_kwargs(**overrides):
    payload = {
        "indicator_code": "sample",
        "indicator_version": "v0",
        "display_name": "Sample",
        "display_type": "overlay",
        "input_fields": ("close",),
        "supported_intervals": ("1d",),
        "default_parameters": {"period": 3},
        "lookback_bars": 3,
        "warmup_bars": 2,
        "calculation_source": "test",
        "closed_bar_only": True,
        "confirmed_only": True,
        "status": "draft",
        "repainting_risk": "none",
        "repainting_notes": "test",
        "web_capable": True,
        "backtest_capable": False,
        "live_capable": False,
        "alert_capable": False,
        "default_visible": False,
        "default_color": "#ffffff",
        "output_schema": "value",
        "formal_policy_id": "ema_sma_window_v1",
        "seed_policy": "sma_window",
        "smoothing_policy": None,
        "histogram_scale": None,
    }
    payload.update(overrides)
    return payload


def test_observation_only_cannot_enable_formal_capabilities() -> None:
    from guiyi_quant.indicators import build_indicator_definition

    with pytest.raises(ValueError, match="observation_only"):
        build_indicator_definition(
            **_base_kwargs(status="observation_only", closed_bar_only=False, confirmed_only=False, backtest_capable=True)
        )


def test_observation_only_can_enable_alert_without_live_or_backtest() -> None:
    from guiyi_quant.indicators import build_indicator_definition

    definition = build_indicator_definition(
        **_base_kwargs(
            status="observation_only",
            closed_bar_only=False,
            confirmed_only=False,
            repainting_risk="known",
            alert_capable=True,
        )
    )

    assert definition.alert_capable is True
    assert definition.live_capable is False
    assert definition.backtest_capable is False


def test_registry_uses_per_indicator_frequency_contracts() -> None:
    from guiyi_quant.indicators import indicator_registry

    expected = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
    assert indicator_registry
    assert {
        code: definition.supported_intervals
        for code, definition in indicator_registry.items()
    } == {
        code: expected
        for code in (
            "ema10",
            "ema21",
            "ema60",
            "macd",
            "atr",
            "huotian_dayou_original_v0",
            "huotian_dayou_strict_v1",
        )
    }


def test_alert_rule_capabilities_keep_stable_identity_and_exact_frequencies() -> None:
    """Catches Rule identity or authoritative-input frequency drift."""
    from app.alerts.registry import HTDY_RULE, SUBING_RULE

    assert HTDY_RULE.input_frequencies == (
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
        "1d",
        "1w",
    )
    assert SUBING_RULE.input_frequencies == ("1m", "5m", "15m")
    assert SUBING_RULE.rule_code == "subing_strategy_v1"
    assert HTDY_RULE.rule_code == "htdy_original_15m"


def test_main_force_mirror_registry_and_policy_are_absent() -> None:
    """Catches retired mirror code remaining callable through generic registries."""
    from guiyi_quant.indicators import formal_policy_registry, indicator_registry

    assert not {
        code for code in indicator_registry if code.startswith("main_force_mirror")
    }
    assert not {
        policy_id
        for policy_id, policy in formal_policy_registry.items()
        if policy.indicator_family.startswith("MAIN_FORCE_MIRROR")
    }


def test_strategy_candidate_cannot_enable_live_or_alert() -> None:
    from guiyi_quant.indicators import build_indicator_definition

    with pytest.raises(ValueError, match="strategy_candidate"):
        build_indicator_definition(**_base_kwargs(status="strategy_candidate", live_capable=True, backtest_capable=True))


def test_validated_requires_confirmed_and_no_repaint() -> None:
    from guiyi_quant.indicators import build_indicator_definition

    with pytest.raises(ValueError, match="confirmed_only"):
        build_indicator_definition(**_base_kwargs(status="validated", confirmed_only=False, closed_bar_only=False))
    with pytest.raises(ValueError, match="repainting_risk"):
        build_indicator_definition(**_base_kwargs(status="validated", repainting_risk="known"))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"status": "draft", "backtest_capable": True}, "draft"),
        ({"status": "compatibility_validated", "backtest_capable": True}, "compatibility_validated"),
        ({"status": "strategy_candidate", "backtest_capable": False}, "strategy_candidate"),
        (
            {
                "status": "strategy_candidate",
                "closed_bar_only": False,
                "confirmed_only": False,
                "backtest_capable": True,
            },
            "strategy_candidate",
        ),
        (
            {
                "status": "strategy_candidate",
                "repainting_risk": "known",
                "backtest_capable": True,
            },
            "strategy_candidate",
        ),
        ({"status": "live_candidate", "live_capable": False}, "live_candidate"),
        (
            {
                "status": "live_candidate",
                "closed_bar_only": False,
                "confirmed_only": False,
                "live_capable": True,
            },
            "live_candidate",
        ),
        (
            {
                "status": "live_candidate",
                "live_capable": True,
                "alert_capable": True,
            },
            "live_candidate",
        ),
        (
            {
                "status": "alert_capable",
                "live_capable": False,
                "alert_capable": True,
            },
            "alert_capable",
        ),
        (
            {
                "status": "alert_capable",
                "closed_bar_only": False,
                "confirmed_only": False,
                "live_capable": True,
                "alert_capable": True,
            },
            "alert_capable",
        ),
        (
            {
                "status": "alert_capable",
                "repainting_risk": "known",
                "live_capable": True,
                "alert_capable": True,
            },
            "alert_capable",
        ),
        ({"status": "retired"}, "retired"),
        ({"status": "retired", "web_capable": False, "backtest_capable": True}, "retired"),
        ({"status": "retired", "web_capable": False, "live_capable": True}, "retired"),
        ({"status": "retired", "web_capable": False, "alert_capable": True}, "retired"),
    ],
)
def test_lifecycle_status_rejects_invalid_capability_matrix(
    overrides: dict[str, object],
    message: str,
) -> None:
    from guiyi_quant.indicators import build_indicator_definition

    with pytest.raises(ValueError, match=message):
        build_indicator_definition(**_base_kwargs(**overrides))


def test_unknown_indicator_and_policy_fail_closed() -> None:
    from guiyi_quant.indicators import get_indicator, require_formal_policy

    with pytest.raises(KeyError, match="unknown indicator_code"):
        get_indicator("not_a_real_indicator")
    with pytest.raises(KeyError, match="unknown formal_policy_id"):
        require_formal_policy("not_a_real_policy")


def test_formal_policy_enforces_allowed_and_blocked_consumers() -> None:
    from guiyi_quant.indicators import (
        FORMAL_BACKTEST_CONSUMER,
        FROZEN_LEGACY_BACKTEST_CONSUMER,
        require_formal_policy,
    )

    assert (
        require_formal_policy("ema_sma_window_v1", consumer=FORMAL_BACKTEST_CONSUMER).policy_id
        == "ema_sma_window_v1"
    )
    assert (
        require_formal_policy("huotian_dayou_strict_v1", consumer=FORMAL_BACKTEST_CONSUMER).policy_id
        == "huotian_dayou_strict_v1"
    )
    assert (
        require_formal_policy(
            "ema_first_value_legacy_v1",
            consumer=FROZEN_LEGACY_BACKTEST_CONSUMER,
        ).policy_id
        == "ema_first_value_legacy_v1"
    )

    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_BLOCKED"):
        require_formal_policy("web_macd_legacy_v1", consumer=FORMAL_BACKTEST_CONSUMER)
    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_NOT_ALLOWED"):
        require_formal_policy("ema_first_value_legacy_v1", consumer=FORMAL_BACKTEST_CONSUMER)
    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_BLOCKED"):
        require_formal_policy("huotian_dayou_original_v0", consumer="Backtest")


def test_ema_registry_is_validated_with_formal_policy() -> None:
    from guiyi_quant.indicators import definition_to_metadata, get_indicator, require_formal_policy

    for code in ("ema10", "ema21", "ema60"):
        definition = get_indicator(code)
        assert definition.status == "validated"
        assert definition.formal_policy_id == "ema_sma_window_v1"
        assert definition.seed_policy == "sma_window"
        assert definition.confirmed_only is True
        assert definition.alert_capable is False
        metadata = definition_to_metadata(definition)
        assert metadata["formal_policy_id"] == "ema_sma_window_v1"
        assert metadata["indicator_code"] == code

    policy = require_formal_policy("ema_sma_window_v1")
    assert policy.seed_policy == "sma_window"
    assert policy.frozen_legacy is False


def test_macd_and_atr_are_compatibility_validated_not_validated() -> None:
    from guiyi_quant.indicators import get_indicator, indicator_registry

    assert "macd" in indicator_registry
    assert "atr" in indicator_registry
    macd = get_indicator("macd")
    atr = get_indicator("atr")
    assert macd.status == "compatibility_validated"
    assert atr.status == "compatibility_validated"
    assert macd.status != "validated"
    assert atr.status != "validated"
    assert macd.formal_policy_id == "web_macd_legacy_v1"
    assert atr.formal_policy_id == "web_atr_wilder_sma_seed_v1"
    assert macd.backtest_capable is False
    assert macd.live_capable is False
    assert macd.alert_capable is False
    assert atr.live_capable is False
    assert atr.alert_capable is False


def test_subing_signal_macd_policy_is_scoped_and_math_equivalent() -> None:
    """Catches widening SuBing MACD approval or drifting from Factor math."""
    from guiyi_quant.indicators import (
        FORMAL_BACKTEST_CONSUMER,
        get_formal_policy,
        require_formal_policy,
    )

    observation = get_formal_policy("web_macd_legacy_v1")
    signal = require_formal_policy(
        "subing_macd_sma_window_scale2_v1",
        consumer="subing_signal",
    )

    assert signal.policy_id == "subing_macd_sma_window_scale2_v1"
    assert signal.indicator_family == "MACD"
    assert (
        (
            signal.seed_policy,
            signal.histogram_scale,
            signal.lookback,
            signal.confirmed_only,
        )
        == (
            observation.seed_policy,
            observation.histogram_scale,
            observation.lookback,
            observation.confirmed_only,
        )
        == ("sma_window", 2, "fast12_slow26_signal9", True)
    )
    assert signal.allowed_consumers == ("subing_signal",)
    assert signal.blocked_consumers == (
        FORMAL_BACKTEST_CONSUMER,
        "alert",
        "notification",
        "generic_live",
    )
    assert signal.frozen_legacy is False

    for consumer in signal.blocked_consumers:
        with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_BLOCKED"):
            require_formal_policy(signal.policy_id, consumer=consumer)
    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_NOT_ALLOWED"):
        require_formal_policy(signal.policy_id, consumer="Market_readonly_display")


def test_htdy_original_is_alert_capable_but_not_live_or_backtest_capable() -> None:
    from guiyi_quant.indicators import (
        HTDY_ALERT_OBSERVATION_CONSUMER,
        get_indicator,
        require_formal_policy,
        resolve_indicator_code,
    )

    original = get_indicator("huotian_dayou_original_v0")
    aliased = get_indicator("huo_tian_da_you")
    assert resolve_indicator_code("huo_tian_da_you") == "huotian_dayou_original_v0"
    assert aliased.indicator_code == "huotian_dayou_original_v0"
    assert original is aliased
    assert original.status == "observation_only"
    assert original.web_capable is True
    assert original.backtest_capable is False
    assert original.live_capable is False
    assert original.alert_capable is True
    assert original.repainting_risk == "known"
    policy = require_formal_policy(
        original.formal_policy_id,
        consumer=HTDY_ALERT_OBSERVATION_CONSUMER,
    )
    assert policy.policy_id == "huotian_dayou_original_v0"
    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_BLOCKED"):
        require_formal_policy(original.formal_policy_id, consumer="alert")


def test_htdy_strict_is_strategy_candidate_backtest_only() -> None:
    from guiyi_quant.indicators import get_indicator

    strict = get_indicator("huotian_dayou_strict_v1")
    original = get_indicator("huotian_dayou_original_v0")
    assert strict.indicator_code != original.indicator_code
    assert strict.indicator_version != original.indicator_version
    assert strict.status == "strategy_candidate"
    assert strict.backtest_capable is True
    assert strict.live_capable is False
    assert strict.alert_capable is False
    assert strict.web_capable is False
    assert "因果" in strict.display_name


def test_jm_v1b_frozen_policy_is_fail_closed_lookup() -> None:
    from guiyi_quant.indicators import require_formal_policy

    policy = require_formal_policy("jm_v1b_report14_frozen_v1")
    assert policy.frozen_legacy is True
    assert policy.seed_policy == "first_value"
    assert policy.smoothing_policy == "ema_first_tr"


def test_kernel_output_hashes_unchanged_for_ema_macd_atr() -> None:
    from guiyi_quant.indicators import atr_series, ema_series, macd_series

    closes = [float(100 + index) for index in range(40)]
    highs = [value + 1.0 for value in closes]
    lows = [value - 1.0 for value in closes]

    ema = ema_series(closes, 21)
    macd = macd_series(closes, 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2)
    atr = atr_series(highs, lows, closes, 14, smoothing_policy="wilder_sma_seed")

    assert ema.indicator_version == "v1"
    assert ema.points[20].value == 110.0
    assert macd.indicator_version == "v1-draft"
    assert atr.indicator_version == "v1-draft"

    ema_again = ema_series(closes, 21)
    macd_again = macd_series(closes, 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2)
    atr_again = atr_series(highs, lows, closes, 14, smoothing_policy="wilder_sma_seed")
    assert ema.parameters_hash == ema_again.parameters_hash
    assert macd.parameters_hash == macd_again.parameters_hash
    assert atr.parameters_hash == atr_again.parameters_hash
    assert [point.value for point in ema.points] == [point.value for point in ema_again.points]
    assert [point.value for point in macd.histogram.points] == [point.value for point in macd_again.histogram.points]
    assert [point.value for point in atr.points] == [point.value for point in atr_again.points]
