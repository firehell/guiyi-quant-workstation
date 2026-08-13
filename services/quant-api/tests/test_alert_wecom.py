from __future__ import annotations

from datetime import UTC, datetime
import logging
import traceback

import pytest

from app.alerts.wecom import AlertEventMessage, WeComSendError, WeComWebhookSender


def _event(observations: tuple[str, ...]) -> AlertEventMessage:
    return AlertEventMessage(
        symbol="ag",
        product_name="白银",
        contract="AG2610",
        frequency="15m",
        bar_end=datetime(2026, 8, 13, 2, 45, tzinfo=UTC),
        observation_types=observations,
    )


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
        "https://example.invalid/webhook",
        timeout_seconds=3.0,
        post_json=post_json,
    ).send(_event(observations))

    assert calls == [
        (
            "https://example.invalid/webhook",
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

    sender = WeComWebhookSender("https://example.invalid/webhook", post_json=post_json)

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
    secret_url = "https://example.invalid/private-key-value"
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
            WeComWebhookSender("https://example.invalid/webhook", post_json=post_json).send(
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
        WeComWebhookSender("https://example.invalid/webhook", post_json=post_json).send(
            _event(("buy",))
        )
