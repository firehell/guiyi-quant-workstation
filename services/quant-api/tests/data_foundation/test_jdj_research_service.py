from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

import pytest

from app.research.jdj import jdj_research_service as research_module
from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_context import JdjBarContext
from app.research.jdj.jdj_events import JdjDirection
from app.research.jdj.jdj_events import (
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    _canonical_trend_follow_event_id,
)
from app.research.jdj.jdj_policy import load_jdj_policy
from app.research.jdj.jdj_research import JdjResearchRequest
from app.research.jdj.jdj_research import JdjSourceUnavailableError
from app.research.jdj.jdj_research_service import JdjResearchService
from app.market_data.market_data_service import MarketDataError
from app.research.n_structure.n_structure_policy import load_n_structure_policy
from app.research.n_structure.n_structure_state import NStructureKind


_CANDIDATE = "jdj_trend_follow_1m_candidate_v1"
_DAY = date(2026, 8, 20)
_SEGMENT_START = date(2026, 8, 18)


def _bar(index: int, *, minutes: int, trading_day: date = _DAY) -> CanonicalBar:
    close = Decimal("100") + Decimal(index)
    return CanonicalBar(
        bar_end=datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
        + timedelta(minutes=minutes * index),
        trading_day=trading_day,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("1"),
        turnover=None,
        open_interest=None,
    )


def _market_result(
    bars: tuple[CanonicalBar, ...],
    segment: ResolvedContractSegment,
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=(segment,),
    )


def _trend_follow_bars(count: int) -> tuple[CanonicalBar, ...]:
    bars: list[CanonicalBar] = []
    start = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
    for index in range(count):
        if index == 0:
            high, low, close = (Decimal("101"), Decimal("99"), Decimal("100"))
        elif index == 1:
            high, low, close = (Decimal("105"), Decimal("95"), Decimal("101"))
        elif index == 2:
            high, low, close = (Decimal("1000"), Decimal("1"), Decimal("102"))
        else:
            close = Decimal("100") + Decimal(index)
            high, low = close + Decimal("1"), close - Decimal("1")
        bars.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=index),
                trading_day=_DAY,
                open=close,
                high=high,
                low=low,
                close=close,
                volume=Decimal("1"),
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(bars)


def _trend_follow_contexts(
    bars: tuple[CanonicalBar, ...],
) -> tuple[JdjBarContext, ...]:
    snapshot_at = bars[0].bar_end
    return tuple(
        JdjBarContext(
            bar=bar,
            ema20=Decimal("100"),
            trend_kind=(
                NStructureKind.UNDEFINED if index == 0 else NStructureKind.BULL
            ),
            trend_snapshot_observed_at=None if index == 0 else snapshot_at,
            trend_epoch=None if index == 0 else 0,
            eligible_high_pivot=None,
            eligible_low_pivot=None,
        )
        for index, bar in enumerate(bars)
    )


def _loaded_with_1m_bars(
    bars_1m: tuple[CanonicalBar, ...],
) -> ActualDominantResearchSeries:
    segment = ResolvedContractSegment("JM2701", _DAY, _DAY)
    bars_5m = (_bar(0, minutes=5),)
    return ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: _market_result(bars_1m, segment),
                BarFrequency.M5: _market_result(bars_5m, segment),
            }
        ),
        segments=(segment,),
    )


def _trend_follow_event_at(
    bars: tuple[CanonicalBar, ...],
    index: int,
    *,
    segment_start: date,
    observation_close: Decimal | None = None,
) -> JdjTrendFollowTriggerEvent:
    reaction_at = bars[index - 1].bar_end
    observed_at = bars[index].bar_end
    trigger_level = bars[index - 1].high
    return JdjTrendFollowTriggerEvent(
        event_id=_canonical_trend_follow_event_id(
            candidate_id=_CANDIDATE,
            symbol="jm",
            contract="JM2701",
            segment_start_trading_day=segment_start,
            direction=JdjDirection.LONG,
            reaction_at=reaction_at,
            observed_at=observed_at,
            trigger_level=trigger_level,
        ),
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.TREND_FOLLOW,
        candidate_id=_CANDIDATE,
        source_event_kind="jdj_trend_follow_triggered",
        direction=JdjDirection.LONG,
        symbol="jm",
        contract="JM2701",
        segment_start_trading_day=segment_start,
        trading_day=bars[index].trading_day,
        observed_at=observed_at,
        segment_bar_index=index,
        trend_snapshot_observed_at=bars[index - 2].bar_end,
        reaction_at=reaction_at,
        ema20_at_reaction=Decimal("100"),
        trigger_level=trigger_level,
        observation_close=(
            bars[index].close
            if observation_close is None
            else observation_close
        ),
    )


def _loaded_for_segment(
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    segment: ResolvedContractSegment,
) -> ActualDominantResearchSeries:
    return ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: _market_result(bars_1m, segment),
                BarFrequency.M5: _market_result(bars_5m, segment),
            }
        ),
        segments=(segment,),
    )


class _RecordingLoader:
    def __init__(self, result: ActualDominantResearchSeries) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def load(self, **kwargs: object) -> ActualDominantResearchSeries:
        self.calls.append(kwargs)
        return self.result


class _FailingLoader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def load(self, **kwargs: object) -> ActualDominantResearchSeries:
        raise self.error


def _loaded_series() -> ActualDominantResearchSeries:
    segment = ResolvedContractSegment(
        contract="JM2701",
        start_trading_day=_SEGMENT_START,
        end_trading_day=_DAY,
    )
    bars_1m = (
        _bar(0, minutes=1, trading_day=_SEGMENT_START),
        _bar(1, minutes=1),
    )
    bars_5m = (
        _bar(0, minutes=5, trading_day=_SEGMENT_START),
        _bar(1, minutes=5),
    )
    return ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: _market_result(bars_1m, segment),
                BarFrequency.M5: _market_result(bars_5m, segment),
            }
        ),
        segments=(segment,),
    )


def _service(loader: _RecordingLoader) -> JdjResearchService:
    return JdjResearchService(
        loader,
        products=("jm",),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
    )


def test_constructor_rejects_scalar_product_scope() -> None:
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        JdjResearchService(
            _RecordingLoader(_loaded_series()),
            products="jm",  # type: ignore[arg-type]
            jdj_policy=load_jdj_policy(),
            n_policy=load_n_structure_policy(),
        )


def test_request_type_and_product_scope_fail_before_loader() -> None:
    loader = _RecordingLoader(_loaded_series())
    service = _service(loader)

    with pytest.raises(TypeError, match="request must be JdjResearchRequest"):
        service.run(object())  # type: ignore[arg-type]
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        service.run(
            JdjResearchRequest(
                since=_DAY,
                through=_DAY,
                symbol="ag",
                candidate_id=_CANDIDATE,
            )
        )

    assert loader.calls == []


def test_loader_and_context_builder_receive_exact_frequencies_and_true_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _loaded_series()
    loader = _RecordingLoader(loaded)
    builder_calls: list[dict[str, object]] = []

    def capture_contexts(
        bars_1m: tuple[CanonicalBar, ...],
        bars_5m: tuple[CanonicalBar, ...],
        **kwargs: object,
    ) -> tuple[()]:
        builder_calls.append(
            {"bars_1m": bars_1m, "bars_5m": bars_5m, **kwargs}
        )
        return ()

    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        capture_contexts,
    )
    service = _service(loader)
    request = JdjResearchRequest(
        since=_DAY,
        through=_DAY,
        symbol="jm",
        candidate_id=_CANDIDATE,
    )

    result = service.run(request)

    assert loader.calls == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.M1, BarFrequency.M5),
            "since": _DAY,
            "through": _DAY,
        }
    ]
    assert builder_calls == [
        {
            "bars_1m": loaded.results[BarFrequency.M1].bars,
            "bars_5m": loaded.results[BarFrequency.M5].bars,
            "contract": "JM2701",
            "segment_start_trading_day": _SEGMENT_START,
            "segment_end_trading_day": _DAY,
            "jdj_policy": load_jdj_policy(),
            "n_policy": load_n_structure_policy(),
        }
    ]
    assert result.products == ("jm",)
    assert result.segment_count == 1
    assert result.evaluable_bar_count == 1
    assert result.events == ()


@pytest.mark.parametrize(
    ("candidate_id", "expected_reducer", "source_event_kind"),
    (
        (
            "jdj_trend_follow_1m_candidate_v1",
            "trend_follow",
            "jdj_trend_follow_triggered",
        ),
        (
            "jdj_trend_reentry_6_1m_candidate_v1",
            "trend_reentry_6",
            "jdj_trend_reentry_6_triggered",
        ),
        (
            "jdj_key_level_breakout_1m_candidate_v1",
            "key_level_breakout",
            "jdj_key_level_breakout_triggered",
        ),
    ),
)
def test_candidate_identity_selects_only_its_exact_reducer(
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: str,
    expected_reducer: str,
    source_event_kind: str,
) -> None:
    calls: list[str] = []

    def empty_contexts(*args: object, **kwargs: object) -> tuple[()]:
        return ()

    def reducer(name: str):  # type: ignore[no-untyped-def]
        def run(*args: object, **kwargs: object) -> SimpleNamespace:
            calls.append(name)
            return SimpleNamespace(events=())

        return run

    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        empty_contexts,
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        reducer("trend_follow"),
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_reentry_6",
        reducer("trend_reentry_6"),
        raising=False,
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_key_level_breakout",
        reducer("key_level_breakout"),
        raising=False,
    )
    service = _service(_RecordingLoader(_loaded_series()))

    result = service.run(
        JdjResearchRequest(_DAY, _DAY, "jm", candidate_id)
    )

    assert calls == [expected_reducer]
    assert result.candidate_id == candidate_id
    assert result.source_event_kind == source_event_kind


@pytest.mark.parametrize(
    "source_error",
    (
        MarketDataError("/private/canonical/jm/1m missing"),
        ActualDominantResearchSegmentIdentityError(
            "/private/canonical/jm segment mismatch"
        ),
    ),
)
def test_typed_source_failures_map_to_stable_redacted_error(
    source_error: Exception,
) -> None:
    service = JdjResearchService(
        _FailingLoader(source_error),
        products=("jm",),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
    )

    with pytest.raises(JdjSourceUnavailableError) as captured:
        service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert str(captured.value) == "JDJ_SOURCE_UNAVAILABLE"
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "unexpected",
    (
        TypeError("bug"),
        ValueError("bug"),
        AssertionError("bug"),
        RuntimeError("bug"),
        KeyError("bug"),
    ),
)
def test_unexpected_loader_failures_propagate_unchanged(
    unexpected: Exception,
) -> None:
    service = JdjResearchService(
        _FailingLoader(unexpected),
        products=("jm",),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
    )

    with pytest.raises(type(unexpected)) as captured:
        service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert captured.value is unexpected


def test_missing_frequency_is_a_typed_source_failure() -> None:
    loaded = _loaded_series()
    malformed = ActualDominantResearchSeries(
        results=MappingProxyType(
            {BarFrequency.M1: loaded.results[BarFrequency.M1]}
        ),
        segments=loaded.segments,
    )
    service = _service(_RecordingLoader(malformed))

    with pytest.raises(JdjSourceUnavailableError):
        service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))


def test_uncovered_bar_is_a_typed_source_failure() -> None:
    loaded = _loaded_series()
    segment = loaded.segments[0]
    uncovered = _bar(2, minutes=1, trading_day=date(2026, 8, 17))
    m1 = loaded.results[BarFrequency.M1]
    malformed_m1 = MarketSeriesResult(
        request_identity=m1.request_identity,
        bars=(uncovered, *m1.bars),
        coverage=(uncovered.bar_end, m1.bars[-1].bar_end),
        resolved_contract_segments=(segment,),
    )
    malformed = ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: malformed_m1,
                BarFrequency.M5: loaded.results[BarFrequency.M5],
            }
        ),
        segments=(segment,),
    )

    with pytest.raises(JdjSourceUnavailableError):
        _service(_RecordingLoader(malformed)).run(
            JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
        )


def test_frequency_segment_identity_mismatch_is_a_typed_source_failure() -> None:
    loaded = _loaded_series()
    different = ResolvedContractSegment(
        contract="JM2705",
        start_trading_day=_SEGMENT_START,
        end_trading_day=_DAY,
    )
    m5 = loaded.results[BarFrequency.M5]
    malformed_m5 = MarketSeriesResult(
        request_identity=m5.request_identity,
        bars=m5.bars,
        coverage=m5.coverage,
        resolved_contract_segments=(different,),
    )
    malformed = ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: loaded.results[BarFrequency.M1],
                BarFrequency.M5: malformed_m5,
            }
        ),
        segments=loaded.segments,
    )

    with pytest.raises(JdjSourceUnavailableError):
        _service(_RecordingLoader(malformed)).run(
            JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
        )


def test_window_clipped_segments_preserve_true_segment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    true_segment = ResolvedContractSegment(
        "JM2701",
        _SEGMENT_START,
        date(2026, 8, 24),
    )
    clipped_segment = ResolvedContractSegment(
        "JM2701",
        _SEGMENT_START,
        _DAY,
    )
    bars_1m = (
        _bar(0, minutes=1, trading_day=_SEGMENT_START),
        _bar(1, minutes=1),
    )
    bars_5m = (
        _bar(0, minutes=5, trading_day=_SEGMENT_START),
        _bar(1, minutes=5),
    )
    loaded = ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: _market_result(bars_1m, clipped_segment),
                BarFrequency.M5: _market_result(bars_5m, clipped_segment),
            }
        ),
        segments=(true_segment,),
    )
    context_calls: list[dict[str, object]] = []

    def capture_contexts(
        bars_1m: tuple[CanonicalBar, ...],
        bars_5m: tuple[CanonicalBar, ...],
        **kwargs: object,
    ) -> tuple[()]:
        context_calls.append(
            {"bars_1m": bars_1m, "bars_5m": bars_5m, **kwargs}
        )
        return ()

    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        capture_contexts,
    )

    result = _service(_RecordingLoader(loaded)).run(
        JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
    )

    assert result.segment_count == 1
    assert context_calls[0]["segment_start_trading_day"] == _SEGMENT_START
    assert context_calls[0]["segment_end_trading_day"] == date(2026, 8, 24)


def test_m1_m5_trading_day_coverage_mismatch_is_a_typed_source_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _loaded_series()
    segment = loaded.segments[0]
    m5 = loaded.results[BarFrequency.M5]
    only_prefix_day = MarketSeriesResult(
        request_identity=m5.request_identity,
        bars=(m5.bars[0],),
        coverage=(m5.bars[0].bar_end, m5.bars[0].bar_end),
        resolved_contract_segments=(segment,),
    )
    malformed = ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: loaded.results[BarFrequency.M1],
                BarFrequency.M5: only_prefix_day,
            }
        ),
        segments=(segment,),
    )
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (),
    )

    with pytest.raises(JdjSourceUnavailableError):
        _service(_RecordingLoader(malformed)).run(
            JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
        )


def test_empty_returned_segment_is_a_typed_source_failure() -> None:
    first = ResolvedContractSegment(
        "JM2701", date(2026, 8, 18), date(2026, 8, 19)
    )
    empty = ResolvedContractSegment("JM2705", _DAY, _DAY)
    bar_1m = _bar(0, minutes=1, trading_day=date(2026, 8, 18))
    bar_5m = _bar(0, minutes=5, trading_day=date(2026, 8, 18))
    loaded = ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: MarketSeriesResult(
                    request_identity={},
                    bars=(bar_1m,),
                    coverage=(bar_1m.bar_end, bar_1m.bar_end),
                    resolved_contract_segments=(first, empty),
                ),
                BarFrequency.M5: MarketSeriesResult(
                    request_identity={},
                    bars=(bar_5m,),
                    coverage=(bar_5m.bar_end, bar_5m.bar_end),
                    resolved_contract_segments=(first, empty),
                ),
            }
        ),
        segments=(first, empty),
    )

    with pytest.raises(JdjSourceUnavailableError):
        _service(_RecordingLoader(loaded)).run(
            JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
        )


def test_overlapping_returned_segments_are_a_typed_source_failure() -> None:
    first = ResolvedContractSegment("JM2701", date(2026, 8, 18), _DAY)
    overlap = ResolvedContractSegment("JM2705", _DAY, date(2026, 8, 21))
    bar_1m = _bar(0, minutes=1)
    bar_5m = _bar(0, minutes=5)
    loaded = ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: MarketSeriesResult(
                    request_identity={},
                    bars=(bar_1m,),
                    coverage=(bar_1m.bar_end, bar_1m.bar_end),
                    resolved_contract_segments=(first, overlap),
                ),
                BarFrequency.M5: MarketSeriesResult(
                    request_identity={},
                    bars=(bar_5m,),
                    coverage=(bar_5m.bar_end, bar_5m.bar_end),
                    resolved_contract_segments=(first, overlap),
                ),
            }
        ),
        segments=(first, overlap),
    )

    with pytest.raises(JdjSourceUnavailableError):
        _service(_RecordingLoader(loaded)).run(
            JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
        )


def test_trigger_outcomes_use_follow_event_close_and_exclude_trigger_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _trend_follow_bars(23)
    contexts = _trend_follow_contexts(bars)
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: contexts,
    )
    service = _service(_RecordingLoader(_loaded_with_1m_bars(bars)))

    result = service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert len(result.events) == 1
    event = result.events[0]
    assert event.direction is JdjDirection.LONG
    assert event.segment_bar_index == 2
    assert event.observation_close == Decimal("102")
    assert result.trigger_count_long == 1
    assert result.trigger_count_short == 0
    assert result.horizon_summary[3].sample_count == 1
    assert result.horizon_summary[3].median_directional_return_bps == Decimal(
        "294.1176470588235294117647059"
    )
    assert result.horizon_summary[3].median_mfe_bps == Decimal(
        "392.1568627450980392156862745"
    )
    assert result.horizon_summary[3].median_mae_bps == Decimal("0")
    assert result.horizon_summary[20].sample_count == 1


def test_request_through_removes_later_trading_day_before_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _trend_follow_bars(5)
    next_day = date(2026, 8, 21)
    suffix = tuple(
        CanonicalBar(
            bar_end=datetime(2026, 8, 21, 1, index, tzinfo=UTC),
            trading_day=next_day,
            open=Decimal("110"),
            high=Decimal("111"),
            low=Decimal("109"),
            close=Decimal("110"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )
        for index in range(20)
    )
    bars = (*current, *suffix)
    segment = ResolvedContractSegment("JM2701", _DAY, next_day)
    bars_5m = (
        _bar(0, minutes=5),
        CanonicalBar(
            bar_end=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
            trading_day=next_day,
            open=Decimal("110"),
            high=Decimal("111"),
            low=Decimal("109"),
            close=Decimal("110"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        ),
    )
    event = _trend_follow_event_at(current, 2, segment_start=_DAY)
    seen_days: list[tuple[date, ...]] = []

    def capture_contexts(
        bars_1m: tuple[CanonicalBar, ...],
        *args: object,
        **kwargs: object,
    ) -> tuple[()]:
        seen_days.append(tuple(bar.trading_day for bar in bars_1m))
        return ()

    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        capture_contexts,
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        lambda *args, **kwargs: SimpleNamespace(events=(event,)),
    )
    service = _service(
        _RecordingLoader(_loaded_for_segment(bars, bars_5m, segment))
    )

    result = service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert seen_days == [(_DAY, _DAY, _DAY, _DAY, _DAY)]
    assert result.horizon_summary[3].sample_count == 0
    assert result.horizon_summary[20].sample_count == 0


def test_same_day_only_prevents_next_day_horizon_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _trend_follow_bars(5)
    next_day = date(2026, 8, 21)
    suffix = tuple(
        CanonicalBar(
            bar_end=datetime(2026, 8, 21, 1, index, tzinfo=UTC),
            trading_day=next_day,
            open=Decimal("110"),
            high=Decimal("111"),
            low=Decimal("109"),
            close=Decimal("110"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )
        for index in range(20)
    )
    bars = (*current, *suffix)
    segment = ResolvedContractSegment("JM2701", _DAY, next_day)
    bars_5m = (
        _bar(0, minutes=5),
        CanonicalBar(
            bar_end=datetime(2026, 8, 21, 1, 5, tzinfo=UTC),
            trading_day=next_day,
            open=Decimal("110"),
            high=Decimal("111"),
            low=Decimal("109"),
            close=Decimal("110"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        ),
    )
    event = _trend_follow_event_at(current, 2, segment_start=_DAY)
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        lambda *args, **kwargs: SimpleNamespace(events=(event,)),
    )

    result = _service(
        _RecordingLoader(_loaded_for_segment(bars, bars_5m, segment))
    ).run(JdjResearchRequest(_DAY, next_day, "jm", _CANDIDATE))

    assert result.horizon_summary[3].sample_count == 0
    assert result.horizon_summary[20].sample_count == 0


def test_event_alignment_drift_fails_as_context_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _trend_follow_bars(5)
    event = _trend_follow_event_at(
        bars,
        2,
        segment_start=_DAY,
        observation_close=Decimal("999"),
    )
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        lambda *args, **kwargs: SimpleNamespace(events=(event,)),
    )

    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _service(_RecordingLoader(_loaded_with_1m_bars(bars))).run(
            JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
        )


def test_events_are_sorted_by_observed_index_and_stable_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _trend_follow_bars(6)
    earlier = _trend_follow_event_at(bars, 2, segment_start=_DAY)
    later = _trend_follow_event_at(bars, 4, segment_start=_DAY)
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        lambda *args, **kwargs: SimpleNamespace(events=(later, earlier)),
    )

    result = _service(_RecordingLoader(_loaded_with_1m_bars(bars))).run(
        JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE)
    )

    assert result.events == (earlier, later)


def test_prefix_event_is_filtered_but_true_segment_index_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix_day = date(2026, 8, 18)
    bars = tuple(
        CanonicalBar(
            bar_end=datetime(2026, 8, trading_day.day, 1, minute, tzinfo=UTC),
            trading_day=trading_day,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )
        for trading_day, minute in (
            (prefix_day, 0),
            (prefix_day, 1),
            (prefix_day, 2),
            (_DAY, 0),
            (_DAY, 1),
            (_DAY, 2),
        )
    )
    segment = ResolvedContractSegment("JM2701", prefix_day, _DAY)
    bars_5m = (
        CanonicalBar(
            bar_end=datetime(2026, 8, 18, 1, 5, tzinfo=UTC),
            trading_day=prefix_day,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        ),
        _bar(1, minutes=5),
    )
    prefix_event = _trend_follow_event_at(
        bars,
        2,
        segment_start=prefix_day,
    )
    requested_event = _trend_follow_event_at(
        bars,
        5,
        segment_start=prefix_day,
    )
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        lambda *args, **kwargs: SimpleNamespace(
            events=(requested_event, prefix_event)
        ),
    )

    result = _service(
        _RecordingLoader(_loaded_for_segment(bars, bars_5m, segment))
    ).run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert result.events == (requested_event,)
    assert result.events[0].segment_bar_index == 5
    assert result.evaluable_bar_count == 3


def test_context_and_reducer_failures_are_not_source_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_error = JdjContextError()
    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (_ for _ in ()).throw(context_error),
    )
    service = _service(_RecordingLoader(_loaded_series()))

    with pytest.raises(JdjContextError) as captured:
        service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert captured.value is context_error

    monkeypatch.setattr(
        research_module,
        "build_jdj_context_series",
        lambda *args, **kwargs: (),
    )
    reducer_error = RuntimeError("reducer invariant")
    monkeypatch.setattr(
        research_module,
        "reduce_jdj_trend_follow",
        lambda *args, **kwargs: (_ for _ in ()).throw(reducer_error),
    )

    with pytest.raises(RuntimeError) as reducer_captured:
        service.run(JdjResearchRequest(_DAY, _DAY, "jm", _CANDIDATE))

    assert reducer_captured.value is reducer_error
