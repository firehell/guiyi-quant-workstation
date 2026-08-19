from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    EntryProgress,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleState,
    SubingLifecycleStateError,
    SubingOpportunityKey,
)
from app.market_data.subing_research import SubingDirection


def _opportunity_key(
    *,
    direction: SubingDirection = SubingDirection.LONG,
    origin_at: datetime = datetime(2026, 8, 19, 1, 5, tzinfo=timezone.utc),
) -> SubingOpportunityKey:
    return SubingOpportunityKey(
        policy_id="subing_lifecycle_v2_research_v1",
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 3),
        direction=direction,
        origin_at=origin_at,
    )


def test_lifecycle_enums_expose_the_approved_wire_values() -> None:
    assert tuple(LifecycleAvailability) == (
        LifecycleAvailability.READY,
        LifecycleAvailability.UNAVAILABLE,
    )
    assert tuple(member.value for member in LifecycleStage) == (
        "idle",
        "setup_armed",
        "entry_confirmed",
        "continuation",
        "exit_risk",
        "closed",
    )
    assert tuple(member.value for member in EntryProgress) == (
        "waiting_trigger",
        "hold_confirming",
        "retest_confirming",
    )
    assert tuple(member.value for member in ConfirmationSource) == (
        "formal_v1",
        "momentum_hold",
        "pivot_break_hold",
        "pivot_retest_rebreak",
    )


def test_opportunity_key_keeps_exact_immutable_identity() -> None:
    key = _opportunity_key()

    assert key.policy_id == "subing_lifecycle_v2_research_v1"
    assert key.symbol == "JM"
    assert key.contract == "JM2701"
    assert key.segment_start_trading_day == date(2026, 8, 3)
    assert key.direction is SubingDirection.LONG
    assert key.origin_at == datetime(2026, 8, 19, 1, 5, tzinfo=timezone.utc)
    with pytest.raises(FrozenInstanceError):
        key.contract = "JM2705"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("policy_id", ""),
        ("symbol", ""),
        ("contract", ""),
        ("segment_start_trading_day", datetime(2026, 8, 3, tzinfo=timezone.utc)),
        ("direction", SubingDirection.NONE),
        ("direction", "long"),
        ("origin_at", datetime(2026, 8, 19, 9, 5)),
    ),
)
def test_opportunity_key_rejects_invalid_identity(
    field: str,
    invalid: object,
) -> None:
    values: dict[str, object] = {
        "policy_id": "subing_lifecycle_v2_research_v1",
        "symbol": "JM",
        "contract": "JM2701",
        "segment_start_trading_day": date(2026, 8, 3),
        "direction": SubingDirection.LONG,
        "origin_at": datetime(2026, 8, 19, 1, 5, tzinfo=timezone.utc),
    }
    values[field] = invalid

    with pytest.raises(ValueError, match="SUBING_OPPORTUNITY_KEY_INVALID"):
        SubingOpportunityKey(**values)  # type: ignore[arg-type]


def test_setup_state_requires_directional_opportunity_identity() -> None:
    state = SubingLifecycleState(
        availability=LifecycleAvailability.READY,
        direction=SubingDirection.LONG,
        stage=LifecycleStage.SETUP_ARMED,
        opportunity_key=_opportunity_key(),
        entry_progress=EntryProgress.WAITING_TRIGGER,
    )

    assert state.opportunity_key == _opportunity_key()
    with pytest.raises(FrozenInstanceError):
        state.stage = LifecycleStage.CLOSED  # type: ignore[misc]


def test_setup_state_rejects_none_direction() -> None:
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STATE_INVALID"):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.NONE,
            stage=LifecycleStage.SETUP_ARMED,
            opportunity_key=_opportunity_key(),
            entry_progress=EntryProgress.WAITING_TRIGGER,
        )


def test_entry_confirmed_requires_opportunity_identity() -> None:
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STATE_INVALID"):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.LONG,
            stage=LifecycleStage.ENTRY_CONFIRMED,
            confirmation_source=ConfirmationSource.FORMAL_V1,
        )


@pytest.mark.parametrize(
    "stage",
    (
        LifecycleStage.ENTRY_CONFIRMED,
        LifecycleStage.CONTINUATION,
        LifecycleStage.EXIT_RISK,
    ),
)
def test_confirmed_stage_rejects_missing_confirmation_time(
    stage: LifecycleStage,
) -> None:
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STATE_INVALID"):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.LONG,
            stage=stage,
            opportunity_key=_opportunity_key(),
            confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
        )


@pytest.mark.parametrize(
    "stage",
    (
        LifecycleStage.ENTRY_CONFIRMED,
        LifecycleStage.CONTINUATION,
        LifecycleStage.EXIT_RISK,
    ),
)
def test_confirmed_stage_rejects_naive_confirmation_time(
    stage: LifecycleStage,
) -> None:
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STATE_INVALID"):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.LONG,
            stage=stage,
            opportunity_key=_opportunity_key(),
            confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
            confirmed_at=datetime(2026, 8, 19, 9, 15),
        )


@pytest.mark.parametrize(
    "stage",
    (
        LifecycleStage.ENTRY_CONFIRMED,
        LifecycleStage.CONTINUATION,
        LifecycleStage.EXIT_RISK,
    ),
)
def test_confirmed_stage_accepts_aware_real_confirmation_time(
    stage: LifecycleStage,
) -> None:
    confirmed_at = datetime(2026, 8, 19, 1, 15, tzinfo=timezone.utc)

    state = SubingLifecycleState(
        availability=LifecycleAvailability.READY,
        direction=SubingDirection.LONG,
        stage=stage,
        opportunity_key=_opportunity_key(),
        confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
        confirmed_at=confirmed_at,
    )

    assert state.confirmed_at == confirmed_at


def test_confirmed_stage_rejects_confirmation_before_opportunity_origin() -> None:
    with pytest.raises(SubingLifecycleStateError):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.LONG,
            stage=LifecycleStage.ENTRY_CONFIRMED,
            opportunity_key=_opportunity_key(),
            confirmation_source=ConfirmationSource.MOMENTUM_HOLD,
            confirmed_at=datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("direction", []),
        ("opportunity_key", object()),
    ),
)
def test_state_runtime_type_errors_use_stable_domain_error(
    field: str,
    invalid: object,
) -> None:
    values: dict[str, object] = {
        "availability": LifecycleAvailability.READY,
        "direction": SubingDirection.LONG,
        "stage": LifecycleStage.SETUP_ARMED,
        "opportunity_key": _opportunity_key(),
        "entry_progress": EntryProgress.WAITING_TRIGGER,
    }
    values[field] = invalid

    with pytest.raises(SubingLifecycleStateError) as exc_info:
        SubingLifecycleState(**values)  # type: ignore[arg-type]

    assert exc_info.value.code == "SUBING_LIFECYCLE_STATE_INVALID"
    assert str(exc_info.value) == "SUBING_LIFECYCLE_STATE_INVALID"


def test_state_direction_must_match_opportunity_identity() -> None:
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STATE_INVALID"):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.SHORT,
            stage=LifecycleStage.ENTRY_CONFIRMED,
            opportunity_key=_opportunity_key(direction=SubingDirection.LONG),
            confirmation_source=ConfirmationSource.FORMAL_V1,
        )


def test_idle_state_rejects_confirmation_progress() -> None:
    with pytest.raises(ValueError, match="SUBING_LIFECYCLE_STATE_INVALID"):
        SubingLifecycleState(
            availability=LifecycleAvailability.READY,
            direction=SubingDirection.NONE,
            stage=LifecycleStage.IDLE,
            entry_progress=EntryProgress.HOLD_CONFIRMING,
        )
