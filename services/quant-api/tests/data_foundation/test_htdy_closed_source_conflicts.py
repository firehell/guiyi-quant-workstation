"""Closed-day disposition fixtures are not future market observations."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.htdy_input_admission import audit_product
from app.market_data.live_market import LiveBarObservation, LiveRecoveryState
from app.market_data.market_read_service import MarketReadService, MarketReadWindowError
from test_htdy_input_admission import Market, AT

DAY = date(2026, 10, 23)
NEXT_DAY = date(2026, 10, 26)
NEXT_START = datetime(2026, 10, 26, 1, tzinfo=UTC)


@pytest.fixture
def closed():
    mds = Market()
    mds.hours = tuple(b for b in mds.hours if b.trading_day != NEXT_DAY)
    mds.minutes.pop(NEXT_DAY)
    mds.sessions[NEXT_DAY] = (
        SessionWindow(NEXT_START, NEXT_START + timedelta(hours=5, minutes=30)),
    )
    original_m1 = list(mds.minutes[DAY])
    original_m1[-2] = replace(original_m1[-2], close=Decimal("100.5"))
    original_h1 = aggregate_from_1m(
        tuple(original_m1), target_frequency="60m", sessions=mds.sessions[DAY]
    )
    original = {"1m": tuple(original_m1), "60m": original_h1}
    phase = SimpleNamespace(
        resolve=lambda _p, t: SimpleNamespace(
            phase=SimpleNamespace(value="CLOSED" if t < NEXT_START else "TRADING"),
            trading_day=None if t < NEXT_START else NEXT_DAY,
            next_session_start=NEXT_START if t < NEXT_START else None,
            current_session=None if t < NEXT_START else mds.sessions[NEXT_DAY][0],
        ),
        completed_observation_trading_day=lambda *_: DAY,
    )

    def read_expected(query, expected):
        available = (
            mds.hours
            if query.frequency.value == "60m"
            else tuple(b for bars in mds.minutes.values() for b in bars)
        )
        bars = tuple(b for b in available if query.start < b.bar_end <= query.end)
        if tuple(b.bar_end for b in bars) != expected:
            raise ValueError("DATASET_OR_PARTITION_MISSING")
        return SimpleNamespace(bars=bars)

    mds.query_maintenance_expected = read_expected
    mds.catalog = SimpleNamespace(
        contract_fact=lambda p, c: SimpleNamespace(
            provider="rqdata",
            symbol=p,
            contract=c,
            listed_date=date(2025, 1, 1),
            expired_date=date(2027, 1, 1),
        )
    )
    mds.contract_source_evidence = lambda **kw: {
        "contract": "AG2612",
        "frequency": kw["frequency"].value,
        "partitions": [{"content_sha256": "a" * 64, "quality_sha256": None}],
    }
    store = SimpleNamespace(
        subscriptions=lambda _: {"ag": "AG2612"},
        recovery_state=lambda *_: None,
        bar_observations=lambda _day, _product, freq, *_args, **_kw: tuple(
            LiveBarObservation(b, "AG2612") for b in original[freq]
        ),
    )
    native = MarketReadService(
        market_data=mds,
        phase_resolver=phase,
        operational_products=("ag",),
        live_store=store,
    )
    coverage = SimpleNamespace(latest_complete_day=lambda _: DAY)
    return native, coverage, mds, store, original


def test_closed_revision_is_explained_without_releasing_old_input(closed):
    native, coverage, _mds, _store, original = closed
    before = dict(original)
    row = audit_product(native, coverage, "ag", AT)
    assert row["status"] == "CLOSED_SOURCE_REVISION_WAIT_NEW_OBSERVATION"
    assert row["calculation_input"]["status"] == "BLOCKED"
    assert row["live"]["status"] == "CONTINUITY_VERIFIED"  # H1 identical here.
    proof = row["source_conflict"]
    assert proof["status"] == "CLOSED_DAY_DIFFERENCE_VERIFIED"
    assert proof["frequencies"]["1m"]["different_bar_count"] == 1
    assert proof["frequencies"]["60m"]["different_bar_count"] == 0
    assert proof["next_trading_day"] == NEXT_DAY
    assert row["future_signal"]["status"] == "WAIT_NEW_TRADING_DAY_OBSERVATION"
    assert row["future_signal"]["eligible_now"] is False
    assert row["future_signal"]["first_seen_proven"] is False
    assert original == before


def test_h1_revision_retains_both_complete_fact_sets(closed):
    native, coverage, mds, _store, original = closed
    changed = list(original["1m"])
    changed[-1] = replace(changed[-1], volume=Decimal(2), close=Decimal("100.5"))
    original["1m"] = tuple(changed)
    original["60m"] = aggregate_from_1m(
        original["1m"], target_frequency="60m", sessions=mds.sessions[DAY]
    )
    row = audit_product(native, coverage, "ag", AT)
    assert row["source_conflict"]["frequencies"]["60m"]["different_bar_count"] == 1
    assert row["live"]["status"] == row["calculation_input"]["status"] == "BLOCKED"
    assert row["status"] == "CLOSED_SOURCE_REVISION_WAIT_NEW_OBSERVATION"


@pytest.mark.parametrize(
    "fault",
    [
        "trading",
        "break",
        "incomplete_day",
        "next_day_same",
        "next_map_missing",
        "raw_gap",
        "raw_duplicate",
        "raw_h1_mismatch",
        "future_recovery",
        "unknown_optional",
        "source_evidence_missing",
    ],
)
def test_unproved_difference_stays_blocked(closed, fault):
    native, coverage, mds, store, original = closed
    resolve = native._phase_resolver.resolve
    if fault in {"trading", "break"}:
        native._phase_resolver.resolve = lambda p, t: SimpleNamespace(
            phase=SimpleNamespace(value=fault.upper()),
            trading_day=DAY,
            next_session_start=NEXT_START,
            current_session=None,
        )
    elif fault == "incomplete_day":
        coverage.latest_complete_day = lambda _: DAY - timedelta(days=1)
    elif fault == "next_day_same":
        native._phase_resolver.resolve = lambda p, t: (
            resolve(p, t)
            if t < NEXT_START
            else SimpleNamespace(
                phase=SimpleNamespace(value="TRADING"),
                trading_day=DAY,
                current_session=mds.sessions[NEXT_DAY][0],
                next_session_start=None,
            )
        )
    elif fault == "next_map_missing":
        old = mds.dominant_segment_for_day

        def owner(p, d):
            if d == NEXT_DAY:
                raise ValueError("MAIN_CONTRACT_MAP_MISSING")
            return old(p, d)

        mds.dominant_segment_for_day = owner
    elif fault == "raw_gap":
        original["1m"] = original["1m"][:-1]
    elif fault == "raw_duplicate":
        original["1m"] = (*original["1m"], original["1m"][-1])
    elif fault == "raw_h1_mismatch":
        original["60m"] = (
            *original["60m"][:-1],
            replace(original["60m"][-1], volume=Decimal(900)),
        )
    elif fault == "future_recovery":
        store.recovery_state = lambda *_: LiveRecoveryState(
            1, NEXT_START + timedelta(hours=1)
        )
    elif fault == "unknown_optional":
        original["1m"] = (
            replace(original["1m"][0], turnover=None),
            *original["1m"][1:],
        )
    elif fault == "source_evidence_missing":
        mds.contract_source_evidence = lambda **_: {"partitions": []}
    row = audit_product(native, coverage, "ag", AT)
    assert row["status"] == "BLOCKED"
    assert row["future_signal"]["status"] == "BLOCKED"
    assert row["future_signal"]["eligible_now"] is False


def test_current_native_reader_and_execution_still_reject_revised_old_input(closed):
    native, coverage, mds, _store, original = closed
    changed = list(original["1m"])
    changed[-1] = replace(changed[-1], close=Decimal("100.5"))
    original["1m"] = tuple(changed)
    original["60m"] = aggregate_from_1m(
        original["1m"], target_frequency="60m", sessions=mds.sessions[DAY]
    )
    row = audit_product(native, coverage, "ag", AT)
    assert row["status"] == "CLOSED_SOURCE_REVISION_WAIT_NEW_OBSERVATION"
    from app.market_data.domain import SeriesKind, SeriesPageQuery, BarFrequency

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_LIVE_UNAVAILABLE"):
        native.bars_until(
            SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT, "ag", BarFrequency.H1, before=AT, limit=32
            ),
            trading_day=DAY,
            end=mds.sessions[DAY][-1].end,
            limit=32,
        )


def test_next_day_native_input_uses_canonical_history_preserving_old_difference(
    closed, monkeypatch
):
    import app.market_data.htdy_input_admission as admission
    from app.htdy_execution import signal_from_window
    from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery

    native, coverage, mds, store, original = closed
    changed = list(original["1m"])
    changed[-1] = replace(changed[-1], close=Decimal("100.5"), volume=Decimal(2))
    original["1m"] = tuple(changed)
    original["60m"] = aggregate_from_1m(
        original["1m"], target_frequency="60m", sessions=mds.sessions[DAY]
    )
    before = dict(original)
    next_m1 = tuple(
        replace(
            original["1m"][0],
            trading_day=NEXT_DAY,
            bar_end=NEXT_START + timedelta(minutes=i),
        )
        for i in range(1, 61)
    )
    next_h1 = aggregate_from_1m(
        next_m1,
        target_frequency="60m",
        sessions=(SessionWindow(NEXT_START, NEXT_START + timedelta(hours=1)),),
    )

    def observations(day, _product, freq, *_args, **_kw):
        values = (
            original[freq]
            if day == DAY
            else (next_m1 if freq == "1m" else next_h1)
            if day == NEXT_DAY
            else ()
        )
        return tuple(LiveBarObservation(b, "AG2612") for b in values)

    store.bar_observations = observations
    native._phase_resolver.completed_observation_trading_day = lambda _p, t: (
        NEXT_DAY if t >= NEXT_START else DAY
    )

    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 26, 3, tzinfo=UTC)

    monkeypatch.setattr(admission, "datetime", FixtureClock)
    at = FixtureClock(2026, 10, 26, 2, tzinfo=UTC)
    row = admission.audit_product(native, coverage, "ag", at)
    assert row["status"] == "INPUTS_VERIFIED_WAIT_NEW_OBSERVATION"
    assert row["calculation_input"]["last"] == next_h1[0].bar_end
    assert row["future_signal"]["first_seen_proven"] is False
    query = SeriesPageQuery(
        SeriesKind.ACTUAL_DOMINANT,
        "ag",
        BarFrequency.H1,
        before=at + timedelta(microseconds=1),
        limit=32,
    )
    real_at = datetime.fromisoformat(at.isoformat())
    window = native.bars_until(query, trading_day=NEXT_DAY, end=real_at, limit=32)
    signal = signal_from_window(
        native,
        window,
        source_id="isolated-new-day-original",
        observed_at=real_at + timedelta(seconds=1),
    )
    assert signal.bar_end == at and signal.bar_end.date() != DAY
    assert original == before
    assert tuple(o.bar for o in store.bar_observations(DAY, "ag", "1m")) == before["1m"]
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_LIVE_UNAVAILABLE"):
        native.bars_until(
            query, trading_day=DAY, end=mds.sessions[DAY][-1].end, limit=32
        )


@pytest.mark.parametrize(
    "fault", ["unregistered", "provider", "expired", "unlisted", "wrong_identity"]
)
def test_next_contract_identity_must_be_proved(closed, fault):
    native, coverage, mds, _store, _original = closed
    old_owner = mds.dominant_segment_for_day
    mds.dominant_segment_for_day = lambda p, d: (
        SimpleNamespace(contract="AG2701") if d == NEXT_DAY else old_owner(p, d)
    )
    old_fact = mds.catalog.contract_fact

    def fact(p, c):
        if c != "AG2701":
            return old_fact(p, c)
        if fault == "unregistered":
            raise ValueError("CONTRACT_NOT_FOUND")
        return SimpleNamespace(
            provider="other" if fault == "provider" else "rqdata",
            symbol="cu" if fault == "wrong_identity" else p,
            contract=c,
            listed_date=date(2026, 10, 27) if fault == "unlisted" else date(2025, 1, 1),
            expired_date=NEXT_DAY if fault == "expired" else date(2027, 1, 1),
        )

    mds.catalog.contract_fact = fact
    row = audit_product(native, coverage, "ag", AT)
    assert row["status"] == row["future_signal"]["status"] == "BLOCKED"


def test_next_day_recovery_identity_is_read_and_fenced(closed):
    native, coverage, _mds, store, _original = closed
    seen = []

    def recovery(day, *_):
        seen.append(day)
        return (
            LiveRecoveryState(1, NEXT_START + timedelta(hours=1))
            if day == NEXT_DAY
            else None
        )

    store.recovery_state = recovery
    row = audit_product(native, coverage, "ag", AT)
    assert NEXT_DAY in seen
    assert row["status"] == row["future_signal"]["status"] == "BLOCKED"
    assert (
        row["source_conflict"]["errors"][0]["code"]
        == "HTDY_SOURCE_DIFFERENCE_NEXT_RECOVERY_FENCED"
    )
