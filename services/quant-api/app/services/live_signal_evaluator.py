from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.backtest.v1b_jm_tasks import JM_V1B_DATA_SOURCE, JM_V1B_STRATEGY_CODE, JM_V1B_STRATEGY_VERSION, JM_V1B_SYMBOL
from app.core.env import PROJECT_ROOT
from app.schemas.signal import LiveSignalEvaluationItem, LiveSignalEvaluationRequest, LiveSignalEvaluationResponse
from app.services.live_market_reader import LiveMarketReader
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.market_data_reader import MarketDataReader
from app.services.profile_lineage import LONG_HORIZON_DAILY_PROFILE, ProfileLineageResolver
from app.services.signal_lineage import SignalFormalLineageResolver

ENTRY_STATUS = "entry_signal"
NO_SIGNAL_STATUS = "no_signal"
QUANT_CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"


class LiveSignalEvaluator:
    """Read-only live evaluator for explicit JM V1-B observation previews."""

    def __init__(self, session: Session, project_root: Path = PROJECT_ROOT) -> None:
        self.session = session
        self.live_reader = LiveMarketReader(session)
        self.market_reader = MarketDataReader(session, project_root=project_root)

    def preview(self, request: LiveSignalEvaluationRequest) -> LiveSignalEvaluationResponse:
        evaluated_at = datetime.now(UTC).replace(tzinfo=None)
        target = LiveTargetContractResolver(self.session).resolve_ready_actual_contract(
            product=request.symbol,
            requested_contract=request.contract,
        )
        results = [self._evaluate_interval(request, entry_interval, evaluated_at, target) for entry_interval in request.entry_intervals]
        return LiveSignalEvaluationResponse(
            strategy_code=JM_V1B_STRATEGY_CODE,
            strategy_version=JM_V1B_STRATEGY_VERSION,
            symbol=request.symbol,
            contract=target["actual_contract"],
            continuous_contract=target["continuous_contract"],
            actual_contract=target["actual_contract"],
            dominant_mapping_date=target["dominant_mapping_date"],
            evaluated_at=evaluated_at.isoformat(),
            results=results,
            quality_summary={
                "status": _aggregate_status([result.quality.get("status") for result in results]),
                "entry_intervals": {result.entry_interval: result.quality for result in results},
                "preview_only": True,
                "writes_strategy_signal": False,
                "sends_notification": False,
                "auto_order": False,
                "live_target_status": target["readiness_status"],
                "live_target_blocked_reasons": target["blocked_reasons"],
            },
            message=None if results else "live evaluator did not produce preview results",
        )

    def _evaluate_interval(
        self,
        request: LiveSignalEvaluationRequest,
        entry_interval: str,
        evaluated_at: datetime,
        target: dict[str, Any],
    ) -> LiveSignalEvaluationItem:
        _ensure_quant_core_path()
        from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.config_schema import validate_params
        from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy import (
            _bar_datetime,
            _indicator_window,
            _min_intraday_bars,
            calculate_indicators,
            confirmed_daily_direction_snapshot,
            decide_entry,
        )

        params = validate_params(
            {
                **request.strategy_params,
                "entry_interval": entry_interval,
                "max_hold_bars_min": 5,
                "max_hold_bars_max": 8,
                "submit_vnpy_orders": False,
                "pricetick": request.pricetick,
            }
        )
        live_response = self.live_reader.get_bars(
            symbol=request.symbol,
            contract=target["actual_contract"],
            period=entry_interval,
            start=None,
            end=None,
            provider=request.provider,
            source_mode=request.source_mode,
            limit=10000,
        )
        entry_bars = live_response.bars[-request.limit :]
        daily_bars = self.market_reader.load_latest_bars(
            request.symbol,
            JM_V1B_SYMBOL,
            "1d",
            limit=250,
            provider=JM_V1B_DATA_SOURCE,
            data_role="primary",
        )
        daily_quality = _daily_quality(self.market_reader, request.symbol, daily_bars)
        live_quality = live_response.quality.model_dump()
        quality = {
            "status": _aggregate_status([live_quality.get("status"), daily_quality.get("status")]),
            "live": live_quality,
            "daily": daily_quality,
        }
        warnings = _live_warnings(live_quality, entry_bars)
        source = {
            "entry_data_source": "live_db_actual_contract",
            "daily_data_source": "active_standard_parquet_continuous",
            "provider": request.provider,
            "source_mode": request.source_mode,
            "continuous_contract": target["continuous_contract"],
            "actual_contract": target["actual_contract"],
            "dominant_mapping_date": target["dominant_mapping_date"],
            "historical_actual_contract_coverage": target["historical_coverage"],
            "live_coverage": target["live_coverage"],
            "preview_only": True,
            "signal_only": True,
            "auto_order": False,
            "writes_strategy_signal": False,
            "writes_signal_event": False,
            "sends_notification": False,
        }
        if not entry_bars:
            return _item(
                request=request,
                target=target,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction="unavailable",
                no_signal_reason="live_entry_bars_missing",
                quality=quality,
                warnings=warnings,
                source=source,
            )

        last_bar = entry_bars[-1]
        source["bar_status"] = last_bar.get("bar_status")
        bar_time = _bar_datetime(last_bar).isoformat()
        bar_end = bar_time
        blocked_quality = _quality_blocks(live_quality, request.allow_warning_quality, "live") or _quality_blocks(
            daily_quality,
            request.allow_warning_quality,
            "daily",
        )
        if blocked_quality:
            return _item(
                request=request,
                target=target,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
                bar_end=bar_end,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction="unavailable",
                no_signal_reason=blocked_quality,
                quality=quality,
                warnings=warnings,
                source=source,
            )
        if not daily_bars:
            return _item(
                request=request,
                target=target,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
                bar_end=bar_end,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction="unavailable",
                no_signal_reason="daily_data_missing",
                quality=quality,
                warnings=warnings,
                source=source,
            )
        if len(entry_bars) < _min_intraday_bars(params):
            return _item(
                request=request,
                target=target,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
                bar_end=bar_end,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction="unavailable",
                no_signal_reason="entry_bars_insufficient",
                quality=quality,
                warnings=warnings,
                source=source,
            )

        daily = confirmed_daily_direction_snapshot(current_bar=last_bar, daily_bars=daily_bars, params=params)
        if daily.direction not in {"long", "short"}:
            reason = f"daily_direction_blocked|{daily.reason}"
            return _item(
                request=request,
                target=target,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
                bar_end=bar_end,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction=daily.direction,
                entry_reason=reason,
                no_signal_reason=reason,
                quality=quality,
                warnings=warnings,
                source=source,
            )

        recent_bars = entry_bars[-_indicator_window(params) :]
        indicators = calculate_indicators(recent_bars, params)
        decision = decide_entry(recent_bars, indicators, daily, params)
        if decision.direction == "none":
            return _item(
                request=request,
                target=target,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
                bar_end=bar_end,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction=decision.daily_direction,
                entry_reason=decision.entry_reason,
                no_signal_reason=decision.entry_reason,
                quality=quality,
                warnings=warnings,
                source=source,
            )

        trigger_price = _float_or_none(last_bar.get("close"))
        context_asset, context_block = _daily_context_asset(
            self.session,
            reader=self.market_reader,
            symbol=request.symbol,
            continuous_contract=target["continuous_contract"],
            daily_bars=daily_bars,
        )
        if trigger_price is not None and context_block is None:
            bar_end_value = _bar_datetime(last_bar)
            resolution = SignalFormalLineageResolver(self.session).resolve(
                profile_id=request.profile_id,
                symbol=request.symbol,
                continuous_contract=target["continuous_contract"],
                actual_contract=target["actual_contract"],
                period=entry_interval,
                dominant_mapping_date=date.fromisoformat(target["dominant_mapping_date"]),
                bar_start=bar_end_value - _period_delta(entry_interval),
                bar_end=bar_end_value,
                trigger_price=trigger_price,
                source_mode="live_confirmed",
                confirmation={
                    "confirmation_mode": "live_confirmed",
                    "bar_status": last_bar.get("bar_status"),
                    "live_bar_id": last_bar.get("live_bar_id"),
                    "live_bar_revision": last_bar.get("revision"),
                    "confirmed_at": last_bar.get("confirmed_at"),
                },
                context_assets=[context_asset] if context_asset else [],
            )
            if resolution.snapshot is not None:
                source["formal_lineage"] = resolution.snapshot
            else:
                source["formal_lineage_blocked"] = {
                    "code": resolution.blocked_code,
                    "context": resolution.blocked_context,
                }
        elif context_block is not None:
            source["formal_lineage_blocked"] = context_block

        return _item(
            request=request,
            target=target,
            entry_interval=entry_interval,
            evaluated_at=evaluated_at,
            bar_time=bar_time,
            bar_end=bar_end,
            trigger_price=trigger_price,
            status=ENTRY_STATUS,
            direction=decision.direction,
            daily_direction=decision.daily_direction,
            entry_reason=decision.entry_reason,
            no_signal_reason=None,
            stop_loss_price=decision.stop_loss_price,
            quality=quality,
            warnings=warnings,
            source=source,
        )


def _item(
    *,
    request: LiveSignalEvaluationRequest,
    target: dict[str, Any],
    entry_interval: str,
    evaluated_at: datetime,
    status: str,
    direction: str,
    daily_direction: str,
    quality: dict[str, Any],
    warnings: list[str],
    source: dict[str, Any],
    bar_time: str | None = None,
    bar_end: str | None = None,
    trigger_price: float | None = None,
    entry_reason: str | None = None,
    no_signal_reason: str | None = None,
    stop_loss_price: float | None = None,
) -> LiveSignalEvaluationItem:
    reasons = [reason for reason in [entry_reason, no_signal_reason] if reason]
    return LiveSignalEvaluationItem(
        strategy_code=JM_V1B_STRATEGY_CODE,
        strategy_version=JM_V1B_STRATEGY_VERSION,
        symbol=request.symbol,
        contract=target["actual_contract"],
        continuous_contract=target["continuous_contract"],
        actual_contract=target["actual_contract"],
        dominant_mapping_date=target["dominant_mapping_date"],
        entry_interval=entry_interval,
        evaluated_at=evaluated_at.isoformat(),
        bar_time=bar_time,
        bar_end=bar_end,
        trigger_price=trigger_price if status == ENTRY_STATUS else None,
        direction=direction,
        status=status,
        daily_direction=daily_direction,
        entry_reason=entry_reason,
        no_signal_reason=no_signal_reason,
        stop_loss_price=stop_loss_price,
        quality=quality,
        warnings=warnings,
        reasons=reasons,
        source=source,
    )


def _daily_quality(reader: MarketDataReader, symbol: str, daily_bars: list[dict[str, Any]]) -> dict[str, Any]:
    if not daily_bars:
        return {"status": "missing", "report_count": 0}
    return reader.get_quality_status(
        symbol=symbol,
        contract=JM_V1B_SYMBOL,
        period="1d",
        start=daily_bars[0]["datetime"],
        end=daily_bars[-1]["datetime"],
        provider=JM_V1B_DATA_SOURCE,
        data_role="primary",
    )


def _quality_blocks(quality: dict[str, Any], allow_warning_quality: bool, prefix: str) -> str | None:
    status = quality.get("status")
    if status == "failed":
        return f"{prefix}_data_quality_failed"
    if status == "warning" and not allow_warning_quality:
        return f"{prefix}_data_quality_warning_blocked"
    return None


def _live_warnings(quality: dict[str, Any], bars: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if quality.get("status") == "warning":
        warnings.append("live_quality_warning")
    if quality.get("partial_count", 0):
        warnings.append("live_partial_bucket")
    if quality.get("failed_count", 0):
        warnings.append("live_failed_rows_present")
    if quality.get("rejected_count", 0):
        warnings.append("live_rejected_rows_present")
    for bar in bars:
        for reason in bar.get("quality_reasons") or []:
            if reason not in warnings:
                warnings.append(str(reason))
    return warnings


def _aggregate_status(statuses: list[Any]) -> str:
    normalized = {str(status) for status in statuses if status}
    if "failed" in normalized:
        return "failed"
    if "warning" in normalized:
        return "warning"
    if "missing" in normalized:
        return "missing"
    if "unchecked" in normalized:
        return "unchecked"
    return "passed" if normalized else "unchecked"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _period_delta(period: str) -> timedelta:
    return timedelta(minutes=int(period.removesuffix("m")))


def _daily_context_asset(
    session: Session,
    *,
    reader: MarketDataReader,
    symbol: str,
    continuous_contract: str,
    daily_bars: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    lineage = ProfileLineageResolver(session).resolve(
        consumer="signal",
        symbol=symbol,
        contract=continuous_contract,
        period="1d",
        profile_id=LONG_HORIZON_DAILY_PROFILE,
        allow_warning_quality=False,
    )
    context = {
        "profile_id": LONG_HORIZON_DAILY_PROFILE,
        "instrument_symbol": symbol,
        "contract_code": continuous_contract,
        "period": "1d",
    }
    if lineage.blocked or lineage.market_file is None or lineage.market_data_file_id is None:
        return None, {"code": "SIGNAL_CONTEXT_BINDING_MISSING", "context": context}
    market_file = lineage.market_file
    if market_file.quality_status != "passed" or market_file.data_role != "primary":
        return None, {"code": "SIGNAL_CONTEXT_QUALITY_BLOCKED", "context": context}
    if daily_bars:
        start = daily_bars[0]["datetime"].replace(tzinfo=None)
        end = daily_bars[-1]["datetime"].replace(tzinfo=None)
        if market_file.start_time.replace(tzinfo=None) > start or market_file.end_time.replace(tzinfo=None) < end:
            return None, {"code": "SIGNAL_CONTEXT_RANGE_NOT_COVERED", "context": context}
        try:
            bound_bars = reader.load_bars_from_market_file(
                market_data_file_id=market_file.id,
                symbol=symbol,
                contract=continuous_contract,
                period="1d",
                start=start,
                end=end,
                passed_only=True,
                expected_provider=market_file.provider,
                expected_data_role="primary",
                expected_quality_status="passed",
                expected_data_version=market_file.data_version,
                expected_checksum=market_file.checksum,
            )
        except ValueError:
            return None, {"code": "SIGNAL_CONTEXT_FILE_INVALID", "context": context}
        if _bar_window_signature(bound_bars) != _bar_window_signature(daily_bars):
            return None, {"code": "SIGNAL_CONTEXT_BINDING_MISMATCH", "context": context}
    return (
        {
            **(lineage.binding_snapshot or {}),
            "profile_id": lineage.profile_id,
            "market_data_file_id": market_file.id,
            "instrument_symbol": market_file.instrument_symbol,
            "contract_code": market_file.contract_code,
            "period": market_file.period,
            "data_version": lineage.data_version,
            "provider": market_file.provider,
            "data_role": market_file.data_role,
            "quality_status": market_file.quality_status,
            "coverage_start": market_file.start_time.isoformat(),
            "coverage_end": market_file.end_time.isoformat(),
            "checksum": market_file.checksum,
        },
        None,
    )


def _bar_window_signature(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            row.get("datetime").replace(tzinfo=None) if isinstance(row.get("datetime"), datetime) else row.get("datetime"),
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume"),
            row.get("open_interest"),
        )
        for row in rows
    ]


def _ensure_quant_core_path() -> None:
    path = str(Path(QUANT_CORE_ROOT))
    if path not in sys.path:
        sys.path.insert(0, path)
