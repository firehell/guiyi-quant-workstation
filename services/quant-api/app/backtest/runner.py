from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.backtest.service import BacktestService
from app.models.backtest import BacktestTask
from app.vnpy_integration.backtest_runner import GuiyiBacktestRequest, VnpyBacktestRunner
from app.vnpy_integration.errors import BacktestConfigurationError, StrategyLoadError, SymbolMappingError, VnpyIntegrationError, VnpyNotInstalledError
from app.vnpy_integration.result_converter import convert_vnpy_result


class BacktestTaskRunner:
    def __init__(self, session: Session, adapter: VnpyBacktestRunner | Any | None = None, service: BacktestService | None = None) -> None:
        self.session = session
        self.service = service or BacktestService(session)
        self.adapter = adapter or VnpyBacktestRunner()

    def run(self, task_id: int) -> dict[str, Any]:
        task = self.session.get(BacktestTask, task_id)
        if task is None:
            raise ValueError(f"backtest task not found: {task_id}")

        self.service.mark_running(task)
        try:
            request = self._request_from_task(task)
            raw_result = self.adapter.run(request)
            normalized_result = convert_vnpy_result(raw_result)
            self.service.mark_success(task, normalized_result)
            return {
                "task_id": task.id,
                "task_no": task.task_no,
                "status": "success",
                "result": normalized_result,
            }
        except VnpyNotInstalledError as exc:
            return self._fail(task, "VnpyNotInstalledError", str(exc))
        except (BacktestConfigurationError, StrategyLoadError, SymbolMappingError, VnpyIntegrationError, ValueError) as exc:
            return self._fail(task, type(exc).__name__, str(exc))

    def _request_from_task(self, task: BacktestTask) -> GuiyiBacktestRequest:
        config = self.service.config_from_task(task)
        return GuiyiBacktestRequest(
            symbol=config.symbol,
            exchange=config.exchange,
            interval=config.interval,
            start=config.start,
            end=config.end,
            rate=config.rate,
            slippage=config.slippage,
            size=config.size,
            pricetick=config.pricetick,
            capital=config.capital,
            strategy_class_path=config.strategy_class_path,
            strategy_parameters=dict(config.strategy_parameters),
            bar_data_path=config.bar_data_path,
            execution_timing=config.execution_timing,
        )

    def _fail(self, task: BacktestTask, error_type: str, error_message: str) -> dict[str, Any]:
        self.service.mark_failed(task, error_type, error_message)
        return {
            "task_id": task.id,
            "task_no": task.task_no,
            "status": "failed",
            "error_type": task.error_type,
            "error_message": task.error_message,
        }
