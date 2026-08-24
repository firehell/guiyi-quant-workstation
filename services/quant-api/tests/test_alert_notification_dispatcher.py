from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.alerts.notification import (
    ALERT_AUDIENCE_HTDY_OBSERVERS,
    ALERT_AUDIENCE_OWNER,
    AlertNotificationDispatcher,
    AlertNotificationMessage,
    NotificationDelivery,
    NotificationTransportError,
    ProviderAcceptance,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.deliveries: list[NotificationDelivery] = []

    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance:
        self.deliveries.append(delivery)
        return ProviderAcceptance("0123456789abcdef0123456789abcdef")


def _message(rule_code: str = "htdy_original_15m") -> AlertNotificationMessage:
    return AlertNotificationMessage(
        rule_code=rule_code,
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m" if rule_code == "htdy_original_15m" else "5m",
        bar_end=datetime(2026, 8, 20, 10, 30, tzinfo=UTC),
        result_codes=("buy",),
    )


def test_dispatcher_routes_htdy_to_one_observer_audience_request() -> None:
    transport = RecordingTransport()
    dispatcher = AlertNotificationDispatcher(transport)

    accepted = dispatcher.send(_message())

    assert len(transport.deliveries) == 1
    assert accepted == ProviderAcceptance(
        "0123456789abcdef0123456789abcdef"
    )
    delivery = transport.deliveries[0]
    assert delivery.audience == ALERT_AUDIENCE_HTDY_OBSERVERS
    assert delivery.title == "归一量化 火天大有"
    assert "研究观察，非交易指令" in delivery.content


def test_dispatcher_routes_subing_to_owner_only() -> None:
    transport = RecordingTransport()
    dispatcher = AlertNotificationDispatcher(transport)

    dispatcher.send(_message("subing_entry_signal_v1"))

    assert [item.audience for item in transport.deliveries] == [
        ALERT_AUDIENCE_OWNER
    ]
    assert transport.deliveries[0].title == "归一量化 苏冰"


def test_canary_accepts_only_fixed_audiences_and_includes_audience_and_time() -> None:
    transport = RecordingTransport()
    dispatcher = AlertNotificationDispatcher(
        transport,
        clock=lambda: datetime(2026, 8, 20, 10, 31, 12, tzinfo=UTC),
    )

    accepted = dispatcher.send_canary(ALERT_AUDIENCE_HTDY_OBSERVERS)

    assert accepted.reference == "0123456789abcdef0123456789abcdef"
    delivery = transport.deliveries[0]
    assert delivery.audience == ALERT_AUDIENCE_HTDY_OBSERVERS
    assert "htdy_observers" in delivery.content
    assert "2026-08-20T10:31:12+00:00" in delivery.content
    assert accepted.reference not in repr(accepted)

    with pytest.raises(
        NotificationTransportError,
        match="^ALERT_NOTIFICATION_AUDIENCE_INVALID$",
    ):
        dispatcher.send_canary("friend1")

    assert len(transport.deliveries) == 1


def test_unexpected_transport_error_is_not_swallowed() -> None:
    class BrokenTransport:
        def send(self, _delivery: NotificationDelivery) -> ProviderAcceptance:
            raise AttributeError("implementation bug")

    dispatcher = AlertNotificationDispatcher(BrokenTransport())

    with pytest.raises(AttributeError, match="implementation bug"):
        dispatcher.send(_message())
