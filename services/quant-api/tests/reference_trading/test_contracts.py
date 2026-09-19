from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import (
    ActionKind,
    CompletedReferenceBar,
    RecordingMode,
    ReferenceAction,
    StreamIdentity,
)


def stream(*, frequency: str = "1d", mode: RecordingMode = RecordingMode.HISTORICAL_REPLAY) -> StreamIdentity:
    return StreamIdentity(
        strategy_code="test_strategy",
        formula_versions=("test_formula_v1",),
        profile_id="default",
        reference_model_version="reference_v1",
        futures_adaptation_version="futures_v1",
        product="RB",
        frequency=frequency,
        series_kind="actual_dominant",
        recording_mode=mode,
        observation_policy_version=None if mode is RecordingMode.HISTORICAL_REPLAY else "forward_flat_start_v1",
    )


def test_stream_identity_is_stable_and_mode_isolation_is_explicit() -> None:
    historical = stream()
    same = stream()
    forward = stream(mode=RecordingMode.FORWARD_OBSERVATION)

    assert historical.stream_id == same.stream_id
    assert historical.stream_id != forward.stream_id


def test_stream_identity_rejects_a_string_formula_version() -> None:
    with pytest.raises(TypeError, match="formula_versions"):
        StreamIdentity(
            strategy_code="strategy", formula_versions="formula_v1", profile_id="default",
            reference_model_version="reference_v1", futures_adaptation_version="futures_v1",
            product="RB", frequency="1d", series_kind="actual_dominant",
            recording_mode=RecordingMode.HISTORICAL_REPLAY, observation_policy_version=None,
        )


def test_reference_action_rejects_float_prices_and_naive_instants() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    common = dict(
        stream=stream(),
        source_action_id="build-1",
        physical_contract="RB2601",
        owner_segment_id="owner-1",
        calculation_segment_id="calc-1",
        bar_end=at,
        trading_day=date(2026, 9, 19),
        sequence=1,
        kind=ActionKind.OPEN_LONG,
    )

    with pytest.raises(TypeError, match="Decimal"):
        ReferenceAction(reference_price=10.0, **common)
    with pytest.raises(ValueError, match="timezone-aware"):
        ReferenceAction(reference_price=Decimal("10"), bar_end=at.replace(tzinfo=None), **{key: value for key, value in common.items() if key != "bar_end"})


def test_action_rejects_close_without_explicit_entry_and_invalid_forward_boundary_mode() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="entry_action_id"):
        ReferenceAction(
            stream=stream(), source_action_id="clear-1", physical_contract="RB2601",
            owner_segment_id="owner-1", calculation_segment_id="calc-1", bar_end=at,
            trading_day=date(2026, 9, 19), sequence=1, kind=ActionKind.CLOSE,
            reference_price=Decimal("10"),
        )


def test_completed_reference_bar_requires_the_full_owner_identity() -> None:
    at = datetime(2026, 9, 19, 15, tzinfo=UTC)
    completed = CompletedReferenceBar(
        physical_contract="RB2601", owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=at, trading_day=date(2026, 9, 19), reference_price=Decimal("100"),
    )
    assert completed.reference_price == Decimal("100")
    with pytest.raises(ValueError, match="owner_segment_id"):
        CompletedReferenceBar(
            physical_contract="RB2601", owner_segment_id="", calculation_segment_id="calc-1",
            bar_end=at, trading_day=date(2026, 9, 19), reference_price=Decimal("100"),
        )
