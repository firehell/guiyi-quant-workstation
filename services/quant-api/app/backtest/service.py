from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.backtest import (
    BacktestDrawdownCurvePointModel,
    BacktestEquityCurvePointModel,
    BacktestOrderModel,
    BacktestReportModel,
    BacktestTask,
    BacktestTradeModel,
)
from app.models.data_center import utc_now
from app.schemas.backtest import BacktestDataRole, BacktestEngineType, BacktestTaskConfig
from app.vnpy_integration.errors import BacktestConfigurationError
from app.vnpy_integration.execution_policy import DEFAULT_EXECUTION_TIMING, validate_execution_timing
from app.vnpy_integration.symbol_mapper import to_vt_symbol


class BacktestService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_task_config(self, payload: BacktestTaskConfig | dict[str, Any]) -> BacktestTaskConfig:
        return payload if isinstance(payload, BacktestTaskConfig) else BacktestTaskConfig.model_validate(payload)

    def create_task(self, config: BacktestTaskConfig | dict[str, Any]) -> BacktestTask:
        task_config = self.create_task_config(config)
        vnpy_setting = self.generate_vnpy_setting(task_config)
        task = BacktestTask(
            task_no=self._new_task_no(),
            task_type=task_config.task_type,
            engine_type=task_config.engine_type.value,
            vnpy_strategy_class=task_config.strategy_class_path,
            vnpy_setting_json=vnpy_setting,
            data_source=task_config.data_source,
            data_role=task_config.data_role.value,
            data_version=task_config.data_version,
            research_only=task_config.research_only,
            status="pending",
            progress=0.0,
            total_items=1,
            request_payload=task_config.model_dump(mode="json"),
            result_payload={},
        )
        self.session.add(task)
        self.session.flush()
        return task

    def config_from_task(self, task: BacktestTask) -> BacktestTaskConfig:
        payload = dict(task.request_payload or {})
        payload.setdefault("engine_type", task.engine_type or BacktestEngineType.VNPY.value)
        payload.setdefault("task_type", task.task_type or "single")
        payload.setdefault("strategy_class_path", task.vnpy_strategy_class)
        payload.setdefault("data_source", task.data_source or "local_parquet")
        payload.setdefault("data_role", task.data_role or BacktestDataRole.PRIMARY.value)
        payload.setdefault("data_version", task.data_version)
        payload.setdefault("research_only", task.research_only)
        return self.create_task_config(payload)

    def generate_vnpy_setting(self, config: BacktestTaskConfig) -> dict[str, Any]:
        execution_timing = validate_execution_timing(config.execution_timing or DEFAULT_EXECUTION_TIMING)
        return {
            "vt_symbol": to_vt_symbol(config.symbol, config.exchange),
            "symbol": config.symbol,
            "exchange": config.exchange,
            "interval": config.interval,
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "rate": config.rate,
            "slippage": config.slippage,
            "size": config.size,
            "pricetick": config.pricetick,
            "capital": config.capital,
            "strategy_class_path": config.strategy_class_path,
            "strategy_code": config.strategy_code,
            "strategy_version": config.strategy_version,
            "strategy_parameters": dict(config.strategy_parameters),
            "execution_timing": execution_timing,
            "bar_data_path": config.bar_data_path,
            "auxiliary_bar_data_paths": dict(config.auxiliary_bar_data_paths),
        }

    def mark_running(self, task: BacktestTask) -> None:
        task.status = "running"
        task.progress = 5.0
        task.started_at = utc_now()
        task.error_type = None
        task.error_message = None
        task.traceback = None
        self.session.commit()

    def mark_success(self, task: BacktestTask, result: dict[str, Any]) -> None:
        self.persist_result(task, result)
        task.status = "success"
        task.progress = 100.0
        task.completed_items = 1
        task.failed_items = 0
        task.finished_at = utc_now()
        task.error_type = None
        task.error_message = None
        task.traceback = None
        self.sanitize_task_local_paths(task)
        self.session.commit()

    def mark_failed(self, task: BacktestTask, error_type: str, error_message: str, traceback_text: str | None = None) -> None:
        task.status = "failed"
        task.progress = 100.0
        task.failed_items = 1
        task.finished_at = utc_now()
        task.error_type = error_type
        task.error_message = self.clean_error_message(error_type, error_message)
        task.traceback = self.clean_traceback(traceback_text)
        self.sanitize_task_local_paths(task)
        self.session.commit()

    def persist_result(self, task: BacktestTask, normalized_result: dict[str, Any]) -> None:
        config = self.config_from_task(task)
        if config.data_role in {BacktestDataRole.VALIDATION, BacktestDataRole.LEGACY_REFERENCE} and not config.research_only:
            raise BacktestConfigurationError("validation and legacy_reference results require research_only=true")
        if config.quality_status.strip().lower() == "failed":
            raise BacktestConfigurationError("failed quality_status data cannot be persisted as a successful backtest")

        for report in list(task.reports):
            self.session.delete(report)
        self.session.flush()

        summary = dict(normalized_result.get("summary") or {})
        summary["report_metadata"] = self.report_metadata(task, config)
        trades = list(normalized_result.get("trades") or [])
        orders = list(normalized_result.get("orders") or [])
        equity_curve = list(normalized_result.get("equity_curve") or [])
        drawdown_curve = list(normalized_result.get("drawdown_curve") or [])
        initial_capital = _float_metric(summary, "initial_capital", "capital")
        final_equity = _metric_or_curve_final(
            _float_metric(summary, "final_equity", "end_balance", "ending_equity", "balance"),
            equity_curve,
        )
        trade_count = max(_int_metric(summary, "trade_count", "total_trade_count", "total_trades"), len(trades))
        max_drawdown_amount = _metric_or_curve_drawdown(_float_metric(summary, "max_drawdown_amount", "max_drawdown"), drawdown_curve)
        max_drawdown_pct = _metric_or_curve_drawdown_pct(_float_metric(summary, "max_drawdown_pct", "max_ddpercent"), drawdown_curve)
        max_drawdown = _float_metric(summary, "max_drawdown", default=max_drawdown_amount)
        total_return = _metric_or_equity_return(_float_metric(summary, "total_return"), initial_capital, final_equity)
        win_rate = _metric_or_trade_win_rate(_float_metric(summary, "win_rate"), trades)
        profit_loss_ratio = _metric_or_trade_profit_loss_ratio(_float_metric(summary, "profit_loss_ratio"), trades)
        max_consecutive_losses = _metric_or_trade_max_consecutive_losses(_int_metric(summary, "max_consecutive_losses"), trades)
        summary["max_consecutive_losses"] = max_consecutive_losses
        summary.setdefault("max_drawdown_amount", max_drawdown_amount)
        summary.setdefault("max_drawdown_pct", max_drawdown_pct)
        now = utc_now()
        report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no=f"{task.task_no}-RPT-{uuid4().hex[:8]}",
            template_name="vnpy",
            template_label="vn.py CTA",
            engine_type=BacktestEngineType.VNPY.value,
            engine_version=(normalized_result.get("metadata") or {}).get("engine_version"),
            strategy_code=config.strategy_code or _strategy_code_from_path(config.strategy_class_path),
            strategy_version=config.strategy_version,
            symbol=_symbol_root(config.symbol),
            contract=config.symbol,
            period=config.interval,
            data_source=config.data_source,
            data_role=config.data_role.value,
            data_version=config.data_version,
            research_only=config.research_only,
            status="success",
            suitability_label="数据不足",
            suitability_score=0.0,
            initial_capital=initial_capital,
            final_equity=final_equity,
            total_return=total_return,
            annual_return=_float_metric(summary, "annual_return"),
            max_drawdown=max_drawdown,
            max_drawdown_amount=max_drawdown_amount,
            max_drawdown_pct=max_drawdown_pct,
            win_rate=win_rate,
            profit_loss_ratio=profit_loss_ratio,
            trade_count=trade_count,
            max_consecutive_losses=max_consecutive_losses,
            total_commission=_float_metric(summary, "total_commission"),
            total_slippage=_float_metric(summary, "total_slippage"),
            max_margin_required=_float_metric(summary, "max_margin_required"),
            max_margin_usage_pct=_float_metric(summary, "max_margin_usage_pct"),
            rollover_exit_count=_int_metric(summary, "rollover_exit_count"),
            delivery_risk_exit_count=_int_metric(summary, "delivery_risk_exit_count"),
            quality_status={"status": config.quality_status},
            summary=summary,
            warnings=list(normalized_result.get("warnings") or []),
            orders=orders,
            fills=trades,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            started_at=task.started_at,
            finished_at=now,
        )
        self.session.add(report)
        self.session.flush()

        for index, trade in enumerate(trades):
            self.session.add(_trade_model(report.id, trade, config=config, index=index))
        for index, order in enumerate(orders):
            self.session.add(_order_model(report.id, order, config=config, index=index))
        for index, point in enumerate(equity_curve):
            self.session.add(_equity_point_model(report.id, point, index=index))
        for index, point in enumerate(drawdown_curve):
            self.session.add(_drawdown_point_model(report.id, point, index=index))

        task.result_payload = {
            "normalized_result": normalized_result,
            "persisted_by": "BacktestService.persist_result",
            "persistence_status": "report_detail_tables",
            "report_id": report.id,
            "report_no": report.report_no,
            "trade_count": len(trades),
            "order_count": len(orders),
            "equity_curve_count": len(equity_curve),
            "drawdown_curve_count": len(drawdown_curve),
        }

    def report_metadata(self, task: BacktestTask, config: BacktestTaskConfig) -> dict[str, Any]:
        return {
            "engine_type": config.engine_type.value,
            "data_source": config.data_source,
            "data_role": config.data_role.value,
            "quality_status": config.quality_status,
            "strategy_code": config.strategy_code or _strategy_code_from_path(config.strategy_class_path),
            "strategy_version": config.strategy_version,
            "symbol": _symbol_root(config.symbol),
            "contract": config.symbol,
            "vt_symbol": to_vt_symbol(config.symbol, config.exchange),
            "exchange": config.exchange,
            "interval": config.interval,
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "initial_capital": config.capital,
            "rate": config.rate,
            "slippage": config.slippage,
            "size": config.size,
            "pricetick": config.pricetick,
            "execution_timing": config.execution_timing,
            "auxiliary_intervals": sorted(config.auxiliary_bar_data_paths),
            "task_no": task.task_no,
        }

    @staticmethod
    def sanitize_task_local_paths(task: BacktestTask) -> None:
        task.request_payload = _redact_bar_data_path(task.request_payload)
        task.vnpy_setting_json = _redact_bar_data_path(task.vnpy_setting_json)

    @staticmethod
    def clean_error_message(error_type: str, message: str) -> str:
        if error_type == "VnpyNotInstalledError":
            return (
                "vn.py is not installed or cannot be imported. "
                "Install the project-approved vn.py dependency before running this backtest task."
            )
        first_line = str(message).strip().splitlines()[0] if str(message).strip() else error_type
        return first_line[:500]

    @staticmethod
    def clean_traceback(traceback_text: str | None) -> str | None:
        if not traceback_text:
            return None
        sanitized = str(traceback_text)
        for marker in ("/Volumes/", "/Users/", "/private/", "\\Users\\"):
            sanitized = sanitized.replace(marker, "<local-path>/")
        return sanitized[-8000:]

    @staticmethod
    def _new_task_no() -> str:
        return f"BTV-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"


def _trade_model(report_id: int, trade: dict[str, Any], *, config: BacktestTaskConfig, index: int) -> BacktestTradeModel:
    open_time = _parse_time(trade.get("entry_datetime") or trade.get("open_time") or trade.get("datetime") or trade.get("close_time"))
    close_time = _parse_time(trade.get("exit_datetime") or trade.get("close_time") or trade.get("datetime") or trade.get("open_time"))
    open_price = _safe_float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    close_price = _safe_float(trade.get("exit_price") or trade.get("close_price") or trade.get("price"))
    volume = int(_safe_float(trade.get("volume"), 1.0))
    direction = str(trade.get("direction") or "unknown")
    gross_pnl = _safe_float(trade.get("gross_pnl"), _gross_pnl(direction, open_price, close_price, volume, config.size))
    turnover = _safe_float(trade.get("turnover"), open_price * volume * config.size)
    commission = _safe_float(trade.get("commission"))
    slippage = _safe_float(trade.get("slippage"))
    contract_multiplier = _optional_int(trade.get("contract_multiplier") or trade.get("size"))
    price_tick = _optional_float(trade.get("price_tick") or trade.get("pricetick"))
    margin_ratio = _optional_float(trade.get("margin_ratio"))
    margin_required = _optional_float(trade.get("margin_required"))
    entry_contract = _optional_str(trade.get("entry_contract"))
    exit_contract = _optional_str(trade.get("exit_contract"))
    if entry_contract is None and exit_contract is not None:
        entry_contract = exit_contract
    if exit_contract is None and entry_contract is not None:
        exit_contract = entry_contract
    return BacktestTradeModel(
        report_id=report_id,
        trade_no=str(trade.get("tradeid") or trade.get("trade_id") or trade.get("trade_no") or f"VN-T-{index + 1}"),
        symbol=_symbol_root(str(trade.get("symbol") or config.symbol)),
        contract=str(trade.get("symbol") or trade.get("contract") or trade.get("contract_code") or config.symbol),
        direction=direction,
        open_time=open_time,
        open_price=open_price,
        close_time=close_time,
        close_price=close_price,
        volume=volume,
        turnover=turnover,
        entry_contract=entry_contract,
        exit_contract=exit_contract,
        entry_contract_month=_optional_str(trade.get("entry_contract_month")),
        exit_contract_month=_optional_str(trade.get("exit_contract_month")),
        contract_multiplier=contract_multiplier,
        price_tick=price_tick,
        commission=commission,
        slippage=slippage,
        margin_ratio=margin_ratio,
        margin_required=margin_required,
        parameter_source=_optional_str(trade.get("parameter_source")),
        fee_rule_source=_optional_dict(trade.get("fee_rule_source")),
        main_contract_source=_optional_dict(trade.get("main_contract_source")),
        rollover_forced_exit=bool(trade.get("rollover_forced_exit", False)),
        delivery_risk_exit=bool(trade.get("delivery_risk_exit", False)),
        rollover_reason=_optional_str(trade.get("rollover_reason")),
        gross_pnl=gross_pnl,
        net_pnl=_safe_float(trade.get("net_pnl"), gross_pnl - commission - slippage),
        return_pct=_safe_float(trade.get("return_pct")),
        holding_bars=int(_safe_float(trade.get("holding_bars") or trade.get("hold_bars"))),
        entry_reason=str(trade.get("entry_reason") or trade.get("reason") or "vnpy_fill"),
        exit_reason=str(trade.get("exit_reason") or "vnpy_fill"),
        raw_payload=dict(trade),
    )


def _order_model(report_id: int, order: dict[str, Any], *, config: BacktestTaskConfig, index: int) -> BacktestOrderModel:
    return BacktestOrderModel(
        report_id=report_id,
        order_no=str(order.get("orderid") or order.get("order_id") or order.get("order_no") or f"VN-O-{index + 1}"),
        symbol=_symbol_root(str(order.get("symbol") or config.symbol)),
        contract=str(order.get("symbol") or order.get("contract") or order.get("contract_code") or config.symbol),
        direction=str(order.get("direction") or "unknown"),
        offset=None if order.get("offset") is None else str(order.get("offset")),
        order_type=None if order.get("type") is None else str(order.get("type")),
        status=None if order.get("status") is None else str(order.get("status")),
        order_time=_parse_optional_time(order.get("datetime") or order.get("order_time")),
        price=_safe_float(order.get("price")),
        volume=_safe_float(order.get("volume")),
        traded=_safe_float(order.get("traded")),
        raw_payload=dict(order),
    )


def _equity_point_model(report_id: int, point: dict[str, Any], *, index: int) -> BacktestEquityCurvePointModel:
    return BacktestEquityCurvePointModel(
        report_id=report_id,
        point_index=index,
        point_time=_parse_optional_time(point.get("datetime") or point.get("time") or point.get("date")),
        equity=_safe_float(point.get("equity") or point.get("balance")),
        raw_payload=dict(point),
    )


def _drawdown_point_model(report_id: int, point: dict[str, Any], *, index: int) -> BacktestDrawdownCurvePointModel:
    return BacktestDrawdownCurvePointModel(
        report_id=report_id,
        point_index=index,
        point_time=_parse_optional_time(point.get("datetime") or point.get("time") or point.get("date")),
        drawdown=_safe_float(point.get("drawdown")),
        drawdown_pct=_safe_float(point.get("drawdown_pct") or point.get("ddpercent")),
        raw_payload=dict(point),
    )


def _redact_bar_data_path(payload: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = dict(payload or {})
    if sanitized.get("bar_data_path"):
        sanitized["bar_data_path"] = "<local_standard_parquet_redacted>"
    if sanitized.get("auxiliary_bar_data_paths"):
        sanitized["auxiliary_bar_data_paths"] = {
            interval: "<local_standard_parquet_redacted>" for interval in sanitized["auxiliary_bar_data_paths"]
        }
    return sanitized


def _strategy_code_from_path(class_path: str) -> str:
    if "su_bing_ema21" in class_path:
        return "su_bing_ema21"
    return class_path.rsplit(".", 1)[-1].rsplit(":", 1)[-1]


def _symbol_root(symbol: str) -> str:
    normalized = symbol.split(".", 1)[0]
    return "".join(char for char in normalized if not char.isdigit()) or normalized


def _float_metric(summary: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in summary and summary[key] is not None:
            return _safe_float(summary[key], default)
    return default


def _int_metric(summary: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        if key in summary and summary[key] is not None:
            return int(_safe_float(summary[key], float(default)))
    return default


def _metric_or_curve_final(value: float, equity_curve: list[dict[str, Any]]) -> float:
    if value != 0 or not equity_curve:
        return value
    return _safe_float(equity_curve[-1].get("equity") or equity_curve[-1].get("balance"))


def _metric_or_curve_drawdown(value: float, drawdown_curve: list[dict[str, Any]]) -> float:
    if value != 0 or not drawdown_curve:
        return value
    return max(abs(_safe_float(point.get("drawdown"))) for point in drawdown_curve)


def _metric_or_curve_drawdown_pct(value: float, drawdown_curve: list[dict[str, Any]]) -> float:
    if value != 0 or not drawdown_curve:
        return value
    values = [
        abs(_safe_float(point.get("drawdown_pct") if point.get("drawdown_pct") is not None else point.get("ddpercent")))
        for point in drawdown_curve
    ]
    return max(values) if values else 0.0


def _metric_or_equity_return(value: float, initial_capital: float, final_equity: float) -> float:
    if value != 0 or initial_capital <= 0 or final_equity <= 0:
        return value
    return (final_equity - initial_capital) / initial_capital


def _metric_or_trade_win_rate(value: float, trades: list[dict[str, Any]]) -> float:
    if value != 0 or not trades:
        return value
    wins = sum(1 for trade in trades if _trade_net_pnl(trade) > 0)
    return wins / len(trades)


def _metric_or_trade_profit_loss_ratio(value: float, trades: list[dict[str, Any]]) -> float:
    if value != 0 or not trades:
        return value
    gross_profit = sum(_trade_net_pnl(trade) for trade in trades if _trade_net_pnl(trade) > 0)
    gross_loss = abs(sum(_trade_net_pnl(trade) for trade in trades if _trade_net_pnl(trade) < 0))
    if gross_loss == 0:
        return 0.0
    return gross_profit / gross_loss


def _metric_or_trade_max_consecutive_losses(value: int, trades: list[dict[str, Any]]) -> int:
    if not trades:
        return value
    return _max_consecutive_losses(trades)


def _max_consecutive_losses(trades: list[dict[str, Any]]) -> int:
    current = 0
    maximum = 0
    for trade in sorted(trades, key=_trade_close_sort_key):
        if _trade_net_pnl(trade) < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _trade_close_sort_key(trade: dict[str, Any]) -> tuple[datetime, str]:
    close_time = _parse_optional_time(trade.get("exit_datetime") or trade.get("close_time") or trade.get("datetime") or trade.get("open_time"))
    trade_no = str(trade.get("tradeid") or trade.get("trade_id") or trade.get("trade_no") or "")
    return close_time or datetime.min.replace(tzinfo=UTC), trade_no


def _trade_net_pnl(trade: dict[str, Any]) -> float:
    explicit = _safe_float(trade.get("net_pnl"))
    if explicit != 0:
        return explicit
    direction = str(trade.get("direction") or "")
    open_price = _safe_float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    close_price = _safe_float(trade.get("exit_price") or trade.get("close_price") or trade.get("price"))
    volume = int(_safe_float(trade.get("volume"), 1.0))
    size = int(_safe_float(trade.get("size"), 1.0))
    return _gross_pnl(direction, open_price, close_price, volume, size)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else int(parsed)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _gross_pnl(direction: str, open_price: float, close_price: float, volume: int, size: int) -> float:
    normalized = direction.lower()
    if normalized in {"short", "空", "short_direction"}:
        return (open_price - close_price) * volume * size
    if normalized in {"long", "多", "long_direction"}:
        return (close_price - open_price) * volume * size
    return 0.0


def _parse_time(value: Any) -> datetime:
    return _parse_optional_time(value) or datetime.now(UTC)


def _parse_optional_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
