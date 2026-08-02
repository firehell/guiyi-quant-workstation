from __future__ import annotations

from copy import deepcopy
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
from app.data_core.contracts import BarFrequency, BarQuery, DatasetKind
from app.models.backtest import WatchlistItem
from app.models.signal import SignalScanTask, StrategySignal
from app.queue import get_redis_connection, get_signal_queue
from app.schemas.signal import (
    FORMAL_SIGNAL_AUXILIARY_PERIOD,
    SignalDataRole,
    SignalScanMode,
    SignalScanRequest,
    SignalStatus,
    build_formal_signal_task_payload,
    validate_formal_signal_task_payload,
)
from app.services import signal_scanner as legacy
from app.services.canonical_market_data import build_canonical_reader
from app.services.market_data_service import MarketDataService
from app.services.actual_contract_semantics import load_strict_main_contract_mapping

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
        if task is None:
            raise ValueError(f"signal scan task not found: {task_id}")
        self._formal_execution = (
            task.profile_id is None and task.market_data_file_id is None
        )
        if self._formal_execution:
            _validate_formal_task(task)
        if not self._formal_execution:
            self.reader = legacy.MarketDataReader(self.session)
        try:
            return super().run(task_id)
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
        if payload.get("research_only"):
            return super()._scan_one(task, target)
        query, result, input_identity = self._canonical_bars(payload, target.period)
        bars = [_canonical_bar_payload(item, exchange=target.exchange_code) for item in result.bars]
        if not bars:
            return None, None
        higher_bars: list[dict[str, Any]] = []
        auxiliary_identities: dict[str, dict[str, object]] = {}
        canonical_results = [result]
        higher_period = FORMAL_SIGNAL_AUXILIARY_PERIOD.get(target.period)
        if higher_period is not None:
            _, higher_result, higher_identity = self._canonical_bars(payload, higher_period)
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
        risk = self._risk_payload(
            snapshot,
            {**last_bar, "close": result.bars[-1].close},
            payload,
        )
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
            return super()._risk_payload(snapshot, bar, payload)
        spec = legacy.load_contract_spec(
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
            stop = prior_low if prior_low is not None else entry - max(Decimal("2") * atr, price_tick)
            target = entry + Decimal("2") * abs(entry - stop)
        elif snapshot.direction == "short":
            stop = prior_high if prior_high is not None else entry + max(Decimal("2") * atr, price_tick)
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
        risk_per_lot = abs(entry - stop) * multiplier if stop is not None else Decimal("0")
        risk_volume = _floor_decimal(risk_budget / risk_per_lot) if risk_per_lot > 0 else 0
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
        payload = {
            **normalized_request,
            "data_role": str(
                normalized_request.get("data_role")
                or SignalDataRole.PRIMARY.value
            ),
            "research_only": True,
        }
    else:
        request = SignalScanRequest.model_validate(request_payload)
        if request.mode is not SignalScanMode.SCAN:
            raise ValueError("SIGNAL_NON_SCAN_MODE_IS_PREVIEW_ONLY")
        payload = build_formal_signal_task_payload(request)
    task = legacy.create_signal_scan_task(session, payload)
    task.request_payload = payload
    task.profile_id = str(payload.get("profile_id")) if payload["research_only"] and payload.get("profile_id") else None
    task.market_data_file_id = None
    return task


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
