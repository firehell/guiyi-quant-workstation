from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertObservationCandidate
from app.alerts.models import AlertRule, AlertEvent
from app.alerts.notification import ProviderAcceptance, NotificationTransportError
from app.alerts.runtime import AlertRuntime
from app.market_data.domain import CanonicalBar
from app.market_data.live_market import LiveRecoveryState
from app.market_data.market_read_service import MarketReadWindow, MarketReadWindowError


@pytest.mark.parametrize("provider_fails", [False, True])
@pytest.mark.parametrize("rule_code", ["subing_ths_alert_15m_v1", "htdy_original_15m"])
def test_recovery_skips_old_and_queued_triggers_new_event_commits_before_one_send(rule_code, provider_fails, tmp_path):
    from app.market_data.live_recovery_guard import recovery_guard
    engine = create_engine("sqlite:///:memory:")
    AlertRule.__table__.create(engine)
    AlertEvent.__table__.create(engine)
    with Session(engine) as session:
        session.add(AlertRule(rule_code=rule_code, enabled=True, scope_product_frequencies={"jm": ["15m"]}))
        session.commit()
    through = datetime(2026, 9, 7, 6, 1, tzinfo=UTC)
    state = LiveRecoveryState(1, through)
    sent = []

    class Reader:
        def bars_until(self, query, *, trading_day, end, limit):
            bar = CanonicalBar(end, trading_day, 1, 1, 1, 1, 1, None, None)
            return MarketReadWindow("jm", "actual_dominant", "15m", trading_day, "JM2701", end,
                                    (bar,), ("JM2701",), recovery_state=state)

        def assert_window_current(self, window):
            if window.recovery_state != state:
                raise MarketReadWindowError("MARKET_READ_RECOVERY_CHANGED")

    class Evaluator:
        def evaluate_candidates(self, reader, window):
            return (AlertObservationCandidate(window.cutoff, window.trading_day, window.contract, ("buy",)),)

    class Sender:
        def send(self, message):
            with pytest.raises(RuntimeError, match="LIVE_RECOVERY_BUSY"):
                with recovery_guard("jm", root=tmp_path):
                    raise AssertionError("recovery entered during Event/send")
            with Session(engine) as session:
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
            sent.append(message)
            if provider_fails:
                raise NotificationTransportError("NOTIFICATION_TRANSPORT_FAILED")
            return ProviderAcceptance()

    def runtime():
        return AlertRuntime(session_factory=lambda: Session(engine), market_read_factory=lambda _: Reader(),
                            live_processing_guard=lambda symbol: recovery_guard(symbol, root=tmp_path),
                            evaluators={rule_code: Evaluator()}, sender=Sender(), operational_products=("jm",),
                            taxonomy={"jm": SimpleNamespace(name="焦煤")}, clock=lambda: through + timedelta(hours=1))

    def trigger(instance, end):
        instance.process_message("live:bar:jm:15m", {
            "bar_end": end.isoformat(), "trading_day": "2026-09-07", "open": "1", "high": "1",
            "low": "1", "close": "1", "volume": "1", "turnover": None, "open_interest": None,
        })

    active = runtime()
    for minute in (30, 45, 60):
        trigger(active, through.replace(hour=5, minute=0) + timedelta(minutes=minute))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
    assert sent == []
    end = through.replace(minute=15)
    trigger(active, end)
    trigger(active, end)
    trigger(runtime(), end)  # restart must not resend an immutable Event
    assert len(sent) == 1
    assert sent[0].bar_end == end
