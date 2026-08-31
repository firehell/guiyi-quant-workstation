from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesPageQuery,
)
from app.market_data.market_read_service import MarketReadService, MarketReadWindowError


DAY_1 = date(2026, 8, 30)
DAY_2 = date(2026, 8, 31)
HISTORICAL_END_1 = datetime(2026, 8, 30, 1, 45, tzinfo=UTC)
HISTORICAL_END_2 = datetime(2026, 8, 31, 1, 45, tzinfo=UTC)
LIVE_END = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)


def _bar(bar_end: datetime, trading_day: date) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


def _bar_with_close(bar_end: datetime, trading_day: date, close: str) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


class _MarketPageReader:
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        segments: tuple[ResolvedContractSegment, ...],
    ) -> None:
        self._bars = bars
        self._segments = segments

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        bars = tuple(
            bar for bar in self._bars if request.before is None or bar.bar_end < request.before
        )[-request.limit :]
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=bars,
            canonical_coverage=None,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=self._segments,
        )


class _LiveStore:
    def __init__(self, bars: tuple[CanonicalBar, ...], contract: str) -> None:
        self._bars = bars
        self._contract = contract

    def subscriptions(self, trading_day: date) -> dict[str, str]:
        assert trading_day == DAY_2
        return {"jm": self._contract}

    def heartbeat(self) -> dict[str, bool]:
        return {"available": True}

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        assert (trading_day, symbol, frequency) == (DAY_2, "jm", "15m")
        return tuple(bar for bar in self._bars if after is None or bar.bar_end > after)


class _ForbiddenPhaseReader:
    def resolve(self, symbol: str, now: datetime) -> object:
        raise AssertionError("bars_until must not inspect the current phase")


def _service(
    *,
    historical: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
    live: tuple[CanonicalBar, ...],
    live_contract: str = "JM2705",
) -> MarketReadService:
    return MarketReadService(
        market_data=_MarketPageReader(historical, segments),
        phase_resolver=_ForbiddenPhaseReader(),
        operational_products=("jm",),
        live_store=_LiveStore(live, live_contract),
    )


def test_bars_until_aligns_historical_and_live_rank1_contract_owners() -> None:
    historical = (
        _bar(HISTORICAL_END_1, DAY_1),
        _bar(HISTORICAL_END_2, DAY_2),
    )
    live = (_bar(LIVE_END, DAY_2),)
    service = _service(
        historical=historical,
        segments=(
            ResolvedContractSegment("JM2701", DAY_1, DAY_1),
            ResolvedContractSegment("JM2705", DAY_2, DAY_2),
        ),
        live=live,
    )

    window = service.bars_until(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        trading_day=DAY_2,
        end=LIVE_END,
        limit=64,
    )

    assert len(window.bar_contracts) == len(window.bars)
    assert tuple(zip((bar.trading_day for bar in window.bars), window.bar_contracts)) == (
        (DAY_1, "JM2701"),
        (DAY_2, "JM2705"),
        (DAY_2, "JM2705"),
    )
    assert window.bar_contracts[-1] == window.contract == "JM2705"


def test_bars_until_rejects_historical_live_owner_conflict_at_same_bar_end() -> None:
    duplicate = _bar(LIVE_END, DAY_2)
    service = _service(
        historical=(duplicate,),
        segments=(ResolvedContractSegment("JM2701", DAY_2, DAY_2),),
        live=(duplicate,),
        live_contract="JM2705",
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", "jm", "15m"),
            trading_day=DAY_2,
            end=LIVE_END,
            limit=64,
        )


def test_bars_until_rejects_historical_live_value_conflict_at_same_bar_end() -> None:
    service = _service(
        historical=(_bar_with_close(LIVE_END, DAY_2, "100"),),
        segments=(ResolvedContractSegment("JM2705", DAY_2, DAY_2),),
        live=(_bar_with_close(LIVE_END, DAY_2, "101"),),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_LIVE_UNAVAILABLE"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", "jm", "15m"),
            trading_day=DAY_2,
            end=LIVE_END,
            limit=64,
        )


def test_bars_until_rejects_historical_bar_without_rank1_owner() -> None:
    service = _service(
        historical=(_bar(LIVE_END, DAY_2),),
        segments=(),
        live=(_bar(LIVE_END, DAY_2),),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", "jm", "15m"),
            trading_day=DAY_2,
            end=LIVE_END,
            limit=64,
        )


def test_latest_canonical_window_preserves_each_bar_rank1_owner() -> None:
    canonical = (
        _bar(HISTORICAL_END_1, DAY_1),
        _bar(HISTORICAL_END_2, DAY_2),
    )
    service = _service(
        historical=canonical,
        segments=(
            ResolvedContractSegment("JM2701", DAY_1, DAY_1),
            ResolvedContractSegment("JM2705", DAY_2, DAY_2),
        ),
        live=(),
    )

    window = service.latest_canonical_window(
        SeriesPageQuery("actual_dominant", "jm", "1d"),
        trading_day=DAY_2,
        limit=64,
    )

    assert window.bars == canonical
    assert window.bar_contracts == ("JM2701", "JM2705")
    assert window.bar_contracts[-1] == window.contract == "JM2705"
