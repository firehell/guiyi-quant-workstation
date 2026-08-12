from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import CanonicalBar, MarketSeriesPageResult
from app.market_data.market_data_service import DominantContractSummary
from app.market_data.market_research_service import MarketResearchService, ResearchSeriesIdentity
from app.market_data.research_metrics import calculate_research_metrics


def test_volume_ratio_excludes_current_bar() -> None:
    daily = _daily_bars(volumes=[Decimal("100")] * 20 + [Decimal("200")])

    result = calculate_research_metrics(daily, _weekly_bars(30))

    assert result.volume_ratio20 == Decimal("2")


def test_missing_latest_oi_is_unavailable_not_zero() -> None:
    daily = _daily_bars(30, open_interests=[Decimal("100")] * 29 + [None])

    result = calculate_research_metrics(daily, _weekly_bars(30))

    assert result.oi_change_1d is None


def test_returns_position_and_turnover_use_frozen_lookbacks() -> None:
    daily = _daily_bars(
        closes=[Decimal(str(value)) for value in range(100, 125)],
        highs=[Decimal(str(value)) for value in range(101, 126)],
        lows=[Decimal(str(value)) for value in range(99, 124)],
        turnovers=[Decimal("10")] * 24 + [Decimal("20")],
    )

    result = calculate_research_metrics(daily, _weekly_bars(30))

    assert result.price_change_1d == Decimal("0.008130081300813008130081301")
    assert result.price_change_5d == Decimal("0.042016806722689075630252101")
    assert result.position20 == Decimal("20") / Decimal("21")
    assert result.distance_to_20d_high == Decimal("-1") / Decimal("125")
    assert result.distance_to_20d_low == Decimal("0.192307692307692307692307692")
    assert result.turnover_change_5d == Decimal("1")


def test_trend_distinguishes_up_down_neutral_and_unavailable() -> None:
    assert calculate_research_metrics(_daily_bars(30), _weekly_bars(30)).daily_trend == "up"
    assert calculate_research_metrics(_daily_bars(30, descending=True), _weekly_bars(30)).daily_trend == "down"
    assert calculate_research_metrics(_daily_bars(22, closes=[Decimal("100")] * 22), _weekly_bars(30)).daily_trend == "neutral"
    assert calculate_research_metrics(_daily_bars(20), _weekly_bars(20)).daily_trend == "unavailable"


def test_zero_range_and_insufficient_history_are_unavailable() -> None:
    daily = _daily_bars(
        20,
        closes=[Decimal("100")] * 20,
        highs=[Decimal("100")] * 20,
        lows=[Decimal("100")] * 20,
    )

    result = calculate_research_metrics(daily, _weekly_bars(20))

    assert result.position20 is None
    assert result.distance_to_20d_high == Decimal("0")
    assert result.distance_to_20d_low == Decimal("0")
    assert result.price_change_5d == Decimal("0")
    assert result.volume_ratio20 is None
    assert result.atr14_percentile252 is None


def test_atr_percentile_uses_previous_ready_values_only() -> None:
    daily = _daily_bars(40, ranges=[Decimal("1")] * 39 + [Decimal("10")])

    result = calculate_research_metrics(daily, _weekly_bars(30))

    assert result.atr14_percentile252 == Decimal("1")


def test_product_snapshot_preserves_identity_and_uses_market_data_service_only() -> None:
    service = _FakeMarketDataService()

    snapshot = MarketResearchService(service).product_snapshot(
        ResearchSeriesIdentity("jm", "contract", "JM2509")
    )

    assert [(item.frequency.value, item.limit, item.contract) for item in service.requests] == [
        ("1d", 300, "JM2509"),
        ("1w", 80, "JM2509"),
    ]
    assert snapshot.symbol == "jm"
    assert snapshot.series_kind.value == "contract"
    assert snapshot.contract == "JM2509"
    assert snapshot.current_dominant == "JM2510"
    assert snapshot.product_name == "焦煤"
    assert snapshot.sector == "black"
    assert snapshot.as_of == date(2025, 1, 30)
    assert len(snapshot.recent_daily) == 30


def _daily_bars(
    count: int = 30,
    *,
    closes: list[Decimal] | None = None,
    highs: list[Decimal] | None = None,
    lows: list[Decimal] | None = None,
    volumes: list[Decimal] | None = None,
    turnovers: list[Decimal | None] | None = None,
    open_interests: list[Decimal | None] | None = None,
    ranges: list[Decimal] | None = None,
    descending: bool = False,
) -> tuple[CanonicalBar, ...]:
    count = len(
        closes
        or highs
        or lows
        or volumes
        or turnovers
        or open_interests
        or ranges
        or [None] * count
    )
    start = date(2025, 1, 1)
    direction = -1 if descending else 1
    closes = closes or [Decimal("100") + Decimal(direction * index) for index in range(count)]
    ranges = ranges or [Decimal("2")] * count
    highs = highs or [close + bar_range / 2 for close, bar_range in zip(closes, ranges, strict=True)]
    lows = lows or [close - bar_range / 2 for close, bar_range in zip(closes, ranges, strict=True)]
    volumes = volumes or [Decimal("100")] * count
    turnovers = turnovers or [Decimal("1000")] * count
    open_interests = open_interests or [Decimal("100")] * count
    return tuple(
        CanonicalBar(
            datetime.combine(start + timedelta(days=index), datetime.min.time(), UTC),
            start + timedelta(days=index),
            close,
            high,
            low,
            close,
            volumes[index],
            turnovers[index],
            open_interests[index],
        )
        for index, (close, high, low) in enumerate(zip(closes, highs, lows, strict=True))
    )


def _weekly_bars(count: int) -> tuple[CanonicalBar, ...]:
    return _daily_bars(count)


class _FakeMarketDataService:
    def __init__(self) -> None:
        self.requests = []
        self.daily = _daily_bars(30)
        self.weekly = _weekly_bars(30)

    def query_page(self, request):
        self.requests.append(request)
        bars = self.daily if request.frequency.value == "1d" else self.weekly
        return MarketSeriesPageResult(
            request_identity={},
            bars=bars,
            canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(),
        )

    def list_latest_dominants(self):
        return (
            DominantContractSummary(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2510",
                dominant_mapping_date=date(2025, 1, 30),
            ),
        )
