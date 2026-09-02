from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .ema import initial_ema_state, step_ema
from .macd import initial_macd_state, step_macd
from .models import EmaState, MacdState


SUBING_THS_FORMULA_VERSION = "subing_ths_15m_v2"
SubingThsResultCode = Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class SubingThs15mState:
    macd: MacdState
    ema21: EmaState
    previous_dif: float | None
    previous_dea: float | None


@dataclass(frozen=True, slots=True)
class SubingThs15mResult:
    formula_version: str
    bar_end: str | None
    ready: bool
    valid: bool
    reason: str | None
    dif: float | None
    dea: float | None
    macd: float | None
    ema21: float | None
    result_codes: tuple[SubingThsResultCode, ...]


class SubingThs15mKernel:
    """Pure, incremental authority for ``subing_ths_15m_v2`` candidates."""

    formula_version = SUBING_THS_FORMULA_VERSION
    fast = 12
    slow = 26
    signal = 9
    ema_period = 21
    ema_seed_policy: Literal["sma_window"] = "sma_window"
    histogram_scale: Literal[2] = 2
    round_digits = 6

    def initial_state(self) -> SubingThs15mState:
        return SubingThs15mState(
            macd=initial_macd_state(
                self.fast,
                self.slow,
                self.signal,
                ema_seed_policy=self.ema_seed_policy,
                histogram_scale=self.histogram_scale,
                round_digits=self.round_digits,
            ),
            ema21=initial_ema_state(
                self.ema_period,
                seed_policy=self.ema_seed_policy,
                round_digits=self.round_digits,
            ),
            previous_dif=None,
            previous_dea=None,
        )

    def step(
        self,
        state: SubingThs15mState,
        close: float | int | None,
        *,
        bar_end: str | None,
    ) -> tuple[SubingThs15mState, SubingThs15mResult]:
        macd_state, (dif_point, dea_point, histogram_point) = step_macd(
            state.macd,
            close,
            bar_end=bar_end,
        )
        ema21_state, ema21_point = step_ema(state.ema21, close, bar_end=bar_end)

        if not all(
            point.valid for point in (dif_point, dea_point, histogram_point, ema21_point)
        ):
            return self._result(
                macd_state,
                ema21_state,
                bar_end=bar_end,
                ready=False,
                valid=False,
                reason="input_invalid",
                dif=dif_point.value,
                dea=dea_point.value,
                macd=histogram_point.value,
                ema21=ema21_point.value,
            )

        if not all(
            point.ready for point in (dif_point, dea_point, histogram_point, ema21_point)
        ):
            return self._result(
                macd_state,
                ema21_state,
                bar_end=bar_end,
                ready=False,
                valid=True,
                reason="warming_up",
                dif=dif_point.value,
                dea=dea_point.value,
                macd=histogram_point.value,
                ema21=ema21_point.value,
            )

        dif = dif_point.value
        dea = dea_point.value
        ema21 = ema21_point.value
        macd = histogram_point.value
        rounded_close = _rounded_finite(close, self.round_digits)
        if (
            dif is None
            or dea is None
            or ema21 is None
            or macd is None
            or rounded_close is None
        ):
            return self._result(
                macd_state,
                ema21_state,
                bar_end=bar_end,
                ready=False,
                valid=False,
                reason="input_invalid",
                dif=dif,
                dea=dea,
                macd=macd,
                ema21=ema21,
            )

        golden = (
            state.previous_dif is not None
            and state.previous_dea is not None
            and state.previous_dif <= state.previous_dea
            and dif > dea
            and rounded_close > ema21
        )
        dead = (
            state.previous_dif is not None
            and state.previous_dea is not None
            and state.previous_dif >= state.previous_dea
            and dif < dea
            and rounded_close < ema21
        )
        if golden and dead:
            return self._result(
                macd_state,
                ema21_state,
                bar_end=bar_end,
                ready=False,
                valid=False,
                reason="formula_consistency_failure",
                dif=dif,
                dea=dea,
                macd=macd,
                ema21=ema21,
            )

        result_codes: tuple[SubingThsResultCode, ...]
        if golden:
            result_codes = ("buy",)
        elif dead:
            result_codes = ("sell",)
        else:
            result_codes = ()
        next_state = SubingThs15mState(
            macd=macd_state,
            ema21=ema21_state,
            previous_dif=dif,
            previous_dea=dea,
        )
        return next_state, SubingThs15mResult(
            formula_version=self.formula_version,
            bar_end=bar_end,
            ready=True,
            valid=True,
            reason=None,
            dif=dif,
            dea=dea,
            macd=macd,
            ema21=ema21,
            result_codes=result_codes,
        )

    def _result(
        self,
        macd_state: MacdState,
        ema21_state: EmaState,
        *,
        bar_end: str | None,
        ready: bool,
        valid: bool,
        reason: str,
        dif: float | None,
        dea: float | None,
        macd: float | None,
        ema21: float | None,
    ) -> tuple[SubingThs15mState, SubingThs15mResult]:
        return (
            SubingThs15mState(
                macd=macd_state,
                ema21=ema21_state,
                previous_dif=None,
                previous_dea=None,
            ),
            SubingThs15mResult(
                formula_version=self.formula_version,
                bar_end=bar_end,
                ready=ready,
                valid=valid,
                reason=reason,
                dif=dif,
                dea=dea,
                macd=macd,
                ema21=ema21,
                result_codes=(),
            ),
        )


def _rounded_finite(value: float | int | None, round_digits: int) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, round_digits)
