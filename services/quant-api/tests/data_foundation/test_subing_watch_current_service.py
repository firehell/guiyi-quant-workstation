from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

import pytest

from guiyi_quant.indicators.subing_watch_15m import step_subing_watch_15m

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.market_read_service import (
    MarketObservationSnapshot,
    MarketObservationSnapshotError,
    MarketReadService,
    MarketReadState,
)
from app.market_data.subing_watch.contracts import (
    SubingWatchSourceIdentity,
    from_kernel_evaluation,
    load_subing_watch_policy,
    to_subing_watch_kernel_bar,
)
from app.market_data.subing_watch.current_service import (
    SubingWatchCurrentProjectionService,
    SubingWatchCurrentRequest,
    SubingWatchCurrentSourceIdentityError,
    SubingWatchCurrentSourceUnavailableError,
)
from app.market_data.subing_watch.replay import replay_subing_watch_segment


DAY = date(2026, 9, 1)
START = datetime(2026, 9, 1, tzinfo=UTC)
CONTRACT = "JM2601"
SEGMENT = ResolvedContractSegment(CONTRACT, DAY, DAY)


def _bar(index: int, *, minutes: int = 15, close: str = "100") -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=START + timedelta(minutes=minutes * index),
        trading_day=DAY,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(100 + index),
        turnover=None,
        open_interest=None,
    )


def _candidate_bars() -> tuple[CanonicalBar, ...]:
    return (*(_bar(index) for index in range(1, 35)), _bar(35, close="110"))


def _result(
    bars_15m: tuple[CanonicalBar, ...],
    bars_60m: tuple[CanonicalBar, ...],
    *,
    segments: tuple[ResolvedContractSegment, ...] = (SEGMENT,),
) -> ActualDominantResearchSeries:
    def series(bars: tuple[CanonicalBar, ...]) -> MarketSeriesResult:
        return MarketSeriesResult(
            request_identity=MappingProxyType({"series_kind": "actual_dominant"}),
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            resolved_contract_segments=segments,
            requested_trading_day_window=(DAY, DAY),
        )

    return ActualDominantResearchSeries(
        MappingProxyType(
            {
                BarFrequency.M15: series(bars_15m),
                BarFrequency.H1: series(bars_60m),
            }
        ),
        segments,
    )


class _Loader:
    def __init__(self, value: ActualDominantResearchSeries | Exception) -> None:
        self.value = value

    def load(self, **_kwargs) -> ActualDominantResearchSeries:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _MarketRead:
    def __init__(
        self,
        *,
        live: dict[BarFrequency, tuple[CanonicalBar, ...]] | None = None,
        contracts: dict[BarFrequency, str] | None = None,
        snapshot_contracts: dict[BarFrequency, str] | None = None,
        snapshot_days: dict[BarFrequency, date] | None = None,
    ) -> None:
        self.live = live or {}
        self.contracts = contracts or {}
        self.snapshot_contracts = snapshot_contracts or {}
        self.snapshot_days = snapshot_days or {}

    def observation_snapshot(
        self,
        identity,
        _after,
        _now,
        *,
        inclusive_after=False,
    ) -> MarketObservationSnapshot:
        assert inclusive_after is True
        bars = self.live.get(identity.frequency, ())
        contract = self.contracts.get(identity.frequency, CONTRACT)
        state = MarketReadState(
            symbol=identity.symbol,
            series_kind=identity.series_kind.value,
            frequency=identity.frequency.value,
            operational=True,
            phase="TRADING",
            trading_day=DAY,
            live_eligible=bool(bars),
            live_available=bool(bars),
            live_contract=contract if bars else None,
            canonical_end=None,
            after_market=MappingProxyType({}),
        )
        return MarketObservationSnapshot(
            state=state,
            source="realtime" if bars else "none",
            trading_day=self.snapshot_days.get(identity.frequency, DAY),
            contract=(
                self.snapshot_contracts.get(identity.frequency, contract)
                if bars
                else None
            ),
            bars=bars,
        )


class _MarketPageReader:
    def __init__(self, bars: tuple[CanonicalBar, ...]) -> None:
        self.bars = bars

    def query_page(self, request) -> MarketSeriesPageResult:
        bars = tuple(
            bar
            for bar in self.bars
            if request.before is None or bar.bar_end < request.before
        )[-request.limit :]
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=bars,
            canonical_coverage=None,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(SEGMENT,),
        )


class _PhaseReader:
    def resolve(self, symbol: str, _now: datetime) -> ProductMarketPhase:
        return ProductMarketPhase(symbol, MarketPhase.TRADING, DAY, None, None)


class _LiveStore:
    def __init__(self, bars: tuple[CanonicalBar, ...]) -> None:
        self.bars = bars

    def subscriptions(self, _trading_day: date) -> dict[str, str]:
        return {"jm": CONTRACT}

    def heartbeat(self) -> dict[str, bool]:
        return {"available": True}

    def bars_after(self, _day, _symbol, frequency, after):
        return (
            tuple(bar for bar in self.bars if after is None or bar.bar_end > after)
            if frequency == "15m"
            else ()
        )

    def bars_between(self, _day, _symbol, frequency, start, end):
        return (
            tuple(bar for bar in self.bars if start <= bar.bar_end <= end)
            if frequency == "15m"
            else ()
        )

    def bar_observations(
        self,
        _day,
        _symbol,
        frequency,
        after,
        until,
        *,
        inclusive_after,
        expected_contract,
    ):
        from app.market_data.live_market import LiveBarObservation

        return (
            tuple(
                LiveBarObservation(bar=bar, contract=expected_contract)
                for bar in self.bars
                if (after is None or bar.bar_end > after or (inclusive_after and bar.bar_end == after))
                and bar.bar_end <= until
            )
            if frequency == "15m"
            else ()
        )


def _real_market_read(
    canonical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
) -> MarketReadService:
    return MarketReadService(
        market_data=_MarketPageReader(canonical),
        phase_resolver=_PhaseReader(),
        operational_products=("jm",),
        live_store=_LiveStore(live),
    )


def _service(
    canonical_15m: tuple[CanonicalBar, ...],
    *,
    canonical_60m: tuple[CanonicalBar, ...] = (),
    live: dict[BarFrequency, tuple[CanonicalBar, ...]] | None = None,
    contracts: dict[BarFrequency, str] | None = None,
    snapshot_contracts: dict[BarFrequency, str] | None = None,
    snapshot_days: dict[BarFrequency, date] | None = None,
    market_read=None,
    loader_error: Exception | None = None,
    segment_error: MarketDataError | None = None,
    loader=None,
) -> SubingWatchCurrentProjectionService:
    def current_segment(symbol: str, _target: date):
        if segment_error is not None:
            raise segment_error
        return SimpleNamespace(
            symbol=symbol,
            contract=CONTRACT,
            start_trading_day=DAY,
            end_trading_day=DAY,
        )

    return SubingWatchCurrentProjectionService(
        loader or _Loader(loader_error or _result(canonical_15m, canonical_60m)),
        products=("jm",),
        market_read=market_read
        or _MarketRead(
            live=live,
            contracts=contracts,
            snapshot_contracts=snapshot_contracts,
            snapshot_days=snapshot_days,
        ),
        current_segment=current_segment,
        policy=load_subing_watch_policy(),
    )


def _request() -> SubingWatchCurrentRequest:
    return SubingWatchCurrentRequest(
        SeriesKind.ACTUAL_DOMINANT,
        "jm",
        BarFrequency.M15,
    )


def test_current_at_cutoff_equals_historical_segment_replay() -> None:
    bars = tuple(_bar(index) for index in range(1, 8))
    now = bars[-1].bar_end

    current = _service(bars).current(_request(), now)
    historical = replay_subing_watch_segment(
        current.source_identity,
        bars,
        (),
        load_subing_watch_policy(),
    )

    assert current.cutoff == now
    assert current.source_mode == "canonical"
    assert current.evaluations == historical.evaluations
    assert current.coverage == historical.coverage


def test_restore_then_same_contract_live_append_equals_full_replay() -> None:
    canonical = tuple(_bar(index) for index in range(1, 7))
    live_bar = _bar(7, close="105")
    restored = _service(canonical).restore_state("jm", canonical[-1].bar_end)
    full = _service(
        canonical,
        live={BarFrequency.M15: (live_bar,)},
    ).current(_request(), live_bar.bar_end)

    kernel_bar = to_subing_watch_kernel_bar(
        live_bar,
        source_identity=restored.source_identity,
    )
    continued_state, continued_evaluation = step_subing_watch_15m(
        restored.state,
        kernel_bar,
    )

    assert continued_state == full.final_state
    assert from_kernel_evaluation(
        continued_evaluation,
        source_mode="canonical_live",
    ) == full.evaluations[-1]


def test_restore_preserves_ready_60m_context_for_next_15m_without_new_60m() -> None:
    canonical_15m = tuple(_bar(index) for index in range(1, 121))
    canonical_60m = tuple(_bar(index, minutes=60) for index in range(1, 26))
    live_bar = _bar(121, close="105")
    restored = _service(
        canonical_15m,
        canonical_60m=canonical_60m,
    ).restore_state("jm", canonical_15m[-1].bar_end)
    full = replay_subing_watch_segment(
        restored.source_identity,
        (*canonical_15m, live_bar),
        canonical_60m,
        restored.policy,
        source_mode="canonical_live",
    )

    continued_state, continued_evaluation = step_subing_watch_15m(
        restored.state,
        to_subing_watch_kernel_bar(
            live_bar,
            source_identity=restored.source_identity,
        ),
        higher_timeframe=restored.latest_higher_timeframe,
    )

    assert restored.latest_higher_timeframe is not None
    assert continued_state == full.final_state
    assert from_kernel_evaluation(
        continued_evaluation,
        source_mode="canonical_live",
    ) == full.evaluations[-1]


def test_canonical_live_exact_overlap_is_an_idempotent_noop() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))

    projected = _service(
        canonical,
        market_read=_real_market_read(canonical, (canonical[-1],)),
    ).current(_request(), canonical[-1].bar_end)

    assert projected.source_mode == "canonical"
    assert len(projected.evaluations) == len(canonical)
    assert projected.final_state.sma21_window == (100.0,) * len(canonical)


@pytest.mark.parametrize(
    ("changes"),
    [
        {
            "open": Decimal("101"),
            "high": Decimal("101"),
            "low": Decimal("101"),
            "close": Decimal("101"),
        },
        {"turnover": Decimal("1001")},
        {"open_interest": Decimal("21")},
        {"trading_day": DAY + timedelta(days=1)},
    ],
)
def test_canonical_live_any_field_conflicting_overlap_fails_closed(
    changes: dict[str, object],
) -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))
    conflict = replace(canonical[-1], **changes)

    with pytest.raises(
        SubingWatchCurrentSourceIdentityError,
        match="SUBING_WATCH_CURRENT_SOURCE_IDENTITY_INVALID",
    ):
        _service(
            canonical,
            market_read=_real_market_read(canonical, (conflict,)),
        ).current(_request(), canonical[-1].bar_end)


def test_typed_snapshot_contract_drift_fails_closed() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))
    live_bar = _bar(5)

    with pytest.raises(SubingWatchCurrentSourceIdentityError):
        _service(
            canonical,
            live={BarFrequency.M15: (live_bar,)},
            snapshot_contracts={BarFrequency.M15: "JM2605"},
        ).current(_request(), live_bar.bar_end)


def test_typed_snapshot_trading_day_drift_fails_closed() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))
    live_bar = _bar(5)

    with pytest.raises(SubingWatchCurrentSourceIdentityError):
        _service(
            canonical,
            live={BarFrequency.M15: (live_bar,)},
            snapshot_days={BarFrequency.M15: DAY + timedelta(days=1)},
        ).current(_request(), live_bar.bar_end)


def test_malformed_typed_snapshot_fails_closed() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))

    class _MalformedMarketRead:
        def observation_snapshot(self, *_args, **_kwargs):
            return SimpleNamespace()

    with pytest.raises(SubingWatchCurrentSourceIdentityError):
        _service(
            canonical,
            market_read=_MalformedMarketRead(),
        ).current(_request(), canonical[-1].bar_end)


def test_observation_snapshot_drift_maps_to_source_unavailable() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))

    class _ChangedMarketRead:
        def observation_snapshot(self, *_args, **_kwargs):
            raise MarketObservationSnapshotError()

    with pytest.raises(SubingWatchCurrentSourceUnavailableError):
        _service(
            canonical,
            market_read=_ChangedMarketRead(),
        ).current(_request(), canonical[-1].bar_end)


def test_15m_live_contract_must_match_frozen_physical_segment() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))
    live_bar = _bar(5)

    with pytest.raises(SubingWatchCurrentSourceIdentityError):
        _service(
            canonical,
            live={BarFrequency.M15: (live_bar,)},
            contracts={BarFrequency.M15: "JM2605"},
        ).current(_request(), live_bar.bar_end)


def test_60m_live_identity_mismatch_is_unavailable_but_non_gating() -> None:
    bars_15m = _candidate_bars()
    bars_60m = tuple(_bar(index, minutes=60) for index in range(1, 26))
    live_60m = _bar(26, minutes=60)

    projected = _service(
        bars_15m,
        canonical_60m=bars_60m,
        live={BarFrequency.H1: (live_60m,)},
        contracts={BarFrequency.H1: "JM2605"},
    ).current(_request(), bars_15m[-1].bar_end)

    assert projected.evaluations[-1].outcome == "evaluated_candidate"
    assert projected.evaluations[-1].observation_types == ("buy",)
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


@pytest.mark.parametrize(
    "higher_error",
    (
        MarketDataError("MARKET_PARTITION_MISSING"),
        ActualDominantResearchSegmentIdentityError(),
    ),
)
def test_missing_or_invalid_canonical_60m_preserves_15m_candidate(
    higher_error: Exception,
) -> None:
    bars_15m = _candidate_bars()

    class _MissingHigherLoader:
        def load(self, *, frequencies, **_kwargs):
            if BarFrequency.H1 in frequencies:
                raise higher_error
            return _result(bars_15m, ())

    projected = _service(
        bars_15m,
        loader=_MissingHigherLoader(),
    ).current(_request(), bars_15m[-1].bar_end)

    assert projected.evaluations[-1].outcome == "evaluated_candidate"
    assert projected.evaluations[-1].observation_types == ("buy",)
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


def test_unavailable_60m_snapshot_preserves_15m_candidate() -> None:
    bars_15m = _candidate_bars()

    class _UnavailableHigherRead(_MarketRead):
        def observation_snapshot(self, identity, *args, **kwargs):
            if identity.frequency is BarFrequency.H1:
                state = MarketReadState(
                    symbol="jm",
                    series_kind="actual_dominant",
                    frequency="60m",
                    operational=True,
                    phase="TRADING",
                    trading_day=DAY,
                    live_eligible=False,
                    live_available=False,
                    live_contract=None,
                    canonical_end=None,
                    after_market=MappingProxyType({}),
                )
                return MarketObservationSnapshot(state, "unavailable", DAY, None, ())
            return super().observation_snapshot(identity, *args, **kwargs)

    projected = _service(
        bars_15m,
        market_read=_UnavailableHigherRead(),
    ).current(_request(), bars_15m[-1].bar_end)

    assert projected.evaluations[-1].outcome == "evaluated_candidate"
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


def test_conflicting_60m_overlap_preserves_15m_candidate() -> None:
    bars_15m = _candidate_bars()
    canonical_60m = (_bar(1, minutes=60),)
    conflict = replace(
        canonical_60m[0],
        open=Decimal("101"),
        high=Decimal("101"),
        low=Decimal("101"),
        close=Decimal("101"),
    )

    projected = _service(
        bars_15m,
        canonical_60m=canonical_60m,
        live={BarFrequency.H1: (conflict,)},
    ).current(_request(), bars_15m[-1].bar_end)

    assert projected.evaluations[-1].outcome == "evaluated_candidate"
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


def test_future_60m_snapshot_preserves_15m_candidate_with_empty_context() -> None:
    bars_15m = _candidate_bars()
    future = replace(
        _bar(1, minutes=60),
        bar_end=bars_15m[-1].bar_end + timedelta(hours=1),
    )

    projected = _service(
        bars_15m,
        live={BarFrequency.H1: (future,)},
    ).current(_request(), bars_15m[-1].bar_end)

    assert projected.evaluations[-1].outcome == "evaluated_candidate"
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


def test_future_malformed_60m_live_tail_preserves_current_historical_parity() -> None:
    bars_15m = tuple(_bar(index) for index in range(1, 121))
    canonical_60m = tuple(_bar(index, minutes=60) for index in range(1, 26))
    future_malformed = replace(
        _bar(1, minutes=60, close="1E+9999"),
        bar_end=bars_15m[-1].bar_end + timedelta(minutes=15),
    )
    historical = replay_subing_watch_segment(
        SubingWatchSourceIdentity("jm", CONTRACT, DAY),
        bars_15m,
        canonical_60m,
        load_subing_watch_policy(),
    )

    current = _service(
        bars_15m,
        canonical_60m=canonical_60m,
        live={BarFrequency.H1: (future_malformed,)},
    ).current(_request(), bars_15m[-1].bar_end)

    assert current.evaluations == historical.evaluations
    assert current.latest_higher_timeframe == historical.latest_higher_timeframe


@pytest.mark.parametrize(
    ("loader_error", "segment_error", "expected"),
    [
        (None, MarketDataError("MAIN_CONTRACT_MAP_MISSING"), SubingWatchCurrentSourceUnavailableError),
        (MarketDataError("MARKET_PARTITION_MISSING"), None, SubingWatchCurrentSourceUnavailableError),
        (ActualDominantResearchSegmentIdentityError(), None, SubingWatchCurrentSourceIdentityError),
    ],
)
def test_missing_map_partition_or_identity_fails_closed(
    loader_error: Exception | None,
    segment_error: MarketDataError | None,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected):
        _service(
            (_bar(1),),
            loader_error=loader_error,
            segment_error=segment_error,
        ).current(_request(), _bar(1).bar_end)


def test_main_contract_summary_requires_explicit_symbol_identity() -> None:
    bars = (_bar(1),)
    service = SubingWatchCurrentProjectionService(
        _Loader(_result(bars, ())),
        products=("jm",),
        market_read=_MarketRead(),
        current_segment=lambda _symbol, _target: SimpleNamespace(
            contract=CONTRACT,
            start_trading_day=DAY,
            end_trading_day=DAY,
        ),
        policy=load_subing_watch_policy(),
    )

    with pytest.raises(
        SubingWatchCurrentSourceIdentityError,
        match="SUBING_WATCH_CURRENT_SOURCE_IDENTITY_INVALID",
    ):
        service.current(_request(), bars[-1].bar_end)


def test_composition_builds_only_the_read_only_current_projection(monkeypatch) -> None:
    from app.market_data import composition

    canonical = (_bar(1), _bar(2))
    loader = _Loader(_result(canonical, ()))
    market_data = SimpleNamespace(
        dominant_segment_for_day=lambda symbol, _target: SimpleNamespace(
            symbol=symbol,
            contract=CONTRACT,
            start_trading_day=DAY,
            end_trading_day=DAY,
        )
    )
    monkeypatch.setattr(composition, "build_market_data_service", lambda _session: market_data)
    monkeypatch.setattr(composition, "build_market_read_service", lambda _session: _MarketRead())
    monkeypatch.setattr(composition, "load_active_products", lambda: ("jm",))
    monkeypatch.setattr(
        composition,
        "ActualDominantResearchSegmentLoader",
        lambda _market_data: loader,
    )

    service = composition.build_subing_watch_current_service(SimpleNamespace())

    projected = service.current(_request(), canonical[-1].bar_end)
    assert projected.cutoff == canonical[-1].bar_end
    assert projected.source_mode == "canonical"
