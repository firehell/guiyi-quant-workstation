"""Alert transport-neutral notification contract and message formatting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


_SHANGHAI = ZoneInfo("Asia/Shanghai")
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


class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...


def format_alert_message(message: AlertNotificationMessage) -> str:
    if message.bar_end.tzinfo is None or message.bar_end.utcoffset() is None:
        raise ValueError("ALERT_NOTIFICATION_TIMEZONE_REQUIRED")
    if (
        not message.symbol.strip()
        or not message.product_name.strip()
        or not message.contract.strip()
    ):
        raise ValueError("ALERT_NOTIFICATION_IDENTITY_INVALID")
    if message.rule_code == "htdy_original_15m":
        return _format_htdy_message(message)
    if message.rule_code == "subing_entry_signal_v1":
        return _format_subing_message(message)
    raise ValueError("ALERT_NOTIFICATION_RULE_INVALID")


def _format_htdy_message(message: AlertNotificationMessage) -> str:
    if message.frequency != "15m":
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
        f"15m · {local_time} 收线"
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
