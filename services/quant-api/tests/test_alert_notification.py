from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.alerts.notification import (
    ALERT_CANARY_TEXT,
    AlertNotificationMessage,
    format_alert_message,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_canary_text_is_channel_neutral() -> None:
    assert ALERT_CANARY_TEXT == "【归一量化】微信通知测试\n\nAlert 通知通道正常"


@pytest.mark.parametrize(
    ("result_codes", "observation"),
    (
        (("buy",), "买入观察"),
        (("sell",), "卖出观察"),
        (("buy", "sell"), "买入观察 + 卖出观察"),
    ),
)
@pytest.mark.parametrize(
    "frequency",
    ("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
)
def test_htdy_message_keeps_exact_copy(
    result_codes: tuple[str, ...],
    observation: str,
    frequency: str,
) -> None:
    message = AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="ag",
        product_name="白银",
        contract="AG2610",
        frequency=frequency,
        bar_end=datetime(2026, 8, 13, 2, 45, tzinfo=UTC),
        result_codes=result_codes,
    )

    assert format_alert_message(message) == (
        "【归一量化】AG 白银\n\n"
        f"火天大有 · {observation}\n"
        "主力：AG2610\n"
        f"{frequency} · 10:45 收线\n"
        "研究观察，非交易指令"
    )


def test_subing_5m_message_is_short() -> None:
    message = AlertNotificationMessage(
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="5m",
        bar_end=datetime(2026, 8, 14, 10, 25, tzinfo=_SHANGHAI),
        result_codes=("buy",),
    )

    assert format_alert_message(message) == "【苏冰】焦煤 · JM2609\n\n5m 买入信号 · 10:25"


def test_subing_15m_lower_tf_confirmation_adds_one_line() -> None:
    message = AlertNotificationMessage(
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=datetime(2026, 8, 14, 10, 30, tzinfo=_SHANGHAI),
        result_codes=("sell",),
        lower_tf_confirmation=True,
    )

    assert format_alert_message(message) == (
        "【苏冰】焦煤 · JM2609\n\n15m 卖出信号 · 10:30\n5m 同向确认"
    )


@pytest.mark.parametrize(
    ("rule_code", "contract", "frequency", "result_codes", "lower_tf", "error_code"),
    (
        (
            "subing_entry_signal_v1",
            "JM2609",
            "5m",
            ("buy",),
            True,
            "ALERT_NOTIFICATION_LOWER_TF_CONFIRMATION_INVALID",
        ),
        (
            "subing_entry_signal_v1",
            "JM2609",
            "15m",
            ("buy", "sell"),
            False,
            "ALERT_NOTIFICATION_RESULT_INVALID",
        ),
        (
            "subing_entry_signal_v1",
            "JM2609",
            "30m",
            ("buy",),
            False,
            "ALERT_NOTIFICATION_FREQUENCY_INVALID",
        ),
        (
            "htdy_original_15m",
            "JM2609",
            "2m",
            ("buy",),
            False,
            "ALERT_NOTIFICATION_FREQUENCY_INVALID",
        ),
        (
            "htdy_original_15m",
            "JM2609",
            "15m",
            (),
            False,
            "ALERT_NOTIFICATION_RESULT_INVALID",
        ),
        (
            "unknown_rule",
            "JM2609",
            "15m",
            ("buy",),
            False,
            "ALERT_NOTIFICATION_RULE_INVALID",
        ),
        (
            "subing_entry_signal_v1",
            " ",
            "15m",
            ("buy",),
            False,
            "ALERT_NOTIFICATION_IDENTITY_INVALID",
        ),
    ),
)
def test_formatter_rejects_invalid_message_inputs(
    rule_code: str,
    contract: str,
    frequency: str,
    result_codes: tuple[str, ...],
    lower_tf: bool,
    error_code: str,
) -> None:
    message = AlertNotificationMessage(
        rule_code=rule_code,
        symbol="jm",
        product_name="焦煤",
        contract=contract,
        frequency=frequency,
        bar_end=datetime(2026, 8, 14, 10, 30, tzinfo=_SHANGHAI),
        result_codes=result_codes,
        lower_tf_confirmation=lower_tf,
    )

    with pytest.raises(ValueError, match=f"^{error_code}$"):
        format_alert_message(message)


def test_formatter_requires_timezone_aware_bar_end() -> None:
    message = AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=datetime(2026, 8, 14, 10, 30),
        result_codes=("buy",),
    )

    with pytest.raises(ValueError, match="^ALERT_NOTIFICATION_TIMEZONE_REQUIRED$"):
        format_alert_message(message)
