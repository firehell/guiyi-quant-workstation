from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar, MarketSeriesPageResult
from app.market_data.market_data_service import MarketDataError
from app.market_data.market_radar import MarketRadarService
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.research_metrics import calculate_research_metrics


def test_radar_marks_only_expected_day_participants_ready_or_stale() -> None:
    service = _service({"ag": _bars(), "jm": _bars()})

    snapshot = service.snapshot()

    assert snapshot.status == "ready"
    assert snapshot.active_count == 2
    assert snapshot.participant_count == 2
    assert snapshot.stale == ()

    stale = _service({"ag": _bars(), "jm": _bars(last_day=date(2025, 1, 29))}).snapshot()
    assert stale.status == "degraded"
    assert stale.participant_count == 1
    assert stale.stale == ("jm",)


def test_radar_uses_previous_complete_snapshot_during_same_day_partial_publication() -> None:
    target = date(2025, 1, 30)
    previous = date(2025, 1, 29)
    market_data = _FakeMarketData(
        outcomes={
            "ag": _bars(
                count=301,
                last_day=target,
                last_close=Decimal("999"),
                last_turnover=Decimal("9999"),
            ),
            "jm": _bars(last_day=previous),
        }
    )
    service = MarketRadarService(
        market_data,
        products=("ag", "jm"),
        taxonomy={
            "ag": ProductTaxonomyEntry(name="白银", sector="precious"),
            "jm": ProductTaxonomyEntry(name="焦煤", sector="black"),
        },
        latest_complete_day=lambda _products: target,
        today=lambda: target,
    )

    snapshot = service.snapshot()

    assert snapshot.status == "ready"
    assert snapshot.expected_as_of == target
    assert snapshot.target_as_of == target
    assert snapshot.data_as_of == previous
    assert snapshot.freshness_state == "pending_after_market"
    assert snapshot.freshness_message == "盘后更新待完成"
    assert snapshot.participant_count == 2
    assert snapshot.stale == ()
    assert snapshot.unavailable == ()
    ag = next(item for item in snapshot.items if item.symbol == "ag")
    assert ag.turnover == Decimal("1000")
    assert ag.metrics == calculate_research_metrics(_bars(last_day=previous), ())
    assert {request.limit for request in market_data.requests} == {301}


def test_radar_becomes_current_after_all_target_bars_are_published() -> None:
    target = date(2025, 1, 30)
    snapshot = _service(
        {"ag": _bars(last_day=target), "jm": _bars(last_day=target)},
        target=target,
        today=target,
    ).snapshot()

    assert snapshot.status == "ready"
    assert snapshot.target_as_of == target
    assert snapshot.data_as_of == target
    assert snapshot.freshness_state == "current"
    assert snapshot.freshness_message == "当前完整"
    assert snapshot.participant_count == 2


def test_radar_cross_day_marks_only_the_truly_missing_symbol_stale() -> None:
    target = date(2025, 1, 30)
    snapshot = _service(
        {
            "ag": _bars(last_day=target),
            "jm": _bars(last_day=date(2025, 1, 29)),
        },
        target=target,
        today=date(2025, 1, 31),
    ).snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.target_as_of == target
    assert snapshot.data_as_of == target
    assert snapshot.freshness_state == "degraded"
    assert snapshot.freshness_message == "数据异常"
    assert snapshot.participant_count == 1
    assert snapshot.stale == ("jm",)


def test_radar_weekend_with_complete_target_snapshot_stays_current() -> None:
    target = date(2025, 1, 30)
    snapshot = _service(
        {"ag": _bars(last_day=target), "jm": _bars(last_day=target)},
        target=target,
        today=date(2025, 2, 1),
    ).snapshot()

    assert snapshot.status == "ready"
    assert snapshot.data_as_of == target
    assert snapshot.freshness_state == "current"


def test_radar_requires_all_active_60_for_ready() -> None:
    products = tuple(f"p{index:02d}" for index in range(60))
    service = MarketRadarService(
        _FakeMarketData({symbol: _bars(last_day=date(2026, 8, 11)) for symbol in products}),
        products=products,
        taxonomy={
            symbol: ProductTaxonomyEntry(name=symbol.upper(), sector="other")
            for symbol in products
        },
        latest_complete_day=lambda _products: date(2026, 8, 11),
        today=lambda: date(2026, 8, 11),
    )

    snapshot = service.snapshot()

    assert snapshot.status == "ready"
    assert snapshot.expected_as_of == date(2026, 8, 11)
    assert snapshot.target_as_of == date(2026, 8, 11)
    assert snapshot.data_as_of == date(2026, 8, 11)
    assert snapshot.freshness_state == "current"
    assert snapshot.active_count == 60
    assert snapshot.participant_count == 60


def test_radar_isolates_known_market_data_errors_but_propagates_unexpected_errors() -> None:
    service = _service({"ag": _bars(), "jm": MarketDataError("QUERY_WINDOW_EMPTY")})

    snapshot = service.snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.unavailable == ("jm",)
    assert snapshot.participant_count == 1
    assert snapshot.freshness_state == "degraded"
    assert snapshot.freshness_message == "数据异常"

    with pytest.raises(RuntimeError, match="boom"):
        _service({"ag": RuntimeError("boom"), "jm": _bars()}).snapshot()


def test_sector_totals_come_from_taxonomy_even_when_one_symbol_is_unavailable() -> None:
    snapshot = _service({"ag": _bars(), "jm": MarketDataError("QUERY_WINDOW_EMPTY")}).snapshot()

    sectors = {item.sector: item for item in snapshot.sector_summary}
    assert sectors["precious"].total_count == 1
    assert sectors["precious"].participant_count == 1
    assert sectors["black"].total_count == 1
    assert sectors["black"].participant_count == 0


def _service(
    outcomes,
    *,
    target: date = date(2025, 1, 30),
    today: date = date(2025, 1, 31),
):
    return MarketRadarService(
        _FakeMarketData(outcomes),
        products=("ag", "jm"),
        taxonomy={
            "ag": ProductTaxonomyEntry(name="白银", sector="precious"),
            "jm": ProductTaxonomyEntry(name="焦煤", sector="black"),
        },
        latest_complete_day=lambda _products: target,
        today=lambda: today,
    )


def _bars(
    *,
    count: int = 300,
    last_day: date = date(2025, 1, 30),
    last_close: Decimal | None = None,
    last_volume: Decimal | None = None,
    last_oi: Decimal | None = None,
    last_turnover: Decimal | None = None,
):
    start = last_day - timedelta(days=count - 1)
    values = []
    for index in range(count):
        close = Decimal("100") + Decimal(index) / Decimal("10")
        values.append(CanonicalBar(datetime.combine(start + timedelta(days=index), datetime.min.time(), UTC), start + timedelta(days=index), close, close + 1, close - 1, close, Decimal("100"), Decimal("1000"), Decimal("100")))
    last = values[-1]
    close = last_close or last.close
    values[-1] = CanonicalBar(
        last.bar_end,
        last.trading_day,
        close,
        close + 1,
        close - 1,
        close,
        last_volume or last.volume,
        last_turnover or last.turnover,
        last_oi or last.open_interest,
    )
    return tuple(values)


class _FakeMarketData:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.requests = []

    def query_page(self, request):
        self.requests.append(request)
        outcome = self.outcomes[request.symbol]
        if isinstance(outcome, Exception):
            raise outcome
        return MarketSeriesPageResult({}, outcome[-request.limit :], None, False, None, ())
