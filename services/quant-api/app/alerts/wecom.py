"""固定短模板、单次请求的企业微信 Alert sender。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


_LOGGER = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CANARY_TEXT = "【归一量化】企微测试\n\nAlert 通知通道正常"


@dataclass(frozen=True, slots=True)
class AlertEventMessage:
    symbol: str
    product_name: str
    contract: str
    frequency: str
    bar_end: datetime
    observation_types: tuple[str, ...]


class WeComSendError(RuntimeError):
    """不携带 webhook、response 或底层异常正文的稳定失败。"""


PostJson = Callable[..., object]


class WeComWebhookSender:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = 5.0,
        post_json: PostJson | None = None,
    ) -> None:
        if not isinstance(webhook_url, str) or not webhook_url.startswith("https://"):
            raise ValueError("WECOM_WEBHOOK_INVALID")
        if timeout_seconds <= 0:
            raise ValueError("WECOM_TIMEOUT_INVALID")
        self._webhook_url = webhook_url
        self._timeout_seconds = float(timeout_seconds)
        self._post_json = post_json or _stdlib_post_json

    def send(self, event: AlertEventMessage) -> None:
        self._send_text(_format_event(event))

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


def _format_event(event: AlertEventMessage) -> str:
    if event.bar_end.tzinfo is None or event.bar_end.utcoffset() is None:
        raise ValueError("ALERT_EVENT_TIMEZONE_REQUIRED")
    if event.frequency != "15m":
        raise ValueError("ALERT_EVENT_FREQUENCY_INVALID")
    if not event.symbol.strip() or not event.product_name.strip() or not event.contract.strip():
        raise ValueError("ALERT_EVENT_IDENTITY_INVALID")
    if event.observation_types == ("buy",):
        observation = "买入观察"
    elif event.observation_types == ("sell",):
        observation = "卖出观察"
    elif event.observation_types == ("buy", "sell"):
        observation = "买入观察 + 卖出观察"
    else:
        raise ValueError("ALERT_EVENT_OBSERVATION_INVALID")
    local_time = event.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
    return (
        f"【归一量化】{event.symbol.strip().upper()} {event.product_name.strip()}\n\n"
        f"火天大有 · {observation}\n"
        f"主力：{event.contract.strip().upper()}\n"
        f"15m · {local_time} 收线"
    )


def _stdlib_post_json(url: str, payload: Mapping[str, Any], *, timeout: float) -> object:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL validated above
        return json.loads(response.read())
