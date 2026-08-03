from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd
from sqlalchemy.orm import Session

from app.backtest.contract_resolver import CommissionRule, resolve_jm_contract
from app.backtest.service import BacktestService
from app.core.env import PROJECT_ROOT
from app.models.data_center import MarketDataFile
from app.schemas.backtest import (
    BacktestDataRole,
    BacktestTaskConfig,
    FormalBacktestTaskRequest,
)
from app.services.profile_lineage import INTRADAY_RESEARCH_PROFILE, ProfileLineageResolver


JM_V1B_STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy."
    "JmV1bDailyDirectionFastEntryStrategy"
)
JM_V1B_STRATEGY_CODE = "jm_v1b_daily_direction_fast_entry"
JM_V1B_STRATEGY_VERSION = "v1b.0"
JM_V1B_SYMBOL = "jm.MAIN"
JM_V1B_EXCHANGE = "DCE"
JM_V1B_DATA_SOURCE = "rqdata"
JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.vnpy_strategy."
    "SuBingJmDailyEma21MacdVolumeStrategy"
)
JM_DAILY_SCORE2OF4_STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.su_bing_jm_daily_score2of4.vnpy_strategy."
    "SuBingJmDailyScore2Of4Strategy"
)
JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.su_bing_jm_daily_trend_cross_score2.vnpy_strategy."
    "SuBingJmDailyTrendCrossScore2Strategy"
)
JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE = "su_bing_jm_daily_ema21_macd_volume"
JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION = "v0.2.0-daily"
JM_DAILY_SCORE2OF4_STRATEGY_VERSION = "v0.3.0-daily-score2of4"
JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_VERSION = "v0.3.1-daily-trend-cross-score2"
JM_DAILY_EMA21_MACD_VOLUME_TASK_TYPE = "v1b_jm_daily_ema21_macd_volume"
JM_DAILY_SCORE2OF4_TASK_TYPE = "v1b_jm_daily_score2of4"
JM_DAILY_TREND_CROSS_SCORE2_TASK_TYPE = "v1b_jm_daily_trend_cross_score2"
JM_DAILY_EMA21_MACD_VOLUME_SPEC_START = datetime(2023, 6, 28, tzinfo=UTC)
JM_DAILY_EMA21_MACD_VOLUME_SPEC_END = datetime(2026, 6, 28, tzinfo=UTC)
JM_DAILY_SCORE2OF4_SPEC_START = datetime(2023, 1, 3, tzinfo=UTC)
JM_DAILY_SCORE2OF4_SPEC_END = datetime(2025, 12, 31, 15, 0, tzinfo=UTC)
JM_DAILY_TREND_CROSS_SCORE2_SPEC_START = datetime(2023, 1, 3, tzinfo=UTC)
JM_DAILY_TREND_CROSS_SCORE2_SPEC_END = datetime(2025, 12, 31, 15, 0, tzinfo=UTC)
JM_V1B_FORMAL_SPEC_START = datetime(2023, 6, 28, tzinfo=UTC)
JM_V1B_FORMAL_SPEC_END = datetime(2026, 6, 28, tzinfo=UTC)

SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.su_bing_jm_v1b_short_hold.vnpy_strategy."
    "SuBingJmV1bShortHoldStrategy"
)
SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE = "su_bing_jm_v1b_short_hold"
SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_VERSION = "v0.1.1-spec"
SU_BING_JM_V1B_WINDOW_START = datetime(2023, 6, 28)
SU_BING_JM_V1B_WINDOW_END = datetime(2026, 6, 28)


@dataclass(frozen=True)
class JmV1bTaskSpec:
    entry_interval: Literal["15m", "5m"]
    config: BacktestTaskConfig
    entry_file: MarketDataFile
    daily_file: MarketDataFile


@dataclass(frozen=True)
class JmDailyEma21MacdVolumeTaskSpec:
    config: BacktestTaskConfig
    daily_file: MarketDataFile


@dataclass(frozen=True)
class JmCanonicalFormalTaskSpec:
    request: FormalBacktestTaskRequest
    server_context: dict[str, object]


def build_jm_v1b_task_config(session: Session, entry_interval: Literal["15m", "5m"]) -> JmV1bTaskSpec:
    if entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")

    entry_file = _profile_bound_formal_file(session, entry_interval)
    daily_file = _profile_bound_formal_file(session, "1d")
    start = max(entry_file.start_time, daily_file.start_time)
    end = min(entry_file.end_time, daily_file.end_time)
    if start >= end:
        raise ValueError("JM V1-B formal 1d and entry data ranges do not overlap")

    config = BacktestTaskConfig(
        task_type=f"v1b_jm_{entry_interval}_entry",
        symbol=JM_V1B_SYMBOL,
        exchange=JM_V1B_EXCHANGE,
        interval=entry_interval,
        start=start,
        end=end,
        strategy_class_path=JM_V1B_STRATEGY_CLASS_PATH,
        strategy_code=JM_V1B_STRATEGY_CODE,
        strategy_version=JM_V1B_STRATEGY_VERSION,
        strategy_parameters=_strategy_parameters(entry_interval),
        rate=0.0001,
        slippage=1.0,
        size=60,
        pricetick=0.5,
        capital=100000.0,
        execution_timing="next_bar_open",
        data_source="local_parquet",
        data_role=BacktestDataRole.PRIMARY,
        data_version=_merged_data_version(entry_file, daily_file),
        research_only=False,
        quality_status="passed",
        bar_data_path=entry_file.file_path,
        auxiliary_bar_data_paths={"1d": daily_file.file_path},
        request_payload={
            "fixed_task": f"JM V1-B {entry_interval} entry",
            "data_provider": JM_V1B_DATA_SOURCE,
            "data_files": {
                entry_interval: _file_summary(entry_file),
                "1d": _file_summary(daily_file),
            },
        },
    )
    return JmV1bTaskSpec(entry_interval=entry_interval, config=config, entry_file=entry_file, daily_file=daily_file)


def build_jm_daily_ema21_macd_volume_task_config(session: Session) -> JmDailyEma21MacdVolumeTaskSpec:
    daily_file = _profile_bound_formal_file(session, "1d")
    start = max(_aware_utc(daily_file.start_time), JM_DAILY_EMA21_MACD_VOLUME_SPEC_START)
    end = min(_aware_utc(daily_file.end_time), JM_DAILY_EMA21_MACD_VOLUME_SPEC_END)
    if start >= end:
        raise ValueError("JM daily EMA21 MACD volume formal 1d data range does not overlap the strategy spec window")

    trade_params = _daily_strategy_trade_params(session, start)
    strategy_parameters = _daily_ema21_macd_volume_strategy_parameters(trade_params)
    config = BacktestTaskConfig(
        task_type=JM_DAILY_EMA21_MACD_VOLUME_TASK_TYPE,
        symbol=JM_V1B_SYMBOL,
        exchange=JM_V1B_EXCHANGE,
        interval="1d",
        start=start,
        end=end,
        strategy_class_path=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CLASS_PATH,
        strategy_code=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        strategy_version=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION,
        strategy_parameters=strategy_parameters,
        rate=0.0001,
        slippage=1.0,
        size=int(trade_params["contract_multiplier"]),
        pricetick=float(trade_params["price_tick"]),
        capital=100000.0,
        execution_timing="next_bar_open",
        data_source="local_parquet",
        data_role=BacktestDataRole.PRIMARY,
        data_version=(daily_file.data_version or f"jm_daily_{start:%Y%m%d}_{end:%Y%m%d}")[:64],
        research_only=False,
        quality_status="passed",
        bar_data_path=daily_file.file_path,
        auxiliary_bar_data_paths={},
        request_payload={
            "fixed_task": "JM V1-B daily EMA21 MACD volume",
            "data_provider": JM_V1B_DATA_SOURCE,
            "data_files": {"1d": _file_summary(daily_file)},
            "strategy_review_context": _daily_strategy_review_context(),
        },
    )
    return JmDailyEma21MacdVolumeTaskSpec(config=config, daily_file=daily_file)


def build_jm_daily_score2of4_task_config(session: Session) -> JmDailyEma21MacdVolumeTaskSpec:
    daily_file = _profile_bound_formal_file(session, "1d")
    start = max(_aware_utc(daily_file.start_time), JM_DAILY_SCORE2OF4_SPEC_START)
    end = min(_aware_utc(daily_file.end_time), JM_DAILY_SCORE2OF4_SPEC_END)
    if start >= end:
        raise ValueError("JM daily score2of4 formal 1d data range does not overlap the strategy spec window")

    trade_params = _daily_strategy_trade_params(session, start)
    strategy_parameters = _daily_score2of4_strategy_parameters(trade_params)
    config = BacktestTaskConfig(
        task_type=JM_DAILY_SCORE2OF4_TASK_TYPE,
        symbol=JM_V1B_SYMBOL,
        exchange=JM_V1B_EXCHANGE,
        interval="1d",
        start=start,
        end=end,
        strategy_class_path=JM_DAILY_SCORE2OF4_STRATEGY_CLASS_PATH,
        strategy_code=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        strategy_version=JM_DAILY_SCORE2OF4_STRATEGY_VERSION,
        strategy_parameters=strategy_parameters,
        rate=0.0001,
        slippage=1.0,
        size=int(trade_params["contract_multiplier"]),
        pricetick=float(trade_params["price_tick"]),
        capital=100000.0,
        execution_timing="next_bar_open",
        data_source="local_parquet",
        data_role=BacktestDataRole.PRIMARY,
        data_version=(daily_file.data_version or f"jm_daily_score2of4_{start:%Y%m%d}_{end:%Y%m%d}")[:64],
        research_only=False,
        quality_status="passed",
        bar_data_path=daily_file.file_path,
        auxiliary_bar_data_paths={},
        request_payload={
            "fixed_task": "JM V1-B daily score2of4",
            "data_provider": JM_V1B_DATA_SOURCE,
            "data_files": {"1d": _file_summary(daily_file)},
            "strategy_review_context": _daily_score2of4_review_context(),
        },
    )
    return JmDailyEma21MacdVolumeTaskSpec(config=config, daily_file=daily_file)


def build_jm_daily_trend_cross_score2_task_config(session: Session) -> JmDailyEma21MacdVolumeTaskSpec:
    daily_file = _profile_bound_formal_file(session, "1d")
    start = max(_aware_utc(daily_file.start_time), JM_DAILY_TREND_CROSS_SCORE2_SPEC_START)
    end = min(_aware_utc(daily_file.end_time), JM_DAILY_TREND_CROSS_SCORE2_SPEC_END)
    if start >= end:
        raise ValueError("JM daily trend cross score2 formal 1d data range does not overlap the strategy spec window")

    trade_params = _daily_strategy_trade_params(session, start)
    strategy_parameters = _daily_trend_cross_score2_strategy_parameters(trade_params)
    config = BacktestTaskConfig(
        task_type=JM_DAILY_TREND_CROSS_SCORE2_TASK_TYPE,
        symbol=JM_V1B_SYMBOL,
        exchange=JM_V1B_EXCHANGE,
        interval="1d",
        start=start,
        end=end,
        strategy_class_path=JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_CLASS_PATH,
        strategy_code=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        strategy_version=JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_VERSION,
        strategy_parameters=strategy_parameters,
        rate=0.0001,
        slippage=1.0,
        size=int(trade_params["contract_multiplier"]),
        pricetick=float(trade_params["price_tick"]),
        capital=100000.0,
        execution_timing="next_bar_open",
        data_source="local_parquet",
        data_role=BacktestDataRole.PRIMARY,
        data_version=(daily_file.data_version or f"jm_daily_trend_cross_score2_{start:%Y%m%d}_{end:%Y%m%d}")[:64],
        research_only=False,
        quality_status="passed",
        bar_data_path=daily_file.file_path,
        auxiliary_bar_data_paths={},
        request_payload={
            "fixed_task": "JM V1-B daily trend cross score2",
            "data_provider": JM_V1B_DATA_SOURCE,
            "data_files": {"1d": _file_summary(daily_file)},
            "strategy_review_context": _daily_trend_cross_score2_review_context(),
        },
    )
    return JmDailyEma21MacdVolumeTaskSpec(config=config, daily_file=daily_file)


def build_su_bing_jm_v1b_short_hold_task_config(
    session: Session,
    entry_interval: Literal["15m", "5m"],
    *,
    output_root: Path | None = None,
) -> JmV1bTaskSpec:
    if entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")

    entry_file = _profile_bound_formal_file(session, entry_interval)
    daily_file = _profile_bound_formal_file(session, "1d")
    start = max(_naive(entry_file.start_time), _naive(daily_file.start_time), SU_BING_JM_V1B_WINDOW_START)
    end = min(_naive(entry_file.end_time), _naive(daily_file.end_time), SU_BING_JM_V1B_WINDOW_END)
    if start >= end:
        raise ValueError("Su Bing JM V1-B formal 1d and entry data ranges do not overlap")

    enriched_entry_path = _enriched_su_bing_entry_file(
        session,
        entry_file,
        entry_interval=entry_interval,
        start=start,
        end=end,
        output_root=output_root,
    )
    config = BacktestTaskConfig(
        task_type=f"su_bing_jm_v1b_{entry_interval}",
        symbol=JM_V1B_SYMBOL,
        exchange=JM_V1B_EXCHANGE,
        interval=entry_interval,
        start=start,
        end=end,
        strategy_class_path=SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CLASS_PATH,
        strategy_code=SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE,
        strategy_version=SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_VERSION,
        strategy_parameters=_su_bing_strategy_parameters(entry_interval),
        rate=0.0001,
        slippage=1.0,
        size=60,
        pricetick=0.5,
        capital=1_000_000.0,
        execution_timing="next_bar_open",
        data_source="local_parquet",
        data_role=BacktestDataRole.PRIMARY,
        data_version=_merged_data_version(entry_file, daily_file),
        research_only=True,
        quality_status="passed",
        bar_data_path=str(enriched_entry_path),
        auxiliary_bar_data_paths={"1d": daily_file.file_path},
        request_payload={
            "fixed_task": f"Su Bing JM V1-B short hold {entry_interval} entry",
            "data_provider": JM_V1B_DATA_SOURCE,
            "data_window": {"start": start.isoformat(), "end": end.isoformat()},
            "data_files": {
                entry_interval: _file_summary(entry_file),
                "1d": _file_summary(daily_file),
            },
            "enriched_entry_file": str(enriched_entry_path),
        },
    )
    return JmV1bTaskSpec(entry_interval=entry_interval, config=config, entry_file=entry_file, daily_file=daily_file)


def available_jm_v1b_entry_intervals(session: Session) -> dict[str, bool]:
    return {interval: _maybe_profile_bound_formal_file(session, interval) is not None for interval in ("15m", "5m", "1d")}


def build_jm_v1b_formal_request(
    entry_interval: Literal["15m", "5m"],
) -> JmCanonicalFormalTaskSpec:
    if entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")
    fixed_task = f"JM V1-B {entry_interval} entry"
    return JmCanonicalFormalTaskSpec(
        request=FormalBacktestTaskRequest(
            task_type=f"v1b_jm_{entry_interval}_entry",
            dataset_kind="continuous",
            instrument_symbol="jm",
            contract_or_series=JM_V1B_SYMBOL,
            exchange=JM_V1B_EXCHANGE,
            interval=entry_interval,
            auxiliary_periods=["1d"],
            start=JM_V1B_FORMAL_SPEC_START,
            end=JM_V1B_FORMAL_SPEC_END,
            strategy_class_path=JM_V1B_STRATEGY_CLASS_PATH,
            strategy_code=JM_V1B_STRATEGY_CODE,
            strategy_version=JM_V1B_STRATEGY_VERSION,
            strategy_parameters=_strategy_parameters(entry_interval),
            rate=0.0001,
            slippage=1.0,
            size=60,
            pricetick=0.5,
            capital=100000.0,
            execution_timing="next_bar_open",
        ),
        server_context={
            "fixed_task": fixed_task,
            "data_provider": JM_V1B_DATA_SOURCE,
        },
    )


def build_jm_daily_ema21_macd_volume_formal_request(
    session: Session,
) -> JmCanonicalFormalTaskSpec:
    return _build_jm_daily_formal_request(
        session,
        task_type=JM_DAILY_EMA21_MACD_VOLUME_TASK_TYPE,
        fixed_task="JM V1-B daily EMA21 MACD volume",
        strategy_class_path=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CLASS_PATH,
        strategy_version=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION,
        start=JM_DAILY_EMA21_MACD_VOLUME_SPEC_START,
        end=JM_DAILY_EMA21_MACD_VOLUME_SPEC_END,
        strategy_parameter_builder=_daily_ema21_macd_volume_strategy_parameters,
        strategy_review_context=_daily_strategy_review_context(),
    )


def build_jm_daily_score2of4_formal_request(
    session: Session,
) -> JmCanonicalFormalTaskSpec:
    return _build_jm_daily_formal_request(
        session,
        task_type=JM_DAILY_SCORE2OF4_TASK_TYPE,
        fixed_task="JM V1-B daily score2of4",
        strategy_class_path=JM_DAILY_SCORE2OF4_STRATEGY_CLASS_PATH,
        strategy_version=JM_DAILY_SCORE2OF4_STRATEGY_VERSION,
        start=JM_DAILY_SCORE2OF4_SPEC_START,
        end=JM_DAILY_SCORE2OF4_SPEC_END,
        strategy_parameter_builder=_daily_score2of4_strategy_parameters,
        strategy_review_context=_daily_score2of4_review_context(),
    )


def build_jm_daily_trend_cross_score2_formal_request(
    session: Session,
) -> JmCanonicalFormalTaskSpec:
    return _build_jm_daily_formal_request(
        session,
        task_type=JM_DAILY_TREND_CROSS_SCORE2_TASK_TYPE,
        fixed_task="JM V1-B daily trend cross score2",
        strategy_class_path=JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_CLASS_PATH,
        strategy_version=JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_VERSION,
        start=JM_DAILY_TREND_CROSS_SCORE2_SPEC_START,
        end=JM_DAILY_TREND_CROSS_SCORE2_SPEC_END,
        strategy_parameter_builder=_daily_trend_cross_score2_strategy_parameters,
        strategy_review_context=_daily_trend_cross_score2_review_context(),
    )


def _build_jm_daily_formal_request(
    session: Session,
    *,
    task_type: str,
    fixed_task: str,
    strategy_class_path: str,
    strategy_version: str,
    start: datetime,
    end: datetime,
    strategy_parameter_builder: Callable[
        [dict[str, float | int]], dict[str, object]
    ],
    strategy_review_context: dict[str, object],
) -> JmCanonicalFormalTaskSpec:
    trade_params = _daily_strategy_trade_params(session, start)
    strategy_parameters = strategy_parameter_builder(trade_params)
    return JmCanonicalFormalTaskSpec(
        request=FormalBacktestTaskRequest(
            task_type=task_type,
            dataset_kind="continuous",
            instrument_symbol="jm",
            contract_or_series=JM_V1B_SYMBOL,
            exchange=JM_V1B_EXCHANGE,
            interval="1d",
            start=start,
            end=end,
            strategy_class_path=strategy_class_path,
            strategy_code=JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
            strategy_version=strategy_version,
            strategy_parameters=strategy_parameters,
            rate=0.0001,
            slippage=1.0,
            size=int(trade_params["contract_multiplier"]),
            pricetick=float(trade_params["price_tick"]),
            capital=100000.0,
            execution_timing="next_bar_open",
        ),
        server_context={
            "fixed_task": fixed_task,
            "data_provider": JM_V1B_DATA_SOURCE,
            "strategy_review_context": strategy_review_context,
        },
    )


def _strategy_parameters(entry_interval: str) -> dict[str, object]:
    return {
        "entry_interval": entry_interval,
        "max_hold_bars_min": 5,
        "max_hold_bars_max": 8,
        "stop_loss_atr_multiple": 1.5,
        "submit_vnpy_orders": True,
        "fill_policy": "signal_on_close_fill_next_bar_open",
        "daily_effective_policy": "confirmed_daily_bar_effective_next_trading_day",
    }


def _jm_daily_indicator_policy_metadata() -> dict[str, object]:
    """C4-04 metadata only; filtered out by strategy validate_params field allowlist."""

    return {
        "indicator_versions": ["ema21", "macd"],
        "formal_policy_ids": [
            "ema_first_value_legacy_v1",
            "strategy_macd_first_value_scale1_v1",
        ],
        "confirmed_only": True,
        "research_status": "formal_candidate",
    }


def _daily_ema21_macd_volume_strategy_parameters(trade_params: dict[str, float | int]) -> dict[str, object]:
    return {
        **_jm_daily_indicator_policy_metadata(),
        "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        "strategy_version": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION,
        "interval": "1d",
        "product": "JM",
        "ema_period": 21,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "jm_macd_zero_band": 25,
        "volume_confirm_enabled": True,
        "volume_rule": "current_volume_gt_previous_volume",
        "maximum_position": 1,
        "allow_long": True,
        "allow_short": True,
        "slippage_ticks": 1,
        "stop_loss_enabled": False,
        "take_profit_enabled": False,
        "time_exit_enabled": False,
        "submit_vnpy_orders": False,
        "live_trading_enabled": False,
        "auto_order_enabled": False,
        "price_tick": trade_params["price_tick"],
        "contract_multiplier": trade_params["contract_multiplier"],
        "commission_rate": trade_params.get("commission_rate"),
        "commission_per_contract": trade_params.get("commission_per_contract"),
        "margin_rate": trade_params["margin_rate"],
        "fill_policy": "daily_close_signal_next_daily_open_fill",
        "reverse_policy": "no_same_daily_bar_reverse",
    }


def _daily_score2of4_strategy_parameters(trade_params: dict[str, float | int]) -> dict[str, object]:
    return {
        **_jm_daily_indicator_policy_metadata(),
        "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        "strategy_version": JM_DAILY_SCORE2OF4_STRATEGY_VERSION,
        "interval": "1d",
        "product": "JM",
        "ema_period": 21,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "macd_zero_threshold": 25,
        "min_entry_score": 2,
        "require_directional_anchor": True,
        "ambiguous_tie_action": "reject",
        "emit_skill_tags": True,
        "maximum_position": 1,
        "allow_long": True,
        "allow_short": True,
        "slippage_ticks": 1,
        "stop_loss_enabled": False,
        "take_profit_enabled": False,
        "time_exit_enabled": False,
        "submit_vnpy_orders": False,
        "live_trading_enabled": False,
        "auto_order_enabled": False,
        "price_tick": trade_params["price_tick"],
        "contract_multiplier": trade_params["contract_multiplier"],
        "commission_rate": trade_params.get("commission_rate"),
        "commission_per_contract": trade_params.get("commission_per_contract"),
        "margin_rate": trade_params["margin_rate"],
        "fill_policy": "daily_close_signal_next_daily_open_fill",
        "reverse_policy": "no_same_daily_bar_reverse",
    }


def _daily_trend_cross_score2_strategy_parameters(trade_params: dict[str, float | int]) -> dict[str, object]:
    return {
        **_jm_daily_indicator_policy_metadata(),
        "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        "strategy_version": JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_VERSION,
        "interval": "1d",
        "product": "JM",
        "ema_period": 21,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "macd_zero_threshold": 25,
        "min_entry_score": 2,
        "require_trend_alignment": True,
        "require_macd_cross": True,
        "volume_rule": "current_volume_gt_previous_volume",
        "emit_skill_tags": True,
        "maximum_position": 1,
        "allow_long": True,
        "allow_short": True,
        "slippage_ticks": 1,
        "stop_loss_enabled": False,
        "take_profit_enabled": False,
        "time_exit_enabled": False,
        "submit_vnpy_orders": False,
        "live_trading_enabled": False,
        "auto_order_enabled": False,
        "price_tick": trade_params["price_tick"],
        "contract_multiplier": trade_params["contract_multiplier"],
        "commission_rate": trade_params.get("commission_rate"),
        "commission_per_contract": trade_params.get("commission_per_contract"),
        "margin_rate": trade_params["margin_rate"],
        "fill_policy": "daily_close_signal_next_daily_open_fill",
        "reverse_policy": "no_same_daily_bar_reverse",
    }


def _daily_strategy_trade_params(session: Session, start: datetime) -> dict[str, float | int]:
    try:
        resolved = resolve_jm_contract(session, moment=start)
    except Exception as exc:
        raise ValueError(f"JM daily EMA21 MACD volume trading parameters cannot be resolved: {exc}") from exc

    params: dict[str, float | int] = {
        "price_tick": float(resolved.price_tick),
        "contract_multiplier": resolved.contract_multiplier,
        "margin_rate": float(resolved.margin_ratio),
    }
    if resolved.commission_rule.fee_type == "rate":
        params["commission_rate"] = float(resolved.commission_rule.open_fee)
    else:
        params["commission_per_contract"] = float(resolved.commission_rule.open_fee)
    return params


def _daily_strategy_review_context() -> dict[str, object]:
    return {
        "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        "strategy_version": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION,
        "spec_path": "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md",
        "review_path": "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC_REVIEW.md",
        "data_constraints": {
            "provider": JM_V1B_DATA_SOURCE,
            "symbol": "jm",
            "contract": JM_V1B_SYMBOL,
            "interval": "1d",
            "data_role": "primary",
            "quality_status": "passed",
        },
        "forbidden_sources": ["legacy_reference", "validation", "tqsdk_formal_backtest_data"],
        "forbidden_execution": ["live_trading", "auto_order", "parameter_optimization"],
        "output_requirements": ["report_id", "trades", "orders_if_any", "equity_curve", "drawdown_curve"],
        "review_notes": [
            "daily close signal only",
            "next daily open fill",
            "no 15m or 5m data",
            "backtest result is not live trading evidence",
        ],
    }


def _daily_score2of4_review_context() -> dict[str, object]:
    return {
        "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        "strategy_version": JM_DAILY_SCORE2OF4_STRATEGY_VERSION,
        "spec_path": "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_SCORE2OF4_DESIGN.md",
        "review_path": "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_SCORE2OF4_BACKTEST_REVIEW.md",
        "metric_scope": "raw_and_trusted_excluding_cross_contract",
        "data_constraints": {
            "provider": JM_V1B_DATA_SOURCE,
            "symbol": "jm",
            "contract": JM_V1B_SYMBOL,
            "interval": "1d",
            "data_role": "primary",
            "quality_status": "passed",
        },
        "forbidden_sources": ["legacy_reference", "validation", "tqsdk_formal_backtest_data"],
        "forbidden_execution": ["live_trading", "auto_order", "parameter_optimization"],
        "output_requirements": [
            "raw_metrics",
            "trusted_excluding_cross_contract_metrics",
            "score_distribution",
            "signal_candidates",
            "rejected_signals",
        ],
        "review_notes": [
            "daily close signal only",
            "next daily open fill",
            "2-of-4 entry score with directional anchor",
            "trusted conclusions exclude cross-contract PnL",
            "backtest result is not live trading evidence",
        ],
    }


def _daily_trend_cross_score2_review_context() -> dict[str, object]:
    return {
        "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
        "strategy_version": JM_DAILY_TREND_CROSS_SCORE2_STRATEGY_VERSION,
        "spec_path": "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_1_TREND_CROSS_SCORE2_DESIGN.md",
        "review_path": (
            "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/"
            "V0_3_1_TREND_CROSS_SCORE2_BACKTEST_REVIEW.md"
        ),
        "metric_scope": "raw_and_trusted_excluding_cross_contract",
        "data_constraints": {
            "provider": JM_V1B_DATA_SOURCE,
            "symbol": "jm",
            "contract": JM_V1B_SYMBOL,
            "interval": "1d",
            "data_role": "primary",
            "quality_status": "passed",
        },
        "forbidden_sources": ["legacy_reference", "validation", "tqsdk_formal_backtest_data"],
        "forbidden_execution": ["live_trading", "auto_order", "parameter_optimization"],
        "output_requirements": [
            "raw_metrics",
            "trusted_excluding_cross_contract_metrics",
            "score_distribution",
            "signal_candidates",
            "rejected_signals",
            "trend_cross_gate_rejections",
        ],
        "review_notes": [
            "daily close signal only",
            "next daily open fill",
            "entry must satisfy trend alignment and matching MACD cross",
            "near-zero MACD and volume expansion remain scoring and review labels",
            "trusted conclusions exclude cross-contract PnL",
            "backtest result is not live trading evidence",
        ],
    }


def _su_bing_strategy_parameters(entry_interval: str) -> dict[str, object]:
    return {
        "entry_interval": entry_interval,
        "submit_vnpy_orders": False,
        "strategy_code": SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE,
        "strategy_version": SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_VERSION,
        "initial_capital": 1_000_000,
        "risk_per_trade_ratio": 0.005,
        "maximum_position": 1,
        "slippage_ticks": 1,
        "fill_policy": "signal_on_close_fill_next_bar_open",
        "daily_effective_policy": "confirmed_daily_bar_effective_next_trading_day",
    }


def _profile_bound_formal_file(session: Session, period: str) -> MarketDataFile:
    lineage, _ = BacktestService(session).resolve_formal_asset(
        instrument_symbol="jm",
        contract_code=JM_V1B_SYMBOL,
        period=period,
        profile_id=INTRADAY_RESEARCH_PROFILE,
    )
    if lineage.market_file is None:
        raise ValueError(f"JM V1-B formal {period} data has no MarketDataFile")
    return lineage.market_file


def _maybe_profile_bound_formal_file(session: Session, period: str) -> MarketDataFile | None:
    lineage = ProfileLineageResolver(session).resolve(
        consumer="backtest",
        symbol="jm",
        contract=JM_V1B_SYMBOL,
        period=period,
        profile_id=INTRADAY_RESEARCH_PROFILE,
        allow_warning_quality=False,
    )
    if lineage.blocked or lineage.quality_policy != "passed_only":
        return None
    row = lineage.market_file
    if row is None or row.provider not in {"rqdata", "local_parquet"}:
        return None
    if row.data_role != "primary" or row.quality_status != "passed":
        return None
    return row


def _enriched_su_bing_entry_file(
    session: Session,
    entry_file: MarketDataFile,
    *,
    entry_interval: str,
    start: datetime,
    end: datetime,
    output_root: Path | None = None,
) -> Path:
    source_path = Path(entry_file.file_path)
    output_path = (
        (output_root or PROJECT_ROOT)
        / "backtests"
        / "results"
        / SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE
        / "enriched"
        / f"{entry_interval}_{entry_file.id}_{start:%Y%m%d}_{end:%Y%m%d}.parquet"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.read_parquet(source_path)
    required = {"datetime", "trading_day", "data_role", "quality_status"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Su Bing JM V1-B entry parquet missing required columns: {', '.join(sorted(missing))}")

    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.tz_localize(None)
    windowed = frame[(frame["datetime"] >= start) & (frame["datetime"] <= end)].copy()
    if windowed.empty:
        raise ValueError(f"Su Bing JM V1-B {entry_interval} data is empty in requested window")
    if set(windowed["data_role"].astype(str)) != {"primary"}:
        raise ValueError("Su Bing JM V1-B only accepts data_role=primary bars")
    if set(windowed["quality_status"].astype(str)) != {"passed"}:
        raise ValueError("Su Bing JM V1-B only accepts quality_status=passed bars")

    resolved_by_day = {
        day: resolve_jm_contract(session, trading_day=day)
        for day in sorted({pd.Timestamp(value).date() for value in windowed["trading_day"]})
    }
    windowed["actual_contract"] = [
        resolved_by_day[pd.Timestamp(value).date()].actual_contract for value in windowed["trading_day"]
    ]
    windowed["price_tick"] = [
        float(resolved_by_day[pd.Timestamp(value).date()].price_tick) for value in windowed["trading_day"]
    ]
    windowed["contract_multiplier"] = [
        resolved_by_day[pd.Timestamp(value).date()].contract_multiplier for value in windowed["trading_day"]
    ]
    windowed["margin_rate"] = [
        float(resolved_by_day[pd.Timestamp(value).date()].margin_ratio) for value in windowed["trading_day"]
    ]
    windowed["commission_rate"] = [
        _commission_rate(resolved_by_day[pd.Timestamp(value).date()].commission_rule) for value in windowed["trading_day"]
    ]
    windowed["commission_per_contract"] = [
        _commission_per_contract(resolved_by_day[pd.Timestamp(value).date()].commission_rule) for value in windowed["trading_day"]
    ]
    windowed["parameter_source"] = [
        resolved_by_day[pd.Timestamp(value).date()].parameter_source for value in windowed["trading_day"]
    ]
    windowed.to_parquet(output_path, index=False)
    return output_path


def _commission_rate(rule: CommissionRule) -> float | None:
    return float(rule.open_fee) if rule.fee_type == "rate" else None


def _commission_per_contract(rule: CommissionRule) -> float | None:
    return float(max(value for value in (rule.open_fee, rule.close_fee, rule.close_today_fee or Decimal("0")) if value is not None)) if rule.fee_type == "fixed" else None


def _merged_data_version(entry_file: MarketDataFile, daily_file: MarketDataFile) -> str:
    entry_version = entry_file.data_version or "unknown"
    daily_version = daily_file.data_version or "unknown"
    if entry_version == daily_version:
        return entry_version[:64]
    start = max(entry_file.start_time, daily_file.start_time)
    end = min(entry_file.end_time, daily_file.end_time)
    return f"v1b_jm_{start:%Y%m%d}_{end:%Y%m%d}"


def _file_summary(row: MarketDataFile) -> dict[str, object]:
    return {
        "file_id": row.id,
        "provider": row.provider,
        "period": row.period,
        "start": _iso(row.start_time),
        "end": _iso(row.end_time),
        "row_count": row.row_count,
        "data_version": row.data_version,
        "data_role": row.data_role,
        "quality_status": row.quality_status,
    }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("JM V1-B market data file is missing start_time or end_time")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _naive(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("market data file start_time/end_time is required")
    return value.replace(tzinfo=None)
