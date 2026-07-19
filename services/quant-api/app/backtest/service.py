from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.equity_curve_generator import generate_equity_curve
from app.backtest.errors import BacktestContractError
from app.backtest.report_metrics import compute_report_metrics
from app.db.session import PROJECT_ROOT
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTask, BacktestTradeModel
from app.models.data_center import utc_now
from app.schemas.backtest import (
    BacktestDataRole,
    BacktestEngineType,
    BacktestTaskConfig,
    FormalBacktestTaskRequest,
)
from app.services.profile_lineage import PASSED_ONLY_POLICY, ProfileLineage, ProfileLineageResolver
from app.vnpy_integration.errors import BacktestConfigurationError
from app.vnpy_integration.execution_policy import DEFAULT_EXECUTION_TIMING, validate_execution_timing
from app.vnpy_integration.result_converter import apply_backtest_lineage_mapping
from app.vnpy_integration.symbol_mapper import to_vt_symbol


BACKTEST_RESOLVER_NAME = "ProfileLineageResolver"
BACKTEST_RESOLVER_CONTRACT_VERSION = "backtest_profile_v1"

_BLOCKED_LINEAGE_ERRORS: dict[str, tuple[str, str]] = {
    "profile_not_found": ("BACKTEST_PROFILE_NOT_FOUND", "formal backtest Profile was not found"),
    "profile_binding_missing": (
        "BACKTEST_PROFILE_BINDING_MISSING",
        "formal backtest Profile binding is missing",
    ),
    "profile_market_file_missing": (
        "BACKTEST_PROFILE_MARKET_FILE_MISSING",
        "formal backtest Profile binding has no MarketDataFile",
    ),
    "profile_quality_failed": (
        "BACKTEST_PROFILE_QUALITY_BLOCKED",
        "formal backtest Profile quality is not passed",
    ),
    "profile_quality_policy_blocked": (
        "BACKTEST_PROFILE_QUALITY_BLOCKED",
        "formal backtest Profile quality is not passed",
    ),
    "profile_lineage_incomplete": (
        "BACKTEST_PROFILE_LINEAGE_INCOMPLETE",
        "formal backtest Profile source interval is not auditable",
    ),
    "profile_identity_mismatch": (
        "BACKTEST_PROFILE_IDENTITY_MISMATCH",
        "formal backtest Profile asset identity does not match",
    ),
    "profile_file_missing": (
        "BACKTEST_PROFILE_FILE_MISSING",
        "formal backtest market data file is missing",
    ),
}


class BacktestService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_task_config(self, payload: BacktestTaskConfig | dict[str, Any]) -> BacktestTaskConfig:
        return payload if isinstance(payload, BacktestTaskConfig) else BacktestTaskConfig.model_validate(payload)

    def create_task(self, config: BacktestTaskConfig | dict[str, Any]) -> BacktestTask:
        """Persist an explicitly non-formal low-level/experiment task.

        Formal API callers must use ``create_formal_task``.  Requiring the
        research-only marker prevents a direct-path config from masquerading
        as a production-research task.
        """
        task_config = self.create_task_config(config)
        if not task_config.research_only:
            raise BacktestConfigurationError(
                "direct BacktestTaskConfig persistence is legacy/experiment-only and requires research_only=true; "
                "formal tasks must use create_formal_task"
            )
        return self._persist_task(task_config, profile_id=None, market_data_file_id=None, binding_snapshot=None)

    def create_formal_task(
        self,
        request: FormalBacktestTaskRequest | dict[str, Any],
        *,
        server_context: dict[str, Any] | None = None,
    ) -> BacktestTask:
        formal_request = (
            request if isinstance(request, FormalBacktestTaskRequest) else FormalBacktestTaskRequest.model_validate(request)
        )
        resolver = ProfileLineageResolver(self.session)
        primary, primary_asset = self.resolve_formal_asset(
            instrument_symbol=formal_request.instrument_symbol,
            contract_code=formal_request.contract_code,
            period=formal_request.interval,
            profile_id=formal_request.profile_id,
            resolver=resolver,
        )
        self._validate_requested_window(primary_asset, start=formal_request.start, end=formal_request.end)
        selected_profile_id = primary.profile_id
        if not selected_profile_id:
            raise BacktestConfigurationError("formal backtest profile resolution returned no profile_id")

        auxiliary_assets: dict[str, dict[str, Any]] = {}
        auxiliary_paths: dict[str, str] = {}
        for period in formal_request.auxiliary_periods:
            _, asset = self.resolve_formal_asset(
                instrument_symbol=formal_request.instrument_symbol,
                contract_code=formal_request.contract_code,
                period=period,
                profile_id=selected_profile_id,
                resolver=resolver,
            )
            self._validate_requested_window(asset, start=formal_request.start, end=formal_request.end)
            auxiliary_assets[period] = asset
            auxiliary_paths[period] = str(asset["file_path"])

        binding_snapshot = {
            "schema_version": "backtest_binding_snapshot_v1",
            "resolver_name": BACKTEST_RESOLVER_NAME,
            "resolver_contract_version": BACKTEST_RESOLVER_CONTRACT_VERSION,
            "quality_policy": PASSED_ONLY_POLICY,
            "profile_id": selected_profile_id,
            "primary": primary_asset,
            "auxiliary": auxiliary_assets,
        }
        cost_parameters = {
            "rate": formal_request.rate,
            "slippage": formal_request.slippage,
            "size": formal_request.size,
            "pricetick": formal_request.pricetick,
            "capital": formal_request.capital,
        }
        try:
            from guiyi_quant.strategies.indicator_policy import build_formal_strategy_indicator_policy

            indicator_policy = build_formal_strategy_indicator_policy(
                strategy_code=formal_request.strategy_code,
                strategy_version=formal_request.strategy_version,
                profile_id=selected_profile_id,
                execution_timing=formal_request.execution_timing,
                strategy_parameters=formal_request.strategy_parameters,
                cost_parameters=cost_parameters,
                explicit_snapshot=(
                    formal_request.strategy_parameters.get("indicator_policy_snapshot")
                    if isinstance(formal_request.strategy_parameters.get("indicator_policy_snapshot"), dict)
                    else None
                ),
            )
        except ValueError as exc:
            raise BacktestConfigurationError(str(exc)) from exc
        indicator_policy_snapshot = indicator_policy.to_dict()
        binding_snapshot["indicator_policy_snapshot"] = indicator_policy_snapshot
        task_config = BacktestTaskConfig(
            engine_type=formal_request.engine_type,
            task_type=formal_request.task_type,
            symbol=formal_request.contract_code,
            exchange=formal_request.exchange,
            interval=formal_request.interval,
            start=formal_request.start,
            end=formal_request.end,
            strategy_class_path=formal_request.strategy_class_path,
            strategy_code=formal_request.strategy_code,
            strategy_version=formal_request.strategy_version,
            strategy_parameters=formal_request.strategy_parameters,
            rate=formal_request.rate,
            slippage=formal_request.slippage,
            size=formal_request.size,
            pricetick=formal_request.pricetick,
            capital=formal_request.capital,
            execution_timing=formal_request.execution_timing,
            data_source=str(primary_asset["provider"]),
            data_role=BacktestDataRole.PRIMARY,
            data_version=primary.data_version,
            research_only=False,
            quality_status="passed",
            bar_data_path=str(primary_asset["file_path"]),
            auxiliary_bar_data_paths=auxiliary_paths,
            request_payload={
                **deepcopy(server_context or {}),
                "formal_consumer": True,
                "instrument_symbol": formal_request.instrument_symbol,
                "contract_code": formal_request.contract_code,
                "profile_id": selected_profile_id,
                "indicator_policy_snapshot": indicator_policy_snapshot,
            },
        )
        return self._persist_task(
            task_config,
            profile_id=selected_profile_id,
            market_data_file_id=primary.market_data_file_id,
            binding_snapshot=binding_snapshot,
        )

    def _persist_task(
        self,
        task_config: BacktestTaskConfig,
        *,
        profile_id: str | None,
        market_data_file_id: int | None,
        binding_snapshot: dict[str, Any] | None,
    ) -> BacktestTask:
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
            profile_id=profile_id,
            market_data_file_id=market_data_file_id,
            binding_snapshot=deepcopy(binding_snapshot),
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

    def resolve_formal_asset(
        self,
        *,
        instrument_symbol: str,
        contract_code: str,
        period: str,
        profile_id: str | None,
        resolver: ProfileLineageResolver | None = None,
    ) -> tuple[ProfileLineage, dict[str, Any]]:
        """Resolve and strictly validate one formal backtest asset.

        Inline, batch, fixed-task and API callers can reuse this method instead
        of duplicating passed-only/profile/file checks.
        """
        lineage_resolver = resolver or ProfileLineageResolver(self.session)
        lineage = lineage_resolver.resolve(
            consumer="backtest",
            symbol=instrument_symbol,
            contract=contract_code,
            period=period,
            profile_id=profile_id,
            allow_warning_quality=False,
        )
        if lineage.blocked:
            code, message = _BLOCKED_LINEAGE_ERRORS.get(
                str(lineage.blocked_reason),
                ("BACKTEST_PROFILE_IDENTITY_MISMATCH", "formal backtest Profile lineage is invalid"),
            )
            raise BacktestContractError(
                code,
                message,
                context=self._lineage_context(
                    profile_id=lineage.profile_id or profile_id,
                    instrument_symbol=instrument_symbol,
                    contract_code=contract_code,
                    period=period,
                ),
            )
        market_file = lineage.market_file
        snapshot = lineage.binding_snapshot
        if market_file is None or lineage.market_data_file_id is None or snapshot is None:
            raise BacktestContractError(
                "BACKTEST_PROFILE_MARKET_FILE_MISSING",
                "formal backtest Profile lineage has no MarketDataFile",
                context=self._lineage_context(
                    profile_id=lineage.profile_id or profile_id,
                    instrument_symbol=instrument_symbol,
                    contract_code=contract_code,
                    period=period,
                ),
            )
        context = self._lineage_context(
            profile_id=lineage.profile_id,
            instrument_symbol=instrument_symbol,
            contract_code=contract_code,
            period=period,
        )
        if lineage.quality_policy != PASSED_ONLY_POLICY:
            raise BacktestContractError(
                "BACKTEST_PROFILE_QUALITY_BLOCKED",
                "formal backtest requires quality_policy=passed_only",
                context=context,
            )
        if market_file.provider not in {"rqdata", "local_parquet"}:
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest Profile provider is not allowed",
                context=context,
            )
        if market_file.data_role != "primary":
            raise BacktestContractError(
                "BACKTEST_PROFILE_QUALITY_BLOCKED",
                "formal backtest MarketDataFile must have data_role=primary",
                context=context,
            )
        if market_file.quality_status != "passed":
            raise BacktestContractError(
                "BACKTEST_PROFILE_QUALITY_BLOCKED",
                "formal backtest MarketDataFile must have quality_status=passed",
                context=context,
            )
        expected_identity = (instrument_symbol, contract_code, period)
        actual_identity = (market_file.instrument_symbol, market_file.contract_code, market_file.period)
        if actual_identity != expected_identity:
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest MarketDataFile identity does not match request",
                context=context,
            )
        if snapshot.get("binding_status") != "active":
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest Profile binding is not active",
                context=context,
            )
        if snapshot.get("market_data_file_id") != market_file.id:
            raise BacktestContractError(
                "BACKTEST_PROFILE_IDENTITY_MISMATCH",
                "formal backtest Profile binding and MarketDataFile do not match",
                context=context,
            )
        raw_path = Path(market_file.file_path)
        path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
        if not path.is_file():
            raise BacktestContractError(
                "BACKTEST_PROFILE_FILE_MISSING",
                "formal backtest market data file is missing",
                context=context,
            )
        asset = {
            **deepcopy(snapshot),
            "resolver_name": BACKTEST_RESOLVER_NAME,
            "resolver_contract_version": BACKTEST_RESOLVER_CONTRACT_VERSION,
            "quality_policy": PASSED_ONLY_POLICY,
            "market_data_file_id": market_file.id,
            "instrument_symbol": instrument_symbol,
            "contract_code": contract_code,
            "period": period,
            "provider": market_file.provider,
            "data_role": market_file.data_role,
            "quality_status": market_file.quality_status,
            "data_version": market_file.data_version,
            "file_path": str(path),
            "checksum": market_file.checksum,
            "start_time": market_file.start_time.isoformat(),
            "end_time": market_file.end_time.isoformat(),
        }
        return lineage, asset

    @staticmethod
    def _validate_requested_window(asset: dict[str, Any], *, start: datetime, end: datetime) -> None:
        asset_start = datetime.fromisoformat(str(asset["start_time"]).replace("Z", "+00:00"))
        asset_end = datetime.fromisoformat(str(asset["end_time"]).replace("Z", "+00:00"))
        requested_start = start.replace(tzinfo=None)
        requested_end = end.replace(tzinfo=None)
        if asset_start.replace(tzinfo=None) > requested_start or asset_end.replace(tzinfo=None) < requested_end:
            raise BacktestContractError(
                "BACKTEST_PROFILE_RANGE_NOT_COVERED",
                "formal backtest requested window is outside the pinned asset coverage",
                context=BacktestService._lineage_context(
                    profile_id=asset.get("profile_id"),
                    instrument_symbol=asset.get("instrument_symbol"),
                    contract_code=asset.get("contract_code"),
                    period=asset.get("period"),
                ),
            )

    @staticmethod
    def _lineage_context(
        *,
        profile_id: Any,
        instrument_symbol: Any,
        contract_code: Any,
        period: Any,
    ) -> dict[str, str | None]:
        return {
            "profile_id": str(profile_id) if profile_id is not None else None,
            "instrument_symbol": str(instrument_symbol),
            "contract_code": str(contract_code),
            "period": str(period),
        }

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
        if not task.research_only and (
            task.profile_id is None or task.market_data_file_id is None or task.binding_snapshot is None
        ):
            raise BacktestConfigurationError("formal backtest result requires immutable profile binding lineage")
        if config.data_role is not BacktestDataRole.PRIMARY:
            raise BacktestConfigurationError("only primary RQData/local parquet data is active for backtest results")
        if config.quality_status.strip().lower() == "failed":
            raise BacktestConfigurationError("failed quality_status data cannot be persisted as a successful backtest")

        for report in list(task.reports):
            self.session.delete(report)
        self.session.flush()

        summary = dict(normalized_result.get("summary") or {})
        summary["report_metadata"] = self.report_metadata(task, config)
        trades = list(normalized_result.get("trades") or [])
        summary["quality_status"] = {"status": config.quality_status}
        trades = _standardize_trade_sequence(trades)
        orders = list(normalized_result.get("orders") or [])
        lineage = apply_backtest_lineage_mapping(
            trades=trades,
            orders=orders,
            strategy_execution_events=list(normalized_result.get("strategy_execution_events") or []),
        )
        trades = lineage["trades"]
        orders = lineage["orders"]
        summary["lineage_summary"] = lineage["lineage_summary"]
        initial_capital = _float_metric(summary, "initial_capital", "capital", default=config.capital)
        equity_curve = generate_equity_curve(trades, initial_capital=initial_capital)
        drawdown_result = generate_drawdown_curve(equity_curve)
        drawdown_curve = drawdown_result["drawdown_curve"]
        metrics = compute_report_metrics(
            summary=summary,
            trades=trades,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            start=config.start,
            end=config.end,
            default_initial_capital=config.capital,
        )
        summary.update(metrics)
        consistency_hash = compute_consistency_hash(summary=summary, trades=trades)
        summary["consistency_hash"] = consistency_hash
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
            profile_id=task.profile_id,
            market_data_file_id=task.market_data_file_id,
            binding_snapshot=deepcopy(task.binding_snapshot),
            research_only=config.research_only,
            status="success",
            suitability_label="数据不足",
            suitability_score=0.0,
            consistency_hash=consistency_hash,
            summary=summary,
            warnings=list(normalized_result.get("warnings") or []),
            started_at=task.started_at,
            finished_at=now,
        )
        self.session.add(report)
        self.session.flush()

        for index, trade in enumerate(trades):
            self.session.add(_trade_model(report.id, trade, config=config, index=index))
        for index, order in enumerate(orders):
            self.session.add(_order_model(report.id, order, config=config, index=index))

        task.result_payload = {
            "normalized_result": _result_fact_payload(normalized_result),
            "persisted_by": "BacktestService.persist_result",
            "persistence_status": "backtest_result_v1_summary_trades",
            "report_id": report.id,
            "report_no": report.report_no,
            "consistency_hash": consistency_hash,
            "trade_count": len(trades),
            "order_count": len(orders),
            "lineage_summary": lineage["lineage_summary"],
            "derived_curve_source": "trades",
            "ignored_input_curve_fields": [
                key
                for key in ("equity_curve", "drawdown_curve", "balance_curve", "daily_results")
                if key in normalized_result
            ],
        }

    def report_metadata(self, task: BacktestTask, config: BacktestTaskConfig) -> dict[str, Any]:
        metadata = {
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
        strategy_review_context = config.request_payload.get("strategy_review_context")
        if isinstance(strategy_review_context, dict):
            metadata["strategy_review_context"] = strategy_review_context
        indicator_policy_snapshot = config.request_payload.get("indicator_policy_snapshot")
        if not isinstance(indicator_policy_snapshot, dict) and isinstance(task.binding_snapshot, dict):
            indicator_policy_snapshot = task.binding_snapshot.get("indicator_policy_snapshot")
        if isinstance(indicator_policy_snapshot, dict):
            metadata["indicator_policy_snapshot"] = deepcopy(indicator_policy_snapshot)
        return metadata

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
    contract_multiplier = _optional_int(trade.get("contract_multiplier") or trade.get("size")) or config.size
    price_tick = _optional_float(trade.get("price_tick") or trade.get("pricetick")) or config.pricetick
    margin_ratio = _optional_float(trade.get("margin_ratio"))
    margin_required = _optional_float(trade.get("margin_required"))
    entry_contract = _optional_str(trade.get("entry_contract"))
    exit_contract = _optional_str(trade.get("exit_contract"))
    if entry_contract is None and exit_contract is not None:
        entry_contract = exit_contract
    if exit_contract is None and entry_contract is not None:
        exit_contract = entry_contract
    sequence = int(_safe_float(trade.get("sequence"), float(index + 1)))
    return BacktestTradeModel(
        report_id=report_id,
        trade_no=str(trade.get("tradeid") or trade.get("trade_id") or trade.get("trade_no") or f"VN-T-{index + 1}"),
        sequence=sequence,
        symbol=_symbol_root(str(trade.get("symbol") or config.symbol)),
        exchange=str(trade.get("exchange") or config.exchange),
        research_contract=str(trade.get("research_contract") or trade.get("research_symbol") or config.symbol),
        contract=str(trade.get("contract") or trade.get("contract_code") or trade.get("symbol") or config.symbol),
        timeframe=str(trade.get("timeframe") or trade.get("interval") or trade.get("entry_interval") or config.interval),
        direction=direction,
        entry_signal_time=_parse_optional_time(trade.get("entry_signal_time") or trade.get("signal_time")),
        entry_signal_source=_optional_str(trade.get("entry_signal_source")),
        entry_order_no=_optional_str(trade.get("entry_order_no")),
        open_time=open_time,
        open_price=open_price,
        exit_signal_time=_parse_optional_time(trade.get("exit_signal_time")),
        exit_signal_source=_optional_str(trade.get("exit_signal_source")),
        exit_order_no=_optional_str(trade.get("exit_order_no")),
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
        stop_loss_price=_optional_float(trade.get("stop_loss_price")),
        entry_reason=str(trade.get("entry_reason") or trade.get("reason") or "vnpy_fill"),
        exit_reason=str(trade.get("exit_reason") or "vnpy_fill"),
        lineage_status=_optional_str(trade.get("lineage_status")),
        raw_payload=_trade_raw_payload(trade),
    )


def _order_model(report_id: int, order: dict[str, Any], *, config: BacktestTaskConfig, index: int) -> BacktestOrderModel:
    return BacktestOrderModel(
        report_id=report_id,
        order_no=str(order.get("orderid") or order.get("order_id") or order.get("order_no") or f"VN-O-{index + 1}"),
        trade_no=_optional_str(order.get("trade_no")),
        leg=_optional_str(order.get("leg")),
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
        lineage_source=_optional_str(order.get("lineage_source")),
        mapping_status=_optional_str(order.get("mapping_status")),
        raw_payload=dict(order),
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


def _standardize_trade_sequence(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    standardized: list[dict[str, Any]] = []
    for index, trade in enumerate(trades):
        row = dict(trade)
        row.setdefault("sequence", index + 1)
        standardized.append(row)
    return standardized


def compute_consistency_hash(*, summary: dict[str, Any], trades: list[dict[str, Any]]) -> str:
    payload = {
        "schema_version": "backtest_result.v1.0",
        "summary": _canonical_hash_value(summary),
        "trades": [_canonical_hash_value(trade) for trade in sorted(trades, key=_trade_hash_sort_key)],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default).encode()
    return hashlib.sha256(encoded).hexdigest()


_VOLATILE_HASH_KEYS = {
    "created_at",
    "finished_at",
    "generated_at",
    "report_id",
    "report_no",
    "started_at",
    "task_id",
    "task_no",
    "updated_at",
    "consistency_hash",
}
_CURVE_FACT_KEYS = {
    "balance",
    "balance_curve",
    "daily_results",
    "drawdown",
    "drawdown_curve",
    "drawdown_pct",
    "equity",
    "equity_after_trade",
    "equity_curve",
    "peak_equity",
}


def _canonical_hash_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_hash_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_HASH_KEYS and str(key) not in _CURVE_FACT_KEYS
        }
    if isinstance(value, list):
        return [_canonical_hash_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _trade_hash_sort_key(trade: dict[str, Any]) -> tuple[datetime, int, str]:
    close_time = _parse_optional_time(
        trade.get("exit_time") or trade.get("exit_datetime") or trade.get("close_time") or trade.get("datetime") or trade.get("open_time")
    )
    sequence = int(_safe_float(trade.get("sequence"), 0.0))
    trade_no = str(trade.get("trade_id") or trade.get("tradeid") or trade.get("trade_no") or trade.get("id") or "")
    return close_time or datetime.min.replace(tzinfo=UTC), sequence, trade_no


def _trade_raw_payload(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(trade).items()
        if str(key) not in _CURVE_FACT_KEYS
    }


def _result_fact_payload(normalized_result: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in normalized_result.items()
        if str(key) not in _CURVE_FACT_KEYS
    }


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
