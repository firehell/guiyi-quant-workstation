from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_calibration import SubingCalibration
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingConditionState,
    SubingDirection,
    SubingFactorResult,
    SubingFactorStatus,
    SubingSignalResolution,
    SubingSignalEvaluation,
    SubingSignalStatus,
    calculate_subing_factor,
    calculate_subing_factor_series,
    evaluate_subing_signal,
    resolve_same_boundary_subing_signals,
)
from guiyi_quant.indicators import (
    get_formal_policy,
    get_indicator,
    require_formal_policy,
)


_SCOPED_SIGNAL_MACD_EQUIVALENCE_TARGET = (
    "sma_window",
    2,
    "fast12_slow26_signal9",
    True,
)


def _bars_from_closes(
    closes: list[Decimal],
    *,
    previous_volume: Decimal = Decimal("100"),
    final_volume: Decimal = Decimal("300"),
) -> tuple[CanonicalBar, ...]:
    start = datetime(2026, 8, 3, 1, tzinfo=UTC)
    bars: list[CanonicalBar] = []
    for index, close in enumerate(closes):
        volume = Decimal("200")
        if index == len(closes) - 2:
            volume = previous_volume
        elif index == len(closes) - 1:
            volume = final_volume
        bars.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=5 * index),
                trading_day=date(2026, 8, 3),
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=volume,
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(bars)


def _ready_bars(
    *,
    count: int = 48,
    previous_volume: Decimal = Decimal("100"),
    final_volume: Decimal = Decimal("300"),
) -> tuple[CanonicalBar, ...]:
    closes = [Decimal("100") + Decimal(index) for index in range(count)]
    return _bars_from_closes(
        closes,
        previous_volume=previous_volume,
        final_volume=final_volume,
    )


def _calculate(bars: tuple[CanonicalBar, ...]):
    return calculate_subing_factor(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )


def _signal_factor(
    *,
    timeframe: BarFrequency,
    price_side: PriceSide = PriceSide.ABOVE,
    slope5: Decimal = Decimal("2"),
    slope10: Decimal = Decimal("1"),
    cross: MacdCross = MacdCross.GOLDEN,
    volume_ratio: Decimal | None = Decimal("3"),
    bar_end: datetime | None = None,
):
    base = _calculate(_ready_bars())
    assert base.snapshot is not None
    return replace(
        base,
        snapshot=replace(
            base.snapshot,
            timeframe=timeframe,
            bar_end=bar_end or base.snapshot.bar_end,
            price_side=price_side,
            slope_5_bps_per_bar=slope5,
            slope_10_bps_per_bar=slope10,
            macd_cross=cross,
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


@pytest.mark.parametrize(
    ("status", "direction"),
    (
        (SubingSignalStatus.MATCHED, SubingDirection.NONE),
        (SubingSignalStatus.NOT_MATCHED, SubingDirection.LONG),
        (SubingSignalStatus.INSUFFICIENT_DATA, SubingDirection.SHORT),
    ),
)
def test_signal_result_rejects_invalid_status_direction_pairs(
    status: SubingSignalStatus,
    direction: SubingDirection,
) -> None:
    """Catches public construction of a formal Signal with an invalid direction."""
    with pytest.raises(ValueError, match="SUBING_SIGNAL_STATE_INVALID"):
        SubingSignalEvaluation(
            status=status,
            direction=direction,
            trigger_timeframe=BarFrequency.M5,
            bar_end=datetime(2026, 8, 3, 6, tzinfo=UTC),
            lower_tf_confirmation=False,
            resolution=None,
            conditions=(),
        )


def test_exact_long_signal_uses_slope_only_calibration() -> None:
    """Catches omission of any approved LONG primary or companion hard condition."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.MATCHED
    assert result.direction is SubingDirection.LONG
    assert result.trigger_timeframe is BarFrequency.M5
    assert result.lower_tf_confirmation is False
    assert result.resolution is None
    assert result.error_code is None
    assert {condition.code for condition in result.conditions} == {
        "PRIMARY_PRICE_DIRECTION",
        "PRIMARY_SLOPE5_THRESHOLD",
        "PRIMARY_SLOPE10_DIRECTION",
        "PRIMARY_MACD_CROSS",
        "PRIMARY_VOLUME_RATIO",
        "COMPANION_PRICE_DIRECTION",
        "COMPANION_SLOPE5_THRESHOLD",
        "COMPANION_SLOPE10_DIRECTION",
        "MACD_POLICY_EQUIVALENCE",
    }


def test_exact_short_signal_mirrors_every_long_condition() -> None:
    """Catches a sign, price-side, or cross asymmetry in the SHORT branch."""
    result = evaluate_subing_signal(
        _signal_factor(
            timeframe=BarFrequency.M15,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.DEAD,
        ),
        companion=_signal_factor(
            timeframe=BarFrequency.M5,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.NONE,
            volume_ratio=None,
        ),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.MATCHED
    assert result.direction is SubingDirection.SHORT
    assert result.trigger_timeframe is BarFrequency.M15


@pytest.mark.parametrize(
    ("direction", "broken_condition", "expected_code"),
    (
        (SubingDirection.LONG, "price", "PRIMARY_PRICE_DIRECTION"),
        (SubingDirection.LONG, "slope5", "PRIMARY_SLOPE5_THRESHOLD"),
        (SubingDirection.LONG, "slope10", "PRIMARY_SLOPE10_DIRECTION"),
        (SubingDirection.LONG, "cross", "PRIMARY_MACD_CROSS"),
        (SubingDirection.LONG, "volume", "PRIMARY_VOLUME_RATIO"),
        (SubingDirection.SHORT, "price", "PRIMARY_PRICE_DIRECTION"),
        (SubingDirection.SHORT, "slope5", "PRIMARY_SLOPE5_THRESHOLD"),
        (SubingDirection.SHORT, "slope10", "PRIMARY_SLOPE10_DIRECTION"),
        (SubingDirection.SHORT, "cross", "PRIMARY_MACD_CROSS"),
        (SubingDirection.SHORT, "volume", "PRIMARY_VOLUME_RATIO"),
    ),
)
def test_each_primary_hard_condition_fails_independently(
    direction: SubingDirection,
    broken_condition: str,
    expected_code: str,
) -> None:
    """Catches deletion or boundary relaxation of any primary hard condition."""
    if direction is SubingDirection.LONG:
        timeframe = BarFrequency.M5
        companion_timeframe = BarFrequency.M15
        primary_kwargs: dict[str, object] = {}
        companion_kwargs: dict[str, object] = {}
        mutations = {
            "price": {"price_side": PriceSide.BELOW},
            "slope5": {"slope5": Decimal("0.688190651160584793944957992")},
            "slope10": {"slope10": Decimal("0")},
            "cross": {"cross": MacdCross.NONE},
            "volume": {"volume_ratio": Decimal("2.999999")},
        }
    else:
        timeframe = BarFrequency.M15
        companion_timeframe = BarFrequency.M5
        primary_kwargs = {
            "price_side": PriceSide.BELOW,
            "slope5": Decimal("-2"),
            "slope10": Decimal("-1"),
            "cross": MacdCross.DEAD,
        }
        companion_kwargs = {
            "price_side": PriceSide.BELOW,
            "slope5": Decimal("-2"),
            "slope10": Decimal("-1"),
            "cross": MacdCross.NONE,
            "volume_ratio": None,
        }
        mutations = {
            "price": {"price_side": PriceSide.ABOVE},
            "slope5": {"slope5": Decimal("-1.329531078893356968545882036")},
            "slope10": {"slope10": Decimal("0")},
            "cross": {"cross": MacdCross.NONE},
            "volume": {"volume_ratio": Decimal("2.999999")},
        }
    primary_kwargs.update(mutations[broken_condition])

    result = evaluate_subing_signal(
        _signal_factor(timeframe=timeframe, **primary_kwargs),
        companion=_signal_factor(
            timeframe=companion_timeframe,
            **companion_kwargs,
        ),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE
    condition = next(item for item in result.conditions if item.code == expected_code)
    assert condition.state is SubingConditionState.FAIL


@pytest.mark.parametrize(
    ("direction", "broken_condition", "expected_code"),
    (
        (SubingDirection.LONG, "price", "COMPANION_PRICE_DIRECTION"),
        (SubingDirection.LONG, "slope5", "COMPANION_SLOPE5_THRESHOLD"),
        (SubingDirection.LONG, "slope10", "COMPANION_SLOPE10_DIRECTION"),
        (SubingDirection.SHORT, "price", "COMPANION_PRICE_DIRECTION"),
        (SubingDirection.SHORT, "slope5", "COMPANION_SLOPE5_THRESHOLD"),
        (SubingDirection.SHORT, "slope10", "COMPANION_SLOPE10_DIRECTION"),
    ),
)
def test_each_companion_hard_condition_fails_independently(
    direction: SubingDirection,
    broken_condition: str,
    expected_code: str,
) -> None:
    """Catches deletion or boundary relaxation of any companion trend condition."""
    if direction is SubingDirection.LONG:
        primary = _signal_factor(timeframe=BarFrequency.M5)
        companion_timeframe = BarFrequency.M15
        companion_kwargs: dict[str, object] = {}
        mutations = {
            "price": {"price_side": PriceSide.BELOW},
            "slope5": {"slope5": Decimal("1.329531078893356968545882036")},
            "slope10": {"slope10": Decimal("0")},
        }
    else:
        primary = _signal_factor(
            timeframe=BarFrequency.M15,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.DEAD,
        )
        companion_timeframe = BarFrequency.M5
        companion_kwargs = {
            "price_side": PriceSide.BELOW,
            "slope5": Decimal("-2"),
            "slope10": Decimal("-1"),
            "cross": MacdCross.NONE,
            "volume_ratio": None,
        }
        mutations = {
            "price": {"price_side": PriceSide.ABOVE},
            "slope5": {"slope5": Decimal("-0.688190651160584793944957992")},
            "slope10": {"slope10": Decimal("0")},
        }
    companion_kwargs.update(mutations[broken_condition])

    result = evaluate_subing_signal(
        primary,
        companion=_signal_factor(
            timeframe=companion_timeframe,
            **companion_kwargs,
        ),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE
    condition = next(item for item in result.conditions if item.code == expected_code)
    assert condition.state is SubingConditionState.FAIL


@pytest.mark.parametrize("direction", (SubingDirection.LONG, SubingDirection.SHORT))
def test_companion_macd_and_volume_are_non_executable_poison(
    direction: SubingDirection,
) -> None:
    """Catches MACD or volume conditions leaking onto either companion direction."""
    if direction is SubingDirection.LONG:
        primary = _signal_factor(timeframe=BarFrequency.M5)
        companion = _signal_factor(
            timeframe=BarFrequency.M15,
            cross=MacdCross.DEAD,
            volume_ratio=None,
        )
    else:
        primary = _signal_factor(
            timeframe=BarFrequency.M15,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.DEAD,
        )
        companion = _signal_factor(
            timeframe=BarFrequency.M5,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.GOLDEN,
            volume_ratio=None,
        )

    result = evaluate_subing_signal(
        primary,
        companion=companion,
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.MATCHED
    assert result.direction is direction


def test_known_hard_failure_precedes_missing_calibration() -> None:
    """A known failed condition is not a candidate waiting on calibration."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5, volume_ratio=Decimal("1")),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE
    assert result.error_code is None


def test_pending_calibration_does_not_emit_an_incoherent_candidate() -> None:
    """A negative slope5 is a known failure, not a pending LONG candidate."""
    result = evaluate_subing_signal(
        _signal_factor(
            timeframe=BarFrequency.M5,
            slope5=Decimal("-0.1"),
        ),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE
    assert result.error_code is None


def test_unavailable_factor_precedes_pending_calibration() -> None:
    """Catches missing warm-up being mislabeled as a research-policy state."""
    result = evaluate_subing_signal(
        SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.INSUFFICIENT_DATA
    assert result.direction is SubingDirection.NONE
    assert result.error_code == "SUBING_FACTOR_UNAVAILABLE"


def test_unavailable_primary_volume_is_insufficient_not_a_failed_ratio() -> None:
    """Catches unavailable volume being coerced to zero before policy/calibration checks."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5, volume_ratio=None),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.INSUFFICIENT_DATA
    assert result.direction is SubingDirection.NONE
    assert result.error_code == "SUBING_VOLUME_RATIO_UNAVAILABLE"


def test_companion_direction_conflict_is_a_known_hard_failure() -> None:
    """Catches a primary-only LONG ignoring an opposite companion trend."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5),
        companion=_signal_factor(
            timeframe=BarFrequency.M15,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.NONE,
            volume_ratio=None,
        ),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE


def test_companion_slope_threshold_is_strictly_exclusive() -> None:
    """Catches equality being admitted despite the approved strict slope condition."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5),
        companion=_signal_factor(
            timeframe=BarFrequency.M15,
            slope5=Decimal("1.329531078893356968545882036"),
        ),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE


def test_future_companion_is_rejected_before_signal_conditions() -> None:
    """Catches companion lookahead at an otherwise exact LONG setup."""
    primary = _signal_factor(timeframe=BarFrequency.M5)
    assert primary.snapshot is not None
    result = evaluate_subing_signal(
        primary,
        companion=_signal_factor(
            timeframe=BarFrequency.M15,
            bar_end=primary.snapshot.bar_end + timedelta(minutes=10),
        ),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.INSUFFICIENT_DATA
    assert result.direction is SubingDirection.NONE
    assert result.error_code == "SUBING_COMPANION_FUTURE"


@pytest.mark.parametrize(
    ("case", "expected_error"),
    (
        ("absent", "SUBING_COMPANION_UNAVAILABLE"),
        ("insufficient", "SUBING_COMPANION_UNAVAILABLE"),
        ("wrong_timeframe", "SUBING_COMPANION_TIMEFRAME_MISMATCH"),
        ("contract", "SUBING_COMPANION_IDENTITY_MISMATCH"),
        ("segment", "SUBING_COMPANION_IDENTITY_MISMATCH"),
    ),
)
def test_companion_readiness_and_identity_precede_pending_calibration(
    case: str,
    expected_error: str,
) -> None:
    """Catches missing or cross-identity companions reaching research-policy states."""
    companion = _signal_factor(timeframe=BarFrequency.M15)
    assert companion.snapshot is not None
    if case == "absent":
        candidate = None
    elif case == "insufficient":
        candidate = SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)
    elif case == "wrong_timeframe":
        candidate = replace(
            companion,
            snapshot=replace(companion.snapshot, timeframe=BarFrequency.M5),
        )
    elif case == "contract":
        candidate = replace(
            companion,
            snapshot=replace(companion.snapshot, contract="RB2610"),
        )
    else:
        candidate = replace(
            companion,
            snapshot=replace(
                companion.snapshot,
                segment_start_trading_day=date(2026, 8, 4),
            ),
        )

    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5),
        companion=candidate,
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.INSUFFICIENT_DATA
    assert result.direction is SubingDirection.NONE
    assert result.error_code == expected_error


def test_daily_signal_remains_research_pending_without_intraday_companion() -> None:
    """Catches the accepted intraday artifact leaking into the independent 1d lane."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.D1),
        companion=None,
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.RESEARCH_PENDING
    assert result.direction is SubingDirection.LONG
    assert result.error_code == "SUBING_DAILY_RESEARCH_PENDING"


def test_known_hard_failure_precedes_scoped_policy_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches missing Gate-C policy hiding an already failed hard condition."""
    real_require = require_formal_policy

    def missing_signal_policy(policy_id: str, *, consumer: str | None = None):
        if policy_id == "subing_macd_sma_window_scale2_v1":
            raise KeyError("missing scoped policy")
        return real_require(policy_id, consumer=consumer)

    monkeypatch.setattr(
        "app.market_data.subing_research.require_formal_policy",
        missing_signal_policy,
    )
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5, volume_ratio=Decimal("1")),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE
    assert result.error_code is None


def test_known_hard_failure_precedes_pending_calibration() -> None:
    """Catches an absent artifact presenting an impossible setup as a candidate."""
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5, volume_ratio=Decimal("1")),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=SubingCalibration(None, frozenset(), {}),
    )

    assert result.status is SubingSignalStatus.NOT_MATCHED
    assert result.direction is SubingDirection.NONE
    assert result.error_code is None


def test_scoped_policy_equivalence_mismatch_never_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a scoped MACD math drift being accepted by the Signal core."""
    real_require = require_formal_policy
    signal_policy = real_require(
        "subing_macd_sma_window_scale2_v1",
        consumer="subing_signal",
    )

    def mismatched_signal_policy(policy_id: str, *, consumer: str | None = None):
        if policy_id == "subing_macd_sma_window_scale2_v1":
            return replace(signal_policy, histogram_scale=1)
        return real_require(policy_id, consumer=consumer)

    monkeypatch.setattr(
        "app.market_data.subing_research.require_formal_policy",
        mismatched_signal_policy,
    )
    result = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5),
        companion=_signal_factor(timeframe=BarFrequency.M15),
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.RESEARCH_PENDING
    assert result.direction is SubingDirection.LONG
    assert result.error_code == "SUBING_MACD_POLICY_MISMATCH"


def test_both_macd_policies_drifting_together_still_mismatch_fixed_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches equal but non-approved MACD tuples bypassing the Gate-C target."""
    primary = _signal_factor(timeframe=BarFrequency.M5)
    companion = _signal_factor(timeframe=BarFrequency.M15)
    observation = replace(
        get_formal_policy("web_macd_legacy_v1"),
        histogram_scale=1,
    )
    signal = replace(
        require_formal_policy(
            "subing_macd_sma_window_scale2_v1",
            consumer="subing_signal",
        ),
        histogram_scale=1,
    )
    monkeypatch.setattr(
        "app.market_data.subing_research.get_formal_policy",
        lambda _policy_id: observation,
    )
    monkeypatch.setattr(
        "app.market_data.subing_research.require_formal_policy",
        lambda _policy_id, *, consumer=None: signal,
    )

    result = evaluate_subing_signal(
        primary,
        companion=companion,
        calibration=_accepted_calibration(),
    )

    assert result.status is SubingSignalStatus.RESEARCH_PENDING
    assert result.direction is SubingDirection.LONG
    assert result.error_code == "SUBING_MACD_POLICY_MISMATCH"


def test_zero_distance_values_and_unavailability_cannot_change_signal() -> None:
    """Catches the rejected zero-band returning as an executable Signal input."""
    primary = _signal_factor(timeframe=BarFrequency.M5)
    companion = _signal_factor(timeframe=BarFrequency.M15)
    assert primary.snapshot is not None
    assert companion.snapshot is not None
    near_zero = evaluate_subing_signal(
        replace(
            primary,
            snapshot=replace(
                primary.snapshot,
                macd_zero_distance_abs=Decimal("0"),
                macd_zero_distance_bps=Decimal("0"),
            ),
        ),
        companion=companion,
        calibration=_accepted_calibration(),
    )
    unavailable_or_huge = evaluate_subing_signal(
        replace(
            primary,
            snapshot=replace(
                primary.snapshot,
                macd_zero_distance_abs=Decimal("NaN"),
                macd_zero_distance_bps=Decimal("999999999999999999"),
            ),
        ),
        companion=companion,
        calibration=_accepted_calibration(),
    )

    assert near_zero.status is unavailable_or_huge.status is SubingSignalStatus.MATCHED
    assert near_zero.direction is unavailable_or_huge.direction is SubingDirection.LONG
    assert not any("ZERO" in condition.code for condition in near_zero.conditions)


def test_same_boundary_same_direction_prefers_15m_once() -> None:
    """Catches duplicate matched emissions or a lower-timeframe winner."""
    bar_end = datetime(2026, 8, 3, 6, tzinfo=UTC)
    m5 = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5, bar_end=bar_end),
        companion=_signal_factor(timeframe=BarFrequency.M15, bar_end=bar_end),
        calibration=_accepted_calibration(),
    )
    m15 = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M15, bar_end=bar_end),
        companion=_signal_factor(timeframe=BarFrequency.M5, bar_end=bar_end),
        calibration=_accepted_calibration(),
    )

    resolved = resolve_same_boundary_subing_signals(m5, m15)

    assert resolved.status is SubingSignalStatus.MATCHED
    assert resolved.direction is SubingDirection.LONG
    assert resolved.trigger_timeframe is BarFrequency.M15
    assert resolved.lower_tf_confirmation is True
    assert resolved.resolution is SubingSignalResolution.HIGHER_TIMEFRAME_WINS


def test_same_boundary_opposite_matched_directions_fail_closed() -> None:
    """Catches deterministic resolver selection across an opposite-direction conflict."""
    bar_end = datetime(2026, 8, 3, 6, tzinfo=UTC)
    long_m5 = evaluate_subing_signal(
        _signal_factor(timeframe=BarFrequency.M5, bar_end=bar_end),
        companion=_signal_factor(timeframe=BarFrequency.M15, bar_end=bar_end),
        calibration=_accepted_calibration(),
    )
    short_m15 = evaluate_subing_signal(
        _signal_factor(
            timeframe=BarFrequency.M15,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.DEAD,
            bar_end=bar_end,
        ),
        companion=_signal_factor(
            timeframe=BarFrequency.M5,
            price_side=PriceSide.BELOW,
            slope5=Decimal("-2"),
            slope10=Decimal("-1"),
            cross=MacdCross.NONE,
            volume_ratio=None,
            bar_end=bar_end,
        ),
        calibration=_accepted_calibration(),
    )

    resolved = resolve_same_boundary_subing_signals(long_m5, short_m15)

    assert resolved.status is SubingSignalStatus.NOT_MATCHED
    assert resolved.direction is SubingDirection.NONE
    assert resolved.trigger_timeframe is None
    assert resolved.lower_tf_confirmation is False
    assert resolved.resolution is SubingSignalResolution.DIRECTION_CONFLICT
    assert resolved.error_code == "SUBING_SIGNAL_DIRECTION_CONFLICT"


def test_ready_factor_preserves_raw_observation_values_and_identity() -> None:
    bars = _ready_bars(count=48, previous_volume=Decimal("100"), final_volume=Decimal("300"))

    series = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    result = _calculate(bars)

    assert len(series) == len(bars)
    assert series[-1] == result
    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.timeframe is BarFrequency.M5
    assert result.snapshot.contract == "JM2609"
    assert result.snapshot.segment_start_trading_day == date(2026, 8, 3)
    assert result.snapshot.bar_source == "canonical"
    assert result.snapshot.price_side is PriceSide.ABOVE
    assert result.snapshot.slope_5_raw == Decimal("1")
    assert result.snapshot.slope_10_raw == Decimal("1")
    assert result.snapshot.slope_5_bps_per_bar == Decimal("74.07407407407407407407407407")
    assert result.snapshot.slope_10_bps_per_bar == Decimal("75.47169811320754716981132075")
    assert result.snapshot.volume_ratio_prev == Decimal("3")
    with pytest.raises(FrozenInstanceError):
        result.snapshot.close = Decimal("0")  # type: ignore[misc]


def test_segment_local_warmup_is_insufficient_until_previous_macd_is_ready() -> None:
    bars = _ready_bars(count=34)

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.snapshot is None


@pytest.mark.parametrize(
    ("final_close", "expected_cross"),
    (
        (Decimal("101"), MacdCross.GOLDEN),
        (Decimal("99"), MacdCross.DEAD),
    ),
)
def test_macd_cross_accepts_equality_on_the_previous_bar(
    final_close: Decimal,
    expected_cross: MacdCross,
) -> None:
    bars = _bars_from_closes([Decimal("100")] * 47 + [final_close])

    series = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    previous = series[-2]
    result = series[-1]

    assert previous.status is SubingFactorStatus.READY
    assert previous.snapshot is not None
    assert previous.snapshot.macd_dif == previous.snapshot.macd_dea
    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.macd_cross is expected_cross
    if expected_cross is MacdCross.GOLDEN:
        assert result.snapshot.macd_dif > result.snapshot.macd_dea
    else:
        assert result.snapshot.macd_dif < result.snapshot.macd_dea


def test_historical_and_completed_live_have_identical_confirmed_factor_math() -> None:
    bars = _ready_bars()
    historical = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    completed_live = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="live",
    )

    assert len(historical) == len(completed_live)
    for historical_result, live_result in zip(historical, completed_live, strict=True):
        assert historical_result.status is live_result.status
        if historical_result.snapshot is None:
            assert live_result.snapshot is None
            continue
        assert live_result.snapshot is not None
        assert replace(live_result.snapshot, bar_source="canonical") == historical_result.snapshot


@pytest.mark.parametrize("previous_volume", (Decimal("0"), Decimal("-1")))
def test_non_positive_previous_volume_keeps_factor_ready_but_ratio_unavailable(
    previous_volume: Decimal,
) -> None:
    bars = _ready_bars(previous_volume=Decimal("0"), final_volume=Decimal("300"))
    # CanonicalBar rejects negative volume at construction. Corrupt only this
    # test input to prove the pure Factor boundary remains fail-closed if an
    # invalid object ever bypasses that upstream contract.
    object.__setattr__(bars[-2], "volume", previous_volume)

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.previous_volume == previous_volume
    assert result.snapshot.volume_ratio_prev is None


def test_zero_close_makes_normalized_zero_distance_insufficient() -> None:
    bars = _bars_from_closes([Decimal("100")] * 47 + [Decimal("0")])

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.snapshot is None


def test_constant_price_reports_equal_side_without_a_cross() -> None:
    bars = _bars_from_closes([Decimal("100")] * 48)

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.price_side is PriceSide.EQUAL
    assert result.snapshot.macd_cross is MacdCross.NONE
    assert result.snapshot.macd_zero_distance_bps == Decimal("0")


@pytest.mark.parametrize("bad_index", (12, 13))
def test_bar_end_must_be_strictly_increasing(bad_index: int) -> None:
    bars = list(_ready_bars())
    replacement_end = bars[bad_index - 1].bar_end
    if bad_index == 13:
        replacement_end -= timedelta(minutes=1)
    original = bars[bad_index]
    bars[bad_index] = CanonicalBar(
        bar_end=replacement_end,
        trading_day=original.trading_day,
        open=original.open,
        high=original.high,
        low=original.low,
        close=original.close,
        volume=original.volume,
        turnover=original.turnover,
        open_interest=original.open_interest,
    )

    with pytest.raises(ValueError, match="bar_end"):
        _calculate(tuple(bars))


def test_input_before_segment_start_is_rejected_instead_of_inheriting_state() -> None:
    bars = _ready_bars()

    with pytest.raises(ValueError, match="segment_start_trading_day"):
        calculate_subing_factor(
            bars,
            timeframe=BarFrequency.M5,
            contract="JM2609",
            segment_start_trading_day=date(2026, 8, 4),
            latest_bar_source="canonical",
        )


def test_factor_macd_matches_scoped_signal_equivalence_target_without_promotion() -> None:
    policy = require_formal_policy("web_macd_legacy_v1", consumer="subing_factor_observation")
    definition = get_indicator("macd")

    assert policy.policy_id == definition.formal_policy_id
    assert (
        policy.seed_policy,
        policy.histogram_scale,
        policy.lookback,
        policy.confirmed_only,
    ) == _SCOPED_SIGNAL_MACD_EQUIVALENCE_TARGET
    assert (
        definition.seed_policy,
        definition.histogram_scale,
        policy.lookback,
        definition.confirmed_only,
    ) == _SCOPED_SIGNAL_MACD_EQUIVALENCE_TARGET
    assert definition.default_parameters["fast"] == 12
    assert definition.default_parameters["slow"] == 26
    assert definition.default_parameters["signal"] == 9
    assert definition.status == "compatibility_validated"
    assert definition.backtest_capable is False
    assert definition.live_capable is False
    assert definition.alert_capable is False
    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_NOT_ALLOWED"):
        require_formal_policy("web_macd_legacy_v1", consumer="subing_signal")
