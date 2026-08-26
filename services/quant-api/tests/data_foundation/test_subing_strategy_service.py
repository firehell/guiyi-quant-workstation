from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from types import MappingProxyType

import pytest

from app.market_data.domain import BarFrequency, ResolvedContractSegment, SeriesKind
from app.market_data.market_data_service import MarketDataError
from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyDirection,
    SubingStrategyPositionState,
)
from app.market_data.subing_strategy.cache import (
    SubingStrategyCacheError,
)
from app.market_data.subing_strategy.engine import SubingStrategySegmentResult
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_strategy.service import (
    _combine_cache_states,
    SubingStrategyHistoricalProjectionService,
    SubingStrategyActiveProductError,
    SubingStrategyHistoricalRequest,
    SubingStrategySegmentIdentityError,
    SubingStrategySourceUnavailableError,
)

from research.subing_lifecycle_fixtures import _accepted_calibration
from research.subing_strategy_fixtures import (
    FakeDirectionContextResolver,
    FakeSegmentLoader,
    loaded_series,
)
from research.test_subing_strategy_engine import (
    CONTRACT,
    SEGMENT_START,
    _bar,
    _candidate,
    _context,
    _frame,
    _run,
)


@pytest.mark.parametrize(
    ("states", "expected"),
    (
        (("hit", "hit"), "hit"),
        (("miss", "miss"), "miss"),
        (("hit", "miss"), "mixed"),
        (("hit", "unavailable"), "unavailable"),
        ((), "unavailable"),
    ),
)
def test_cache_state_combines_all_segment_results(
    states: tuple[str, ...],
    expected: str,
) -> None:
    assert _combine_cache_states(states) == expected


def _request(*, since: date, through: date) -> SubingStrategyHistoricalRequest:
    return SubingStrategyHistoricalRequest(
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        symbol="jm",
        frequency=BarFrequency.M15,
        since=since,
        through=through,
    )


def _closed_result():
    first = _bar(1)
    second = _bar(2, close="98")
    third = _bar(3, open_price="97", gap_days=2)
    frames = (
        _frame(
            first,
            previous=None,
            candidates=(_candidate(first, direction=SubingDirection.LONG),),
        ),
        _frame(second, previous=first, ema21="99"),
        _frame(third, previous=second),
    )
    return frames, _run(frames)


def _service(loader, resolver) -> SubingStrategyHistoricalProjectionService:
    return SubingStrategyHistoricalProjectionService(
        loader,
        products=("jm",),
        direction_context_resolver=resolver,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )


def test_entry_left_of_window_and_exit_inside_returns_complete_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames, segment_result = _closed_result()
    bars = tuple(frame.bar for frame in frames)
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, bars[-1].trading_day)
    loader = FakeSegmentLoader(
        loaded_series(segments=(segment,), bars_5m=bars, bars_15m=bars)
    )
    contexts = {
        day: _context(frame.bar, SubingStrategyDirection.LONG_ONLY)
        for day, frame in {frame.bar.trading_day: frame for frame in frames}.items()
    }
    resolver = FakeDirectionContextResolver(contexts)
    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        lambda **_kwargs: segment_result,
    )

    result = _service(loader, resolver).history(
        _request(
            since=SEGMENT_START + timedelta(days=1),
            through=bars[-1].trading_day,
        )
    )

    episode = result.episodes[0]
    assert episode.entry_action.trading_day < result.request.since
    assert episode.exit_action is not None
    assert episode.exit_action.trading_day >= result.request.since
    assert tuple(action.kind for action in result.actions) == (
        SubingStrategyActionKind.CLOSE_LONG,
    )


def test_nonterminal_through_preserves_open_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = (
        _frame(
            _bar(1),
            previous=None,
            candidates=(_candidate(_bar(1), direction=SubingDirection.LONG),),
        ),
        _frame(_bar(2), previous=_bar(1)),
    )
    segment_result = _run(frames)
    segment = ResolvedContractSegment(
        CONTRACT,
        SEGMENT_START,
        SEGMENT_START + timedelta(days=5),
    )
    bars = tuple(frame.bar for frame in frames)
    loaded = loaded_series(segments=(segment,), bars_5m=bars, bars_15m=bars)
    observed_prefix = ResolvedContractSegment(
        CONTRACT,
        SEGMENT_START,
        SEGMENT_START,
    )
    loaded = replace(
        loaded,
        results=MappingProxyType(
            {
                frequency: replace(
                    result,
                    resolved_contract_segments=(observed_prefix,),
                )
                for frequency, result in loaded.results.items()
            }
        ),
    )
    loader = FakeSegmentLoader(loaded)
    resolver = FakeDirectionContextResolver(
        {SEGMENT_START: _context(_bar(1), SubingStrategyDirection.LONG_ONLY)}
    )
    terminals: list[object] = []

    def replay(**kwargs):
        terminals.append(kwargs["terminal_bar_end"])
        return segment_result

    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        replay,
    )

    result = _service(loader, resolver).history(
        _request(since=SEGMENT_START, through=SEGMENT_START)
    )

    assert terminals == [None]
    assert result.episodes[0].exit_action is None
    assert result.segment_summaries[0].final_position is SubingStrategyPositionState.LONG


def test_new_contract_segment_starts_flat(monkeypatch: pytest.MonkeyPatch) -> None:
    first = ResolvedContractSegment("JM2701", SEGMENT_START, SEGMENT_START)
    second_day = SEGMENT_START + timedelta(days=1)
    second = ResolvedContractSegment("JM2705", second_day, second_day)
    bars = (_bar(1), _bar(2, gap_days=1))
    loader = FakeSegmentLoader(
        loaded_series(segments=(first, second), bars_5m=bars, bars_15m=bars)
    )
    resolver = FakeDirectionContextResolver(
        {
            bars[0].trading_day: _context(
                bars[0],
                SubingStrategyDirection.NO_NEW_ENTRY,
            ),
            bars[1].trading_day: replace(
                _context(bars[1], SubingStrategyDirection.NO_NEW_ENTRY),
                # The target is the first day of JM2705, while Daily Watch V2
                # causally reads the previous common trading day on JM2701.
                physical_contract="JM2701",
            ),
        }
    )
    empty = SubingStrategySegmentResult(
        actions=(),
        episodes=(),
        consumed_opportunity_ids=(),
        canceled_pending=(),
        pending_action=None,
        final_position=SubingStrategyPositionState.FLAT,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        lambda **_kwargs: empty,
    )

    result = _service(loader, resolver).history(
        _request(since=SEGMENT_START, through=second_day)
    )

    assert len(result.segment_summaries) == 2
    assert all(
        summary.initial_position is SubingStrategyPositionState.FLAT
        for summary in result.segment_summaries
    )


def test_loader_failure_maps_to_typed_source_error() -> None:
    service = _service(
        FakeSegmentLoader(MarketDataError("SOURCE_UNAVAILABLE")),
        FakeDirectionContextResolver(MappingProxyType({})),
    )

    with pytest.raises(SubingStrategySourceUnavailableError):
        service.history(_request(since=SEGMENT_START, through=SEGMENT_START))


def test_loader_identity_failure_maps_to_typed_segment_error() -> None:
    service = _service(
        FakeSegmentLoader(ActualDominantResearchSegmentIdentityError()),
        FakeDirectionContextResolver(MappingProxyType({})),
    )

    with pytest.raises(SubingStrategySegmentIdentityError):
        service.history(_request(since=SEGMENT_START, through=SEGMENT_START))


def test_context_unavailable_day_remains_response_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bar = _bar(1)
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SEGMENT_START)
    loader = FakeSegmentLoader(
        loaded_series(segments=(segment,), bars_5m=(bar,), bars_15m=(bar,))
    )
    unavailable = replace(
        _context(bar, SubingStrategyDirection.LONG_ONLY),
        direction=SubingStrategyDirection.UNAVAILABLE,
        reason_codes=("D1_HISTORY_INSUFFICIENT",),
        daily_bar_end=None,
    )
    resolver = FakeDirectionContextResolver({SEGMENT_START: unavailable})
    empty = SubingStrategySegmentResult(
        actions=(),
        episodes=(),
        consumed_opportunity_ids=(),
        canceled_pending=(),
        pending_action=None,
        final_position=SubingStrategyPositionState.FLAT,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        lambda **_kwargs: empty,
    )

    result = _service(loader, resolver).history(
        _request(since=SEGMENT_START, through=SEGMENT_START)
    )

    assert result.context_unavailable == (unavailable,)
    assert result.actions == ()


def test_service_rejects_symbol_outside_active_products() -> None:
    service = _service(
        FakeSegmentLoader(MarketDataError("SHOULD_NOT_READ")),
        FakeDirectionContextResolver(MappingProxyType({})),
    )

    with pytest.raises(SubingStrategyActiveProductError):
        service.history(
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol="rb",
                frequency=BarFrequency.M15,
                since=SEGMENT_START,
                through=SEGMENT_START,
            )
        )


@pytest.mark.parametrize("failure", ("read", "write"))
def test_cache_failure_recomputes_without_changing_result(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    bar = _bar(1)
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SEGMENT_START)
    loader = FakeSegmentLoader(
        loaded_series(segments=(segment,), bars_5m=(bar,), bars_15m=(bar,))
    )
    resolver = FakeDirectionContextResolver(
        {SEGMENT_START: _context(bar, SubingStrategyDirection.NO_NEW_ENTRY)}
    )
    expected = SubingStrategySegmentResult(
        actions=(),
        episodes=(),
        consumed_opportunity_ids=(),
        canceled_pending=(),
        pending_action=None,
        final_position=SubingStrategyPositionState.FLAT,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        lambda **_kwargs: expected,
    )

    class FailingCache:
        available = True

        def read(self, _identity):
            if failure == "read":
                raise SubingStrategyCacheError()
            return None

        def write(self, _identity, _projection):
            if failure == "write":
                raise SubingStrategyCacheError()

    service = SubingStrategyHistoricalProjectionService(
        loader,
        products=("jm",),
        direction_context_resolver=resolver,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        cache=FailingCache(),
    )

    result = service.history(
        _request(since=SEGMENT_START, through=SEGMENT_START)
    )

    assert result.actions == expected.actions
    assert result.episodes == expected.episodes
    assert result.cache_state == "unavailable"


def test_cache_identity_uses_current_lifecycle_formula_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bar = _bar(1)
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SEGMENT_START)
    loader = FakeSegmentLoader(
        loaded_series(segments=(segment,), bars_5m=(bar,), bars_15m=(bar,))
    )
    resolver = FakeDirectionContextResolver(
        {SEGMENT_START: _context(bar, SubingStrategyDirection.NO_NEW_ENTRY)}
    )
    empty = SubingStrategySegmentResult(
        actions=(),
        episodes=(),
        consumed_opportunity_ids=(),
        canceled_pending=(),
        pending_action=None,
        final_position=SubingStrategyPositionState.FLAT,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        lambda **_kwargs: empty,
    )

    identities = []

    class CapturingCache:
        available = True

        def read(self, identity):
            identities.append(identity)
            return None

        def write(self, _identity, _projection):
            return None

    service = SubingStrategyHistoricalProjectionService(
        loader,
        products=("jm",),
        direction_context_resolver=resolver,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        cache=CapturingCache(),
    )

    service.history(_request(since=SEGMENT_START, through=SEGMENT_START))

    assert len(identities) == 1
    assert (
        identities[0].lifecycle_formula_version
        == "subing_lifecycle_v2_structure_binding_v1"
    )


@pytest.mark.parametrize(
    ("series_kind", "frequency"),
    (
        (SeriesKind.CONTINUOUS, BarFrequency.M15),
        (SeriesKind.ACTUAL_DOMINANT, BarFrequency.M5),
    ),
)
def test_request_supports_only_actual_dominant_15m(
    series_kind: SeriesKind,
    frequency: BarFrequency,
) -> None:
    with pytest.raises(ValueError):
        SubingStrategyHistoricalRequest(
            series_kind=series_kind,
            symbol="jm",
            frequency=frequency,
            since=SEGMENT_START,
            through=SEGMENT_START,
        )
