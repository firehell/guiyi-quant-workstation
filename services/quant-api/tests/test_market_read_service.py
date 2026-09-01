from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesPageQuery,
)
from app.market_data.market_read_service import (
    MarketObservationSnapshotError,
    MarketReadService,
    MarketReadWindowError,
)
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


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

    def bars_between(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalBar, ...]:
        assert (trading_day, symbol, frequency) == (DAY_2, "jm", "15m")
        return tuple(bar for bar in self._bars if start <= bar.bar_end <= end)

    def bar_observations(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
        until: datetime,
        *,
        inclusive_after: bool,
        expected_contract: str,
    ) -> tuple[object, ...]:
        from app.market_data.live_market import LiveBarObservation

        assert (trading_day, symbol, frequency) == (DAY_2, "jm", "15m")
        assert expected_contract == self._contract
        return tuple(
            LiveBarObservation(bar=bar, contract=self._contract)
            for bar in self._bars
            if (after is None or bar.bar_end > after or (inclusive_after and bar.bar_end == after))
            and bar.bar_end <= until
        )


class _MutatingLiveStore(_LiveStore):
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        drift: str,
    ) -> None:
        super().__init__(bars, "JM2701")
        self._drift = drift
        self._available = True

    def heartbeat(self) -> dict[str, bool]:
        return {"available": self._available}

    def bars_between(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalBar, ...]:
        bars = super().bars_between(
            trading_day,
            symbol,
            frequency,
            start,
            end,
        )
        if self._drift == "subscription":
            self._contract = "JM2705"
        elif self._drift == "heartbeat":
            self._available = False
        return bars

    def bar_observations(self, *args, **kwargs) -> tuple[object, ...]:
        observations = super().bar_observations(*args, **kwargs)
        if self._drift == "subscription":
            self._contract = "JM2705"
        elif self._drift == "heartbeat":
            self._available = False
        return observations


class _ProvenanceLiveStore(_LiveStore):
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        bar_contracts: tuple[object, ...],
        drift: str | None = None,
    ) -> None:
        super().__init__(bars, "JM2701")
        self._bar_contracts = bar_contracts
        self._drift = drift
        self._available = True

    def heartbeat(self) -> dict[str, bool]:
        return {"available": self._available}

    def bars_between(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalBar, ...]:
        bars = super().bars_between(trading_day, symbol, frequency, start, end)
        self._apply_aba_drift()
        return bars

    def bar_observations(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
        until: datetime,
        *,
        inclusive_after: bool,
        expected_contract: str,
    ) -> tuple[object, ...]:
        from app.market_data.live_market import LiveBarObservation

        assert expected_contract == "JM2701"
        bars = tuple(
            bar
            for bar in self._bars
            if (after is None or bar.bar_end > after or (inclusive_after and bar.bar_end == after))
            and bar.bar_end <= until
        )
        self._apply_aba_drift()
        return tuple(
            LiveBarObservation(bar=bar, contract=contract)  # type: ignore[arg-type]
            for bar, contract in zip(bars, self._bar_contracts, strict=True)
        )

    def _apply_aba_drift(self) -> None:
        if self._drift == "subscription":
            self._contract = "JM2705"
            self._contract = "JM2701"
        elif self._drift == "heartbeat":
            self._available = False
            self._available = True


class _ForbiddenPhaseReader:
    def resolve(self, symbol: str, now: datetime) -> object:
        raise AssertionError("bars_until must not inspect the current phase")


class _TradingPhaseReader:
    def resolve(self, symbol: str, _now: datetime) -> ProductMarketPhase:
        return ProductMarketPhase(symbol, MarketPhase.TRADING, DAY_2, None, None)


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


def _observation_service(
    *,
    historical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
) -> MarketReadService:
    return MarketReadService(
        market_data=_MarketPageReader(
            historical,
            (ResolvedContractSegment("JM2705", DAY_2, DAY_2),),
        ),
        phase_resolver=_TradingPhaseReader(),
        operational_products=("jm",),
        live_store=_LiveStore(live, "JM2705"),
    )


def _mutating_observation_service(
    *,
    historical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
    drift: str,
) -> MarketReadService:
    return MarketReadService(
        market_data=_MarketPageReader(
            historical,
            (ResolvedContractSegment("JM2701", DAY_2, DAY_2),),
        ),
        phase_resolver=_TradingPhaseReader(),
        operational_products=("jm",),
        live_store=_MutatingLiveStore(live, drift=drift),
    )


def _provenance_observation_service(
    *,
    historical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
    bar_contracts: tuple[object, ...],
    drift: str | None = None,
) -> MarketReadService:
    return MarketReadService(
        market_data=_MarketPageReader(
            historical,
            (ResolvedContractSegment("JM2701", DAY_2, DAY_2),),
        ),
        phase_resolver=_TradingPhaseReader(),
        operational_products=("jm",),
        live_store=_ProvenanceLiveStore(
            live,
            bar_contracts=bar_contracts,
            drift=drift,
        ),
    )


def test_observation_snapshot_includes_exact_canonical_boundary() -> None:
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    service = _observation_service(historical=(boundary,), live=(boundary,))

    snapshot = service.observation_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=boundary.bar_end,
        now=LIVE_END,
        inclusive_after=True,
    )

    assert snapshot.state.live_available is True
    assert snapshot.source == "realtime"
    assert snapshot.trading_day == DAY_2
    assert snapshot.contract == "JM2705"
    assert snapshot.bars == (boundary,)


def test_observation_snapshot_preserves_any_field_boundary_conflict() -> None:
    canonical = _bar(HISTORICAL_END_2, DAY_2)
    live_conflict = replace(canonical, turnover=Decimal("1001"))
    service = _observation_service(
        historical=(canonical,),
        live=(live_conflict,),
    )

    snapshot = service.observation_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=canonical.bar_end,
        now=LIVE_END,
        inclusive_after=True,
    )

    assert snapshot.bars == (live_conflict,)
    assert snapshot.bars[0] != canonical


@pytest.mark.parametrize("drift", ["subscription", "heartbeat"])
def test_observation_snapshot_fails_when_authority_changes_during_bar_read(
    drift: str,
) -> None:
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    service = _mutating_observation_service(
        historical=(boundary,),
        live=(boundary,),
        drift=drift,
    )

    with pytest.raises(
        MarketObservationSnapshotError,
        match="MARKET_OBSERVATION_SNAPSHOT_CHANGED",
    ):
        service.observation_snapshot(
            SeriesPageQuery("actual_dominant", "jm", "15m"),
            after=boundary.bar_end,
            now=LIVE_END,
            inclusive_after=True,
        )


def test_observation_snapshot_rejects_contract_aba_bound_to_other_contract() -> None:
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    snapshot = _provenance_observation_service(
        historical=(boundary,),
        live=(boundary,),
        bar_contracts=("JM2705",),
        drift="subscription",
    ).observation_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=boundary.bar_end,
        now=LIVE_END,
        inclusive_after=True,
    )

    assert snapshot.source == "unavailable"
    assert snapshot.bars == ()


@pytest.mark.parametrize(
    ("bars", "bar_contracts"),
    [
        ((_bar(HISTORICAL_END_2, DAY_2),), (None,)),
        ((_bar(HISTORICAL_END_2, DAY_2),), ("invalid",)),
        (
            (
                _bar(HISTORICAL_END_2, DAY_2),
                _bar(LIVE_END, DAY_2),
            ),
            ("JM2701", "JM2705"),
        ),
    ],
    ids=("missing", "invalid", "mixed"),
)
def test_observation_snapshot_rejects_untrusted_bar_provenance(
    bars: tuple[CanonicalBar, ...],
    bar_contracts: tuple[object, ...],
) -> None:
    snapshot = _provenance_observation_service(
        historical=(bars[0],),
        live=bars,
        bar_contracts=bar_contracts,
    ).observation_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=bars[0].bar_end,
        now=LIVE_END,
        inclusive_after=True,
    )

    assert snapshot.source == "unavailable"
    assert snapshot.bars == ()


@pytest.mark.parametrize("drift", [None, "heartbeat"], ids=("stable", "availability-aba"))
def test_observation_snapshot_accepts_matching_bar_provenance(
    drift: str | None,
) -> None:
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    snapshot = _provenance_observation_service(
        historical=(boundary,),
        live=(boundary,),
        bar_contracts=("JM2701",),
        drift=drift,
    ).observation_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=boundary.bar_end,
        now=LIVE_END,
        inclusive_after=True,
    )

    assert snapshot.source == "realtime"
    assert snapshot.contract == "JM2701"
    assert snapshot.bars == (boundary,)


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
