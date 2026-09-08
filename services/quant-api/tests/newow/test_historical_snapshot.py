from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.market_data.market_data_service import MarketDataError
from app.market_data.newow.historical_snapshot import (
    HistoricalSnapshotError,
    NewowHistoricalSnapshotResolver,
)
from app.market_data.newow.product_reader import NewowProductReadError
from app.market_data.newow.product_service import ProductSection


class Reader:
    def __init__(self, candidates):
        self.candidates = candidates
        self.limit = None

    def historical_snapshot_candidates(self, _product, *, as_of, limit, cancelled):
        self.limit = limit
        assert not cancelled()
        return self.candidates


def delivered(as_of, section):
    ready = SimpleNamespace(status=SimpleNamespace(value="ready"), reason_code=None)
    value = SimpleNamespace(delivery="delivered", value=object(), status=ready)
    return SimpleNamespace(
        meta=SimpleNamespace(as_of=as_of),
        section=ProductSection(section),
        chart=value if section == "chart" else None,
        auxiliary=value if section == "auxiliary" else None,
    )


def test_resolver_skips_only_known_unavailable_and_returns_same_cutoff_for_chart_and_mirror():
    newer = datetime(2026, 9, 8, 7, 0, 0, 1, tzinfo=UTC)
    older = datetime(2026, 9, 7, 7, 0, 0, 1, tzinfo=UTC)
    calls = []

    class Service:
        def query(self, query):
            calls.append(query)
            if query.as_of == newer:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            return delivered(query.as_of, query.section.value)

    reader = Reader(((date(2026, 9, 8), newer), (date(2026, 9, 7), older)))
    result = NewowHistoricalSnapshotResolver(
        reader,
        lambda _cancelled: Service(),
        now=lambda: datetime(2026, 9, 8, 8, tzinfo=UTC),
    ).resolve("rb", "trend", "1d")
    assert result.trading_day == date(2026, 9, 7)
    assert result.as_of.microsecond == 1
    assert reader.limit == 20
    assert [call.as_of for call in calls[-2:]] == [older, older]


def test_resolver_propagates_unknown_market_error_and_stops_on_deadline():
    cutoff = datetime(2026, 9, 7, 7, 0, 0, 1, tzinfo=UTC)

    class Broken:
        def query(self, _query):
            raise MarketDataError("PARTITION_INTEGRITY_INVALID")

    resolver = NewowHistoricalSnapshotResolver(
        Reader(((date(2026, 9, 7), cutoff),)),
        lambda _cancelled: Broken(),
        now=lambda: cutoff,
    )
    with pytest.raises(MarketDataError, match="PARTITION_INTEGRITY_INVALID"):
        resolver.resolve("rb", "trend", "1d")

    tick_values = iter((0.0, 31.0))
    last_tick = 0.0
    def clock():
        nonlocal last_tick
        last_tick = next(tick_values, last_tick)
        return last_tick
    timed = NewowHistoricalSnapshotResolver(
        Reader(()),
        lambda _cancelled: Broken(),
        now=lambda: cutoff,
        monotonic_clock=clock,
    )
    with pytest.raises(
        HistoricalSnapshotError, match="NEWOW_HISTORICAL_RESOLUTION_TIMEOUT"
    ):
        timed.resolve("rb", "trend", "1d")


@pytest.mark.parametrize(
    "error",
    [
        NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID"),
        NewowProductReadError("NEWOW_DATA_UNAVAILABLE"),
        MarketDataError("PARTITION_INTEGRITY_INVALID"),
    ],
)
def test_resolver_never_falls_back_from_integrity_or_ambiguous_errors(error):
    newer = datetime(2026, 9, 8, 7, 0, 0, 1, tzinfo=UTC)
    older = datetime(2026, 9, 7, 7, 0, 0, 1, tzinfo=UTC)
    calls = 0

    class Service:
        def query(self, query):
            nonlocal calls
            calls += 1
            if query.as_of == newer:
                raise error
            return delivered(query.as_of, query.section.value)

    resolver = NewowHistoricalSnapshotResolver(
        Reader(((date(2026, 9, 8), newer), (date(2026, 9, 7), older))),
        lambda _cancelled: Service(),
        now=lambda: newer,
    )
    with pytest.raises(type(error), match=str(error)):
        resolver.resolve("rb", "trend", "1d")
    assert calls == 1


@pytest.mark.parametrize("mode", ["cutoff", "lifecycle"])
def test_resolver_rejects_response_conflicts_without_older_fallback(mode):
    newer = datetime(2026, 9, 8, 7, 0, 0, 1, tzinfo=UTC)
    older = datetime(2026, 9, 7, 7, 0, 0, 1, tzinfo=UTC)
    calls = 0

    class Service:
        def query(self, query):
            nonlocal calls
            calls += 1
            result = delivered(query.as_of, query.section.value)
            if mode == "cutoff" and query.as_of == newer:
                result.meta.as_of = older
            if mode == "lifecycle" and query.as_of == newer:
                target = result.chart if query.section.value == "chart" else result.auxiliary
                target.status.status.value = "warming"
                target.status.reason_code = "NEWOW_CHART_WARMING"
            return result

    resolver = NewowHistoricalSnapshotResolver(
        Reader(((date(2026, 9, 8), newer), (date(2026, 9, 7), older))),
        lambda _cancelled: Service(),
        now=lambda: newer,
    )
    with pytest.raises(
        HistoricalSnapshotError, match="NEWOW_HISTORICAL_SNAPSHOT_INVALID"
    ):
        resolver.resolve("rb", "trend", "1d")
    assert calls == 1


def test_resolver_skips_mixed_ready_and_known_missing_but_rejects_malformed_mix():
    newer = datetime(2026, 9, 8, 7, 0, 0, 1, tzinfo=UTC)
    older = datetime(2026, 9, 7, 7, 0, 0, 1, tzinfo=UTC)

    class Service:
        def __init__(self, malformed):
            self.malformed = malformed
        def query(self, query):
            result = delivered(query.as_of, query.section.value)
            if query.as_of == newer and query.section.value == "auxiliary":
                result.auxiliary.value = None
                result.auxiliary.status.status.value = "unavailable"
                result.auxiliary.status.reason_code = "NEWOW_COMPLETE_TRADING_DAY_MISSING"
            if self.malformed and query.as_of == newer and query.section.value == "chart":
                result.chart.status = None
            return result

    candidates = Reader(((date(2026, 9, 8), newer), (date(2026, 9, 7), older)))
    result = NewowHistoricalSnapshotResolver(
        candidates, lambda _cancelled: Service(False), now=lambda: newer
    ).resolve("rb", "trend", "1d")
    assert result.trading_day == date(2026, 9, 7)

    with pytest.raises(
        HistoricalSnapshotError, match="NEWOW_HISTORICAL_SNAPSHOT_INVALID"
    ):
        NewowHistoricalSnapshotResolver(
            candidates, lambda _cancelled: Service(True), now=lambda: newer
        ).resolve("rb", "trend", "1d")
