from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

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


@dataclass(frozen=True)
class JmV1bTaskSpec:
    entry_interval: Literal["15m", "5m"]
    config: BacktestTaskConfig
    entry_file: MarketDataFile
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
