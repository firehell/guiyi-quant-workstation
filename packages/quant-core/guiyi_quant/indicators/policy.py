from __future__ import annotations

from types import MappingProxyType

from .models import FormalPolicy


FORMAL_BACKTEST_CONSUMER = "formal_backtest"
FROZEN_LEGACY_BACKTEST_CONSUMER = "frozen_legacy_backtest"
HTDY_ALERT_OBSERVATION_CONSUMER = "htdy_alert_observation"


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
        allowed_consumers=("Market", "Web", "Backtest", "live_confirmed", FORMAL_BACKTEST_CONSUMER),
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
        allowed_consumers=("versioned_legacy_strategies", FROZEN_LEGACY_BACKTEST_CONSUMER),
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
        allowed_consumers=("Market_readonly_display", "subing_factor_observation"),
        blocked_consumers=("formal_strategy_signal_until_validated", FORMAL_BACKTEST_CONSUMER),
        notes="Web/Market MACD display compatibility policy; not strategy-validated.",
    ),
    "main_force_mirror_observation_v0": FormalPolicy(
        policy_id="main_force_mirror_observation_v0",
        indicator_family="MAIN_FORCE_MIRROR",
        seed_policy=None,
        smoothing_policy=None,
        histogram_scale=None,
        lookback="volume20_flowEMA5_range20_cautionHHV5_BARSLAST10",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("Web_manual_observation",),
        blocked_consumers=(FORMAL_BACKTEST_CONSUMER, "live", "alert", "notification"),
        notes=(
            "Designed causal OHLCV observation only. Six coloured states are a proxy, not measured fund flow; "
            "the caution event mirrors the provided HHV/BARSLAST formula."
        ),
    ),
    "main_force_mirror_futures_observation_v1": FormalPolicy(
        policy_id="main_force_mirror_futures_observation_v1",
        indicator_family="MAIN_FORCE_MIRROR_FUTURES",
        seed_policy=None,
        smoothing_policy=None,
        histogram_scale=None,
        lookback="60m_state21_caution31_physical_contract_segment",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("Web_manual_observation",),
        blocked_consumers=(
            FORMAL_BACKTEST_CONSUMER,
            "live",
            "alert",
            "notification",
            "auto_order",
        ),
        notes=(
            "60m Web-only directional position-pressure observation proxy. "
            "Not measured fund flow, participant identity, an Alert, or a trade signal."
        ),
    ),
    "subing_macd_sma_window_scale2_v1": FormalPolicy(
        policy_id="subing_macd_sma_window_scale2_v1",
        indicator_family="MACD",
        seed_policy="sma_window",
        smoothing_policy=None,
        histogram_scale=2,
        lookback="fast12_slow26_signal9",
        confirmed_only=True,
        frozen_legacy=False,
        allowed_consumers=("subing_signal",),
        blocked_consumers=(
            FORMAL_BACKTEST_CONSUMER,
            "alert",
            "notification",
            "generic_live",
        ),
        notes=(
            "Scoped confirmed MACD policy approved only for SuBing V1 entry-signal "
            "evaluation; generic MACD registry capability remains unchanged."
        ),
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
        allowed_consumers=("versioned_legacy_strategy_compatibility", FROZEN_LEGACY_BACKTEST_CONSUMER),
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
        blocked_consumers=("formal_report_or_signal_without_policy", FORMAL_BACKTEST_CONSUMER),
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
        allowed_consumers=("legacy_strategy_compatibility", FROZEN_LEGACY_BACKTEST_CONSUMER),
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
        allowed_consumers=("versioned_legacy_strategy_compatibility", FROZEN_LEGACY_BACKTEST_CONSUMER),
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
        allowed_consumers=("Web_manual_observation", HTDY_ALERT_OBSERVATION_CONSUMER),
        blocked_consumers=("Backtest", FORMAL_BACKTEST_CONSUMER, "Signal", "live", "alert", "notification"),
        notes=(
            "Original XMA observation-only; scoped current-bar Alert observation is allowed, "
            "while generic alert/live/Signal/notification and formal backtest remain blocked."
        ),
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
        allowed_consumers=(
            "offline_candidate",
            "manual_review",
            "research_only_backtest",
            FORMAL_BACKTEST_CONSUMER,
        ),
        blocked_consumers=("live", "alert", "notification"),
        notes="Causal rewrite strategy_candidate approved for formal historical backtest/report input only.",
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
        allowed_consumers=(
            "report_id14",
            "JM_V1B_scanner",
            "live_evaluator_shared_helper",
            FROZEN_LEGACY_BACKTEST_CONSUMER,
        ),
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


def require_formal_policy(policy_id: str, *, consumer: str | None = None) -> FormalPolicy:
    """Fail-closed formal policy lookup for consumers that must name a policy."""

    policy = get_formal_policy(policy_id)
    if consumer is None:
        return policy
    if consumer in policy.blocked_consumers:
        raise ValueError(
            f"FORMAL_POLICY_CONSUMER_BLOCKED: policy {policy_id} blocks consumer {consumer}"
        )
    if consumer not in policy.allowed_consumers:
        raise ValueError(
            f"FORMAL_POLICY_CONSUMER_NOT_ALLOWED: policy {policy_id} does not allow consumer {consumer}"
        )
    return policy
