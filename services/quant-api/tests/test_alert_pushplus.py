from __future__ import annotations

import pytest
from perk_pushplus import PushPlusError

from app.alerts.notification import (
    ALERT_AUDIENCE_HTDY_OBSERVERS,
    ALERT_AUDIENCE_OWNER,
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
            ALERT_AUDIENCE_OWNER,
            "归一量化 苏冰",
            "fixture content",
        )
    )

    request = client.requests[0]
    assert request.title == "归一量化 苏冰"
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
            ALERT_AUDIENCE_HTDY_OBSERVERS,
            "归一量化 火天大有",
            "fixture content",
        )
    )

    assert len(client.requests) == 1
    assert client.requests[0].topic == HTDY_TOPIC
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
                ALERT_AUDIENCE_OWNER,
                "title",
                "private content",
            )
        )

    assert MESSAGE_TOKEN not in str(captured.value)
    assert HTDY_TOPIC not in str(captured.value)
    assert "private content" not in str(captured.value)


def test_unexpected_client_bug_is_not_swallowed() -> None:
    transport = _transport(RecordingClient(AttributeError("implementation bug")))

    with pytest.raises(AttributeError, match="implementation bug"):
        transport.send(
            NotificationDelivery(ALERT_AUDIENCE_OWNER, "title", "content")
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
            NotificationDelivery(ALERT_AUDIENCE_OWNER, "title", "content")
        )

    assert "provider rejected" not in str(captured.value)


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
