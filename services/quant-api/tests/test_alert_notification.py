from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts.notification import (
    ALERT_CANARY_TEXT,
    AlertNotificationMessage,
    format_alert_message,
)
from app.alerts.strategy_payload import (
    StrategyPayloadError,
    SubingStrategyActionPayload,
    serialize_subing_strategy_payload,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from app.market_data.subing_structure import (
    ConfirmedPivot,
    PivotKind,
    _canonical_pivot_id,
)


TRADING_DAY = date(2026, 8, 15)
BAR_END = datetime(2026, 8, 14, 13, 15, tzinfo=UTC)


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
        strategy_payload=None,
    )

    assert format_alert_message(message) == (
        "【归一量化】AG 白银\n\n"
        f"火天大有 · {observation}\n"
        "主力：AG2610\n"
        f"{frequency} · 10:45 收线\n"
        "研究观察，非交易指令"
    )


def test_open_long_with_pivot_uses_exact_typed_payload_facts() -> None:
    payload = _open_payload(
        kind=SubingStrategyActionKind.OPEN_LONG,
        price=Decimal("1234.5000"),
        source=ConfirmationSource.PIVOT_RETEST_REBREAK,
        pivot=_pivot(PivotKind.LOW, Decimal("1200.00")),
    )

    assert format_alert_message(_message(payload)) == (
        "【苏冰策略】焦煤 · JM2601\n\n"
        "15m 建多\n"
        "建仓参考：1234.5\n"
        "原因：\n"
        "- Pivot 回踩再突破\n"
        "- 结构保护：前低 1200"
    )


def test_open_short_without_pivot_uses_required_confirmation_label() -> None:
    payload = _open_payload(
        kind=SubingStrategyActionKind.OPEN_SHORT,
        price=Decimal("987.60"),
        source=ConfirmationSource.MOMENTUM_HOLD,
    )

    assert format_alert_message(_message(payload)) == (
        "【苏冰策略】焦煤 · JM2601\n\n15m 建空\n建仓参考：987.6\n原因：\n- 动量保持"
    )


def test_close_long_matches_the_exact_user_fixture_and_policy_reason_order() -> None:
    payload = _close_payload(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("105"),
        reasons=("EMA21_BREACH_LONG", "MACD_HIGH_DEAD_CROSS"),
    )

    assert format_alert_message(_message(payload)) == (
        "【苏冰策略】焦煤 · JM2601\n\n"
        "15m 清多\n"
        "建仓参考：100\n"
        "清仓参考：105\n"
        "参考变动：+5.00%\n"
        "原因：\n"
        "- 跌破 EMA21\n"
        "- MACD 高位死叉"
    )


def test_close_short_uses_symmetric_copy_and_explicit_positive_sign() -> None:
    payload = _close_payload(
        kind=SubingStrategyActionKind.CLOSE_SHORT,
        entry_price=Decimal("100"),
        exit_price=Decimal("95"),
        reasons=("EMA21_BREACH_SHORT", "MACD_LOW_GOLDEN_CROSS"),
    )

    assert format_alert_message(_message(payload)) == (
        "【苏冰策略】焦煤 · JM2601\n\n"
        "15m 清空\n"
        "建仓参考：100\n"
        "清仓参考：95\n"
        "参考变动：+5.00%\n"
        "原因：\n"
        "- 突破 EMA21\n"
        "- MACD 低位金叉"
    )


def test_terminal_close_uses_committed_terminal_price_and_reason() -> None:
    payload = _close_payload(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("99.2500"),
        reasons=("CONTRACT_SEGMENT_END",),
        terminal=True,
    )

    assert format_alert_message(_message(payload)) == (
        "【苏冰策略】焦煤 · JM2601\n\n"
        "15m 清多\n"
        "建仓参考：100\n"
        "清仓参考：99.25\n"
        "参考变动：-0.75%\n"
        "原因：\n"
        "- 主力合约切换"
    )


def test_prices_use_canonical_decimal_text_without_scientific_notation() -> None:
    payload = _open_payload(
        kind=SubingStrategyActionKind.OPEN_LONG,
        price=Decimal("1E+3"),
        source=ConfirmationSource.FORMAL_V1,
    )

    assert "建仓参考：1000" in format_alert_message(_message(payload))


@pytest.mark.parametrize(
    ("exit_price", "expected"),
    ((Decimal("105"), "+5.00%"), (Decimal("95"), "-5.00%")),
)
def test_reference_change_always_has_explicit_sign_and_two_decimals(
    exit_price: Decimal,
    expected: str,
) -> None:
    payload = _close_payload(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        entry_price=Decimal("100"),
        exit_price=exit_price,
        reasons=("EMA21_BREACH_LONG",),
    )

    assert f"参考变动：{expected}" in format_alert_message(_message(payload))


def test_formatter_rejects_unknown_reason_even_in_typed_payload_instance() -> None:
    payload = _close_payload(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("95"),
        reasons=("EMA21_BREACH_LONG",),
    )
    bypassed = replace(payload, reason_codes=("UNKNOWN_EXIT_REASON",))

    with pytest.raises(
        StrategyPayloadError,
        match="^SUBING_STRATEGY_PAYLOAD_INVALID$",
    ):
        format_alert_message(_message(bypassed))


def test_formatter_rejects_loose_strategy_payload_dict() -> None:
    payload = _open_payload(
        kind=SubingStrategyActionKind.OPEN_LONG,
        price=Decimal("100"),
        source=ConfirmationSource.FORMAL_V1,
    )
    message = replace(_message(payload), strategy_payload=payload.to_json())  # type: ignore[arg-type]

    with pytest.raises(
        StrategyPayloadError,
        match="^SUBING_STRATEGY_PAYLOAD_INVALID$",
    ):
        format_alert_message(message)


def test_notification_boundary_rejects_opposite_side_pivot_in_typed_payload() -> None:
    payload = _open_payload(
        kind=SubingStrategyActionKind.OPEN_LONG,
        price=Decimal("100"),
        source=ConfirmationSource.PIVOT_BREAK_HOLD,
        pivot=_pivot(PivotKind.LOW, Decimal("98")),
    )
    bypassed = replace(
        payload,
        bound_reference_pivot=_pivot(PivotKind.HIGH, Decimal("102")),
    )

    with pytest.raises(
        StrategyPayloadError,
        match="^SUBING_STRATEGY_PAYLOAD_INVALID$",
    ):
        format_alert_message(_message(bypassed))


@pytest.mark.parametrize(
    ("message", "error_code"),
    (
        (
            AlertNotificationMessage(
                rule_code="subing_strategy_v1",
                symbol="jm",
                product_name="焦煤",
                contract="JM2601",
                frequency="30m",
                bar_end=BAR_END,
                result_codes=("open_long",),
                strategy_payload=None,
            ),
            "ALERT_NOTIFICATION_FREQUENCY_INVALID",
        ),
        (
            AlertNotificationMessage(
                rule_code="htdy_original_15m",
                symbol="jm",
                product_name="焦煤",
                contract="JM2601",
                frequency="2m",
                bar_end=BAR_END,
                result_codes=("buy",),
                strategy_payload=None,
            ),
            "ALERT_NOTIFICATION_FREQUENCY_INVALID",
        ),
        (
            AlertNotificationMessage(
                rule_code="unknown_rule",
                symbol="jm",
                product_name="焦煤",
                contract="JM2601",
                frequency="15m",
                bar_end=BAR_END,
                result_codes=("buy",),
                strategy_payload=None,
            ),
            "ALERT_NOTIFICATION_RULE_INVALID",
        ),
        (
            AlertNotificationMessage(
                rule_code="htdy_original_15m",
                symbol="jm",
                product_name="焦煤",
                contract=" ",
                frequency="15m",
                bar_end=BAR_END,
                result_codes=("buy",),
                strategy_payload=None,
            ),
            "ALERT_NOTIFICATION_IDENTITY_INVALID",
        ),
    ),
)
def test_formatter_rejects_invalid_message_inputs(
    message: AlertNotificationMessage,
    error_code: str,
) -> None:
    with pytest.raises(ValueError, match=f"^{error_code}$"):
        format_alert_message(message)


def test_formatter_requires_timezone_aware_bar_end() -> None:
    message = AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="jm",
        product_name="焦煤",
        contract="JM2601",
        frequency="15m",
        bar_end=datetime(2026, 8, 14, 10, 30),
        result_codes=("buy",),
        strategy_payload=None,
    )

    with pytest.raises(ValueError, match="^ALERT_NOTIFICATION_TIMEZONE_REQUIRED$"):
        format_alert_message(message)


def _message(payload: SubingStrategyActionPayload) -> AlertNotificationMessage:
    return AlertNotificationMessage(
        rule_code="subing_strategy_v1",
        symbol=payload.symbol,
        product_name="焦煤",
        contract=payload.contract,
        frequency="15m",
        bar_end=payload.decision_at,
        result_codes=(payload.kind.value,),
        strategy_payload=payload,
    )


def _open_payload(
    *,
    kind: SubingStrategyActionKind,
    price: Decimal,
    source: ConfirmationSource,
    pivot: ConfirmedPivot | None = None,
) -> SubingStrategyActionPayload:
    return serialize_subing_strategy_payload(
        _action(
            kind=kind,
            price=price,
            source=source,
            bound_reference_pivot=pivot,
        )
    )


def _close_payload(
    *,
    kind: SubingStrategyActionKind,
    entry_price: Decimal,
    exit_price: Decimal,
    reasons: tuple[str, ...],
    terminal: bool = False,
) -> SubingStrategyActionPayload:
    entry_kind = (
        SubingStrategyActionKind.OPEN_LONG
        if kind is SubingStrategyActionKind.CLOSE_LONG
        else SubingStrategyActionKind.OPEN_SHORT
    )
    entry = _action(
        kind=entry_kind,
        price=entry_price,
        source=ConfirmationSource.FORMAL_V1,
    )
    exit_decision = BAR_END + timedelta(minutes=45 if terminal else 30)
    exit_action = _action(
        kind=kind,
        price=exit_price,
        reasons=reasons,
        decision_at=exit_decision,
        effective_bar_end=(
            exit_decision if terminal else exit_decision + timedelta(minutes=15)
        ),
        fill_basis=(
            SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE
            if terminal
            else SubingStrategyFillBasis.NEXT_BAR_OPEN
        ),
        episode_id=entry.episode_id,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=exit_action,
        completed_15m_bars=(
            _bar(BAR_END + timedelta(minutes=15), entry_price),
            _bar(BAR_END + timedelta(minutes=30), exit_price),
            _bar(BAR_END + timedelta(minutes=45), exit_price),
        ),
        latest_reference_price=None,
    )
    return serialize_subing_strategy_payload(exit_action, episode=episode)


def _action(
    *,
    kind: SubingStrategyActionKind,
    price: Decimal,
    source: ConfirmationSource | None = None,
    reasons: tuple[str, ...] = (),
    decision_at: datetime = BAR_END,
    effective_bar_end: datetime = BAR_END + timedelta(minutes=15),
    fill_basis: SubingStrategyFillBasis = SubingStrategyFillBasis.NEXT_BAR_OPEN,
    episode_id: str | None = None,
    bound_reference_pivot: ConfirmedPivot | None = None,
) -> SubingStrategyAction:
    identity = {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "symbol": "jm",
        "contract": "JM2601",
        "segment_start_trading_day": TRADING_DAY.isoformat(),
        "opportunity_id": "subing-opportunity:notification-test",
        "kind": kind.value,
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": fill_basis.value,
    }
    is_open = kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=(
            subing_strategy_episode_id(identity) if is_open else str(episode_id)
        ),
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=kind,
        symbol="jm",
        contract="JM2601",
        trading_day=TRADING_DAY,
        segment_start_trading_day=TRADING_DAY,
        opportunity_id="subing-opportunity:notification-test",
        decision_at=decision_at,
        effective_open_at=(
            effective_bar_end - timedelta(minutes=15)
            if fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN
            else None
        ),
        effective_bar_end=effective_bar_end,
        reference_price=price,
        fill_basis=fill_basis,
        confirmation_source=source if is_open else None,
        reason_codes=() if is_open else reasons,
        direction_context_source_day=TRADING_DAY if is_open else None,
        direction_context_target_day=TRADING_DAY if is_open else None,
        bound_reference_pivot=bound_reference_pivot,
    )


def _bar(bar_end: datetime, close: Decimal) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=TRADING_DAY,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1"),
        turnover=None,
        open_interest=None,
    )


def _pivot(kind: PivotKind, price: Decimal) -> ConfirmedPivot:
    pivot_time = BAR_END - timedelta(minutes=30)
    return ConfirmedPivot(
        pivot_id=_canonical_pivot_id(
            contract="JM2601",
            segment_start_trading_day=TRADING_DAY,
            source_timeframe=BarFrequency.M5,
            kind=kind,
            pivot_time=pivot_time,
        ),
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_time,
        confirmed_at=BAR_END - timedelta(minutes=15),
        price=price,
        contract="JM2601",
        segment_start_trading_day=TRADING_DAY,
    )
