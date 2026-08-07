from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
import os
from time import perf_counter
from typing import Any

from redis import Redis
from rq import Queue, Worker
from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.data_center import (
    AfterMarketSchedulerCheckpoint,
    DataDownloadTask,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.models.signal import SignalNotification
from app.queue import NOTIFICATION_QUEUE_NAME, SIGNAL_QUEUE_NAME, get_redis_connection
from app.after_market_scheduler import HEARTBEAT_KEY as AFTER_MARKET_HEARTBEAT_KEY
from app.services.after_market_automation import discover_eligible_trading_days
from app.services.trading_session_clock import TradingSessionClock
from app.signal.stage9_wechat import CHANNEL as STAGE9_WECHAT_CHANNEL

RUNTIME_STATUS_OK = "ok"
RUNTIME_STATUS_DEGRADED = "degraded"
RUNTIME_STATUS_FAILED = "failed"
RUNTIME_STATUS_UNKNOWN = "unknown"
RUNTIME_STATUS_DISABLED = "disabled"

RUNTIME_QUEUE_NAMES = (SIGNAL_QUEUE_NAME,)
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
    # Live polling / checkpoint runtime is permanently retired (Task06 cleanup).
    del live_runtime_enabled, live_polling_expected, live_market_phase
    notification_enabled = (
        _env_enabled("GUIYI_WECHAT_AUTOSEND_ENABLED")
        if notification_autosend_enabled is None
        else notification_autosend_enabled
    )
    freshness_seconds = live_freshness_seconds or _env_positive_int("GUIYI_LIVE_FRESHNESS_SECONDS", 300)
    after_market_archive_enabled = (
        _env_enabled("GUIYI_AFTER_MARKET_ARCHIVE_ENABLED") if archive_enabled is None else archive_enabled
    )
    automation_enabled = (
        _env_enabled("GUIYI_AFTER_MARKET_AUTOMATION_ENABLED")
        if after_market_automation_enabled is None
        else after_market_automation_enabled
    )
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
            queue_names = RUNTIME_QUEUE_NAMES + ((NOTIFICATION_QUEUE_NAME,) if notification_enabled else ())
            components["rq"] = _collect_rq_health(redis_connection, queue_names=queue_names)
    components["live_checkpoints"] = _retired_live_checkpoint_health(freshness_seconds=freshness_seconds)
    if components["db"]["status"] == RUNTIME_STATUS_FAILED:
        db_error = {
            "status": RUNTIME_STATUS_FAILED,
            "error_type": "database_unavailable",
            "error_message": None,
        }
        components["notification_retry"] = {
            **db_error,
            "enabled": notification_enabled,
            "channel": STAGE9_WECHAT_CHANNEL,
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
        }
        components["archive"] = {
            **db_error,
            "enabled": after_market_archive_enabled,
            "latest_task_no": None,
            "latest_task_status": None,
            "latest_contract": None,
            "latest_finished_at": None,
            "latest_error_type": None,
        }
        components["after_market_scheduler"] = _empty_after_market_scheduler_health(
            enabled=automation_enabled,
            status=RUNTIME_STATUS_FAILED,
            error_type="database_unavailable",
        )
    else:
        components["notification_retry"] = _collect_notification_retry_health(
            session,
            current_time,
            enabled=notification_enabled,
        )
        components["archive"] = _collect_archive_health(session, enabled=after_market_archive_enabled)
        components["after_market_scheduler"] = _collect_after_market_scheduler_health(
            session,
            connection=redis_connection,
            now=current_time,
            enabled=automation_enabled,
        )

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


def _collect_notification_retry_health(session: Session, now: datetime, *, enabled: bool) -> dict[str, Any]:
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
        last_sent_at = session.scalar(
            select(func.max(SignalNotification.sent_at)).where(
                SignalNotification.channel == STAGE9_WECHAT_CHANNEL,
                SignalNotification.status == "sent",
            )
        )
        last_failed_at = session.scalar(
            select(func.max(SignalNotification.last_attempt_at)).where(
                SignalNotification.channel == STAGE9_WECHAT_CHANNEL,
                SignalNotification.status == "failed",
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
            "enabled": enabled,
            "channel": STAGE9_WECHAT_CHANNEL,
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
            **_error_fields(exc),
        }

    status = RUNTIME_STATUS_DISABLED if not enabled else RUNTIME_STATUS_OK
    if enabled and (due_retry_count > 0 or status_counts.get("failed", 0) > 0):
        status = RUNTIME_STATUS_DEGRADED

    return {
        "status": status,
        "enabled": enabled,
        "channel": STAGE9_WECHAT_CHANNEL,
        "total_count": total_count,
        "retry_pending_count": status_counts.get("retry_pending", 0),
        "due_retry_count": due_retry_count,
        "failed_count": status_counts.get("failed", 0),
        "sent_count": status_counts.get("sent", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "pending_count": status_counts.get("pending", 0),
        "next_retry_at": _iso(next_retry_at),
        "last_sent_at": _iso(last_sent_at),
        "last_failed_at": _iso(last_failed_at),
        "last_error_type_counts": error_type_counts,
        "error_type": None,
        "error_message": None,
    }


def _collect_archive_health(session: Session, *, enabled: bool) -> dict[str, Any]:
    try:
        latest = session.scalar(
            select(DataDownloadTask)
            .where(DataDownloadTask.data_type == "after_market_archive")
            .order_by(DataDownloadTask.created_at.desc(), DataDownloadTask.id.desc())
            .limit(1)
        )
    except Exception as exc:  # noqa: BLE001 - health endpoints must degrade instead of raising.
        return {
            "status": RUNTIME_STATUS_FAILED,
            "enabled": enabled,
            "latest_task_no": None,
            "latest_task_status": None,
            "latest_contract": None,
            "latest_finished_at": None,
            "latest_error_type": None,
            **_error_fields(exc),
        }

    if not enabled:
        status = RUNTIME_STATUS_DISABLED
    elif latest is None or latest.status in {"failed", "running", "pending"}:
        status = RUNTIME_STATUS_DEGRADED
    else:
        status = RUNTIME_STATUS_OK
    result = latest.result if latest is not None and isinstance(latest.result, dict) else {}
    return {
        "status": status,
        "enabled": enabled,
        "latest_task_no": latest.task_no if latest is not None else None,
        "latest_task_status": latest.status if latest is not None else None,
        "latest_contract": latest.contract_code if latest is not None else None,
        "latest_finished_at": _iso(latest.finished_at) if latest is not None else None,
        "latest_error_type": result.get("error_type"),
        "error_type": None,
        "error_message": None,
    }


def _collect_after_market_scheduler_health(
    session: Session,
    *,
    connection: Redis | None,
    now: datetime,
    enabled: bool,
    clock: TradingSessionClock | None = None,
) -> dict[str, Any]:
    if not enabled:
        return _empty_after_market_scheduler_health(enabled=False, status=RUNTIME_STATUS_DISABLED)
    checkpoint = session.scalar(
        select(AfterMarketSchedulerCheckpoint).where(AfterMarketSchedulerCheckpoint.product == "jm")
    )
    if checkpoint is None:
        return _empty_after_market_scheduler_health(
            enabled=True,
            status=RUNTIME_STATUS_DEGRADED,
            error_type="checkpoint_missing",
        )
    heartbeat = _after_market_heartbeat(connection, now)
    try:
        eligibility = discover_eligible_trading_days(
            last_successful_trading_day=checkpoint.last_successful_trading_day,
            now=now,
            clock=clock or TradingSessionClock(session),
            product=checkpoint.product,
            exchange=checkpoint.exchange_code,
        )
        eligibility_error = None
    except Exception as exc:  # noqa: BLE001 - health remains read-only and bounded.
        eligibility = None
        eligibility_error = type(exc).__name__
    active_end, active_details = _after_market_active_binding_end(session)
    status = RUNTIME_STATUS_OK
    heartbeat_health = heartbeat.get("health_status") or heartbeat.get("status")
    if heartbeat_health in {RUNTIME_STATUS_FAILED, RUNTIME_STATUS_DEGRADED}:
        status = heartbeat_health
    if checkpoint.status in {"retry_wait", "waiting_provider", "running"} or active_end is None:
        status = RUNTIME_STATUS_DEGRADED
    if checkpoint.status == "blocked" or eligibility_error:
        status = RUNTIME_STATUS_FAILED
    return {
        "status": status,
        "enabled": True,
        "last_successful_trading_day": _date_iso(checkpoint.last_successful_trading_day),
        "latest_completed_trading_day": (
            _date_iso(eligibility.latest_completed_trading_day) if eligibility is not None else None
        ),
        "latest_eligible_trading_day": (
            _date_iso(eligibility.latest_eligible_trading_day) if eligibility is not None else None
        ),
        "archive_lag_trading_days": eligibility.archive_lag_trading_days if eligibility is not None else None,
        "current_task": (
            f"archive:{checkpoint.product}:{checkpoint.current_trading_day.isoformat()}"
            if checkpoint.current_trading_day
            else None
        ),
        "last_error_type": checkpoint.last_error_type,
        "last_error_at": _iso(checkpoint.last_error_at) if checkpoint.last_error_at else None,
        "retry_count": checkpoint.retry_count,
        "scheduler_heartbeat": heartbeat,
        "active_binding_end": active_end,
        "active_binding_ends": active_details,
        "next_retry_at": _iso(checkpoint.next_retry_at) if checkpoint.next_retry_at else None,
        "authorization_hash": checkpoint.authorization_hash,
        "lock_status": heartbeat.get("lock_status"),
        "error_type": eligibility_error,
        "error_message": None,
    }


def _empty_after_market_scheduler_health(
    *,
    enabled: bool,
    status: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "enabled": enabled,
        "last_successful_trading_day": None,
        "latest_completed_trading_day": None,
        "latest_eligible_trading_day": None,
        "archive_lag_trading_days": None,
        "current_task": None,
        "last_error_type": None,
        "last_error_at": None,
        "retry_count": 0,
        "scheduler_heartbeat": None,
        "active_binding_end": None,
        "active_binding_ends": [],
        "next_retry_at": None,
        "authorization_hash": None,
        "lock_status": None,
        "error_type": error_type,
        "error_message": None,
    }


def _after_market_heartbeat(connection: Redis | None, now: datetime) -> dict[str, Any]:
    if connection is None:
        return {"status": RUNTIME_STATUS_FAILED, "error_type": "redis_unavailable", "lock_status": None}
    try:
        raw = connection.get(AFTER_MARKET_HEARTBEAT_KEY)
        if raw is None:
            return {"status": RUNTIME_STATUS_DEGRADED, "error_type": "heartbeat_missing", "lock_status": None}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(str(raw))
        heartbeat_at = datetime.fromisoformat(str(payload["generated_at"]))
        age = _age_seconds(now, heartbeat_at)
        state = str(payload.get("status") or RUNTIME_STATUS_UNKNOWN)
        pid = payload.get("pid")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
        ):
            pid = None
        health_status = RUNTIME_STATUS_OK if age <= 180 and state != "failed" else RUNTIME_STATUS_DEGRADED
        return {
            "status": state if state in {"retry_wait", "waiting_provider", "running", "idle", "success"} else health_status,
            "health_status": health_status,
            "heartbeat_at": _iso(heartbeat_at),
            "heartbeat_age_seconds": age,
            "error_type": payload.get("error_type"),
            "lock_status": payload.get("lock_status"),
            "pid": pid,
        }
    except Exception as exc:  # noqa: BLE001 - malformed heartbeat degrades safely.
        return {"status": RUNTIME_STATUS_DEGRADED, "error_type": type(exc).__name__, "lock_status": None}


def _after_market_active_binding_end(session: Session) -> tuple[str | None, list[dict[str, Any]]]:
    required = {
        ("intraday_research_v1", "1m"),
        ("intraday_research_v1", "5m"),
        ("intraday_research_v1", "15m"),
        ("live_observation_v1", "1m"),
        ("live_observation_v1", "5m"),
        ("live_observation_v1", "15m"),
        ("long_horizon_daily_v1", "1d"),
    }
    rows = session.execute(
        select(ProfileActiveBinding, MarketDataFile)
        .join(MarketDataFile, MarketDataFile.id == ProfileActiveBinding.market_data_file_id)
        .where(
            ProfileActiveBinding.instrument_symbol == "jm",
            ProfileActiveBinding.binding_status == "active",
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
        )
    ).all()
    latest_by_identity: dict[tuple[str, str], tuple[ProfileActiveBinding, MarketDataFile]] = {}
    for binding, market_file in rows:
        identity = (binding.profile_id, binding.period)
        if identity not in required:
            continue
        current = latest_by_identity.get(identity)
        candidate_rank = (market_file.end_time, binding.activated_at, binding.id)
        if current is None:
            latest_by_identity[identity] = (binding, market_file)
            continue
        current_binding, current_file = current
        current_rank = (current_file.end_time, current_binding.activated_at, current_binding.id)
        if candidate_rank > current_rank:
            latest_by_identity[identity] = (binding, market_file)
    details = [
        {
            "profile_id": binding.profile_id,
            "contract": binding.contract_code,
            "period": binding.period,
            "end": market_file.end_time.date().isoformat(),
        }
        for binding, market_file in latest_by_identity.values()
    ]
    identities = {(row["profile_id"], row["period"]) for row in details}
    if identities != required:
        return None, sorted(details, key=lambda row: (row["profile_id"], row["period"]))
    return min(row["end"] for row in details), sorted(details, key=lambda row: (row["profile_id"], row["period"]))


def _date_iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


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


def _env_enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _age_seconds(now: datetime, value: datetime) -> int:
    left = now
    right = value
    if left.tzinfo is None and right.tzinfo is not None:
        left = left.replace(tzinfo=UTC)
    elif left.tzinfo is not None and right.tzinfo is None:
        right = right.replace(tzinfo=UTC)
    return max(0, int((left - right).total_seconds()))


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
        return value.isoformat()
    return value.astimezone(UTC).isoformat()


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
