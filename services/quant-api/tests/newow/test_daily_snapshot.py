from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.market_data.market_data_service import MarketDataError
from app.market_data.newow.daily_snapshot import (
    DailySnapshotError,
    NewowDailySnapshotResolver,
)


OLDER = datetime(2026, 9, 17, 7, 0, 0, 1, tzinfo=UTC)
NEWER = datetime(2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC)


class Reader:
    def historical_snapshot_candidates(self, _product, *, as_of, limit, cancelled):
        assert limit == 2 and as_of == NEWER and not cancelled()
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
    for code in ("PARTITION_INTEGRITY_INVALID", "MAPPED_CONTRACT_DATASET_MISSING"):
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


def test_daily_default_requires_verified_chart_and_never_searches_past_one_tail_day():
    class Service:
        def query(self, query):
            if query.as_of == NEWER:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    resolver = NewowDailySnapshotResolver(
        Reader(), lambda _cancelled: Service(), now=lambda: NEWER
    )
    with pytest.raises(DailySnapshotError, match="NEWOW_DAILY_SNAPSHOT_UNAVAILABLE"):
        resolver.resolve("rb", "trend", "1d")
