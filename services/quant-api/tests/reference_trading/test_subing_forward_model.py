from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from guiyi_quant.reference_trading import (
    ActionKind, RecordingMode, ReferenceAction, ReferenceState, StreamIdentity,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json, adapter_checkpoint_to_json,
)
from guiyi_quant.reference_trading.subing_forward import (
    advance_subing_forward, seed_subing_forward,
)


def test_subing_forward_reuses_kernel_and_advances_no_signal_bar():
    start = datetime(2026, 9, 23, 0, tzinfo=UTC)
    stream = StreamIdentity(
        "subing-reference", ("subing_ths_15m_v3",), "subing_reference_15m_v1",
        "subing_reference_v1", "subing_actual_dominant_v1", "RB", "15m",
        "actual_dominant", RecordingMode.FORWARD_OBSERVATION, "completed_v1",
    )
    strategy = seed_subing_forward()
    reference = ReferenceState.flat(stream, recording_start=start)
    for index in range(35):
        instant = start + timedelta(minutes=15 * index)
        strategy, actions, transition, _display = advance_subing_forward(
            strategy, reference, physical_contract="RB2610",
            owner_segment_id="owner", calculation_segment_id="calc",
            bar_end=instant, trading_day=date(2026, 9, 23), close=Decimal("3500"),
        )
        assert actions == ()
        reference = transition.state
    assert reference.computed_through == start + timedelta(minutes=15 * 34)
    checkpoint = AdapterCheckpoint(
        strategy, reference.computed_through, "fixture-fingerprint", "RB2610",
        "owner", "calc", stream, reference,
    )
    encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema="subing_forward_v1")
    assert adapter_checkpoint_from_json(
        encoded, expected_stream=stream, expected_strategy_schema="subing_forward_v1",
    ) == checkpoint


def test_owner_switch_interrupts_old_open_without_using_new_price_as_exit():
    start = datetime(2026, 9, 23, 0, tzinfo=UTC)
    stream = StreamIdentity(
        "subing-reference", ("subing_ths_15m_v3",), "subing_reference_15m_v1",
        "subing_reference_v1", "subing_actual_dominant_v1", "RB", "15m",
        "actual_dominant", RecordingMode.FORWARD_OBSERVATION, "completed_v1",
    )
    opened = reduce_reference(ReferenceState.flat(stream, recording_start=start), actions=(
        ReferenceAction(
            stream=stream, source_action_id="old-entry", sequence=0,
            kind=ActionKind.OPEN_LONG, physical_contract="RB2610",
            owner_segment_id="owner-old", calculation_segment_id="calc-old",
            bar_end=start, trading_day=date(2026, 9, 23),
            reference_price=Decimal("3500"), reference_price_type="signal_close",
        ),
    ), completed_bar_end=start, completed_trading_day=date(2026, 9, 23),
        completed_reference_price=Decimal("3500"))
    strategy, _, _, _ = advance_subing_forward(
        seed_subing_forward(), ReferenceState.flat(stream, recording_start=start),
        physical_contract="RB2610", owner_segment_id="owner-old",
        calculation_segment_id="calc-old", bar_end=start,
        trading_day=date(2026, 9, 23), close=Decimal("3500"),
    )
    next_bar = start + timedelta(minutes=15)
    new_strategy, actions, transition, display = advance_subing_forward(
        strategy, opened.state, physical_contract="RB2701", owner_segment_id="owner-new",
        calculation_segment_id="calc-new", bar_end=next_bar,
        trading_day=date(2026, 9, 23), close=Decimal("3600"),
    )
    assert actions == ()
    assert transition.changed_trades[0].status.value == "ROLLOVER_INTERRUPTED"
    assert transition.changed_trades[0].exit_reference_price is None
    assert transition.state.open_trade is None
    assert display["rollover_interrupted"] is True
    assert new_strategy.physical_contract == "RB2701"
