from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar, MarketSeriesPageResult
from app.market_data.market_data_service import DominantContractSummary, MarketDataError
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


def test_snapshot_uses_taxonomy_as_the_name_and_sector_authority() -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET), "rb": _bars(30, end=TARGET)},
        weekly={"jm": _bars(22, end=TARGET), "rb": _bars(22, end=TARGET)},
        dominants=(
            DominantContractSummary(
                symbol="jm",
                product_name="错误名称",
                sector="other",
                exchange="DCE",
                actual_contract="JM2505",
                dominant_mapping_date=TARGET,
            ),
            DominantContractSummary(
                symbol="rb",
                product_name="错误名称",
                sector="other",
                exchange="SHFE",
                actual_contract="RB2505",
                dominant_mapping_date=TARGET,
            ),
        ),
    )

    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=("jm", "rb"),
        taxonomy=_taxonomy(),
        latest_complete_day=_TargetDay(TARGET),
    ).snapshot()

    assert [(item.symbol, item.product_name, item.sector) for item in snapshot.items] == [
        ("jm", "焦煤", "black"),
        ("rb", "螺纹钢", "steel"),
    ]


def test_snapshot_marks_old_daily_data_stale_without_fabricating_item() -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET), "rb": _bars(30, end=TARGET - timedelta(days=1))},
        weekly={"jm": _bars(22, end=TARGET), "rb": _bars(22, end=TARGET)},
    )

    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=("jm", "rb"),
        taxonomy=_taxonomy(),
        latest_complete_day=_TargetDay(TARGET),
    ).snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.freshness == "stale"
    assert snapshot.stale_count == 1
    assert snapshot.unavailable_count == 0
    assert [item.symbol for item in snapshot.items] == ["jm"]


def test_snapshot_treats_empty_daily_query_as_unavailable_and_still_reads_weekly() -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET), "rb": _bars(30, end=TARGET)},
        weekly={"jm": _bars(22, end=TARGET), "rb": _bars(22, end=TARGET)},
        failures={("rb", "1d"): MarketDataError("QUERY_WINDOW_EMPTY")},
    )

    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=("jm", "rb"),
        taxonomy=_taxonomy(),
        latest_complete_day=_TargetDay(TARGET),
    ).snapshot()

    assert snapshot.unavailable_count == 1
    assert [item.symbol for item in snapshot.items] == ["jm"]
    assert [(request.symbol, request.frequency.value) for request in market_data.requests] == [
        ("jm", "1d"),
        ("jm", "1w"),
        ("rb", "1d"),
        ("rb", "1w"),
    ]


@pytest.mark.parametrize("size", [59, 60, 61])
def test_snapshot_supports_universe_sizes_without_a_magic_60(size: int) -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    products = tuple(f"p{index}" for index in range(size))
    taxonomy = {
        symbol: ProductTaxonomyEntry(name=f"名称{index}", sector="other")
        for index, symbol in enumerate(products)
    }
    market_data = _FakeMarketDataService(
        daily={symbol: _bars(30, end=TARGET) for symbol in products},
        weekly={symbol: _bars(22, end=TARGET) for symbol in products},
        dominants=tuple(
            DominantContractSummary(
                symbol=symbol,
                product_name=f"名称{index}",
                sector="other",
                exchange="EX",
                actual_contract=f"P{index}2505",
                dominant_mapping_date=TARGET,
            )
            for index, symbol in enumerate(products)
        ),
    )

    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=products,
        taxonomy=taxonomy,
        latest_complete_day=_TargetDay(TARGET),
    ).snapshot()

    assert snapshot.active_count == size
    assert snapshot.participant_count == size
    assert len(snapshot.items) == size


def test_constructor_rejects_duplicate_products_without_reading_market_data() -> None:
    from app.market_data.market_home_overview import (
        MarketHomeOverviewError,
        MarketHomeOverviewService,
    )

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET)},
        weekly={"jm": _bars(22, end=TARGET)},
    )

    with pytest.raises(MarketHomeOverviewError, match="MARKET_HOME_UNIVERSE_INVALID"):
        MarketHomeOverviewService(
            market_data=market_data,
            products=("jm", "jm"),
            taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="black")},
            latest_complete_day=_TargetDay(TARGET),
        )

    assert market_data.requests == []
    assert market_data.dominant_reads == 0


def test_constructor_rejects_taxonomy_mismatch_without_reading_market_data() -> None:
    from app.market_data.market_home_overview import (
        MarketHomeOverviewError,
        MarketHomeOverviewService,
    )

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET)},
        weekly={"jm": _bars(22, end=TARGET)},
    )

    with pytest.raises(MarketHomeOverviewError, match="MARKET_HOME_TAXONOMY_INVALID"):
        MarketHomeOverviewService(
            market_data=market_data,
            products=("jm",),
            taxonomy={"rb": ProductTaxonomyEntry(name="螺纹钢", sector="steel")},
            latest_complete_day=_TargetDay(TARGET),
        )

    assert market_data.requests == []
    assert market_data.dominant_reads == 0


@pytest.mark.parametrize(
    "dominants",
    [
        (),
        (
            DominantContractSummary(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2505",
                dominant_mapping_date=TARGET,
            ),
            DominantContractSummary(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2505",
                dominant_mapping_date=TARGET,
            ),
        ),
    ],
)
def test_snapshot_fails_closed_for_missing_or_duplicate_dominants(
    dominants: tuple[DominantContractSummary, ...],
) -> None:
    from app.market_data.market_home_overview import (
        MarketHomeOverviewError,
        MarketHomeOverviewService,
    )

    market_data = _FakeMarketDataService(
        daily={"jm": _bars(30, end=TARGET)},
        weekly={"jm": _bars(22, end=TARGET)},
        dominants=dominants,
    )

    with pytest.raises(MarketHomeOverviewError, match="MARKET_HOME_DOMINANT_CONTEXT_INVALID"):
        MarketHomeOverviewService(
            market_data=market_data,
            products=("jm",),
            taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="black")},
            latest_complete_day=_TargetDay(TARGET),
        ).snapshot()


def test_snapshot_reconciles_summary_and_sector_medians() -> None:
    from app.market_data.market_home_overview import MarketHomeOverviewService

    products = ("jm", "rb", "cu")
    taxonomy = {
        "jm": ProductTaxonomyEntry(name="焦煤", sector="black"),
        "rb": ProductTaxonomyEntry(name="螺纹钢", sector="black"),
        "cu": ProductTaxonomyEntry(name="沪铜", sector="nonferrous"),
    }
    market_data = _FakeMarketDataService(
        daily={
            "jm": _bars(30, end=TARGET, closes=[Decimal("100")] * 29 + [Decimal("110")]),
            "rb": _bars(30, end=TARGET, closes=[Decimal("100")] * 29 + [Decimal("90")]),
            "cu": _bars(30, end=TARGET, closes=[Decimal("100")] * 30),
        },
        weekly={symbol: _bars(22, end=TARGET) for symbol in products},
        dominants=tuple(
            DominantContractSummary(
                symbol=symbol,
                product_name=taxonomy[symbol].name,
                sector=taxonomy[symbol].sector,
                exchange="EX",
                actual_contract=f"{symbol.upper()}2505",
                dominant_mapping_date=TARGET,
            )
            for symbol in products
        ),
    )

    snapshot = MarketHomeOverviewService(
        market_data=market_data,
        products=products,
        taxonomy=taxonomy,
        latest_complete_day=_TargetDay(TARGET),
    ).snapshot()

    assert snapshot.summary.price_up_count == 1
    assert snapshot.summary.price_down_count == 1
    assert snapshot.summary.price_flat_count == 1
    assert [(item.sector, item.active_count, item.participant_count, item.median_price_change_1d) for item in snapshot.sectors] == [
        ("black", 2, 2, Decimal("0")),
        ("nonferrous", 1, 1, Decimal("0")),
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
        dominants: tuple[DominantContractSummary, ...] | None = None,
        failures: dict[tuple[str, str], Exception] | None = None,
    ) -> None:
        self.daily = daily
        self.weekly = weekly
        self.requests = []
        self.dominant_reads = 0
        self.failures = failures or {}
        self.dominants = dominants or (
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

    def query_page(self, request):
        self.requests.append(request)
        failure = self.failures.get((request.symbol, request.frequency.value))
        if failure is not None:
            raise failure
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
        return self.dominants


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
    closes: list[Decimal] | None = None,
) -> tuple[CanonicalBar, ...]:
    start = end - timedelta(days=count - 1)
    values: list[CanonicalBar] = []
    for index in range(count):
        close = closes[index] if closes is not None else Decimal("100") + Decimal(index)
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
