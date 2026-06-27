from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.vnpy_integration.errors import BacktestConfigurationError
from app.vnpy_integration.execution_policy import DEFAULT_EXECUTION_TIMING, validate_execution_timing
from app.vnpy_integration.settings import VnpyBacktestSettings, require_vnpy
from app.vnpy_integration.strategy_loader import load_strategy_class
from app.vnpy_integration.symbol_mapper import normalize_exchange, to_vt_symbol


@dataclass(frozen=True)
class GuiyiBacktestRequest:
    symbol: str
    exchange: str
    interval: str
    start: datetime
    end: datetime
    rate: float
    slippage: float
    size: int
    pricetick: float
    capital: float
    strategy_class_path: str
    strategy_parameters: dict[str, Any] = field(default_factory=dict)
    bar_data_path: str | Path | None = None
    bars: list[dict[str, Any]] | None = None
    auxiliary_bar_data_paths: dict[str, str | Path] = field(default_factory=dict)
    auxiliary_bars: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    prepared_only: bool = False
    execution_timing: str = DEFAULT_EXECUTION_TIMING


@dataclass(frozen=True)
class PreparedVnpyBacktest:
    settings: VnpyBacktestSettings
    strategy_class: type[Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "vt_symbol": self.settings.vt_symbol,
            "interval": self.settings.interval,
            "start": self.settings.start.isoformat(),
            "end": self.settings.end.isoformat(),
            "rate": self.settings.rate,
            "slippage": self.settings.slippage,
            "size": self.settings.size,
            "pricetick": self.settings.pricetick,
            "capital": self.settings.capital,
            "strategy_class_path": self.settings.strategy_class_path,
            "strategy_parameters": dict(self.settings.strategy_parameters),
            "strategy_class_name": self.strategy_class.__name__,
            "execution_timing": self.settings.execution_timing,
        }


class VnpyBacktestRunner:
    """Adapter boundary for vn.py CTA BacktestingEngine execution."""

    def prepare(self, request: GuiyiBacktestRequest) -> PreparedVnpyBacktest:
        self._validate_request(request)
        require_vnpy()
        strategy_class = load_strategy_class(request.strategy_class_path)
        execution_timing = validate_execution_timing(request.execution_timing)
        runtime_symbol = _to_vnpy_runtime_symbol(request.symbol)
        settings = VnpyBacktestSettings(
            vt_symbol=to_vt_symbol(runtime_symbol, request.exchange),
            interval=request.interval,
            start=request.start,
            end=request.end,
            rate=request.rate,
            slippage=request.slippage,
            size=request.size,
            pricetick=request.pricetick,
            capital=request.capital,
            strategy_class_path=request.strategy_class_path,
            strategy_parameters=dict(request.strategy_parameters),
            execution_timing=execution_timing,
        )
        return PreparedVnpyBacktest(settings=settings, strategy_class=strategy_class)

    def run(self, request: GuiyiBacktestRequest) -> dict[str, Any]:
        prepared = self.prepare(request)
        if request.prepared_only:
            return {
                "status": "prepared",
                "engine": "vnpy_cta_backtesting",
                "executed": False,
                "execution_timing": prepared.settings.execution_timing,
                "message": "vn.py backtest settings prepared; execution skipped by prepared_only=true.",
                "prepared": prepared.to_json(),
            }

        engine_class, bar_class, exchange_enum, interval_enum = _load_vnpy_backtesting_objects()
        bars = _load_request_bars(request, bar_class=bar_class, exchange_enum=exchange_enum, interval_enum=interval_enum)
        auxiliary_bars = _load_auxiliary_bars(request)
        if not bars:
            raise BacktestConfigurationError("vn.py backtest requires at least one standard bar")

        engine = engine_class()
        engine.set_parameters(
            vt_symbol=prepared.settings.vt_symbol,
            interval=_to_vnpy_interval(prepared.settings.interval, interval_enum),
            start=prepared.settings.start,
            end=prepared.settings.end,
            rate=prepared.settings.rate,
            slippage=prepared.settings.slippage,
            size=prepared.settings.size,
            pricetick=prepared.settings.pricetick,
            capital=int(prepared.settings.capital),
        )
        strategy_parameters = dict(prepared.settings.strategy_parameters)
        if auxiliary_bars:
            strategy_parameters["_guiyi_auxiliary_bars"] = auxiliary_bars
        engine.add_strategy(prepared.strategy_class, strategy_parameters)
        engine.history_data = bars
        engine.run_backtesting()
        daily_df = engine.calculate_result()
        statistics = engine.calculate_statistics(daily_df, output=False)

        return {
            "status": "success",
            "engine": "vnpy_cta_backtesting",
            "executed": True,
            "execution_timing": prepared.settings.execution_timing,
            "message": "vn.py BacktestingEngine executed with injected standard bars.",
            "prepared": prepared.to_json(),
            "statistics": statistics,
            "trades": engine.get_all_trades(),
            "orders": engine.get_all_orders(),
            "daily_results": engine.get_all_daily_results(),
            "equity_curve": _dataframe_records(daily_df, fields=("balance",)),
            "drawdown_curve": _dataframe_records(daily_df, fields=("drawdown", "ddpercent")),
            "metadata": {
                "bar_count": len(bars),
                "auxiliary_bar_counts": {interval: len(rows) for interval, rows in auxiliary_bars.items()},
                "data_mode": "injected_standard_bars",
                "load_data_called": False,
                "live_gateway_used": False,
                "strategy_class_name": prepared.strategy_class.__name__,
                "vnpy_runtime_symbol": prepared.settings.vt_symbol.rsplit(".", 1)[0],
            },
        }

    @staticmethod
    def _validate_request(request: GuiyiBacktestRequest) -> None:
        if request.start >= request.end:
            raise BacktestConfigurationError("start must be earlier than end")
        if request.rate < 0:
            raise BacktestConfigurationError("rate cannot be negative")
        if request.slippage < 0:
            raise BacktestConfigurationError("slippage cannot be negative")
        if request.size <= 0:
            raise BacktestConfigurationError("size must be greater than zero")
        if request.pricetick <= 0:
            raise BacktestConfigurationError("pricetick must be greater than zero")
        if request.capital <= 0:
            raise BacktestConfigurationError("capital must be greater than zero")
        if request.bars is not None and request.bar_data_path is not None:
            raise BacktestConfigurationError("provide either bars or bar_data_path, not both")
        overlapping_auxiliary = set(request.auxiliary_bars).intersection(request.auxiliary_bar_data_paths)
        if overlapping_auxiliary:
            intervals = ", ".join(sorted(overlapping_auxiliary))
            raise BacktestConfigurationError(f"provide either auxiliary_bars or auxiliary_bar_data_paths for each interval, not both: {intervals}")


def _load_vnpy_backtesting_objects() -> tuple[type[Any], type[Any], Any, Any]:
    try:
        backtesting_module = require_vnpy("vnpy_ctastrategy.backtesting")
        object_module = require_vnpy("vnpy.trader.object")
        constant_module = require_vnpy("vnpy.trader.constant")
    except Exception as exc:
        if exc.__class__.__name__ == "VnpyNotInstalledError":
            raise
        raise BacktestConfigurationError(f"vn.py backtesting runtime is unavailable: {exc}") from exc

    return (
        backtesting_module.BacktestingEngine,
        object_module.BarData,
        constant_module.Exchange,
        constant_module.Interval,
    )


def _load_request_bars(request: GuiyiBacktestRequest, *, bar_class: type[Any], exchange_enum: Any, interval_enum: Any) -> list[Any]:
    rows = request.bars if request.bars is not None else _read_standard_parquet(request.bar_data_path)
    _validate_standard_rows(rows)
    return [
        _row_to_bar(
            row,
            request=request,
            bar_class=bar_class,
            exchange_enum=exchange_enum,
            interval_enum=interval_enum,
        )
        for row in sorted(rows, key=lambda item: item["datetime"])
    ]


def _load_auxiliary_bars(request: GuiyiBacktestRequest) -> dict[str, list[dict[str, Any]]]:
    loaded: dict[str, list[dict[str, Any]]] = {}
    intervals = sorted(set(request.auxiliary_bars).union(request.auxiliary_bar_data_paths))
    for interval in intervals:
        normalized_interval = interval.strip().lower()
        rows = request.auxiliary_bars.get(interval)
        if rows is None:
            rows = _read_standard_parquet(request.auxiliary_bar_data_paths[interval])
        rows = sorted(list(rows), key=lambda item: item["datetime"])
        _validate_standard_rows(rows)
        if normalized_interval != "1d":
            raise BacktestConfigurationError(f"unsupported auxiliary bar interval: {interval}")
        _validate_auxiliary_interval_rows(rows, normalized_interval)
        loaded[normalized_interval] = rows
    return loaded


def _read_standard_parquet(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        raise BacktestConfigurationError("bar_data_path or bars is required for real vn.py execution")
    parquet_path = Path(path)
    if not parquet_path.exists():
        raise BacktestConfigurationError(f"standard parquet bar_data_path not found: {parquet_path}")
    frame = pd.read_parquet(parquet_path)
    return list(frame.to_dict("records"))


def _validate_standard_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise BacktestConfigurationError("standard bar data is empty")

    required = {"datetime", "open", "high", "low", "close", "volume", "turnover", "open_interest"}
    missing = sorted(required.difference(rows[0]))
    if missing:
        raise BacktestConfigurationError(f"standard bar data missing required fields: {', '.join(missing)}")

    for row in rows:
        role = str(row.get("data_role", "primary"))
        if role != "primary":
            raise BacktestConfigurationError("vn.py backtest only accepts data_role=primary standard bars")
        quality_status = str(row.get("quality_status", "passed"))
        if quality_status != "passed":
            raise BacktestConfigurationError("vn.py backtest only accepts quality_status=passed standard bars")
        if float(row["high"]) < max(float(row["open"]), float(row["close"])):
            raise BacktestConfigurationError("standard bar high must be greater than or equal to open and close")
        if float(row["low"]) > min(float(row["open"]), float(row["close"])):
            raise BacktestConfigurationError("standard bar low must be less than or equal to open and close")


def _validate_auxiliary_interval_rows(rows: list[dict[str, Any]], interval: str) -> None:
    for row in rows:
        row_interval = str(row.get("interval") or row.get("period") or "").strip().lower()
        if row_interval != interval:
            raise BacktestConfigurationError(f"auxiliary {interval} bars require interval/period={interval}")


def _row_to_bar(
    row: dict[str, Any],
    *,
    request: GuiyiBacktestRequest,
    bar_class: type[Any],
    exchange_enum: Any,
    interval_enum: Any,
) -> Any:
    symbol = _to_vnpy_runtime_symbol(str(row.get("contract") or request.symbol))
    exchange_name = normalize_exchange(str(row.get("exchange") or request.exchange))
    return bar_class(
        gateway_name="BACKTESTING",
        symbol=symbol,
        exchange=exchange_enum[exchange_name],
        datetime=_to_naive_datetime(row["datetime"]),
        interval=_to_vnpy_interval(str(row.get("interval") or row.get("period") or request.interval), interval_enum),
        volume=float(row["volume"]),
        turnover=float(row["turnover"]),
        open_interest=float(row["open_interest"]),
        open_price=float(row["open"]),
        high_price=float(row["high"]),
        low_price=float(row["low"]),
        close_price=float(row["close"]),
    )


def _to_vnpy_interval(interval: str, interval_enum: Any) -> Any:
    normalized = interval.strip().lower()
    if normalized in {"1m", "5m", "15m", "minute"}:
        return interval_enum.MINUTE
    if normalized in {"60m", "1h", "hour"}:
        return interval_enum.HOUR
    if normalized in {"d", "1d", "day", "daily"}:
        return interval_enum.DAILY
    raise BacktestConfigurationError(f"unsupported vn.py backtest interval: {interval}")


def _to_vnpy_runtime_symbol(symbol: str) -> str:
    normalized = symbol.strip()
    if not normalized:
        raise BacktestConfigurationError("symbol cannot be empty")
    return normalized.replace(".", "_")


def _to_naive_datetime(value: Any) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value))
    return value.replace(tzinfo=None)


def _dataframe_records(frame: Any, *, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    records: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        item: dict[str, Any] = {"date": index}
        for field_name in fields:
            if field_name in row:
                item[field_name] = row[field_name]
        records.append(item)
    return records
