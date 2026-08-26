from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleContractError,
)
from app.market_data.domain import BarFrequency
from app.market_data.subing_calibration import SubingCalibration
from app.market_data.subing_research import (
    MacdCross,
    SubingDirection,
    SubingFactorStatus,
)
from research.subing_lifecycle_fixtures import (
    _accepted_calibration,
    _bar,
    _evaluate,
    _evaluate_raw,
    _factor,
    _long_pivot_prefix,
    _short_pivot_prefix,
    _stream_lifecycle_prefixes,
    _with_lifecycle_reset,
)


_SEGMENT_START = date(2026, 8, 3)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


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


def test_empty_segment_emits_one_idle_segment_reset_diagnostic() -> None:
    trace = _evaluate_raw((), bars_15m=())

    assert trace.snapshots == ()
    assert trace.transitions == ()
    assert trace.completed_opportunities == ()
    assert trace.current_snapshot.stage is LifecycleStage.IDLE
    assert trace.current_snapshot.boundary_reset == "segment_changed"


def test_first_evaluable_boundary_is_reset_only_then_lifecycle_starts() -> None:
    reset_boundary, evaluable = (_bar(minutes) for minutes in (5, 10))
    trace = _evaluate_raw((reset_boundary, evaluable), bars_15m=(_bar(0),))

    reset, current = trace.snapshots
    assert reset.availability is LifecycleAvailability.READY
    assert reset.stage is LifecycleStage.IDLE
    assert reset.boundary_reset == "segment_changed"
    assert reset.opportunity_key is None
    assert reset.latest_transition is None
    assert reset.current_risk_codes == ()
    assert reset.crossed_trading_day is False
    assert len(trace.transitions) == 1
    assert trace.transitions[0].transition_at == evaluable.bar_end
    assert current.stage is LifecycleStage.SETUP_ARMED
    assert current.boundary_reset is None


def test_unavailable_warmup_boundary_carries_only_first_segment_reset() -> None:
    warmup, evaluable = (_bar(minutes) for minutes in (5, 10))
    trace = _evaluate_raw(
        (warmup, evaluable),
        factors_5m=(
            _factor(
                warmup,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
            _factor(evaluable, BarFrequency.M5),
        ),
        bars_15m=(_bar(0),),
    )

    reset, current = trace.snapshots
    assert reset.availability is LifecycleAvailability.UNAVAILABLE
    assert reset.stage is LifecycleStage.IDLE
    assert reset.boundary_reset == "segment_changed"
    assert reset.opportunity_key is None
    assert reset.latest_transition is None
    assert current.availability is LifecycleAvailability.READY
    assert current.stage is LifecycleStage.SETUP_ARMED
    assert current.boundary_reset is None
    assert sum(
        snapshot.boundary_reset == "segment_changed" for snapshot in trace.snapshots
    ) == 1


def test_reset_boundary_remains_valid_pivot_left_context() -> None:
    bars = _long_pivot_prefix()[:5]

    trace = _evaluate_raw(bars, bars_15m=(_bar(0),))

    assert trace.snapshots[0].boundary_reset == "segment_changed"
    assert trace.snapshots[0].stage is LifecycleStage.IDLE
    assert trace.transitions[0].transition_at == bars[1].bar_end
    assert len(trace.confirmed_pivots) == 1
    assert trace.confirmed_pivots[0].pivot_time == bars[2].bar_end
    assert trace.confirmed_pivots[0].confirmed_at == bars[4].bar_end


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


def test_entry_confirmed_exists_only_on_its_confirmation_boundary() -> None:
    confirmed = _bar(15)
    next_boundary = _bar(20)

    trace = _evaluate(
        (confirmed, next_boundary),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(next_boundary, BarFrequency.M5),
        ),
        bars_15m=(confirmed,),
    )

    assert tuple(snapshot.stage for snapshot in trace.snapshots) == (
        LifecycleStage.ENTRY_CONFIRMED,
        LifecycleStage.CONTINUATION,
    )
    assert trace.transitions[-1].from_stage is LifecycleStage.ENTRY_CONFIRMED
    assert trace.transitions[-1].to_stage is LifecycleStage.CONTINUATION
    assert trace.transitions[-1].reason_codes == ("CONFIRMED_TREND_CONTINUES",)


@pytest.mark.parametrize(
    ("risk_code", "factor_kwargs"),
    (
        ("LOWER_TF_EMA21_BREACH", {"ema21": "101"}),
        ("LOWER_TF_SLOPE5_REVERSAL", {"slope5": "-1"}),
        ("LOWER_TF_MACD_OPPOSITE_CROSS", {"cross": MacdCross.DEAD}),
    ),
)
def test_two_consecutive_lower_tf_risks_enter_exit_risk(
    risk_code: str,
    factor_kwargs: dict[str, object],
) -> None:
    confirmed, first_risk, second_risk = (
        _bar(minutes) for minutes in (15, 20, 25)
    )

    trace = _evaluate(
        (confirmed, first_risk, second_risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, **factor_kwargs),  # type: ignore[arg-type]
            _factor(second_risk, BarFrequency.M5, **factor_kwargs),  # type: ignore[arg-type]
        ),
        bars_15m=(confirmed,),
    )

    watching = trace.snapshots[1]
    assert watching.stage is LifecycleStage.CONTINUATION
    assert watching.current_risk_codes == (risk_code,)
    assert watching.risk_progress == "watching"
    assert watching.lower_tf_risk_count == 1
    assert trace.current_snapshot.stage is LifecycleStage.EXIT_RISK
    assert trace.current_snapshot.current_risk_codes == (risk_code,)
    assert trace.current_snapshot.lower_tf_risk_count == 2
    assert trace.transitions[-1].reason_codes == (risk_code,)


def test_two_confirmed_lower_tf_risks_require_exit_risk_stage() -> None:
    confirmed = _bar(15)
    first_risk = _bar(20)
    watching = _evaluate(
        (confirmed, first_risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
        ),
        bars_15m=(confirmed,),
    ).current_snapshot

    with pytest.raises(SubingLifecycleContractError):
        replace(
            watching,
            lower_tf_risk_count=2,
            risk_progress=None,
        )


def test_clean_lower_tf_boundary_resets_risk_count() -> None:
    confirmed, first_risk, clean, risk_after_reset = (
        _bar(minutes) for minutes in (15, 20, 25, 30)
    )

    trace = _evaluate(
        (confirmed, first_risk, clean, risk_after_reset),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
            _factor(clean, BarFrequency.M5),
            _factor(risk_after_reset, BarFrequency.M5, ema21="101"),
        ),
        bars_15m=(confirmed,),
    )

    assert trace.snapshots[1].lower_tf_risk_count == 1
    assert trace.snapshots[2].lower_tf_risk_count == 0
    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert trace.current_snapshot.lower_tf_risk_count == 1


def test_unavailable_boundary_pauses_lower_tf_risk_count() -> None:
    confirmed, first_risk, unavailable, second_risk = (
        _bar(minutes) for minutes in (15, 20, 25, 30)
    )

    trace = _evaluate(
        (confirmed, first_risk, unavailable, second_risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
            _factor(
                unavailable,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
            _factor(second_risk, BarFrequency.M5, ema21="101"),
        ),
        bars_15m=(confirmed,),
    )

    paused = trace.snapshots[2]
    assert paused.availability is LifecycleAvailability.UNAVAILABLE
    assert paused.lower_tf_risk_count == 1
    assert paused.risk_progress == "watching"
    assert trace.current_snapshot.stage is LifecycleStage.EXIT_RISK
    assert trace.current_snapshot.lower_tf_risk_count == 2


def test_unavailable_snapshot_retains_the_last_evaluable_stage_and_time() -> None:
    confirmed, transition_boundary, stable_boundary, unavailable = (
        _bar(minutes) for minutes in (15, 20, 25, 30)
    )

    trace = _evaluate(
        (confirmed, transition_boundary, stable_boundary, unavailable),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(transition_boundary, BarFrequency.M5),
            _factor(stable_boundary, BarFrequency.M5),
            _factor(
                unavailable,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
        ),
        bars_15m=(confirmed,),
    )

    assert trace.snapshots[2].latest_transition == trace.transitions[-1]
    assert trace.snapshots[2].last_confirmed_stage is LifecycleStage.CONTINUATION
    assert trace.snapshots[2].last_confirmed_at == stable_boundary.bar_end
    assert trace.current_snapshot.availability is LifecycleAvailability.UNAVAILABLE
    assert trace.current_snapshot.last_confirmed_stage is LifecycleStage.CONTINUATION
    assert trace.current_snapshot.last_confirmed_at == stable_boundary.bar_end


def test_trigger_pivot_reentry_remains_the_existing_lower_tf_risk() -> None:
    confirmed_bars = (
        *_long_pivot_prefix(),
        _bar(35, close="112", high="113", low="111"),
        _bar(40, close="113", high="114", low="112"),
    )
    reentry = _bar(45, close="109", high="110", low="108")

    trace = _evaluate((*confirmed_bars, reentry), bars_15m=(_bar(0),))

    assert trace.snapshots[-2].confirmation_source is ConfirmationSource.PIVOT_BREAK_HOLD
    assert trace.snapshots[-2].trigger_reference_pivot is not None
    assert trace.snapshots[-2].trigger_reference_pivot.price == Decimal("110")
    assert trace.snapshots[-2].bound_reference_pivot is None
    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert trace.current_snapshot.current_risk_codes == (
        "LOWER_TF_BOUND_PIVOT_REENTRY",
    )
    assert trace.current_snapshot.lower_tf_risk_count == 1


@pytest.mark.parametrize(
    ("risk_code", "factor_5m_kwargs", "factor_15m_kwargs"),
    (
        ("ANCHOR_EMA21_BREACH", {}, {"ema21": "101"}),
        ("ANCHOR_SLOPE5_REVERSAL", {}, {"slope5": "-1"}),
        ("ANCHOR_MACD_OPPOSITE_CROSS", {}, {"cross": MacdCross.DEAD}),
        ("TIMEFRAME_ALIGNMENT_LOST", {"slope5": "0.5"}, {}),
    ),
)
def test_completed_15m_soft_risk_enters_exit_risk_immediately(
    risk_code: str,
    factor_5m_kwargs: dict[str, object],
    factor_15m_kwargs: dict[str, object],
) -> None:
    confirmed = _bar(15)
    anchor_risk = _bar(30)

    trace = _evaluate(
        (confirmed, anchor_risk),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(anchor_risk, BarFrequency.M5, **factor_5m_kwargs),  # type: ignore[arg-type]
        ),
        bars_15m=(confirmed, anchor_risk),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(anchor_risk, BarFrequency.M15, **factor_15m_kwargs),  # type: ignore[arg-type]
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.EXIT_RISK
    assert risk_code in trace.current_snapshot.current_risk_codes
    assert trace.current_snapshot.lower_tf_risk_count == 0
    assert trace.transitions[-1].reason_codes == (risk_code,)


def test_completed_anchor_risk_is_not_synthesized_on_a_later_5m_boundary() -> None:
    confirmed = _bar(5)
    clean = _bar(10)
    skipped_anchor_boundary = _bar(15)
    later_5m = _bar(20)

    trace = _evaluate(
        (confirmed, clean, later_5m),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(clean, BarFrequency.M5),
            _factor(later_5m, BarFrequency.M5),
        ),
        bars_15m=(_bar(0), skipped_anchor_boundary),
        factors_15m=(
            _factor(_bar(0), BarFrequency.M15),
            _factor(skipped_anchor_boundary, BarFrequency.M15, slope5="-1"),
        ),
    )

    assert trace.current_snapshot.anchor_bar_end == skipped_anchor_boundary.bar_end
    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert trace.current_snapshot.current_risk_codes == ()
    assert all(
        transition.reason_codes != ("ANCHOR_SLOPE5_REVERSAL",)
        for transition in trace.transitions
    )


def test_exit_risk_recovers_only_on_a_clean_completed_15m_boundary() -> None:
    confirmed = _bar(15)
    risk = _bar(30)
    non_anchor_clean = _bar(40)
    recovery = _bar(45)

    trace = _evaluate(
        (confirmed, risk, non_anchor_clean, recovery),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(risk, BarFrequency.M5),
            _factor(non_anchor_clean, BarFrequency.M5),
            _factor(recovery, BarFrequency.M5),
        ),
        bars_15m=(confirmed, risk, recovery),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(risk, BarFrequency.M15, slope5="-1"),
            _factor(recovery, BarFrequency.M15),
        ),
    )

    assert trace.snapshots[1].stage is LifecycleStage.EXIT_RISK
    assert trace.snapshots[2].stage is LifecycleStage.EXIT_RISK
    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert trace.current_snapshot.current_risk_codes == ()
    assert trace.transitions[-1].reason_codes == ("ANCHOR_RECOVERY_CONFIRMED",)


@pytest.mark.parametrize(
    ("factor_5m_kwargs", "factor_15m_kwargs"),
    (
        ({}, {"ema21": "101"}),
        ({}, {"slope10": "-1"}),
        ({}, {"cross": MacdCross.DEAD}),
        ({"ema21": "101"}, {}),
    ),
)
def test_exit_risk_recovery_requires_every_approved_condition(
    factor_5m_kwargs: dict[str, object],
    factor_15m_kwargs: dict[str, object],
) -> None:
    confirmed = _bar(15)
    risk = _bar(30)
    blocked_recovery = _bar(45)

    trace = _evaluate(
        (confirmed, risk, blocked_recovery),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(risk, BarFrequency.M5),
            _factor(blocked_recovery, BarFrequency.M5, **factor_5m_kwargs),  # type: ignore[arg-type]
        ),
        bars_15m=(confirmed, risk, blocked_recovery),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(risk, BarFrequency.M15, slope5="-1"),
            _factor(blocked_recovery, BarFrequency.M15, **factor_15m_kwargs),  # type: ignore[arg-type]
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.EXIT_RISK
    assert trace.transitions[-1].to_stage is LifecycleStage.EXIT_RISK


def test_hard_close_prioritizes_opposite_formal_over_all_other_facts() -> None:
    confirmed = _bar(15)
    close_boundary = _bar(30)

    trace = _evaluate(
        (confirmed, close_boundary),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(
                close_boundary,
                BarFrequency.M5,
                direction=SubingDirection.SHORT,
                cross=MacdCross.DEAD,
                volume_ratio=Decimal("3"),
            ),
        ),
        bars_15m=(confirmed, close_boundary),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(
                close_boundary,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
                cross=MacdCross.DEAD,
                volume_ratio=Decimal("3"),
            ),
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("OPPOSITE_FORMAL_V1",)


def test_hard_close_prioritizes_opposite_context_over_anchor_break() -> None:
    confirmed = _bar(15)
    close_boundary = _bar(30)

    trace = _evaluate(
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

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == (
        "OPPOSITE_DIRECTION_CONTEXT_CONFIRMED",
    )


def test_hard_close_prioritizes_anchor_break_over_structure_invalidation() -> None:
    confirmed_bars = (
        *_long_pivot_prefix(),
        _bar(35, close="112", high="113", low="111"),
        _bar(40, close="113", high="114", low="112"),
    )
    close_boundary = _bar(45, close="109", high="110", low="108")

    trace = _evaluate(
        (*confirmed_bars, close_boundary),
        factors_5m=tuple(
            _factor(bar, BarFrequency.M5)
            for bar in (*confirmed_bars, close_boundary)
        ),
        bars_15m=(_bar(0), close_boundary),
        factors_15m=(
            _factor(_bar(0), BarFrequency.M15),
            _factor(close_boundary, BarFrequency.M15, ema21="110", slope10="-1"),
        ),
    )

    assert trace.snapshots[-2].confirmation_source is ConfirmationSource.PIVOT_BREAK_HOLD
    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("ANCHOR_TREND_BROKEN",)


def test_structure_invalidation_closes_only_a_pivot_confirmed_opportunity() -> None:
    confirmed_bars = (
        *_long_pivot_prefix(),
        _bar(35, close="112", high="113", low="111"),
        _bar(40, close="113", high="114", low="112"),
    )
    close_boundary = _bar(45, close="109", high="110", low="108")

    trace = _evaluate(
        (*confirmed_bars, close_boundary),
        bars_15m=(_bar(0), close_boundary),
        factors_15m=(
            _factor(_bar(0), BarFrequency.M15),
            _factor(close_boundary, BarFrequency.M15, ema21="108", slope10="1"),
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("STRUCTURE_INVALIDATED",)
    completed = trace.completed_opportunities[-1]
    assert completed.confirmation_source is ConfirmationSource.PIVOT_BREAK_HOLD
    assert completed.confirmed_at == confirmed_bars[-1].bar_end


def test_non_pivot_confirmation_does_not_use_structure_invalidation() -> None:
    confirmed = _bar(15, close="100")
    below_unbound_price = _bar(30, close="90")

    trace = _evaluate(
        (confirmed, below_unbound_price),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(below_unbound_price, BarFrequency.M5, ema21="89"),
        ),
        bars_15m=(confirmed, below_unbound_price),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15),
            _factor(below_unbound_price, BarFrequency.M15, ema21="89"),
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert all(
        transition.reason_codes != ("STRUCTURE_INVALIDATED",)
        for transition in trace.transitions
    )


def test_short_anchor_trend_break_uses_the_exact_mirrored_formula() -> None:
    confirmed = _bar(15)
    close_boundary = _bar(30)

    trace = _evaluate(
        (confirmed, close_boundary),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                direction=SubingDirection.SHORT,
                cross=MacdCross.DEAD,
                volume_ratio=Decimal("3"),
            ),
            _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
        ),
        bars_15m=(confirmed, close_boundary),
        factors_15m=(
            _factor(confirmed, BarFrequency.M15, direction=SubingDirection.SHORT),
            _factor(
                close_boundary,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
                ema21="99",
                slope10="1",
            ),
        ),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("ANCHOR_TREND_BROKEN",)


def test_short_structure_invalidation_keeps_using_trigger_low() -> None:
    prefix = _short_pivot_prefix()
    confirmed_bars = (
        *prefix,
        _bar(35, close="88", high="89", low="87"),
        _bar(40, close="87", high="88", low="86"),
    )
    close_boundary = _bar(45, close="91", high="92", low="90")
    all_bars = (*confirmed_bars, close_boundary)

    trace = _evaluate(
        all_bars,
        factors_5m=tuple(
            _factor(bar, BarFrequency.M5, direction=SubingDirection.SHORT)
            for bar in all_bars
        ),
        bars_15m=(_bar(0), close_boundary),
        factors_15m=(
            _factor(_bar(0), BarFrequency.M15, direction=SubingDirection.SHORT),
            _factor(
                close_boundary,
                BarFrequency.M15,
                direction=SubingDirection.SHORT,
                ema21="92",
                slope10="-1",
            ),
        ),
    )

    assert trace.snapshots[-2].confirmation_source is ConfirmationSource.PIVOT_BREAK_HOLD
    assert trace.snapshots[-2].trigger_reference_pivot is not None
    assert trace.snapshots[-2].trigger_reference_pivot.price == Decimal("90")
    assert trace.snapshots[-2].bound_reference_pivot is None
    assert trace.current_snapshot.stage is LifecycleStage.CLOSED
    assert trace.transitions[-1].reason_codes == ("STRUCTURE_INVALIDATED",)


def test_confirmed_opportunity_continues_across_trading_day_in_same_segment() -> None:
    confirmed = _bar(15)
    next_day = _bar(20, trading_day=date(2026, 8, 4))

    trace = _evaluate(
        (confirmed, next_day),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(next_day, BarFrequency.M5),
        ),
        bars_15m=(confirmed,),
    )

    assert trace.current_snapshot.stage is LifecycleStage.CONTINUATION
    assert trace.current_snapshot.crossed_trading_day is True
    assert all(
        transition.reason_codes != ("UNCONFIRMED_TRADING_DAY_ROLLOVER",)
        for transition in trace.transitions
    )


def test_exit_risk_continues_across_trading_day_without_automatic_close() -> None:
    confirmed, first_risk, exit_risk = (
        _bar(minutes) for minutes in (15, 20, 25)
    )
    next_day = _bar(30, trading_day=date(2026, 8, 4))

    trace = _evaluate(
        (confirmed, first_risk, exit_risk, next_day),
        factors_5m=(
            _factor(
                confirmed,
                BarFrequency.M5,
                cross=MacdCross.GOLDEN,
                volume_ratio=Decimal("3"),
            ),
            _factor(first_risk, BarFrequency.M5, ema21="101"),
            _factor(exit_risk, BarFrequency.M5, ema21="101"),
            _factor(next_day, BarFrequency.M5),
        ),
        bars_15m=(confirmed,),
    )

    assert trace.snapshots[-2].stage is LifecycleStage.EXIT_RISK
    assert trace.current_snapshot.stage is LifecycleStage.EXIT_RISK
    assert trace.current_snapshot.crossed_trading_day is True
    assert trace.transitions[-1].to_stage is LifecycleStage.EXIT_RISK


def test_future_stream_append_preserves_earlier_transition_ids() -> None:
    confirmed, continuation, close_boundary = (
        _bar(minutes) for minutes in (15, 20, 30)
    )
    bars = (confirmed, continuation, close_boundary)
    factors = (
        _factor(
            confirmed,
            BarFrequency.M5,
            cross=MacdCross.GOLDEN,
            volume_ratio=Decimal("3"),
        ),
        _factor(continuation, BarFrequency.M5),
        _factor(close_boundary, BarFrequency.M5, direction=SubingDirection.SHORT),
    )
    anchors = (confirmed, close_boundary)
    anchor_factors = (
        _factor(confirmed, BarFrequency.M15),
        _factor(close_boundary, BarFrequency.M15, direction=SubingDirection.SHORT),
    )
    raw_bars, raw_factors = _with_lifecycle_reset(bars, factors)

    states = _stream_lifecycle_prefixes(
        raw_bars,
        factors_5m=raw_factors,
        bars_15m=anchors,
        factors_15m=anchor_factors,
    )
    prefix_ids = tuple(
        transition.transition_id for transition in states[-2].transitions
    )
    full_ids = tuple(transition.transition_id for transition in states[-1].transitions)

    assert full_ids[: len(prefix_ids)] == prefix_ids
    assert len(set(full_ids)) == len(full_ids)
