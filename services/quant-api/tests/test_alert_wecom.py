from __future__ import annotations

from datetime import UTC, datetime
import logging
import traceback
from zoneinfo import ZoneInfo

import pytest

from app.alerts.wecom import (
    AlertNotificationMessage,
    WeComSendError,
    WeComWebhookSender,
    format_alert_message,
)


_TEST_WEBHOOK_URL = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?" + "key=test-key-12345678"
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _event(observations: tuple[str, ...]) -> AlertNotificationMessage:
    return AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="ag",
        product_name="白银",
        contract="AG2610",
        frequency="15m",
        bar_end=datetime(2026, 8, 13, 2, 45, tzinfo=UTC),
        result_codes=observations,
    )


def test_htdy_message_keeps_v1_copy() -> None:
    text = format_alert_message(
        AlertNotificationMessage(
            rule_code="htdy_original_15m",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="15m",
            bar_end=datetime(2026, 8, 13, 14, 30, tzinfo=UTC),
            result_codes=("sell",),
        )
    )

    assert "火天大有 · 卖出观察" in text
    assert "15m" in text


def test_subing_5m_message_is_short() -> None:
    text = format_alert_message(
        AlertNotificationMessage(
            rule_code="subing_entry_signal_v1",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="5m",
            bar_end=datetime(2026, 8, 14, 10, 25, tzinfo=_SHANGHAI),
            result_codes=("buy",),
        )
    )

    assert text == "【苏冰】焦煤 · JM2609\n\n5m 买入信号 · 10:25"


def test_subing_15m_lower_tf_confirmation_adds_one_line() -> None:
    text = format_alert_message(
        AlertNotificationMessage(
            rule_code="subing_entry_signal_v1",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="15m",
            bar_end=datetime(2026, 8, 14, 10, 30, tzinfo=_SHANGHAI),
            result_codes=("buy",),
            lower_tf_confirmation=True,
        )
    )

    assert text.endswith("15m 买入信号 · 10:30\n5m 同向确认")


@pytest.mark.parametrize(
    ("rule_code", "contract", "frequency", "result_codes", "error_code"),
    (
        (
            "subing_entry_signal_v1",
            "JM2609",
            "15m",
            ("buy", "sell"),
            "ALERT_NOTIFICATION_RESULT_INVALID",
        ),
        (
            "subing_entry_signal_v1",
            "JM2609",
            "30m",
            ("buy",),
            "ALERT_NOTIFICATION_FREQUENCY_INVALID",
        ),
        (
            "unknown_rule",
            "JM2609",
            "15m",
            ("buy",),
            "ALERT_NOTIFICATION_RULE_INVALID",
        ),
        (
            "subing_entry_signal_v1",
            " ",
            "15m",
            ("buy",),
            "ALERT_NOTIFICATION_IDENTITY_INVALID",
        ),
    ),
)
def test_subing_renderer_rejects_invalid_message_inputs(
    rule_code: str,
    contract: str,
    frequency: str,
    result_codes: tuple[str, ...],
    error_code: str,
) -> None:
    event = AlertNotificationMessage(
        rule_code=rule_code,
        symbol="jm",
        product_name="焦煤",
        contract=contract,
        frequency=frequency,
        bar_end=datetime(2026, 8, 14, 10, 30, tzinfo=_SHANGHAI),
        result_codes=result_codes,
    )

    with pytest.raises(ValueError, match=f"^{error_code}$"):
        format_alert_message(event)


@pytest.mark.parametrize(
    ("observations", "label"),
    (
        (("buy",), "买入观察"),
        (("sell",), "卖出观察"),
        (("buy", "sell"), "买入观察 + 卖出观察"),
    ),
)
def test_send_uses_exact_concise_template(
    observations: tuple[str, ...],
    label: str,
) -> None:
    calls: list[tuple[str, object, float]] = []

    def post_json(url: str, payload: object, *, timeout: float) -> object:
        calls.append((url, payload, timeout))
        return {"errcode": 0}

    WeComWebhookSender(
        _TEST_WEBHOOK_URL,
        timeout_seconds=3.0,
        post_json=post_json,
    ).send(_event(observations))

    assert calls == [
        (
            _TEST_WEBHOOK_URL,
            {
                "msgtype": "text",
                "text": {
                    "content": (
                        "【归一量化】AG 白银\n\n"
                        f"火天大有 · {label}\n"
                        "主力：AG2610\n"
                        "15m · 10:45 收线"
                    )
                },
            },
            3.0,
        )
    ]


def test_canary_is_fixed_and_does_not_accept_arbitrary_text() -> None:
    payloads: list[object] = []

    def post_json(_url: str, payload: object, *, timeout: float) -> object:
        assert timeout == 5.0
        payloads.append(payload)
        return {"errcode": 0}

    sender = WeComWebhookSender(_TEST_WEBHOOK_URL, post_json=post_json)

    sender.send_canary()

    assert payloads == [
        {
            "msgtype": "text",
            "text": {"content": "【归一量化】企微测试\n\nAlert 通知通道正常"},
        }
    ]


@pytest.mark.parametrize("failure", (TimeoutError("private body"), RuntimeError("raw reply")))
def test_send_failure_is_one_shot_and_log_is_sanitized(
    failure: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_url = _TEST_WEBHOOK_URL
    calls = 0

    def post_json(_url: str, _payload: object, *, timeout: float) -> object:
        nonlocal calls
        calls += 1
        assert timeout == 5.0
        raise failure

    with caplog.at_level(logging.WARNING, logger="app.alerts.wecom"):
        with pytest.raises(WeComSendError, match="WECOM_REQUEST_FAILED") as exc_info:
            WeComWebhookSender(secret_url, post_json=post_json).send(_event(("buy",)))

    assert calls == 1
    log_text = caplog.text
    assert "WECOM_REQUEST_FAILED" in log_text
    assert secret_url not in log_text
    assert str(failure) not in log_text
    rendered_traceback = "".join(traceback.format_exception(exc_info.value))
    assert secret_url not in rendered_traceback
    assert str(failure) not in rendered_traceback


def test_wecom_error_response_is_one_shot_and_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    calls = 0

    def post_json(_url: str, _payload: object, *, timeout: float) -> object:
        nonlocal calls
        calls += 1
        return {"errcode": 40001, "errmsg": "private raw response"}

    with caplog.at_level(logging.WARNING, logger="app.alerts.wecom"):
        with pytest.raises(WeComSendError, match="WECOM_RESPONSE_REJECTED"):
            WeComWebhookSender(_TEST_WEBHOOK_URL, post_json=post_json).send(
                _event(("sell",))
            )

    assert calls == 1
    assert "WECOM_RESPONSE_REJECTED" in caplog.text
    assert "private raw response" not in caplog.text


@pytest.mark.parametrize("errcode", (False, 0.0, "0", None))
def test_malformed_success_errcode_fails_closed(errcode: object) -> None:
    def post_json(_url: str, _payload: object, *, timeout: float) -> object:
        return {"errcode": errcode}

    with pytest.raises(WeComSendError, match="WECOM_RESPONSE_REJECTED"):
        WeComWebhookSender(_TEST_WEBHOOK_URL, post_json=post_json).send(
            _event(("buy",))
        )


@pytest.mark.parametrize(
    "url",
    (
        "https://example.invalid/cgi-bin/webhook/send?" + "key=test-key-12345678",
        "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?" + "key=test-key-12345678",
        "https://qyapi.weixin.qq.com:443/cgi-bin/webhook/send?" + "key=test-key-12345678",
        "https://user@qyapi.weixin.qq.com/cgi-bin/webhook/send?" + "key=test-key-12345678",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/other?" + "key=test-key-12345678",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?" + "key=short",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?"
        + "key=test-key-12345678&extra=1",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?"
        + "key=test-key-12345678#fragment",
    ),
)
def test_sender_rejects_non_wecom_or_ambiguous_webhook_urls(url: str) -> None:
    """Catches Alert content being sent to arbitrary HTTPS destinations."""
    with pytest.raises(ValueError, match="WECOM_WEBHOOK_INVALID"):
        WeComWebhookSender(url, post_json=lambda *_args, **_kwargs: {"errcode": 0})
