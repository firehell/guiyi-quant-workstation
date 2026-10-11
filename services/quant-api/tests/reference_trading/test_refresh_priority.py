from threading import Event, Thread
from types import SimpleNamespace

import pytest

from app.reference_trading.refresh_priority import RefreshPriority


def test_one_background_unit_requires_a_new_healthy_foreground_round():
    gate = RefreshPriority()
    assert not gate.can_run()
    gate.grant()
    assert gate.begin()
    gate.grant()  # Healthy callbacks during an active unit must not bank permits.
    gate.finish()
    assert not gate.can_run()
    gate.grant()
    assert gate.can_run()


def test_foreground_withdraws_unclaimed_permission():
    gate = RefreshPriority()
    gate.grant()
    with gate.foreground():
        assert not gate.begin()
        gate.grant()
    assert not gate.can_run()


def test_foreground_cooperatively_requests_yield_without_releasing_a_source_lock():
    gate = RefreshPriority(wait_seconds=1)
    gate.grant()
    assert gate.begin()
    entered = Event()
    def foreground():
        with gate.observation(), gate.foreground():
            entered.set()
    thread = Thread(target=foreground)
    thread.start()
    assert gate._yield.wait(timeout=1)
    assert not entered.is_set()
    gate.finish()  # The actual source owner must finish; no TTL authorizes effects.
    thread.join(1)
    assert entered.is_set()
    assert not gate.can_run()


def test_wait_budget_expiry_does_not_claim_background_has_finished():
    gate = RefreshPriority(wait_seconds=0)
    gate.grant()
    assert gate.begin()
    with gate.observation(), gate.foreground():
        assert gate.yield_requested()
        assert not gate.can_run()
        assert not gate.begin()
    assert gate.yield_requested()
    gate.finish()


def test_healthy_round_permission_does_not_restart_the_refresh_thread():
    from app.reference_trading.worker_entry import defer_historical_refresh
    gate = RefreshPriority()
    starts = []
    worker = SimpleNamespace()
    refresh = SimpleNamespace(start=lambda: starts.append(True))
    defer_historical_refresh(worker, refresh, should_stop=lambda: False, priority=gate)
    worker.after_healthy_round()
    assert gate.begin()
    worker.after_healthy_round()
    gate.finish()
    assert not gate.can_run()
    worker.after_healthy_round()
    assert gate.can_run()
    assert starts == [True]


def test_priority_permission_does_not_bypass_external_catalog_contention():
    from app.reference_trading.worker_entry import _acquire_canonical_lease
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    gate = RefreshPriority(wait_seconds=0)
    with gate.foreground(), pytest.raises(ForwardInputUnavailable, match='SOURCE_BUSY'):
        _acquire_canonical_lease(SimpleNamespace(acquire_maintenance_lock=lambda: None), deadline=None)


def test_normal_scan_does_not_cancel_a_background_source_read():
    gate = RefreshPriority(wait_seconds=0)
    gate.grant()
    assert gate.begin()
    with gate.foreground():
        assert not gate.yield_requested()
        assert not gate.begin()
    gate.finish()
    assert not gate.can_run()


@pytest.mark.parametrize('phase,next_seconds,allowed', [
    ('BREAK', 141, True), ('CLOSED', 3600, True), ('TRADING', 3600, False),
    ('UNKNOWN', 3600, False), ('BREAK', 140, False), ('CLOSED', None, False),
])
def test_background_permission_requires_all_authoritative_sessions_in_rest(
    monkeypatch, phase, next_seconds, allowed,
):
    from datetime import UTC, datetime, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
    from app.reference_trading.refresh_priority import historical_rest_allowed
    now = datetime(2026, 10, 11, tzinfo=UTC)
    resolved = []
    def resolve(self, product, actual_now):
        assert actual_now == now
        resolved.append(product)
        return SimpleNamespace(phase=MarketPhase(phase), next_session_start=(
            None if next_seconds is None else now + timedelta(seconds=next_seconds)))
    monkeypatch.setattr(MarketPhaseResolver, 'resolve', resolve)
    factory = sessionmaker(bind=create_engine('sqlite://'))
    products = tuple(f'p{index}' for index in range(60))
    assert historical_rest_allowed(factory, products, now=now) is allowed
    assert len(resolved) == (60 if allowed else 1)
    assert not historical_rest_allowed(factory, products[:-1], now=now)
