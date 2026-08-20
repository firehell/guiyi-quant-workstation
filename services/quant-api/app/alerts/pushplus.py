"""PushPlus SDK adapter for the transport-neutral Alert notification seam."""

from __future__ import annotations

from typing import Mapping, Protocol, TypeGuard, cast

from perk_pushplus import Channel, PushPlusClient, PushPlusError, SendRequest, Template

from app.alerts.notification import (
    ALERT_AUDIENCE_HTDY_OBSERVERS,
    ALERT_AUDIENCE_OWNER,
    NotificationDelivery,
    NotificationTransportError,
    ProviderAcceptance,
)
from app.alerts.notification_config import (
    NotificationConfigError,
    validate_pushplus_transport_config,
)


PUSHPLUS_TRANSPORT = "pushplus"


class PushPlusClientProtocol(Protocol):
    def send(self, request: SendRequest) -> object: ...


class PushPlusTransport:
    def __init__(
        self,
        *,
        htdy_topic: str,
        client: PushPlusClientProtocol,
    ) -> None:
        self._htdy_topic = htdy_topic
        self._client = client

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, object],
        *,
        client: PushPlusClientProtocol | None = None,
    ) -> PushPlusTransport:
        try:
            validate_pushplus_transport_config(config)
        except NotificationConfigError:
            raise NotificationTransportError(
                "ALERT_NOTIFICATION_TRANSPORT_INVALID"
            ) from None
        message_token = cast(str, config["message_token"])
        htdy_topic = cast(str, config["htdy_topic"])
        sdk_client: PushPlusClientProtocol = client or (
            PushPlusClient.builder().token(message_token).build()
        )
        return cls(htdy_topic=htdy_topic, client=sdk_client)

    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance:
        if delivery.audience == ALERT_AUDIENCE_OWNER:
            topic = None
        elif delivery.audience == ALERT_AUDIENCE_HTDY_OBSERVERS:
            topic = self._htdy_topic
        else:
            raise NotificationTransportError(
                "ALERT_NOTIFICATION_AUDIENCE_INVALID"
            )
        request = SendRequest(
            title=delivery.title,
            content=delivery.content,
            template=Template.TXT,
            channel=Channel.WECHAT,
            topic=topic,
        )
        try:
            reference = self._client.send(request)
        except PushPlusError:
            raise NotificationTransportError(
                "ALERT_NOTIFICATION_TRANSPORT_FAILED"
            ) from None
        if not _valid_provider_reference(reference):
            raise NotificationTransportError(
                "ALERT_NOTIFICATION_TRANSPORT_FAILED"
            )
        return ProviderAcceptance(reference)


def _valid_provider_reference(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value.strip() == value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )
