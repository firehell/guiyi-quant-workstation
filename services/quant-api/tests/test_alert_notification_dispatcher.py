from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts.notification import (
    ALERT_AUDIENCE_HTDY_OBSERVERS,
    ALERT_AUDIENCE_OWNER,
    AlertNotificationDispatcher,
    AlertNotificationMessage,
    NotificationDelivery,
    NotificationTransportError,
    ProviderAcceptance,
)
from app.alerts.strategy_payload import serialize_subing_strategy_payload
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.deliveries: list[NotificationDelivery] = []

    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance:
        self.deliveries.append(delivery)
        return ProviderAcceptance("0123456789abcdef0123456789abcdef")


def _message(rule_code: str = "htdy_original_15m") -> AlertNotificationMessage:
    if rule_code == "subing_strategy_v1":
        decision_at = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
        effective_bar_end = decision_at + timedelta(minutes=15)
        identity = {
            "strategy_id": "subing_strategy_v1",
            "formula_version": "subing_strategy_15m_v1",
            "symbol": "jm",
            "contract": "JM2609",
            "segment_start_trading_day": "2026-08-20",
            "opportunity_id": "subing-opportunity:dispatcher-test",
            "kind": "open_long",
            "decision_at": decision_at.isoformat(),
            "effective_bar_end": effective_bar_end.isoformat(),
            "fill_basis": "next_bar_open",
        }
        action = SubingStrategyAction(
            action_id=subing_strategy_action_id(identity),
            episode_id=subing_strategy_episode_id(identity),
            strategy_id="subing_strategy_v1",
            formula_version="subing_strategy_15m_v1",
            kind=SubingStrategyActionKind.OPEN_LONG,
            symbol="jm",
            contract="JM2609",
            trading_day=date(2026, 8, 20),
            segment_start_trading_day=date(2026, 8, 20),
            opportunity_id="subing-opportunity:dispatcher-test",
            decision_at=decision_at,
            effective_open_at=decision_at,
            effective_bar_end=effective_bar_end,
            reference_price=Decimal("100"),
            fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
            confirmation_source=ConfirmationSource.FORMAL_V1,
            reason_codes=(),
            direction_context_source_day=date(2026, 8, 20),
            direction_context_target_day=date(2026, 8, 20),
            bound_reference_pivot=None,
        )
        return AlertNotificationMessage(
            rule_code=rule_code,
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="15m",
            bar_end=decision_at,
            result_codes=("open_long",),
            strategy_payload=serialize_subing_strategy_payload(action),
        )
    return AlertNotificationMessage(
        rule_code=rule_code,
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=datetime(2026, 8, 20, 10, 30, tzinfo=UTC),
        result_codes=("buy",),
        strategy_payload=None,
    )


def test_dispatcher_routes_htdy_to_one_observer_audience_request() -> None:
    transport = RecordingTransport()
    dispatcher = AlertNotificationDispatcher(transport)

    accepted = dispatcher.send(_message())

    assert len(transport.deliveries) == 1
    assert accepted == ProviderAcceptance("0123456789abcdef0123456789abcdef")
    delivery = transport.deliveries[0]
    assert delivery.audience == ALERT_AUDIENCE_HTDY_OBSERVERS
    assert delivery.title == "归一量化 火天大有"
    assert "研究观察，非交易指令" in delivery.content


def test_dispatcher_routes_subing_to_owner_only() -> None:
    transport = RecordingTransport()
    dispatcher = AlertNotificationDispatcher(transport)

    dispatcher.send(_message("subing_strategy_v1"))

    assert [item.audience for item in transport.deliveries] == [ALERT_AUDIENCE_OWNER]
    assert transport.deliveries[0].title == "归一量化 苏冰"


def test_canary_accepts_only_fixed_audiences_and_includes_audience_and_time() -> None:
    transport = RecordingTransport()
    dispatcher = AlertNotificationDispatcher(
        transport,
        clock=lambda: datetime(2026, 8, 20, 10, 31, 12, tzinfo=UTC),
    )

    accepted = dispatcher.send_canary(ALERT_AUDIENCE_HTDY_OBSERVERS)

    assert accepted.reference == "0123456789abcdef0123456789abcdef"
    delivery = transport.deliveries[0]
    assert delivery.audience == ALERT_AUDIENCE_HTDY_OBSERVERS
    assert "htdy_observers" in delivery.content
    assert "2026-08-20T10:31:12+00:00" in delivery.content
    assert accepted.reference not in repr(accepted)

    with pytest.raises(
        NotificationTransportError,
        match="^ALERT_NOTIFICATION_AUDIENCE_INVALID$",
    ):
        dispatcher.send_canary("friend1")

    assert len(transport.deliveries) == 1


def test_unexpected_transport_error_is_not_swallowed() -> None:
    class BrokenTransport:
        def send(self, _delivery: NotificationDelivery) -> ProviderAcceptance:
            raise AttributeError("implementation bug")

    dispatcher = AlertNotificationDispatcher(BrokenTransport())

    with pytest.raises(AttributeError, match="implementation bug"):
        dispatcher.send(_message())
