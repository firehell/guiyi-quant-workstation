from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.backtest.jm_daily_ema21_result_enricher import enrich_jm_daily_ema21_result, should_enrich_jm_daily_ema21_result
from app.backtest.jm_v1b_result_enricher import enrich_jm_v1b_result, should_enrich_jm_v1b_result
from app.backtest.service import BacktestService
from app.db.session import PROJECT_ROOT
from app.models.backtest import BacktestTask
from app.models.data_center import MarketDataFile
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
            config = self.service.config_from_task(task)
            if should_enrich_jm_v1b_result(config):
                normalized_result = enrich_jm_v1b_result(self.session, config, normalized_result)
            if should_enrich_jm_daily_ema21_result(config):
                normalized_result = enrich_jm_daily_ema21_result(self.session, config, normalized_result)
            self.service.mark_success(task, normalized_result)
            return {
                "task_id": task.id,
                "task_no": task.task_no,
                "status": "success",
                "result": normalized_result,
            }
        except VnpyNotInstalledError as exc:
            return self._fail(task, "VnpyNotInstalledError", str(exc), traceback.format_exc())
        except (BacktestConfigurationError, StrategyLoadError, SymbolMappingError, VnpyIntegrationError, ValueError) as exc:
            return self._fail(task, type(exc).__name__, str(exc), traceback.format_exc())

    def _request_from_task(self, task: BacktestTask) -> GuiyiBacktestRequest:
        config = self.service.config_from_task(task)
        bar_data_path, auxiliary_bar_data_paths = self._execution_paths(task, config)
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
            bar_data_path=bar_data_path,
            auxiliary_bar_data_paths=auxiliary_bar_data_paths,
            execution_timing=config.execution_timing,
        )

    def _execution_paths(self, task: BacktestTask, config: Any) -> tuple[str | Path | None, dict[str, str | Path]]:
        if task.research_only:
            return config.bar_data_path, dict(config.auxiliary_bar_data_paths)

        snapshot = task.binding_snapshot
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != "backtest_binding_snapshot_v1":
            raise BacktestConfigurationError("formal backtest task requires immutable binding_snapshot")
        if not task.profile_id or snapshot.get("profile_id") != task.profile_id:
            raise BacktestConfigurationError("formal backtest task profile_id does not match binding_snapshot")
        primary = snapshot.get("primary")
        if not isinstance(primary, dict):
            raise BacktestConfigurationError("formal backtest binding_snapshot primary asset is missing")
        if task.market_data_file_id is None or primary.get("market_data_file_id") != task.market_data_file_id:
            raise BacktestConfigurationError("formal backtest task market_data_file_id does not match binding_snapshot")
        primary_path = self._validated_pinned_asset(primary, expected_profile_id=task.profile_id)

        auxiliary_paths: dict[str, str | Path] = {}
        auxiliary = snapshot.get("auxiliary")
        if not isinstance(auxiliary, dict):
            raise BacktestConfigurationError("formal backtest binding_snapshot auxiliary assets are invalid")
        for period, asset in auxiliary.items():
            if not isinstance(period, str) or not isinstance(asset, dict):
                raise BacktestConfigurationError("formal backtest auxiliary asset snapshot is invalid")
            if asset.get("period") != period:
                raise BacktestConfigurationError("formal backtest auxiliary period does not match binding_snapshot")
            auxiliary_paths[period] = self._validated_pinned_asset(asset, expected_profile_id=task.profile_id)
        return primary_path, auxiliary_paths

    def _validated_pinned_asset(self, asset: dict[str, Any], *, expected_profile_id: str) -> Path:
        file_id = asset.get("market_data_file_id")
        if not isinstance(file_id, int):
            raise BacktestConfigurationError("formal backtest asset market_data_file_id is missing")
        market_file = self.session.get(MarketDataFile, file_id)
        if market_file is None:
            raise BacktestConfigurationError("formal backtest pinned MarketDataFile is missing")
        expected = {
            "profile_id": expected_profile_id,
            "instrument_symbol": market_file.instrument_symbol,
            "contract_code": market_file.contract_code,
            "period": market_file.period,
            "provider": market_file.provider,
            "data_role": "primary",
            "quality_status": "passed",
            "data_version": market_file.data_version,
            "checksum": market_file.checksum,
        }
        for field_name, expected_value in expected.items():
            if asset.get(field_name) != expected_value:
                raise BacktestConfigurationError(f"formal backtest pinned asset {field_name} mismatch")
        if market_file.data_role != "primary" or market_file.quality_status != "passed":
            raise BacktestConfigurationError("formal backtest pinned asset is no longer primary/passed")
        if market_file.provider not in {"rqdata", "local_parquet"}:
            raise BacktestConfigurationError("formal backtest pinned asset provider is not allowed")
        registered_path = Path(market_file.file_path)
        path = registered_path if registered_path.is_absolute() else PROJECT_ROOT / registered_path
        if str(path) != str(asset.get("file_path")):
            raise BacktestConfigurationError("formal backtest pinned asset file path mismatch")
        if not path.is_file():
            raise BacktestConfigurationError("formal backtest pinned asset file is missing")
        return path

    def _fail(self, task: BacktestTask, error_type: str, error_message: str, traceback_text: str) -> dict[str, Any]:
        self.service.mark_failed(task, error_type, error_message, traceback_text=traceback_text)
        return {
            "task_id": task.id,
            "task_no": task.task_no,
            "status": "failed",
            "error_type": task.error_type,
            "error_message": task.error_message,
        }
