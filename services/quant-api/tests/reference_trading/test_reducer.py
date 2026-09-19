from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import (
    ActionKind,
    BoundaryReason,
    RecordingMode,
    ReferenceAction,
    ReferenceBoundary,
    ReferenceState,
    ReferenceTrade,
    StreamIdentity,
    TradeStatus,
    reduce_reference,
)


def stream(mode: RecordingMode = RecordingMode.HISTORICAL_REPLAY) -> StreamIdentity:
    return StreamIdentity(
        strategy_code="test_strategy", formula_versions=("formula_v1",), profile_id="default",
        reference_model_version="reference_v1", futures_adaptation_version="futures_v1",
        product="RB", frequency="1d", series_kind="actual_dominant", recording_mode=mode,
        observation_policy_version=None if mode is RecordingMode.HISTORICAL_REPLAY else "forward_flat_start_v1",
    )


def action(
    kind: ActionKind, name: str, *, sequence: int = 1, at: datetime | None = None,
    entry_action_id: str | None = None, mode: RecordingMode = RecordingMode.HISTORICAL_REPLAY,
) -> ReferenceAction:
    instant = at or datetime(2026, 9, 19, 15, tzinfo=UTC)
    return ReferenceAction(
        stream=stream(mode), source_action_id=name, physical_contract="RB2601",
        owner_segment_id="owner-1", calculation_segment_id="calc-1", bar_end=instant,
        trading_day=date(2026, 9, 19), sequence=sequence, kind=kind,
        reference_price=Decimal("100" if kind is not ActionKind.CLOSE else "110"),
        entry_action_id=entry_action_id,
    )


def test_reducer_closes_then_opens_a_same_bar_reverse_with_explicit_pairing() -> None:
    opened = reduce_reference(
        ReferenceState.flat(stream()),
        actions=(action(ActionKind.OPEN_LONG, "open-1", at=datetime(2026, 9, 18, 15, tzinfo=UTC)),),
    )
    result = reduce_reference(
        opened.state,
        actions=(
            action(ActionKind.CLOSE, "close-1", sequence=1, entry_action_id="open-1"),
            action(ActionKind.OPEN_SHORT, "open-2", sequence=2),
        ),
    )

    assert [trade.status for trade in result.changed_trades] == [TradeStatus.CLOSED, TradeStatus.OPEN]
    assert result.changed_trades[0].exit_action_id == "close-1"
    assert result.state.open_trade is not None
    assert result.state.open_trade.entry_action_id == "open-2"


def test_legal_same_bar_batches_match_one_batch_transition() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    open_action = action(ActionKind.OPEN_LONG, "open-1", at=at, sequence=1)
    close_action = action(ActionKind.CLOSE, "close-1", at=at, sequence=2, entry_action_id="open-1")
    combined = reduce_reference(ReferenceState.flat(stream()), actions=(open_action, close_action))
    split = reduce_reference(ReferenceState.flat(stream()), actions=(open_action,))
    split = reduce_reference(split.state, actions=(close_action,))

    assert split.state.open_trade == combined.state.open_trade
    assert split.state.last_event_key == combined.state.last_event_key
    assert split.changed_trades[-1].status is TradeStatus.CLOSED


def test_same_bar_open_then_boundary_can_be_split_without_changing_result() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    open_action = action(ActionKind.OPEN_LONG, "open-1", at=at, sequence=1)
    boundary = ReferenceBoundary(
        stream=stream(), reason=BoundaryReason.ROLLOVER, physical_contract="RB2601",
        owner_segment_id="owner-1", calculation_segment_id="calc-1", bar_end=at,
        trading_day=date(2026, 9, 19),
    )
    combined = reduce_reference(ReferenceState.flat(stream()), actions=(open_action,), boundaries=(boundary,))
    split = reduce_reference(ReferenceState.flat(stream()), actions=(open_action,))
    split = reduce_reference(split.state, boundaries=(boundary,))

    assert split.state.open_trade == combined.state.open_trade
    assert split.state.last_event_key == combined.state.last_event_key
    assert split.changed_trades[-1].status is TradeStatus.ROLLOVER_INTERRUPTED


def test_close_rejects_a_different_owner_segment() -> None:
    opened = reduce_reference(ReferenceState.flat(stream()), actions=(action(ActionKind.OPEN_LONG, "open-1", at=datetime(2026, 9, 18, 15, tzinfo=UTC)),))
    close = action(ActionKind.CLOSE, "close-1", entry_action_id="open-1")
    close = ReferenceAction(**{
        **{field: getattr(close, field) for field in close.__dataclass_fields__},
        "owner_segment_id": "other-owner",
    })
    with pytest.raises(ValueError, match="physical contract and segments"):
        reduce_reference(opened.state, actions=(close,))


def test_reducer_rejects_reverse_in_wrong_sequence_without_changing_input() -> None:
    opened = reduce_reference(
        ReferenceState.flat(stream()),
        actions=(action(ActionKind.OPEN_LONG, "open-1", at=datetime(2026, 9, 18, 15, tzinfo=UTC)),),
    )
    original = opened.state

    with pytest.raises(ValueError, match="OPEN requires FLAT"):
        reduce_reference(
            original,
            actions=(
                action(ActionKind.OPEN_SHORT, "open-2", sequence=1),
                action(ActionKind.CLOSE, "close-1", sequence=2, entry_action_id="open-1"),
            ),
        )
    assert original.open_trade is not None
    assert original.open_trade.entry_action_id == "open-1"


def test_hint_has_no_trade_effect_and_empty_completed_bar_advances_watermark_and_holding() -> None:
    start = datetime(2026, 9, 19, 15, tzinfo=UTC)
    opened = reduce_reference(ReferenceState.flat(stream()), actions=(action(ActionKind.OPEN_LONG, "open-1", at=start),))
    result = reduce_reference(
        opened.state,
        actions=(action(ActionKind.HINT, "hint-1", at=start + timedelta(days=1)),),
        completed_bar_end=start + timedelta(days=1),
        completed_trading_day=date(2026, 9, 20),
        completed_reference_price=Decimal("105"),
    )

    assert result.changed_trades == ()
    assert result.state.computed_through == start + timedelta(days=1)
    assert result.state.open_trade is not None
    assert result.state.open_trade.holding_bars == 1
    assert result.marks[0].reference_return == Decimal("5.00")


def test_forward_clear_after_hold_is_no_observed_entry_not_initial_clear() -> None:
    forward = stream(RecordingMode.FORWARD_OBSERVATION)
    result = reduce_reference(
        ReferenceState.flat(forward, recording_start=datetime(2026, 9, 19, 9, tzinfo=UTC)),
        actions=(action(ActionKind.CLOSE, "clear-1", entry_action_id="unobserved", mode=RecordingMode.FORWARD_OBSERVATION),),
    )

    assert result.changed_trades == ()
    assert result.diagnostics == ("NO_OBSERVED_ENTRY",)


def test_forward_state_rejects_input_before_its_explicit_recording_start() -> None:
    forward = stream(RecordingMode.FORWARD_OBSERVATION)
    with pytest.raises(ValueError, match="recording_start"):
        reduce_reference(
            ReferenceState.flat(forward, recording_start=datetime(2026, 9, 20, 9, tzinfo=UTC)),
            actions=(action(ActionKind.OPEN_LONG, "open-1", mode=RecordingMode.FORWARD_OBSERVATION),),
        )


def test_forward_state_rejects_an_open_trade_from_before_recording_start() -> None:
    forward = stream(RecordingMode.FORWARD_OBSERVATION)
    historical_open = reduce_reference(
        ReferenceState.flat(stream()), actions=(action(ActionKind.OPEN_LONG, "open-1"),),
    ).state.open_trade
    assert historical_open is not None
    with pytest.raises(ValueError, match="open_trade entry"):
        ReferenceState(
            stream=forward, recording_start=datetime(2026, 9, 20, 9, tzinfo=UTC),
            open_trade=ReferenceTrade(**{
                **{field: getattr(historical_open, field) for field in historical_open.__dataclass_fields__},
                "stream": forward,
            }),
        )


def test_historical_clear_without_adapter_lifecycle_evidence_is_not_initial_clear() -> None:
    result = reduce_reference(
        ReferenceState.flat(stream()),
        actions=(action(ActionKind.CLOSE, "clear-1", entry_action_id="unproven-entry"),),
    )

    assert result.diagnostics == ("NO_ENTRY",)


def test_boundary_interrupts_open_without_inventing_exit_price_or_return() -> None:
    state = reduce_reference(ReferenceState.flat(stream()), actions=(action(ActionKind.OPEN_LONG, "open-1"),)).state
    boundary = ReferenceBoundary(
        stream=stream(), reason=BoundaryReason.ROLLOVER, physical_contract="RB2601",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=datetime(2026, 9, 20, 15, tzinfo=UTC), trading_day=date(2026, 9, 20),
    )
    result = reduce_reference(state, boundaries=(boundary,))

    assert result.changed_trades[0].status is TradeStatus.ROLLOVER_INTERRUPTED
    assert result.changed_trades[0].exit_reference_price is None
    assert result.changed_trades[0].reference_return is None
    assert result.state.open_trade is None
    assert result.state.computed_through is None


def test_reducer_rejects_a_close_before_its_entry() -> None:
    opened = reduce_reference(
        ReferenceState.flat(stream()),
        actions=(action(ActionKind.OPEN_LONG, "open-1", at=datetime(2026, 9, 20, 15, tzinfo=UTC)),),
    )

    with pytest.raises(ValueError, match="prior event"):
        reduce_reference(
            opened.state,
            actions=(
                action(
                    ActionKind.CLOSE, "close-1", entry_action_id="open-1",
                    at=datetime(2026, 9, 19, 15, tzinfo=UTC),
                ),
            ),
        )


def test_same_completed_batch_replay_is_a_noop_and_does_not_recount_holding() -> None:
    start = datetime(2026, 9, 19, 15, tzinfo=UTC)
    state = reduce_reference(ReferenceState.flat(stream()), actions=(action(ActionKind.OPEN_LONG, "open-1", at=start),)).state
    first = reduce_reference(
        state, completed_bar_end=start + timedelta(days=1), completed_trading_day=date(2026, 9, 20),
        completed_reference_price=Decimal("100"),
    )
    replay = reduce_reference(
        first.state, completed_bar_end=start + timedelta(days=1), completed_trading_day=date(2026, 9, 20),
        completed_reference_price=Decimal("100"),
    )

    assert first.state.open_trade is not None
    assert first.state.open_trade.holding_bars == 1
    assert replay.state == first.state
    assert replay.changed_trades == ()


def test_actions_are_applied_before_a_later_boundary_in_one_batch() -> None:
    start = datetime(2026, 9, 19, 15, tzinfo=UTC)
    boundary_at = start + timedelta(days=1)
    boundary = ReferenceBoundary(
        stream=stream(), reason=BoundaryReason.ROLLOVER, physical_contract="RB2601",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=boundary_at, trading_day=date(2026, 9, 20),
    )
    result = reduce_reference(
        ReferenceState.flat(stream()),
        actions=(action(ActionKind.OPEN_LONG, "open-1", at=start),), boundaries=(boundary,),
    )

    assert [trade.status for trade in result.changed_trades] == [TradeStatus.OPEN, TradeStatus.ROLLOVER_INTERRUPTED]
    assert result.state.open_trade is None


def test_short_reference_return_uses_the_opposite_price_direction() -> None:
    opened = reduce_reference(
        ReferenceState.flat(stream()),
        actions=(action(ActionKind.OPEN_SHORT, "open-1", at=datetime(2026, 9, 18, 15, tzinfo=UTC)),),
    )
    result = reduce_reference(
        opened.state,
        actions=(action(ActionKind.CLOSE, "close-1", entry_action_id="open-1"),),
    )

    assert result.changed_trades[0].reference_return == Decimal("-10.0")


def test_batch_rejects_duplicate_source_identity_and_input_after_watermark() -> None:
    start = datetime(2026, 9, 19, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="source_action_id"):
        reduce_reference(
            ReferenceState.flat(stream()),
            actions=(
                action(ActionKind.HINT, "same", sequence=1, at=start),
                action(ActionKind.HINT, "same", sequence=2, at=start),
            ),
        )
    state = reduce_reference(
        ReferenceState.flat(stream()),
        completed_bar_end=start + timedelta(days=1), completed_trading_day=date(2026, 9, 20),
    ).state
    with pytest.raises(ValueError, match="computed_through"):
        reduce_reference(
            state,
            actions=(action(ActionKind.HINT, "old", at=start),),
        )


def test_open_completed_bar_requires_explicit_mark_price() -> None:
    start = datetime(2026, 9, 19, 15, tzinfo=UTC)
    opened = reduce_reference(ReferenceState.flat(stream()), actions=(action(ActionKind.OPEN_LONG, "open-1", at=start),))
    with pytest.raises(ValueError, match="completed_reference_price"):
        reduce_reference(
            opened.state, completed_bar_end=start + timedelta(days=1),
            completed_trading_day=date(2026, 9, 20),
        )


def test_batch_rejects_conflicting_boundaries_for_one_segment_at_one_bar() -> None:
    at = datetime(2026, 9, 20, 15, tzinfo=UTC)
    first = ReferenceBoundary(
        stream=stream(), reason=BoundaryReason.ROLLOVER, physical_contract="RB2601",
        owner_segment_id="owner-1", calculation_segment_id="calc-1", bar_end=at,
        trading_day=date(2026, 9, 20),
    )
    second = ReferenceBoundary(
        stream=stream(), reason=BoundaryReason.DATA_INTERRUPTED, physical_contract="RB2601",
        owner_segment_id="owner-1", calculation_segment_id="calc-1", bar_end=at,
        trading_day=date(2026, 9, 20),
    )
    with pytest.raises(ValueError, match="boundaries"):
        reduce_reference(ReferenceState.flat(stream()), boundaries=(first, second))


def test_observation_interruption_is_forward_only() -> None:
    with pytest.raises(ValueError, match="forward_observation"):
        ReferenceBoundary(
            stream=stream(), reason=BoundaryReason.OBSERVATION_INTERRUPTED, physical_contract="RB2601",
            owner_segment_id="owner-1", calculation_segment_id="calc-1",
            bar_end=datetime(2026, 9, 20, 15, tzinfo=UTC), trading_day=date(2026, 9, 20),
        )
