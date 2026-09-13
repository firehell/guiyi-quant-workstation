from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
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
from app.market_data.live_market import LiveBarObservation
from app.market_data.market_read_service import (
    MarketObservationSnapshotError,
    MarketReadService,
    MarketReadWindow,
    MarketReadWindowError,
)
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)


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


def test_replay_endpoint_authority_can_bound_today_without_losing_lifecycle(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _add_replay_metadata(session, (DAY_1, DAY_2))
        mds = MarketDataService(
            MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
        )
        endpoints = mds.expected_contract_replay_endpoints(
            symbol="rb",
            contract="RB2610",
            frequency="15m",
            trading_day=DAY_2,
            cutoff=LIVE_END,
        )
        assert endpoints == (
            (HISTORICAL_END_1, DAY_1),
            (datetime(2026, 8, 30, 2, tzinfo=UTC), DAY_1),
            (HISTORICAL_END_2, DAY_2),
            (LIVE_END, DAY_2),
        )
        today = mds.expected_contract_replay_endpoints(
            symbol="rb",
            contract="RB2610",
            frequency="1m",
            trading_day=DAY_2,
            cutoff=LIVE_END,
            since=DAY_2,
        )
        assert len(today) == 30
        assert today[0] == (datetime(2026, 8, 31, 1, 31, tzinfo=UTC), DAY_2)
        assert today[-1] == (LIVE_END, DAY_2)


def test_replay_endpoint_queries_are_bounded_across_long_exact_session_history(
    tmp_path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    first = date(2024, 1, 1)
    through = date(2025, 11, 30)
    calendar = tuple(
        first + timedelta(days=offset) for offset in range((through - first).days + 1)
    )
    trading_days = tuple(day for day in calendar if day.weekday() < 5)
    with Session(engine) as session:
        _add_replay_metadata(session, trading_days)
        session.add_all(
            TradingCalendar(
                exchange_code="SHFE",
                trade_date=day,
                is_trading_day=False,
                provider="rqdata",
            )
            for day in calendar
            if day.weekday() >= 5
        )
        contract = session.scalar(
            select(Contract).where(Contract.contract_code == "RB2610")
        )
        assert contract is not None
        contract.expired_date = through + timedelta(days=1)
        session.commit()
        service = MarketDataService(
            MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
        )
        selects: list[str] = []

        def count_selects(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", count_selects)
        try:
            endpoints = service.expected_contract_replay_endpoints(
                symbol="rb",
                contract="RB2610",
                frequency="15m",
                trading_day=trading_days[-1],
                cutoff=datetime.combine(trading_days[-1], time.max, tzinfo=UTC),
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_selects)

    assert len(trading_days) == 500
    assert len(endpoints) == 1000
    assert {day for _bar_end, day in endpoints} == set(trading_days)
    assert len(selects) <= 6


@pytest.mark.parametrize("frequency", ("5m", "15m", "60m"))
def test_actual_dominant_alert_window_rejects_a_missing_owned_session_endpoint(
    tmp_path, frequency: str
) -> None:
    """Catches compressing a legal Session gap into the HTDY 32-bar input."""
    first = date(2026, 8, 27)
    through = date(2026, 9, 2)
    calendar_days = tuple(
        first + timedelta(days=offset)
        for offset in range((through - first).days + 1)
    )
    trading_days = tuple(day for day in calendar_days if day.weekday() < 5)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Exchange(code="SHFE", name="SHFE"),
                Instrument(symbol="rb", name="RB", exchange_code="SHFE", is_active=True),
                Contract(
                    contract_code="RB2605",
                    instrument_symbol="rb",
                    exchange_code="SHFE",
                    listed_date=first,
                    expired_date=date(2027, 1, 1),
                ),
                Contract(
                    contract_code="RB2610",
                    instrument_symbol="rb",
                    exchange_code="SHFE",
                    listed_date=first,
                    expired_date=date(2027, 1, 1),
                ),
                *(
                    TradingCalendar(
                        exchange_code="SHFE",
                        trade_date=day,
                        is_trading_day=day in trading_days,
                        provider="rqdata",
                    )
                    for day in calendar_days
                ),
                *(
                    MainContractMap(
                        symbol="rb",
                        trade_date=day,
                        rank=1,
                        contract_code=(
                            "RB2605" if day == trading_days[-2] else "RB2610"
                        ),
                    )
                    for day in trading_days[:-1]
                ),
            ]
        )
        for day in trading_days:
            sessions = (
                ("morning_1", time(9), time(10, 15)),
                ("morning_2", time(10, 30), time(11, 30)),
                ("afternoon", time(13, 30), time(15)),
            )
            if day != trading_days[0]:
                sessions = (("night", time(21), time(23)), *sessions)
            for name, start, end in sessions:
                session.add(
                    TradingSession(
                        exchange_code="SHFE",
                        instrument_symbol="rb",
                        session_name=name,
                        start_time=start,
                        end_time=end,
                        effective_from=day,
                        effective_to=day,
                        crosses_midnight=False,
                        is_active=True,
                        provider="rqdata",
                    )
                )
        session.commit()
        mds = MarketDataService(
            MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
        )
        endpoints = tuple(
            (*item, "RB2605" if day == trading_days[-2] else "RB2610")
            for day in trading_days
            for item in mds.expected_contract_replay_endpoints(
                symbol="rb",
                contract="RB2605" if day == trading_days[-2] else "RB2610",
                frequency=frequency,
                trading_day=day,
                cutoff=datetime.max.replace(tzinfo=UTC),
                since=day,
            )
        )
        selected = endpoints[-33:]
        bars = tuple(_bar(bar_end, day) for bar_end, day, _owner in selected)
        owners = tuple(owner for _bar_end, _day, owner in selected)
        if frequency == "60m":
            assert set(owners) == {"RB2605", "RB2610"}

        mds.validate_actual_dominant_alert_window(
            symbol="rb",
            frequency=frequency,
            trading_day=trading_days[-1],
            current_contract="RB2610",
            cutoff=bars[-1].bar_end,
            bars=bars,
            bar_contracts=owners,
        )

        sparse = bars[:10] + bars[11:]
        sparse_owners = owners[:10] + owners[11:]
        with pytest.raises(MarketDataError, match="ACTUAL_DOMINANT_ALERT_WINDOW_UNAVAILABLE"):
            mds.validate_actual_dominant_alert_window(
                symbol="rb",
                frequency=frequency,
                trading_day=trading_days[-1],
                current_contract="RB2610",
                cutoff=bars[-1].bar_end,
                bars=sparse,
                bar_contracts=sparse_owners,
            )
    engine.dispose()


def test_input_readiness_separates_historical_prefix_from_live_gap(tmp_path):
    from app.market_data.live_market import LiveBarObservation

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _add_replay_metadata(session, (DAY_1, DAY_2))
        catalog = MarketCatalog(session, tmp_path)
        store = CanonicalMonthlyStore(tmp_path)
        canonical = (
            _bar(HISTORICAL_END_1, DAY_1),
            _bar(datetime(2026, 8, 30, 2, tzinfo=UTC), DAY_1),
        )
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
        # Today's MainContractMap is published by after-market; the frozen Live
        # rank1 snapshot is the established intraday authority.
        session.commit()

        class Live(_ContractReplayLiveStore):
            def bar_observations(
                self, trading_day, symbol, frequency, after, until, **kwargs
            ):
                if frequency == "1m":
                    return tuple(
                        LiveBarObservation(
                            _bar(LIVE_END - timedelta(minutes=i), DAY_2), "RB2610"
                        )
                        for i in reversed(range(29))
                    )
                return (LiveBarObservation(_bar(LIVE_END, DAY_2), "RB2610"),)

        service = MarketReadService(
            market_data=MarketDataService(catalog, store),
            phase_resolver=_ForbiddenPhaseReader(),
            operational_products=("rb",),
            live_store=Live((_bar(LIVE_END, DAY_2),)),
        )
        result = service.contract_input_readiness(
            "rb", trading_day=DAY_2, as_of=LIVE_END
        )
        assert result["status"] == "blocked"
        assert result["historical_15m_gap"]["count"] == 0
        assert result["live_1m_gap"]["count"] == 1
        assert result["live_1m_gap"]["first"] == "2026-08-31T01:31:00+00:00"
        assert result["live_15m_gap"]["count"] == 1
        assert "LIVE_1M_GAP" in result["error_codes"]
        assert "LIVE_15M_GAP" in result["error_codes"]


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
            bar
            for bar in self._bars
            if request.before is None or bar.bar_end < request.before
        )[-request.limit :]
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=bars,
            canonical_coverage=None,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=self._segments,
        )

    @staticmethod
    def validate_actual_dominant_alert_window(**_kwargs) -> None:
        return None


class _LiveStore:
    def recovery_state(self, trading_day, symbol, expected_contract):
        return None

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
            if (
                after is None
                or bar.bar_end > after
                or (inclusive_after and bar.bar_end == after)
            )
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
            if (
                after is None
                or bar.bar_end > after
                or (inclusive_after and bar.bar_end == after)
            )
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


@pytest.mark.parametrize(
    "drift", [None, "heartbeat"], ids=("stable", "availability-aba")
)
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


def test_display_snapshot_rejects_a_bar_bound_to_a_previous_contract() -> None:
    """Catches a detail snapshot relabelling a delayed old-owner Bar as the current owner."""
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    live = _bar(LIVE_END, DAY_2)
    snapshot = _provenance_observation_service(
        historical=(boundary,),
        live=(live,),
        bar_contracts=("JM2705",),
    ).display_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=boundary.bar_end,
        now=LIVE_END,
    )

    assert snapshot.source == "none"
    assert snapshot.bars == ()


@pytest.mark.parametrize("drift", ["subscription", "heartbeat"])
def test_display_snapshot_discards_bars_when_authority_changes_during_read(
    drift: str,
) -> None:
    """Catches snapshot Bars escaping after their owner or availability changed."""
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    live = _bar(LIVE_END, DAY_2)
    snapshot = _mutating_observation_service(
        historical=(boundary,),
        live=(live,),
        drift=drift,
    ).display_snapshot(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        after=boundary.bar_end,
        now=LIVE_END,
    )

    assert snapshot.source == "none"
    assert snapshot.bars == ()


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
    assert tuple(
        zip((bar.trading_day for bar in window.bars), window.bar_contracts)
    ) == (
        (DAY_1, "JM2701"),
        (DAY_2, "JM2705"),
        (DAY_2, "JM2705"),
    )
    assert window.bar_contracts[-1] == window.contract == "JM2705"


@pytest.mark.parametrize("symbol,frequency,contract", [
    ("jm", "5m", "JM2701"),
    ("jm", "15m", "JM2701"),
    ("rb", "60m", "RB2610"),
])
@pytest.mark.parametrize("defect", [
    "wrong_contract", "missing_contract", "noncanonical_contract",
    "wrong_trading_day", "duplicate_endpoint", "beyond_cutoff",
])
def test_bars_until_rejects_malformed_redis_provenance(
    symbol: str, frequency: str, contract: str, defect: str,
) -> None:
    from app.market_data.live_market import RedisLiveStore
    from tests.data_foundation.test_live_market import FakeRedis

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    store.set_subscriptions(DAY_2, {symbol: contract})
    store.put_bar(DAY_2, symbol, frequency, _bar(LIVE_END, DAY_2), contract=contract)
    key = next(iter(redis.zsets))
    raw, score = next(iter(redis.zsets[key].items()))
    payload = json.loads(raw)
    if defect == "wrong_contract":
        payload["contract"] = "JM2705" if symbol == "jm" else "RB2701"
    elif defect == "missing_contract":
        del payload["contract"]
    elif defect == "noncanonical_contract":
        payload["contract"] = contract.lower()
    elif defect == "wrong_trading_day":
        payload["trading_day"] = DAY_1.isoformat()
    elif defect == "beyond_cutoff":
        payload["bar_end"] = (LIVE_END + timedelta(minutes=1)).isoformat()
    if defect != "duplicate_endpoint":
        del redis.zsets[key][raw]
    # Different JSON whitespace creates distinct members with identical endpoints.
    redis.zadd(key, {json.dumps(payload): score})
    # A valid historical cutoff exposes silently discarded future payloads.
    service = MarketReadService(
        market_data=_MarketPageReader(
            (_bar(LIVE_END, DAY_2),) if defect == "beyond_cutoff" else (),
            (ResolvedContractSegment(contract, DAY_2, DAY_2),),
        ),
        phase_resolver=_ForbiddenPhaseReader(),
        operational_products=(symbol,),
        live_store=store,
    )
    with pytest.raises(MarketReadWindowError, match="^MARKET_READ_LIVE_UNAVAILABLE$"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", symbol, frequency),
            trading_day=DAY_2, end=LIVE_END,
        )


@pytest.mark.parametrize("malformed", [object(), LiveBarObservation(object(), "JM2705")])
def test_bars_until_rejects_invalid_typed_observation(malformed: object) -> None:
    class InvalidObservationStore(_LiveStore):
        def bar_observations(self, *_args, **_kwargs):
            return (malformed,)

    service = _service(historical=(), segments=(), live=(_bar(LIVE_END, DAY_2),))
    service._live_store = InvalidObservationStore((_bar(LIVE_END, DAY_2),), "JM2705")
    with pytest.raises(MarketReadWindowError, match="^MARKET_READ_LIVE_UNAVAILABLE$"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", "jm", "15m"),
            trading_day=DAY_2, end=LIVE_END,
        )


def test_bars_until_bounds_redis_read_and_dedupes_matching_canonical_overlap() -> None:
    from app.market_data.live_market import RedisLiveStore
    from tests.data_foundation.test_live_market import FakeRedis

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    store.set_subscriptions(DAY_2, {"jm": "JM2705"})
    boundary = _bar(HISTORICAL_END_2, DAY_2)
    cutoff_bar = _bar(LIVE_END, DAY_2)
    for bar in (boundary, cutoff_bar):
        store.put_bar(DAY_2, "jm", "15m", bar, contract="JM2705")
    # Corrupt future data must not poison this completed, cutoff-bounded read.
    key = next(iter(redis.zsets))
    redis.zadd(key, {"invalid future payload": int((LIVE_END + timedelta(minutes=15)).timestamp() * 1000)})
    service = MarketReadService(
        market_data=_MarketPageReader(
            (_bar(HISTORICAL_END_1, DAY_1), boundary),
            (ResolvedContractSegment("JM2701", DAY_1, DAY_1),
             ResolvedContractSegment("JM2705", DAY_2, DAY_2)),
        ),
        phase_resolver=_ForbiddenPhaseReader(),
        operational_products=("jm",),
        live_store=store,
    )
    window = service.bars_until(
        SeriesPageQuery("actual_dominant", "jm", "15m"),
        trading_day=DAY_2, end=LIVE_END,
    )
    assert window.bars == (_bar(HISTORICAL_END_1, DAY_1), boundary, cutoff_bar)
    assert window.bar_contracts == ("JM2701", "JM2705", "JM2705")


def test_bars_until_rejects_fixed_in_session_gap_before_htdy_signal_changes() -> None:
    from app.alerts.evaluators import HtdyOriginalEvaluator

    prior = date(2026, 8, 27)

    def endpoints(day: date, night_day: date) -> tuple[datetime, ...]:
        return tuple(
            [datetime(night_day.year, night_day.month, night_day.day, 13, minute, tzinfo=UTC) for minute in (15, 30, 45)]
            + [datetime(night_day.year, night_day.month, night_day.day, hour, minute, tzinfo=UTC) for hour, minute in ((14, 0), (14, 15), (14, 30), (14, 45), (15, 0))]
            + [datetime(day.year, day.month, day.day, 1, minute, tzinfo=UTC) for minute in (15, 30, 45)]
            + [datetime(day.year, day.month, day.day, 2, minute, tzinfo=UTC) for minute in (0, 15, 45)]
            + [datetime(day.year, day.month, day.day, 3, minute, tzinfo=UTC) for minute in (0, 15, 30)]
            + [datetime(day.year, day.month, day.day, 5, 45, tzinfo=UTC)]
            + [datetime(day.year, day.month, day.day, 6, minute, tzinfo=UTC) for minute in (0, 15, 30, 45)]
            + [datetime(day.year, day.month, day.day, 7, 0, tzinfo=UTC)]
        )

    points = tuple(
        (bar_end, day)
        for day, night_day in ((prior, date(2026, 8, 26)), (date(2026, 8, 28), prior))
        for bar_end in endpoints(day, night_day)
    )[-41:] + tuple((bar_end, DAY_2) for bar_end in endpoints(DAY_2, date(2026, 8, 28)))
    prices = (
        103.048, 93.344, 90.627, 102.765, 91.059, 100.975, 109.429, 99.274,
        96.241, 92.124, 96.038, 96.405, 92.342, 104.05, 102.047, 104.357,
        92.143, 95.009, 108.501, 90.176, 97.397, 106.359, 94.577, 94.401,
        102.749, 95.035, 96.721, 97.832, 95.974, 103.181, 104.692, 105.222,
        109.608, 91.456, 95.134, 109.73, 105.961, 105.209, 94.446, 92.567,
        95.507, 107.857, 105.01, 97.339, 103.173, 104.705, 95.732, 92.128,
        106.222, 104.157, 106.144, 104.855, 97.309, 103.089, 97.336, 108.071,
        92.478, 103.932, 96.928, 108.192, 106.077, 93.499, 90.313, 94.675,
    )
    all_bars = tuple(
        _bar_with_close(bar_end, day, str(price))
        for (bar_end, day), price in zip(points, prices, strict=True)
    )

    class ValidatingReader(_MarketPageReader):
        def validate_actual_dominant_alert_window(self, **kwargs) -> None:
            actual = tuple(
                (bar.bar_end, bar.trading_day, owner)
                for bar, owner in zip(kwargs["bars"], kwargs["bar_contracts"], strict=True)
            )
            expected = tuple(
                (bar.bar_end, bar.trading_day, "JM2705")
                for bar in all_bars
                if actual[0][0] <= bar.bar_end <= kwargs["cutoff"]
            )
            if actual != expected:
                raise MarketDataError("ACTUAL_DOMINANT_ALERT_WINDOW_UNAVAILABLE")

    def read(live: tuple[CanonicalBar, ...]) -> tuple[MarketReadService, MarketReadWindow]:
        service = MarketReadService(
            market_data=ValidatingReader(
                all_bars[:41], (ResolvedContractSegment("JM2705", prior, DAY_2),)
            ),
            phase_resolver=_ForbiddenPhaseReader(),
            operational_products=("jm",),
            live_store=_LiveStore(live, "JM2705"),
        )
        window = service.bars_until(
            SeriesPageQuery("actual_dominant", "jm", "15m"),
            trading_day=DAY_2,
            end=all_bars[-1].bar_end,
            limit=64,
        )
        return service, window

    service, full = read(all_bars[41:])
    assert HtdyOriginalEvaluator().evaluate_candidates(service, full)[0].observation_types == ("buy",)
    sparse_live = all_bars[41:61] + all_bars[62:]
    service, sparse = read(sparse_live)
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_WINDOW_INCOMPLETE"):
        HtdyOriginalEvaluator().evaluate_candidates(service, sparse)


def test_rule_specific_alert_windows_keep_subing_on_current_contract_lifecycle(
    tmp_path,
) -> None:
    """Catches applying HTDY's cross-owner 32-bar proof to SuBing replay."""
    from app.alerts.evaluators import HtdyOriginalEvaluator, SubingThs15mEvaluator

    first = date(2026, 9, 1)
    through = date(2026, 9, 21)
    calendar_days = tuple(
        first + timedelta(days=offset)
        for offset in range((through - first).days + 1)
    )
    trading_days = tuple(day for day in calendar_days if day.weekday() < 5)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            (
                Exchange(code="SHFE", name="SHFE"),
                Instrument(
                    symbol="rb",
                    name="RB",
                    exchange_code="SHFE",
                    is_active=True,
                ),
                Contract(
                    contract_code="RB2605",
                    instrument_symbol="rb",
                    exchange_code="SHFE",
                    listed_date=first,
                    expired_date=date(2027, 1, 1),
                ),
                Contract(
                    contract_code="RB2610",
                    instrument_symbol="rb",
                    exchange_code="SHFE",
                    listed_date=first,
                    expired_date=date(2027, 1, 1),
                ),
            )
        )
        session.add_all(
            TradingCalendar(
                exchange_code="SHFE",
                trade_date=day,
                is_trading_day=day in trading_days,
                provider="rqdata",
            )
            for day in calendar_days
        )
        session.add_all(
            MainContractMap(
                symbol="rb",
                trade_date=day,
                rank=1,
                contract_code="RB2610" if day == trading_days[-1] else "RB2605",
            )
            for day in trading_days
        )
        session.add_all(
            TradingSession(
                exchange_code="SHFE",
                instrument_symbol="rb",
                session_name="day",
                start_time=time(9),
                end_time=time(11),
                effective_from=day,
                effective_to=day,
                crosses_midnight=False,
                is_active=True,
                provider="rqdata",
            )
            for day in trading_days
        )
        session.commit()

        catalog = MarketCatalog(session, tmp_path)
        store = CanonicalMonthlyStore(tmp_path)
        market_data = MarketDataService(catalog, store)
        endpoints: list[tuple[datetime, date]] = []
        for day in trading_days:
            endpoints.extend(
                market_data.expected_contract_replay_endpoints(
                    symbol="rb",
                    contract="RB2610",
                    frequency="15m",
                    trading_day=day,
                    cutoff=datetime.max.replace(tzinfo=UTC),
                    since=day,
                )
            )
        current_bars = tuple(
            _bar_with_close(bar_end, day, str(Decimal("100") + Decimal(index % 17) / 10))
            for index, (bar_end, day) in enumerate(endpoints)
        )
        old_endpoints = list(endpoints[:-8])
        missing_old_owner = old_endpoints.pop(-12)
        old_bars = tuple(
            _bar_with_close(bar_end, day, str(Decimal("100") + Decimal(index % 17) / 10))
            for index, (bar_end, day) in enumerate(old_endpoints)
        )
        for contract, bars in (("RB2605", old_bars), ("RB2610", current_bars)):
            artifact = store.publish(
                PublishRequest(
                    DatasetKey("contract", "rb", contract, "15m"),
                    2026,
                    9,
                    bars,
                    tuple(bar.bar_end for bar in bars),
                )
            )
            catalog.register_partition(artifact)
        session.commit()

        class Live:
            def __init__(self, bars: tuple[CanonicalBar, ...]) -> None:
                self._bars = bars

            @staticmethod
            def subscriptions(_day):
                return {"rb": "RB2610"}

            @staticmethod
            def recovery_state(*_args):
                return None

            def bars_after(self, *_args):
                return self._bars[-8:]

            def bar_observations(self, *_args, **_kwargs):
                return tuple(
                    LiveBarObservation(bar, "RB2610") for bar in self._bars[-8:]
                )

        market_read = MarketReadService(
            market_data=market_data,
            phase_resolver=_ForbiddenPhaseReader(),
            operational_products=("rb",),
            live_store=Live(current_bars),
        )
        actual_page = market_data.query_page(
            SeriesPageQuery(
                "actual_dominant",
                "rb",
                "15m",
                before=current_bars[-1].bar_end + timedelta(microseconds=1),
                limit=64,
            )
        )
        assert len(current_bars) == 120
        assert len(actual_page.bars) == 64
        assert missing_old_owner not in tuple(
            (bar.bar_end, bar.trading_day) for bar in old_bars
        )

        window = market_read.bars_until(
            SeriesPageQuery("actual_dominant", "rb", "15m"),
            trading_day=trading_days[-1],
            end=current_bars[-1].bar_end,
            limit=64,
        )
        candidates = SubingThs15mEvaluator().evaluate_candidates(market_read, window)

        assert len(candidates) == 1
        assert candidates[0].bar_end == current_bars[-1].bar_end
        with pytest.raises(
            MarketReadWindowError, match="MARKET_READ_WINDOW_INCOMPLETE"
        ):
            HtdyOriginalEvaluator().evaluate_candidates(market_read, window)

        htdy_prices = (
            103.048, 93.344, 90.627, 102.765, 91.059, 100.975, 109.429, 99.274,
            96.241, 92.124, 96.038, 96.405, 92.342, 104.05, 102.047, 104.357,
            92.143, 95.009, 108.501, 90.176, 97.397, 106.359, 94.577, 94.401,
            102.749, 95.035, 96.721, 97.832, 95.974, 103.181, 104.692, 105.222,
            109.608, 91.456, 95.134, 109.73, 105.961, 105.209, 94.446, 92.567,
            95.507, 107.857, 105.01, 97.339, 103.173, 104.705, 95.732, 92.128,
            106.222, 104.157, 106.144, 104.855, 97.309, 103.089, 97.336, 108.071,
            92.478, 103.932, 96.928, 108.192, 106.077, 93.499, 90.313, 94.675,
        )
        htdy_close = {
            endpoint: str(price)
            for endpoint, price in zip(endpoints[-64:], htdy_prices, strict=True)
        }

        def repaired_bars(
            owned_endpoints: list[tuple[datetime, date]],
        ) -> tuple[CanonicalBar, ...]:
            return tuple(
                _bar_with_close(
                    bar_end,
                    day,
                    htdy_close.get(
                        (bar_end, day),
                        str(Decimal("100") + Decimal(index % 17) / 10),
                    ),
                )
                for index, (bar_end, day) in enumerate(owned_endpoints)
            )

        repaired_old_bars = repaired_bars(endpoints[:-8])
        repaired_current_bars = repaired_bars(endpoints)
        for contract, bars in (
            ("RB2605", repaired_old_bars),
            ("RB2610", repaired_current_bars),
        ):
            artifact = store.publish(
                PublishRequest(
                    DatasetKey("contract", "rb", contract, "15m"),
                    2026,
                    9,
                    bars,
                    tuple(bar.bar_end for bar in bars),
                )
            )
            catalog.register_partition(artifact)
        session.commit()
        repaired_read = MarketReadService(
            market_data=market_data,
            phase_resolver=_ForbiddenPhaseReader(),
            operational_products=("rb",),
            live_store=Live(repaired_current_bars),
        )
        repaired_window = repaired_read.bars_until(
            SeriesPageQuery("actual_dominant", "rb", "15m"),
            trading_day=trading_days[-1],
            end=repaired_current_bars[-1].bar_end,
            limit=64,
        )

        repaired_candidates = HtdyOriginalEvaluator().evaluate_candidates(
            repaired_read, repaired_window
        )
        assert len(repaired_candidates) == 1
        assert repaired_candidates[0].observation_types == ("buy",)


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_htdy_canonical_window_never_reads_live_recovery(frequency: str) -> None:
    """D1/W1 evaluation is canonical-only even when the live seam is unavailable."""
    from app.alerts.evaluators import HtdyOriginalEvaluator

    first = date(2026, 8, 1)
    bars = tuple(
        _bar_with_close(
            datetime.combine(first + timedelta(days=index), time(7), tzinfo=UTC),
            first + timedelta(days=index),
            str(Decimal("100") + Decimal(index) / 10),
        )
        for index in range(32)
    )

    class ForbiddenLive:
        def __getattr__(self, name: str):
            raise AssertionError(f"canonical evaluation touched live seam: {name}")

    service = MarketReadService(
        market_data=_MarketPageReader(
            bars,
            (ResolvedContractSegment("RB2610", first, bars[-1].trading_day),),
        ),
        phase_resolver=_ForbiddenPhaseReader(),
        operational_products=("rb",),
        live_store=ForbiddenLive(),
    )
    window = service.latest_canonical_window(
        SeriesPageQuery("actual_dominant", "rb", frequency),
        trading_day=bars[-1].trading_day,
        limit=64,
    )

    assert HtdyOriginalEvaluator().evaluate_candidates(service, window) == ()


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
    def __init__(
        self, bars: tuple[CanonicalBar, ...], *, stalled: bool = False
    ) -> None:
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
            next_before=request.before
            if self._stalled
            else (page[0].bar_end if has_more_before else None),
            resolved_contract_segments=(),
        )


class _ContractReplayLiveStore:
    def recovery_state(self, trading_day, symbol, expected_contract):
        return None

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

        assert (trading_day, symbol, frequency) == (DAY_2, "rb", "15m")
        assert expected_contract == "RB2610"
        bars = tuple(
            bar
            for bar in self._bars
            if (
                after is None
                or bar.bar_end > after
                or (inclusive_after and bar.bar_end == after)
            )
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


def test_contract_replay_rejects_recovery_committed_after_window_was_read():
    from app.market_data.live_market import LiveRecoveryState

    service, reader = _replay_service(
        (_bar(HISTORICAL_END_1, DAY_1),), (_bar(LIVE_END, DAY_2),)
    )
    service._live_store.recovery_state = lambda *args: LiveRecoveryState(1, LIVE_END)
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_RECOVERY_CHANGED"):
        service.current_contract_replay_window(_replay_window(), after=None)
    assert reader.requests == []


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
        _bar(start + timedelta(minutes=15 * index), DAY_1) for index in range(2001)
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

    assert service.current_contract_replay_window(
        _replay_window(), after=None
    ).bars == (canonical,)

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


def test_current_contract_replay_fails_closed_for_missing_cutoff_and_stalled_cursor() -> (
    None
):
    missing, _reader = _replay_service((_bar(HISTORICAL_END_2, DAY_2),), ())
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        missing.current_contract_replay_window(_replay_window(), after=None)

    stalled, _reader = _replay_service(
        (_bar(HISTORICAL_END_2, DAY_2),), (), stalled=True
    )
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
