"""Runtime 分层健康检查聚合服务。

健康检查分层说明：
- **真实探测**：``db``（SELECT 1）、``redis``（PING）、``rq``（队列 registry 与 worker 列表）
- **Market Runtime 只读状态**：Redis ``live:heartbeat`` 与本地盘后公开状态文件

安全与 fail-closed：
- 健康端点捕获异常并降级为 failed/degraded，不向 HTTP 层抛出原始 stack trace
- ``_safe_error_message`` 过滤含 password/token/webhook 等敏感子串的错误正文
- 顶层 ``readonly=True`` 及 ``would_*`` 标志声明本响应不授权启动服务、入队或发通知
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from redis import Redis
from rq import Queue, Worker
from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.queue import get_redis_connection
from app.core.env import PROJECT_ROOT

RUNTIME_STATUS_OK = "ok"
RUNTIME_STATUS_DEGRADED = "degraded"
RUNTIME_STATUS_FAILED = "failed"
RUNTIME_STATUS_UNKNOWN = "unknown"
RUNTIME_STATUS_DISABLED = "disabled"
DEFAULT_AFTER_MARKET_STATUS_PATH = PROJECT_ROOT / ".run" / "after-market-status.json"
MARKET_RUNTIME_ACTIVATION_MARKER_NAME = "market-runtime-enabled"
_PUBLIC_AFTER_MARKET_ERROR_CODES = frozenset(
    {
        "MAINTENANCE_LOCKED",
        "LIVE_DOMINANT_MISMATCH",
        "NON_TRADING_DAY",
        "PROVIDER_QUOTA_EXHAUSTED",
        "RQDATA_NOT_READY",
        "RQDATA_READY_CHECK_FAILED",
        "UPDATE_FAILED",
    }
)

# 当前无活跃业务队列；空元组时 RQ 健康仅枚举 worker、不检查队列积压
RUNTIME_QUEUE_NAMES: tuple[str, ...] = ()
# 错误消息脱敏：命中任一子串则 error_message 置 None（fail-closed 不泄露凭据）
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
    after_market_status_path: Path | None = DEFAULT_AFTER_MARKET_STATUS_PATH,
) -> dict[str, Any]:
    """构建 Runtime 健康快照字典（供 HTTP 与 CLI 共用）。

    真实探测 db/redis/rq，读取 Market Runtime 的公开状态。可选注入 redis_factory 与
    rq_collector 供测试替换；其余旧 Profile 参数保持兼容但不参与状态判定。
    """
    current_time = now or datetime.now(UTC)
    # 已退役参数不改变 V1 状态；live_runtime_enabled 保留为测试/本地装配可注入开关。
    # 真实启动状态来自项目固定 .run 标记，而非另一个 launchd job 的进程环境。
    del live_polling_expected, live_market_phase, notification_autosend_enabled
    del archive_enabled, after_market_automation_enabled
    freshness_seconds = live_freshness_seconds or _env_positive_int("GUIYI_LIVE_FRESHNESS_SECONDS", 300)
    components: dict[str, Any] = {}
    components["db"] = _collect_db_health(session)
    redis_connection, redis_health = _collect_redis_health(redis_factory or get_redis_connection)
    components["redis"] = redis_health

    if redis_connection is None:
        # Redis 不可达时 RQ 无法探测，直接标记 failed
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

    components["live_market"] = _collect_live_market_health(
        redis_connection,
        now=current_time,
        configured_enabled=(
            _market_runtime_activation_enabled()
            if live_runtime_enabled is None
            else live_runtime_enabled
        ),
        freshness_seconds=freshness_seconds,
    )
    components["after_market"] = _collect_after_market_health(after_market_status_path)

    return {
        "status": _overall_status(components.values()),
        "generated_at": _iso(current_time),
        "readonly": True,
        "would_start_services": False,
        "would_enqueue_jobs": False,
        "would_send_notifications": False,
        "components": components,
    }


def _market_runtime_activation_enabled() -> bool:
    """仅接受本项目显式 activation 写入的固定本地标记，任何读取异常均保持关闭。"""
    marker_path = PROJECT_ROOT / ".run" / MARKET_RUNTIME_ACTIVATION_MARKER_NAME
    try:
        return marker_path.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        return False


def _collect_live_market_health(
    connection: Redis | None,
    *,
    now: datetime,
    configured_enabled: bool,
    freshness_seconds: int,
) -> dict[str, Any]:
    """从短 TTL Redis heartbeat 读取 Live V1 状态；不创建订阅或写 Redis。"""
    empty: dict[str, Any] = {
        "configured_enabled": configured_enabled,
        "operational_count": 0,
        "subscribed_count": 0,
        "last_heartbeat_at": None,
        "last_bar_at": None,
        "phase_counts": {},
        "error_type": None,
        "error_message": None,
    }
    if connection is None:
        return {
            "status": RUNTIME_STATUS_DEGRADED if configured_enabled else RUNTIME_STATUS_DISABLED,
            **empty,
            "error_type": "redis_unavailable" if configured_enabled else None,
        }
    try:
        raw = connection.get("live:heartbeat")
    except Exception as exc:  # noqa: BLE001 - health reads must fail closed.
        return {
            "status": RUNTIME_STATUS_DEGRADED if configured_enabled else RUNTIME_STATUS_DISABLED,
            **empty,
            **(_error_fields(exc) if configured_enabled else {}),
        }
    try:
        heartbeat = _json_mapping(raw)
    except UnicodeDecodeError:
        return {
            "status": RUNTIME_STATUS_DEGRADED if configured_enabled else RUNTIME_STATUS_DISABLED,
            **empty,
            "error_type": "live_heartbeat_invalid" if configured_enabled else None,
        }
    if heartbeat is None:
        return {
            "status": RUNTIME_STATUS_DEGRADED if configured_enabled else RUNTIME_STATUS_DISABLED,
            **empty,
            "error_type": "live_heartbeat_missing" if configured_enabled else None,
        }
    try:
        heartbeat_at = _required_timestamp(heartbeat.get("generated_at"))
        operational_count = _nonnegative_int(heartbeat.get("operational_count"))
        subscribed_count = _nonnegative_int(heartbeat.get("subscribed_count"))
        last_bar_at = _optional_timestamp(heartbeat.get("last_bar_at"))
        phase_counts = _phase_counts(heartbeat.get("phase_counts"))
        available = heartbeat.get("available") is True
    except ValueError:
        return {
            "status": RUNTIME_STATUS_DEGRADED if configured_enabled else RUNTIME_STATUS_DISABLED,
            **empty,
            "error_type": "live_heartbeat_invalid" if configured_enabled else None,
        }
    payload = {
        **empty,
        "operational_count": operational_count,
        "subscribed_count": subscribed_count,
        "last_heartbeat_at": _iso(heartbeat_at),
        "last_bar_at": _iso(last_bar_at),
        "phase_counts": phase_counts,
    }
    stale = heartbeat_at > now or (now - heartbeat_at).total_seconds() > freshness_seconds
    if not configured_enabled:
        return {"status": RUNTIME_STATUS_DISABLED, **payload}
    if stale:
        return {"status": RUNTIME_STATUS_DEGRADED, **payload, "error_type": "live_heartbeat_stale"}
    if not available:
        return {"status": RUNTIME_STATUS_DEGRADED, **payload, "error_type": "live_unavailable"}
    return {"status": RUNTIME_STATUS_OK, **payload}


def _collect_after_market_health(status_path: Path | None) -> dict[str, Any]:
    """读取盘后运行的公开状态文件；不恢复任何 scheduler/checkpoint 模型。"""
    empty = {
        "last_run": None,
        "last_successful_trading_day": None,
        "last_failure": None,
        "error_type": None,
        "error_message": None,
    }
    if status_path is None or not status_path.exists():
        return {"status": RUNTIME_STATUS_DISABLED, **empty}
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": RUNTIME_STATUS_DEGRADED, **empty, "error_type": "after_market_status_invalid"}
    if not isinstance(raw, Mapping):
        return {"status": RUNTIME_STATUS_DEGRADED, **empty, "error_type": "after_market_status_invalid"}
    last_run = _public_after_market_run(raw.get("last_run"))
    last_success = _public_trading_day(raw.get("last_successful_trading_day"))
    last_failure = _public_after_market_failure(raw.get("last_failure"))
    if last_run is None and last_success is None and last_failure is None:
        return {"status": RUNTIME_STATUS_DEGRADED, **empty, "error_type": "after_market_status_invalid"}
    status = RUNTIME_STATUS_UNKNOWN
    if last_run is not None:
        status = RUNTIME_STATUS_FAILED if last_run["status"] == "failed" else RUNTIME_STATUS_OK
    return {
        "status": status,
        "last_run": last_run,
        "last_successful_trading_day": last_success,
        "last_failure": last_failure,
        "error_type": None,
        "error_message": None,
    }


def _collect_db_health(session: Session) -> dict[str, Any]:
    """真实探测：执行 SELECT 1 并记录延迟；异常时 status=failed 并脱敏 error_message。"""
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
    """真实探测：PING Redis；失败时返回 (None, failed_health) 供上层跳过 RQ。"""
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
    """真实探测：枚举队列 registry 计数与 Worker.all；单 registry 失败仅 degraded。"""
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
    """收集单队列各 JobRegistry 计数；单项失败将该队列标为 degraded。"""
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
    """检查每个配置队列是否有 worker 监听；缺失则标 degraded + worker_missing。"""
    worker_queues = {queue_name for worker in worker_results for queue_name in worker["queues"]}
    missing = False
    for queue_health in queue_results:
        queue_health["worker_present"] = queue_health["name"] in worker_queues
        if not queue_health["worker_present"]:
            queue_health["status"] = RUNTIME_STATUS_DEGRADED
            queue_health["error_type"] = "worker_missing"
            missing = True
    return missing


def _worker_payload(worker: Any) -> dict[str, Any]:
    """将 RQ Worker 对象序列化为健康响应子结构。"""
    queues = []
    for queue in getattr(worker, "queues", []) or []:
        queues.append(_to_text(getattr(queue, "name", queue)))
    return {
        "name": _to_text(getattr(worker, "name", "")) or "",
        "state": _to_text(getattr(worker, "state", None)),
        "queues": queues,
    }


def _overall_status(component_values: Any) -> str:
    """聚合子组件 status：任一 failed → failed；否则任一 degraded → degraded；否则 ok。"""
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
    """从环境变量读取正整数；无效或非正时回退 default。"""
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _json_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _required_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: object) -> datetime | None:
    return None if value is None else _required_timestamp(value)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("nonnegative integer required")
    return value


def _phase_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("phase counts required")
    result: dict[str, int] = {}
    for phase, count in value.items():
        if not isinstance(phase, str) or not phase or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("invalid phase count")
        result[phase] = count
    return result


def _public_trading_day(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _public_after_market_failure(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    trading_day = _public_trading_day(value.get("trading_day"))
    error_code = value.get("error_code")
    if trading_day is None or error_code not in _PUBLIC_AFTER_MARKET_ERROR_CODES:
        return None
    return {"trading_day": trading_day, "error_code": error_code}


def _public_after_market_run(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    trading_day = _public_trading_day(value.get("trading_day"))
    status = value.get("status")
    attempts = value.get("attempts")
    products = value.get("products")
    error_code = value.get("error_code")
    started_at_text = value.get("started_at")
    finished_at_text = value.get("finished_at")
    try:
        _required_timestamp(started_at_text)
        _required_timestamp(finished_at_text)
    except ValueError:
        return None
    if (
        trading_day is None
        or status not in {"passed", "failed", "skipped"}
        or isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or attempts < 0
        or not isinstance(products, list)
        or any(not isinstance(product, str) or not product.strip() for product in products)
        or (error_code is not None and error_code not in _PUBLIC_AFTER_MARKET_ERROR_CODES)
    ):
        return None
    return {
        "trading_day": trading_day,
        "status": status,
        "attempts": attempts,
        "started_at": started_at_text,
        "finished_at": finished_at_text,
        "products": [product.strip().lower() for product in products],
        "error_code": error_code,
    }


def _count_value(value: Any) -> int:
    """兼容 RQ count 属性为可调用或整型。"""
    return int(value() if callable(value) else value)


def _elapsed_ms(started: float) -> float:
    """perf_counter 起点至今的毫秒数（保留两位小数）。"""
    return round((perf_counter() - started) * 1000, 2)


def _error_fields(exc: Exception) -> dict[str, str | None]:
    """构造 error_type + 经脱敏的 error_message。"""
    return {
        "error_type": exc.__class__.__name__,
        "error_message": _safe_error_message(exc),
    }


def _safe_error_message(exc: Exception) -> str | None:
    """fail-closed 错误正文：空消息或含敏感子串时返回 None，否则截断至 200 字符。"""
    message = str(exc).strip()
    if not message:
        return None
    lowered = message.lower()
    if any(part in lowered for part in SENSITIVE_TEXT_PARTS):
        return None
    return message[:200]


def _iso(value: datetime | None) -> str | None:
    """datetime 转 ISO 字符串；naive 时假定 UTC。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _to_text(value: Any) -> str | None:
    """将任意值转为 str 或 None。"""
    if value is None:
        return None
    return str(value)
