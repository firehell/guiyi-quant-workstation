"""Default W1 snapshots keep a calendar cutoff separate from current owner facts."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.market_data.market_data_service import MarketDataError
from app.market_data.newow.weekly_snapshot import (
    NewowWeeklySnapshotResolver,
    WeeklySnapshotError,
    publication_state_from_status,
)


REQUESTED = datetime(2026, 9, 18, 8, tzinfo=UTC)
NEW = datetime(2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC)
OLD = datetime(2026, 9, 11, 7, 0, 0, 1, tzinfo=UTC)


class Reader:
    def weekly_snapshot_candidates(self, product, *, as_of, limit, cancelled):
        assert (product, as_of, limit) == ("rb", REQUESTED, 2)
        assert not cancelled()
        return ((date(2026, 9, 18), NEW), (date(2026, 9, 11), OLD))

    def current_owner_context(self, product, at):
        assert (product, at) == ("rb", REQUESTED)
        return {"status": "unknown", "physical_contract": None}

    def weekly_tail_unpublished(self, product, day):
        assert (product, day) == ("rb", date(2026, 9, 18))
        return True


def delivered(query, *, status="ready", value=object()):
    return SimpleNamespace(
        section=query.section,
        meta=SimpleNamespace(as_of=query.as_of),
        chart=SimpleNamespace(
            delivery="delivered", value=value,
            status=SimpleNamespace(status=SimpleNamespace(value=status)),
        ),
    )


def resolver(service, publication="unknown"):
    return NewowWeeklySnapshotResolver(
        Reader(), lambda _cancelled: service, now=lambda: REQUESTED,
        publication_state=lambda product, day, at: publication,
    )


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
def test_all_strategies_use_the_same_verified_complete_week(strategy):
    class Service:
        def query(self, query):
            assert query.as_of == NEW
            return delivered(query, status="warming")

    snapshot = resolver(Service()).resolve("rb", strategy, "1w")
    assert snapshot.expected_period_end == NEW
    assert snapshot.available_period_end == NEW
    assert snapshot.as_of == NEW
    assert snapshot.freshness == "current"
    assert snapshot.current_context == {"status": "unknown", "physical_contract": None}


def test_complete_calendar_week_without_a_verified_chart_is_not_current():
    class Service:
        def query(self, query):
            return delivered(query, status="warming", value=None)

    with pytest.raises(WeeklySnapshotError, match="NEWOW_WEEKLY_UNKNOWN"):
        resolver(Service()).resolve("rb", "trend", "1w")


def test_only_proved_tail_publication_wait_may_use_immediately_previous_week():
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            if query.as_of == NEW:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            return delivered(query)

    snapshot = resolver(Service(), publication="pending_update").resolve(
        "rb", "trend", "1w",
    )
    assert calls == [NEW, OLD]
    assert snapshot.expected_period_end == NEW
    assert snapshot.available_period_end == OLD
    assert snapshot.as_of == OLD
    assert snapshot.freshness == "pending_update"


@pytest.mark.parametrize("publication", ["unknown", "failed", "stale"])
def test_unproved_or_failed_publication_never_turns_an_old_week_green(publication):
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    with pytest.raises(WeeklySnapshotError, match=f"NEWOW_WEEKLY_{publication.upper()}"):
        resolver(Service(), publication=publication).resolve("rb", "trend", "1w")
    assert calls == [NEW]


def test_internal_source_conflict_does_not_search_older_weeks():
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            raise MarketDataError("WEEKLY_SOURCE_BAR_CONFLICT")

    with pytest.raises(MarketDataError, match="WEEKLY_SOURCE_BAR_CONFLICT"):
        resolver(Service(), publication="pending_update").resolve("rb", "trend", "1w")
    assert calls == [NEW]


@pytest.mark.parametrize("code", [
    "WEEKLY_SOURCE_BAR_CONFLICT",
    "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
])
def test_weekly_source_failure_never_uses_previous_week(code):
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            raise MarketDataError(code)

    with pytest.raises(MarketDataError, match=code):
        resolver(Service(), publication="pending_update").resolve("rb", "trend", "1w")
    assert calls == [NEW]


def test_proven_price_interruption_stays_on_current_week_without_fallback():
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            return delivered(query, value={"price_unavailable_days": [date(2026, 9, 17)]})

    snapshot = resolver(Service(), publication="pending_update").resolve(
        "rb", "trend", "1w",
    )
    assert calls == [NEW]
    assert snapshot.as_of == NEW
    assert snapshot.freshness == "current"


def test_current_owner_rollover_does_not_rewrite_historical_week_cutoff():
    class RolledReader(Reader):
        def current_owner_context(self, product, at):
            return {"status": "known", "physical_contract": "RB2701"}

    class Service:
        def query(self, query):
            assert query.as_of == NEW
            return delivered(query)

    snapshot = NewowWeeklySnapshotResolver(
        RolledReader(), lambda _cancelled: Service(), now=lambda: REQUESTED,
        publication_state=lambda _product, _day, _at: "unknown",
    ).resolve("rb", "trend", "1w")
    assert snapshot.as_of == NEW
    assert snapshot.current_context == {"status": "known", "physical_contract": "RB2701"}


def test_publication_state_uses_exact_maintenance_day_and_terminal_result():
    running = {"current_run": {
        "scheduled_date": "2026-09-18", "products": ["rb"],
    }, "last_run": None}
    assert publication_state_from_status(running, "rb", date(2026, 9, 18), REQUESTED) == "pending_update"
    failed = {"current_run": None, "last_run": {
        "trading_day": "2026-09-18", "status": "failed", "products": ["rb"],
    }}
    assert publication_state_from_status(failed, "rb", date(2026, 9, 18), REQUESTED) == "failed"
    passed_but_missing = {"current_run": None, "last_run": {
        "trading_day": "2026-09-18", "status": "passed", "products": ["rb"],
    }}
    assert publication_state_from_status(passed_but_missing, "rb", date(2026, 9, 18), REQUESTED) == "stale"


def test_publication_state_uses_existing_schedule_only_before_1805():
    old = {"current_run": None, "last_run": {
        "trading_day": "2026-09-11", "status": "passed", "products": ["rb"],
    }}
    assert publication_state_from_status(old, "rb", date(2026, 9, 18), REQUESTED) == "pending_update"
    assert publication_state_from_status(
        old, "rb", date(2026, 9, 18), datetime(2026, 9, 18, 11, tzinfo=UTC),
    ) == "unknown"
    other = {"current_run": {"scheduled_date": "2026-09-18", "products": ["au"]}}
    assert publication_state_from_status(other, "rb", date(2026, 9, 18), REQUESTED) == "unknown"
    assert publication_state_from_status({}, "rb", date(2026, 9, 18), REQUESTED) == "unknown"
    other_last = {"current_run": None, "last_run": {
        "trading_day": "2026-09-11", "status": "passed", "products": ["au"],
    }}
    assert publication_state_from_status(other_last, "rb", date(2026, 9, 18), REQUESTED) == "unknown"


def test_weekend_cannot_keep_a_previous_friday_run_pending():
    weekend = REQUESTED + timedelta(days=1)
    running = {"current_run": {
        "scheduled_date": "2026-09-18", "products": ["rb"],
    }, "last_run": None}
    assert publication_state_from_status(running, "rb", date(2026, 9, 18), weekend) == "stale"
    assert publication_state_from_status(
        {"last_run": {"trading_day": "2026-09-18", "status": "failed", "products": ["rb"]}},
        "rb", date(2026, 9, 18), weekend,
    ) == "failed"
