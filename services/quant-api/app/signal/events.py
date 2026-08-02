from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.consumer_identity import CanonicalConsumerInput
from app.data_core.contracts import DataCoreError, DatasetKind
from app.models.signal import SignalEvent, SignalScanTask, StrategySignal
from app.schemas.signal import (
    FORMAL_SIGNAL_STRATEGY_CODE,
    FORMAL_SIGNAL_STRATEGY_VERSION,
    SignalScanMode,
    validate_formal_signal_task_payload,
)
from app.signal.contract_context import signal_contract_context_payload
from app.signal.formal_identity import parse_formal_auxiliary_identities

SIGNAL_CREATED = "signal_created"
SIGNAL_CHANGED = "signal_changed"
SIGNAL_STATUS_CHANGED = "signal_status_changed"
SIGNAL_SCAN_EVENT_TYPES = {SIGNAL_CREATED, SIGNAL_CHANGED}
SENSITIVE_KEY_PARTS = ("webhook", "token", "password", "passwd", "secret", "cookie")


def record_signal_scan_event(
    session: Session,
    signal: StrategySignal,
    event_type: str | None,
    task: SignalScanTask,
) -> SignalEvent | None:
    request_payload = task.request_payload or {}
    if bool(request_payload.get("research_only")):
        return None
    if str(request_payload.get("mode") or "scan") != "scan":
        return None
    if not _valid_formal_scan_identity(signal, task):
        return None
    if event_type not in SIGNAL_SCAN_EVENT_TYPES:
        return None
    event_key = _scan_event_key(signal, event_type, task.task_no)
    return _create_event_if_missing(
        session,
        signal=signal,
        event_key=event_key,
        event_type=event_type,
        source_mode=_scan_source_mode(task, signal),
        task_no=task.task_no,
        payload_extra={"task": _task_payload(task)},
    )


def _valid_formal_scan_identity(
    signal: StrategySignal,
    task: SignalScanTask,
) -> bool:
    request_payload = task.request_payload or {}
    try:
        formal_request = validate_formal_signal_task_payload(request_payload)
    except (TypeError, ValueError):
        return False
    if formal_request.mode is not SignalScanMode.SCAN:
        return False
    input_snapshot = _input_identity(signal)
    if not isinstance(input_snapshot, dict):
        return False
    try:
        identity = CanonicalConsumerInput.from_snapshot(input_snapshot)
    except (DataCoreError, TypeError, ValueError):
        return False
    request = identity.request
    if request.dataset_kind is not DatasetKind.ACTUAL_DOMINANT:
        return False
    if signal.profile_id is not None or signal.market_data_file_id is not None:
        return False
    if task.profile_id is not None or task.market_data_file_id is not None:
        return False
    if signal.research_contract or signal.data_role != "primary":
        return False
    if signal.source != "historical_canonical" or signal.provider != "rqdata":
        return False
    if signal.strategy_name != FORMAL_SIGNAL_STRATEGY_CODE:
        return False
    if signal.strategy_version != FORMAL_SIGNAL_STRATEGY_VERSION:
        return False
    if formal_request.strategy_code != signal.strategy_name:
        return False
    if formal_request.strategy_version != signal.strategy_version:
        return False
    strategy_prefix = f"{signal.strategy_name}:{signal.strategy_version}:"
    if not identity.strategy_input_version.startswith(strategy_prefix):
        return False
    strategy_params = formal_request.strategy_params
    if not isinstance(strategy_params, dict):
        return False
    encoded_params = json.dumps(
        strategy_params,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    expected_strategy_input_version = (
        f"{strategy_prefix}{hashlib.sha256(encoded_params).hexdigest()}"
    )
    if identity.strategy_input_version != expected_strategy_input_version:
        return False
    if formal_request.dataset_kind is not request.dataset_kind:
        return False
    if formal_request.instrument_symbol != request.symbol:
        return False
    if formal_request.contract_or_series != request.contract_or_series:
        return False
    if request.frequency.value not in formal_request.periods:
        return False
    try:
        signal_start = _event_datetime(signal.bar_start)
        signal_end = _event_datetime(signal.bar_end)
        signal_time = _event_datetime(signal.signal_time)
    except (TypeError, ValueError):
        return False
    if formal_request.start != request.start or formal_request.end != request.end:
        return False
    if not (request.start <= signal_start < signal_end <= request.end):
        return False
    if signal_time != signal_end:
        return False
    if signal.symbol.lower() != request.symbol or (signal.product or "").lower() != request.symbol:
        return False
    if signal.contract.upper() != request.contract_or_series:
        return False
    if (signal.actual_contract or "").upper() != request.contract_or_series:
        return False
    if signal.period != request.frequency.value:
        return False
    formal_lineage = (signal.features or {}).get("formal_lineage")
    if not isinstance(formal_lineage, dict):
        return False
    if formal_lineage.get("schema_version") != "signal_canonical_inputs_v1":
        return False
    if formal_lineage.get("input_identity") != input_snapshot:
        return False
    if formal_lineage.get("strategy_version") != signal.strategy_version:
        return False
    features = signal.features or {}
    auxiliary_snapshots = formal_lineage.get("auxiliary_input_identities")
    if features.get("auxiliary_input_identities") != auxiliary_snapshots:
        return False
    try:
        parse_formal_auxiliary_identities(identity, auxiliary_snapshots)
    except (TypeError, ValueError):
        return False
    if (
        features.get("observation_only") is not True
        or features.get("not_trading_instruction") is not True
        or features.get("auto_order") is not False
    ):
        return False
    quality = signal.quality_status if isinstance(signal.quality_status, dict) else {}
    return quality.get("canonical_consumer_input_digest") == identity.digest


def _event_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def record_signal_status_change(
    session: Session,
    signal: StrategySignal,
    old_status: str,
    new_status: str,
    changed_at: datetime | None = None,
) -> SignalEvent | None:
    if old_status == new_status:
        return None
    event_time = changed_at or datetime.now(UTC)
    event_key = f"{SIGNAL_STATUS_CHANGED}:{signal.id}:{old_status}:{new_status}:{event_time.isoformat()}"
    return _create_event_if_missing(
        session,
        signal=signal,
        event_key=event_key,
        event_type=SIGNAL_STATUS_CHANGED,
        source_mode="manual_api",
        task_no=signal.task_no,
        created_at=event_time,
        lifecycle_status_value=new_status,
        payload_extra={"status_change": {"old_status": old_status, "new_status": new_status}},
    )


def record_live_signal_event(
    session: Session,
    signal: StrategySignal,
    event_type: str,
    *,
    state_key: str,
) -> SignalEvent | None:
    """Append a live-confirmed event without creating a historical scan task."""
    if event_type not in SIGNAL_SCAN_EVENT_TYPES:
        return None
    suffix = "created" if event_type == SIGNAL_CREATED else state_key
    return _create_event_if_missing(
        session,
        signal=signal,
        event_key=f"{event_type}:{signal.dedupe_key}:{suffix}",
        event_type=event_type,
        source_mode="live_confirmed",
        task_no=None,
        payload_extra={
            "live_observation": {
                "observation_only": True,
                "not_trading_instruction": True,
                "auto_order": False,
                "state_key": state_key,
            }
        },
    )


def record_htdy_first_seen_event(
    session: Session,
    signal: StrategySignal,
) -> SignalEvent | None:
    """Append the single immutable HTDY first-seen event."""

    if signal.strategy_name != "htdy_original_realtime_first_seen":
        return None
    return _create_event_if_missing(
        session,
        signal=signal,
        event_key=f"{SIGNAL_CREATED}:{signal.dedupe_key}:created",
        event_type=SIGNAL_CREATED,
        source_mode="live_realtime_repainting",
        task_no=None,
        payload_extra={
            "htdy_first_seen": {
                "observation_only": True,
                "future_looking": True,
                "repainting_accepted": True,
                "first_seen_no_retraction": True,
                "historical_backtest_allowed": False,
                "notification_ready": False,
                "not_trading_instruction": True,
                "auto_order": False,
            }
        },
    )


def list_signal_events(
    session: Session,
    *,
    signal_id: int | None = None,
    task_no: str | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    source_mode: str | None = None,
    product: str | None = None,
    continuous_contract: str | None = None,
    actual_contract: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    data_role: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SignalEvent]:
    query = _signal_events_query(
        signal_id=signal_id,
        task_no=task_no,
        symbol=symbol,
        event_type=event_type,
        source_mode=source_mode,
        product=product,
        continuous_contract=continuous_contract,
        actual_contract=actual_contract,
        provider=provider,
        source=source,
        data_role=data_role,
    )
    return list(session.scalars(query.order_by(SignalEvent.created_at.desc(), SignalEvent.id.desc()).limit(limit).offset(offset)))


def count_signal_events(
    session: Session,
    **filters: Any,
) -> int:
    query = _signal_events_query(**filters)
    return int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)


def _signal_events_query(
    *,
    signal_id: int | None = None,
    task_no: str | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    source_mode: str | None = None,
    product: str | None = None,
    continuous_contract: str | None = None,
    actual_contract: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    data_role: str | None = None,
):
    query = select(SignalEvent)
    if signal_id is not None:
        query = query.where(SignalEvent.signal_id == signal_id)
    if task_no:
        query = query.where(SignalEvent.task_no == task_no)
    if symbol:
        query = query.where(SignalEvent.symbol == symbol)
    if event_type:
        query = query.where(SignalEvent.event_type == event_type)
    if source_mode:
        query = query.where(SignalEvent.source_mode == source_mode)
    if product:
        query = query.where(SignalEvent.product == product)
    if continuous_contract:
        query = query.where(SignalEvent.continuous_contract == continuous_contract)
    if actual_contract:
        query = query.where(SignalEvent.actual_contract == actual_contract)
    if provider:
        query = query.where(SignalEvent.provider == provider)
    if source:
        query = query.where(SignalEvent.source == source)
    if data_role:
        query = query.where(SignalEvent.data_role == data_role)
    return query


def signal_event_payload(event: SignalEvent) -> dict[str, Any]:
    input_identity = (event.payload or {}).get("input_identity")
    return {
        "id": event.id,
        "event_key": event.event_key,
        "event_type": event.event_type,
        "signal_id": event.signal_id,
        "task_no": event.task_no,
        "source_mode": event.source_mode,
        "strategy_name": event.strategy_name,
        "strategy_version": event.strategy_version,
        "watchlist_code": event.watchlist_code,
        "symbol": event.symbol,
        "contract": event.contract,
        "product": event.product,
        "continuous_contract": event.continuous_contract,
        "actual_contract": event.actual_contract,
        "dominant_mapping_date": event.dominant_mapping_date.isoformat() if event.dominant_mapping_date else None,
        "exchange": event.exchange,
        "period": event.period,
        "signal_time": event.signal_time.isoformat() if event.signal_time else None,
        "bar_start": event.bar_start.isoformat() if event.bar_start else None,
        "bar_end": event.bar_end.isoformat() if event.bar_end else None,
        "trigger_price": event.trigger_price,
        "provider": event.provider,
        "source": event.source,
        "direction": event.direction,
        "signal_status": event.signal_status,
        "lifecycle_status": event.lifecycle_status,
        "score_bucket": event.score_bucket,
        "data_role": event.data_role,
        "quality_status": event.quality_status,
        "profile_id": event.profile_id,
        "market_data_file_id": event.market_data_file_id,
        "input_identity": deepcopy(input_identity) if isinstance(input_identity, dict) else None,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def lifecycle_status(signal: StrategySignal) -> str:
    features = signal.features or {}
    feature_status = features.get("signal_status")
    if isinstance(feature_status, str) and feature_status:
        return feature_status
    if signal.alert_status == "acknowledged":
        return "viewed"
    if signal.alert_status == "unread":
        return "new"
    if signal.alert_status:
        return signal.alert_status
    return "new"


def _create_event_if_missing(
    session: Session,
    *,
    signal: StrategySignal,
    event_key: str,
    event_type: str,
    source_mode: str,
    task_no: str | None,
    payload_extra: dict[str, Any],
    created_at: datetime | None = None,
    lifecycle_status_value: str | None = None,
) -> SignalEvent | None:
    existing = session.scalar(select(SignalEvent).where(SignalEvent.event_key == event_key))
    if existing is not None:
        return existing
    formal_lineage = _formal_lineage(signal)
    input_identity = _input_identity(signal)
    event = SignalEvent(
        event_key=event_key,
        event_type=event_type,
        signal_id=signal.id,
        task_no=task_no,
        source_mode=source_mode,
        strategy_name=signal.strategy_name,
        strategy_version=signal.strategy_version,
        watchlist_code=signal.watchlist_code,
        symbol=signal.symbol,
        contract=signal.contract,
        product=signal.product,
        continuous_contract=signal.continuous_contract,
        actual_contract=signal.actual_contract,
        dominant_mapping_date=signal.dominant_mapping_date,
        exchange=signal.exchange,
        period=signal.period,
        signal_time=signal.signal_time,
        bar_start=signal.bar_start,
        bar_end=signal.bar_end,
        trigger_price=signal.trigger_price,
        provider=signal.provider,
        source=signal.source,
        direction=signal.direction,
        signal_status=signal.status,
        lifecycle_status=lifecycle_status_value or lifecycle_status(signal),
        score_bucket=signal.score_bucket,
        data_role=_data_role(signal),
        quality_status=_sanitize(signal.quality_status or {}),
        profile_id=signal.profile_id,
        market_data_file_id=signal.market_data_file_id,
        payload=_sanitize(
            {
                "event": {"type": event_type, "source_mode": source_mode},
                "signal": _signal_payload(signal),
                **({"formal_lineage": deepcopy(formal_lineage)} if formal_lineage else {}),
                **({"input_identity": deepcopy(input_identity)} if input_identity else {}),
                **payload_extra,
            }
        ),
        created_at=created_at or datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    return event


def _scan_event_key(signal: StrategySignal, event_type: str, task_no: str) -> str:
    if event_type == SIGNAL_CREATED:
        return f"{SIGNAL_CREATED}:{signal.dedupe_key}"
    return f"{SIGNAL_CHANGED}:{signal.dedupe_key}:{task_no}"


def _scan_source_mode(task: SignalScanTask, signal: StrategySignal) -> str:
    payload = task.request_payload or {}
    if payload.get("source_mode") == "jm_v1b_historical_replay":
        return "jm_v1b_historical_replay"
    strategy_code = payload.get("strategy_code") or (signal.features or {}).get("strategy_code")
    if strategy_code == "jm_v1b_daily_direction_fast_entry" or signal.watchlist_code == "jm_v1b":
        return "jm_v1b_scan"
    return "historical_scan"


def _data_role(signal: StrategySignal) -> str:
    if signal.data_role:
        return signal.data_role
    features = signal.features or {}
    data_role = features.get("data_role")
    return str(data_role) if data_role else "primary"


def _signal_payload(signal: StrategySignal) -> dict[str, Any]:
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
        "signal_time": signal.signal_time.isoformat() if signal.signal_time else None,
        "status": signal.status,
        "lifecycle_status": lifecycle_status(signal),
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


def _formal_lineage(signal: StrategySignal) -> dict[str, Any] | None:
    value = (signal.features or {}).get("formal_lineage")
    return value if isinstance(value, dict) else None


def _input_identity(signal: StrategySignal) -> dict[str, Any] | None:
    value = (signal.features or {}).get("input_identity")
    return value if isinstance(value, dict) else None


def _task_payload(task: SignalScanTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_no": task.task_no,
        "watchlist_code": task.watchlist_code,
        "periods": task.periods,
        "status": task.status,
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS):
                continue
            sanitized[str(key)] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    return value
