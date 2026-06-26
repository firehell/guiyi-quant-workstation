from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.backtest import WatchlistItem
from app.models.signal import SignalScanTask, StrategySignal
from app.queue import get_redis_connection, get_signal_queue
from app.schemas.signal import SignalDataRole, SignalStatus
from app.services import signal_scanner as legacy

DEFAULT_PERIODS = legacy.DEFAULT_PERIODS
SIGNAL_STATUS_VALUES = {item.value for item in SignalStatus}


class SignalScanner(legacy.SignalScanner):
    """Research-only signal scanner with explicit data-role boundaries."""

    def _targets(self, payload: dict[str, Any]) -> list[legacy.ScanTarget]:
        watchlist_code = str(payload["watchlist_code"])
        selected_symbols = payload.get("symbols")
        periods = payload.get("periods") or DEFAULT_PERIODS
        data_role = str(payload.get("data_role") or SignalDataRole.PRIMARY.value)
        provider = payload.get("provider")
        targets: list[legacy.ScanTarget] = []
        for item in _watchlist_items(self.session, watchlist_code, selected_symbols):
            for period in periods:
                coverage = [
                    row
                    for row in self.reader.get_coverage(symbol=item.symbol, period=period)
                    if row.data_role == data_role and row.quality_status != "failed" and (provider is None or row.provider == provider)
                ]
                if not coverage:
                    targets.append(
                        legacy.ScanTarget(
                            symbol=item.symbol,
                            name=item.name,
                            contract=item.default_contract or f"{item.symbol}.MAIN",
                            exchange_code=item.exchange_code,
                            period=period,
                        )
                    )
                    continue
                preferred = next((row for row in coverage if row.contract_code == item.default_contract), coverage[-1])
                targets.append(
                    legacy.ScanTarget(
                        symbol=item.symbol,
                        name=item.name,
                        contract=preferred.contract_code or item.default_contract or f"{item.symbol}.MAIN",
                        exchange_code=item.exchange_code,
                        period=period,
                    )
                )
        return targets


def create_signal_scan_task(session: Session, request_payload: dict[str, Any]) -> SignalScanTask:
    payload = {
        **request_payload,
        "data_role": str(request_payload.get("data_role") or SignalDataRole.PRIMARY.value),
        "research_only": bool(request_payload.get("research_only", False)),
    }
    task = legacy.create_signal_scan_task(session, payload)
    task.request_payload = payload
    return task


def enqueue_signal_scan_task(task_id: int) -> str:
    redis = get_redis_connection()
    redis.ping()
    queued = get_signal_queue().enqueue(run_signal_scan_task, task_id, job_timeout="2h", result_ttl=86400)
    return queued.id


def run_signal_scan_task(task_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        return SignalScanner(session).run(task_id)


def task_snapshot(task: SignalScanTask) -> dict[str, Any]:
    payload = legacy.task_snapshot(task)
    request_payload = task.request_payload or {}
    payload["data_role"] = str(request_payload.get("data_role") or SignalDataRole.PRIMARY.value)
    payload["research_only"] = bool(request_payload.get("research_only", False))
    return payload


def signal_payload(signal: StrategySignal) -> dict[str, Any]:
    payload = legacy.signal_payload(signal)
    features = dict(signal.features or {})
    strategy_status = signal.status
    lifecycle_status = _lifecycle_status(signal)
    signal_type = _signal_type(strategy_status, signal.direction)
    reasons = list(signal.reasons or [])
    data_role = str(features.get("data_role") or SignalDataRole.PRIMARY.value)
    payload.update(
        {
            "strategy_id": signal.strategy_name,
            "strategy_version_id": signal.strategy_version,
            "interval": signal.period,
            "signal_type": signal_type,
            "price": signal.current_price,
            "strength_score": signal.score_bucket,
            "reason": "；".join(reasons),
            "status": lifecycle_status,
            "strategy_status": strategy_status,
            "data_role": data_role,
            "research_only": data_role != SignalDataRole.PRIMARY.value or bool(features.get("research_only", False)),
        }
    )
    return payload


def update_signal_status(session: Session, signal_id: int, status: SignalStatus) -> StrategySignal:
    signal = session.get(StrategySignal, signal_id)
    if signal is None:
        raise ValueError("signal not found")
    features = dict(signal.features or {})
    features["signal_status"] = status.value
    signal.features = features
    signal.alert_status = "acknowledged" if status is SignalStatus.VIEWED else status.value
    signal.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(signal)
    return signal


def _lifecycle_status(signal: StrategySignal) -> str:
    features = signal.features or {}
    feature_status = features.get("signal_status")
    if isinstance(feature_status, str) and feature_status in SIGNAL_STATUS_VALUES:
        return feature_status
    if signal.alert_status == "acknowledged":
        return SignalStatus.VIEWED.value
    if signal.alert_status in SIGNAL_STATUS_VALUES:
        return signal.alert_status
    return SignalStatus.NEW.value


def _signal_type(strategy_status: str, direction: str) -> str:
    if "平" in strategy_status or "减" in strategy_status:
        return "exit_setup"
    if "开" in strategy_status or "试" in strategy_status:
        return "entry_setup"
    if "观察" in strategy_status:
        return "watch"
    if direction in {"long", "short"}:
        return "trend_signal"
    return "neutral"


def _watchlist_items(session: Session, watchlist_code: str, symbols: list[str] | None = None) -> list[WatchlistItem]:
    selected = set(symbols or [])
    query = (
        select(WatchlistItem)
        .where(WatchlistItem.watchlist_code == watchlist_code, WatchlistItem.is_active.is_(True))
        .order_by(WatchlistItem.sort_order, WatchlistItem.symbol)
    )
    rows = list(session.scalars(query))
    return [row for row in rows if not selected or row.symbol in selected]
