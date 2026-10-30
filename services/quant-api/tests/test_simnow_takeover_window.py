"""Offline authority fixtures; no credentials, Redis, broker or database server."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace as NS
import pytest
from app import simnow_takeover_window as w

T = datetime(2026, 10, 30, 7, tzinfo=UTC)
D = date(2026, 11, 2)


@pytest.fixture
def authority(monkeypatch):
    state = dict(
        count=60,
        gap=1000,
        owner="A2701",
        phase=w.MarketPhase.CLOSED,
        calendar=True,
        night=True,
        elapsed=0,
    )

    @dataclass
    class Owner:
        contract: str

    class Clock:
        @staticmethod
        def now(_):
            return T + timedelta(seconds=state["elapsed"])

        strptime = staticmethod(datetime.strptime)

    class Resolver:
        def __init__(self, db):
            pass

        def resolve(self, p, at):
            start = T + timedelta(seconds=state["gap"])
            if at == start:
                return NS(
                    phase=w.MarketPhase.TRADING,
                    current_session=NS(start=start),
                    trading_day=D,
                )
            return NS(
                phase=state["phase"], current_session=None, next_session_start=start
            )

    monkeypatch.setattr(w, "datetime", Clock)
    monkeypatch.setattr(
        w,
        "load_operational_products",
        lambda: ["p" + str(i) for i in range(state["count"])],
    )
    monkeypatch.setattr(w, "MarketPhaseResolver", Resolver)
    monkeypatch.setattr(
        w,
        "build_market_data_service",
        lambda db: NS(
            catalog=NS(exchange_for_symbol=lambda p: "DCE"),
            dominant_segment_for_day=lambda p, d: Owner(state["owner"]),
        ),
    )
    monkeypatch.setattr(
        w,
        "resolved_session_windows_for_trading_day",
        lambda *args, **kw: (
            NS(
                name="night",
                is_night=True,
                window=NS(
                    start=T + timedelta(seconds=1000), end=T + timedelta(hours=3)
                ),
            ),
            NS(
                name="day",
                is_night=False,
                window=NS(
                    start=T + timedelta(days=2), end=T + timedelta(days=2, hours=6)
                ),
            ),
        ),
    )
    db = NS(
        scalar=lambda _: NS(
            is_trading_day=state["calendar"],
            has_night_session=state["night"],
            provider="rqdata",
        )
    )
    return db, state


def test_target_day_full_sessions_and_static_identity_are_shared(authority):
    db, state = authority
    first = w._resolve(db, T, None, True)
    later = w._resolve(db, T + timedelta(seconds=100), D, False)
    assert first["trading_day"] == "20261102" and first["product_count"] == 60
    assert len(first["sessions"]) == 2
    assert first["sessions"] == later["sessions"]
    assert first["session_facts_sha256"] == later["session_facts_sha256"]
    state["owner"] = "A2705"
    assert (
        w._resolve(db, T, D, False)["session_facts_sha256"]
        != first["session_facts_sha256"]
    )


@pytest.mark.parametrize(
    "change", ["scope", "unknown", "calendar", "slow", "strict660"]
)
def test_incomplete_or_expired_window_fails_closed(authority, change):
    db, state = authority
    if change == "scope":
        state["count"] = 59
    if change == "unknown":
        state["phase"] = w.MarketPhase.UNKNOWN
    if change == "calendar":
        state["calendar"] = False
    if change == "slow":
        state["elapsed"] = 341
    if change == "strict660":
        state["gap"] = 660
    with pytest.raises(ValueError):
        w._resolve(db, T, D, True)


def test_calendar_without_night_filters_night_and_changes_identity(authority):
    db, state = authority
    first = w._resolve(db, T, D, False)
    state["night"] = False
    second = w._resolve(db, T, D, False)
    assert len(second["sessions"]) == 1
    assert first["session_facts_sha256"] != second["session_facts_sha256"]
