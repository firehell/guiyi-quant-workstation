"""Runtime 分层健康检查聚合服务。

健康检查分层说明：
- **真实探测**：``db``（SELECT 1）、``redis``（PING）
- **Market Runtime 只读状态**：Redis ``live:heartbeat`` 与本地盘后公开状态文件

安全与 fail-closed：
- 健康端点捕获异常并降级为 failed/degraded，不向 HTTP 层抛出原始 stack trace
- 公共 health 只返回稳定 ``error_type``，不返回原始异常正文
- 顶层 ``readonly=True`` 及 ``would_*`` 标志声明本响应不授权启动服务、入队或发通知
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.alerts.notification_composition import notification_transport_status_from_env
from app.alerts.notification_config import NOTIFICATION_CONFIG_ENV
from app.alerts.pushplus import PUSHPLUS_TRANSPORT
from app.alerts.runtime import validate_alert_runtime_status
from app.redis_connections import get_redis_connection
from app.core.env import PROJECT_ROOT
from app.market_data.after_market import public_after_market_status

RUNTIME_STATUS_OK = "ok"
RUNTIME_STATUS_DEGRADED = "degraded"
RUNTIME_STATUS_FAILED = "failed"
RUNTIME_STATUS_UNKNOWN = "unknown"
RUNTIME_STATUS_DISABLED = "disabled"
RUNTIME_STATUS_PENDING = "pending"
DEFAULT_AFTER_MARKET_STATUS_PATH = PROJECT_ROOT / ".run" / "after-market-status.json"
MARKET_RUNTIME_ACTIVATION_MARKER_NAME = "market-runtime-enabled"
ALERT_RUNTIME_ACTIVATION_MARKER_NAME = "alert-runtime-enabled"


def build_runtime_health(
    session: Session,
    *,
    redis_factory: Callable[[], Redis] | None = None,
    now: datetime | None = None,
    live_runtime_enabled: bool | None = None,
    live_freshness_seconds: int | None = None,
    after_market_automation_enabled: bool | None = None,
    alert_runtime_enabled: bool | None = None,
    notification_transport_configured: bool | None = None,
    alert_freshness_seconds: int = 30,
    after_market_status_path: Path | None = DEFAULT_AFTER_MARKET_STATUS_PATH,
) -> dict[str, Any]:
    """构建 Runtime 健康快照字典（供 HTTP 与 CLI 共用）。

    真实探测 db/redis，读取 Market Runtime 的公开状态。可选注入 redis_factory 供测试替换。
    """
    current_time = now or datetime.now(UTC)
    # live_runtime_enabled 保留为测试/本地装配可注入开关。
    # 真实启动状态来自项目固定 .run 标记，而非另一个 launchd job 的进程环境。
    freshness_seconds = live_freshness_seconds or _env_positive_int("GUIYI_LIVE_FRESHNESS_SECONDS", 300)
    activation_enabled = _market_runtime_activation_enabled()
    live_enabled = activation_enabled if live_runtime_enabled is None else live_runtime_enabled
    after_market_enabled = (
        activation_enabled
        if after_market_automation_enabled is None
        else after_market_automation_enabled
    )
    alert_enabled = (
        _alert_runtime_activation_enabled()
        if alert_runtime_enabled is None
        else alert_runtime_enabled
    )
    if notification_transport_configured is None:
        transport_present = bool(os.getenv(NOTIFICATION_CONFIG_ENV, ""))
        notification = notification_transport_status_from_env()
        transport_configured = notification["configured"] is True
        transport_error_type = (
            None
            if transport_configured
            else "alert_notification_transport_invalid"
            if transport_present
            else "alert_notification_transport_missing"
        )
    else:
        transport_configured = notification_transport_configured
        notification = {
            "transport": PUSHPLUS_TRANSPORT,
            "configured": transport_configured,
            "audience_count": 2,
            "would_send": False,
        }
        transport_error_type = (
            None
            if transport_configured
            else "alert_notification_transport_missing"
        )
    components: dict[str, Any] = {}
    components["db"] = _collect_db_health(session)
    redis_connection, redis_health = _collect_redis_health(redis_factory or get_redis_connection)
    components["redis"] = redis_health

    components["live_market"] = _collect_live_market_health(
        redis_connection,
        now=current_time,
        configured_enabled=live_enabled,
        freshness_seconds=freshness_seconds,
    )
    components["after_market"] = _collect_after_market_health(
        after_market_status_path,
        configured_enabled=after_market_enabled,
    )
    components["alert"] = _collect_alert_health(
        redis_connection,
        now=current_time,
        configured_enabled=alert_enabled,
        notification=notification,
        transport_error_type=transport_error_type,
        freshness_seconds=alert_freshness_seconds,
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


def _market_runtime_activation_enabled() -> bool:
    """仅接受本项目显式 activation 写入的固定本地标记，任何读取异常均保持关闭。"""
    marker_path = PROJECT_ROOT / ".run" / MARKET_RUNTIME_ACTIVATION_MARKER_NAME
    try:
        return marker_path.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        return False


def _alert_runtime_activation_enabled() -> bool:
    """Alert activation 与 Market marker 严格分离，读取异常时保持关闭。"""
    marker_path = PROJECT_ROOT / ".run" / ALERT_RUNTIME_ACTIVATION_MARKER_NAME
    try:
        return marker_path.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        return False


def _collect_alert_health(
    connection: Redis | None,
    *,
    now: datetime,
    configured_enabled: bool,
    notification: dict[str, object],
    transport_error_type: str | None,
    freshness_seconds: int,
) -> dict[str, Any]:
    empty = {
        "configured_enabled": configured_enabled,
        "notification": notification,
        "last_heartbeat_at": None,
        "enabled_rule_count": 0,
        "scope_product_count": 0,
        "processing_state": "unobserved",
        "notification_state": "unobserved",
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        "error_type": None,
    }
    if not configured_enabled:
        return {"status": RUNTIME_STATUS_DISABLED, **empty}
    if notification["configured"] is not True:
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **empty,
            "error_type": transport_error_type
            or "alert_notification_transport_missing",
        }
    if connection is None:
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **empty,
            "error_type": "redis_unavailable",
        }
    try:
        heartbeat = _json_mapping(connection.get("alert:heartbeat"))
    except Exception:  # noqa: BLE001 - public health stays sanitized
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **empty,
            "error_type": "alert_heartbeat_invalid",
        }
    if heartbeat is None:
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **empty,
            "error_type": "alert_heartbeat_missing",
        }
    try:
        heartbeat_at = _required_timestamp(heartbeat.get("generated_at"))
        enabled_rule_count = _nonnegative_int(heartbeat.get("enabled_rule_count"))
        scope_product_count = _nonnegative_int(heartbeat.get("scope_product_count"))
        available = heartbeat.get("available") is True
    except ValueError:
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **empty,
            "error_type": "alert_heartbeat_invalid",
        }
    payload = {
        **empty,
        "last_heartbeat_at": _iso(heartbeat_at),
        "enabled_rule_count": enabled_rule_count,
        "scope_product_count": scope_product_count,
    }
    stale = heartbeat_at > now or (now - heartbeat_at).total_seconds() > freshness_seconds
    if stale:
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **payload,
            "error_type": "alert_heartbeat_stale",
        }
    if not available:
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **payload,
            "error_type": "alert_unavailable",
        }
    try:
        runtime_status = _runtime_status_mapping(
            connection.get("alert:runtime-status")
        )
        if runtime_status is not None:
            runtime_status = validate_alert_runtime_status(runtime_status)
    except Exception:  # noqa: BLE001 - public health stays sanitized
        return {
            "status": RUNTIME_STATUS_DEGRADED,
            **payload,
            "error_type": "alert_runtime_status_invalid",
        }
    if runtime_status is None:
        return {"status": RUNTIME_STATUS_OK, **payload}
    observation = _alert_runtime_observation(runtime_status)
    observed_status = (
        RUNTIME_STATUS_DEGRADED
        if "failed"
        in {observation["processing_state"], observation["notification_state"]}
        else RUNTIME_STATUS_OK
    )
    return {"status": observed_status, **payload, **observation}


def _alert_runtime_observation(
    runtime_status: Mapping[str, object],
) -> dict[str, object]:
    processing_success = _optional_timestamp(
        runtime_status["last_processing_success_at"]
    )
    processing_failure = _optional_timestamp(
        runtime_status["last_processing_failure_at"]
    )
    if processing_success is None and processing_failure is None:
        processing_state = "unobserved"
    elif processing_failure is not None and (
        processing_success is None or processing_failure >= processing_success
    ):
        processing_state = "failed"
    else:
        processing_state = "ok"

    provider_accepted = _optional_timestamp(
        runtime_status["last_provider_accepted_at"]
    )
    notification_failure = _optional_timestamp(
        runtime_status["last_notification_failure_at"]
    )
    if provider_accepted is None and notification_failure is None:
        notification_state = "unobserved"
    elif notification_failure is not None and (
        provider_accepted is None or notification_failure >= provider_accepted
    ):
        notification_state = "failed"
    else:
        notification_state = "provider_accepted"

    return {
        "processing_state": processing_state,
        "notification_state": notification_state,
        "last_processed_bar_at": runtime_status["last_processed_bar_at"],
        "last_processing_success_at": runtime_status[
            "last_processing_success_at"
        ],
        "last_processing_failure_at": runtime_status[
            "last_processing_failure_at"
        ],
        "processing_error_type": runtime_status["processing_error_type"],
        "last_event_at": runtime_status["last_event_at"],
        "last_transport_attempt_at": runtime_status[
            "last_transport_attempt_at"
        ],
        "last_provider_accepted_at": runtime_status[
            "last_provider_accepted_at"
        ],
        "last_notification_failure_at": runtime_status[
            "last_notification_failure_at"
        ],
        "notification_error_type": runtime_status["notification_error_type"],
        "consecutive_notification_failures": runtime_status[
            "consecutive_notification_failures"
        ],
    }


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


def _collect_after_market_health(
    status_path: Path | None,
    *,
    configured_enabled: bool,
) -> dict[str, Any]:
    """读取盘后运行的公开状态文件；不恢复任何 scheduler/checkpoint 模型。"""
    empty = {
        "configured_enabled": configured_enabled,
        "last_run": None,
        "last_successful_trading_day": None,
        "last_failure": None,
        "error_type": None,
        "error_message": None,
    }
    if status_path is None:
        return {"status": RUNTIME_STATUS_DISABLED, **empty}
    if not status_path.exists():
        return {
            "status": RUNTIME_STATUS_PENDING if configured_enabled else RUNTIME_STATUS_DISABLED,
            **empty,
        }
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": RUNTIME_STATUS_DEGRADED, **empty, "error_type": "after_market_status_invalid"}
    if not isinstance(raw, Mapping):
        return {"status": RUNTIME_STATUS_DEGRADED, **empty, "error_type": "after_market_status_invalid"}
    public = public_after_market_status(raw)
    if not public:
        return {"status": RUNTIME_STATUS_DEGRADED, **empty, "error_type": "after_market_status_invalid"}
    last_run = public["last_run"]
    status = RUNTIME_STATUS_UNKNOWN
    if isinstance(last_run, Mapping):
        status = RUNTIME_STATUS_FAILED if last_run["status"] == "failed" else RUNTIME_STATUS_OK
    return {
        "status": status,
        **empty,
        "last_run": last_run,
        "last_successful_trading_day": public["last_successful_trading_day"],
        "last_failure": public["last_failure"],
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
    """真实探测：PING Redis；失败时返回 (None, failed_health) 供上层跳过 Live 读取。"""
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


def _runtime_status_mapping(value: object) -> Mapping[str, Any] | None:
    if value is None:
        return None
    payload = _json_mapping(value)
    if payload is None:
        raise ValueError("alert runtime status invalid")
    return payload


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
    """Public health never returns provider, path, address, SQL, or exception text."""
    del exc
    return None


def _iso(value: datetime | None) -> str | None:
    """datetime 转 ISO 字符串；naive 时假定 UTC。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
