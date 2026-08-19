from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data import composition
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesQuery,
)
from app.market_data.subing_calibration import (
    SubingOutcome,
    load_accepted_subing_calibration,
)
from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    EntryProgress,
    LifecycleAvailability,
    LifecycleStage,
    evaluate_subing_lifecycle as reduce_subing_lifecycle,
)
from app.market_data.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchService,
)
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_research import SubingDirection


_DAY_ONE = date(2026, 8, 3)
_DAY_TWO = date(2026, 8, 4)


class _FakeMarketData:
    def __init__(
        self,
        results: dict[tuple[str, BarFrequency], MarketSeriesResult],
    ) -> None:
        self._results = results
        self.queries: list[SeriesQuery] = []

    def query(self, request: SeriesQuery) -> MarketSeriesResult:
        self.queries.append(request)
        return self._results[(request.symbol, request.frequency)]


def test_request_normalizes_symbol_and_rejects_invalid_window() -> None:
    request = LifecycleResearchRequest(
        since=_DAY_ONE,
        through=_DAY_TWO,
        symbol=" JM ",
    )

    assert request.symbol == "jm"
    with pytest.raises(ValueError):
        LifecycleResearchRequest(
            since=_DAY_TWO,
            through=_DAY_ONE,
            symbol=None,
        )


def test_service_uses_only_actual_dominant_and_runs_each_segment_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = (
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),
        ResolvedContractSegment("JM2701", _DAY_TWO, _DAY_TWO),
    )
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                _bars(BarFrequency.M5, (_DAY_ONE, _DAY_TWO)), segments
            ),
            ("jm", BarFrequency.M15): _result(
                _bars(BarFrequency.M15, (_DAY_ONE, _DAY_TWO)), segments
            ),
        }
    )
    factor_calls: list[tuple[BarFrequency, str, date, int]] = []
    lifecycle_calls: list[tuple[str, date, int, int]] = []

    def factors(
        bars: tuple[CanonicalBar, ...],
        *,
        timeframe: BarFrequency,
        contract: str,
        segment_start_trading_day: date,
        latest_bar_source: str,
    ) -> tuple[object, ...]:
        assert latest_bar_source == "canonical"
        factor_calls.append(
            (timeframe, contract, segment_start_trading_day, len(bars))
        )
        return tuple(object() for _bar_value in bars)

    def lifecycle(**kwargs: object) -> SimpleNamespace:
        contract = str(kwargs["contract"])
        segment_start = kwargs["segment_start_trading_day"]
        bars_5m = kwargs["bars_5m"]
        bars_15m = kwargs["bars_15m"]
        assert isinstance(segment_start, date)
        assert isinstance(bars_5m, tuple)
        assert isinstance(bars_15m, tuple)
        lifecycle_calls.append(
            (contract, segment_start, len(bars_5m), len(bars_15m))
        )
        return SimpleNamespace(snapshots=(), transitions=())

    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.calculate_subing_factor_series",
        factors,
    )
    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.evaluate_subing_lifecycle",
        lifecycle,
    )
    service = SubingLifecycleResearchService(
        market_data,
        products=("jm",),
        calibration=object(),
        policy=SimpleNamespace(policy_id="subing_lifecycle_v2_research_v1"),
    )

    result = service.run(LifecycleResearchRequest(_DAY_ONE, _DAY_TWO, None))

    assert result.products == ("jm",)
    assert result.segment_count == 2
    assert [(query.series_kind, query.frequency) for query in market_data.queries] == [
        (SeriesKind.ACTUAL_DOMINANT, BarFrequency.M5),
        (SeriesKind.ACTUAL_DOMINANT, BarFrequency.M15),
    ]
    assert factor_calls == [
        (BarFrequency.M5, "JM2609", _DAY_ONE, 1),
        (BarFrequency.M15, "JM2609", _DAY_ONE, 1),
        (BarFrequency.M5, "JM2701", _DAY_TWO, 1),
        (BarFrequency.M15, "JM2701", _DAY_TWO, 1),
    ]
    assert lifecycle_calls == [
        ("JM2609", _DAY_ONE, 1, 1),
        ("JM2701", _DAY_TWO, 1, 1),
    ]


def test_service_fails_closed_for_inconsistent_rank1_segments() -> None:
    bars_5m = _bars(BarFrequency.M5, (_DAY_ONE,))
    bars_15m = _bars(BarFrequency.M15, (_DAY_ONE,))
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                bars_5m,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            ),
            ("jm", BarFrequency.M15): _result(
                bars_15m,
                (ResolvedContractSegment("JM2701", _DAY_ONE, _DAY_ONE),),
            ),
        }
    )
    service = SubingLifecycleResearchService(
        market_data,
        products=("jm",),
        calibration=object(),
        policy=SimpleNamespace(policy_id="subing_lifecycle_v2_research_v1"),
    )

    with pytest.raises(ValueError, match="rank1 segment identity"):
        service.run(LifecycleResearchRequest(_DAY_ONE, _DAY_ONE, "jm"))


def test_service_aggregates_funnel_overlap_close_and_horizon_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = (
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),
        ResolvedContractSegment("JM2701", _DAY_TWO, _DAY_TWO),
    )
    bars_5m = _bars(
        BarFrequency.M5,
        (
            _DAY_ONE,
            _DAY_ONE,
            _DAY_ONE,
            _DAY_TWO,
            _DAY_TWO,
            _DAY_TWO,
            _DAY_TWO,
        ),
    )
    bars_15m = _bars(BarFrequency.M15, (_DAY_ONE, _DAY_TWO))
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(bars_5m, segments),
            ("jm", BarFrequency.M15): _result(bars_15m, segments),
        }
    )

    def factors(
        bars: tuple[CanonicalBar, ...],
        **_kwargs: object,
    ) -> tuple[object, ...]:
        return tuple(object() for _bar_value in bars)

    def lifecycle(**kwargs: object) -> SimpleNamespace:
        segment_bars = kwargs["bars_5m"]
        contract = kwargs["contract"]
        assert isinstance(segment_bars, tuple)
        assert isinstance(contract, str)
        first, second, third, *remaining = segment_bars
        opportunity_key = f"{contract}:opportunity"
        if contract == "JM2609":
            snapshots = (
                _snapshot(
                    first.bar_end,
                    LifecycleStage.SETUP_ARMED,
                    opportunity_key=opportunity_key,
                ),
                _snapshot(
                    second.bar_end,
                    LifecycleStage.ENTRY_CONFIRMED,
                    entry_progress=None,
                    confirmation_source=ConfirmationSource.FORMAL_V1,
                    confirmed_at=second.bar_end,
                    formal_v1_matched=True,
                    opportunity_key=opportunity_key,
                ),
                _snapshot(
                    third.bar_end,
                    LifecycleStage.CLOSED,
                    entry_progress=None,
                    confirmation_source=ConfirmationSource.FORMAL_V1,
                    confirmed_at=second.bar_end,
                    formal_v1_matched=True,
                    opportunity_key=opportunity_key,
                ),
            )
            transitions = (
                _transition(first.bar_end, LifecycleStage.SETUP_ARMED, "aligned"),
                _transition(
                    second.bar_end, LifecycleStage.ENTRY_CONFIRMED, "formal"
                ),
                _transition(third.bar_end, LifecycleStage.CLOSED, "MANUAL_FREE_CLOSE"),
            )
        else:
            (fourth,) = remaining
            snapshots = (
                _snapshot(
                    first.bar_end,
                    LifecycleStage.SETUP_ARMED,
                    trigger_kind="macd_cross",
                    triggered_at=first.bar_end,
                    opportunity_key=opportunity_key,
                ),
                _snapshot(
                    second.bar_end,
                    LifecycleStage.ENTRY_CONFIRMED,
                    entry_progress=None,
                    trigger_kind="macd_cross",
                    triggered_at=first.bar_end,
                    confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
                    confirmed_at=second.bar_end,
                    opportunity_key=opportunity_key,
                ),
                _snapshot(
                    third.bar_end,
                    LifecycleStage.EXIT_RISK,
                    entry_progress=None,
                    trigger_kind="macd_cross",
                    triggered_at=first.bar_end,
                    confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
                    confirmed_at=second.bar_end,
                    formal_v1_matched=True,
                    opportunity_key=opportunity_key,
                ),
                _snapshot(
                    fourth.bar_end,
                    LifecycleStage.CONTINUATION,
                    entry_progress=None,
                    trigger_kind="macd_cross",
                    triggered_at=first.bar_end,
                    confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
                    confirmed_at=second.bar_end,
                    opportunity_key=opportunity_key,
                    crossed_trading_day=True,
                ),
            )
            transitions = (
                _transition(first.bar_end, LifecycleStage.SETUP_ARMED, "aligned"),
                _transition(
                    second.bar_end, LifecycleStage.ENTRY_CONFIRMED, "momentum"
                ),
                _transition(
                    third.bar_end,
                    LifecycleStage.EXIT_RISK,
                    "ANCHOR_EMA21_BREACH",
                    from_stage=LifecycleStage.CONTINUATION,
                ),
                _transition(
                    fourth.bar_end,
                    LifecycleStage.CONTINUATION,
                    "ANCHOR_RECOVERY_CONFIRMED",
                    from_stage=LifecycleStage.EXIT_RISK,
                ),
            )
        return SimpleNamespace(snapshots=snapshots, transitions=transitions)

    outcome_calls: list[tuple[int, SubingDirection]] = []

    def outcomes(
        _factors: tuple[object, ...],
        _bars_value: tuple[CanonicalBar, ...],
        *,
        index: int,
        direction: object,
        horizons: tuple[int, ...],
    ) -> dict[int, SubingOutcome]:
        side = SubingDirection(direction.value)
        outcome_calls.append((index, side))
        sign = Decimal("1") if side is SubingDirection.LONG else Decimal("-1")
        return {
            horizon: SubingOutcome(
                horizon,
                sign * Decimal(horizon),
                Decimal(horizon + 1),
                Decimal(-horizon),
                horizon == 5,
            )
            for horizon in horizons
        }

    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.calculate_subing_factor_series",
        factors,
    )
    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.evaluate_subing_lifecycle",
        lifecycle,
    )
    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.build_outcomes_at",
        outcomes,
    )
    service = SubingLifecycleResearchService(
        market_data,
        products=("jm",),
        calibration=object(),
        policy=SimpleNamespace(policy_id="subing_lifecycle_v2_research_v1"),
    )

    result = service.run(LifecycleResearchRequest(_DAY_ONE, _DAY_TWO, "jm"))

    assert result.evaluable_boundary_count == 7
    assert result.funnel_counts == {
        "DATA_READY": 7,
        "DIRECTION_CONTEXT_ALIGNED": 7,
        "SETUP_ARMED": 2,
        "TRIGGER_OBSERVED": 2,
        "ENTRY_CONFIRMED": 2,
    }
    assert result.confirmation_source_counts == {
        "FORMAL_V1": 1,
        "MOMENTUM_HOLD": 1,
        "PIVOT_BREAK_HOLD": 0,
        "PIVOT_RETEST_REBREAK": 0,
    }
    assert result.v1_v2_overlap_counts == {
        "V1_AND_V2": 1,
        "V2_ONLY": 1,
        "V1_ONLY": 2,
    }
    assert result.close_reason_counts == {"MANUAL_FREE_CLOSE": 1}
    assert result.risk_reason_counts == {"ANCHOR_EMA21_BREACH": 1}
    assert result.recovery_reason_counts == {"ANCHOR_RECOVERY_CONFIRMED": 1}
    assert result.v2_to_v1_lead_bars == (1,)
    assert result.confirmed_trading_day_span_counts == {
        "SAME_DAY": 1,
        "CROSS_DAY": 1,
    }
    assert outcome_calls == [
        (1, SubingDirection.LONG),
        (1, SubingDirection.LONG),
    ]
    assert set(result.horizon_summary) == {3, 5, 8}
    assert result.horizon_summary[3].sample_count == 2
    assert result.horizon_summary[3].median_directional_return_bps == Decimal("3")
    assert result.horizon_summary[5].ema21_failure_rate == Decimal("1")


def test_service_selects_active_products_and_rejects_unknown_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segment = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),)
    jm_results = {
        ("jm", BarFrequency.M5): _result(
            _bars(BarFrequency.M5, (_DAY_ONE,)), segment
        ),
        ("jm", BarFrequency.M15): _result(
            _bars(BarFrequency.M15, (_DAY_ONE,)), segment
        ),
    }
    market_data = _FakeMarketData(jm_results)
    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.calculate_subing_factor_series",
        lambda bars, **_kwargs: tuple(object() for _bar_value in bars),
    )
    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.evaluate_subing_lifecycle",
        lambda **_kwargs: SimpleNamespace(snapshots=(), transitions=()),
    )
    service = SubingLifecycleResearchService(
        market_data,
        products=("jm",),
        calibration=object(),
        policy=SimpleNamespace(policy_id="subing_lifecycle_v2_research_v1"),
    )

    assert service.run(LifecycleResearchRequest(_DAY_ONE, _DAY_ONE, None)).products == (
        "jm",
    )
    with pytest.raises(ValueError, match="active product scope"):
        service.run(LifecycleResearchRequest(_DAY_ONE, _DAY_ONE, "ag"))


def test_composition_builder_constructs_only_historical_read_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies: dict[str, object] = {}
    market_data = object()
    calibration = object()
    policy = SimpleNamespace(policy_id="subing_lifecycle_v2_research_v1")
    monkeypatch.setattr(composition, "build_market_data_service", lambda _session: market_data)
    monkeypatch.setattr(composition, "load_active_products", lambda: ("jm",))
    monkeypatch.setattr(
        composition, "load_accepted_subing_calibration", lambda _path: calibration
    )
    monkeypatch.setattr(composition, "load_subing_lifecycle_policy", lambda _path: policy)
    monkeypatch.setattr(
        composition,
        "SubingLifecycleResearchService",
        lambda market_data_arg, **kwargs: dependencies.update(
            market_data=market_data_arg, **kwargs
        )
        or SimpleNamespace(),
    )
    monkeypatch.setattr(
        composition,
        "build_market_read_service",
        lambda _session: pytest.fail("MarketRead/Redis must not be constructed"),
    )

    composition.build_subing_lifecycle_research_service(object())

    assert dependencies == {
        "market_data": market_data,
        "products": ("jm",),
        "calibration": calibration,
        "policy": policy,
    }


def test_service_runs_the_real_factor_and_lifecycle_kernels_on_fixture_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches orchestration drift hidden by the narrow dependency doubles above."""
    segment = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),)
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                _bars(BarFrequency.M5, (_DAY_ONE,) * 180), segment
            ),
            ("jm", BarFrequency.M15): _result(
                _bars(BarFrequency.M15, (_DAY_ONE,) * 60), segment
            ),
        }
    )
    traces: list[object] = []

    def capture_trace(**kwargs: object) -> object:
        trace = reduce_subing_lifecycle(**kwargs)  # type: ignore[arg-type]
        traces.append(trace)
        return trace

    monkeypatch.setattr(
        "app.market_data.subing_lifecycle_research_service.evaluate_subing_lifecycle",
        capture_trace,
    )
    service = SubingLifecycleResearchService(
        market_data,
        products=("jm",),
        calibration=load_accepted_subing_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    result = service.run(LifecycleResearchRequest(_DAY_ONE, _DAY_ONE, "jm"))

    assert result.segment_count == 1
    unavailable_reasons = {
        snapshot.unavailable_reason
        for trace in traces
        for snapshot in trace.snapshots  # type: ignore[union-attr]
        if snapshot.unavailable_reason is not None
    }
    assert result.evaluable_boundary_count > 0, unavailable_reasons
    assert set(result.funnel_counts) == {
        "DATA_READY",
        "DIRECTION_CONTEXT_ALIGNED",
        "SETUP_ARMED",
        "TRIGGER_OBSERVED",
        "ENTRY_CONFIRMED",
    }
    assert set(result.horizon_summary) == {3, 5, 8}


def _bars(
    frequency: BarFrequency,
    trading_days: tuple[date, ...],
) -> tuple[CanonicalBar, ...]:
    counts: dict[date, int] = {}
    minute_step = 5 if frequency is BarFrequency.M5 else 15
    result: list[CanonicalBar] = []
    for trading_day in trading_days:
        index = counts.get(trading_day, 0)
        counts[trading_day] = index + 1
        close = Decimal("100") + Decimal(index)
        result.append(
            CanonicalBar(
                bar_end=datetime.combine(
                    trading_day,
                    datetime.min.time(),
                    UTC,
                )
                + timedelta(minutes=minute_step * (index + 1)),
                trading_day=trading_day,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100"),
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(result)


def _result(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=segments,
    )


def _snapshot(
    observed_at: datetime,
    stage: LifecycleStage,
    *,
    entry_progress: EntryProgress | None = EntryProgress.WAITING_TRIGGER,
    trigger_kind: str | None = None,
    triggered_at: datetime | None = None,
    confirmation_source: ConfirmationSource | None = None,
    confirmed_at: datetime | None = None,
    formal_v1_matched: bool = False,
    opportunity_key: object | None = None,
    crossed_trading_day: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        observed_at=observed_at,
        availability=LifecycleAvailability.READY,
        direction=SubingDirection.LONG,
        stage=stage,
        entry_progress=entry_progress,
        trigger_kind=trigger_kind,
        triggered_at=triggered_at,
        confirmation_source=confirmation_source,
        confirmed_at=confirmed_at,
        formal_v1_matched=formal_v1_matched,
        opportunity_key=opportunity_key,
        crossed_trading_day=crossed_trading_day,
    )


def _transition(
    transition_at: datetime,
    to_stage: LifecycleStage,
    reason: str,
    *,
    from_stage: LifecycleStage = LifecycleStage.IDLE,
) -> SimpleNamespace:
    return SimpleNamespace(
        transition_at=transition_at,
        to_stage=to_stage,
        from_stage=from_stage,
        reason_codes=(reason,),
    )
