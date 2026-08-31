"""Alert notification domain contract, routing and message formatting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.alerts.registry import (
    HTDY_RULE,
    SUBING_RULE,
    AlertRuleDefinition,
    get_alert_rule_definition,
)
from app.alerts.strategy_payload import (
    StrategyPayloadError,
    SubingStrategyActionPayload,
    parse_subing_strategy_payload,
    validate_subing_strategy_event_facts,
)
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import SubingStrategyActionKind
from app.market_data.subing_structure import PivotKind


_SHANGHAI = ZoneInfo("Asia/Shanghai")
ALERT_AUDIENCE_OWNER = "owner"
ALERT_AUDIENCE_HTDY_OBSERVERS = "htdy_observers"
ALERT_AUDIENCES = frozenset({ALERT_AUDIENCE_OWNER, ALERT_AUDIENCE_HTDY_OBSERVERS})
ALERT_CANARY_TEXT = "【归一量化】微信通知测试\n\nAlert 通知通道正常"
SUBING_STRATEGY_REASON_LABELS = {
    "EMA21_BREACH_LONG": "跌破 EMA21",
    "EMA21_BREACH_SHORT": "突破 EMA21",
    "PREVIOUS_BAR_LOW_BREACH": "跌破上一根 15m 低点",
    "PREVIOUS_BAR_HIGH_BREACH": "突破上一根 15m 高点",
    "BOUND_LOW_PIVOT_BREACH": "跌破结构前低",
    "BOUND_HIGH_PIVOT_BREACH": "突破结构前高",
    "MACD_HIGH_DEAD_CROSS": "MACD 高位死叉",
    "MACD_LOW_GOLDEN_CROSS": "MACD 低位金叉",
    "CONTRACT_SEGMENT_END": "主力合约切换",
}
_SUBING_CONFIRMATION_LABELS = {
    ConfirmationSource.FORMAL_V1: "Formal V1 研究对照",
    ConfirmationSource.MOMENTUM_HOLD: "动量保持",
    ConfirmationSource.PIVOT_BREAK_HOLD: "Pivot 突破保持",
    ConfirmationSource.PIVOT_RETEST_REBREAK: "Pivot 回踩再突破",
}


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
    strategy_payload: SubingStrategyActionPayload | None = None


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
        return self._transport.send(NotificationDelivery(audience, title, rendered))

    def send_canary(self, audience: str) -> ProviderAcceptance:
        if audience not in ALERT_AUDIENCES:
            raise NotificationTransportError("ALERT_NOTIFICATION_AUDIENCE_INVALID")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise NotificationTransportError("ALERT_NOTIFICATION_TIME_INVALID")
        content = f"{ALERT_CANARY_TEXT}\naudience={audience}\ntime={now.isoformat()}"
        return self._transport.send(
            NotificationDelivery(audience, "归一量化 通知测试", content)
        )


def format_alert_message(message: AlertNotificationMessage) -> str:
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (message.bar_end, message.detected_at)
    ):
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
    if message.strategy_payload is not None:
        raise StrategyPayloadError()
    if message.result_codes == ("buy",):
        observation = "买入观察"
    elif message.result_codes == ("sell",):
        observation = "卖出观察"
    elif message.result_codes == ("buy", "sell"):
        observation = "买入观察 + 卖出观察"
    else:
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    observation_time = message.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
    first_seen_time = message.detected_at.astimezone(_SHANGHAI).strftime("%H:%M")
    return (
        f"【归一量化】{message.symbol.strip().upper()} {message.product_name.strip()}\n\n"
        f"火天大有 · {observation}\n"
        f"主力：{message.contract.strip().upper()}\n"
        f"观察K线：{message.frequency} · {observation_time}\n"
        f"首次识别：{first_seen_time}\n"
        "研究观察，非交易指令"
    )


def _format_subing_message(message: AlertNotificationMessage) -> str:
    if message.frequency != "15m":
        raise ValueError("ALERT_NOTIFICATION_FREQUENCY_INVALID")
    if not isinstance(message.strategy_payload, SubingStrategyActionPayload):
        raise StrategyPayloadError()
    payload = parse_subing_strategy_payload(message.strategy_payload.to_json())
    validate_subing_strategy_event_facts(
        payload,
        action_id=payload.action_id,
        symbol=message.symbol,
        contract=message.contract,
        trading_day=payload.trading_day,
        frequency=message.frequency,
        bar_end=message.bar_end,
        result_codes=message.result_codes,
    )
    heading = f"【苏冰策略】{message.product_name.strip()} · {payload.contract}\n\n"
    if payload.kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }:
        return heading + _format_subing_open(payload)
    return heading + _format_subing_close(payload)


def _format_subing_open(payload: SubingStrategyActionPayload) -> str:
    if payload.confirmation_source is None:
        raise StrategyPayloadError()
    action = "建多" if payload.kind is SubingStrategyActionKind.OPEN_LONG else "建空"
    reason_lines = [f"- {_SUBING_CONFIRMATION_LABELS[payload.confirmation_source]}"]
    if payload.bound_reference_pivot is not None:
        pivot_label = (
            "前低" if payload.bound_reference_pivot.kind is PivotKind.LOW else "前高"
        )
        reason_lines.append(
            "- 结构保护："
            f"{pivot_label} {_decimal_text(payload.bound_reference_pivot.price)}"
        )
    return (
        f"15m {action}\n"
        f"建仓参考：{_decimal_text(payload.reference_price)}\n"
        "原因：\n" + "\n".join(reason_lines)
    )


def _format_subing_close(payload: SubingStrategyActionPayload) -> str:
    if payload.entry is None or payload.reference_change_percent is None:
        raise StrategyPayloadError()
    action = "清多" if payload.kind is SubingStrategyActionKind.CLOSE_LONG else "清空"
    try:
        reason_lines = [
            f"- {SUBING_STRATEGY_REASON_LABELS[reason]}"
            for reason in payload.reason_codes
        ]
    except KeyError:
        raise StrategyPayloadError() from None
    return (
        f"15m {action}\n"
        f"建仓参考：{_decimal_text(payload.entry.reference_price)}\n"
        f"清仓参考：{_decimal_text(payload.reference_price)}\n"
        f"参考变动：{_signed_percent(payload.reference_change_percent)}%\n"
        "原因：\n" + "\n".join(reason_lines)
    )


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _signed_percent(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    if rounded == 0:
        rounded = abs(rounded)
    return f"{rounded:+.2f}"
