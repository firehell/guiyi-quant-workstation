from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import (
    ActionKind,
    ReferenceAction,
    ReferenceState,
    StreamIdentity,
    checkpoint_from_json,
    checkpoint_to_json,
    reduce_reference,
)


def _stream() -> StreamIdentity:
    return StreamIdentity(
        strategy_code="checkpoint-test", formula_versions=("formula-v1",), profile_id="default",
        reference_model_version="reference-v1", futures_adaptation_version="futures-v1",
        product="RB", frequency="1d", series_kind="actual_dominant",
        recording_mode="historical_replay", observation_policy_version=None,
    )


def test_reference_checkpoint_round_trips_open_state_without_history() -> None:
    instant = datetime(2026, 9, 19, 15, tzinfo=UTC)
    action = ReferenceAction(
        stream=_stream(), source_action_id="open", physical_contract="RB2601",
        owner_segment_id="owner", calculation_segment_id="calc", bar_end=instant,
        trading_day=instant.date(), sequence=0, kind=ActionKind.OPEN_LONG,
        reference_price=Decimal("100"),
    )
    state = reduce_reference(ReferenceState.flat(_stream()), actions=(action,)).state

    restored = checkpoint_from_json(checkpoint_to_json(state))

    assert restored == state


def test_reference_checkpoint_rejects_wrong_schema_and_nonfinite_decimal() -> None:
    with pytest.raises(ValueError, match="schema"):
        checkpoint_from_json('{"schema_version":"wrong"}')
    instant = datetime(2026, 9, 19, 15, tzinfo=UTC)
    action = ReferenceAction(
        stream=_stream(), source_action_id="open", physical_contract="RB2601",
        owner_segment_id="owner", calculation_segment_id="calc", bar_end=instant,
        trading_day=instant.date(), sequence=0, kind=ActionKind.OPEN_LONG,
        reference_price=Decimal("100"),
    )
    state = reduce_reference(ReferenceState.flat(_stream()), actions=(action,)).state
    with pytest.raises(ValueError, match="finite"):
        checkpoint_from_json(checkpoint_to_json(state).replace('"100"', '"NaN"', 1))
