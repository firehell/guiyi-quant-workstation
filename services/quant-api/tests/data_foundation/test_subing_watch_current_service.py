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
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.market_read_service import MarketReadState
from app.market_data.subing_watch.contracts import (
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
    ) -> None:
        self.live = live or {}
        self.contracts = contracts or {}

    def state(self, identity, _now) -> MarketReadState:
        bars = self.live.get(identity.frequency, ())
        contract = self.contracts.get(identity.frequency, CONTRACT)
        return MarketReadState(
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

    def live_snapshot(self, identity, _after, _now) -> tuple[CanonicalBar, ...]:
        return self.live.get(identity.frequency, ())


def _service(
    canonical_15m: tuple[CanonicalBar, ...],
    *,
    canonical_60m: tuple[CanonicalBar, ...] = (),
    live: dict[BarFrequency, tuple[CanonicalBar, ...]] | None = None,
    contracts: dict[BarFrequency, str] | None = None,
    loader_error: Exception | None = None,
    segment_error: MarketDataError | None = None,
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
        _Loader(loader_error or _result(canonical_15m, canonical_60m)),
        products=("jm",),
        market_read=_MarketRead(live=live, contracts=contracts),
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


def test_canonical_live_exact_overlap_is_an_idempotent_noop() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))

    projected = _service(
        canonical,
        live={BarFrequency.M15: (canonical[-1],)},
    ).current(_request(), canonical[-1].bar_end)

    assert projected.source_mode == "canonical"
    assert len(projected.evaluations) == len(canonical)
    assert projected.final_state.sma21_window == (100.0,) * len(canonical)


def test_canonical_live_conflicting_overlap_fails_closed() -> None:
    canonical = tuple(_bar(index) for index in range(1, 5))
    conflict = replace(
        canonical[-1],
        open=Decimal("101"),
        high=Decimal("101"),
        low=Decimal("101"),
        close=Decimal("101"),
    )

    with pytest.raises(
        SubingWatchCurrentSourceIdentityError,
        match="SUBING_WATCH_CURRENT_SOURCE_IDENTITY_INVALID",
    ):
        _service(
            canonical,
            live={BarFrequency.M15: (conflict,)},
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
    bars_15m = tuple(_bar(index) for index in range(1, 121))
    bars_60m = tuple(_bar(index, minutes=60) for index in range(1, 26))
    live_60m = _bar(26, minutes=60)

    projected = _service(
        bars_15m,
        canonical_60m=bars_60m,
        live={BarFrequency.H1: (live_60m,)},
        contracts={BarFrequency.H1: "JM2605"},
    ).current(_request(), bars_15m[-1].bar_end)

    assert projected.evaluations[-1].outcome in {
        "evaluated_no_signal",
        "evaluated_candidate",
    }
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


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
