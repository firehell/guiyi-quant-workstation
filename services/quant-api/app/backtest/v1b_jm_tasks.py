from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.contract_resolver import CommissionRule, resolve_jm_contract
from app.core.env import PROJECT_ROOT
from app.models.data_center import MarketDataFile
from app.schemas.backtest import BacktestDataRole, BacktestTaskConfig


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
JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE = "su_bing_jm_daily_ema21_macd_volume"
JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION = "v0.2.0-daily"
JM_DAILY_EMA21_MACD_VOLUME_TASK_TYPE = "v1b_jm_daily_ema21_macd_volume"
JM_DAILY_EMA21_MACD_VOLUME_SPEC_START = datetime(2023, 6, 28, tzinfo=UTC)
JM_DAILY_EMA21_MACD_VOLUME_SPEC_END = datetime(2026, 6, 28, tzinfo=UTC)

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


def build_jm_v1b_task_config(session: Session, entry_interval: Literal["15m", "5m"]) -> JmV1bTaskSpec:
    if entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")

    entry_file = _latest_formal_file(session, entry_interval)
    daily_file = _latest_formal_file(session, "1d")
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
    daily_file = _latest_formal_file(session, "1d")
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


def build_su_bing_jm_v1b_short_hold_task_config(
    session: Session,
    entry_interval: Literal["15m", "5m"],
) -> JmV1bTaskSpec:
    if entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")

    entry_file = _latest_formal_file(session, entry_interval)
    daily_file = _latest_formal_file(session, "1d")
    start = max(_naive(entry_file.start_time), _naive(daily_file.start_time), SU_BING_JM_V1B_WINDOW_START)
    end = min(_naive(entry_file.end_time), _naive(daily_file.end_time), SU_BING_JM_V1B_WINDOW_END)
    if start >= end:
        raise ValueError("Su Bing JM V1-B formal 1d and entry data ranges do not overlap")

    enriched_entry_path = _enriched_su_bing_entry_file(session, entry_file, entry_interval=entry_interval, start=start, end=end)
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
        research_only=False,
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
    return {interval: _maybe_latest_formal_file(session, interval) is not None for interval in ("15m", "5m", "1d")}


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


def _daily_ema21_macd_volume_strategy_parameters(trade_params: dict[str, float | int]) -> dict[str, object]:
    return {
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


def _daily_strategy_trade_params(session: Session, start: datetime) -> dict[str, float | int]:
    try:
        resolved = resolve_jm_contract(session, moment=start)
    except Exception as exc:
        raise ValueError(f"JM daily EMA21 MACD volume trading parameters cannot be resolved: {exc}") from exc

    params: dict[str, float | int] = {
        "price_tick": resolved.price_tick,
        "contract_multiplier": resolved.contract_multiplier,
        "margin_rate": resolved.margin_ratio,
    }
    if resolved.commission_rule.fee_type == "rate":
        params["commission_rate"] = resolved.commission_rule.open_fee
    else:
        params["commission_per_contract"] = resolved.commission_rule.open_fee
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


def _latest_formal_file(session: Session, period: str) -> MarketDataFile:
    row = _maybe_latest_formal_file(session, period)
    if row is None:
        raise ValueError(f"JM V1-B formal {period} data file is not registered as rqdata primary passed")
    if not Path(row.file_path).exists():
        raise ValueError(f"JM V1-B formal {period} data file is registered but missing on disk")
    return row


def _maybe_latest_formal_file(session: Session, period: str) -> MarketDataFile | None:
    return session.scalar(
        select(MarketDataFile)
        .where(
            MarketDataFile.provider == JM_V1B_DATA_SOURCE,
            MarketDataFile.data_type == "bars",
            MarketDataFile.instrument_symbol == "jm",
            MarketDataFile.contract_code == JM_V1B_SYMBOL,
            MarketDataFile.period == period,
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
        )
        .order_by(MarketDataFile.end_time.desc(), MarketDataFile.created_at.desc(), MarketDataFile.id.desc())
        .limit(1)
    )


def _enriched_su_bing_entry_file(
    session: Session,
    entry_file: MarketDataFile,
    *,
    entry_interval: str,
    start: datetime,
    end: datetime,
) -> Path:
    source_path = Path(entry_file.file_path)
    output_path = (
        PROJECT_ROOT
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
        resolved_by_day[pd.Timestamp(value).date()].price_tick for value in windowed["trading_day"]
    ]
    windowed["contract_multiplier"] = [
        resolved_by_day[pd.Timestamp(value).date()].contract_multiplier for value in windowed["trading_day"]
    ]
    windowed["margin_rate"] = [
        resolved_by_day[pd.Timestamp(value).date()].margin_ratio for value in windowed["trading_day"]
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
    return rule.open_fee if rule.fee_type == "rate" else None


def _commission_per_contract(rule: CommissionRule) -> float | None:
    return max(value for value in (rule.open_fee, rule.close_fee, rule.close_today_fee or 0.0) if value is not None) if rule.fee_type == "fixed" else None


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
