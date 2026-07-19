from __future__ import annotations

from types import MappingProxyType

from .models import FormalPolicy


_POLICIES: dict[str, FormalPolicy] = {
    "ema_sma_window_v1": FormalPolicy(
        policy_id="ema_sma_window_v1",
        indicator_family="EMA",
        seed_policy="sma_window",
        smoothing_policy=None,
        histogram_scale=None,
        lookback="period",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("Market", "Web", "Backtest", "live_confirmed"),
        blocked_consumers=("unconfirmed_signal", "alert"),
        notes="Validated EMA10/21/60 kernel policy.",
    ),
    "ema_first_value_legacy_v1": FormalPolicy(
        policy_id="ema_first_value_legacy_v1",
        indicator_family="EMA",
        seed_policy="first_value",
        smoothing_policy=None,
        histogram_scale=None,
        lookback="period",
        confirmed_only=True,
        frozen_legacy=True,
        allowed_consumers=("versioned_legacy_strategies",),
        blocked_consumers=("unversioned_formal_replacement",),
        notes="Compatibility-only first_value EMA for JM V1-B and related strategies.",
    ),
    "web_macd_legacy_v1": FormalPolicy(
        policy_id="web_macd_legacy_v1",
        indicator_family="MACD",
        seed_policy="sma_window",
        smoothing_policy=None,
        histogram_scale=2,
        lookback="fast12_slow26_signal9",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("Market_readonly_display",),
        blocked_consumers=("formal_strategy_signal_until_validated",),
        notes="Web/Market MACD display compatibility policy; not strategy-validated.",
    ),
    "strategy_macd_first_value_scale1_v1": FormalPolicy(
        policy_id="strategy_macd_first_value_scale1_v1",
        indicator_family="MACD",
        seed_policy="first_value",
        smoothing_policy=None,
        histogram_scale=1,
        lookback="fast12_slow26_signal9",
        confirmed_only=True,
        frozen_legacy=True,
        allowed_consumers=("versioned_legacy_strategy_compatibility",),
        blocked_consumers=("Web_scale2", "silent_strategy_replacement"),
        notes="Python strategy-style MACD compatibility policy.",
    ),
    "web_atr_wilder_sma_seed_v1": FormalPolicy(
        policy_id="web_atr_wilder_sma_seed_v1",
        indicator_family="ATR",
        seed_policy=None,
        smoothing_policy="wilder_sma_seed",
        histogram_scale=None,
        lookback="period",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("observation_display",),
        blocked_consumers=("formal_report_or_signal_without_policy",),
        notes="Web ATR display compatibility policy.",
    ),
    "fastapi_atr_wilder_first_tr_v1": FormalPolicy(
        policy_id="fastapi_atr_wilder_first_tr_v1",
        indicator_family="ATR",
        seed_policy=None,
        smoothing_policy="wilder_first_tr",
        histogram_scale=None,
        lookback="period",
        confirmed_only=True,
        frozen_legacy=True,
        allowed_consumers=("legacy_strategy_compatibility",),
        blocked_consumers=("unversioned_formal_replacement",),
        notes="FastAPI su_bing ATR compatibility policy.",
    ),
    "quantcore_atr_ema_first_tr_v1": FormalPolicy(
        policy_id="quantcore_atr_ema_first_tr_v1",
        indicator_family="ATR",
        seed_policy=None,
        smoothing_policy="ema_first_tr",
        histogram_scale=None,
        lookback="period",
        confirmed_only=True,
        frozen_legacy=True,
        allowed_consumers=("versioned_legacy_strategy_compatibility",),
        blocked_consumers=("wilder_policy_substitution",),
        notes="quant-core / JM V1-B ATR compatibility policy.",
    ),
    "huotian_dayou_original_v0": FormalPolicy(
        policy_id="huotian_dayou_original_v0",
        indicator_family="HTDY",
        seed_policy=None,
        smoothing_policy=None,
        histogram_scale=None,
        lookback="period25_with_future_window",
        confirmed_only=False,
        frozen_legacy=False,
        allowed_consumers=("Web_manual_observation",),
        blocked_consumers=("Backtest", "Signal", "live", "alert", "notification"),
        notes="Original XMA observation-only; D4-00 unresolved blocks Tongdaxin-equivalent claim.",
    ),
    "huotian_dayou_strict_v1": FormalPolicy(
        policy_id="huotian_dayou_strict_v1",
        indicator_family="HTDY",
        seed_policy="sma_window",
        smoothing_policy=None,
        histogram_scale=None,
        lookback="channel49_zd2_73_var23_12",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("offline_candidate", "manual_review", "research_only_backtest"),
        blocked_consumers=("live", "alert", "notification", "unapproved_formal_report"),
        notes="Causal rewrite strategy_candidate; not Stage 5 formal report Ready.",
    ),
    "jm_v1b_report14_frozen_v1": FormalPolicy(
        policy_id="jm_v1b_report14_frozen_v1",
        indicator_family="JM_V1B",
        seed_policy="first_value",
        smoothing_policy="ema_first_tr",
        histogram_scale=None,
        lookback="intraday_window220_and_daily_min35",
        confirmed_only=True,
        frozen_legacy=True,
        allowed_consumers=("report_id14", "JM_V1B_scanner", "live_evaluator_shared_helper"),
        blocked_consumers=("silent_v1b_0_replacement", "unversioned_kernel_swap"),
        notes="Frozen report 14 / JM V1-B composite legacy policy; migrate only with new strategy version.",
    ),
}

formal_policy_registry = MappingProxyType(_POLICIES)


def get_formal_policy(policy_id: str) -> FormalPolicy:
    try:
        return formal_policy_registry[policy_id]
    except KeyError as exc:
        raise KeyError(f"unknown formal_policy_id: {policy_id}") from exc


def require_formal_policy(policy_id: str) -> FormalPolicy:
    """Fail-closed formal policy lookup for consumers that must name a policy."""

    return get_formal_policy(policy_id)
