from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.specs import load_contract_spec
from app.models.backtest import WatchlistItem
from app.models.signal import SignalNotification, SignalScanTask, StrategySignal
from app.queue import get_redis_connection, get_signal_queue
from app.services.batch_backtest import ensure_default_watchlists
from app.services.market_data_reader import MarketDataReader
from app.strategy.su_bing_ema21 import SignalSnapshot, SuBingParams, generate_signals

DEFAULT_PERIODS = ["5m", "15m", "30m", "60m", "1d"]
HIGHER_PERIOD = {"5m": "15m", "15m": "30m", "30m": "60m", "60m": "1d"}
SCAN_SIGNAL_VERSION = "su_bing_ema21:v0"


@dataclass(frozen=True)
class ScanTarget:
    symbol: str
    name: str | None
    contract: str
    exchange_code: str | None
    period: str


def create_signal_scan_task(session: Session, request_payload: dict[str, Any]) -> SignalScanTask:
    ensure_default_watchlists(session)
    periods = request_payload.get("periods") or DEFAULT_PERIODS
    item_count = len(_watchlist_items(session, str(request_payload["watchlist_code"]), request_payload.get("symbols")))
    task = SignalScanTask(
        task_no=f"SIG-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        status="pending",
        progress=0.0,
        watchlist_code=str(request_payload["watchlist_code"]),
        periods=periods,
        total_items=item_count * len(periods),
        request_payload={**request_payload, "periods": periods},
        result_payload={},
    )
    session.add(task)
    session.flush()
    return task


def enqueue_signal_scan_task(task_id: int) -> str:
    from app.tasks.signals import run_signal_scan_task

    redis = get_redis_connection()
    redis.ping()
    queued = get_signal_queue().enqueue(run_signal_scan_task, task_id, job_timeout="2h", result_ttl=86400)
    return queued.id


class SignalScanner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.reader = MarketDataReader(session)

    def run(self, task_id: int) -> dict[str, Any]:
        task = self.session.get(SignalScanTask, task_id)
        if task is None:
            raise ValueError(f"signal scan task not found: {task_id}")
        task.status = "running"
        task.started_at = utc_now()
        self.session.commit()
        self._publish("scan_started", {"task": task_snapshot(task)})
        try:
            result = self._run_task(task)
            task.result_payload = result
            task.status = "partial_failed" if task.failed_items or task.skipped_items else "completed"
            task.progress = 100.0
            task.finished_at = utc_now()
            self.session.commit()
            self._publish("scan_completed", {"task": task_snapshot(task)})
            return result
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)
            task.finished_at = utc_now()
            self.session.commit()
            self._publish("scan_failed", {"task": task_snapshot(task), "error_message": str(exc)})
            raise

    def _run_task(self, task: SignalScanTask) -> dict[str, Any]:
        payload = task.request_payload
        targets = self._targets(payload)
        task.total_items = max(1, len(targets))
        self.session.commit()
        created = changed = skipped = failed = 0
        for target in targets:
            try:
                signal, event = self._scan_one(task, target)
                if signal is None:
                    skipped += 1
                    task.skipped_items += 1
                else:
                    if event == "signal_created":
                        created += 1
                    elif event == "signal_changed":
                        changed += 1
                    task.completed_items += 1
            except Exception as exc:
                failed += 1
                task.failed_items += 1
                self._publish("scan_item_failed", {"task_no": task.task_no, "symbol": target.symbol, "period": target.period, "error_message": str(exc)})
            done = task.completed_items + task.failed_items + task.skipped_items
            task.progress = round(done / max(task.total_items, 1) * 100, 2)
            self.session.commit()
        return {
            "created": created,
            "changed": changed,
            "skipped": skipped,
            "failed": failed,
            "total": task.total_items,
        }

    def _targets(self, payload: dict[str, Any]) -> list[ScanTarget]:
        watchlist_code = str(payload["watchlist_code"])
        selected_symbols = payload.get("symbols")
        periods = payload.get("periods") or DEFAULT_PERIODS
        targets: list[ScanTarget] = []
        for item in _watchlist_items(self.session, watchlist_code, selected_symbols):
            for period in periods:
                coverage = self.reader.get_coverage(symbol=item.symbol, period=period)
                if not coverage:
                    targets.append(
                        ScanTarget(
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
                    ScanTarget(
                        symbol=item.symbol,
                        name=item.name,
                        contract=preferred.contract_code or item.default_contract or f"{item.symbol}.MAIN",
                        exchange_code=item.exchange_code,
                        period=period,
                    )
                )
        return targets

    def _scan_one(self, task: SignalScanTask, target: ScanTarget) -> tuple[StrategySignal | None, str | None]:
        payload = task.request_payload
        limit = 250 if target.period == "1d" else 500
        bars = self.reader.load_latest_bars(target.symbol, target.contract, target.period, limit=limit, provider=payload.get("provider"))
        if not bars:
            return None, None
        last_bar = bars[-1]
        quality = self.reader.get_quality_status(
            symbol=target.symbol,
            contract=target.contract,
            period=target.period,
            start=bars[0]["datetime"],
            end=last_bar["datetime"],
            provider=payload.get("provider"),
        )
        if quality["status"] == "failed" or (quality["status"] == "warning" and not payload.get("allow_warning_quality", False)):
            return None, None
        higher_bars = self._higher_bars(target, last_bar["datetime"], payload.get("provider"))
        snapshot = generate_signals(
            bars,
            higher_timeframe_bars=higher_bars,
            params=SuBingParams(**(payload.get("strategy_params") or {})),
        )[-1]
        risk = self._risk_payload(snapshot, last_bar, payload)
        score = score_signal(snapshot, risk)
        min_bucket = int(payload.get("min_score_bucket", 51))
        dedupe_key = f"{SCAN_SIGNAL_VERSION}:{target.symbol}:{target.contract}:{target.period}:{snapshot.datetime.isoformat()}"
        existing = self.session.scalar(select(StrategySignal).where(StrategySignal.dedupe_key == dedupe_key))
        if existing is None:
            signal = self._make_signal(task, target, snapshot, last_bar, quality, risk, score, dedupe_key)
            self.session.add(signal)
            self.session.flush()
            event = "signal_created"
        else:
            changed = _signal_changed(existing, snapshot, score, risk)
            signal = existing
            _update_signal(signal, task, snapshot, last_bar, quality, risk, score)
            event = "signal_changed" if changed else None
        if event and signal.score_bucket >= min_bucket:
            self._notify(signal, task.task_no, event)
        return signal, event

    def _higher_bars(self, target: ScanTarget, current_time: datetime, provider: str | None) -> list[dict[str, Any]]:
        higher_period = HIGHER_PERIOD.get(target.period)
        if higher_period is None:
            return []
        rows = self.reader.load_latest_bars(target.symbol, target.contract, higher_period, limit=250, provider=provider)
        return [row for row in rows if row["datetime"] <= current_time]

    def _risk_payload(self, snapshot: SignalSnapshot, bar: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        spec = load_contract_spec(self.session, str(bar["symbol"]), str(bar["contract"]))
        direction = snapshot.direction
        entry = float(bar["close"])
        atr = float(snapshot.features.get("atr") or 0.0)
        prior_high = snapshot.features.get("prior_high")
        prior_low = snapshot.features.get("prior_low")
        if direction == "long":
            stop = _float_or_none(prior_low) or (entry - max(2 * atr, spec.price_tick))
            target = entry + 2 * abs(entry - stop)
        elif direction == "short":
            stop = _float_or_none(prior_high) or (entry + max(2 * atr, spec.price_tick))
            target = entry - 2 * abs(entry - stop)
        else:
            stop = None
            target = None
        account_equity = float(payload.get("account_equity", 100000.0))
        risk_pct = float(payload.get("risk_per_trade_pct", 0.01))
        max_margin_pct = float(payload.get("max_margin_usage_pct", 0.35))
        risk_budget = account_equity * risk_pct
        risk_per_lot = abs(entry - stop) * spec.volume_multiple if stop is not None else 0.0
        risk_volume = floor(risk_budget / risk_per_lot) if risk_per_lot > 0 else 0
        margin_per_lot = entry * spec.volume_multiple * spec.margin_rate
        margin_volume = floor(account_equity * max_margin_pct / margin_per_lot) if margin_per_lot > 0 else 0
        open_volume = max(0, min(risk_volume, margin_volume))
        margin_required = open_volume * margin_per_lot
        risk_amount = open_volume * risk_per_lot
        return {
            "entry_price": entry,
            "target_price": target,
            "stop_loss_price": stop,
            "risk_reward_ratio": None if stop is None or target is None or abs(entry - stop) <= 0 else abs(target - entry) / abs(entry - stop),
            "open_volume": open_volume,
            "margin_required": margin_required,
            "risk_amount": risk_amount,
            "account_equity": account_equity,
            "spec_source": spec.source,
        }

    def _make_signal(
        self,
        task: SignalScanTask,
        target: ScanTarget,
        snapshot: SignalSnapshot,
        bar: dict[str, Any],
        quality: dict[str, Any],
        risk: dict[str, Any],
        score: dict[str, Any],
        dedupe_key: str,
    ) -> StrategySignal:
        return StrategySignal(
            task_no=task.task_no,
            dedupe_key=dedupe_key,
            watchlist_code=task.watchlist_code,
            symbol=target.symbol,
            contract=target.contract,
            exchange=bar.get("exchange") or target.exchange_code,
            period=target.period,
            signal_time=snapshot.datetime,
            status=snapshot.status,
            direction=snapshot.direction,
            signal_level=int(snapshot.signal_level),
            score_bucket=score["bucket"],
            bucket_label=score["label"],
            current_price=float(bar["close"]),
            target_price=risk["target_price"],
            stop_loss_price=risk["stop_loss_price"],
            risk_reward_ratio=risk["risk_reward_ratio"],
            open_volume=risk["open_volume"],
            margin_required=risk["margin_required"],
            risk_amount=risk["risk_amount"],
            account_equity=risk["account_equity"],
            reasons=snapshot.reasons,
            features=snapshot.features,
            quality_status=quality,
            research_contract=target.contract.endswith(".MAIN"),
            spec_source=risk["spec_source"],
        )

    def _notify(self, signal: StrategySignal, task_no: str, event_type: str) -> None:
        payload = signal_payload(signal)
        notification = SignalNotification(
            signal_id=signal.id,
            task_no=task_no,
            dedupe_key=f"{event_type}:{signal.dedupe_key}:{signal.score_bucket}:{signal.status}",
            event_type=event_type,
            channel="websocket",
            status="sent",
            payload=payload,
            sent_at=utc_now(),
        )
        self.session.add(notification)
        self._publish(event_type, payload)

    @staticmethod
    def _publish(event_type: str, payload: dict[str, Any]) -> None:
        try:
            get_redis_connection().publish("signals", json.dumps({"type": event_type, "data": payload}, default=str, ensure_ascii=False))
        except Exception:
            return


def task_snapshot(task: SignalScanTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_no": task.task_no,
        "status": task.status,
        "progress": task.progress,
        "watchlist_code": task.watchlist_code,
        "periods": task.periods,
        "total_items": task.total_items,
        "completed_items": task.completed_items,
        "failed_items": task.failed_items,
        "skipped_items": task.skipped_items,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "result_payload": task.result_payload,
    }


def signal_payload(signal: StrategySignal) -> dict[str, Any]:
    return {
        "id": signal.id,
        "task_no": signal.task_no,
        "strategy_name": signal.strategy_name,
        "strategy_version": signal.strategy_version,
        "watchlist_code": signal.watchlist_code,
        "symbol": signal.symbol,
        "contract": signal.contract,
        "exchange": signal.exchange,
        "period": signal.period,
        "signal_time": signal.signal_time.isoformat(),
        "status": signal.status,
        "direction": signal.direction,
        "signal_level": signal.signal_level,
        "score_bucket": signal.score_bucket,
        "bucket_label": signal.bucket_label,
        "current_price": signal.current_price,
        "target_price": signal.target_price,
        "stop_loss_price": signal.stop_loss_price,
        "risk_reward_ratio": signal.risk_reward_ratio,
        "open_volume": signal.open_volume,
        "margin_required": signal.margin_required,
        "risk_amount": signal.risk_amount,
        "account_equity": signal.account_equity,
        "reasons": signal.reasons,
        "features": signal.features,
        "quality_status": signal.quality_status,
        "research_contract": signal.research_contract,
        "spec_source": signal.spec_source,
        "alert_status": signal.alert_status,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "updated_at": signal.updated_at.isoformat() if signal.updated_at else None,
    }


def score_signal(snapshot: SignalSnapshot, risk: dict[str, Any]) -> dict[str, Any]:
    score = int(snapshot.signal_level or 0)
    features = snapshot.features
    if features.get("volume_ratio") and float(features["volume_ratio"]) >= 1.5:
        score += 5
    if features.get("higher_timeframe_resonance") is True:
        score += 8
    if risk.get("risk_reward_ratio") and float(risk["risk_reward_ratio"]) >= 1.8:
        score += 6
    if snapshot.trade_intent.get("action") in {"trial_entry", "confirm_entry", "add_watch"}:
        score += 4
    if snapshot.direction == "neutral":
        score = min(score, 50)
    score = max(0, min(100, score))
    bucket = 80 if score >= 80 else 70 if score >= 70 else 60 if score >= 60 else 51 if score >= 51 else 0
    label = {80: "重点关注", 70: "强信号", 60: "有效", 51: "观察", 0: "过滤"}[bucket]
    return {"score": score, "bucket": bucket, "label": label}


def _update_signal(
    signal: StrategySignal,
    task: SignalScanTask,
    snapshot: SignalSnapshot,
    bar: dict[str, Any],
    quality: dict[str, Any],
    risk: dict[str, Any],
    score: dict[str, Any],
) -> None:
    signal.task_no = task.task_no
    signal.status = snapshot.status
    signal.direction = snapshot.direction
    signal.signal_level = int(snapshot.signal_level)
    signal.score_bucket = score["bucket"]
    signal.bucket_label = score["label"]
    signal.current_price = float(bar["close"])
    signal.target_price = risk["target_price"]
    signal.stop_loss_price = risk["stop_loss_price"]
    signal.risk_reward_ratio = risk["risk_reward_ratio"]
    signal.open_volume = risk["open_volume"]
    signal.margin_required = risk["margin_required"]
    signal.risk_amount = risk["risk_amount"]
    signal.account_equity = risk["account_equity"]
    signal.reasons = snapshot.reasons
    signal.features = snapshot.features
    signal.quality_status = quality
    signal.spec_source = risk["spec_source"]
    signal.updated_at = utc_now()


def _signal_changed(existing: StrategySignal, snapshot: SignalSnapshot, score: dict[str, Any], risk: dict[str, Any]) -> bool:
    return (
        existing.status != snapshot.status
        or existing.direction != snapshot.direction
        or existing.score_bucket != score["bucket"]
        or existing.open_volume != risk["open_volume"]
    )


def _watchlist_items(session: Session, watchlist_code: str, symbols: list[str] | None = None) -> list[WatchlistItem]:
    selected = set(symbols or [])
    query = (
        select(WatchlistItem)
        .where(WatchlistItem.watchlist_code == watchlist_code, WatchlistItem.is_active.is_(True))
        .order_by(WatchlistItem.sort_order, WatchlistItem.symbol)
    )
    rows = list(session.scalars(query))
    return [row for row in rows if not selected or row.symbol in selected]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def utc_now() -> datetime:
    return datetime.now(UTC)
