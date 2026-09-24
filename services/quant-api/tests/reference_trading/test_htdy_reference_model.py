from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.htdy import MODEL_VERSION, project_first_seen
from guiyi_quant.reference_trading.htdy import HtdyForwardState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_to_json, adapter_checkpoint_from_json,
)


START = datetime(2026, 9, 23, 8, tzinfo=UTC)


def _stream():
    from test_repository import _stream as base

    return replace(
        base(), strategy_code="htdy", reference_model_version=MODEL_VERSION,
        recording_mode=RecordingMode.FORWARD_OBSERVATION,
        observation_policy_version="latest_only_32_v1",
    )


def _step(state, offset, observations):
    instant = START + timedelta(minutes=15 * offset)
    return project_first_seen(
        state, observations=observations, physical_contract="RB2610",
        owner_segment_id="owner", calculation_segment_id="calc",
        bar_end=instant, trading_day=date(2026, 9, 23), close=Decimal("3500") + offset,
    )


def test_first_seen_opens_then_reverses_with_linked_close():
    state = ReferenceState.flat(_stream(), recording_start=START)
    opened_actions, opened = _step(state, 0, ("buy",))
    assert [action.kind.value for action in opened_actions] == ["OPEN_LONG"]
    same_actions, same = _step(opened.state, 1, ("buy",))
    assert same_actions == ()
    reverse_actions, reverse = _step(same.state, 2, ("sell",))
    assert [action.kind.value for action in reverse_actions] == ["CLOSE", "OPEN_SHORT"]
    assert reverse_actions[0].entry_action_id == opened_actions[0].source_action_id
    assert reverse.state.open_trade.side.value == "SHORT"


def test_conflict_blocks_progress_without_mutating_prior_state():
    state = ReferenceState.flat(_stream(), recording_start=START)
    with pytest.raises(ValueError, match="HTDY_SIGNAL_CONFLICT"):
        _step(state, 0, ("buy", "sell"))
    assert state.computed_through is None


def test_htdy_checkpoint_is_strict_and_roundtrips():
    stream = _stream()
    checkpoint = AdapterCheckpoint(
        HtdyForwardState(MODEL_VERSION, stream.observation_policy_version),
        stream=stream, reference_state=ReferenceState.flat(stream, recording_start=START),
    )
    encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema="htdy_first_seen_v1")
    restored = adapter_checkpoint_from_json(
        encoded, expected_stream=stream, expected_strategy_schema="htdy_first_seen_v1",
    )
    assert restored == checkpoint
