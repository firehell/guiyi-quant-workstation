from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.data_core.consumer_identity import build_canonical_consumer_input
from app.data_core.contracts import BarFrequency, BarQuery, DatasetKind
from app.models.backtest import WatchlistItem
from app.models.signal import SignalScanTask, StrategySignal
from app.queue import get_redis_connection, get_signal_queue
from app.schemas.signal import SignalDataRole, SignalScanMode, SignalScanRequest, SignalStatus
from app.signal.jm_v1b import JM_V1B_SCAN_PERIODS, JM_V1B_STRATEGY_CODE, JM_V1B_SYMBOL, JM_V1B_WATCHLIST_CODE, scan_jm_v1b_signal
from app.services import signal_scanner as legacy
from app.services.canonical_market_data import build_canonical_reader
from app.services.market_data_service import MarketDataService

DEFAULT_PERIODS = legacy.DEFAULT_PERIODS
SIGNAL_STATUS_VALUES = {item.value for item in SignalStatus}


class SignalScanner(legacy.SignalScanner):
    """Historical scanner with canonical formal and legacy research-preview paths."""

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
        self._formal_execution = bool(task is not None and not (task.request_payload or {}).get("research_only"))
        if not self._formal_execution:
            self.reader = legacy.MarketDataReader(self.session)
        try:
            return super().run(task_id)
        finally:
            self._formal_execution = False

    def _publish(self, event: str, payload: dict[str, Any]) -> None:
        if self._formal_execution:
            return
        super()._publish(event, payload)

    def _run_task(self, task: SignalScanTask) -> dict[str, Any]:
        self._formal_blocked_items = []
        self._formal_evaluations = []
        result = super()._run_task(task)
        return {
            **result,
            "mode": str((task.request_payload or {}).get("mode") or SignalScanMode.SCAN.value),
            "evaluations": deepcopy(self._formal_evaluations),
            "blocked_items": list(self._formal_blocked_items),
        }

    def _targets(self, payload: dict[str, Any]) -> list[legacy.ScanTarget]:
        if payload.get("research_only") and payload.get("strategy_code") == JM_V1B_STRATEGY_CODE:
            return [
                legacy.ScanTarget(
                    symbol="jm",
                    name="焦煤",
                    contract=JM_V1B_SYMBOL,
                    exchange_code="DCE",
                    period=period,
                )
                for period in JM_V1B_SCAN_PERIODS
            ]
        if not payload.get("research_only"):
            return [
                legacy.ScanTarget(
                    symbol=str(payload["instrument_symbol"]).lower(),
                    name=None,
                    contract=str(payload["contract_or_series"]).upper(),
                    exchange_code="DCE",
                    period=str(period),
                )
                for period in payload["periods"]
            ]
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
                    for row in self._research_reader().get_coverage(symbol=item.symbol, period=period)
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

    def _scan_one(self, task: SignalScanTask, target: legacy.ScanTarget) -> tuple[StrategySignal | None, str | None]:
        payload = task.request_payload or {}
        if payload.get("research_only") and payload.get("strategy_code") == JM_V1B_STRATEGY_CODE:
            return scan_jm_v1b_signal(self.session, self._research_reader(), task, target.period)
        if payload.get("research_only"):
            return super()._scan_one(task, target)
        query, result, input_identity = self._canonical_bars(payload, target.period)
        bars = [_canonical_bar_payload(item, exchange=target.exchange_code) for item in result.bars]
        if not bars:
            return None, None
        higher_bars: list[dict[str, Any]] = []
        auxiliary_identities: dict[str, dict[str, object]] = {}
        higher_period = legacy.HIGHER_PERIOD.get(target.period)
        if higher_period is not None:
            _, higher_result, higher_identity = self._canonical_bars(payload, higher_period)
            higher_bars = [
                _canonical_bar_payload(item, exchange=target.exchange_code)
                for item in higher_result.bars
                if item.bar_end <= result.bars[-1].bar_end
            ]
            auxiliary_identities[higher_period] = higher_identity
        snapshot = legacy.generate_signals(
            bars,
            higher_timeframe_bars=higher_bars,
            params=legacy.SuBingParams(**(payload.get("strategy_params") or {})),
        )[-1]
        last_bar = bars[-1]
        quality = {
            "status": "passed",
            "provider": "rqdata",
            "canonical_consumer_input_digest": input_identity["digest"],
        }
        risk = self._risk_payload(snapshot, last_bar, payload)
        score = legacy.score_signal(snapshot, risk)
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
            changed = legacy._signal_changed(existing, snapshot, score, risk)
            legacy._update_signal(existing, task, snapshot, last_bar, quality, risk, score)
            event_type = "signal_changed" if changed else None
        features = dict(signal.features or {})
        features["formal_lineage"] = deepcopy(formal_lineage)
        features["input_identity"] = deepcopy(input_identity)
        features["auxiliary_input_identities"] = deepcopy(auxiliary_identities)
        features["research_only"] = False
        features["source_mode"] = "historical_scan"
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

    def _canonical_bars(
        self,
        payload: dict[str, Any],
        period: str,
    ) -> tuple[BarQuery, Any, dict[str, object]]:
        query = BarQuery(
            dataset_kind=DatasetKind(str(payload["dataset_kind"])),
            symbol=str(payload["instrument_symbol"]),
            contract_or_series=str(payload["contract_or_series"]),
            frequency=BarFrequency(period),
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

    def _research_reader(self):
        if self.reader is None:
            self.reader = legacy.MarketDataReader(self.session)
        return self.reader

    def _block(self, task: SignalScanTask, target: legacy.ScanTarget, code: str) -> None:
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


def create_signal_scan_task(session: Session, request_payload: dict[str, Any]) -> SignalScanTask:
    research_only = bool(request_payload.get("research_only", False))
    if research_only:
        normalized_request = dict(request_payload)
    else:
        normalized_request = SignalScanRequest.model_validate(request_payload).model_dump(mode="json")
    payload = {
        **normalized_request,
        "data_role": str(normalized_request.get("data_role") or SignalDataRole.PRIMARY.value),
        "research_only": research_only,
    }
    task = legacy.create_signal_scan_task(session, payload)
    task.request_payload = payload
    task.profile_id = str(payload.get("profile_id")) if payload["research_only"] and payload.get("profile_id") else None
    task.market_data_file_id = None
    return task


def create_jm_v1b_signal_scan_task(session: Session, request_payload: dict[str, Any] | None = None) -> SignalScanTask:
    payload = {
        "watchlist_code": JM_V1B_WATCHLIST_CODE,
        "symbols": ["jm"],
        "periods": JM_V1B_SCAN_PERIODS.copy(),
        "provider": None,
        "data_role": SignalDataRole.PRIMARY.value,
        "research_only": True,
        "strategy_code": JM_V1B_STRATEGY_CODE,
        "strategy_version": "v1b.0",
        "account_equity": 100000.0,
        "risk_per_trade_pct": 0.01,
        "max_margin_usage_pct": 0.35,
        "min_score_bucket": 0,
        "allow_warning_quality": False,
        "strategy_params": {},
        **(request_payload or {}),
    }
    task = SignalScanTask(
        task_no=f"SIG-JM-V1B-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        status="pending",
        progress=0.0,
        watchlist_code=JM_V1B_WATCHLIST_CODE,
        periods=JM_V1B_SCAN_PERIODS.copy(),
        total_items=len(JM_V1B_SCAN_PERIODS),
        request_payload=payload,
        result_payload={},
    )
    session.add(task)
    session.flush()
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
    payload["mode"] = str(request_payload.get("mode") or SignalScanMode.SCAN.value)
    payload["profile_id"] = task.profile_id
    payload["market_data_file_id"] = task.market_data_file_id
    return payload


def signal_payload(signal: StrategySignal) -> dict[str, Any]:
    payload = legacy.signal_payload(signal)
    features = dict(signal.features or {})
    strategy_status = signal.status
    lifecycle_status = _lifecycle_status(signal)
    signal_type = _signal_type(strategy_status, signal.direction)
    reasons = list(signal.reasons or [])
    data_role = str(signal.data_role or features.get("data_role") or SignalDataRole.PRIMARY.value)
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
            "strategy_code": features.get("strategy_code") or signal.strategy_name,
            "entry_interval": features.get("entry_interval") or signal.period,
            "signal_price": features.get("signal_price") or signal.current_price,
            "daily_direction": features.get("daily_direction"),
            "entry_reason": features.get("entry_reason"),
            "no_signal_reason": features.get("no_signal_reason"),
            "max_hold_bars": features.get("max_hold_bars"),
            "profile_id": signal.profile_id,
            "market_data_file_id": signal.market_data_file_id,
            "input_identity": deepcopy(features.get("input_identity")) if isinstance(features.get("input_identity"), dict) else None,
        }
    )
    return payload


def update_signal_status(session: Session, signal_id: int, status: SignalStatus) -> StrategySignal:
    signal = session.get(StrategySignal, signal_id)
    if signal is None:
        raise ValueError("signal not found")
    from app.signal.events import lifecycle_status, record_signal_status_change

    old_status = lifecycle_status(signal)
    new_status = status.value
    features = dict(signal.features or {})
    features["signal_status"] = new_status
    signal.features = features
    signal.alert_status = "acknowledged" if status is SignalStatus.VIEWED else status.value
    changed_at = datetime.now(UTC)
    signal.updated_at = changed_at
    record_signal_status_change(session, signal, old_status, new_status, changed_at)
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
        "open_interest": None if bar.open_interest is None else float(bar.open_interest),
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
    target: legacy.ScanTarget,
    signal_time: datetime,
    input_digest: str,
) -> str:
    encoded = (
        f"{legacy.SCAN_SIGNAL_VERSION}:{target.symbol}:{target.contract}:"
        f"{target.period}:{signal_time.isoformat()}:{input_digest}"
    ).encode("utf-8")
    return f"canonical:{hashlib.sha256(encoded).hexdigest()}"


def _aware_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("formal signal window datetimes must be timezone-aware")
    return parsed.astimezone(UTC)
