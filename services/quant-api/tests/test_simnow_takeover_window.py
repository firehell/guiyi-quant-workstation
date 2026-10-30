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
        == first["session_facts_sha256"]
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


def test_future_mapping_missing_does_not_prove_or_block_session_window(
    authority, monkeypatch
):
    db, state = authority
    market = w.build_market_data_service(db)

    def missing(*args):
        raise ValueError("MAIN_CONTRACT_MAP_MISSING")

    market.dominant_segment_for_day = missing
    monkeypatch.setattr(w, "build_market_data_service", lambda db: market)
    result = w._resolve(db, T, None, True)
    assert (
        result["window_open"] and result["policy"] == "simnow_ordinary_next_session_v2"
    )
    # Exercise the real execution authority inlet: no historical-anchor fallback.
    from contextlib import contextmanager
    from app import simnow_controlled_market as execution

    bridge = object.__new__(execution.MarketBridge)
    bridge.product = "p0"

    @contextmanager
    def reader():
        yield db, NS()

    bridge.reader = reader
    monkeypatch.setattr(execution, "build_market_data_service", lambda db: market)
    with pytest.raises(ValueError, match="MAIN_CONTRACT_MAP_MISSING"):
        bridge.authority(D, T)


def test_historical_anchor_selects_latest_fully_ended_day(authority, monkeypatch):
    db, state = authority
    days = [date(2026, 10, 30), date(2026, 10, 29)]
    db.scalars = lambda query: days
    monkeypatch.setattr(
        w,
        "resolved_session_windows_for_trading_day",
        lambda *args, **kw: (
            NS(
                name="actual",
                is_night=False,
                window=NS(
                    start=T - timedelta(hours=2),
                    end=T + timedelta(minutes=15)
                    if kw["trading_day"] == days[0]
                    else T - timedelta(hours=1),
                ),
            ),
        ),
    )
    anchor = w._historical(db, T)
    assert anchor["trading_day"] == "20261029" and anchor["product_count"] == 60
    assert "checked_at" not in anchor and len(anchor["entries"]) == 60
    state["owner"] = "A2705"
    assert w._historical(db, T)["sha256"] != anchor["sha256"]


def test_latest_completed_mapping_missing_never_falls_back(authority, monkeypatch):
    db, state = authority
    db.scalars = lambda query: [date(2026, 10, 30), date(2026, 10, 29)]
    monkeypatch.setattr(
        w,
        "resolved_session_windows_for_trading_day",
        lambda *args, **kw: (
            NS(
                name="actual",
                is_night=False,
                window=NS(start=T - timedelta(hours=2), end=T - timedelta(hours=1)),
            ),
        ),
    )
    market = w.build_market_data_service(db)
    calls = []

    def missing(product, day):
        calls.append(day)
        raise ValueError("MAIN_CONTRACT_MAP_MISSING")

    market.dominant_segment_for_day = missing
    monkeypatch.setattr(w, "build_market_data_service", lambda db: market)
    with pytest.raises(ValueError, match="MAIN_CONTRACT_MAP_MISSING"):
        w._historical(db, T)
    assert calls == [date(2026, 10, 30)]
