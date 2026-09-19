from __future__ import annotations

from datetime import UTC, datetime

import pytest
from perk_pushplus import PushPlusError

from app.alerts.notification import (
    ALERT_AUDIENCE_HTDY_OBSERVERS,
    ALERT_AUDIENCE_OWNER,
    AlertNotificationDispatcher,
    AlertNotificationMessage,
    NotificationDelivery,
    NotificationTransportError,
)
from app.alerts.pushplus import PushPlusTransport


MESSAGE_TOKEN = "0123456789abcdef0123456789abcdef"
HTDY_TOPIC = "fixture-private-topic"
SHORT_CODE = "fedcba9876543210fedcba9876543210"


class RecordingClient:
    def __init__(self, result: object = SHORT_CODE) -> None:
        self.result = result
        self.requests: list[object] = []

    def send(self, request: object) -> object:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _transport(client: RecordingClient) -> PushPlusTransport:
    return PushPlusTransport.from_config(
        {"message_token": MESSAGE_TOKEN, "htdy_topic": HTDY_TOPIC},
        client=client,
    )


def test_owner_uses_wechat_txt_without_topic_and_returns_hidden_short_code() -> None:
    client = RecordingClient()
    accepted = _transport(client).send(
        NotificationDelivery(
            title="归一量化提醒",
            content="fixture content",
            audience=ALERT_AUDIENCE_OWNER,
        )
    )

    request = client.requests[0]
    assert request.title == "归一量化提醒"
    assert request.content == "fixture content"
    assert request.template.value == "txt"
    assert request.channel.value == "wechat"
    assert request.topic is None
    assert request.to is None
    assert request.callbackUrl is None
    assert request.token is None
    assert accepted.reference == SHORT_CODE
    assert SHORT_CODE not in repr(accepted)


def test_htdy_observers_uses_exact_dedicated_topic_once() -> None:
    client = RecordingClient()
    _transport(client).send(
        NotificationDelivery(
            title="归一量化 火天大有",
            content="fixture content",
            audience=ALERT_AUDIENCE_HTDY_OBSERVERS,
        )
    )

    assert len(client.requests) == 1
    assert client.requests[0].topic == HTDY_TOPIC
    assert client.requests[0].to is None


@pytest.mark.parametrize(
    ("rule_code", "expected_topic"),
    [("subing_ths_alert_15m_v1", None), ("htdy_original_15m", HTDY_TOPIC)],
)
def test_rule_dispatch_preserves_owner_and_topic_isolation(
    rule_code: str, expected_topic: str | None,
) -> None:
    client = RecordingClient()
    dispatcher = AlertNotificationDispatcher(_transport(client))
    dispatcher.send(AlertNotificationMessage(
        rule_code=rule_code,
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=datetime(2026, 9, 18, 7, tzinfo=UTC),
        detected_at=datetime(2026, 9, 18, 7, 0, 1, tzinfo=UTC),
        result_codes=("buy",),
    ))
    assert len(client.requests) == 1
    assert client.requests[0].topic == expected_topic
    assert client.requests[0].to is None


@pytest.mark.parametrize("result", [None, "", " bad ", 123])
def test_rejects_malformed_provider_acceptance_without_leaking(
    result: object,
) -> None:
    transport = _transport(RecordingClient(result))

    with pytest.raises(
        NotificationTransportError,
        match="^ALERT_NOTIFICATION_TRANSPORT_FAILED$",
    ) as captured:
        transport.send(
            NotificationDelivery(
                title="title",
                content="private content",
                audience=ALERT_AUDIENCE_OWNER,
            )
        )

    assert MESSAGE_TOKEN not in str(captured.value)
    assert HTDY_TOPIC not in str(captured.value)
    assert "private content" not in str(captured.value)


def test_unexpected_client_bug_is_not_swallowed() -> None:
    transport = _transport(RecordingClient(AttributeError("implementation bug")))

    with pytest.raises(AttributeError, match="implementation bug"):
        transport.send(
            NotificationDelivery(title="title", content="content", audience=ALERT_AUDIENCE_OWNER)
        )


def test_sdk_error_is_mapped_without_leaking_provider_details() -> None:
    transport = _transport(
        RecordingClient(PushPlusError("provider rejected private token", code=500))
    )

    with pytest.raises(
        NotificationTransportError,
        match="^ALERT_NOTIFICATION_TRANSPORT_FAILED$",
    ) as captured:
        transport.send(
            NotificationDelivery(title="title", content="content", audience=ALERT_AUDIENCE_OWNER)
        )

    assert "provider rejected" not in str(captured.value)


@pytest.mark.parametrize(
    ("sdk_code", "expected_diagnostic_code"),
    [
        (500, "PUSHPLUS_PROVIDER_REJECTED"),
        (900, "PUSHPLUS_RATE_LIMITED"),
        (-1, "PUSHPLUS_REQUEST_OUTCOME_UNKNOWN"),
        (123456, "UNKNOWN"),
    ],
)
def test_sdk_error_exposes_only_a_fixed_safe_diagnostic_code(
    sdk_code: int,
    expected_diagnostic_code: str,
) -> None:
    sensitive_marker = "fixture-sensitive-marker-in-provider-body"
    transport = _transport(
        RecordingClient(PushPlusError(sensitive_marker, code=sdk_code))
    )

    with pytest.raises(NotificationTransportError) as captured:
        transport.send(
            NotificationDelivery(
                title="title",
                content=sensitive_marker,
                audience=ALERT_AUDIENCE_OWNER,
            )
        )

    assert captured.value.code == "ALERT_NOTIFICATION_TRANSPORT_FAILED"
    assert captured.value.diagnostic_code == expected_diagnostic_code
    assert sensitive_marker not in str(captured.value)
    assert sensitive_marker not in repr(captured.value)


def test_malformed_provider_reference_has_safe_adapter_diagnostic() -> None:
    sensitive_marker = " fixture-sensitive-marker-in-provider-reference "

    with pytest.raises(NotificationTransportError) as captured:
        _transport(RecordingClient(sensitive_marker)).send(
            NotificationDelivery(title="title", content="content", audience=ALERT_AUDIENCE_OWNER)
        )

    assert captured.value.code == "ALERT_NOTIFICATION_TRANSPORT_FAILED"
    assert captured.value.diagnostic_code == "PUSHPLUS_ACCEPTANCE_INVALID"
    assert sensitive_marker not in str(captured.value)
    assert sensitive_marker not in repr(captured.value)


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"message_token": MESSAGE_TOKEN},
        {"message_token": "wrong", "htdy_topic": HTDY_TOPIC},
        {
            "message_token": MESSAGE_TOKEN,
            "htdy_topic": HTDY_TOPIC,
            "extra": "value",
        },
    ],
)
def test_rejects_invalid_provider_config_before_client_use(
    config: dict[str, object],
) -> None:
    client = RecordingClient()

    with pytest.raises(
        NotificationTransportError,
        match="^ALERT_NOTIFICATION_TRANSPORT_INVALID$",
    ):
        PushPlusTransport.from_config(config, client=client)

    assert client.requests == []
