from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.v1b_jm_tasks import JM_V1B_DATA_SOURCE, JM_V1B_EXCHANGE, JM_V1B_STRATEGY_CODE, JM_V1B_STRATEGY_VERSION, JM_V1B_SYMBOL
from app.core.env import PROJECT_ROOT
from app.models.signal import SignalScanTask, StrategySignal
from app.signal.contract_context import apply_signal_contract_context, build_signal_contract_context
from app.services.market_data_reader import MarketDataReader

QUANT_CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
JM_V1B_WATCHLIST_CODE = "jm_v1b"
JM_V1B_SCAN_PERIODS = ["15m", "5m"]
JM_V1B_SIGNAL_VERSION = f"{JM_V1B_STRATEGY_CODE}:{JM_V1B_STRATEGY_VERSION}"
ENTRY_STATUS = "entry_signal"
NO_SIGNAL_STATUS = "no_signal"


def scan_jm_v1b_signal(
    session: Session,
    reader: MarketDataReader,
    task: SignalScanTask,
    target_period: str,
) -> tuple[StrategySignal | None, str | None]:
    _ensure_quant_core_path()
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.config_schema import validate_params
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy import (
        _indicator_window,
        _min_intraday_bars,
        calculate_indicators,
        confirmed_daily_direction_snapshot,
        decide_entry,
    )

    payload = task.request_payload or {}
    data_role = str(payload.get("data_role") or "primary")
    provider = payload.get("provider")
    params = validate_params(
        {
            **(payload.get("strategy_params") or {}),
            "entry_interval": target_period,
            "max_hold_bars_min": 5,
            "max_hold_bars_max": 8,
            "submit_vnpy_orders": False,
            "pricetick": float(payload.get("pricetick", 0.5)),
        }
    )

    entry_bars = reader.load_latest_bars("jm", JM_V1B_SYMBOL, target_period, limit=500, provider=provider, data_role=data_role)
    if not entry_bars:
        return None, None
    daily_bars = reader.load_latest_bars("jm", JM_V1B_SYMBOL, "1d", limit=250, provider=provider, data_role=data_role)
    last_bar = entry_bars[-1]
    quality = _quality(reader, target_period, entry_bars, provider, data_role)
    daily_quality = _quality(reader, "1d", daily_bars, provider, data_role) if daily_bars else {"status": "missing", "report_count": 0}
    signal_time = _bar_datetime(last_bar)

    decision_payload: dict[str, Any]
    reasons: list[str]
    status = NO_SIGNAL_STATUS
    direction = "neutral"
    stop_loss_price: float | None = None
    daily_direction = "unavailable"
    entry_reason = ""

    blocked_quality = _quality_blocks(quality, payload) or _quality_blocks(daily_quality, payload)
    if blocked_quality:
        reasons = [blocked_quality]
        decision_payload = {"no_signal_reason": blocked_quality}
        entry_reason = blocked_quality
    elif len(daily_bars) == 0:
        reasons = ["no_signal: daily_data_missing"]
        decision_payload = {"no_signal_reason": "daily_data_missing"}
        entry_reason = "daily_data_missing"
    elif len(entry_bars) < _min_intraday_bars(params):
        reasons = ["no_signal: entry_bars_insufficient"]
        decision_payload = {"no_signal_reason": "entry_bars_insufficient"}
        entry_reason = "entry_bars_insufficient"
    else:
        daily = confirmed_daily_direction_snapshot(current_bar=last_bar, daily_bars=daily_bars, params=params)
        daily_direction = daily.direction
        if daily.direction not in {"long", "short"}:
            reasons = [f"no_signal: daily_direction_blocked|{daily.reason}"]
            decision_payload = {"no_signal_reason": f"daily_direction_blocked|{daily.reason}"}
            entry_reason = f"daily_direction_blocked|{daily.reason}"
        else:
            recent_bars = entry_bars[-_indicator_window(params) :]
            indicators = calculate_indicators(recent_bars, params)
            decision = decide_entry(recent_bars, indicators, daily, params)
            daily_direction = decision.daily_direction
            entry_reason = decision.entry_reason
            if decision.direction == "none":
                reasons = [f"no_signal: {decision.entry_reason}"]
                decision_payload = {"no_signal_reason": decision.entry_reason}
            else:
                status = ENTRY_STATUS
                direction = decision.direction
                stop_loss_price = decision.stop_loss_price
                reasons = [decision.entry_reason, f"daily_direction={decision.daily_direction}", "signal_only_no_order"]
                decision_payload = {"no_signal_reason": None}

    features = {
        **decision_payload,
        "product": "jm",
        "continuous_contract": JM_V1B_SYMBOL,
        "strategy_code": JM_V1B_STRATEGY_CODE,
        "strategy_version": JM_V1B_STRATEGY_VERSION,
        "entry_interval": target_period,
        "signal_price": float(last_bar["close"]),
        "daily_direction": daily_direction,
        "entry_reason": entry_reason,
        "stop_loss_price": stop_loss_price,
        "max_hold_bars": params.max_hold_bars_max,
        "max_hold_bars_min": params.max_hold_bars_min,
        "max_hold_bars_max": params.max_hold_bars_max,
        "status": status,
        "data_role": data_role,
        "data_provider": JM_V1B_DATA_SOURCE,
        "source": "historical_standard_parquet",
        "research_only": False,
        "signal_only": True,
        "auto_order": False,
        "daily_quality": daily_quality,
    }
    score_bucket = 70 if status == ENTRY_STATUS else 0
    dedupe_key = f"{JM_V1B_SIGNAL_VERSION}:{JM_V1B_SYMBOL}:{target_period}:{signal_time.isoformat()}"
    existing = session.scalar(select(StrategySignal).where(StrategySignal.dedupe_key == dedupe_key))
    if existing is None:
        signal = StrategySignal(
            task_no=task.task_no,
            dedupe_key=dedupe_key,
            strategy_name=JM_V1B_STRATEGY_CODE,
            strategy_version=JM_V1B_STRATEGY_VERSION,
            watchlist_code=JM_V1B_WATCHLIST_CODE,
            symbol="jm",
            contract=JM_V1B_SYMBOL,
            exchange=JM_V1B_EXCHANGE,
            period=target_period,
            signal_time=signal_time,
            status=status,
            direction=direction,
            signal_level=score_bucket,
            score_bucket=score_bucket,
            bucket_label="入场提醒" if status == ENTRY_STATUS else "无信号",
            current_price=float(last_bar["close"]),
            target_price=None,
            stop_loss_price=stop_loss_price,
            risk_reward_ratio=None,
            open_volume=0,
            margin_required=0.0,
            risk_amount=0.0,
            account_equity=float(payload.get("account_equity", 100000.0)),
            reasons=reasons,
            features=features,
            quality_status=quality,
            research_contract=True,
            spec_source="jm_v1b_registered_formal_data",
        )
        _apply_jm_contract_context(signal, target_period, signal_time, float(last_bar["close"]), features, quality)
        session.add(signal)
        session.flush()
        return signal, "signal_created"

    changed = _jm_signal_changed(existing, status, direction, stop_loss_price, features, reasons)
    _update_jm_signal(existing, task, status, direction, score_bucket, last_bar, stop_loss_price, reasons, features, quality)
    return existing, "signal_changed" if changed else None


def _quality(reader: MarketDataReader, period: str, bars: list[dict[str, Any]], provider: str | None, data_role: str) -> dict[str, Any]:
    if not bars:
        return {"status": "missing", "report_count": 0}
    return reader.get_quality_status(
        symbol="jm",
        contract=JM_V1B_SYMBOL,
        period=period,
        start=bars[0]["datetime"],
        end=bars[-1]["datetime"],
        provider=provider,
        data_role=data_role,
    )


def _quality_blocks(quality: dict[str, Any], payload: dict[str, Any]) -> str | None:
    status = quality.get("status")
    if status == "failed":
        return "data_quality_failed"
    if status == "warning" and not payload.get("allow_warning_quality", False):
        return "data_quality_warning_blocked"
    return None


def _update_jm_signal(
    signal: StrategySignal,
    task: SignalScanTask,
    status: str,
    direction: str,
    score_bucket: int,
    bar: dict[str, Any],
    stop_loss_price: float | None,
    reasons: list[str],
    features: dict[str, Any],
    quality: dict[str, Any],
) -> None:
    signal.task_no = task.task_no
    signal.status = status
    signal.direction = direction
    signal.signal_level = score_bucket
    signal.score_bucket = score_bucket
    signal.bucket_label = "入场提醒" if status == ENTRY_STATUS else "无信号"
    signal.current_price = float(bar["close"])
    signal.stop_loss_price = stop_loss_price
    signal.reasons = reasons
    signal.features = features
    signal.quality_status = quality
    _apply_jm_contract_context(signal, signal.period, signal.signal_time, float(bar["close"]), features, quality)
    signal.updated_at = datetime.now(UTC)


def _jm_signal_changed(
    existing: StrategySignal,
    status: str,
    direction: str,
    stop_loss_price: float | None,
    features: dict[str, Any],
    reasons: list[str],
) -> bool:
    return (
        existing.status != status
        or existing.direction != direction
        or existing.stop_loss_price != stop_loss_price
        or existing.features != features
        or existing.reasons != reasons
    )


def _bar_datetime(bar: dict[str, Any]) -> datetime:
    value = bar["datetime"]
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


def _apply_jm_contract_context(
    signal: StrategySignal,
    period: str,
    signal_time: datetime,
    current_price: float,
    features: dict[str, Any],
    quality: dict[str, Any],
) -> None:
    apply_signal_contract_context(
        signal,
        build_signal_contract_context(
            symbol=signal.symbol,
            contract=signal.contract,
            period=period,
            signal_time=signal_time,
            current_price=current_price,
            features=features,
            quality_status=quality,
            research_contract=signal.research_contract,
            provider=JM_V1B_DATA_SOURCE,
            data_role=features.get("data_role"),
        ),
    )


def _ensure_quant_core_path() -> None:
    path = str(Path(QUANT_CORE_ROOT))
    if path not in sys.path:
        sys.path.insert(0, path)
