from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
import traceback

import pytest

from app.research.n_structure import n_structure_research_service as research_module
from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.research.n_structure.n_structure_policy import load_n_structure_policy
from app.research.n_structure.n_structure_segment import evaluate_n_structure_segment
from app.market_data.market_data_service import MarketDataError
from app.research.n_structure.n_structure_research_service import (
    NStructureSegmentIdentityError,
    NStructureResearchRequest,
    NStructureResearchService,
    NStructureSourceUnavailableError,
)


_VALUES = (
    ("10", "9"),
    ("9", "8.5"),
    ("8.5", "8"),
    ("9.5", "8.2"),
    ("12", "9"),
    ("11", "8.8"),
    ("13", "9"),
    ("14", "10"),
    ("13", "9.5"),
    ("15", "10"),
)


def _bars() -> tuple[CanonicalBar, ...]:
    start = datetime(2026, 8, 18, 1, 5, tzinfo=UTC)
    days = (
        *(date(2026, 8, 18) for _ in range(6)),
        *(date(2026, 8, 19) for _ in range(2)),
        *(date(2026, 8, 20) for _ in range(2)),
    )
    result: list[CanonicalBar] = []
    for index, ((high, low), trading_day) in enumerate(zip(_VALUES, days, strict=True)):
        high_value = Decimal(high)
        low_value = Decimal(low)
        close = (high_value + low_value) / Decimal(2)
        result.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=5 * index),
                trading_day=trading_day,
                open=close,
                high=high_value,
                low=low_value,
                close=close,
                volume=Decimal("1"),
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(result)


class _FakeSegmentLoader:
    def __init__(self, bars: tuple[CanonicalBar, ...]) -> None:
        segment = ResolvedContractSegment(
            contract="JM2701",
            start_trading_day=date(2026, 8, 18),
            end_trading_day=date(2026, 8, 20),
        )
        result = MarketSeriesResult(
            request_identity={},
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end),
            resolved_contract_segments=(segment,),
        )
        self.result = ActualDominantResearchSeries(
            results=MappingProxyType({BarFrequency.M5: result}),
            segments=(segment,),
        )
        self.calls: list[dict[str, object]] = []

    def load(self, **kwargs: object) -> ActualDominantResearchSeries:
        self.calls.append(kwargs)
        return self.result


class _FailingSegmentLoader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def load(self, **kwargs: object) -> ActualDominantResearchSeries:
        raise self.error


@pytest.mark.parametrize(
    ("shared_error", "public_error", "code"),
    (
        (
            MarketDataError("DATASET_OR_PARTITION_MISSING"),
            NStructureSourceUnavailableError,
            "N_STRUCTURE_SOURCE_UNAVAILABLE",
        ),
        (
            ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is incomplete for 5m"
            ),
            NStructureSegmentIdentityError,
            "N_STRUCTURE_SEGMENT_IDENTITY_INVALID",
        ),
    ),
)
def test_shared_loader_failures_map_to_stable_sanitized_n_errors(
    shared_error: Exception,
    public_error: type[Exception],
    code: str,
) -> None:
    service = NStructureResearchService(
        _FailingSegmentLoader(shared_error),
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    with pytest.raises(public_error) as captured:
        service.run(
            NStructureResearchRequest(
                since=date(2026, 8, 18),
                through=date(2026, 8, 20),
                symbol="jm",
            )
        )

    assert str(captured.value) == code
    assert getattr(captured.value, "code", None) == code
    assert captured.value.__cause__ is None
    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert "/private/canonical" not in rendered
    assert "MarketDataError" not in rendered


@pytest.mark.parametrize(
    "unexpected",
    (
        TypeError("bug"),
        ValueError("bug"),
        AssertionError("bug"),
        RuntimeError("bug"),
    ),
)
def test_unexpected_loader_errors_escape_without_unavailable_wrapping(
    unexpected: Exception,
) -> None:
    service = NStructureResearchService(
        _FailingSegmentLoader(unexpected),
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    with pytest.raises(type(unexpected)) as captured:
        service.run(NStructureResearchRequest(date(2026, 8, 18), date(2026, 8, 20), "jm"))

    assert captured.value is unexpected


def test_reducer_uses_true_segment_prefix_but_counts_only_requested_window() -> None:
    loader = _FakeSegmentLoader(_bars())
    service = NStructureResearchService(
        loader,
        products=("jm", "ag"),
        policy=load_n_structure_policy(),
    )

    request = NStructureResearchRequest(
            since=date(2026, 8, 19),
            through=date(2026, 8, 20),
            symbol=" JM ",
    )
    result = service.run(request)

    assert loader.calls == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.M5,),
            "since": date(2026, 8, 19),
            "through": date(2026, 8, 20),
        }
    ]
    assert result.products == ("jm",)
    assert result.segment_count == 1
    assert result.evaluable_bar_count == 4
    assert result.confirmed_pivot_count == 3
    assert result.completed_n_counts == {"up": 2, "down": 0}
    assert result.structure_established_counts == {"bull": 1, "bear": 0, "range": 0}

    horizon_3 = result.horizon_summary[3]
    assert horizon_3.sample_count == 1
    assert horizon_3.median_directional_return_bps == Decimal(
        "1363.636363636363636363636364"
    )
    assert horizon_3.median_mfe_bps == Decimal(
        "3636.363636363636363636363636"
    )
    assert horizon_3.median_mae_bps == Decimal(
        "-1363.636363636363636363636364"
    )
    assert result.horizon_summary[5].sample_count == 0
    assert result.horizon_summary[8].sample_count == 0

    trace = evaluate_n_structure_segment(
        _bars(),
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 18),
        segment_end_trading_day=date(2026, 8, 20),
        policy=load_n_structure_policy(),
    )
    expected = tuple(
        pattern
        for pattern in trace.patterns.patterns
        if pattern.completed_at in {bar.bar_end for bar in _bars()[6:]}
    )
    events = service.completion_events(request)
    assert tuple(event.event_id for event in events) == tuple(
        pattern.n_id for pattern in expected
    )
    assert tuple(event.observed_at for event in events) == tuple(
        pattern.completed_at for pattern in expected
    )
    assert tuple(event.segment_bar_index for event in events) == tuple(
        _bars().index(next(bar for bar in _bars() if bar.bar_end == pattern.completed_at))
        for pattern in expected
    )
    assert all(event.symbol == "jm" for event in events)
    assert all(event.contract == "JM2701" for event in events)
    assert service.run(request) == result


def test_research_uses_one_segment_trace_without_legacy_rescans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def counted_segment(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return evaluate_n_structure_segment(*args, **kwargs)  # type: ignore[arg-type]

    def legacy_scan(*args: object, **kwargs: object) -> None:
        raise AssertionError("research used a legacy linear rescan")

    monkeypatch.setattr(
        research_module,
        "evaluate_n_structure_segment",
        counted_segment,
        raising=False,
    )
    monkeypatch.setattr(
        research_module,
        "_bar_index",
        legacy_scan,
        raising=False,
    )
    monkeypatch.setattr(
        research_module,
        "_prefix_replacement_count",
        legacy_scan,
        raising=False,
    )
    service = NStructureResearchService(
        _FakeSegmentLoader(_bars()),
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    result = service.run(
        NStructureResearchRequest(
            since=date(2026, 8, 19),
            through=date(2026, 8, 20),
            symbol="jm",
        )
    )

    assert calls == 1
    assert result.completed_n_counts == {"up": 2, "down": 0}


def test_outcomes_stop_at_requested_through_even_if_loader_returns_later_bars() -> None:
    bars = _bars()
    later = tuple(
        CanonicalBar(
            bar_end=bars[-1].bar_end + timedelta(minutes=5 * (index + 1)),
            trading_day=date(2026, 8, 21),
            open=Decimal("13"),
            high=Decimal("14"),
            low=Decimal("12"),
            close=Decimal("13"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )
        for index in range(8)
    )
    loaded_bars = (*bars, *later)
    segment = ResolvedContractSegment(
        contract="JM2701",
        start_trading_day=date(2026, 8, 18),
        end_trading_day=date(2026, 8, 21),
    )
    loaded_result = MarketSeriesResult(
        request_identity={},
        bars=loaded_bars,
        coverage=(loaded_bars[0].bar_end, loaded_bars[-1].bar_end),
        resolved_contract_segments=(segment,),
    )
    loader = _FakeSegmentLoader(bars)
    loader.result = ActualDominantResearchSeries(
        results=MappingProxyType({BarFrequency.M5: loaded_result}),
        segments=(segment,),
    )
    service = NStructureResearchService(
        loader,
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    result = service.run(
        NStructureResearchRequest(
            since=date(2026, 8, 19),
            through=date(2026, 8, 20),
            symbol="jm",
        )
    )

    assert loader.result.results[BarFrequency.M5].bars[-1].trading_day == date(
        2026, 8, 21
    )
    assert result.horizon_summary[5].sample_count == 0
    assert result.horizon_summary[8].sample_count == 0


def test_completion_event_prefix_is_invariant_to_future_same_segment_suffix() -> None:
    bars = _bars()
    request = NStructureResearchRequest(
        date(2026, 8, 18),
        date(2026, 8, 20),
        "jm",
    )
    base_service = NStructureResearchService(
        _FakeSegmentLoader(bars),
        products=("jm",),
        policy=load_n_structure_policy(),
    )
    prefix = base_service.completion_events(request)

    suffix = tuple(
        CanonicalBar(
            bar_end=bars[-1].bar_end + timedelta(minutes=5 * (index + 1)),
            trading_day=date(2026, 8, 21),
            open=Decimal("13"),
            high=Decimal("14"),
            low=Decimal("12"),
            close=Decimal("13"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )
        for index in range(8)
    )
    extended_bars = (*bars, *suffix)
    segment = ResolvedContractSegment("JM2701", date(2026, 8, 18), date(2026, 8, 21))
    result = MarketSeriesResult(
        request_identity={},
        bars=extended_bars,
        coverage=(extended_bars[0].bar_end, extended_bars[-1].bar_end),
        resolved_contract_segments=(segment,),
    )
    loader = _FakeSegmentLoader(bars)
    loader.result = ActualDominantResearchSeries(
        results=MappingProxyType({BarFrequency.M5: result}),
        segments=(segment,),
    )
    extended_service = NStructureResearchService(
        loader,
        products=("jm",),
        policy=load_n_structure_policy(),
    )
    extended = extended_service.completion_events(
        NStructureResearchRequest(date(2026, 8, 18), date(2026, 8, 21), "jm")
    )

    assert tuple(event for event in extended if event.trading_day <= date(2026, 8, 20)) == prefix


def test_misaligned_reducer_fact_maps_to_segment_identity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _bars()
    trace = evaluate_n_structure_segment(
        bars,
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 18),
        segment_end_trading_day=date(2026, 8, 20),
        policy=load_n_structure_policy(),
    )
    pattern = trace.patterns.patterns[0]
    misaligned_pattern = replace(
        pattern,
        completed_at=pattern.completed_at + timedelta(seconds=1),
    )
    misaligned_trace = replace(
        trace,
        patterns=replace(
            trace.patterns,
            patterns=(misaligned_pattern, *trace.patterns.patterns[1:]),
        ),
    )
    monkeypatch.setattr(
        research_module,
        "evaluate_n_structure_segment",
        lambda *args, **kwargs: misaligned_trace,
    )
    service = NStructureResearchService(
        _FakeSegmentLoader(bars),
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    with pytest.raises(
        NStructureSegmentIdentityError,
        match="^N_STRUCTURE_SEGMENT_IDENTITY_INVALID$",
    ):
        service.completion_events(
            NStructureResearchRequest(
                date(2026, 8, 18),
                date(2026, 8, 20),
                "jm",
            )
        )


def test_rank1_segment_change_resets_the_real_n_producer_chain() -> None:
    bars = _bars()
    segments = (
        ResolvedContractSegment(
            contract="JM2609",
            start_trading_day=date(2026, 8, 18),
            end_trading_day=date(2026, 8, 18),
        ),
        ResolvedContractSegment(
            contract="JM2701",
            start_trading_day=date(2026, 8, 19),
            end_trading_day=date(2026, 8, 20),
        ),
    )
    loaded_result = MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=segments,
    )
    loader = _FakeSegmentLoader(bars)
    loader.result = ActualDominantResearchSeries(
        results=MappingProxyType({BarFrequency.M5: loaded_result}),
        segments=segments,
    )
    service = NStructureResearchService(
        loader,
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    result = service.run(
        NStructureResearchRequest(
            since=date(2026, 8, 18),
            through=date(2026, 8, 20),
            symbol="jm",
        )
    )

    assert result.segment_count == 2
    assert result.evaluable_bar_count == len(bars)
    assert result.completed_n_counts == {"up": 0, "down": 0}
    assert all(
        evaluation.sample_count == 0
        for evaluation in result.horizon_summary.values()
    )
