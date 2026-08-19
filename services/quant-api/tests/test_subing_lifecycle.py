from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    EntryProgress,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleContractError,
    SubingLifecycleState,
    SubingLifecycleStateError,
    SubingOpportunityKey,
    evaluate_subing_lifecycle,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_calibration import SubingCalibration
from app.market_data.subing_lifecycle_policy import (
    SubingLifecyclePolicy,
    load_subing_lifecycle_policy,
)
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
)


_SEGMENT_START = date(2026, 8, 3)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


def _bar(
    minutes: int,
    *,
    close: str = "100",
    high: str | None = None,
    low: str | None = None,
    trading_day: date = _SEGMENT_START,
) -> CanonicalBar:
    close_value = Decimal(close)
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=minutes),
        trading_day=trading_day,
        open=close_value,
        high=Decimal(high) if high is not None else close_value + Decimal("1"),
        low=Decimal(low) if low is not None else close_value - Decimal("1"),
        close=close_value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )


def _factor(
    bar: CanonicalBar,
    timeframe: BarFrequency,
    *,
    direction: SubingDirection = SubingDirection.LONG,
    cross: MacdCross = MacdCross.NONE,
    contract: str = "JM2701",
    segment_start: date = _SEGMENT_START,
    status: SubingFactorStatus = SubingFactorStatus.READY,
    volume_ratio: Decimal | None = Decimal("1"),
) -> SubingFactorResult:
    if status is SubingFactorStatus.INSUFFICIENT_DATA:
        return SubingFactorResult(status=status, snapshot=None)
    long = direction is SubingDirection.LONG
    price_side = PriceSide.ABOVE if long else PriceSide.BELOW
    slope5 = Decimal("2") if long else Decimal("-2")
    slope10 = Decimal("1") if long else Decimal("-1")
    ema21 = bar.close - Decimal("1") if long else bar.close + Decimal("1")
    return SubingFactorResult(
        status=SubingFactorStatus.READY,
        snapshot=SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start,
            bar_source="canonical",
            close=bar.close,
            ema21=ema21,
            price_side=price_side,
            slope_5_raw=slope5,
            slope_10_raw=slope10,
            slope_5_bps_per_bar=slope5,
            slope_10_bps_per_bar=slope10,
            macd_dif=Decimal("1"),
            macd_dea=Decimal("1"),
            macd_histogram=Decimal("0"),
            macd_cross=cross,
            macd_cross_level=Decimal("1"),
            macd_zero_distance_abs=Decimal("1"),
            macd_zero_distance_bps=Decimal("1"),
            volume=bar.volume,
            previous_volume=bar.volume,
            volume_ratio_prev=volume_ratio,
        ),
    )


def _accepted_calibration() -> SubingCalibration:
    return SubingCalibration(
        calibration_id="subing_intraday_v1",
        accepted_timeframes=frozenset({BarFrequency.M5, BarFrequency.M15}),
        slope_flat_threshold_bps_per_bar={
            BarFrequency.M5: Decimal("0.688190651160584793944957992"),
            BarFrequency.M15: Decimal("1.329531078893356968545882036"),
        },
    )


def _evaluate(
    bars_5m: tuple[CanonicalBar, ...],
    *,
    factors_5m: tuple[SubingFactorResult, ...] | None = None,
    bars_15m: tuple[CanonicalBar, ...],
    factors_15m: tuple[SubingFactorResult, ...] | None = None,
    calibration: SubingCalibration | None = None,
    policy: SubingLifecyclePolicy | None = None,
):
    return evaluate_subing_lifecycle(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=bars_5m,
        factors_5m=(
            factors_5m
            if factors_5m is not None
            else tuple(_factor(bar, BarFrequency.M5) for bar in bars_5m)
        ),
        bars_15m=bars_15m,
        factors_15m=(
            factors_15m
            if factors_15m is not None
            else tuple(_factor(bar, BarFrequency.M15) for bar in bars_15m)
        ),
        calibration=calibration or _accepted_calibration(),
        policy=policy or load_subing_lifecycle_policy(),
    )


def _long_pivot_prefix() -> tuple[CanonicalBar, ...]:
    return (
        _bar(5, close="100", high="101", low="99"),
        _bar(10, close="100", high="102", low="99"),
        _bar(15, close="105", high="110", low="100"),
        _bar(20, close="102", high="103", low="99"),
        _bar(25, close="108", high="109", low="101"),
        _bar(30, close="111", high="115", low="109"),
    )


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


def test_lifecycle_uses_each_completed_5m_bar_as_its_only_top_level_clock() -> None:
    bars_5m = tuple(_bar(minutes) for minutes in (5, 10, 15, 20))
    bars_15m = (_bar(0), _bar(15))

    trace = _evaluate(bars_5m, bars_15m=bars_15m)

    assert tuple(snapshot.observed_at for snapshot in trace.snapshots) == tuple(
        bar.bar_end for bar in bars_5m
    )
    assert tuple(snapshot.anchor_bar_end for snapshot in trace.snapshots) == (
        bars_15m[0].bar_end,
        bars_15m[0].bar_end,
        bars_15m[1].bar_end,
        bars_15m[1].bar_end,
    )
    assert len({transition.transition_at for transition in trace.transitions}) == len(
        trace.transitions
    )
    assert trace.confirmed_transitions == trace.transitions


def test_same_15m_boundary_is_evaluated_once_not_as_a_second_transition() -> None:
    boundary = _bar(15)

    trace = _evaluate((boundary,), bars_15m=(boundary,))

    assert len(trace.snapshots) == 1
    assert len(trace.transitions) == 1
    assert trace.transitions[0].transition_at == boundary.bar_end
    assert trace.current_snapshot.stage is LifecycleStage.SETUP_ARMED


def test_future_15m_factor_is_never_visible_to_an_earlier_5m_boundary() -> None:
    bars_5m = (_bar(5), _bar(10))
    completed_anchor = _bar(0)
    future_anchor = _bar(15)
    completed_only = _evaluate(bars_5m, bars_15m=(completed_anchor,))
    with_future = _evaluate(
        bars_5m,
        bars_15m=(completed_anchor, future_anchor),
        factors_15m=(
            _factor(completed_anchor, BarFrequency.M15),
            _factor(
                future_anchor,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
            ),
        ),
    )

    assert with_future.snapshots == completed_only.snapshots
    assert with_future.transitions == completed_only.transitions


def test_missing_completed_15m_anchor_is_unavailable_without_a_transition() -> None:
    boundary = _bar(5)
    future_anchor = _bar(15)

    trace = _evaluate((boundary,), bars_15m=(future_anchor,))

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_15M_ANCHOR_UNAVAILABLE"
    assert trace.current_snapshot.stage is LifecycleStage.IDLE
    assert trace.transitions == ()


@pytest.mark.parametrize(
    "direction",
    (SubingDirection.LONG, SubingDirection.SHORT),
)
def test_direction_context_requires_both_timeframes_to_pass_accepted_thresholds(
    direction: SubingDirection,
) -> None:
    boundary = _bar(15)

    trace = _evaluate(
        (boundary,),
        factors_5m=(_factor(boundary, BarFrequency.M5, direction=direction),),
        bars_15m=(boundary,),
        factors_15m=(_factor(boundary, BarFrequency.M15, direction=direction),),
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.READY
    assert trace.current_snapshot.direction is direction
    assert trace.current_snapshot.stage is LifecycleStage.SETUP_ARMED


def test_missing_direction_alignment_is_ready_none_idle() -> None:
    boundary = _bar(15)

    trace = _evaluate(
        (boundary,),
        factors_5m=(_factor(boundary, BarFrequency.M5),),
        bars_15m=(boundary,),
        factors_15m=(
            _factor(
                boundary,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
            ),
        ),
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.READY
    assert trace.current_snapshot.direction is SubingDirection.NONE
    assert trace.current_snapshot.stage is LifecycleStage.IDLE
    assert trace.transitions == ()


def test_factor_identity_mismatch_is_unavailable_not_idle() -> None:
    boundary = _bar(15)

    trace = _evaluate(
        (boundary,),
        factors_5m=(
            _factor(boundary, BarFrequency.M5, contract="RB2701"),
        ),
        bars_15m=(boundary,),
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_FACTOR_IDENTITY_MISMATCH"
    assert trace.transitions == ()


def test_missing_accepted_calibration_is_unavailable() -> None:
    boundary = _bar(15)

    trace = _evaluate(
        (boundary,),
        bars_15m=(boundary,),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_CALIBRATION_INVALID"


def test_same_id_calibration_threshold_drift_is_unavailable() -> None:
    boundary = _bar(15)
    accepted = _accepted_calibration()
    drifted_thresholds = dict(accepted.slope_flat_threshold_bps_per_bar)
    drifted_thresholds[BarFrequency.M5] += Decimal("0.000000000000000000000000001")
    drifted = SubingCalibration(
        calibration_id=accepted.calibration_id,
        accepted_timeframes=accepted.accepted_timeframes,
        slope_flat_threshold_bps_per_bar=drifted_thresholds,
    )

    trace = _evaluate(
        (boundary,),
        bars_15m=(boundary,),
        calibration=drifted,
    )

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_CALIBRATION_INVALID"


def test_setup_origin_is_the_first_boundary_departing_idle() -> None:
    first = _bar(5)
    second = _bar(10)
    anchor = _bar(0)

    trace = _evaluate(
        (first, second),
        factors_5m=(
            _factor(first, BarFrequency.M5, direction=SubingDirection.SHORT),
            _factor(second, BarFrequency.M5),
        ),
        bars_15m=(anchor,),
    )

    assert trace.snapshots[0].stage is LifecycleStage.IDLE
    assert trace.current_snapshot.opportunity_key is not None
    assert trace.current_snapshot.opportunity_key.origin_at == second.bar_end


def test_idle_formal_v1_match_confirms_with_origin_at_confirmed_boundary() -> None:
    boundary = _bar(15)

    trace = _evaluate(
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
    )

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert snapshot.confirmed_at == boundary.bar_end
    assert snapshot.formal_v1_matched is True
    assert snapshot.opportunity_key is not None
    assert snapshot.opportunity_key.origin_at == boundary.bar_end
    assert len(trace.transitions) == 1
    assert trace.transitions[0].from_stage is LifecycleStage.IDLE


def test_direct_formal_without_trigger_rejects_positive_hold_count() -> None:
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

    assert snapshot.trigger_kind is None
    with pytest.raises(SubingLifecycleContractError):
        replace(snapshot, hold_count=1)


def test_direct_formal_without_trigger_rejects_completed_hold_count() -> None:
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

    assert snapshot.trigger_kind is None
    with pytest.raises(SubingLifecycleContractError):
        replace(snapshot, hold_count=snapshot.hold_required)


def test_closed_direction_is_not_reused_for_a_new_opposite_opportunity() -> None:
    first, close_boundary, new_boundary = (_bar(value) for value in (5, 10, 15))
    anchor_long = _bar(0)
    anchor_short = _bar(10)

    trace = _evaluate(
        (first, close_boundary, new_boundary),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
            _factor(new_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(anchor_long, anchor_short),
        factors_15m=(
            _factor(anchor_long, BarFrequency.M15),
            _factor(
                anchor_short,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
            ),
        ),
    )

    old_key = trace.snapshots[0].opportunity_key
    assert old_key is not None
    assert trace.snapshots[1].stage is LifecycleStage.CLOSED
    assert trace.snapshots[1].opportunity_key == old_key
    new_key = trace.snapshots[2].opportunity_key
    assert new_key is not None
    assert new_key != old_key
    assert new_key.direction is SubingDirection.SHORT
    assert new_key.origin_at == new_boundary.bar_end


@pytest.mark.parametrize(
    "trigger_timeframe",
    (BarFrequency.M5, BarFrequency.M15),
)
def test_same_direction_macd_cross_starts_momentum_hold_at_one(
    trigger_timeframe: BarFrequency,
) -> None:
    first, trigger = (_bar(value) for value in (5, 15))
    anchor_first, anchor_trigger = (_bar(value) for value in (0, 15))
    factors_5m = (
        _factor(first, BarFrequency.M5),
        _factor(
            trigger,
            BarFrequency.M5,
            cross=(
                MacdCross.GOLDEN
                if trigger_timeframe is BarFrequency.M5
                else MacdCross.NONE
            ),
        ),
    )
    factors_15m = (
        _factor(anchor_first, BarFrequency.M15),
        _factor(
            anchor_trigger,
            BarFrequency.M15,
            cross=(
                MacdCross.GOLDEN
                if trigger_timeframe is BarFrequency.M15
                else MacdCross.NONE
            ),
        ),
    )

    trace = _evaluate(
        (first, trigger),
        factors_5m=factors_5m,
        bars_15m=(anchor_first, anchor_trigger),
        factors_15m=factors_15m,
    )

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.SETUP_ARMED
    assert snapshot.entry_progress is EntryProgress.HOLD_CONFIRMING
    assert snapshot.trigger_kind == "macd_cross"
    assert snapshot.trigger_timeframe is trigger_timeframe
    assert snapshot.triggered_at == trigger.bar_end
    assert snapshot.hold_count == 1


def test_momentum_hold_confirms_after_three_evaluable_5m_boundaries() -> None:
    bars_5m = tuple(_bar(value) for value in (5, 10, 15, 20))
    anchor = _bar(0)
    factors_5m = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == 1 else MacdCross.NONE,
        )
        for index, bar in enumerate(bars_5m)
    )

    trace = _evaluate(
        bars_5m,
        factors_5m=factors_5m,
        bars_15m=(anchor,),
    )

    assert tuple(snapshot.hold_count for snapshot in trace.snapshots[1:]) == (1, 2, 3)
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.MOMENTUM_HOLD
    assert trace.current_snapshot.confirmed_at == bars_5m[-1].bar_end


def test_unavailable_boundary_pauses_momentum_hold_counter() -> None:
    bars_5m = tuple(_bar(value) for value in (5, 10, 15, 20, 25))
    anchor = _bar(0)
    factors = tuple(
        (
            _factor(bar, BarFrequency.M5, status=SubingFactorStatus.INSUFFICIENT_DATA)
            if index == 2
            else _factor(
                bar,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN if index == 1 else MacdCross.NONE,
            )
        )
        for index, bar in enumerate(bars_5m)
    )

    trace = _evaluate(
        bars_5m,
        factors_5m=factors,
        bars_15m=(anchor,),
    )

    unavailable = trace.snapshots[2]
    assert unavailable.availability is LifecycleAvailability.UNAVAILABLE
    assert unavailable.entry_progress is EntryProgress.HOLD_CONFIRMING
    assert unavailable.hold_count == 1
    assert trace.snapshots[3].hold_count == 2
    assert trace.current_snapshot.hold_count == 3
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED


@pytest.mark.parametrize("failure", ("opposite_cross", "persistence"))
def test_momentum_hold_closes_on_hard_failure(failure: str) -> None:
    first, trigger, failure_bar = (_bar(value) for value in (5, 10, 15))
    anchor = _bar(0)
    failed_factor = (
        _factor(failure_bar, BarFrequency.M5, cross=MacdCross.DEAD)
        if failure == "opposite_cross"
        else _factor(
            failure_bar,
            BarFrequency.M5,
            direction=SubingDirection.SHORT,
        )
    )

    trace = _evaluate(
        (first, trigger, failure_bar),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(trigger, BarFrequency.M5, cross=MacdCross.GOLDEN),
            failed_factor,
        ),
        bars_15m=(anchor,),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("MOMENTUM_HOLD_FAILED",)
    assert trace.current_snapshot.hold_count == 1


def test_pivot_break_requires_prior_confirmation_and_a_true_close_cross() -> None:
    prefix = _long_pivot_prefix()
    intrabar_only = CanonicalBar(
        bar_end=prefix[-1].bar_end,
        trading_day=prefix[-1].trading_day,
        open=Decimal("108"),
        high=Decimal("115"),
        low=Decimal("108"),
        close=Decimal("110"),
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )
    bars = (*prefix[:-1], intrabar_only)

    trace = _evaluate(bars, bars_15m=(_bar(0),))

    assert trace.current_snapshot.entry_progress is EntryProgress.WAITING_TRIGGER
    assert trace.current_snapshot.bound_reference_pivot is None


def test_pivot_break_beats_macd_and_freezes_reference_at_trigger() -> None:
    bars = _long_pivot_prefix()
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE,
        )
        for index, bar in enumerate(bars)
    )

    trace = _evaluate(
        bars,
        factors_5m=factors,
        bars_15m=(_bar(0),),
    )

    snapshot = trace.current_snapshot
    pivot = snapshot.bound_reference_pivot
    assert pivot is not None
    assert pivot.price == Decimal("110")
    assert pivot.confirmed_at == bars[4].bar_end
    assert pivot.confirmed_at < snapshot.triggered_at
    assert snapshot.trigger_kind == "pivot_break"
    assert snapshot.trigger_timeframe is BarFrequency.M5
    assert snapshot.hold_count == 1
    assert snapshot.rebreak_reference_price == Decimal("115")


def test_formal_v1_has_priority_over_simultaneous_pivot_break() -> None:
    bars = _long_pivot_prefix()
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE,
            volume_ratio=(Decimal("3") if index == len(bars) - 1 else Decimal("1")),
        )
        for index, bar in enumerate(bars)
    )

    trace = _evaluate(bars, factors_5m=factors, bars_15m=(_bar(0),))

    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert trace.current_snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert trace.current_snapshot.bound_reference_pivot is None


def test_formal_v1_preempts_active_momentum_hold_with_prior_trigger_evidence() -> None:
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

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert snapshot.confirmed_at == formal.bar_end
    assert snapshot.trigger_kind == "macd_cross"
    assert snapshot.triggered_at == trigger.bar_end
    assert snapshot.triggered_at < snapshot.confirmed_at
    assert snapshot.hold_count == 1
    for inconsistent in (
        {"triggered_at": snapshot.confirmed_at},
        {"hold_count": 0},
        {"hold_count": snapshot.hold_required},
    ):
        with pytest.raises(SubingLifecycleContractError):
            replace(snapshot, **inconsistent)


def test_formal_v1_preempts_active_pivot_hold_with_prior_trigger_evidence() -> None:
    prefix = _long_pivot_prefix()
    formal = _bar(35, close="112", high="113", low="111")
    bars = (*prefix, formal)
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE,
            volume_ratio=(Decimal("3") if index == len(bars) - 1 else Decimal("1")),
        )
        for index, bar in enumerate(bars)
    )

    trace = _evaluate(bars, factors_5m=factors, bars_15m=(_bar(0),))

    snapshot = trace.current_snapshot
    assert snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert snapshot.confirmation_source is ConfirmationSource.FORMAL_V1
    assert snapshot.confirmed_at == formal.bar_end
    assert snapshot.trigger_kind == "pivot_break"
    assert snapshot.triggered_at == prefix[-1].bar_end
    assert snapshot.triggered_at < snapshot.confirmed_at
    assert snapshot.hold_count == 1
    assert snapshot.bound_reference_pivot is not None


def test_pivot_break_hold_confirms_after_three_bars_with_frozen_pivot() -> None:
    prefix = _long_pivot_prefix()
    bars = (
        *prefix,
        _bar(35, close="112", high="113", low="111"),
        _bar(40, close="113", high="114", low="112"),
    )

    trace = _evaluate(bars, bars_15m=(_bar(0),))

    assert trace.snapshots[-3].hold_count == 1
    assert trace.snapshots[-2].hold_count == 2
    assert trace.current_snapshot.hold_count == 3
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert (
        trace.current_snapshot.confirmation_source
        is ConfirmationSource.PIVOT_BREAK_HOLD
    )
    assert trace.current_snapshot.bound_reference_pivot is not None
    assert trace.current_snapshot.bound_reference_pivot.price == Decimal("110")


def test_legal_retest_beats_hold_increment_and_rebreak_uses_trigger_high() -> None:
    prefix = _long_pivot_prefix()
    retest = _bar(35, close="111", high="112", low="109")
    below_trigger_high = _bar(40, close="114", high="114", low="111")
    rebreak = _bar(45, close="116", high="117", low="113")
    bars = (*prefix, retest, below_trigger_high, rebreak)

    trace = _evaluate(bars, bars_15m=(_bar(0),))

    retest_snapshot = trace.snapshots[-3]
    assert retest_snapshot.entry_progress is EntryProgress.RETEST_CONFIRMING
    assert retest_snapshot.hold_count == 1
    assert retest_snapshot.retest_at == retest.bar_end
    assert retest_snapshot.retest_rebreak_count == 0
    assert trace.snapshots[-2].retest_rebreak_count == 1
    assert trace.current_snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    assert (
        trace.current_snapshot.confirmation_source
        is ConfirmationSource.PIVOT_RETEST_REBREAK
    )
    assert trace.current_snapshot.rebreak_reference_price == Decimal("115")


@pytest.mark.parametrize(
    ("tail", "expected_reason"),
    (
        (
            (
                _bar(35, close="111", high="112", low="109"),
                _bar(40, close="112", high="113", low="111"),
                _bar(45, close="113", high="114", low="112"),
                _bar(50, close="114", high="114", low="113"),
            ),
            "RETEST_REBREAK_TIMEOUT",
        ),
        (
            (
                _bar(35, close="111", high="112", low="109"),
                _bar(40, close="109", high="111", low="108"),
            ),
            "PIVOT_RETEST_INVALIDATED",
        ),
    ),
)
def test_pivot_retest_closes_on_three_bar_timeout_or_hard_invalidation(
    tail: tuple[CanonicalBar, ...],
    expected_reason: str,
) -> None:
    trace = _evaluate((*_long_pivot_prefix(), *tail), bars_15m=(_bar(0),))

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == (expected_reason,)


def test_unconfirmed_rollover_waits_for_first_evaluable_later_day_boundary() -> None:
    next_day = date(2026, 8, 4)
    first = _bar(5)
    unavailable = _bar(24 * 60 + 5, trading_day=next_day)
    evaluable = _bar(24 * 60 + 10, trading_day=next_day)
    first_anchor = _bar(0)
    next_day_anchor = _bar(24 * 60, trading_day=next_day)

    trace = _evaluate(
        (first, unavailable, evaluable),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(
                unavailable,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
            _factor(evaluable, BarFrequency.M5),
        ),
        bars_15m=(first_anchor, next_day_anchor),
    )

    assert trace.snapshots[1].availability is LifecycleAvailability.UNAVAILABLE
    assert trace.snapshots[1].stage is LifecycleStage.SETUP_ARMED
    assert trace.snapshots[1].opportunity_key == trace.snapshots[0].opportunity_key
    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == (
        "UNCONFIRMED_TRADING_DAY_ROLLOVER",
    )
    assert trace.current_snapshot.opportunity_key == trace.snapshots[0].opportunity_key


def test_next_day_rollover_preempts_simultaneous_formal_v1_match() -> None:
    next_day = date(2026, 8, 4)
    first = _bar(5)
    next_day_boundary = _bar(24 * 60 + 15, trading_day=next_day)
    first_anchor = _bar(0)
    next_day_anchor = _bar(24 * 60 + 15, trading_day=next_day)

    trace = _evaluate(
        (first, next_day_boundary),
        factors_5m=(
            _factor(first, BarFrequency.M5),
            _factor(
                next_day_boundary,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(first_anchor, next_day_anchor),
    )

    old_key = trace.snapshots[0].opportunity_key
    assert old_key is not None
    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.current_snapshot.opportunity_key == old_key
    assert trace.current_snapshot.confirmation_source is None
    assert trace.current_snapshot.confirmed_at is None
    assert trace.transitions[-1].reason_codes == (
        "UNCONFIRMED_TRADING_DAY_ROLLOVER",
    )


def test_previous_trading_day_pivot_cannot_trigger_a_new_day_opportunity() -> None:
    next_day = date(2026, 8, 4)
    prior_day = _long_pivot_prefix()[:-1]
    rollover = _bar(
        24 * 60 + 5,
        close="108",
        high="109",
        low="107",
        trading_day=next_day,
    )
    new_setup = _bar(
        24 * 60 + 10,
        close="108",
        high="109",
        low="107",
        trading_day=next_day,
    )
    old_level_cross = _bar(
        24 * 60 + 15,
        close="111",
        high="112",
        low="108",
        trading_day=next_day,
    )
    next_day_anchor = _bar(24 * 60, trading_day=next_day)

    trace = _evaluate(
        (*prior_day, rollover, new_setup, old_level_cross),
        bars_15m=(_bar(0), next_day_anchor),
    )

    assert trace.current_snapshot.stage is LifecycleStage.SETUP_ARMED
    assert trace.current_snapshot.entry_progress is EntryProgress.WAITING_TRIGGER
    assert trace.current_snapshot.bound_reference_pivot is None


def test_corrupted_policy_identity_is_unavailable() -> None:
    boundary = _bar(15)
    policy = load_subing_lifecycle_policy()
    object.__setattr__(policy, "policy_id", "drifted_same_object")

    trace = _evaluate((boundary,), bars_15m=(boundary,), policy=policy)

    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.unavailable_reason == "SUBING_LIFECYCLE_POLICY_INVALID"


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
    assert (trace.symbol, trace.contract) == ("RB", "RB2701")


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
