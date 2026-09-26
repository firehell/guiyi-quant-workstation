from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.market_data.market_data_service import MarketDataError
from app.market_data.errors import InfrastructureError
from app.market_data.newow.daily_snapshot import (
    DailySnapshotError,
    NewowDailySnapshotResolver,
)


OLDER = datetime(2026, 9, 17, 7, 0, 0, 1, tzinfo=UTC)
NEWER = datetime(2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC)


class Reader:
    def historical_snapshot_candidates(self, _product, *, as_of, limit, cancelled):
        assert limit == 20 and as_of == NEWER and not cancelled()
        return ((date(2026, 9, 18), NEWER), (date(2026, 9, 17), OLDER))

    def dependency_owners(self, _product, since, through):
        assert since == through
        if since == date(2026, 9, 18):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        return (object(),)


def ready(query):
    return SimpleNamespace(
        section=query.section,
        meta=SimpleNamespace(as_of=query.as_of),
        chart=SimpleNamespace(
            delivery="delivered",
            value=object(),
            status=SimpleNamespace(status=SimpleNamespace(value="ready")),
        ),
    )


def test_daily_default_uses_verified_previous_close_when_latest_map_is_unpublished():
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            if query.as_of == NEWER:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            return ready(query)

    result = NewowDailySnapshotResolver(
        Reader(), lambda _cancelled: Service(), now=lambda: NEWER
    ).resolve("rb", "trend", "1d")
    assert calls == [NEWER, OLDER]
    assert result.expected_trading_day == date(2026, 9, 18)
    assert result.available_trading_day == date(2026, 9, 17)
    assert result.as_of == OLDER
    assert result.freshness == "pending_update"


def test_daily_default_does_not_hide_internal_missing_or_corrupt_inputs():
    for code in ("PARTITION_INTEGRITY_INVALID", "CONTRACT_IDENTITY_MISMATCH"):
        calls = []

        class Service:
            def query(self, query):
                calls.append(query.as_of)
                raise MarketDataError(code)

        resolver = NewowDailySnapshotResolver(
            Reader(), lambda _cancelled: Service(), now=lambda: NEWER
        )
        with pytest.raises(MarketDataError, match=code):
            resolver.resolve("rb", "trend", "1d")
        assert calls == [NEWER]


def test_daily_default_does_not_hide_internal_map_gap_when_latest_owner_exists():
    class MappedReader(Reader):
        def dependency_owners(self, _product, since, through):
            assert since == through == date(2026, 9, 18)
            return (object(),)

    class Service:
        def query(self, _query):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    resolver = NewowDailySnapshotResolver(
        MappedReader(), lambda _cancelled: Service(), now=lambda: NEWER
    )
    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        resolver.resolve("rb", "trend", "1d")


def test_daily_default_accepts_delivered_warming_chart():
    class Service:
        def query(self, query):
            result = ready(query)
            result.chart.status.status.value = "warming"
            return result

    result = NewowDailySnapshotResolver(
        Reader(), lambda _cancelled: Service(), now=lambda: NEWER
    ).resolve("rb", "trend", "1d")
    assert result.available_trading_day == date(2026, 9, 18)


def test_daily_default_requires_verified_chart_when_candidates_are_exhausted():
    class Service:
        def query(self, query):
            if query.as_of == NEWER:
                raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")

    resolver = NewowDailySnapshotResolver(
        Reader(), lambda _cancelled: Service(), now=lambda: NEWER
    )
    with pytest.raises(DailySnapshotError, match="NEWOW_DAILY_SNAPSHOT_UNAVAILABLE"):
        resolver.resolve("rb", "trend", "1d")


@pytest.mark.parametrize("error", [
    MarketDataError("MAPPED_CONTRACT_DATASET_MISSING"),
    InfrastructureError("REPLAY_ENDPOINTS_MISSING"),
])
def test_daily_default_uses_verified_history_after_multiple_unpublished_days(error):
    earlier = datetime(2026, 9, 16, 7, 0, 0, 1, tzinfo=UTC)

    class ExtendedReader(Reader):
        def historical_snapshot_candidates(self, _product, *, as_of, limit, cancelled):
            assert limit == 20 and not cancelled()
            return ((NEWER.date(), NEWER), (OLDER.date(), OLDER), (earlier.date(), earlier))

    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            if query.as_of != earlier:
                raise error
            return ready(query)

    snapshot = NewowDailySnapshotResolver(
        ExtendedReader(), lambda _cancelled: Service(), now=lambda: NEWER
    ).resolve("rb", "trend", "1d")
    assert calls == [NEWER, OLDER, earlier]
    assert snapshot.available_trading_day == earlier.date()
    assert snapshot.expected_trading_day == NEWER.date()
    assert snapshot.as_of == earlier and snapshot.freshness == "pending_update"


def test_daily_default_never_hides_corruption_after_missing_latest_day():
    class Service:
        def query(self, query):
            if query.as_of == NEWER:
                raise InfrastructureError("REPLAY_ENDPOINTS_MISSING")
            raise MarketDataError("PARTITION_INTEGRITY_INVALID")

    with pytest.raises(MarketDataError, match="PARTITION_INTEGRITY_INVALID"):
        NewowDailySnapshotResolver(
            Reader(), lambda _cancelled: Service(), now=lambda: NEWER
        ).resolve("rb", "trend", "1d")


def test_daily_default_rejects_response_completed_after_deadline():
    from app.market_data.newow.product_reader import NewowProductReadCancelled

    clock = [0.0]

    class Service:
        def query(self, query):
            clock[0] = 31.0
            return ready(query)

    with pytest.raises(NewowProductReadCancelled):
        NewowDailySnapshotResolver(
            Reader(), lambda _cancelled: Service(), now=lambda: NEWER,
            monotonic_clock=lambda: clock[0],
        ).resolve("rb", "trend", "1d")
