"""Alert Runtime 的默认关闭 composition；构造不启动消费循环。"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from typing import Any

from sqlalchemy.orm import Session

from app.alerts.evaluators import HtdyOriginal15mEvaluator
from app.alerts.runtime import AlertRuntime
from app.alerts.wecom import WeComWebhookSender
from app.core.env import PROJECT_ROOT
from app.market_data.composition import build_market_read_service
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
        )
        self._redis.expire("alert:heartbeat", ttl_seconds)


def build_wecom_sender_from_env() -> WeComWebhookSender:
    webhook_url = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("WECOM_WEBHOOK_NOT_CONFIGURED")
    return WeComWebhookSender(webhook_url)


def build_alert_runtime(session: Session) -> AlertRuntime:
    """构造已显式 activation 的 Alert Runtime；缺 Gate 时保持关闭。"""
    try:
        enabled = ALERT_RUNTIME_ACTIVATION_MARKER.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        enabled = False
    if not enabled:
        raise RuntimeError("ALERT_RUNTIME_NOT_ENABLED")
    redis = get_redis_connection()
    return AlertRuntime(
        session=session,
        market_read=build_market_read_service(session),
        evaluator=HtdyOriginal15mEvaluator(),
        sender=build_wecom_sender_from_env(),
        operational_products=load_operational_products(),
        taxonomy=load_product_taxonomy(),
        message_source=RedisAlertMessageSource(redis),
        heartbeat_store=RedisAlertHeartbeatStore(redis),
    )
