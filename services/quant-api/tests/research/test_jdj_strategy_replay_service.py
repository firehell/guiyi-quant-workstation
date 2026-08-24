from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSegmentLoader,
)
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import MarketDataError
from app.research.jdj.jdj_context import JdjBarContext
from app.research.jdj.jdj_policy import load_jdj_policy
from app.research.jdj_strategy.engine import JdjActionKind, JdjReferenceReplay
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyProfileUnavailableError,
    JdjStrategyReplayRequest,
    JdjStrategyReplayService,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
)
from app.research.n_structure.n_structure_policy import load_n_structure_policy
from app.research.n_structure.n_structure_state import NStructureKind
from app.research.n_structure.n_structure_swing import NSwingPivot, NSwingPivotKind


_FIRST_START = date(2026, 8, 18)
_FIRST_END = date(2026, 8, 19)
_SECOND_START = date(2026, 8, 20)
_SECOND_END = date(2026, 8, 21)
_SEGMENTS_BY_SYMBOL = {
    "jm": (
        ResolvedContractSegment("JM2701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("JM2705", _SECOND_START, _SECOND_END),
    ),
    "rb": (
        ResolvedContractSegment("RB2701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("RB2705", _SECOND_START, _SECOND_END),
    ),
    "cf": (
        ResolvedContractSegment("CF701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("CF705", _SECOND_START, _SECOND_END),
    ),
    "sc": (
        ResolvedContractSegment("SC2701", _FIRST_START, _FIRST_END),
        ResolvedContractSegment("SC2705", _SECOND_START, _SECOND_END),
    ),
}
_SEGMENTS = _SEGMENTS_BY_SYMBOL["jm"]


def _day_bars(trading_day: date) -> tuple[CanonicalBar, ...]:
    start = datetime(
        trading_day.year,
        trading_day.month,
        trading_day.day,
        1,
        tzinfo=UTC,
    )
    values = (
        ("100", "101", "99", "100"),
        ("101", "105", "95", "101"),
        ("104", "130", "101", "104"),
        ("103", "110", "102", "108"),
        ("108", "109", "107", "108"),
    )
    return tuple(
        CanonicalBar(
            bar_end=start + timedelta(minutes=index),
            trading_day=trading_day,
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal("100"),
            turnover=None,
            open_interest=None,
        )
        for index, (open_, high, low, close) in enumerate(values)
    )


def _five_minute_bar(trading_day: date) -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(
            trading_day.year,
            trading_day.month,
            trading_day.day,
            1,
            5,
            tzinfo=UTC,
        ),
        trading_day=trading_day,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("108"),
        volume=Decimal("500"),
        turnover=None,
        open_interest=None,
    )


def _projected_segments(
    bars: Sequence[CanonicalBar],
    *,
    segments: Sequence[ResolvedContractSegment],
) -> tuple[ResolvedContractSegment, ...]:
    projected: list[ResolvedContractSegment] = []
    for segment in segments:
        days = tuple(
            bar.trading_day
            for bar in bars
            if segment.start_trading_day
            <= bar.trading_day
            <= segment.end_trading_day
        )
        if days:
            projected.append(
                ResolvedContractSegment(segment.contract, min(days), max(days))
            )
    return tuple(projected)


class _Reader:
    def __init__(
        self,
        *,
        segments_by_symbol: Mapping[
            str, tuple[ResolvedContractSegment, ...]
        ] = _SEGMENTS_BY_SYMBOL,
    ) -> None:
        days = (_FIRST_START, _FIRST_END, _SECOND_START, _SECOND_END)
        self.segments_by_symbol = dict(segments_by_symbol)
        self.bars = {
            BarFrequency.M1: tuple(bar for day in days for bar in _day_bars(day)),
            BarFrequency.M5: tuple(_five_minute_bar(day) for day in days),
        }
        self.calls: list[ActualDominantTradingDayQuery] = []
        self.multiplier_calls: list[tuple[str, str]] = []
        self.terminal_calls: list[str] = []

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        self.calls.append(request)
        bars = tuple(
            bar
            for bar in self.bars[request.frequency]
            if request.since <= bar.trading_day <= request.through
        )
        return MarketSeriesResult(
            request_identity={},
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end),
            resolved_contract_segments=_projected_segments(
                bars,
                segments=self.segments_by_symbol[request.symbol],
            ),
        )

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> SimpleNamespace:
        segment = next(
            segment
            for segment in self.segments_by_symbol[symbol]
            if segment.start_trading_day
            <= trading_day
            <= segment.end_trading_day
        )
        return SimpleNamespace(
            symbol=symbol,
            contract=segment.contract,
            start_trading_day=segment.start_trading_day,
            end_trading_day=segment.end_trading_day,
        )


def _contexts(
    bars_1m: Sequence[CanonicalBar],
    _bars_5m: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    **_kwargs: object,
) -> tuple[JdjBarContext, ...]:
    contexts: list[JdjBarContext] = []
    active_day: date | None = None
    for bar in bars_1m:
        if bar.trading_day != active_day:
            active_day = bar.trading_day
            contexts.append(
                JdjBarContext(
                    bar=bar,
                    ema20=Decimal("100"),
                    trend_kind=NStructureKind.UNDEFINED,
                    trend_snapshot_observed_at=None,
                    trend_epoch=None,
                    eligible_high_pivot=None,
                    eligible_low_pivot=None,
                )
            )
            continue
        confirmed_at = contexts[-1].bar.bar_end
        pivot_at = confirmed_at - timedelta(minutes=5)
        pivot = NSwingPivot(
            pivot_id=(
                f"{contract}:{segment_start_trading_day}:5m:0:high:"
                f"{pivot_at.isoformat()}"
            ),
            epoch=0,
            kind=NSwingPivotKind.HIGH,
            source_timeframe=BarFrequency.M5,
            pivot_time=pivot_at,
            confirmed_at=confirmed_at,
            price=Decimal("130"),
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
        )
        contexts.append(
            JdjBarContext(
                bar=bar,
                ema20=Decimal("100"),
                trend_kind=NStructureKind.BULL,
                trend_snapshot_observed_at=confirmed_at,
                trend_epoch=0,
                eligible_high_pivot=pivot,
                eligible_low_pivot=None,
            )
        )
    return tuple(contexts)


def _service(
    reader: _Reader,
    *,
    products: tuple[str, ...] = ("jm",),
    multiplier: object = Decimal("60"),
    terminal_failure: bool = False,
) -> JdjStrategyReplayService:
    def multiplier_for_contract(*, symbol: str, contract: str) -> Decimal:
        reader.multiplier_calls.append((symbol, contract))
        assert contract in {
            segment.contract for segment in reader.segments_by_symbol[symbol]
        }
        return multiplier  # type: ignore[return-value]

    def terminal_bar_ends(
        *,
        symbol: str,
        bars_1m: Sequence[CanonicalBar],
    ) -> dict[date, datetime]:
        reader.terminal_calls.append(symbol)
        assert symbol in reader.segments_by_symbol
        if terminal_failure:
            raise JdjStrategySessionIdentityError()
        return {
            day: max(bar.bar_end for bar in bars_1m if bar.trading_day == day)
            for day in {bar.trading_day for bar in bars_1m}
        }

    return JdjStrategyReplayService(
        ActualDominantResearchSegmentLoader(reader),
        products=products,
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
        contract_multiplier_for_contract=multiplier_for_contract,
        terminal_bar_ends_for_segment=terminal_bar_ends,
    )


def _request(
    *,
    since: date = _FIRST_END,
    through: date = _SECOND_END,
    series_kind: str = "actual_dominant",
    symbol: str = "jm",
    frequency: str = "1m",
) -> JdjStrategyReplayRequest:
    return JdjStrategyReplayRequest(
        series_kind=series_kind,
        symbol=symbol,
        frequency=frequency,
        since=since,
        through=through,
    )


def test_history_warms_true_segment_prefix_and_keeps_episode_state_per_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader()
    context_starts: list[tuple[str, date]] = []

    def record_contexts(*args: object, **kwargs: object) -> tuple[JdjBarContext, ...]:
        bars_1m = args[0]
        assert isinstance(bars_1m, Sequence)
        context_starts.append(
            (str(kwargs["contract"]), bars_1m[0].trading_day)  # type: ignore[index,union-attr]
        )
        return _contexts(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        record_contexts,
    )

    result = _service(reader).history(_request())

    assert result.reference_execution is True
    assert context_starts == [
        ("JM2701", _FIRST_START),
        ("JM2705", _SECOND_START),
    ]
    assert all(action.trading_day >= _FIRST_END for action in result.actions)
    assert {action.contract for action in result.actions} == {"JM2701", "JM2705"}
    assert all(
        action.segment_start_trading_day
        == (_FIRST_START if action.contract == "JM2701" else _SECOND_START)
        for action in result.actions
    )
    episode_contracts: dict[str, str] = {}
    for action in result.actions:
        if action.episode_id is not None:
            episode_contracts.setdefault(action.episode_id, action.contract)
            assert episode_contracts[action.episode_id] == action.contract
    assert {action.kind for action in result.actions} >= {
        JdjActionKind.ENTRY,
        JdjActionKind.EXIT,
    }
    assert any(call.since == _FIRST_START for call in reader.calls)


def test_history_passes_each_exact_loader_segment_to_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader()
    received: list[tuple[str, ResolvedContractSegment]] = []

    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        _contexts,
    )

    def record_replay(
        *,
        symbol: str,
        segment: ResolvedContractSegment,
        bars_1m: Sequence[CanonicalBar],
        contexts: Sequence[JdjBarContext],
        candidate_events: Sequence[object],
        contract_multiplier: Decimal,
        terminal_bar_end_by_day: dict[date, datetime],
        config: object,
    ) -> JdjReferenceReplay:
        assert bars_1m
        assert contexts
        assert contract_multiplier == Decimal("60")
        assert set(terminal_bar_end_by_day) == {
            bar.trading_day for bar in bars_1m
        }
        assert candidate_events is not None
        assert config is not None
        received.append((symbol, segment))
        return JdjReferenceReplay(actions=())

    monkeypatch.setattr(
        "app.research.jdj_strategy.service.run_jdj_reference_segment",
        record_replay,
    )

    result = _service(reader).history(_request())

    assert result.actions == ()
    assert received == [("jm", _SEGMENTS[0]), ("jm", _SEGMENTS[1])]


def test_history_prefix_is_identical_inside_a_longer_through_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        _contexts,
    )
    service = _service(_Reader())

    shorter = service.history(_request(through=_SECOND_START))
    longer = service.history(_request(through=_SECOND_END))

    assert shorter.actions == tuple(
        action
        for action in longer.actions
        if action.trading_day <= _SECOND_START
    )


def test_request_accepts_normalized_symbol_without_membership_lookup() -> None:
    request = _request(symbol=" RB ")

    assert request.symbol == "rb"


def test_service_replays_an_admitted_non_jm_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        _contexts,
    )
    reader = _Reader()

    result = _service(reader, products=("jm", "rb")).history(
        _request(symbol="rb")
    )

    assert result.request.symbol == "rb"
    assert result.actions
    assert all(action.contract.startswith("RB") for action in result.actions)


def test_service_rejects_non_admitted_product_before_historical_load() -> None:
    reader = _Reader()
    service = _service(reader, products=("jm",))

    with pytest.raises(
        JdjStrategyProfileUnavailableError,
        match="^JDJ_STRATEGY_PROFILE_UNAVAILABLE$",
    ):
        service.history(_request(symbol="rb"))

    assert reader.calls == []


def test_one_service_replays_symbols_sequentially_without_cached_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        _contexts,
    )
    reader = _Reader(segments_by_symbol=_SEGMENTS_BY_SYMBOL)
    service = _service(
        reader,
        products=("jm", "rb", "cf", "sc"),
    )

    for symbol in ("jm", "rb", "cf", "sc"):
        result = service.history(_request(symbol=symbol))
        assert result.request.symbol == symbol
        assert result.actions
        assert all(
            action.contract.startswith(symbol.upper())
            for action in result.actions
        )

    assert list(dict.fromkeys(call.symbol for call in reader.calls)) == [
        "jm",
        "rb",
        "cf",
        "sc",
    ]
    assert list(dict.fromkeys(symbol for symbol, _contract in reader.multiplier_calls)) == [
        "jm",
        "rb",
        "cf",
        "sc",
    ]
    assert list(dict.fromkeys(reader.terminal_calls)) == ["jm", "rb", "cf", "sc"]


@pytest.mark.parametrize(
    ("series_kind", "symbol", "frequency"),
    (
        ("continuous", "jm", "1m"),
        ("actual_dominant", "jm", "5m"),
        ("actual_dominant", "", "1m"),
        ("actual_dominant", "   ", "1m"),
        ("actual_dominant", None, "1m"),
    ),
)
def test_request_rejects_invalid_static_shape(
    series_kind: str,
    symbol: object,
    frequency: str,
) -> None:
    with pytest.raises(
        JdjStrategyProfileUnavailableError,
        match="^JDJ_STRATEGY_PROFILE_UNAVAILABLE$",
    ):
        _request(
            series_kind=series_kind,
            symbol=symbol,  # type: ignore[arg-type]
            frequency=frequency,
        )


@pytest.mark.parametrize(
    ("since", "through"),
    (
        (_SECOND_END, _FIRST_START),
        (datetime(2026, 8, 19, tzinfo=UTC), _SECOND_END),
        (_FIRST_END, datetime(2026, 8, 21, tzinfo=UTC)),
    ),
)
def test_request_rejects_invalid_date_window(
    since: date,
    through: date,
) -> None:
    with pytest.raises(
        JdjStrategyProfileUnavailableError,
        match="^JDJ_STRATEGY_PROFILE_UNAVAILABLE$",
    ):
        _request(since=since, through=through)


@pytest.mark.parametrize(
    "products",
    (
        [],
        (),
        ("JM",),
        (" jm",),
        ("jm", "jm"),
        ("jm", 1),
    ),
)
def test_service_rejects_invalid_product_admission_contract(
    products: object,
) -> None:
    with pytest.raises(
        JdjStrategyContextInvalidError,
        match="^JDJ_STRATEGY_CONTEXT_INVALID$",
    ):
        _service(_Reader(), products=products)  # type: ignore[arg-type]


@pytest.mark.parametrize("multiplier", (None, 0, Decimal("0"), Decimal("NaN")))
def test_missing_or_invalid_trusted_multiplier_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    multiplier: object,
) -> None:
    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        _contexts,
    )

    with pytest.raises(
        JdjStrategyContextInvalidError,
        match="^JDJ_STRATEGY_CONTEXT_INVALID$",
    ):
        _service(_Reader(), multiplier=multiplier).history(_request())


def test_missing_session_terminal_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.jdj_strategy.service.build_jdj_context_series",
        _contexts,
    )

    with pytest.raises(
        JdjStrategySessionIdentityError,
        match="^JDJ_STRATEGY_SESSION_IDENTITY_INVALID$",
    ):
        _service(_Reader(), terminal_failure=True).history(_request())


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (
            ActualDominantResearchSegmentIdentityError(),
            JdjStrategySegmentIdentityError,
        ),
        (MarketDataError("private source detail"), JdjStrategyContextInvalidError),
    ),
)
def test_loader_failures_map_to_stable_redacted_strategy_errors(
    failure: Exception,
    expected: type[Exception],
) -> None:
    class FailingLoader:
        def load(self, **_kwargs: object) -> object:
            raise failure

    service = JdjStrategyReplayService(
        FailingLoader(),  # type: ignore[arg-type]
        products=("jm",),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
        contract_multiplier_for_contract=lambda **_kwargs: Decimal("60"),
        terminal_bar_ends_for_segment=lambda **_kwargs: {},
    )

    with pytest.raises(expected) as captured:
        service.history(_request())

    assert captured.value.__cause__ is None
    assert "private" not in str(captured.value)
