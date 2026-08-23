from __future__ import annotations

from collections.abc import Sequence
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
from app.research.jdj_strategy.engine import JdjActionKind
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
_SEGMENTS = (
    ResolvedContractSegment("JM2701", _FIRST_START, _FIRST_END),
    ResolvedContractSegment("JM2705", _SECOND_START, _SECOND_END),
)


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
) -> tuple[ResolvedContractSegment, ...]:
    projected: list[ResolvedContractSegment] = []
    for segment in _SEGMENTS:
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
    def __init__(self) -> None:
        days = (_FIRST_START, _FIRST_END, _SECOND_START, _SECOND_END)
        self.bars = {
            BarFrequency.M1: tuple(bar for day in days for bar in _day_bars(day)),
            BarFrequency.M5: tuple(_five_minute_bar(day) for day in days),
        }
        self.calls: list[ActualDominantTradingDayQuery] = []

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
            resolved_contract_segments=_projected_segments(bars),
        )

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> SimpleNamespace:
        assert symbol == "jm"
        segment = next(
            segment
            for segment in _SEGMENTS
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
    multiplier: object = Decimal("60"),
    terminal_failure: bool = False,
) -> JdjStrategyReplayService:
    def multiplier_for_contract(*, symbol: str, contract: str) -> Decimal:
        assert symbol == "jm"
        assert contract in {"JM2701", "JM2705"}
        return multiplier  # type: ignore[return-value]

    def terminal_bar_ends(
        *,
        symbol: str,
        bars_1m: Sequence[CanonicalBar],
    ) -> dict[date, datetime]:
        assert symbol == "jm"
        if terminal_failure:
            raise JdjStrategySessionIdentityError()
        return {
            day: max(bar.bar_end for bar in bars_1m if bar.trading_day == day)
            for day in {bar.trading_day for bar in bars_1m}
        }

    return JdjStrategyReplayService(
        ActualDominantResearchSegmentLoader(reader),
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


@pytest.mark.parametrize(
    ("series_kind", "symbol", "frequency"),
    (
        ("continuous", "jm", "1m"),
        ("actual_dominant", "rb", "1m"),
        ("actual_dominant", "jm", "5m"),
    ),
)
def test_only_frozen_jm_actual_dominant_1m_profile_is_accepted(
    series_kind: str,
    symbol: str,
    frequency: str,
) -> None:
    with pytest.raises(
        JdjStrategyProfileUnavailableError,
        match="^JDJ_STRATEGY_PROFILE_UNAVAILABLE$",
    ):
        _request(
            series_kind=series_kind,
            symbol=symbol,
            frequency=frequency,
        )


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
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
        contract_multiplier_for_contract=lambda **_kwargs: Decimal("60"),
        terminal_bar_ends_for_segment=lambda **_kwargs: {},
    )

    with pytest.raises(expected) as captured:
        service.history(_request())

    assert captured.value.__cause__ is None
    assert "private" not in str(captured.value)
