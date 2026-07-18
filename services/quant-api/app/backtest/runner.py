from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.backtest.jm_daily_ema21_result_enricher import enrich_jm_daily_ema21_result, should_enrich_jm_daily_ema21_result
from app.backtest.jm_v1b_result_enricher import enrich_jm_v1b_result, should_enrich_jm_v1b_result
from app.backtest.errors import BacktestContractError
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
        except BacktestContractError as exc:
            return self._fail(task, exc.code, str(exc), traceback.format_exc())
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
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest task requires immutable binding_snapshot",
                context=self._task_context(task, config),
            )
        if not task.profile_id or snapshot.get("profile_id") != task.profile_id:
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest task profile_id does not match binding_snapshot",
                context=self._task_context(task, config),
            )
        primary = snapshot.get("primary")
        if not isinstance(primary, dict):
            raise BacktestContractError(
                "BACKTEST_PROFILE_MARKET_FILE_MISSING",
                "formal backtest binding_snapshot primary asset is missing",
                context=self._task_context(task, config),
            )
        if task.market_data_file_id is None or primary.get("market_data_file_id") != task.market_data_file_id:
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest task market_data_file_id does not match binding_snapshot",
                context=self._task_context(task, config),
            )
        primary_path = self._validated_pinned_asset(primary, expected_profile_id=task.profile_id)

        auxiliary_paths: dict[str, str | Path] = {}
        auxiliary = snapshot.get("auxiliary")
        if not isinstance(auxiliary, dict):
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest binding_snapshot auxiliary assets are invalid",
                context=self._task_context(task, config),
            )
        for period, asset in auxiliary.items():
            if not isinstance(period, str) or not isinstance(asset, dict):
                raise BacktestContractError(
                    "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                    "formal backtest auxiliary asset snapshot is invalid",
                    context=self._task_context(task, config),
                )
            if asset.get("period") != period:
                raise BacktestContractError(
                    "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                    "formal backtest auxiliary period does not match binding_snapshot",
                    context=self._task_context(task, config),
                )
            auxiliary_paths[period] = self._validated_pinned_asset(asset, expected_profile_id=task.profile_id)
        return primary_path, auxiliary_paths

    def _validated_pinned_asset(self, asset: dict[str, Any], *, expected_profile_id: str) -> Path:
        file_id = asset.get("market_data_file_id")
        if not isinstance(file_id, int):
            raise BacktestContractError(
                "BACKTEST_PROFILE_MARKET_FILE_MISSING",
                "formal backtest asset market_data_file_id is missing",
                context=self._asset_context(asset, expected_profile_id),
            )
        market_file = self.session.get(MarketDataFile, file_id)
        if market_file is None:
            raise BacktestContractError(
                "BACKTEST_PROFILE_MARKET_FILE_MISSING",
                "formal backtest pinned MarketDataFile is missing",
                context=self._asset_context(asset, expected_profile_id),
            )
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
                raise BacktestContractError(
                    "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                    f"formal backtest pinned asset {field_name} mismatch",
                    context=self._asset_context(asset, expected_profile_id),
                )
        if market_file.data_role != "primary" or market_file.quality_status != "passed":
            raise BacktestContractError(
                "BACKTEST_PROFILE_QUALITY_BLOCKED",
                "formal backtest pinned asset is no longer primary/passed",
                context=self._asset_context(asset, expected_profile_id),
            )
        if market_file.provider not in {"rqdata", "local_parquet"}:
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest pinned asset provider is not allowed",
                context=self._asset_context(asset, expected_profile_id),
            )
        registered_path = Path(market_file.file_path)
        path = registered_path if registered_path.is_absolute() else PROJECT_ROOT / registered_path
        if str(path) != str(asset.get("file_path")):
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest pinned asset file path mismatch",
                context=self._asset_context(asset, expected_profile_id),
            )
        if not path.is_file():
            raise BacktestContractError(
                "BACKTEST_PROFILE_FILE_MISSING",
                "formal backtest pinned asset file is missing",
                context=self._asset_context(asset, expected_profile_id),
            )
        return path

    @staticmethod
    def _task_context(task: BacktestTask, config: Any) -> dict[str, str | None]:
        payload = task.request_payload or {}
        return {
            "profile_id": task.profile_id,
            "instrument_symbol": payload.get("instrument_symbol"),
            "contract_code": payload.get("contract_code") or config.symbol,
            "period": config.interval,
        }

    @staticmethod
    def _asset_context(asset: dict[str, Any], expected_profile_id: str) -> dict[str, str | None]:
        return {
            "profile_id": expected_profile_id,
            "instrument_symbol": asset.get("instrument_symbol"),
            "contract_code": asset.get("contract_code"),
            "period": asset.get("period"),
        }

    def _fail(self, task: BacktestTask, error_type: str, error_message: str, traceback_text: str) -> dict[str, Any]:
        self.service.mark_failed(task, error_type, error_message, traceback_text=traceback_text)
        return {
            "task_id": task.id,
            "task_no": task.task_no,
            "status": "failed",
            "error_type": task.error_type,
            "error_message": task.error_message,
        }
