"""Alert Runtime 的默认关闭 composition；构造不启动消费循环。"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from app.alerts.evaluators import HtdyOriginal15mEvaluator
from app.alerts.runtime import AlertRuntime
from app.alerts.wechat_courier import (
    WeChatCourierError,
    WeChatCourierRunner,
    WeChatGroupAlertSender,
    resolve_wechat_courier_dependency,
)
from app.alerts.wechat_group_config import (
    WeChatGroupConfigError,
    load_wechat_group_target,
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


def build_wechat_group_sender_from_env() -> WeChatGroupAlertSender:
    courier_root = os.getenv("GUIYI_WECHAT_COURIER_ROOT", "")
    group_config_path = os.getenv("GUIYI_ALERT_WECHAT_GROUP_PATH", "")
    if not courier_root or not group_config_path:
        raise RuntimeError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY")
    try:
        root = Path(courier_root)
        config_path = Path(group_config_path)
        if not root.is_absolute() or not config_path.is_absolute():
            raise ValueError
        target = load_wechat_group_target(config_path)
        dependency = resolve_wechat_courier_dependency(root)
        runner = WeChatCourierRunner(dependency)
    except (OSError, ValueError, WeChatGroupConfigError, WeChatCourierError):
        raise RuntimeError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    return WeChatGroupAlertSender(target=target, runner=runner)


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
    sender = build_wechat_group_sender_from_env()
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
    )
