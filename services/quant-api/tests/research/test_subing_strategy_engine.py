from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_ema_trend import PriceSide
from app.market_data.subing_lifecycle import ConfirmationSource, SubingOpportunityKey
from app.market_data.subing_research import (
    MacdCross,
    SubingDirection,
    SubingFactorSnapshot,
)
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyDirection,
    SubingStrategyEpisodeState,
    SubingStrategyFillBasis,
    SubingStrategyPositionState,
    subing_opportunity_key_id,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyDirectionContext,
)
from app.market_data.subing_strategy.engine import (
    SubingStrategyDecisionFrame,
    run_subing_strategy_segment,
)
from app.market_data.subing_strategy.entry_projection import (
    SubingStrategyEntryCandidate,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_structure import (
    ConfirmedPivot,
    PivotKind,
    _canonical_pivot_id,
)


SEGMENT_START = date(2026, 8, 3)
SOURCE_DAY = date(2026, 7, 31)
CONTRACT = "JM2701"
START = datetime(2026, 8, 3, 1, tzinfo=UTC)
POLICY = load_subing_strategy_policy()


def _bar(
    index: int,
    *,
    open_price: str = "100",
    close: str = "100",
    high: str = "105",
    low: str = "95",
    gap_days: int = 0,
) -> CanonicalBar:
    return CanonicalBar(
        bar_end=START + timedelta(minutes=15 * index, days=gap_days),
        trading_day=SEGMENT_START + timedelta(days=gap_days),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )


def _factor(
    bar: CanonicalBar,
    *,
    ema21: str = "99",
    cross: MacdCross = MacdCross.NONE,
    cross_level: str = "0",
) -> SubingFactorSnapshot:
    ema = Decimal(ema21)
    return SubingFactorSnapshot(
        timeframe=BarFrequency.M15,
        bar_end=bar.bar_end,
        trading_day=bar.trading_day,
        contract=CONTRACT,
        segment_start_trading_day=SEGMENT_START,
        bar_source="canonical",
        close=bar.close,
        ema21=ema,
        price_side=(
            PriceSide.ABOVE
            if bar.close > ema
            else PriceSide.BELOW
            if bar.close < ema
            else PriceSide.EQUAL
        ),
        slope_5_raw=Decimal("1"),
        slope_10_raw=Decimal("1"),
        slope_5_bps_per_bar=Decimal("1"),
        slope_10_bps_per_bar=Decimal("1"),
        macd_dif=Decimal("1"),
        macd_dea=Decimal("1"),
        macd_histogram=Decimal("0"),
        macd_cross=cross,
        macd_cross_level=Decimal(cross_level),
        macd_zero_distance_abs=Decimal("1"),
        macd_zero_distance_bps=Decimal("1"),
        volume=bar.volume,
        previous_volume=bar.volume,
        volume_ratio_prev=Decimal("1"),
    )


def _context(
    bar: CanonicalBar,
    direction: SubingStrategyDirection,
) -> SubingStrategyDirectionContext:
    return SubingStrategyDirectionContext(
        symbol="jm",
        target_trading_day=bar.trading_day,
        source_trading_day=SOURCE_DAY,
        direction=direction,
        reason_codes=("D1_H1_ALIGNED",),
        daily_bar_end=START - timedelta(days=1),
        hourly_bar_end=START - timedelta(hours=1),
        physical_contract=CONTRACT,
    )


def _pivot(direction: SubingDirection, price: str) -> ConfirmedPivot:
    kind = PivotKind.LOW if direction is SubingDirection.LONG else PivotKind.HIGH
    pivot_time = START - timedelta(minutes=30)
    return ConfirmedPivot(
        pivot_id=_canonical_pivot_id(
            contract=CONTRACT,
            segment_start_trading_day=SEGMENT_START,
            source_timeframe=BarFrequency.M5,
            kind=kind,
            pivot_time=pivot_time,
        ),
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_time,
        confirmed_at=START - timedelta(minutes=15),
        price=Decimal(price),
        contract=CONTRACT,
        segment_start_trading_day=SEGMENT_START,
    )


def _candidate(
    frame_bar: CanonicalBar,
    *,
    direction: SubingDirection,
    suffix: str = "a",
    pivot: ConfirmedPivot | None = None,
) -> SubingStrategyEntryCandidate:
    key = SubingOpportunityKey(
        policy_id="subing_lifecycle_v2_research_v1",
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=SEGMENT_START,
        direction=direction,
        origin_at=frame_bar.bar_end - timedelta(minutes=5),
    )
    if suffix != "a":
        object.__setattr__(
            key, "origin_at", key.origin_at - timedelta(seconds=ord(suffix))
        )
    return SubingStrategyEntryCandidate(
        opportunity_key=key,
        opportunity_id=subing_opportunity_key_id(key),
        direction=direction,
        confirmation_source=ConfirmationSource.FORMAL_V1,
        confirmed_at=frame_bar.bar_end - timedelta(minutes=5),
        decision_bar_end=frame_bar.bar_end,
        bound_reference_pivot=pivot,
    )


def _frame(
    bar: CanonicalBar,
    *,
    previous: CanonicalBar | None,
    context: SubingStrategyDirection = SubingStrategyDirection.LONG_ONLY,
    candidates: tuple[SubingStrategyEntryCandidate, ...] = (),
    ema21: str = "99",
    cross: MacdCross = MacdCross.NONE,
    cross_level: str = "0",
) -> SubingStrategyDecisionFrame:
    return SubingStrategyDecisionFrame(
        bar=bar,
        previous_bar=previous,
        factor=_factor(bar, ema21=ema21, cross=cross, cross_level=cross_level),
        direction_context=_context(bar, context),
        entry_candidates=candidates,
    )


def _entry_frames(
    *,
    direction: SubingDirection = SubingDirection.LONG,
    pivot: ConfirmedPivot | None = None,
    exit_bar: CanonicalBar | None = None,
    exit_ema: str = "99",
    exit_cross: MacdCross = MacdCross.NONE,
    exit_cross_level: str = "0",
) -> tuple[SubingStrategyDecisionFrame, ...]:
    first = _bar(1)
    second = exit_bar or _bar(2, open_price="100.5")
    third = _bar(3, open_price="101")
    context = (
        SubingStrategyDirection.LONG_ONLY
        if direction is SubingDirection.LONG
        else SubingStrategyDirection.SHORT_ONLY
    )
    return (
        _frame(
            first,
            previous=None,
            context=context,
            candidates=(_candidate(first, direction=direction, pivot=pivot),),
        ),
        _frame(
            second,
            previous=first,
            context=context,
            ema21=exit_ema,
            cross=exit_cross,
            cross_level=exit_cross_level,
        ),
        _frame(third, previous=second, context=context),
    )


def _run(
    frames: tuple[SubingStrategyDecisionFrame, ...],
    *,
    first_1m_bars: tuple[CanonicalBar, ...] | None = None,
    terminal_bar_end: datetime | None = None,
):
    if first_1m_bars is None:
        first_1m_bars = tuple(
            CanonicalBar(
                bar_end=frame.bar.bar_end - timedelta(minutes=14),
                trading_day=frame.bar.trading_day,
                open=frame.bar.open,
                high=frame.bar.open,
                low=frame.bar.open,
                close=frame.bar.open,
                volume=frame.bar.volume,
                turnover=None,
                open_interest=frame.bar.open_interest,
            )
            for frame in frames
        )
    return run_subing_strategy_segment(
        symbol="jm",
        contract=CONTRACT,
        segment_start=SEGMENT_START,
        frames=frames,
        first_1m_bars=first_1m_bars,
        policy=POLICY,
        terminal_bar_end=terminal_bar_end,
    )


def test_long_entry_decides_on_close_and_fills_next_open() -> None:
    result = _run(_entry_frames()[:2])
    action = result.actions[0]

    assert action.kind is SubingStrategyActionKind.OPEN_LONG
    assert action.decision_at == _bar(1).bar_end
    assert action.effective_open_at == _bar(2).bar_end - timedelta(minutes=15)
    assert action.effective_bar_end == _bar(2).bar_end
    assert action.reference_price == Decimal("100.5")
    assert action.fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN


def test_unaligned_context_consumes_but_does_not_enter_old_opportunity() -> None:
    first, second = _bar(1), _bar(2)
    candidate = _candidate(first, direction=SubingDirection.LONG)
    frames = (
        _frame(
            first,
            previous=None,
            context=SubingStrategyDirection.NO_NEW_ENTRY,
            candidates=(candidate,),
        ),
        _frame(second, previous=first),
    )

    result = _run(frames)

    assert result.actions == ()
    assert result.consumed_opportunity_ids == (candidate.opportunity_id,)


@pytest.mark.parametrize(
    ("direction", "bar", "ema", "cross", "level", "pivot", "reason"),
    (
        (
            SubingDirection.LONG,
            _bar(2, close="98"),
            "99",
            MacdCross.NONE,
            "0",
            None,
            "EMA21_BREACH_LONG",
        ),
        (
            SubingDirection.LONG,
            _bar(2, close="94", high="100", low="93"),
            "90",
            MacdCross.NONE,
            "0",
            None,
            "PREVIOUS_BAR_LOW_BREACH",
        ),
        (
            SubingDirection.LONG,
            _bar(2, close="97"),
            "90",
            MacdCross.NONE,
            "0",
            _pivot(SubingDirection.LONG, "98"),
            "BOUND_LOW_PIVOT_BREACH",
        ),
        (
            SubingDirection.LONG,
            _bar(2),
            "99",
            MacdCross.DEAD,
            "1",
            None,
            "MACD_HIGH_DEAD_CROSS",
        ),
        (
            SubingDirection.SHORT,
            _bar(2, close="102"),
            "101",
            MacdCross.NONE,
            "0",
            None,
            "EMA21_BREACH_SHORT",
        ),
        (
            SubingDirection.SHORT,
            _bar(2, close="106", high="107"),
            "110",
            MacdCross.NONE,
            "0",
            None,
            "PREVIOUS_BAR_HIGH_BREACH",
        ),
        (
            SubingDirection.SHORT,
            _bar(2, close="103"),
            "110",
            MacdCross.NONE,
            "0",
            _pivot(SubingDirection.SHORT, "102"),
            "BOUND_HIGH_PIVOT_BREACH",
        ),
        (
            SubingDirection.SHORT,
            _bar(2),
            "101",
            MacdCross.GOLDEN,
            "-1",
            None,
            "MACD_LOW_GOLDEN_CROSS",
        ),
    ),
)
def test_each_exit_family_closes_full_position(
    direction: SubingDirection,
    bar: CanonicalBar,
    ema: str,
    cross: MacdCross,
    level: str,
    pivot: ConfirmedPivot | None,
    reason: str,
) -> None:
    result = _run(
        _entry_frames(
            direction=direction,
            pivot=pivot,
            exit_bar=bar,
            exit_ema=ema,
            exit_cross=cross,
            exit_cross_level=level,
        )
    )
    close = result.actions[-1]

    assert close.kind in {
        SubingStrategyActionKind.CLOSE_LONG,
        SubingStrategyActionKind.CLOSE_SHORT,
    }
    assert reason in close.reason_codes
    assert result.episodes[-1].state is SubingStrategyEpisodeState.CLOSED


def test_multiple_exit_reasons_preserve_policy_order() -> None:
    pivot = _pivot(SubingDirection.LONG, "101")
    exit_bar = _bar(2, close="94", high="100", low="93")
    result = _run(
        _entry_frames(
            pivot=pivot,
            exit_bar=exit_bar,
            exit_ema="99",
            exit_cross=MacdCross.DEAD,
            exit_cross_level="1",
        )
    )

    assert result.actions[-1].reason_codes == (
        "EMA21_BREACH_LONG",
        "PREVIOUS_BAR_LOW_BREACH",
        "BOUND_LOW_PIVOT_BREACH",
        "MACD_HIGH_DEAD_CROSS",
    )


def test_confirmations_while_holding_are_ignored_and_consumed() -> None:
    first, second, third = _bar(1), _bar(2), _bar(3)
    initial = _candidate(first, direction=SubingDirection.LONG)
    same = _candidate(second, direction=SubingDirection.LONG, suffix="b")
    opposite = _candidate(second, direction=SubingDirection.SHORT, suffix="c")
    frames = (
        _frame(first, previous=None, candidates=(initial,)),
        _frame(second, previous=first, candidates=(same, opposite)),
        _frame(third, previous=second),
    )

    result = _run(frames)

    assert tuple(action.kind for action in result.actions) == (
        SubingStrategyActionKind.OPEN_LONG,
    )
    assert result.consumed_opportunity_ids == (
        initial.opportunity_id,
        same.opportunity_id,
        opposite.opportunity_id,
    )
    assert result.final_position is SubingStrategyPositionState.LONG


def test_context_change_does_not_exit_an_existing_position() -> None:
    first, second = _bar(1), _bar(2)
    frames = (
        _frame(
            first,
            previous=None,
            candidates=(_candidate(first, direction=SubingDirection.LONG),),
        ),
        _frame(
            second,
            previous=first,
            context=SubingStrategyDirection.SHORT_ONLY,
        ),
    )

    result = _run(frames)

    assert tuple(action.kind for action in result.actions) == (
        SubingStrategyActionKind.OPEN_LONG,
    )
    assert result.final_position is SubingStrategyPositionState.LONG


def test_rollover_first_day_accepts_previous_source_contract_context() -> None:
    bar = _bar(1)
    frame = replace(
        _frame(bar, previous=None),
        direction_context=replace(
            _context(bar, SubingStrategyDirection.NO_NEW_ENTRY),
            physical_contract="JM2612",
        ),
    )

    result = _run((frame,))

    assert result.actions == ()
    assert result.final_position is SubingStrategyPositionState.FLAT


def test_one_opportunity_enters_at_most_once_after_it_closes() -> None:
    first = _bar(1)
    second = _bar(2, close="98")
    third = _bar(3, open_price="97")
    fourth = _bar(4, open_price="99")
    initial = _candidate(first, direction=SubingDirection.LONG)
    duplicate = replace(initial, decision_bar_end=third.bar_end)
    frames = (
        _frame(first, previous=None, candidates=(initial,)),
        _frame(second, previous=first, ema21="99"),
        _frame(third, previous=second, candidates=(duplicate,)),
        _frame(fourth, previous=third),
    )

    result = _run(frames)

    assert tuple(action.kind for action in result.actions) == (
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.CLOSE_LONG,
    )
    assert result.consumed_opportunity_ids == (initial.opportunity_id,)


def test_missing_pivot_disables_only_structure_exit() -> None:
    result = _run(_entry_frames()[:2])

    assert result.actions[0].kind is SubingStrategyActionKind.OPEN_LONG
    assert result.episodes[0].structure_exit_available is False


def test_entry_action_and_episode_preserve_lifecycle_bound_pivot() -> None:
    pivot = _pivot(SubingDirection.LONG, "98")

    result = _run(_entry_frames(pivot=pivot)[:2])

    assert result.actions[0].bound_reference_pivot is pivot
    assert result.episodes[0].entry_action.bound_reference_pivot is pivot
    assert result.episodes[0].structure_exit_available is True


def test_ordinary_cutoff_preserves_pending_without_close_fallback() -> None:
    first = _bar(1, close="100")
    frames = (
        _frame(
            first,
            previous=None,
            candidates=(_candidate(first, direction=SubingDirection.LONG),),
        ),
    )

    result = _run(frames)

    assert result.actions == ()
    assert result.pending_action is not None
    assert result.canceled_pending == ()


def test_ordinary_cutoff_preserves_pending_close_and_open_episode() -> None:
    frames = _entry_frames(exit_bar=_bar(2, close="98"), exit_ema="99")[:2]

    result = _run(frames)

    assert tuple(action.kind for action in result.actions) == (
        SubingStrategyActionKind.OPEN_LONG,
    )
    assert result.pending_action is not None
    assert result.pending_action.kind is SubingStrategyActionKind.CLOSE_LONG
    assert result.episodes[0].state is SubingStrategyEpisodeState.OPEN
    assert result.final_position is SubingStrategyPositionState.LONG


def test_authoritative_terminal_cancels_pending_open() -> None:
    first = _bar(1)
    frames = (
        _frame(
            first,
            previous=None,
            candidates=(_candidate(first, direction=SubingDirection.LONG),),
        ),
    )

    result = _run(frames, terminal_bar_end=first.bar_end)

    assert result.actions == ()
    assert result.pending_action is None
    assert result.canceled_pending[0].reason_code == "NEXT_BAR_OPEN_UNAVAILABLE"
    assert result.final_position is SubingStrategyPositionState.FLAT


def test_session_gap_fills_at_next_existing_same_segment_bar() -> None:
    first = _bar(1)
    next_session = _bar(2, open_price="103", gap_days=1)
    frames = (
        _frame(
            first,
            previous=None,
            candidates=(_candidate(first, direction=SubingDirection.LONG),),
        ),
        _frame(next_session, previous=first),
    )

    result = _run(frames)

    assert result.actions[0].effective_bar_end == next_session.bar_end
    assert result.actions[0].reference_price == Decimal("103")


def test_authoritative_terminal_closes_at_final_close() -> None:
    frames = _entry_frames()[:2]
    terminal = frames[-1].bar.bar_end

    result = _run(frames, terminal_bar_end=terminal)

    close = result.actions[-1]
    assert close.kind is SubingStrategyActionKind.CLOSE_LONG
    assert close.reference_price == frames[-1].bar.close
    assert close.fill_basis is SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE
    assert close.effective_open_at is None
    assert close.reason_codes == ("CONTRACT_SEGMENT_END",)
    assert result.final_position is SubingStrategyPositionState.FLAT


def test_terminal_close_preserves_ordinary_reasons_before_terminal_reason() -> None:
    frames = _entry_frames(exit_bar=_bar(2, close="98"), exit_ema="99")[:2]

    result = _run(frames, terminal_bar_end=frames[-1].bar.bar_end)

    assert result.actions[-1].reason_codes == (
        "EMA21_BREACH_LONG",
        "CONTRACT_SEGMENT_END",
    )


def test_terminal_bar_must_equal_final_frame() -> None:
    frames = _entry_frames()[:2]

    with pytest.raises(ValueError, match="SUBING_STRATEGY_TERMINAL_INVALID"):
        _run(frames, terminal_bar_end=frames[0].bar.bar_end)
