from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import CanonicalBar, MarketSeriesPageResult
from app.market_data.market_data_service import DominantContractSummary
from app.market_data.product_taxonomy import ProductTaxonomyEntry


TARGET = date(2025, 2, 11)


def test_snapshot_uses_one_completed_day_and_preserves_metric_nulls() -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    market_data = _FakeMarketDataService(
        daily={
            "jm": _bars(30, end=TARGET, latest_open_interest=None),
            "rb": _bars(30, end=TARGET),
        },
        weekly={
            "jm": _bars(22, end=TARGET),
            "rb": _bars(20, end=TARGET),
        },
    )
    target_day = _TargetDay(TARGET)
    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=("jm", "rb"),
        taxonomy=_taxonomy(),
        latest_complete_day=target_day,
    ).snapshot()

    assert target_day.calls == [("jm", "rb")]
    assert snapshot.target_as_of == TARGET
    assert snapshot.data_as_of == TARGET
    assert snapshot.participant_count == 2
    assert snapshot.unavailable_count == 0
    assert [item.symbol for item in snapshot.items] == ["jm", "rb"]
    assert {item.data_as_of for item in snapshot.items} == {TARGET}
    assert snapshot.items[0].oi_change_1d is None
    assert snapshot.items[1].weekly_trend == "unavailable"
    assert market_data.dominant_reads == 1
    assert [(request.symbol, request.frequency.value) for request in market_data.requests] == [
        ("jm", "1d"),
        ("jm", "1w"),
        ("rb", "1d"),
        ("rb", "1w"),
    ]


def test_snapshot_excludes_product_without_completed_daily_bar_and_counts_unavailable() -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET), "rb": ()},
        weekly={"jm": _bars(22, end=TARGET), "rb": _bars(22, end=TARGET)},
    )

    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=("jm", "rb"),
        taxonomy=_taxonomy(),
        latest_complete_day=_TargetDay(TARGET),
    ).snapshot()

    assert snapshot.active_count == 2
    assert snapshot.participant_count == 1
    assert snapshot.unavailable_count == 1
    assert [item.symbol for item in snapshot.items] == ["jm"]
    assert [(request.symbol, request.frequency.value) for request in market_data.requests] == [
        ("jm", "1d"),
        ("jm", "1w"),
        ("rb", "1d"),
        ("rb", "1w"),
    ]


class _TargetDay:
    def __init__(self, value: date) -> None:
        self.value = value
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, products: tuple[str, ...]) -> date:
        self.calls.append(products)
        return self.value


class _FakeMarketDataService:
    def __init__(
        self,
        *,
        daily: dict[str, tuple[CanonicalBar, ...]],
        weekly: dict[str, tuple[CanonicalBar, ...]],
    ) -> None:
        self.daily = daily
        self.weekly = weekly
        self.requests = []
        self.dominant_reads = 0

    def query_page(self, request):
        self.requests.append(request)
        bars = self.daily[request.symbol] if request.frequency.value == "1d" else self.weekly[request.symbol]
        return MarketSeriesPageResult(
            request_identity={},
            bars=bars,
            canonical_coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(),
        )

    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]:
        self.dominant_reads += 1
        return (
            DominantContractSummary(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2505",
                dominant_mapping_date=TARGET,
            ),
            DominantContractSummary(
                symbol="rb",
                product_name="螺纹钢",
                sector="steel",
                exchange="SHFE",
                actual_contract="RB2505",
                dominant_mapping_date=TARGET,
            ),
        )


def _taxonomy() -> dict[str, ProductTaxonomyEntry]:
    return {
        "jm": ProductTaxonomyEntry(name="焦煤", sector="black"),
        "rb": ProductTaxonomyEntry(name="螺纹钢", sector="steel"),
    }


def _bars(
    count: int,
    *,
    end: date,
    latest_open_interest: Decimal | None = Decimal("130"),
) -> tuple[CanonicalBar, ...]:
    start = end - timedelta(days=count - 1)
    values: list[CanonicalBar] = []
    for index in range(count):
        close = Decimal("100") + Decimal(index)
        open_interest = (
            latest_open_interest
            if index == count - 1
            else Decimal("100") + Decimal(index)
        )
        trading_day = start + timedelta(days=index)
        values.append(
            CanonicalBar(
                bar_end=datetime.combine(trading_day, datetime.min.time(), UTC),
                trading_day=trading_day,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100") + Decimal(index),
                turnover=Decimal("1000"),
                open_interest=open_interest,
            )
        )
    return tuple(values)
