"""Alert Runtime 的 HTDY current-bar 与 forward-only first-seen evaluator。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.alerts.registry import HTDY_RULE
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from guiyi_quant.indicators import (
    HTDY_ALERT_OBSERVATION_CONSUMER,
    compute_htdy_original,
    get_indicator,
    require_formal_policy,
)
from guiyi_quant.indicators.htdy_original import HtdyOriginalResult


CURRENT_BAR_CONTEXT_BARS = 32


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    observation_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HtdyFirstSeenObservation:
    bar_end: datetime
    trading_day: date
    contract: str
    observation_types: tuple[str, ...]


class AlertEvaluationError(RuntimeError):
    """Evaluator 输入或 capability 不满足固定合同时 fail closed。"""


class AlertEvaluator(Protocol):
    indicator_code: str

    def evaluate(self, window: MarketReadWindow) -> AlertEvaluation: ...

    def evaluate_first_seen(
        self,
        window: MarketReadWindow,
    ) -> tuple[HtdyFirstSeenObservation, ...]: ...


class HtdyOriginalEvaluator:
    indicator_code = "huotian_dayou_original_v0"
    context_bars = CURRENT_BAR_CONTEXT_BARS

    def evaluate(self, window: MarketReadWindow) -> AlertEvaluation:
        self._validate_policy()
        self._validate_window(window, minimum=CURRENT_BAR_CONTEXT_BARS)
        result = self._compute(window.bars[-CURRENT_BAR_CONTEXT_BARS:])
        return AlertEvaluation(observation_types=_observation_types(result, -1))

    def evaluate_first_seen(
        self,
        window: MarketReadWindow,
    ) -> tuple[HtdyFirstSeenObservation, ...]:
        self._validate_policy()
        self._validate_window(window, minimum=CURRENT_BAR_CONTEXT_BARS)
        current = self._compute(window.bars[-CURRENT_BAR_CONTEXT_BARS:])
        return self._latest_candidate(window, _observation_types(current, -1))

    def _validate_policy(self) -> None:
        definition = get_indicator(self.indicator_code)
        if definition.alert_capable is not True:
            raise AlertEvaluationError("ALERT_EVALUATION_CAPABILITY_DISABLED")
        try:
            require_formal_policy(
                definition.formal_policy_id,
                consumer=HTDY_ALERT_OBSERVATION_CONSUMER,
            )
        except (KeyError, ValueError):
            raise AlertEvaluationError("ALERT_EVALUATION_POLICY_DISABLED") from None

    @staticmethod
    def _validate_window(window: MarketReadWindow, *, minimum: int) -> None:
        if (
            window.series_kind != "actual_dominant"
            or window.frequency not in HTDY_RULE.input_frequencies
            or len(window.bars) < minimum
            or not window.bars
            or window.bars[-1].bar_end != window.cutoff
            or len(window.bar_contracts) != len(window.bars)
            or window.bar_contracts[-1] != window.contract
        ):
            raise AlertEvaluationError("ALERT_EVALUATION_INPUT_INVALID")

    @staticmethod
    def _compute(bars: tuple[CanonicalBar, ...]) -> HtdyOriginalResult:
        return compute_htdy_original(
            [bar.bar_end for bar in bars],
            [float(bar.open) for bar in bars],
            [float(bar.high) for bar in bars],
            [float(bar.low) for bar in bars],
            [float(bar.close) for bar in bars],
            [float(bar.volume) for bar in bars],
        )

    @staticmethod
    def _latest_candidate(
        window: MarketReadWindow,
        observations: tuple[str, ...],
    ) -> tuple[HtdyFirstSeenObservation, ...]:
        if not observations:
            return ()
        bar = window.bars[-1]
        return (
            HtdyFirstSeenObservation(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                contract=window.bar_contracts[-1],
                observation_types=observations,
            ),
        )

def _observation_types(result: HtdyOriginalResult, index: int) -> tuple[str, ...]:
    observations: list[str] = []
    if bool(result.buy_observation[index]):
        observations.append("buy")
    if bool(result.sell_observation[index]):
        observations.append("sell")
    return tuple(observations)
