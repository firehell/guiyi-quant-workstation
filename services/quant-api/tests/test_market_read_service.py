from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import (
    CanonicalBar,
    DatasetKey,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesPageQuery,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.market_read_service import (
    MarketObservationSnapshotError,
    MarketReadService,
    MarketReadWindow,
    MarketReadWindowError,
)
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession


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


def _add_replay_metadata(session: Session, days: tuple[date, ...]) -> None:
    session.add_all(
        [
            Exchange(code="SHFE", name="SHFE"),
            Instrument(symbol="rb", name="RB", exchange_code="SHFE", is_active=True),
            Contract(
                contract_code="RB2610",
                instrument_symbol="rb",
                exchange_code="SHFE",
                listed_date=days[0],
                expired_date=date(2027, 1, 1),
            ),
            *(
                TradingCalendar(
                    exchange_code="SHFE",
                    trade_date=day,
                    is_trading_day=True,
                    provider="rqdata",
                )
                for day in days
            ),
            *(
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol="rb",
                    session_name="day",
                    start_time=time(9, 30),
                    end_time=time(10),
                    effective_from=day,
                    effective_to=day,
                    is_active=True,
                    provider="rqdata",
                )
                for day in days
            ),
        ]
    )
    session.commit()


@pytest.mark.parametrize(
    "gap",
    [
        "metadata",
        "listing",
        "canonical_tail",
        "live_middle",
        "prior_day_live_fill",
        "none",
    ],
)
@pytest.mark.parametrize("restart", [False, True])
def test_contract_replay_rejects_unproven_lifecycle_or_missing_intervals(
    tmp_path, gap: str, restart: bool
) -> None:
    days = (DAY_1 - timedelta(days=1), DAY_1, DAY_2)
    complete = tuple(
        _bar(datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC), day)
        for day in days
        for hour, minute in ((1, 45), (2, 0))
    )
    canonical = complete[:4]
    live = complete[4:]
    if gap == "listing":
        canonical = canonical[1:]
    elif gap == "canonical_tail":
        canonical = canonical[:-1]
    elif gap == "live_middle":
        live = live[1:]
    elif gap == "prior_day_live_fill":
        live = (canonical[-1], *live)
        canonical = canonical[:-1]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if gap != "metadata":
            _add_replay_metadata(session, days)
        catalog = MarketCatalog(session, tmp_path)
        store = CanonicalMonthlyStore(tmp_path)
        catalog.register_partition(
            store.publish(
                PublishRequest(
                    DatasetKey("contract", "rb", "RB2610", "15m"),
                    2026,
                    8,
                    canonical,
                    tuple(bar.bar_end for bar in canonical),
                )
            )
        )
        session.commit()
        service = MarketReadService(
            market_data=MarketDataService(catalog, store),
            phase_resolver=_ForbiddenPhaseReader(),
            operational_products=("rb",),
            live_store=_ContractReplayLiveStore(live),
        )
        # Restart always reconstructs from the lifecycle floor; incremental mode
        # still must prove all intervals after its already validated cursor.
        after = complete[0].bar_end - timedelta(minutes=1) if not restart else None
        if gap == "none":
            replay = service.current_contract_replay_window(
                _replay_window(), after=after
            )
            assert replay.bars == complete
            incremental = service.current_contract_replay_window(
                _replay_window(), after=canonical[-1].bar_end
            )
            assert incremental.bars == live
        else:
            code = (
                "MARKET_READ_LIVE_UNAVAILABLE"
                if gap == "prior_day_live_fill"
                else "MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE"
            )
            with pytest.raises(MarketReadWindowError, match=code):
                service.current_contract_replay_window(_replay_window(), after=after)
    engine.dispose()


class _RecordingMarketDataService:
    """Keeps the production historical reader real while freezing its cursor boundary."""

    def __init__(self, delegate: MarketDataService) -> None:
        self._delegate = delegate
        self.requests: list[SeriesPageQuery] = []

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        self.requests.append(request)
        return self._delegate.query_page(request)

    def validate_contract_replay_coverage(self, **kwargs) -> None:
        self._delegate.validate_contract_replay_coverage(**kwargs)


@dataclass(frozen=True, slots=True)
class _ProductionContractReplayFixture:
    service: MarketReadService
    market_data: _RecordingMarketDataService
    canonical: tuple[CanonicalBar, ...]
    cutoff: CanonicalBar


@pytest.fixture
def production_contract_replay_fixture(tmp_path) -> _ProductionContractReplayFixture:
    """Real Catalog/Parquet history ending before the following trading-day Live cutoff."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    canonical_end = datetime(2026, 8, 30, 2, tzinfo=UTC)
    canonical = (
        _bar(HISTORICAL_END_1, DAY_1),
        _bar(canonical_end, DAY_1),
    )
    cutoff = _bar(LIVE_END, DAY_2)
    with Session(engine) as session:
        _add_replay_metadata(session, (DAY_1, DAY_2))
        from sqlalchemy import select

        day_two_session = session.scalar(
            select(TradingSession).where(TradingSession.effective_from == DAY_2)
        )
        assert day_two_session is not None
        day_two_session.start_time = time(9, 45)
        session.commit()
        catalog = MarketCatalog(session, tmp_path)
        store = CanonicalMonthlyStore(tmp_path)
        key = DatasetKey("contract", "rb", "RB2610", "15m")
        partition = store.publish(
            PublishRequest(
                dataset=key,
                year=DAY_1.year,
                month=DAY_1.month,
                bars=canonical,
                expected_bar_ends=tuple(bar.bar_end for bar in canonical),
            )
        )
        catalog.register_partition(partition)
        session.commit()
        historical = _RecordingMarketDataService(MarketDataService(catalog, store))

        with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
            historical.query_page(
                SeriesPageQuery(
                    "contract",
                    "rb",
                    "15m",
                    contract="RB2610",
                    before=cutoff.bar_end + timedelta(microseconds=1),
                    limit=2000,
                )
            )
        historical.requests.clear()

        yield _ProductionContractReplayFixture(
            service=MarketReadService(
                market_data=historical,
                phase_resolver=_ForbiddenPhaseReader(),
                operational_products=("rb",),
                live_store=_ContractReplayLiveStore((cutoff,)),
            ),
            market_data=historical,
            canonical=canonical,
            cutoff=cutoff,
        )
    engine.dispose()


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
        assert symbol == "jm"
        return ProductMarketPhase(
            symbol=symbol,
            phase=MarketPhase.TRADING,
            trading_day=DAY_2,
            current_session=None,
            next_session_start=None,
        )


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


def test_live_snapshot_excludes_bars_after_observation_time() -> None:
    observed = _bar(LIVE_END, DAY_2)
    future = _bar(LIVE_END + timedelta(minutes=15), DAY_2)
    service = MarketReadService(
        market_data=_MarketPageReader(
            (_bar(HISTORICAL_END_2, DAY_2),),
            (ResolvedContractSegment("JM2705", DAY_2, DAY_2),),
        ),
        phase_resolver=_TradingPhaseReader(),
        operational_products=("jm",),
        live_store=_LiveStore((observed, future), "JM2705"),
    )

    snapshot = service.live_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=HISTORICAL_END_2,
        now=LIVE_END,
    )

    assert snapshot == (observed,)


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


class _ContractReplayPageReader:
    def __init__(self, bars: tuple[CanonicalBar, ...], *, stalled: bool = False) -> None:
        self._bars = bars
        self._stalled = stalled
        self.requests: list[SeriesPageQuery] = []

    def validate_contract_replay_coverage(self, **kwargs) -> None:
        # Paging/merge unit fixtures use an explicit successful metadata boundary.
        # Coverage rejection itself is exercised above with real Catalog/Parquet.
        assert kwargs["symbol"] == "rb"
        assert kwargs["contract"] == "RB2610"

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        assert request.series_kind.value == "contract"
        assert request.symbol == "rb"
        assert request.contract == "RB2610"
        assert request.frequency.value == "15m"
        assert request.limit == 2000
        self.requests.append(request)
        eligible = tuple(
            bar
            for bar in self._bars
            if request.before is None or bar.bar_end < request.before
        )
        page = eligible[-request.limit :]
        has_more_before = len(eligible) > len(page)
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=page,
            canonical_coverage=None,
            has_more_before=has_more_before or self._stalled,
            next_before=request.before if self._stalled else (page[0].bar_end if has_more_before else None),
            resolved_contract_segments=(),
        )


class _ContractReplayLiveStore:
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        bar_contracts: tuple[str, ...] | None = None,
    ) -> None:
        self._bars = bars
        self._bar_contracts = bar_contracts or ("RB2610",) * len(bars)

    def subscriptions(self, trading_day: date) -> dict[str, str]:
        return {"rb": "RB2610"}

    def heartbeat(self) -> dict[str, bool]:
        return {"available": True}

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        assert (trading_day, symbol, frequency) == (DAY_2, "rb", "15m")
        return tuple(bar for bar in self._bars if after is None or bar.bar_end > after)

    def bars_between(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalBar, ...]:
        return tuple(
            bar
            for bar in self._bars
            if start <= bar.bar_end <= end
        )

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

        assert (trading_day, symbol, frequency) == (DAY_2, "rb", "15m")
        assert expected_contract == "RB2610"
        bars = tuple(
            bar
            for bar in self._bars
            if (after is None or bar.bar_end > after or (inclusive_after and bar.bar_end == after))
            and bar.bar_end <= until
        )
        return tuple(
            LiveBarObservation(bar=bar, contract=contract)
            for bar, contract in zip(bars, self._bar_contracts, strict=True)
        )


def _replay_window(cutoff: datetime = LIVE_END) -> MarketReadWindow:
    cutoff_bar = _bar(cutoff, DAY_2)
    return MarketReadWindow(
        symbol="rb",
        series_kind="actual_dominant",
        frequency="15m",
        trading_day=DAY_2,
        contract="RB2610",
        cutoff=cutoff,
        bars=(cutoff_bar,),
        bar_contracts=("RB2610",),
    )


def _replay_service(
    historical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
    *,
    stalled: bool = False,
    live_contracts: tuple[str, ...] | None = None,
) -> tuple[MarketReadService, _ContractReplayPageReader]:
    reader = _ContractReplayPageReader(historical, stalled=stalled)
    return (
        MarketReadService(
            market_data=reader,
            phase_resolver=_ForbiddenPhaseReader(),
            operational_products=("rb",),
            live_store=_ContractReplayLiveStore(live, bar_contracts=live_contracts),
        ),
        reader,
    )


def test_current_contract_replay_bootstraps_latest_canonical_before_live_cutoff(
    production_contract_replay_fixture: _ProductionContractReplayFixture,
) -> None:
    """Catches using a Live cutoff cursor to start strict Canonical physical history."""
    fixture = production_contract_replay_fixture

    replay = fixture.service.current_contract_replay_window(
        _replay_window(fixture.cutoff.bar_end),
        after=None,
    )

    assert replay.bars == (*fixture.canonical, fixture.cutoff)
    assert fixture.canonical[-1].trading_day == DAY_1
    assert fixture.cutoff.trading_day == DAY_2
    assert fixture.market_data.requests[0].before is None


def test_current_contract_replay_clips_future_tail_and_honors_after() -> None:
    """Catches future Canonical bars or the inclusive cursor leaking into replay input."""
    future_tail = _bar(LIVE_END + timedelta(minutes=15), DAY_2)
    historical = (
        _bar(HISTORICAL_END_1, DAY_1),
        _bar(HISTORICAL_END_2, DAY_2),
        future_tail,
    )
    service, reader = _replay_service(historical, (_bar(LIVE_END, DAY_2),))

    replay = service.current_contract_replay_window(
        _replay_window(),
        after=HISTORICAL_END_1,
    )

    assert reader.requests[0].before is None
    assert replay.bars == (_bar(HISTORICAL_END_2, DAY_2), _bar(LIVE_END, DAY_2))
    assert all(HISTORICAL_END_1 < bar.bar_end <= LIVE_END for bar in replay.bars)


def test_current_contract_replay_includes_predominant_same_contract_only() -> None:
    predom = _bar(HISTORICAL_END_1, DAY_1)
    canonical = _bar(HISTORICAL_END_2, DAY_2)
    cutoff = _bar(LIVE_END, DAY_2)
    service, reader = _replay_service((predom, canonical, cutoff), (cutoff,))

    replay = service.current_contract_replay_window(_replay_window(), after=None)

    assert replay.contract == "RB2610"
    assert replay.bars == (predom, canonical, cutoff)
    assert replay.bars[-1].bar_end == LIVE_END
    assert all(request.contract == "RB2610" for request in reader.requests)


def test_current_contract_replay_pages_back_to_all_same_contract_history() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    historical = tuple(
        _bar(start + timedelta(minutes=15 * index), DAY_1)
        for index in range(2001)
    ) + (_bar(LIVE_END, DAY_2),)
    service, reader = _replay_service(historical, ())

    replay = service.current_contract_replay_window(
        _replay_window(),
        after=None,
    )

    assert replay.bars == historical
    assert len(reader.requests) == 2
    assert reader.requests[0].before is None
    assert reader.requests[1].before == historical[2].bar_end


def test_current_contract_replay_filters_after() -> None:
    historical = (
        _bar(HISTORICAL_END_1, DAY_1),
        _bar(HISTORICAL_END_2, DAY_2),
        _bar(LIVE_END, DAY_2),
    )
    service, _reader = _replay_service(historical, ())

    replay = service.current_contract_replay_window(
        _replay_window(),
        after=HISTORICAL_END_1,
    )

    assert replay.bars == historical[1:]


def test_current_contract_replay_allows_duplicate_cutoff_and_rejects_conflict() -> None:
    canonical = _bar(LIVE_END, DAY_2)
    service, _reader = _replay_service((canonical,), (canonical,))

    assert service.current_contract_replay_window(_replay_window(), after=None).bars == (
        canonical,
    )

    conflict = replace(canonical, turnover=Decimal("1001"))
    conflicted, _reader = _replay_service((canonical,), (conflict,))
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_LIVE_UNAVAILABLE"):
        conflicted.current_contract_replay_window(_replay_window(), after=None)


def test_current_contract_replay_rejects_live_bar_from_another_contract() -> None:
    predom = _bar(HISTORICAL_END_2, DAY_2)
    cutoff = _bar(LIVE_END, DAY_2)
    service, _reader = _replay_service(
        (predom,),
        (cutoff,),
        live_contracts=("RB2605",),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_LIVE_UNAVAILABLE"):
        service.current_contract_replay_window(_replay_window(), after=None)


@pytest.mark.parametrize(
    ("after", "error"),
    [
        (LIVE_END + timedelta(microseconds=1), "MARKET_READ_AFTER_EXCEEDS_CUTOFF"),
        (datetime(2026, 8, 31, 2, 0), "MARKET_READ_AFTER_TIMEZONE_REQUIRED"),
    ],
)
def test_current_contract_replay_rejects_invalid_after(
    after: datetime,
    error: str,
) -> None:
    service, _reader = _replay_service((_bar(LIVE_END, DAY_2),), ())

    with pytest.raises(MarketReadWindowError, match=error):
        service.current_contract_replay_window(_replay_window(), after=after)


def test_current_contract_replay_allows_stale_duplicate_cutoff() -> None:
    service, _reader = _replay_service((_bar(LIVE_END, DAY_2),), ())

    replay = service.current_contract_replay_window(_replay_window(), after=LIVE_END)

    assert replay.bars == ()


def test_current_contract_replay_fails_closed_for_missing_cutoff_and_stalled_cursor() -> None:
    missing, _reader = _replay_service((_bar(HISTORICAL_END_2, DAY_2),), ())
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        missing.current_contract_replay_window(_replay_window(), after=None)

    stalled, _reader = _replay_service((_bar(HISTORICAL_END_2, DAY_2),), (), stalled=True)
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_PAGINATION_STALLED"):
        stalled.current_contract_replay_window(_replay_window(), after=None)


@pytest.mark.parametrize(
    ("error", "expected_type", "expected"),
    (
        (
            MarketDataError("DATASET_OR_PARTITION_MISSING"),
            MarketReadWindowError,
            "MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE",
        ),
        (RuntimeError("unexpected"), RuntimeError, "unexpected"),
    ),
)
def test_current_contract_replay_maps_only_market_data_history_errors(
    error: Exception,
    expected_type: type[Exception],
    expected: str,
) -> None:
    """Catches leaking storage failure codes or swallowing unrelated programming errors."""

    class FailingHistoryReader:
        def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
            raise error

    service = MarketReadService(
        market_data=FailingHistoryReader(),
        phase_resolver=_ForbiddenPhaseReader(),
        operational_products=("rb",),
        live_store=_ContractReplayLiveStore((_bar(LIVE_END, DAY_2),)),
    )

    with pytest.raises(expected_type, match=expected):
        service.current_contract_replay_window(_replay_window(), after=None)
