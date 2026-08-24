"""Alert Runtime 的默认关闭 composition；构造不启动消费循环。"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from app.alerts.evaluators import HtdyOriginal15mEvaluator
from app.alerts.notification_composition import build_notification_sender_from_env
from app.alerts.runtime import (
    AlertRuntime,
    empty_alert_runtime_status,
    validate_alert_runtime_status,
)
from app.core.env import PROJECT_ROOT
from app.db.session import SessionLocal
from app.market_data.composition import (
    build_market_read_service,
    build_subing_read_service,
)
from app.market_data.operational_universe import load_operational_products
from app.market_data.product_taxonomy import load_product_taxonomy
from app.redis_connections import get_redis_connection


ALERT_RUNTIME_ACTIVATION_MARKER = PROJECT_ROOT / ".run" / "alert-runtime-enabled"


class RedisAlertMessageSource:
    def __init__(self, redis: Any) -> None:
        self._pubsub = redis.pubsub(ignore_subscribe_messages=True)

    def subscribe(self, pattern: str) -> None:
        self._pubsub.psubscribe(pattern)

    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None:
        message = self._pubsub.get_message(timeout=timeout_seconds)
        if not isinstance(message, Mapping) or message.get("type") != "pmessage":
            return None
        return message.get("channel"), message.get("data")

    def close(self) -> None:
        self._pubsub.close()


class RedisAlertHeartbeatStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None:
        self._redis.set(
            "alert:heartbeat",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=ttl_seconds,
        )


class RedisAlertRuntimeStatusStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def read(self) -> dict[str, object]:
        raw = self._redis.get("alert:runtime-status")
        if raw is None:
            return empty_alert_runtime_status()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, Mapping):
            raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
        return validate_alert_runtime_status(parsed)

    def write(self, payload: dict[str, object]) -> None:
        persisted = self._redis.set(
            "alert:runtime-status",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        if persisted is not True:
            raise RuntimeError("ALERT_RUNTIME_STATUS_WRITE_FAILED")


def build_alert_runtime() -> AlertRuntime:
    """构造已显式 activation 的 Alert Runtime；缺 Gate 时保持关闭。"""
    try:
        enabled = ALERT_RUNTIME_ACTIVATION_MARKER.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        enabled = False
    if not enabled:
        raise RuntimeError("ALERT_RUNTIME_NOT_ENABLED")
    operational_products = load_operational_products()
    taxonomy = load_product_taxonomy()
    sender = build_notification_sender_from_env()
    redis = get_redis_connection()
    return AlertRuntime(
        session_factory=SessionLocal,
        market_read_factory=build_market_read_service,
        subing_read_factory=build_subing_read_service,
        htdy_evaluator=HtdyOriginal15mEvaluator(),
        sender=sender,
        operational_products=operational_products,
        taxonomy=taxonomy,
        message_source=RedisAlertMessageSource(redis),
        heartbeat_store=RedisAlertHeartbeatStore(redis),
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )
