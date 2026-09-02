"""One-shot Alert notification contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol

from app.alerts.registry import (
    HTDY_ALERT_RULE_CODE,
    SUBING_THS_ALERT_RULE_CODE,
    get_alert_rule_definition,
)


ALERT_AUDIENCE_HTDY_OBSERVERS = "htdy_observers"
ALERT_AUDIENCE_OWNER = "owner"
ALERT_AUDIENCES = frozenset(
    {ALERT_AUDIENCE_HTDY_OBSERVERS, ALERT_AUDIENCE_OWNER}
)


@dataclass(frozen=True, slots=True)
class AlertNotificationMessage:
    rule_code: str
    symbol: str
    product_name: str
    contract: str
    frequency: str
    bar_end: datetime
    detected_at: datetime
    result_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlertNotificationPolicy:
    rule_code: str
    title: str
    audience: str
    formatter: Callable[[AlertNotificationMessage], str]


class NotificationTransportError(RuntimeError):
    code = "ALERT_NOTIFICATION_TRANSPORT_FAILED"

    def __init__(self, code: str = "ALERT_NOTIFICATION_TRANSPORT_FAILED") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NotificationDelivery:
    title: str
    content: str
    audience: str


@dataclass(frozen=True, slots=True)
class ProviderAcceptance:
    reference: str | None = field(default=None, repr=False)


class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> ProviderAcceptance: ...


class NotificationTransport(Protocol):
    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance: ...


def _validate_result_codes(message: AlertNotificationMessage) -> None:
    if not message.result_codes or any(
        value not in {"buy", "sell"} for value in message.result_codes
    ):
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")


def _format_htdy_message(message: AlertNotificationMessage) -> str:
    try:
        definition = get_alert_rule_definition(message.rule_code)
    except KeyError:
        raise ValueError("ALERT_NOTIFICATION_RULE_INVALID") from None
    if definition.rule_code != HTDY_ALERT_RULE_CODE:
        raise ValueError("ALERT_NOTIFICATION_RULE_INVALID")
    _validate_result_codes(message)
    observations = "、".join(
        "买入观察" if value == "buy" else "卖出观察"
        for value in message.result_codes
    )
    return (
        f"{definition.display_name}：{message.product_name}（{message.symbol.upper()}）\n"
        f"合约：{message.contract}　周期：{message.frequency}\n"
        f"观察：{observations}\n"
        f"Bar：{message.bar_end.isoformat()}\n"
        "仅供研究观察，不是交易指令。"
    )


def _format_subing_message(message: AlertNotificationMessage) -> str:
    try:
        definition = get_alert_rule_definition(message.rule_code)
    except KeyError:
        raise ValueError("ALERT_NOTIFICATION_RULE_INVALID") from None
    if definition.rule_code != SUBING_THS_ALERT_RULE_CODE:
        raise ValueError("ALERT_NOTIFICATION_RULE_INVALID")
    _validate_result_codes(message)
    if message.frequency != "15m":
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    if message.result_codes == ("buy",):
        direction, cross, position = "多头预警", "MACD 金叉", "EMA21 上方"
    elif message.result_codes == ("sell",):
        direction, cross, position = "空头预警", "MACD 死叉", "EMA21 下方"
    else:
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    return (
        f"【苏冰预警】{message.product_name}（{message.symbol.upper()}）\n"
        f"合约：{message.contract}　周期：15m\n"
        f"{direction}：{cross}，收盘价位于 {position}\n"
        f"Bar：{message.bar_end.isoformat()}\n"
        "请打开图表复核；仅供研究观察，不是交易指令。"
    )


ALERT_NOTIFICATION_POLICIES: Final = {
    HTDY_ALERT_RULE_CODE: AlertNotificationPolicy(
        rule_code=HTDY_ALERT_RULE_CODE,
        title="归一量化 · 火天大有",
        audience=ALERT_AUDIENCE_HTDY_OBSERVERS,
        formatter=_format_htdy_message,
    ),
    SUBING_THS_ALERT_RULE_CODE: AlertNotificationPolicy(
        rule_code=SUBING_THS_ALERT_RULE_CODE,
        title="归一量化 · 苏冰预警",
        audience=ALERT_AUDIENCE_HTDY_OBSERVERS,
        formatter=_format_subing_message,
    ),
}

_EXPECTED_POLICY_BINDINGS: Final = {
    HTDY_ALERT_RULE_CODE: (
        "归一量化 · 火天大有",
        ALERT_AUDIENCE_HTDY_OBSERVERS,
        _format_htdy_message,
    ),
    SUBING_THS_ALERT_RULE_CODE: (
        "归一量化 · 苏冰预警",
        ALERT_AUDIENCE_HTDY_OBSERVERS,
        _format_subing_message,
    ),
}


def _validate_policy_entry(rule_code: str, policy: object) -> AlertNotificationPolicy:
    expected = _EXPECTED_POLICY_BINDINGS.get(rule_code)
    if (
        not isinstance(policy, AlertNotificationPolicy)
        or expected is None
        or policy.rule_code != rule_code
        or not isinstance(policy.title, str)
        or not policy.title.strip()
        or policy.title != expected[0]
        or policy.audience != expected[1]
        or policy.formatter is not expected[2]
    ):
        raise ValueError("ALERT_NOTIFICATION_POLICY_INVALID")
    return policy


def notification_policy_rule_codes() -> tuple[str, ...]:
    for rule_code, policy in ALERT_NOTIFICATION_POLICIES.items():
        _validate_policy_entry(rule_code, policy)
    return tuple(sorted(ALERT_NOTIFICATION_POLICIES))


class AlertNotificationDispatcher:
    def __init__(self, transport: NotificationTransport) -> None:
        self._transport = transport

    def send(self, message: AlertNotificationMessage) -> ProviderAcceptance:
        policy = _notification_policy(message.rule_code)
        return self._transport.send(
            NotificationDelivery(
                title=policy.title,
                content=policy.formatter(message),
                audience=policy.audience,
            )
        )

    def send_canary(self, audience: str) -> ProviderAcceptance:
        if audience not in ALERT_AUDIENCES:
            raise ValueError("ALERT_AUDIENCE_INVALID")
        return self._transport.send(
            NotificationDelivery(
                title="归一量化 · Alert Canary",
                content="HTDY Alert 通知通道测试；provider accepted 不等于微信送达。",
                audience=audience,
            )
        )


def format_alert_message(message: AlertNotificationMessage) -> str:
    return _notification_policy(message.rule_code).formatter(message)


def _notification_policy(rule_code: str) -> AlertNotificationPolicy:
    try:
        policy = ALERT_NOTIFICATION_POLICIES[rule_code]
    except KeyError:
        raise ValueError("ALERT_NOTIFICATION_RULE_INVALID") from None
    return _validate_policy_entry(rule_code, policy)
