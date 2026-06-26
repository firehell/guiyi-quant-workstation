from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.backtest import BacktestTask
from app.models.data_center import utc_now
from app.schemas.backtest import BacktestDataRole, BacktestEngineType, BacktestTaskConfig
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
            "strategy_parameters": dict(config.strategy_parameters),
            "execution_timing": execution_timing,
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
        self.session.commit()

    def mark_failed(self, task: BacktestTask, error_type: str, error_message: str) -> None:
        task.status = "failed"
        task.progress = 100.0
        task.failed_items = 1
        task.finished_at = utc_now()
        task.error_type = error_type
        task.error_message = self.clean_error_message(error_type, error_message)
        task.traceback = None
        self.session.commit()

    def persist_result(self, task: BacktestTask, normalized_result: dict[str, Any]) -> None:
        task.result_payload = {
            "normalized_result": normalized_result,
            "persisted_by": "BacktestService.persist_result",
            "persistence_status": "task_payload_only",
            "note": "Report/trade table persistence will be wired in a later API/report task.",
        }

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
    def _new_task_no() -> str:
        return f"BTV-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
