"""Alert V1 的唯一 HTDY current-bar evaluator。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.market_data.market_read_service import MarketReadWindow
from guiyi_quant.indicators import (
    HTDY_ALERT_OBSERVATION_CONSUMER,
    compute_htdy_original,
    get_indicator,
    require_formal_policy,
)


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    observation_types: tuple[str, ...]


class AlertEvaluationError(RuntimeError):
    """Evaluator 输入或 capability 不满足固定合同时 fail closed。"""


class AlertEvaluator(Protocol):
    indicator_code: str
    frequency: str

    def evaluate(self, window: MarketReadWindow) -> AlertEvaluation: ...


class HtdyOriginal15mEvaluator:
    indicator_code = "huotian_dayou_original_v0"
    frequency = "15m"
    context_bars = 32

    def evaluate(self, window: MarketReadWindow) -> AlertEvaluation:
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
        if (
            window.series_kind != "actual_dominant"
            or window.frequency != self.frequency
            or len(window.bars) < self.context_bars
            or not window.bars
            or window.bars[-1].bar_end != window.cutoff
        ):
            raise AlertEvaluationError("ALERT_EVALUATION_INPUT_INVALID")

        bars = window.bars[-self.context_bars :]
        result = compute_htdy_original(
            [bar.bar_end for bar in bars],
            [float(bar.open) for bar in bars],
            [float(bar.high) for bar in bars],
            [float(bar.low) for bar in bars],
            [float(bar.close) for bar in bars],
            [float(bar.volume) for bar in bars],
        )
        observations: list[str] = []
        if bool(result.buy_observation[-1]):
            observations.append("buy")
        if bool(result.sell_observation[-1]):
            observations.append("sell")
        return AlertEvaluation(observation_types=tuple(observations))
