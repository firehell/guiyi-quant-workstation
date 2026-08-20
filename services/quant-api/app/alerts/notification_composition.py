"""Composition for the single active Alert notification transport."""

from __future__ import annotations

import os
from pathlib import Path

from app.alerts.notification import AlertNotificationDispatcher
from app.alerts.notification_config import (
    NOTIFICATION_CONFIG_ENV,
    NotificationConfig,
    NotificationConfigError,
    load_notification_config,
    validate_pushplus_transport_config,
)
from app.alerts.pushplus import (
    PUSHPLUS_TRANSPORT,
    PushPlusClientProtocol,
    PushPlusTransport,
)


def build_notification_sender_from_env(
    *,
    client: PushPlusClientProtocol | None = None,
) -> AlertNotificationDispatcher:
    config = _load_from_env()
    if config.transport != PUSHPLUS_TRANSPORT:
        raise NotificationConfigError()
    transport = PushPlusTransport.from_config(
        config.transport_config,
        client=client,
    )
    return AlertNotificationDispatcher(transport)


def notification_transport_status_from_env() -> dict[str, object]:
    """Return secret-safe structural readiness without network access."""
    try:
        config = _load_from_env()
        if config.transport != PUSHPLUS_TRANSPORT:
            raise NotificationConfigError()
        validate_pushplus_transport_config(config.transport_config)
    except NotificationConfigError:
        return _unconfigured_status()
    return {
        "transport": PUSHPLUS_TRANSPORT,
        "configured": True,
        "audience_count": 2,
        "would_send": False,
    }


def _load_from_env() -> NotificationConfig:
    raw_path = os.getenv(NOTIFICATION_CONFIG_ENV, "")
    path = Path(raw_path)
    if not raw_path or not path.is_absolute():
        raise NotificationConfigError()
    return load_notification_config(path)


def _unconfigured_status() -> dict[str, object]:
    return {
        "transport": PUSHPLUS_TRANSPORT,
        "configured": False,
        "audience_count": 2,
        "would_send": False,
    }
