from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data import subing_lifecycle as lifecycle_module
from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    EntryProgress,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleContractError,
    SubingLifecycleState,
    SubingLifecycleStateError,
    SubingOpportunityKey,
    evaluate_subing_direction_context,
    evaluate_subing_lifecycle,
)
from app.market_data.domain import BarFrequency
from app.market_data.subing_lifecycle_policy import (
    load_subing_lifecycle_policy,
)
from app.market_data.subing_research import (
    MacdCross,
    SubingDirection,
    SubingFactorStatus,
    calculate_subing_factor_series,
)
from research.subing_lifecycle_fixtures import (
    _accepted_calibration,
    _bar,
    _evaluate,
    _factor,
    _opportunity_key,
    _stream_lifecycle_prefixes,
    _with_lifecycle_reset,
)


_SEGMENT_START = date(2026, 8, 3)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


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


def test_machine_state_and_nested_opportunity_are_immutable() -> None:
    boundary = _bar(5)
    bars, factors = _with_lifecycle_reset(
        (boundary,),
        (_factor(boundary, BarFrequency.M5),),
    )
    anchor = _bar(0)
    state = _stream_lifecycle_prefixes(
        bars,
        factors_5m=factors,
        bars_15m=(anchor,),
        factors_15m=(_factor(anchor, BarFrequency.M15),),
    )[-1]

    assert state.active_opportunity is not None
    with pytest.raises(FrozenInstanceError):
        state.active_opportunity.hold_count = 2  # type: ignore[misc]
    with pytest.raises(SubingLifecycleContractError):
        replace(state, formula_version="drifted")
    assert tuple(member.value for member in EntryProgress) == (
        "waiting_trigger",
        "hold_confirming",
        "retest_confirming",
    )


def test_public_direction_context_is_the_reducer_exact_pure_fact() -> None:
    boundary = _bar(15)
    long_5m = _factor(boundary, BarFrequency.M5).snapshot
    long_15m = _factor(boundary, BarFrequency.M15).snapshot
    short_15m = _factor(
        boundary,
        BarFrequency.M15,
        direction=SubingDirection.SHORT,
    ).snapshot
    assert long_5m is not None
    assert long_15m is not None
    assert short_15m is not None

    assert (
        evaluate_subing_direction_context(
            long_5m,
            long_15m,
            _accepted_calibration(),
        )
        is SubingDirection.LONG
    )
    assert (
        evaluate_subing_direction_context(
            long_5m,
            short_15m,
            _accepted_calibration(),
        )
        is SubingDirection.NONE
    )
    assert tuple(member.value for member in ConfirmationSource) == (
        "formal_v1",
        "momentum_hold",
        "pivot_break_hold",
        "pivot_retest_rebreak",
    )


def test_reducer_trace_calls_public_direction_fact_without_semantic_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = evaluate_subing_direction_context
    observed: list[SubingDirection] = []

    def characterize(*args: object, **kwargs: object) -> SubingDirection:
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        observed.append(result)
        return result

    monkeypatch.setattr(
        lifecycle_module,
        "evaluate_subing_direction_context",
        characterize,
    )
    first, trigger, formal = (_bar(value) for value in (5, 10, 15))
    trace = _evaluate(
        (first, trigger, formal),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(trigger, BarFrequency.M5, cross=MacdCross.GOLDEN),
            _factor(
                formal,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(_bar(0), _bar(15)),
    )

    assert observed == [SubingDirection.LONG] * 3
    assert tuple(snapshot.stage for snapshot in trace.snapshots) == (
        LifecycleStage.SETUP_ARMED,
        LifecycleStage.SETUP_ARMED,
        LifecycleStage.ENTRY_CONFIRMED,
    )
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert trace.current_snapshot.triggered_at == trigger.bar_end


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


def test_timezone_equivalent_opportunity_origins_store_one_utc_identity() -> None:
    utc_key = _opportunity_key()
    offset_key = _opportunity_key(
        origin_at=utc_key.origin_at.astimezone(timezone(timedelta(hours=8)))
    )

    assert offset_key == utc_key
    assert offset_key.origin_at.tzinfo is UTC
    assert offset_key.origin_at.isoformat() == "2026-08-19T01:05:00+00:00"


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("policy_id", "another_policy"),
        ("policy_id", ""),
        ("symbol", ""),
        ("contract", ""),
        ("contract", "RB2701"),
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
def test_corrupted_policy_identity_is_unavailable() -> None:
    boundary = _bar(15)
    policy = load_subing_lifecycle_policy()
    object.__setattr__(policy, "policy_id", "drifted_same_object")

    trace = _evaluate((boundary,), bars_15m=(boundary,), policy=policy)

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_LIFECYCLE_POLICY_INVALID"


@pytest.mark.parametrize(
    "mismatch",
    ("missing_5m", "extra_5m", "missing_15m", "extra_15m"),
)
def test_series_alignment_mismatch_is_unavailable_without_index_error(
    mismatch: str,
) -> None:
    boundary = _bar(15)
    factor_5m = _factor(boundary, BarFrequency.M5)
    factor_15m = _factor(boundary, BarFrequency.M15)
    factors_5m = {
        "missing_5m": (),
        "extra_5m": (factor_5m, factor_5m),
    }.get(mismatch, (factor_5m,))
    factors_15m = {
        "missing_15m": (),
        "extra_15m": (factor_15m, factor_15m),
    }.get(mismatch, (factor_15m,))

    trace = evaluate_subing_lifecycle(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=(boundary,),
        factors_5m=factors_5m,
        bars_15m=(boundary,),
        factors_15m=factors_15m,
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    assert len(trace.snapshots) == 1
    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert (
        trace.current_snapshot.unavailable_reason
        == "SUBING_LIFECYCLE_SERIES_ALIGNMENT_INVALID"
    )
    assert trace.confirmed_pivots == ()
    assert trace.completed_opportunities == ()
    assert trace.transitions == ()


def test_batch_warmup_15m_factor_returns_unavailable_trace() -> None:
    """Catches the batch adapter sending a real warm-up Factor to the strict step."""
    boundary = _bar(15)
    factors_15m = calculate_subing_factor_series(
        (boundary,),
        timeframe=BarFrequency.M15,
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
        latest_bar_source="canonical",
    )
    assert factors_15m[0].status is SubingFactorStatus.INSUFFICIENT_DATA
    assert factors_15m[0].snapshot is None

    trace = evaluate_subing_lifecycle(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=(boundary,),
        factors_5m=(_factor(boundary, BarFrequency.M5),),
        bars_15m=(boundary,),
        factors_15m=factors_15m,
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    assert len(trace.snapshots) == 1
    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_FACTOR_UNAVAILABLE"
    assert trace.current_snapshot.anchor_bar_end == boundary.bar_end
    assert trace.confirmed_pivots == ()
    assert trace.completed_opportunities == ()
    assert trace.transitions == ()


def test_batch_mismatched_15m_factor_returns_unavailable_trace() -> None:
    """Catches the batch adapter storing or raising on a mismatched 15m Factor."""
    boundary = _bar(15)

    trace = evaluate_subing_lifecycle(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=(boundary,),
        factors_5m=(_factor(boundary, BarFrequency.M5),),
        bars_15m=(boundary,),
        factors_15m=(
            _factor(boundary, BarFrequency.M15, contract="RB2701"),
        ),
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    assert len(trace.snapshots) == 1
    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert (
        trace.current_snapshot.unavailable_reason
        == "SUBING_FACTOR_IDENTITY_MISMATCH"
    )
    assert trace.current_snapshot.anchor_bar_end == boundary.bar_end
    assert trace.confirmed_pivots == ()
    assert trace.completed_opportunities == ()
    assert trace.transitions == ()


def test_symbol_contract_mismatch_is_unavailable() -> None:
    boundary = _bar(15)
    factor_5m = _factor(boundary, BarFrequency.M5, contract="RB2701")
    factor_15m = _factor(boundary, BarFrequency.M15, contract="RB2701")

    trace = evaluate_subing_lifecycle(
        symbol="JM",
        contract="RB2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=(boundary,),
        factors_5m=(factor_5m,),
        bars_15m=(boundary,),
        factors_15m=(factor_15m,),
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_LIFECYCLE_IDENTITY_INVALID"
    assert (trace.symbol, trace.contract, trace.segment_start_trading_day) == (
        None,
        None,
        None,
    )
    assert trace.confirmed_pivots == ()
    assert trace.completed_opportunities == ()
    assert trace.transitions == ()


def test_identity_less_trace_rejects_a_mixed_unavailable_snapshot_reason() -> None:
    boundaries = (_bar(15), _bar(20))
    factors_5m = tuple(
        _factor(boundary, BarFrequency.M5, contract="RB2701")
        for boundary in boundaries
    )
    trace = evaluate_subing_lifecycle(
        symbol="JM",
        contract="RB2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=boundaries,
        factors_5m=factors_5m,
        bars_15m=(boundaries[0],),
        factors_15m=(
            _factor(boundaries[0], BarFrequency.M15, contract="RB2701"),
        ),
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )
    forged_first = replace(
        trace.snapshots[0],
        unavailable_reason="SUBING_FACTOR_UNAVAILABLE",
    )

    with pytest.raises(SubingLifecycleContractError):
        replace(trace, snapshots=(forged_first, trace.snapshots[1]))


def test_transition_contract_requires_canonical_id_and_aware_time() -> None:
    boundary = _bar(15)
    transition = _evaluate((boundary,), bars_15m=(boundary,)).transitions[0]
    expected_id = ":".join(
        (
            "subing_lifecycle_v2_research_v1",
            "JM",
            "JM2701",
            _SEGMENT_START.isoformat(),
            "long",
            boundary.bar_end.isoformat(),
            boundary.bar_end.isoformat(),
            "setup_armed",
        )
    )

    assert transition.transition_id == expected_id
    for field, invalid in (
        ("transition_id", "forged"),
        ("transition_at", boundary.bar_end.replace(tzinfo=None)),
        ("from_stage", LifecycleStage.CLOSED),
    ):
        with pytest.raises(SubingLifecycleContractError) as exc_info:
            replace(transition, **{field: invalid})
        assert exc_info.value.code == "SUBING_LIFECYCLE_CONTRACT_INVALID"
        assert str(exc_info.value) == "SUBING_LIFECYCLE_CONTRACT_INVALID"


def test_timezone_equivalent_transition_times_share_canonical_identity() -> None:
    boundary = _bar(15)
    transition = _evaluate((boundary,), bars_15m=(boundary,)).transitions[0]
    offset = timezone(timedelta(hours=8))
    offset_key = replace(
        transition.opportunity_key,
        origin_at=transition.opportunity_key.origin_at.astimezone(offset),
    )

    equivalent = replace(
        transition,
        opportunity_key=offset_key,
        transition_at=transition.transition_at.astimezone(offset),
    )

    assert equivalent == transition
    assert equivalent.opportunity_key.origin_at.tzinfo is UTC
    assert equivalent.transition_at.tzinfo is UTC
    assert equivalent.transition_id == transition.transition_id


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("policy_id", "another_policy"),
        ("formula_version", "another_formula"),
        ("research_only", False),
        ("observed_at", datetime(2026, 8, 3, 1, 15)),
        ("stage", LifecycleStage.IDLE),
        ("current_risk_codes", ["LOWER_TF_EMA21_BREACH"]),
        ("risk_progress", "confirmed"),
        ("lower_tf_risk_count", 3),
        ("last_confirmed_stage", "continuation"),
        ("last_confirmed_at", datetime(2026, 8, 3, 1, 15)),
        ("crossed_trading_day", 1),
        ("boundary_reset", "trading_day_changed"),
    ),
)
def test_snapshot_contract_rejects_invalid_identity_time_and_projection(
    field: str,
    invalid: object,
) -> None:
    boundary = _bar(15)
    snapshot = _evaluate((boundary,), bars_15m=(boundary,)).current_snapshot

    with pytest.raises(SubingLifecycleContractError) as exc_info:
        replace(snapshot, **{field: invalid})

    assert exc_info.value.code == "SUBING_LIFECYCLE_CONTRACT_INVALID"


def test_idle_snapshot_rejects_stale_opportunity_evidence() -> None:
    snapshot = _evaluate((), bars_15m=()).current_snapshot

    with pytest.raises(SubingLifecycleContractError) as exc_info:
        replace(snapshot, volume_ratio_prev=Decimal("1"))

    assert exc_info.value.code == "SUBING_LIFECYCLE_CONTRACT_INVALID"


@pytest.mark.parametrize(
    "mutation",
    (
        "policy_id",
        "formula_version",
        "symbol_contract",
        "current_snapshot",
        "transitions_projection",
        "completed_projection",
    ),
)
def test_trace_contract_rejects_invalid_identity_or_current_projection(
    mutation: str,
) -> None:
    bars = (_bar(5), _bar(10))
    trace = _evaluate(bars, bars_15m=(_bar(0),))
    if mutation == "policy_id":
        values = {"policy_id": "another_policy"}
    elif mutation == "formula_version":
        values = {"formula_version": "another_formula"}
    elif mutation == "symbol_contract":
        values = {"symbol": "RB"}
    elif mutation == "transitions_projection":
        values = {"transitions": ()}
    elif mutation == "completed_projection":
        snapshot = trace.current_snapshot
        values = {
            "completed_opportunities": (
                SubingLifecycleState(
                    availability=LifecycleAvailability.READY,
                    direction=snapshot.direction,
                    stage=LifecycleStage.SETUP_ARMED,
                    opportunity_key=snapshot.opportunity_key,
                    entry_progress=EntryProgress.WAITING_TRIGGER,
                ),
            )
        }
    else:
        values = {"current_snapshot": trace.snapshots[0]}

    with pytest.raises(SubingLifecycleContractError) as exc_info:
        replace(trace, **values)

    assert exc_info.value.code == "SUBING_LIFECYCLE_CONTRACT_INVALID"


def _confirmed_closed_trace():
    confirmed = _bar(15)
    close_boundary = _bar(30)
    return _evaluate(
        (confirmed, close_boundary),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(confirmed, close_boundary),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(close_boundary, BarFrequency.M15, direction=SubingDirection.SHORT),
        ),
    )


def _two_setup_closed_trace():
    first, first_close, second, second_close = (
        _bar(minutes) for minutes in (5, 10, 15, 20)
    )
    short_anchor = _bar(15)
    return _evaluate(
        (first, first_close, second, second_close),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(first_close, BarFrequency.M5, direction=SubingDirection.SHORT),
            _factor(second, BarFrequency.M5, direction=SubingDirection.SHORT),
            _factor(second_close, BarFrequency.M5),
        ),
        bars_15m=(_bar(0), short_anchor),
        factors_15m=(
            _factor(_bar(0), BarFrequency.M15),
            _factor(short_anchor, BarFrequency.M15, direction=SubingDirection.SHORT),
        ),
    )


def test_trace_rejects_missing_completed_state_for_closed_transition() -> None:
    trace = _confirmed_closed_trace()

    with pytest.raises(SubingLifecycleContractError):
        replace(trace, completed_opportunities=())


def test_trace_rejects_duplicate_completed_state() -> None:
    trace = _confirmed_closed_trace()

    with pytest.raises(SubingLifecycleContractError):
        replace(
            trace,
            completed_opportunities=(
                *trace.completed_opportunities,
                *trace.completed_opportunities,
            ),
        )


def test_trace_rejects_confirmed_completion_with_stripped_confirmation() -> None:
    trace = _confirmed_closed_trace()
    completed = trace.completed_opportunities[0]

    with pytest.raises(SubingLifecycleContractError):
        replace(
            trace,
            completed_opportunities=(
                replace(completed, confirmation_source=None, confirmed_at=None),
            ),
        )


def test_trace_rejects_stripped_confirmation_from_close_snapshot_and_state() -> None:
    trace = _confirmed_closed_trace()
    stripped_snapshot = replace(
        trace.current_snapshot,
        confirmation_source=None,
        confirmed_at=None,
    )
    stripped_state = replace(
        trace.completed_opportunities[0],
        confirmation_source=None,
        confirmed_at=None,
    )

    with pytest.raises(SubingLifecycleContractError):
        replace(
            trace,
            snapshots=(*trace.snapshots[:-1], stripped_snapshot),
            current_snapshot=stripped_snapshot,
            completed_opportunities=(stripped_state,),
        )


def test_trace_rejects_completed_states_out_of_closed_transition_order() -> None:
    trace = _two_setup_closed_trace()
    assert len(trace.completed_opportunities) == 2

    with pytest.raises(SubingLifecycleContractError):
        replace(
            trace,
            completed_opportunities=tuple(reversed(trace.completed_opportunities)),
        )


def test_trace_rejects_transitions_and_completions_reversed_together() -> None:
    trace = _two_setup_closed_trace()

    with pytest.raises(SubingLifecycleContractError):
        replace(
            trace,
            transitions=tuple(reversed(trace.transitions)),
            completed_opportunities=tuple(reversed(trace.completed_opportunities)),
        )


def test_trace_rejects_forged_setup_close_after_confirmed_entry() -> None:
    trace = _confirmed_closed_trace()
    forged_close = replace(
        trace.transitions[-1],
        from_stage=LifecycleStage.SETUP_ARMED,
    )
    forged_snapshot = replace(
        trace.current_snapshot,
        confirmation_source=None,
        confirmed_at=None,
        latest_transition=forged_close,
    )
    forged_completed = replace(
        trace.completed_opportunities[0],
        confirmation_source=None,
        confirmed_at=None,
    )

    with pytest.raises(SubingLifecycleContractError):
        replace(
            trace,
            transitions=(*trace.transitions[:-1], forged_close),
            snapshots=(*trace.snapshots[:-1], forged_snapshot),
            current_snapshot=forged_snapshot,
            completed_opportunities=(forged_completed,),
        )


def test_unconfirmed_setup_completion_legally_has_no_confirmation_metadata() -> None:
    first, close_boundary = (_bar(minutes) for minutes in (5, 10))
    trace = _evaluate(
        (first, close_boundary),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(_bar(0),),
    )

    assert trace.completed_opportunities[0].confirmation_source is None
    assert trace.completed_opportunities[0].confirmed_at is None


@pytest.mark.parametrize(
    "mutation",
    ("risk", "crossed_trading_day", "boundary_reset"),
)
def test_setup_snapshot_rejects_confirmed_only_projection_fields(
    mutation: str,
) -> None:
    snapshot = _evaluate((_bar(5),), bars_15m=(_bar(0),)).current_snapshot
    assert snapshot.stage is LifecycleStage.SETUP_ARMED
    if mutation == "risk":
        values = {
            "current_risk_codes": ("LOWER_TF_EMA21_BREACH",),
            "risk_progress": "watching",
            "lower_tf_risk_count": 1,
        }
    elif mutation == "crossed_trading_day":
        values = {"crossed_trading_day": True}
    else:
        values = {"boundary_reset": "segment_changed"}

    with pytest.raises(SubingLifecycleContractError):
        replace(snapshot, **values)


def test_segment_boundary_reset_requires_empty_idle_projection() -> None:
    snapshot = _evaluate((), bars_15m=()).current_snapshot

    reset = replace(snapshot, boundary_reset="segment_changed")

    assert reset.stage is LifecycleStage.IDLE
    assert reset.opportunity_key is None
    assert reset.current_risk_codes == ()


def test_closed_snapshot_keeps_close_reason_only_in_latest_transition() -> None:
    trace = _confirmed_closed_trace()

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.current_snapshot.current_risk_codes == ()
    assert trace.current_snapshot.latest_transition is not None
    assert trace.current_snapshot.latest_transition.reason_codes == (
        "OPPOSITE_DIRECTION_CONTEXT_CONFIRMED",
    )


def test_snapshot_rejects_risk_codes_in_inconsistent_stage_or_source() -> None:
    confirmed, risk = (_bar(minutes) for minutes in (15, 20))
    watching = _evaluate(
        (confirmed, risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(risk, BarFrequency.M5, ema21="101"),
        ),
        bars_15m=(confirmed,),
    ).current_snapshot
    assert watching.stage is LifecycleStage.CONTINUATION

    for values in (
        {"current_risk_codes": ("UNKNOWN_RISK",)},
        {"current_risk_codes": ("ANCHOR_EMA21_BREACH",)},
        {
            "current_risk_codes": ("ANCHOR_EMA21_BREACH",),
            "risk_progress": None,
            "lower_tf_risk_count": 0,
        },
    ):
        with pytest.raises(SubingLifecycleContractError):
            replace(watching, **values)

    closed = _confirmed_closed_trace().current_snapshot
    with pytest.raises(SubingLifecycleContractError):
        replace(
            closed,
            current_risk_codes=("OPPOSITE_DIRECTION_CONTEXT_CONFIRMED",),
        )


def test_short_lower_tf_risk_and_completed_anchor_recovery_are_mirrored() -> None:
    confirmed, first_risk, second_risk, recovery = (
        _bar(minutes) for minutes in (15, 20, 25, 30)
    )
    trace = _evaluate(
        (confirmed, first_risk, second_risk, recovery),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                direction=SubingDirection.SHORT,
                cross=MacdCross.DEAD,
                volume_ratio=Decimal("3"),
            ),
            _factor(
                first_risk,
                BarFrequency.M5,
                direction=SubingDirection.SHORT,
                ema21="99",
            ),
            _factor(
                second_risk,
                BarFrequency.M5,
                direction=SubingDirection.SHORT,
                ema21="99",
            ),
            _factor(recovery, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(confirmed, recovery),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15, direction=SubingDirection.SHORT),
            _factor(recovery, BarFrequency.M15, direction=SubingDirection.SHORT),
        ),
    )

    assert trace.snapshots[1].current_risk_codes == ("LOWER_TF_EMA21_BREACH",)
    assert trace.snapshots[1].risk_progress == "watching"
    assert trace.snapshots[2].stage is LifecycleStage.EXIT_RISK
    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert trace.transitions[-1].reason_codes == ("ANCHOR_RECOVERY_CONFIRMED",)


def test_exit_risk_rejects_lower_tf_code_with_zero_count() -> None:
    confirmed, first_risk, second_risk = (
        _bar(minutes) for minutes in (15, 20, 25)
    )
    snapshot = _evaluate(
        (confirmed, first_risk, second_risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
            _factor(second_risk, BarFrequency.M5, ema21="101"),
        ),
        bars_15m=(confirmed,),
    ).current_snapshot
    assert snapshot.stage is LifecycleStage.EXIT_RISK

    with pytest.raises(SubingLifecycleContractError):
        replace(snapshot, lower_tf_risk_count=0, risk_progress=None)


def test_exit_risk_rejects_mixed_anchor_and_lower_tf_codes() -> None:
    confirmed, first_risk, second_risk = (
        _bar(minutes) for minutes in (15, 20, 25)
    )
    snapshot = _evaluate(
        (confirmed, first_risk, second_risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
            _factor(second_risk, BarFrequency.M5, ema21="101"),
        ),
        bars_15m=(confirmed,),
    ).current_snapshot

    with pytest.raises(SubingLifecycleContractError):
        replace(
            snapshot,
            current_risk_codes=(
                "LOWER_TF_EMA21_BREACH",
                "ANCHOR_EMA21_BREACH",
            ),
            lower_tf_risk_count=1,
            risk_progress="watching",
        )


def test_same_day_entry_confirmation_does_not_claim_crossed_trading_day() -> None:
    boundary = _bar(15)
    snapshot = _evaluate(
        (boundary,),
        factors_5m=(
            _factor(
                boundary,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(boundary,),
    ).current_snapshot
    assert snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert snapshot.crossed_trading_day is False


def test_confirmed_closed_snapshot_may_retain_crossed_trading_day() -> None:
    confirmed = _bar(15)
    next_day = _bar(20, trading_day=date(2026, 8, 4))
    close_boundary = _bar(30, trading_day=date(2026, 8, 4))
    trace = _evaluate(
        (confirmed, next_day, close_boundary),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(next_day, BarFrequency.M5),
            _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(confirmed, close_boundary),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(close_boundary, BarFrequency.M15, direction=SubingDirection.SHORT),
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert trace.current_snapshot.crossed_trading_day is True
