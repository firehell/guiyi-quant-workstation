"""Ordinary upgrade consumes the existing budget and rechecks authority before SDK."""

from datetime import UTC, datetime, date, timedelta
from types import SimpleNamespace as NS
import pytest
from guiyi_quant.simnow_execution.supervisor import Supervisor
from guiyi_quant.simnow_execution import ordinary_takeover as ordinary

T = datetime(2026, 11, 2, 1, tzinfo=UTC)


def fixture(monkeypatch):
    calls = []
    s = object.__new__(Supervisor)
    s.settings = NS(
        ordinary_takeover_permit="private-permit", deployment_connection_permit=None
    )
    s.inbox = NS(
        blocked=lambda day: False, attempt=lambda day: calls.append("budget") or 1
    )
    s.market = NS(
        plan=lambda now: NS(connect_allowed=True, trading_day=date(2026, 11, 2)),
        ordinary_takeover_window=lambda day, now: dict(day=day),
    )
    s.run_id = "a" * 32
    s.folder = "private-folder"
    s.now = lambda: T
    s.status = lambda *a: None
    s.prepare = lambda day: calls.append("prepare")
    s.factory = lambda *a: (
        calls.append("factory") or NS(connect=lambda: calls.append("SDK"))
    )
    monkeypatch.setattr(ordinary, "permit_required", lambda *a: True)
    monkeypatch.setattr(
        ordinary,
        "consume",
        lambda *a, **k: (calls.append("claim") or 1, (T, T + timedelta(seconds=120))),
    )
    monkeypatch.setattr(
        ordinary,
        "validate_connection",
        lambda window, now, authority: calls.append("authority") or authority(),
    )
    return s, calls


def test_claim_and_authority_checks_precede_sdk(monkeypatch):
    s, calls = fixture(monkeypatch)
    s.connect("20261102")
    assert calls == ["claim", "authority", "factory", "authority", "SDK", "prepare"]


def test_authority_day_drift_after_factory_never_connects_sdk(monkeypatch):
    s, calls = fixture(monkeypatch)

    def factory(*args):
        calls.append("factory")
        s.market.plan = lambda now: NS(
            connect_allowed=True, trading_day=date(2026, 11, 3)
        )
        return NS(connect=lambda: calls.append("SDK"))

    s.factory = factory
    with pytest.raises(ValueError, match="ORDINARY_TAKEOVER_INVALID"):
        s.connect("20261102")
    assert calls == ["claim", "authority", "factory", "authority"]


def test_verified_later_authoritative_day_uses_original_budget(monkeypatch):
    s, calls = fixture(monkeypatch)
    monkeypatch.setattr(ordinary, "permit_required", lambda *a: False)
    s.connect("20261102")
    assert calls == ["budget", "factory", "SDK", "prepare"]
