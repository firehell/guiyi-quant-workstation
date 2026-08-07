from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.data_core.consumer_identity import build_canonical_consumer_input
from app.data_core.contracts import BarQuery, DatasetKind, parse_bar_frequency
from app.models.watchlist import WatchlistItem
from app.models.signal import SignalScanTask, StrategySignal
from app.queue import get_redis_connection, get_signal_queue
from app.schemas.signal import (
    FORMAL_SIGNAL_AUXILIARY_PERIOD,
    FORMAL_SIGNAL_EXECUTION_CONTRACT,
    SignalDataRole,
    SignalScanMode,
    SignalScanRequest,
    SignalStatus,
    build_formal_signal_task_payload,
    validate_formal_signal_task_payload,
)
from app.services.actual_contract_semantics import load_strict_main_contract_mapping
from app.services.canonical_market_data import build_canonical_reader
from app.services.contract_specs import load_contract_spec
from app.services.market_data_service import MarketDataService
from app.services.watchlists import ensure_default_watchlists
from app.signal.contract_context import (
    apply_signal_contract_context,
    build_signal_contract_context,
    signal_contract_context_payload,
)
from app.strategy.su_bing_ema21 import SignalSnapshot, SuBingParams, generate_signals

DEFAULT_PERIODS = ["5m", "15m", "30m", "60m", "1d"]
SCAN_SIGNAL_VERSION = "su_bing_ema21:v0"
SIGNAL_STATUS_VALUES = {item.value for item in SignalStatus}
LEGACY_SIGNAL_EXECUTION_CONTRACT = "legacy_research_scan_v1"
FORMAL_SIGNAL_ROUTING_MARKERS = frozenset(
    {
        "request_payload_sha256",
        "dataset_kind",
        "instrument_symbol",
        "contract_or_series",
        "start",
        "end",
        "strategy_code",
        "strategy_version",
        "observation_only",
        "not_trading_instruction",
        "auto_order",
    }
)


@dataclass(frozen=True)
class ScanTarget:
    symbol: str
    name: str | None
    contract: str
    exchange_code: str | None
    period: str


class SignalScanner:
    """Historical scanner with one canonical formal execution path."""

    def __init__(
        self,
        session: Session,
        *,
        canonical_market_data: MarketDataService | None = None,
    ) -> None:
        self.session = session
        self.reader = None
        self._canonical_market_data = canonical_market_data
        self._formal_blocked_items: list[dict[str, Any]] = []
        self._formal_evaluations: list[dict[str, Any]] = []
        self._formal_execution = False

    def run(self, task_id: int) -> dict[str, Any]:
        task = self.session.get(SignalScanTask, task_id)
        if task is None:
            raise ValueError(f"signal scan task not found: {task_id}")
        self._formal_execution = _is_formal_task_payload(task.request_payload)
        if self._formal_execution:
            _validate_formal_task(task)
        if not self._formal_execution:
            raise ValueError("SIGNAL_LEGACY_EXECUTION_RETIRED")
        task.status = "running"
        task.started_at = utc_now()
        self.session.commit()
        self._publish("scan_started", {"task": task_snapshot(task)})
        try:
            try:
                result = self._run_task(task)
                task.result_payload = result
                task.status = (
                    "partial_failed"
                    if task.failed_items or task.skipped_items
                    else "completed"
                )
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
                self._publish(
                    "scan_failed",
                    {"task": task_snapshot(task), "error_message": str(exc)},
                )
                raise
        finally:
            self._formal_execution = False

    def preview(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        request = SignalScanRequest.model_validate(request_payload)
        if request.mode is SignalScanMode.SCAN:
            raise ValueError("SIGNAL_SCAN_MODE_REQUIRES_PERSISTED_TASK")
        payload = {
            **request.model_dump(mode="json"),
            "data_role": SignalDataRole.PRIMARY.value,
            "research_only": False,
        }
        task = SignalScanTask(
            task_no=f"SIG-PREVIEW-{uuid4().hex}",
            status="preview",
            progress=0.0,
            watchlist_code=request.watchlist_code,
            periods=list(request.periods),
            total_items=len(request.periods),
            request_payload=payload,
            result_payload={},
            profile_id=None,
            market_data_file_id=None,
        )
        self._formal_execution = True
        self._formal_blocked_items = []
        self._formal_evaluations = []
        try:
            for target in self._targets(payload):
                self._scan_one(task, target)
        finally:
            self._formal_execution = False
        return {
            "mode": request.mode.value,
            "evaluations": deepcopy(self._formal_evaluations),
            "blocked_items": deepcopy(self._formal_blocked_items),
            "created": 0,
            "changed": 0,
            "skipped": 0,
            "failed": 0,
            "total": len(request.periods),
        }

    def _publish(self, event: str, payload: dict[str, Any]) -> None:
        if self._formal_execution:
            return
        try:
            get_redis_connection().publish(
                "signals",
                json.dumps(
                    {"type": event, "data": payload},
                    default=str,
                    ensure_ascii=False,
                ),
            )
        except Exception:
            return

    def _run_task(self, task: SignalScanTask) -> dict[str, Any]:
        self._formal_blocked_items = []
        self._formal_evaluations = []
        payload = task.request_payload or {}
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
                    if event:
                        from app.signal.events import record_signal_scan_event

                        record_signal_scan_event(self.session, signal, event, task)
                    task.completed_items += 1
            except Exception as exc:
                failed += 1
                task.failed_items += 1
                self._publish(
                    "scan_item_failed",
                    {
                        "task_no": task.task_no,
                        "symbol": target.symbol,
                        "period": target.period,
                        "error_message": str(exc),
                    },
                )
            done = task.completed_items + task.failed_items + task.skipped_items
            task.progress = round(done / max(task.total_items, 1) * 100, 2)
            self.session.commit()
        return {
            "created": created,
            "changed": changed,
            "skipped": skipped,
            "failed": failed,
            "total": task.total_items,
            "mode": str(payload.get("mode") or SignalScanMode.SCAN.value),
            "evaluations": deepcopy(self._formal_evaluations),
            "blocked_items": list(self._formal_blocked_items),
        }

    def _targets(self, payload: dict[str, Any]) -> list[ScanTarget]:
        if payload.get("research_only"):
            raise ValueError("SIGNAL_LEGACY_EXECUTION_RETIRED")
        return [
            ScanTarget(
                symbol=str(payload["instrument_symbol"]).lower(),
                name=None,
                contract=str(payload["contract_or_series"]).upper(),
                exchange_code="DCE",
                period=str(period),
            )
            for period in payload["periods"]
        ]

    def _scan_one(
        self, task: SignalScanTask, target: ScanTarget
    ) -> tuple[StrategySignal | None, str | None]:
        payload = task.request_payload or {}
        if payload.get("research_only"):
            raise ValueError("SIGNAL_LEGACY_EXECUTION_RETIRED")
        query, result, input_identity = self._canonical_bars(payload, target.period)
        bars = [
            _canonical_bar_payload(item, exchange=target.exchange_code)
            for item in result.bars
        ]
        if not bars:
            return None, None
        higher_bars: list[dict[str, Any]] = []
        auxiliary_identities: dict[str, dict[str, object]] = {}
        canonical_results = [result]
        higher_period = FORMAL_SIGNAL_AUXILIARY_PERIOD.get(target.period)
        if higher_period is not None:
            _, higher_result, higher_identity = self._canonical_bars(
                payload, higher_period
            )
            canonical_results.append(higher_result)
            higher_bars = [
                _canonical_bar_payload(item, exchange=target.exchange_code)
                for item in higher_result.bars
                if item.bar_end <= result.bars[-1].bar_end
            ]
            auxiliary_identities[higher_period] = higher_identity
        _validate_actual_dominant_mapping_provenance(
            self.session,
            canonical_results,
        )
        snapshot = generate_signals(
            bars,
            higher_timeframe_bars=higher_bars,
            params=SuBingParams(**(payload.get("strategy_params") or {})),
        )[-1]
        last_bar = bars[-1]
        quality = {
            "status": "passed",
            "provider": "rqdata",
            "canonical_consumer_input_digest": input_identity["digest"],
        }
        risk = self._risk_payload(
            snapshot,
            {**last_bar, "close": result.bars[-1].close},
            payload,
        )
        score = score_signal(snapshot, risk)
        dedupe_key = _canonical_dedupe_key(
            target=target,
            signal_time=snapshot.datetime,
            input_digest=str(input_identity["digest"]),
        )
        formal_lineage = {
            "schema_version": "signal_canonical_inputs_v1",
            "input_identity": deepcopy(input_identity),
            "auxiliary_input_identities": deepcopy(auxiliary_identities),
            "strategy_version": str(payload.get("strategy_version") or "v0"),
        }
        mode = SignalScanMode(str(payload.get("mode") or SignalScanMode.SCAN.value))
        existing = None
        if mode is SignalScanMode.SCAN:
            existing = self.session.scalar(
                select(StrategySignal).where(StrategySignal.dedupe_key == dedupe_key)
            )
        if existing is None:
            signal = self._make_signal(
                task,
                target,
                snapshot,
                last_bar,
                quality,
                risk,
                score,
                dedupe_key,
            )
            event_type = "signal_created"
        else:
            signal = existing
            changed = _signal_changed(existing, snapshot, score, risk)
            _update_signal(existing, task, snapshot, last_bar, quality, risk, score)
            event_type = "signal_changed" if changed else None
        features = dict(signal.features or {})
        features["formal_lineage"] = deepcopy(formal_lineage)
        features["input_identity"] = deepcopy(input_identity)
        features["auxiliary_input_identities"] = deepcopy(auxiliary_identities)
        features["research_only"] = False
        features["source_mode"] = "historical_scan"
        features["observation_only"] = True
        features["not_trading_instruction"] = True
        features["auto_order"] = False
        signal.features = features
        signal.profile_id = None
        signal.market_data_file_id = None
        signal.strategy_name = str(payload.get("strategy_code") or "su_bing_ema21")
        signal.strategy_version = str(payload.get("strategy_version") or "v0")
        signal.product = target.symbol
        signal.continuous_contract = f"{target.symbol.upper()}.MAIN"
        signal.actual_contract = target.contract
        signal.dominant_mapping_date = result.bars[-1].trading_day
        signal.provider = "rqdata"
        signal.source = "historical_canonical"
        signal.data_role = "primary"
        signal.bar_start = snapshot.datetime - _period_delta(target.period)
        signal.bar_end = snapshot.datetime
        signal.trigger_price = float(signal.current_price)
        signal.quality_status = quality
        signal.research_contract = False
        task.profile_id = None
        task.market_data_file_id = None
        evaluation = signal_payload(signal)
        self._formal_evaluations.append(deepcopy(evaluation))
        if mode is not SignalScanMode.SCAN:
            return None, None
        if existing is None:
            self.session.add(signal)
            self.session.flush()
        return signal, event_type

    def _risk_payload(
        self,
        snapshot: Any,
        bar: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if payload.get("research_only"):
            raise ValueError("SIGNAL_LEGACY_EXECUTION_RETIRED")
        spec = load_contract_spec(
            self.session,
            str(bar["symbol"]),
            str(bar["contract"]),
        )
        entry = _decimal_value(bar["close"], field="bar.close")
        atr = _decimal_value(snapshot.features.get("atr") or 0, field="atr")
        price_tick = _decimal_value(spec.price_tick, field="price_tick")
        prior_high = _decimal_or_none(snapshot.features.get("prior_high"))
        prior_low = _decimal_or_none(snapshot.features.get("prior_low"))
        if snapshot.direction == "long":
            stop = (
                prior_low
                if prior_low is not None
                else entry - max(Decimal("2") * atr, price_tick)
            )
            target = entry + Decimal("2") * abs(entry - stop)
        elif snapshot.direction == "short":
            stop = (
                prior_high
                if prior_high is not None
                else entry + max(Decimal("2") * atr, price_tick)
            )
            target = entry - Decimal("2") * abs(entry - stop)
        else:
            stop = None
            target = None
        account_equity = _decimal_value(
            payload.get("account_equity", "100000"),
            field="account_equity",
        )
        risk_pct = _decimal_value(
            payload.get("risk_per_trade_pct", "0.01"),
            field="risk_per_trade_pct",
        )
        max_margin_pct = _decimal_value(
            payload.get("max_margin_usage_pct", "0.35"),
            field="max_margin_usage_pct",
        )
        multiplier = Decimal(spec.volume_multiple)
        margin_rate = _decimal_value(spec.margin_rate, field="margin_rate")
        risk_budget = account_equity * risk_pct
        risk_per_lot = (
            abs(entry - stop) * multiplier if stop is not None else Decimal("0")
        )
        risk_volume = (
            _floor_decimal(risk_budget / risk_per_lot) if risk_per_lot > 0 else 0
        )
        margin_per_lot = entry * multiplier * margin_rate
        margin_volume = (
            _floor_decimal(account_equity * max_margin_pct / margin_per_lot)
            if margin_per_lot > 0
            else 0
        )
        open_volume = max(0, min(risk_volume, margin_volume))
        margin_required = Decimal(open_volume) * margin_per_lot
        risk_amount = Decimal(open_volume) * risk_per_lot
        return {
            "entry_price": entry,
            "target_price": target,
            "stop_loss_price": stop,
            "risk_reward_ratio": (
                None
                if stop is None or target is None or abs(entry - stop) <= 0
                else abs(target - entry) / abs(entry - stop)
            ),
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
        signal = StrategySignal(
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
            research_contract=target.contract.lower().endswith(".main"),
            spec_source=risk["spec_source"],
        )
        _apply_contract_context(
            signal,
            task,
            target.period,
            snapshot.datetime,
            float(bar["close"]),
            signal.features,
            quality,
        )
        return signal

    def _canonical_bars(
        self,
        payload: dict[str, Any],
        period: str,
    ) -> tuple[BarQuery, Any, dict[str, object]]:
        query = BarQuery(
            dataset_kind=DatasetKind(str(payload["dataset_kind"])),
            symbol=str(payload["instrument_symbol"]),
            contract_or_series=str(payload["contract_or_series"]),
            frequency=parse_bar_frequency(period),
            start=_aware_datetime(payload["start"]),
            end=_aware_datetime(payload["end"]),
        )
        result = self._canonical_service().get_bars(query)
        identity = build_canonical_consumer_input(
            query,
            result,
            strategy_input_version=_strategy_input_version(payload),
        ).to_snapshot()
        return query, result, identity

    def _canonical_service(self) -> MarketDataService:
        if self._canonical_market_data is None:
            self._canonical_market_data = MarketDataService(
                self.session,
                canonical_reader=build_canonical_reader(self.session),
            )
        return self._canonical_market_data

    def _block(self, task: SignalScanTask, target: ScanTarget, code: str) -> None:
        del task
        self._formal_blocked_items.append(
            {
                "code": code,
                "context": {
                    "instrument_symbol": target.symbol,
                    "contract_or_series": target.contract,
                    "period": target.period,
                },
            }
        )


def create_signal_scan_task(
    session: Session, request_payload: dict[str, Any]
) -> SignalScanTask:
    research_only = bool(request_payload.get("research_only", False))
    if research_only:
        raise ValueError("SIGNAL_LEGACY_EXECUTION_RETIRED")
    request = SignalScanRequest.model_validate(request_payload)
    if request.mode is not SignalScanMode.SCAN:
        raise ValueError("SIGNAL_NON_SCAN_MODE_IS_PREVIEW_ONLY")
    payload = build_formal_signal_task_payload(request)
    ensure_default_watchlists(session)
    periods = payload.get("periods") or DEFAULT_PERIODS
    item_count = len(
        _watchlist_items(
            session, str(payload["watchlist_code"]), payload.get("symbols")
        )
    )
    task = SignalScanTask(
        task_no=f"SIG-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        status="pending",
        progress=0.0,
        watchlist_code=str(payload["watchlist_code"]),
        periods=periods,
        total_items=max(1, item_count * len(periods)),
        request_payload=payload,
        result_payload={},
        profile_id=None,
        market_data_file_id=None,
    )
    session.add(task)
    session.flush()
    return task


def _is_formal_task_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        raise ValueError("SIGNAL_TASK_ROUTING_INVALID")
    execution_contract = payload.get("execution_contract")
    has_formal_marker = (
        execution_contract == FORMAL_SIGNAL_EXECUTION_CONTRACT
        or payload.get("research_only") is False
        or bool(FORMAL_SIGNAL_ROUTING_MARKERS & set(payload))
    )
    if has_formal_marker:
        return True
    if (
        execution_contract == LEGACY_SIGNAL_EXECUTION_CONTRACT
        and payload.get("research_only") is True
    ):
        return False
    raise ValueError("SIGNAL_TASK_ROUTING_INVALID")


def _validate_formal_task(task: SignalScanTask) -> SignalScanRequest:
    try:
        request = validate_formal_signal_task_payload(task.request_payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID") from exc
    if (
        task.profile_id is not None
        or task.market_data_file_id is not None
        or task.watchlist_code != request.watchlist_code
        or list(task.periods or []) != request.periods
    ):
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID")
    return request


def enqueue_signal_scan_task(task_id: int) -> str:
    redis = get_redis_connection()
    redis.ping()
    queued = get_signal_queue().enqueue(
        run_signal_scan_task, task_id, job_timeout="2h", result_ttl=86400
    )
    return queued.id


def run_signal_scan_task(task_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        return SignalScanner(session).run(task_id)


def task_snapshot(task: SignalScanTask) -> dict[str, Any]:
    request_payload = task.request_payload or {}
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
        "profile_id": task.profile_id,
        "market_data_file_id": task.market_data_file_id,
        "data_role": str(
            request_payload.get("data_role") or SignalDataRole.PRIMARY.value
        ),
        "research_only": bool(request_payload.get("research_only", False)),
        "mode": str(request_payload.get("mode") or SignalScanMode.SCAN.value),
    }


def _base_signal_payload(signal: StrategySignal) -> dict[str, Any]:
    return {
        "id": signal.id,
        "task_no": signal.task_no,
        "strategy_name": signal.strategy_name,
        "strategy_version": signal.strategy_version,
        "watchlist_code": signal.watchlist_code,
        "symbol": signal.symbol,
        "contract": signal.contract,
        **signal_contract_context_payload(signal),
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
        "profile_id": signal.profile_id,
        "market_data_file_id": signal.market_data_file_id,
        "research_contract": signal.research_contract,
        "spec_source": signal.spec_source,
        "alert_status": signal.alert_status,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "updated_at": signal.updated_at.isoformat() if signal.updated_at else None,
    }


def signal_payload(signal: StrategySignal) -> dict[str, Any]:
    payload = _base_signal_payload(signal)
    for field in (
        "current_price",
        "target_price",
        "stop_loss_price",
        "risk_reward_ratio",
        "margin_required",
        "risk_amount",
        "account_equity",
    ):
        if isinstance(payload.get(field), Decimal):
            payload[field] = float(payload[field])
    features = dict(signal.features or {})
    strategy_status = signal.status
    lifecycle_status = _lifecycle_status(signal)
    signal_type = _signal_type(strategy_status, signal.direction)
    reasons = list(signal.reasons or [])
    data_role = str(
        signal.data_role or features.get("data_role") or SignalDataRole.PRIMARY.value
    )
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
            "research_only": data_role != SignalDataRole.PRIMARY.value
            or bool(features.get("research_only", False)),
            "strategy_code": features.get("strategy_code") or signal.strategy_name,
            "entry_interval": features.get("entry_interval") or signal.period,
            "signal_price": features.get("signal_price") or signal.current_price,
            "daily_direction": features.get("daily_direction"),
            "entry_reason": features.get("entry_reason"),
            "no_signal_reason": features.get("no_signal_reason"),
            "max_hold_bars": features.get("max_hold_bars"),
            "profile_id": signal.profile_id,
            "market_data_file_id": signal.market_data_file_id,
            "input_identity": deepcopy(features.get("input_identity"))
            if isinstance(features.get("input_identity"), dict)
            else None,
        }
    )
    return payload


def update_signal_status(
    session: Session, signal_id: int, status: SignalStatus
) -> StrategySignal:
    signal = session.get(StrategySignal, signal_id)
    if signal is None:
        raise ValueError("signal not found")
    from app.signal.events import lifecycle_status, record_signal_status_change

    old_status = lifecycle_status(signal)
    new_status = status.value
    features = dict(signal.features or {})
    features["signal_status"] = new_status
    signal.features = features
    signal.alert_status = (
        "acknowledged" if status is SignalStatus.VIEWED else status.value
    )
    changed_at = datetime.now(UTC)
    signal.updated_at = changed_at
    record_signal_status_change(session, signal, old_status, new_status, changed_at)
    session.commit()
    session.refresh(signal)
    return signal


def score_signal(snapshot: SignalSnapshot, risk: dict[str, Any]) -> dict[str, Any]:
    score = int(snapshot.signal_level or 0)
    features = snapshot.features
    if features.get("volume_ratio") and float(features["volume_ratio"]) >= 1.5:
        score += 5
    if features.get("higher_timeframe_resonance") is True:
        score += 8
    if risk.get("risk_reward_ratio") and float(risk["risk_reward_ratio"]) >= 1.8:
        score += 6
    if snapshot.trade_intent.get("action") in {
        "trial_entry",
        "confirm_entry",
        "add_watch",
    }:
        score += 4
    if snapshot.direction == "neutral":
        score = min(score, 50)
    score = max(0, min(100, score))
    bucket = (
        80
        if score >= 80
        else 70
        if score >= 70
        else 60
        if score >= 60
        else 51
        if score >= 51
        else 0
    )
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
    _apply_contract_context(
        signal,
        task,
        signal.period,
        snapshot.datetime,
        float(bar["close"]),
        snapshot.features,
        quality,
    )
    signal.updated_at = utc_now()


def _signal_changed(
    existing: StrategySignal,
    snapshot: SignalSnapshot,
    score: dict[str, Any],
    risk: dict[str, Any],
) -> bool:
    return (
        existing.status != snapshot.status
        or existing.direction != snapshot.direction
        or existing.score_bucket != score["bucket"]
        or existing.open_volume != risk["open_volume"]
    )


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


def _watchlist_items(
    session: Session, watchlist_code: str, symbols: list[str] | None = None
) -> list[WatchlistItem]:
    selected = set(symbols or [])
    query = (
        select(WatchlistItem)
        .where(
            WatchlistItem.watchlist_code == watchlist_code,
            WatchlistItem.is_active.is_(True),
        )
        .order_by(WatchlistItem.sort_order, WatchlistItem.symbol)
    )
    rows = list(session.scalars(query))
    return [row for row in rows if not selected or row.symbol in selected]


def _apply_contract_context(
    signal: StrategySignal,
    task: SignalScanTask,
    period: str,
    signal_time: datetime,
    current_price: float,
    features: dict[str, Any],
    quality: dict[str, Any],
) -> None:
    payload = task.request_payload or {}
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
            provider=payload.get("provider"),
            data_role=payload.get("data_role"),
        ),
    )


def _period_delta(period: str) -> timedelta:
    if period.endswith("m") and period[:-1].isdigit():
        return timedelta(minutes=int(period[:-1]))
    if period == "1d":
        return timedelta(days=1)
    if period == "1w":
        return timedelta(days=7)
    return timedelta(0)


def _canonical_bar_payload(bar: Any, *, exchange: str | None) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "contract": bar.contract_or_series,
        "exchange": exchange,
        "datetime": bar.bar_end,
        "trading_day": bar.trading_day,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "turnover": None if bar.turnover is None else float(bar.turnover),
        "open_interest": None
        if bar.open_interest is None
        else float(bar.open_interest),
        "period": bar.frequency.value,
        "provider": bar.provider,
    }


def _strategy_input_version(payload: dict[str, Any]) -> str:
    strategy_code = str(payload.get("strategy_code") or "su_bing_ema21")
    strategy_version = str(payload.get("strategy_version") or "v0")
    encoded = json.dumps(
        payload.get("strategy_params") or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{strategy_code}:{strategy_version}:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_dedupe_key(
    *,
    target: ScanTarget,
    signal_time: datetime,
    input_digest: str,
) -> str:
    encoded = (
        f"{SCAN_SIGNAL_VERSION}:{target.symbol}:{target.contract}:"
        f"{target.period}:{signal_time.isoformat()}:{input_digest}"
    ).encode("utf-8")
    return f"canonical:{hashlib.sha256(encoded).hexdigest()}"


def _aware_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("formal signal window datetimes must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal_value(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"SIGNAL_RISK_DECIMAL_INVALID:{field}") from exc
    if not parsed.is_finite():
        raise ValueError(f"SIGNAL_RISK_DECIMAL_INVALID:{field}")
    return parsed


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _decimal_value(value, field="strategy_feature")


def _floor_decimal(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def utc_now() -> datetime:
    return datetime.now(UTC)


def _validate_actual_dominant_mapping_provenance(
    session: Session,
    results: list[Any],
) -> None:
    first_decision_by_day: dict[Any, datetime] = {}
    contract_by_day: dict[Any, str] = {}
    symbol_by_day: dict[Any, str] = {}
    for result in results:
        for bar in result.bars:
            trading_day = bar.trading_day
            decision_time = _aware_datetime(bar.bar_end)
            current = first_decision_by_day.get(trading_day)
            if current is None or decision_time < current:
                first_decision_by_day[trading_day] = decision_time
            contract = str(bar.contract_or_series).strip().upper()
            existing_contract = contract_by_day.setdefault(trading_day, contract)
            if existing_contract != contract:
                raise ValueError("SIGNAL_MAIN_CONTRACT_BAR_CONFLICT")
            symbol_by_day.setdefault(trading_day, str(bar.symbol).strip().lower())

    for trading_day, decision_time in first_decision_by_day.items():
        try:
            mapping = load_strict_main_contract_mapping(
                session,
                instrument_symbol=symbol_by_day[trading_day],
                trade_date=trading_day,
            )
        except ValueError as exc:
            raise ValueError("SIGNAL_MAIN_CONTRACT_MAPPING_INVALID") from exc
        if mapping is None:
            raise ValueError("SIGNAL_MAIN_CONTRACT_MAPPING_MISSING")
        if str(mapping.contract_code).strip().upper() != contract_by_day[trading_day]:
            raise ValueError("SIGNAL_MAIN_CONTRACT_MAPPING_MISMATCH")
        raw_payload = mapping.raw_payload if isinstance(mapping.raw_payload, dict) else {}
        known_at = raw_payload.get("known_at")
        if known_at is None:
            raise ValueError("SIGNAL_MAIN_CONTRACT_KNOWN_AT_MISSING")
        try:
            normalized_known_at = _aware_datetime(known_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("SIGNAL_MAIN_CONTRACT_KNOWN_AT_INVALID") from exc
        if normalized_known_at > decision_time:
            raise ValueError("SIGNAL_MAIN_CONTRACT_KNOWN_AT_AFTER_DECISION")
