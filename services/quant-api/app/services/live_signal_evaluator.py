from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.backtest.v1b_jm_tasks import JM_V1B_DATA_SOURCE, JM_V1B_STRATEGY_CODE, JM_V1B_STRATEGY_VERSION, JM_V1B_SYMBOL
from app.core.env import PROJECT_ROOT
from app.schemas.signal import LiveSignalEvaluationItem, LiveSignalEvaluationRequest, LiveSignalEvaluationResponse
from app.services.live_market_reader import LiveMarketReader
from app.services.market_data_reader import MarketDataReader

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
        results = [self._evaluate_interval(request, entry_interval, evaluated_at) for entry_interval in request.entry_intervals]
        return LiveSignalEvaluationResponse(
            strategy_code=JM_V1B_STRATEGY_CODE,
            strategy_version=JM_V1B_STRATEGY_VERSION,
            symbol=request.symbol,
            contract=request.contract,
            evaluated_at=evaluated_at.isoformat(),
            results=results,
            quality_summary={
                "status": _aggregate_status([result.quality.get("status") for result in results]),
                "entry_intervals": {result.entry_interval: result.quality for result in results},
                "preview_only": True,
                "writes_strategy_signal": False,
                "sends_notification": False,
                "auto_order": False,
            },
            message=None if results else "live evaluator did not produce preview results",
        )

    def _evaluate_interval(
        self,
        request: LiveSignalEvaluationRequest,
        entry_interval: str,
        evaluated_at: datetime,
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
            contract=request.contract,
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
            "entry_data_source": "live_db",
            "daily_data_source": "active_standard_parquet",
            "provider": request.provider,
            "source_mode": request.source_mode,
            "preview_only": True,
            "signal_only": True,
            "auto_order": False,
        }
        if not entry_bars:
            return _item(
                request=request,
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
        bar_time = _bar_datetime(last_bar).isoformat()
        blocked_quality = _quality_blocks(live_quality, request.allow_warning_quality, "live") or _quality_blocks(
            daily_quality,
            request.allow_warning_quality,
            "daily",
        )
        if blocked_quality:
            return _item(
                request=request,
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
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
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
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
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
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
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
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
                entry_interval=entry_interval,
                evaluated_at=evaluated_at,
                bar_time=bar_time,
                status=NO_SIGNAL_STATUS,
                direction="neutral",
                daily_direction=decision.daily_direction,
                entry_reason=decision.entry_reason,
                no_signal_reason=decision.entry_reason,
                quality=quality,
                warnings=warnings,
                source=source,
            )

        return _item(
            request=request,
            entry_interval=entry_interval,
            evaluated_at=evaluated_at,
            bar_time=bar_time,
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
    entry_interval: str,
    evaluated_at: datetime,
    status: str,
    direction: str,
    daily_direction: str,
    quality: dict[str, Any],
    warnings: list[str],
    source: dict[str, Any],
    bar_time: str | None = None,
    entry_reason: str | None = None,
    no_signal_reason: str | None = None,
    stop_loss_price: float | None = None,
) -> LiveSignalEvaluationItem:
    reasons = [reason for reason in [entry_reason, no_signal_reason] if reason]
    return LiveSignalEvaluationItem(
        strategy_code=JM_V1B_STRATEGY_CODE,
        strategy_version=JM_V1B_STRATEGY_VERSION,
        symbol=request.symbol,
        contract=request.contract,
        entry_interval=entry_interval,
        evaluated_at=evaluated_at.isoformat(),
        bar_time=bar_time,
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


def _ensure_quant_core_path() -> None:
    path = str(Path(QUANT_CORE_ROOT))
    if path not in sys.path:
        sys.path.insert(0, path)
