from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from redis import Redis
from rq import Queue, Worker
from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.data_center import LiveAggregationCheckpoint, LiveIngestCheckpoint
from app.models.signal import SignalNotification
from app.queue import BACKTEST_QUEUE_NAME, SIGNAL_QUEUE_NAME, get_redis_connection
from app.signal.stage9_wechat import CHANNEL as STAGE9_WECHAT_CHANNEL

RUNTIME_STATUS_OK = "ok"
RUNTIME_STATUS_DEGRADED = "degraded"
RUNTIME_STATUS_FAILED = "failed"
RUNTIME_STATUS_UNKNOWN = "unknown"

RUNTIME_QUEUE_NAMES = (BACKTEST_QUEUE_NAME, SIGNAL_QUEUE_NAME)
SENSITIVE_TEXT_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "webhook",
    "cookie",
    "license",
    "key",
    "authorization",
)


def build_runtime_health(
    session: Session,
    *,
    redis_factory: Callable[[], Redis] | None = None,
    rq_collector: Callable[[Redis], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(UTC)
    components: dict[str, Any] = {}

    components["db"] = _collect_db_health(session)
    redis_connection, redis_health = _collect_redis_health(redis_factory or get_redis_connection)
    components["redis"] = redis_health

    if redis_connection is None:
        components["rq"] = {
            "status": RUNTIME_STATUS_FAILED,
            "queues": [],
            "worker_count": 0,
            "workers": [],
            "error_type": "redis_unavailable",
            "error_message": None,
        }
    else:
        components["rq"] = (rq_collector or _collect_rq_health)(redis_connection)

    if components["db"]["status"] == RUNTIME_STATUS_FAILED:
        db_error = {
            "status": RUNTIME_STATUS_FAILED,
            "error_type": "database_unavailable",
            "error_message": None,
        }
        components["live_checkpoints"] = {
            **db_error,
            "ingest_count": 0,
            "aggregation_count": 0,
            "status_counts": {},
            "latest_success_at": None,
            "latest_error": None,
            "recent_ingest": [],
            "recent_aggregation": [],
        }
        components["notification_retry"] = {
            **db_error,
            "channel": STAGE9_WECHAT_CHANNEL,
            "total_count": 0,
            "retry_pending_count": 0,
            "due_retry_count": 0,
            "failed_count": 0,
            "sent_count": 0,
            "skipped_count": 0,
            "pending_count": 0,
            "next_retry_at": None,
            "last_error_type_counts": {},
        }
    else:
        components["live_checkpoints"] = _collect_live_checkpoint_health(session)
        components["notification_retry"] = _collect_notification_retry_health(session, current_time)

    return {
        "status": _overall_status(components.values()),
        "generated_at": _iso(current_time),
        "readonly": True,
        "would_start_services": False,
        "would_enqueue_jobs": False,
        "would_send_notifications": False,
        "components": components,
    }


def _collect_db_health(session: Session) -> dict[str, Any]:
    started = perf_counter()
    try:
        session.execute(text("select 1")).scalar_one()
    except Exception as exc:  # noqa: BLE001 - health endpoints must degrade instead of raising.
        return {
            "status": RUNTIME_STATUS_FAILED,
            "latency_ms": _elapsed_ms(started),
            **_error_fields(exc),
        }
    return {
        "status": RUNTIME_STATUS_OK,
        "latency_ms": _elapsed_ms(started),
        "error_type": None,
        "error_message": None,
    }


def _collect_redis_health(redis_factory: Callable[[], Redis]) -> tuple[Redis | None, dict[str, Any]]:
    started = perf_counter()
    try:
        connection = redis_factory()
        connection.ping()
    except Exception as exc:  # noqa: BLE001 - health endpoints must degrade instead of raising.
        return None, {
            "status": RUNTIME_STATUS_FAILED,
            "latency_ms": _elapsed_ms(started),
            **_error_fields(exc),
        }
    return connection, {
        "status": RUNTIME_STATUS_OK,
        "latency_ms": _elapsed_ms(started),
        "error_type": None,
        "error_message": None,
    }


def _collect_rq_health(connection: Redis) -> dict[str, Any]:
    queue_results: list[dict[str, Any]] = []
    component_status = RUNTIME_STATUS_OK

    for queue_name in RUNTIME_QUEUE_NAMES:
        queue = Queue(queue_name, connection=connection)
        queue_health = _collect_queue_health(queue)
        queue_results.append(queue_health)
        if queue_health["status"] != RUNTIME_STATUS_OK:
            component_status = RUNTIME_STATUS_DEGRADED

    try:
        workers = list(Worker.all(connection=connection))
        worker_results = [_worker_payload(worker) for worker in workers]
    except Exception as exc:  # noqa: BLE001 - health endpoints must degrade instead of raising.
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            "queues": queue_results,
            "worker_count": 0,
            "workers": [],
            **_error_fields(exc),
        }

    if not workers and component_status == RUNTIME_STATUS_OK:
        component_status = RUNTIME_STATUS_DEGRADED

    return {
        "status": component_status,
        "queues": queue_results,
        "worker_count": len(workers),
        "workers": worker_results,
        "error_type": None,
        "error_message": None,
    }


def _collect_queue_health(queue: Queue) -> dict[str, Any]:
    payload = {
        "name": queue.name,
        "status": RUNTIME_STATUS_OK,
        "queued_count": 0,
        "started_count": 0,
        "failed_count": 0,
        "deferred_count": 0,
        "scheduled_count": 0,
        "error_type": None,
    }
    registry_specs = {
        "queued_count": lambda: _count_value(queue.count),
        "started_count": lambda: _count_value(StartedJobRegistry(queue=queue).count),
        "failed_count": lambda: _count_value(FailedJobRegistry(queue=queue).count),
        "deferred_count": lambda: _count_value(DeferredJobRegistry(queue=queue).count),
        "scheduled_count": lambda: _count_value(ScheduledJobRegistry(queue=queue).count),
    }
    for field_name, collector in registry_specs.items():
        try:
            payload[field_name] = collector()
        except Exception as exc:  # noqa: BLE001 - one registry should not break the health endpoint.
            payload["status"] = RUNTIME_STATUS_DEGRADED
            payload["error_type"] = exc.__class__.__name__
    return payload


def _collect_live_checkpoint_health(session: Session) -> dict[str, Any]:
    try:
        ingest_count = session.scalar(select(func.count()).select_from(LiveIngestCheckpoint)) or 0
        aggregation_count = session.scalar(select(func.count()).select_from(LiveAggregationCheckpoint)) or 0
        status_counts = _checkpoint_status_counts(session)
        latest_success_at = _max_datetime(
            session.scalar(select(func.max(LiveIngestCheckpoint.last_success_at))),
            session.scalar(select(func.max(LiveAggregationCheckpoint.last_success_at))),
        )
        latest_error = _latest_checkpoint_error(session)
        recent_ingest = [
            _ingest_checkpoint_payload(row)
            for row in session.scalars(select(LiveIngestCheckpoint).order_by(LiveIngestCheckpoint.updated_at.desc(), LiveIngestCheckpoint.id.desc()).limit(5))
        ]
        recent_aggregation = [
            _aggregation_checkpoint_payload(row)
            for row in session.scalars(
                select(LiveAggregationCheckpoint).order_by(LiveAggregationCheckpoint.updated_at.desc(), LiveAggregationCheckpoint.id.desc()).limit(5)
            )
        ]
    except Exception as exc:  # noqa: BLE001 - health endpoints must degrade instead of raising.
        return {
            "status": RUNTIME_STATUS_FAILED,
            "ingest_count": 0,
            "aggregation_count": 0,
            "status_counts": {},
            "latest_success_at": None,
            "latest_error": None,
            "recent_ingest": [],
            "recent_aggregation": [],
            **_error_fields(exc),
        }

    total_count = ingest_count + aggregation_count
    status = RUNTIME_STATUS_UNKNOWN if total_count == 0 else RUNTIME_STATUS_OK
    if status_counts.get("failed", 0) > 0:
        status = RUNTIME_STATUS_DEGRADED

    return {
        "status": status,
        "ingest_count": ingest_count,
        "aggregation_count": aggregation_count,
        "status_counts": status_counts,
        "latest_success_at": _iso(latest_success_at),
        "latest_error": latest_error,
        "recent_ingest": recent_ingest,
        "recent_aggregation": recent_aggregation,
        "error_type": None,
        "error_message": None,
    }


def _collect_notification_retry_health(session: Session, now: datetime) -> dict[str, Any]:
    try:
        status_counts = {
            status: count
            for status, count in session.execute(
                select(SignalNotification.status, func.count())
                .where(SignalNotification.channel == STAGE9_WECHAT_CHANNEL)
                .group_by(SignalNotification.status)
            )
        }
        total_count = sum(status_counts.values())
        due_retry_count = session.scalar(
            select(func.count())
            .select_from(SignalNotification)
            .where(
                SignalNotification.channel == STAGE9_WECHAT_CHANNEL,
                SignalNotification.status == "retry_pending",
                SignalNotification.next_retry_at <= now,
            )
        ) or 0
        next_retry_at = session.scalar(
            select(func.min(SignalNotification.next_retry_at)).where(
                SignalNotification.channel == STAGE9_WECHAT_CHANNEL,
                SignalNotification.status == "retry_pending",
                SignalNotification.next_retry_at.is_not(None),
            )
        )
        error_type_counts = {
            error_type: count
            for error_type, count in session.execute(
                select(SignalNotification.last_error_type, func.count())
                .where(
                    SignalNotification.channel == STAGE9_WECHAT_CHANNEL,
                    SignalNotification.last_error_type.is_not(None),
                )
                .group_by(SignalNotification.last_error_type)
            )
        }
    except Exception as exc:  # noqa: BLE001 - health endpoints must degrade instead of raising.
        return {
            "status": RUNTIME_STATUS_FAILED,
            "channel": STAGE9_WECHAT_CHANNEL,
            "total_count": 0,
            "retry_pending_count": 0,
            "due_retry_count": 0,
            "failed_count": 0,
            "sent_count": 0,
            "skipped_count": 0,
            "pending_count": 0,
            "next_retry_at": None,
            "last_error_type_counts": {},
            **_error_fields(exc),
        }

    status = RUNTIME_STATUS_UNKNOWN if total_count == 0 else RUNTIME_STATUS_OK
    if due_retry_count > 0:
        status = RUNTIME_STATUS_DEGRADED

    return {
        "status": status,
        "channel": STAGE9_WECHAT_CHANNEL,
        "total_count": total_count,
        "retry_pending_count": status_counts.get("retry_pending", 0),
        "due_retry_count": due_retry_count,
        "failed_count": status_counts.get("failed", 0),
        "sent_count": status_counts.get("sent", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "pending_count": status_counts.get("pending", 0),
        "next_retry_at": _iso(next_retry_at),
        "last_error_type_counts": error_type_counts,
        "error_type": None,
        "error_message": None,
    }


def _checkpoint_status_counts(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in (LiveIngestCheckpoint, LiveAggregationCheckpoint):
        for status, count in session.execute(select(model.status, func.count()).group_by(model.status)):
            key = status or RUNTIME_STATUS_UNKNOWN
            counts[key] = counts.get(key, 0) + int(count)
    return counts


def _latest_checkpoint_error(session: Session) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    ingest_error = session.scalar(
        select(LiveIngestCheckpoint)
        .where(LiveIngestCheckpoint.last_error_type.is_not(None))
        .order_by(LiveIngestCheckpoint.updated_at.desc(), LiveIngestCheckpoint.id.desc())
        .limit(1)
    )
    aggregation_error = session.scalar(
        select(LiveAggregationCheckpoint)
        .where(LiveAggregationCheckpoint.last_error_type.is_not(None))
        .order_by(LiveAggregationCheckpoint.updated_at.desc(), LiveAggregationCheckpoint.id.desc())
        .limit(1)
    )
    if ingest_error is not None:
        candidates.append(_checkpoint_error_payload("ingest", ingest_error))
    if aggregation_error is not None:
        candidates.append(_checkpoint_error_payload("aggregation", aggregation_error))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get("updated_at") or "")


def _checkpoint_error_payload(kind: str, checkpoint: LiveIngestCheckpoint | LiveAggregationCheckpoint) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": checkpoint.id,
        "contract_code": checkpoint.contract_code,
        "period": checkpoint.period,
        "status": checkpoint.status,
        "last_error_type": checkpoint.last_error_type,
        "updated_at": _iso(checkpoint.updated_at),
    }


def _ingest_checkpoint_payload(checkpoint: LiveIngestCheckpoint) -> dict[str, Any]:
    return {
        "id": checkpoint.id,
        "provider": checkpoint.provider,
        "instrument_symbol": checkpoint.instrument_symbol,
        "contract_code": checkpoint.contract_code,
        "period": checkpoint.period,
        "source_mode": checkpoint.source_mode,
        "status": checkpoint.status,
        "lag_seconds": checkpoint.lag_seconds,
        "consecutive_error_count": checkpoint.consecutive_error_count,
        "last_success_at": _iso(checkpoint.last_success_at),
        "last_run_at": _iso(checkpoint.last_polled_at),
        "last_bar_at": _iso(checkpoint.last_confirmed_bar_at),
        "last_error_type": checkpoint.last_error_type,
        "updated_at": _iso(checkpoint.updated_at),
    }


def _aggregation_checkpoint_payload(checkpoint: LiveAggregationCheckpoint) -> dict[str, Any]:
    return {
        "id": checkpoint.id,
        "provider": checkpoint.provider,
        "instrument_symbol": checkpoint.instrument_symbol,
        "contract_code": checkpoint.contract_code,
        "period": checkpoint.period,
        "source_mode": checkpoint.source_mode,
        "status": checkpoint.status,
        "lag_seconds": checkpoint.lag_seconds,
        "consecutive_error_count": checkpoint.consecutive_error_count,
        "last_success_at": _iso(checkpoint.last_success_at),
        "last_run_at": _iso(checkpoint.last_run_at),
        "last_bar_at": _iso(checkpoint.last_aggregated_bar_at),
        "last_error_type": checkpoint.last_error_type,
        "updated_at": _iso(checkpoint.updated_at),
    }


def _worker_payload(worker: Worker) -> dict[str, Any]:
    queues = []
    for queue in getattr(worker, "queues", []) or []:
        queues.append(_to_text(getattr(queue, "name", queue)))
    return {
        "name": _to_text(getattr(worker, "name", "")) or "",
        "state": _to_text(getattr(worker, "state", None)),
        "queues": queues,
    }


def _overall_status(component_values: Any) -> str:
    has_failed = False
    has_degraded = False
    for component in component_values:
        status = component.get("status")
        if status == RUNTIME_STATUS_FAILED:
            has_failed = True
        elif status == RUNTIME_STATUS_DEGRADED:
            has_degraded = True
    if has_failed:
        return RUNTIME_STATUS_FAILED
    if has_degraded:
        return RUNTIME_STATUS_DEGRADED
    return RUNTIME_STATUS_OK


def _count_value(value: Any) -> int:
    return int(value() if callable(value) else value)


def _max_datetime(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)


def _error_fields(exc: Exception) -> dict[str, str | None]:
    return {
        "error_type": exc.__class__.__name__,
        "error_message": _safe_error_message(exc),
    }


def _safe_error_message(exc: Exception) -> str | None:
    message = str(exc).strip()
    if not message:
        return None
    lowered = message.lower()
    if any(part in lowered for part in SENSITIVE_TEXT_PARTS):
        return None
    return message[:200]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat()


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
