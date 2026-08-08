from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import os
from time import perf_counter
from typing import Any

from redis import Redis
from rq import Queue, Worker
from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.queue import get_redis_connection

RUNTIME_STATUS_OK = "ok"
RUNTIME_STATUS_DEGRADED = "degraded"
RUNTIME_STATUS_FAILED = "failed"
RUNTIME_STATUS_UNKNOWN = "unknown"
RUNTIME_STATUS_DISABLED = "disabled"

RUNTIME_QUEUE_NAMES: tuple[str, ...] = ()
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
    live_runtime_enabled: bool | None = None,
    notification_autosend_enabled: bool | None = None,
    live_freshness_seconds: int | None = None,
    archive_enabled: bool | None = None,
    after_market_automation_enabled: bool | None = None,
    live_polling_expected: bool | None = None,
    live_market_phase: str | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(UTC)
    # Live polling / notification / after-market archive Profile paths are permanently retired.
    del live_runtime_enabled, live_polling_expected, live_market_phase, notification_autosend_enabled
    del archive_enabled, after_market_automation_enabled
    freshness_seconds = live_freshness_seconds or _env_positive_int("GUIYI_LIVE_FRESHNESS_SECONDS", 300)
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
        if rq_collector is not None:
            components["rq"] = rq_collector(redis_connection)
        else:
            components["rq"] = _collect_rq_health(redis_connection, queue_names=RUNTIME_QUEUE_NAMES)
    components["live_checkpoints"] = _retired_live_checkpoint_health(freshness_seconds=freshness_seconds)
    components["notification_retry"] = _retired_notification_retry_health()
    components["archive"] = _retired_archive_health()
    components["after_market_scheduler"] = _retired_after_market_scheduler_health()

    return {
        "status": _overall_status(components.values()),
        "generated_at": _iso(current_time),
        "readonly": True,
        "would_start_services": False,
        "would_enqueue_jobs": False,
        "would_send_notifications": False,
        "components": components,
    }


def _retired_live_checkpoint_health(*, freshness_seconds: int) -> dict[str, Any]:
    return {
        "status": RUNTIME_STATUS_DISABLED,
        "enabled": False,
        "retired": True,
        "freshness_seconds": freshness_seconds,
        "stale": False,
        "polling_expected": False,
        "market_phase": "retired",
        "ingest_count": 0,
        "aggregation_count": 0,
        "status_counts": {},
        "latest_success_at": None,
        "latest_error": None,
        "recent_ingest": [],
        "recent_aggregation": [],
        "error_type": None,
        "error_message": None,
    }


def _retired_archive_health() -> dict[str, Any]:
    return {
        "status": RUNTIME_STATUS_DISABLED,
        "enabled": False,
        "retired": True,
        "latest_task_no": None,
        "latest_task_status": None,
        "latest_contract": None,
        "latest_finished_at": None,
        "latest_error_type": None,
        "error_type": None,
        "error_message": None,
    }


def _retired_after_market_scheduler_health() -> dict[str, Any]:
    return {
        "status": RUNTIME_STATUS_DISABLED,
        "enabled": False,
        "retired": True,
        "last_successful_trading_day": None,
        "latest_completed_trading_day": None,
        "latest_eligible_trading_day": None,
        "archive_lag_trading_days": None,
        "current_task": None,
        "last_error_type": None,
        "last_error_at": None,
        "retry_count": 0,
        "scheduler_heartbeat": None,
        "next_retry_at": None,
        "authorization_hash": None,
        "lock_status": None,
        "error_type": None,
        "error_message": None,
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


def _collect_rq_health(connection: Redis, *, queue_names: tuple[str, ...] = RUNTIME_QUEUE_NAMES) -> dict[str, Any]:
    queue_results: list[dict[str, Any]] = []
    component_status = RUNTIME_STATUS_OK

    for queue_name in queue_names:
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

    if _apply_worker_coverage(queue_results, worker_results):
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
        "worker_present": False,
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


def _apply_worker_coverage(queue_results: list[dict[str, Any]], worker_results: list[dict[str, Any]]) -> bool:
    worker_queues = {queue_name for worker in worker_results for queue_name in worker["queues"]}
    missing = False
    for queue_health in queue_results:
        queue_health["worker_present"] = queue_health["name"] in worker_queues
        if not queue_health["worker_present"]:
            queue_health["status"] = RUNTIME_STATUS_DEGRADED
            queue_health["error_type"] = "worker_missing"
            missing = True
    return missing


def _retired_notification_retry_health() -> dict[str, Any]:
    return {
        "status": RUNTIME_STATUS_DISABLED,
        "enabled": False,
        "retired": True,
        "channel": "retired",
        "total_count": 0,
        "retry_pending_count": 0,
        "due_retry_count": 0,
        "failed_count": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "pending_count": 0,
        "next_retry_at": None,
        "last_sent_at": None,
        "last_failed_at": None,
        "last_error_type_counts": {},
        "error_type": None,
        "error_message": None,
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


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _count_value(value: Any) -> int:
    return int(value() if callable(value) else value)


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
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
