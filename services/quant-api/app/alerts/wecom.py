"""固定短模板、单次请求的企业微信 Alert sender。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


_LOGGER = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CANARY_TEXT = "【归一量化】企微测试\n\nAlert 通知通道正常"
_WECOM_WEBHOOK_HOST = "qyapi.weixin.qq.com"
_WECOM_WEBHOOK_PATH = "/cgi-bin/webhook/send"
_WECOM_WEBHOOK_QUERY = re.compile(r"key=[A-Za-z0-9_-]{8,}")


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


class WeComSendError(RuntimeError):
    """不携带 webhook、response 或底层异常正文的稳定失败。"""


PostJson = Callable[..., object]


def validate_wecom_webhook_url(value: object) -> str:
    """只接受企业微信机器人固定 HTTPS endpoint，不回显 key。"""
    if not isinstance(value, str):
        raise ValueError("WECOM_WEBHOOK_INVALID")
    normalized = value.strip()
    try:
        parsed = urlsplit(normalized)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == _WECOM_WEBHOOK_HOST
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path == _WECOM_WEBHOOK_PATH
            and _WECOM_WEBHOOK_QUERY.fullmatch(parsed.query) is not None
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not normalized or not valid:
        raise ValueError("WECOM_WEBHOOK_INVALID")
    return normalized


def is_valid_wecom_webhook_url(value: object) -> bool:
    try:
        validate_wecom_webhook_url(value)
    except ValueError:
        return False
    return True


class WeComWebhookSender:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = 5.0,
        post_json: PostJson | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("WECOM_TIMEOUT_INVALID")
        self._webhook_url = validate_wecom_webhook_url(webhook_url)
        self._timeout_seconds = float(timeout_seconds)
        self._post_json = post_json or _stdlib_post_json

    def send(self, event: AlertNotificationMessage) -> None:
        self._send_text(format_alert_message(event))

    def send_canary(self) -> None:
        self._send_text(_CANARY_TEXT)

    def _send_text(self, content: str) -> None:
        payload = {"msgtype": "text", "text": {"content": content}}
        try:
            response = self._post_json(
                self._webhook_url,
                payload,
                timeout=self._timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - transport detail must be collapsed
            _LOGGER.warning("WECOM_REQUEST_FAILED")
            raise WeComSendError("WECOM_REQUEST_FAILED") from None
        errcode = response.get("errcode") if isinstance(response, Mapping) else None
        if type(errcode) is not int or errcode != 0:
            _LOGGER.warning("WECOM_RESPONSE_REJECTED")
            raise WeComSendError("WECOM_RESPONSE_REJECTED")


def format_alert_message(event: AlertNotificationMessage) -> str:
    if event.bar_end.tzinfo is None or event.bar_end.utcoffset() is None:
        raise ValueError("ALERT_NOTIFICATION_TIMEZONE_REQUIRED")
    if not event.symbol.strip() or not event.product_name.strip() or not event.contract.strip():
        raise ValueError("ALERT_NOTIFICATION_IDENTITY_INVALID")
    if event.rule_code == "htdy_original_15m":
        return _format_htdy_message(event)
    if event.rule_code == "subing_entry_signal_v1":
        return _format_subing_message(event)
    raise ValueError("ALERT_NOTIFICATION_RULE_INVALID")


def _format_htdy_message(event: AlertNotificationMessage) -> str:
    if event.frequency != "15m":
        raise ValueError("ALERT_NOTIFICATION_FREQUENCY_INVALID")
    if event.result_codes == ("buy",):
        observation = "买入观察"
    elif event.result_codes == ("sell",):
        observation = "卖出观察"
    elif event.result_codes == ("buy", "sell"):
        observation = "买入观察 + 卖出观察"
    else:
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    local_time = event.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
    return (
        f"【归一量化】{event.symbol.strip().upper()} {event.product_name.strip()}\n\n"
        f"火天大有 · {observation}\n"
        f"主力：{event.contract.strip().upper()}\n"
        f"15m · {local_time} 收线"
    )


def _format_subing_message(event: AlertNotificationMessage) -> str:
    if event.frequency not in {"5m", "15m"}:
        raise ValueError("ALERT_NOTIFICATION_FREQUENCY_INVALID")
    if event.frequency == "5m" and event.lower_tf_confirmation:
        raise ValueError("ALERT_NOTIFICATION_LOWER_TF_CONFIRMATION_INVALID")
    if event.result_codes == ("buy",):
        action = "买入"
    elif event.result_codes == ("sell",):
        action = "卖出"
    else:
        raise ValueError("ALERT_NOTIFICATION_RESULT_INVALID")
    local_time = event.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
    message = (
        f"【苏冰】{event.product_name.strip()} · {event.contract.strip().upper()}\n\n"
        f"{event.frequency} {action}信号 · {local_time}"
    )
    if event.lower_tf_confirmation:
        message += "\n5m 同向确认"
    return message


def _stdlib_post_json(url: str, payload: Mapping[str, Any], *, timeout: float) -> object:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL validated above
        return json.loads(response.read())
