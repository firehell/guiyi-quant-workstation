"""Alert notification domain contract, routing and message formatting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.alerts.registry import (
    HTDY_RULE,
    SUBING_RULE,
    AlertRuleDefinition,
    get_alert_rule_definition,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
ALERT_AUDIENCE_OWNER = "owner"
ALERT_AUDIENCE_HTDY_OBSERVERS = "htdy_observers"
ALERT_AUDIENCES = frozenset(
    {ALERT_AUDIENCE_OWNER, ALERT_AUDIENCE_HTDY_OBSERVERS}
)
ALERT_CANARY_TEXT = "【归一量化】微信通知测试\n\nAlert 通知通道正常"


@dataclass(frozen=True, slots=True)
class AlertNotificationMessage:
    rule_code: str
    symbol: str
    product_name: str
    contract: str
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool = False


class NotificationTransportError(RuntimeError):
    """Stable transport error that never includes provider-private data."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class NotificationDelivery:
    audience: str
    title: str
    content: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProviderAcceptance:
    """Provider request reference; acceptance is not final delivery evidence."""

    reference: str | None = field(default=None, repr=False)


class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> ProviderAcceptance: ...


class NotificationTransport(Protocol):
    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance: ...


class AlertNotificationDispatcher:
    """Map the two frozen Alert rules to provider-independent audiences."""

    def __init__(
        self,
        transport: NotificationTransport,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    def send(self, message: AlertNotificationMessage) -> ProviderAcceptance:
        rendered = format_alert_message(message)
        definition = _notification_rule(message.rule_code)
        if definition == HTDY_RULE:
            audience = ALERT_AUDIENCE_HTDY_OBSERVERS
            title = "归一量化 火天大有"
        elif definition == SUBING_RULE:
            audience = ALERT_AUDIENCE_OWNER
            title = "归一量化 苏冰"
        else:
            raise ValueError("ALERT_NOTIFICATION_RULE_INVALID")
        return self._transport.send(
            NotificationDelivery(audience, title, rendered)
        )

    def send_canary(self, audience: str) -> ProviderAcceptance:
        if audience not in ALERT_AUDIENCES:
            raise NotificationTransportError(
                "ALERT_NOTIFICATION_AUDIENCE_INVALID"
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise NotificationTransportError("ALERT_NOTIFICATION_TIME_INVALID")
        content = (
            f"{ALERT_CANARY_TEXT}\n"
            f"audience={audience}\n"
            f"time={now.isoformat()}"
        )
        return self._transport.send(
            NotificationDelivery(audience, "归一量化 通知测试", content)
        )


def format_alert_message(message: AlertNotificationMessage) -> str:
    if message.bar_end.tzinfo is None or message.bar_end.utcoffset() is None:
        raise ValueError("ALERT_NOTIFICATION_TIMEZONE_REQUIRED")
    if (
        not message.symbol.strip()
        or not message.product_name.strip()
        or not message.contract.strip()
    ):
        raise ValueError("ALERT_NOTIFICATION_IDENTITY_INVALID")
    definition = _notification_rule(message.rule_code)
    if definition == HTDY_RULE:
        return _format_htdy_message(message)
    if definition == SUBING_RULE:
        return _format_subing_message(message)
    raise ValueError("ALERT_NOTIFICATION_RULE_INVALID")


def _notification_rule(rule_code: str) -> AlertRuleDefinition:
    try:
        return get_alert_rule_definition(rule_code)
    except KeyError:
        raise ValueError("ALERT_NOTIFICATION_RULE_INVALID") from None


def _format_htdy_message(message: AlertNotificationMessage) -> str:
    if message.frequency not in HTDY_RULE.input_frequencies:
        raise ValueError("ALERT_NOTIFICATION_FREQUENCY_INVALID")
    if message.result_codes == ("buy",):
        observation = "买入观察"
    elif message.result_codes == ("sell",):
        observation = "卖出观察"
    elif message.result_codes == ("buy", "sell"):
        observation = "买入观察 + 卖出观察"
    else:
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    local_time = message.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
    return (
        f"【归一量化】{message.symbol.strip().upper()} {message.product_name.strip()}\n\n"
        f"火天大有 · {observation}\n"
        f"主力：{message.contract.strip().upper()}\n"
        f"{message.frequency} · {local_time} 收线\n"
        "研究观察，非交易指令"
    )


def _format_subing_message(message: AlertNotificationMessage) -> str:
    if message.frequency not in {"5m", "15m"}:
        raise ValueError("ALERT_NOTIFICATION_FREQUENCY_INVALID")
    if message.frequency == "5m" and message.lower_tf_confirmation:
        raise ValueError("ALERT_NOTIFICATION_LOWER_TF_CONFIRMATION_INVALID")
    if message.result_codes == ("buy",):
        action = "买入"
    elif message.result_codes == ("sell",):
        action = "卖出"
    else:
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    local_time = message.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
    rendered = (
        f"【苏冰】{message.product_name.strip()} · {message.contract.strip().upper()}\n\n"
        f"{message.frequency} {action}信号 · {local_time}"
    )
    if message.lower_tf_confirmation:
        rendered += "\n5m 同向确认"
    return rendered
