from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.alerts.notification import (
    ALERT_AUDIENCE_HTDY_OBSERVERS,
    ALERT_AUDIENCE_OWNER,
    AlertNotificationDispatcher,
    AlertNotificationMessage,
    NotificationDelivery,
    ProviderAcceptance,
    format_alert_message,
)


class Transport:
    def __init__(self) -> None:
        self.deliveries: list[NotificationDelivery] = []

    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance:
        self.deliveries.append(delivery)
        return ProviderAcceptance("accepted")


def message(**overrides: object) -> AlertNotificationMessage:
    values: dict[str, object] = {
        "rule_code": "htdy_original_15m",
        "symbol": "jm",
        "product_name": "焦煤",
        "contract": "JM2609",
        "frequency": "15m",
        "bar_end": datetime(2026, 8, 15, 2, tzinfo=UTC),
        "detected_at": datetime(2026, 8, 15, 2, 0, 1, tzinfo=UTC),
        "result_codes": ("buy",),
    }
    values.update(overrides)
    return AlertNotificationMessage(**values)  # type: ignore[arg-type]


def test_htdy_message_is_observation_only() -> None:
    content = format_alert_message(message(result_codes=("buy", "sell")))
    assert "火天大有" in content
    assert "买入观察、卖出观察" in content
    assert "仅供研究观察，不是交易指令" in content


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("rule_code", "future_rule", "ALERT_NOTIFICATION_RULE_INVALID"),
        ("result_codes", (), "ALERT_NOTIFICATION_RESULT_INVALID"),
        ("result_codes", ("hold",), "ALERT_NOTIFICATION_RESULT_INVALID"),
    ],
)
def test_invalid_notification_facts_fail_closed(
    field: str, value: object, code: str
) -> None:
    with pytest.raises(ValueError, match=code):
        format_alert_message(message(**{field: value}))


def test_dispatcher_routes_htdy_and_explicit_canary_audiences() -> None:
    transport = Transport()
    dispatcher = AlertNotificationDispatcher(transport)
    assert dispatcher.send(message()).reference == "accepted"
    assert transport.deliveries[-1].audience == ALERT_AUDIENCE_HTDY_OBSERVERS
    dispatcher.send_canary(ALERT_AUDIENCE_OWNER)
    assert transport.deliveries[-1].audience == ALERT_AUDIENCE_OWNER
    with pytest.raises(ValueError, match="ALERT_AUDIENCE_INVALID"):
        dispatcher.send_canary("unknown")
