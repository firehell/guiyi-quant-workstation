"""Deterministic, copy-free facts for Newow diagnostic presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from .main_rise import MAIN_RISE_PAGE_V1, MainRiseState
from .models import (
    CupHandleState,
    NewowCupHandleOverlay,
    NewowDailyBar,
    NewowTrendBandPoint,
    TrendBandState,
)
from .oscillation_channel import OSCILLATION_FORMULA_VERSION, OscillationState
from .price_channel import (
    TARGET_ABSORB_DISPLAY_PAGE_V1,
    DisplayPriceSelection,
    PageSignalState,
)
from .profile import NEWOW_TREND_D1_PAGE_V2
from .subplots import (
    ZHAOYAO_MIRROR_FORMULA_VERSION,
    MainForceControlResult,
    MainForceStatus,
)


DIAGNOSTIC_FACTS_CLEANROOM_V1 = "newow_diagnostic_facts_cleanroom_v1"
_PCT_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class DiagnosticInputs:
    """Explicit primitive outputs accepted by the diagnostic fact builder."""

    bars: tuple[NewowDailyBar, ...]
    display_prices: DisplayPriceSelection
    trend_points: tuple[NewowTrendBandPoint, ...]
    trend_formula_version: str
    oscillation_state: OscillationState | None
    main_force: MainForceControlResult | None
    main_rise_state: MainRiseState | None
    cup_overlay: NewowCupHandleOverlay | None
    weekly_signal: PageSignalState | None
    daily_signal: PageSignalState | None
    repainting_inputs: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticFacts:
    as_of: datetime
    target_price: Decimal | None
    absorb_price: Decimal | None
    target_distance_pct: Decimal | None
    absorb_distance_pct: Decimal | None
    ema20: Decimal | None
    close_vs_ema20: Literal["above", "below", "equal", "unavailable"]
    trend_state: TrendBandState
    trend_duration_bars: int
    oscillation_holding: bool | None
    main_force_status: MainForceStatus | None
    main_rise_active: bool | None
    cup_state: CupHandleState | None
    weekly_signal: PageSignalState | None
    daily_signal: PageSignalState | None
    repainting_inputs_excluded: tuple[str, ...]
    formula_versions: tuple[str, ...]


def _validate_inputs(inputs: DiagnosticInputs) -> None:
    if not isinstance(inputs, DiagnosticInputs) or not inputs.bars:
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")
    if not isinstance(inputs.display_prices, DisplayPriceSelection):
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")
    if inputs.display_prices.formula_version != TARGET_ABSORB_DISPLAY_PAGE_V1:
        raise ValueError("NEWOW_FORMULA_IDENTITY_MISMATCH")
    if len(inputs.bars) != len(inputs.trend_points) or any(
        bar.bar_end != point.bar_end
        for bar, point in zip(inputs.bars, inputs.trend_points, strict=True)
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_TREND_ALIGNMENT_INVALID")
    if inputs.trend_formula_version != NEWOW_TREND_D1_PAGE_V2.trend_band_formula:
        raise ValueError("NEWOW_FORMULA_IDENTITY_MISMATCH")
    if any(
        left.bar_end >= right.bar_end
        for left, right in zip(inputs.bars, inputs.bars[1:])
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_BAR_ORDER_INVALID")
    if inputs.repainting_inputs:
        raise ValueError("NEWOW_DIAGNOSTIC_REPAINTING_INPUT")
    if inputs.oscillation_state is not None and not isinstance(
        inputs.oscillation_state, OscillationState
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")
    if inputs.main_force is not None and not isinstance(
        inputs.main_force, MainForceControlResult
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")
    if inputs.main_rise_state is not None and not isinstance(
        inputs.main_rise_state, MainRiseState
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")
    if inputs.cup_overlay is not None and not isinstance(
        inputs.cup_overlay, NewowCupHandleOverlay
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")
    if any(
        value is not None and not isinstance(value, PageSignalState)
        for value in (inputs.weekly_signal, inputs.daily_signal)
    ):
        raise ValueError("NEWOW_DIAGNOSTIC_INPUT_INVALID")


def _ema_strict_before(bars: tuple[NewowDailyBar, ...]) -> Decimal | None:
    latest = bars[-1]
    tail: list[NewowDailyBar] = []
    for bar in reversed(bars):
        if (
            bar.physical_contract != latest.physical_contract
            or bar.segment_id != latest.segment_id
        ):
            break
        tail.append(bar)
    segment = tuple(reversed(tail))
    if len(segment) < 21:
        return None
    values = tuple(bar.close for bar in segment[:-1])
    alpha = Decimal(2) / Decimal(21)
    result = values[0]
    for value in values[1:]:
        result = value * alpha + result * (Decimal(1) - alpha)
    return result


def _distance(value: Decimal | None, close: Decimal) -> Decimal | None:
    if value is None:
        return None
    return ((value - close) / close * Decimal(100)).quantize(
        _PCT_QUANTUM, rounding=ROUND_HALF_UP
    )


def _trend_duration(
    bars: tuple[NewowDailyBar, ...], points: tuple[NewowTrendBandPoint, ...]
) -> int:
    latest_bar = bars[-1]
    latest_state = points[-1].state
    if latest_state is TrendBandState.UNAVAILABLE:
        return 0
    count = 0
    for bar, point in reversed(tuple(zip(bars, points, strict=True))):
        if (
            bar.physical_contract != latest_bar.physical_contract
            or bar.segment_id != latest_bar.segment_id
            or point.state is not latest_state
        ):
            break
        count += 1
    return count


def _same_tail_segment(
    physical_contract: str | None,
    segment_id: str | None,
    latest: NewowDailyBar,
) -> bool:
    return (
        physical_contract == latest.physical_contract
        and segment_id == latest.segment_id
    )


def build_diagnostic_facts(inputs: DiagnosticInputs) -> DiagnosticFacts:
    """Project existing primitives into facts without accepting prose."""

    _validate_inputs(inputs)
    latest = inputs.bars[-1]
    ema20 = _ema_strict_before(inputs.bars)
    if ema20 is None:
        close_vs_ema20: Literal["above", "below", "equal", "unavailable"] = (
            "unavailable"
        )
    elif latest.close > ema20:
        close_vs_ema20 = "above"
    elif latest.close < ema20:
        close_vs_ema20 = "below"
    else:
        close_vs_ema20 = "equal"

    oscillation_holding = None
    if inputs.oscillation_state is not None and _same_tail_segment(
        inputs.oscillation_state.physical_contract,
        inputs.oscillation_state.segment_id,
        latest,
    ):
        oscillation_holding = inputs.oscillation_state.holding

    main_rise_active = None
    if inputs.main_rise_state is not None and _same_tail_segment(
        inputs.main_rise_state.physical_contract,
        inputs.main_rise_state.segment_id,
        latest,
    ):
        main_rise_active = inputs.main_rise_state.band_state is TrendBandState.YELLOW

    versions = [
        DIAGNOSTIC_FACTS_CLEANROOM_V1,
        inputs.display_prices.formula_version,
        inputs.trend_formula_version,
    ]
    if inputs.oscillation_state is not None:
        versions.append(OSCILLATION_FORMULA_VERSION)
    if inputs.main_force is not None:
        versions.append(inputs.main_force.formula_version)
    if inputs.main_rise_state is not None:
        versions.append(MAIN_RISE_PAGE_V1.band_formula)
    if inputs.cup_overlay is not None:
        versions.append(inputs.cup_overlay.formula_version)

    return DiagnosticFacts(
        as_of=latest.bar_end,
        target_price=inputs.display_prices.target,
        absorb_price=inputs.display_prices.absorb,
        target_distance_pct=_distance(inputs.display_prices.target, latest.close),
        absorb_distance_pct=_distance(inputs.display_prices.absorb, latest.close),
        ema20=ema20,
        close_vs_ema20=close_vs_ema20,
        trend_state=inputs.trend_points[-1].state,
        trend_duration_bars=_trend_duration(inputs.bars, inputs.trend_points),
        oscillation_holding=oscillation_holding,
        main_force_status=(
            inputs.main_force.current_status if inputs.main_force is not None else None
        ),
        main_rise_active=main_rise_active,
        cup_state=(inputs.cup_overlay.state if inputs.cup_overlay is not None else None),
        weekly_signal=inputs.weekly_signal,
        daily_signal=inputs.daily_signal,
        repainting_inputs_excluded=(ZHAOYAO_MIRROR_FORMULA_VERSION,),
        formula_versions=tuple(dict.fromkeys(versions)),
    )
