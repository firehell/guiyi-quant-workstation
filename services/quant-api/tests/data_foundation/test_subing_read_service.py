from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    DominantContractSummary,
)
from app.market_data.market_read_service import MarketReadState
from app.market_data.subing_read_service import SubingReadRequest, SubingReadService


_SEGMENT_START = date(2026, 8, 3)
_NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def test_snapshot_reads_only_the_current_rank1_contract_segment() -> None:
    """Catches actual-dominant or older same-contract bars poisoning current warm-up."""
    current = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    old_same_contract = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=date(2026, 7, 1),
        first_end=datetime(2026, 7, 1, 1, 5, tzinfo=UTC),
        first_close=Decimal("10000"),
    )
    companion = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("200"),
    )

    clean = _service({BarFrequency.M5: current, BarFrequency.M15: companion}).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )
    poisoned = _service(
        {
            BarFrequency.M5: old_same_contract + current,
            BarFrequency.M15: companion,
        }
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert poisoned == clean
    assert poisoned.actual_contract == "JM2609"
    assert poisoned.segment_start_trading_day == _SEGMENT_START
    assert poisoned.primary.snapshot is not None
    assert poisoned.primary.snapshot.trading_day == _SEGMENT_START
    assert poisoned.calibration_state == "pending"


def test_companion_is_cut_off_at_the_primary_confirmed_bar() -> None:
    """Catches a later companion observation leaking future information into the snapshot."""
    primary = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    primary_cutoff = primary[-1].bar_end
    companion = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=primary_cutoff - timedelta(minutes=15 * 48),
        first_close=Decimal("200"),
    )

    result = _service(
        {BarFrequency.M5: primary, BarFrequency.M15: companion}
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == primary_cutoff
    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end == primary_cutoff
    assert result.companion.snapshot.bar_end <= result.primary.snapshot.bar_end


def test_live_contract_mismatch_keeps_the_snapshot_historical_only() -> None:
    """Catches bars from a different Live contract being merged into current rank1 history."""
    historical = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=80,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    mismatched_live = _bar(
        historical[-1].bar_end + timedelta(minutes=15),
        _SEGMENT_START,
        Decimal("9999"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: historical, BarFrequency.M5: companion},
        live={BarFrequency.M15: (mismatched_live,)},
        live_contract="JM2610",
    )

    result = SubingReadService(
        market_data=_FakeMarketData(), market_read=market_read
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == historical[-1].bar_end
    assert result.primary.snapshot.close == historical[-1].close
    assert result.primary.snapshot.bar_source == "canonical"
    assert result.source_mode == "canonical"
    assert result.live_observation == "unavailable"
    assert result.live_reason == "contract_mismatch"


def test_same_contract_live_bars_are_merged_after_the_historical_seam() -> None:
    """Catches available completed Live bars being ignored for an intraday current contract."""
    historical = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=160,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    live_primary = _bar(
        historical[-1].bar_end + timedelta(minutes=15),
        _SEGMENT_START,
        Decimal("999"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: historical, BarFrequency.M5: companion},
        live={BarFrequency.M15: (live_primary,)},
    )

    result = SubingReadService(
        market_data=_FakeMarketData(), market_read=market_read
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == live_primary.bar_end
    assert result.primary.snapshot.close == Decimal("999")
    assert result.primary.snapshot.bar_source == "live"
    assert result.source_mode == "canonical_live"
    assert result.live_observation == "available"
    assert result.live_reason is None
    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end <= live_primary.bar_end


def test_companion_keeps_live_source_when_cutoff_removes_only_later_live_bars() -> None:
    """Catches companion cutoff relabeling a retained Live observation as canonical."""
    primary = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    retained_live = _bar(primary[-1].bar_end, _SEGMENT_START, Decimal("500"))
    later_live = _bar(
        primary[-1].bar_end + timedelta(minutes=5),
        _SEGMENT_START,
        Decimal("600"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: primary, BarFrequency.M5: companion},
        live={BarFrequency.M5: (retained_live, later_live)},
    )

    result = SubingReadService(
        market_data=_FakeMarketData(), market_read=market_read
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end == retained_live.bar_end
    assert result.companion.snapshot.close == retained_live.close
    assert result.companion.snapshot.bar_source == "live"


def test_daily_snapshot_is_historical_only_and_has_no_companion() -> None:
    """Catches 1d SuBing reads consulting transient Live or inventing a companion series."""
    daily = _bars(
        frequency=BarFrequency.D1,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 6, 15, 7, 0, tzinfo=UTC),
        first_close=Decimal("100"),
        trading_day_step=True,
    )
    market_read = _HistoricalOnlyMarketRead({BarFrequency.D1: daily})

    result = SubingReadService(
        market_data=_FakeMarketData(segment_start=daily[0].trading_day),
        market_read=market_read,
    ).snapshot(SubingReadRequest("jm", BarFrequency.D1), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == daily[-1].bar_end
    assert result.primary.snapshot.bar_source == "canonical"
    assert result.companion is None
    assert result.source_mode == "canonical"
    assert result.live_observation == "not_applicable"
    assert result.live_reason == "daily_historical_only"


class _FakeMarketData:
    def __init__(self, *, segment_start: date = _SEGMENT_START) -> None:
        self.segment_start = segment_start

    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]:
        return (
            DominantContractSummary(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2609",
                dominant_mapping_date=date(2026, 8, 3),
            ),
        )

    def latest_dominant_segment(self, symbol: str) -> DominantContractSegmentSummary:
        assert symbol == "jm"
        return DominantContractSegmentSummary(
            symbol="jm",
            contract="JM2609",
            start_trading_day=self.segment_start,
            end_trading_day=date(2026, 8, 3),
        )


class _FakeMarketRead:
    def __init__(
        self,
        history: dict[BarFrequency, tuple[CanonicalBar, ...]],
        *,
        live: dict[BarFrequency, tuple[CanonicalBar, ...]] | None = None,
        live_contract: str = "JM2609",
        live_available: bool = True,
    ) -> None:
        self.history = history
        self.live = live or {}
        self.live_contract = live_contract
        self.live_available = live_available

    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        assert request.series_kind is SeriesKind.CONTRACT
        assert request.symbol == "jm"
        assert request.contract == "JM2609"
        assert request.limit == 300
        bars = self.history[request.frequency]
        return MarketSeriesPageResult(
            request_identity={},
            bars=bars,
            canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(),
        )

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        assert identity.series_kind is SeriesKind.CONTRACT
        assert identity.contract == "JM2609"
        assert now == _NOW
        return MarketReadState(
            symbol="jm",
            series_kind="contract",
            frequency=identity.frequency.value,
            operational=True,
            phase="trading",
            trading_day=_SEGMENT_START,
            live_eligible=True,
            live_available=self.live_available,
            live_contract=self.live_contract,
            canonical_end=self.history[identity.frequency][-1].bar_end,
            after_market={},
        )

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]:
        assert identity.series_kind is SeriesKind.CONTRACT
        assert identity.contract == "JM2609"
        assert now == _NOW
        return self.live.get(identity.frequency, ())


class _HistoricalOnlyMarketRead(_FakeMarketRead):
    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        raise AssertionError("1d SuBing must not query Live state")

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]:
        raise AssertionError("1d SuBing must not query Live snapshot")


def _service(
    history: dict[BarFrequency, tuple[CanonicalBar, ...]],
) -> SubingReadService:
    return SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(history, live_available=False),
    )


def _bars(
    *,
    frequency: BarFrequency,
    count: int,
    trading_day: date,
    first_end: datetime,
    first_close: Decimal,
    trading_day_step: bool = False,
) -> tuple[CanonicalBar, ...]:
    minutes = {
        BarFrequency.M5: 5,
        BarFrequency.M15: 15,
        BarFrequency.D1: 24 * 60,
    }[frequency]
    return tuple(
        _bar(
            first_end + timedelta(minutes=minutes * index),
            trading_day + timedelta(days=index) if trading_day_step else trading_day,
            first_close + Decimal(index),
        )
        for index in range(count)
    )


def _bar(bar_end: datetime, trading_day: date, close: Decimal) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("100"),
        turnover=Decimal("1000"),
        open_interest=Decimal("200"),
    )
