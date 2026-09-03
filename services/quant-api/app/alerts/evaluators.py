"""Alert Runtime evaluators and their bounded candidate contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.alerts.registry import HTDY_RULE, SUBING_THS_RULE
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import (
    CurrentContractReplayWindow,
    MarketReadService,
    MarketReadWindow,
    MarketReadWindowError,
)
from guiyi_quant.indicators import (
    HTDY_ALERT_OBSERVATION_CONSUMER,
    compute_htdy_original,
    get_indicator,
    require_formal_policy,
)
from guiyi_quant.indicators.htdy_original import HtdyOriginalResult
from guiyi_quant.indicators.subing_ths import SubingThs15mKernel, SubingThs15mState


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


@dataclass(frozen=True, slots=True)
class AlertObservationCandidate:
    bar_end: datetime
    trading_day: date
    contract: str
    observation_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SubingCursor:
    contract: str
    last_bar_end: datetime
    state: SubingThs15mState


class AlertEvaluationError(RuntimeError):
    """Evaluator 输入或 capability 不满足固定合同时 fail closed。"""


class AlertEvaluator(Protocol):
    def evaluate_candidates(
        self,
        market_read: MarketReadService,
        window: MarketReadWindow,
    ) -> tuple[AlertObservationCandidate, ...]: ...


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

    def evaluate_candidates(
        self,
        market_read: MarketReadService,
        window: MarketReadWindow,
    ) -> tuple[AlertObservationCandidate, ...]:
        del market_read
        return tuple(
            AlertObservationCandidate(
                bar_end=candidate.bar_end,
                trading_day=candidate.trading_day,
                contract=candidate.contract,
                observation_types=candidate.observation_types,
            )
            for candidate in self.evaluate_first_seen(window)
        )

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


class SubingThs15mEvaluator:
    """Forward-only, same-physical-contract adapter around the S1 authority."""

    formula_version = "subing_ths_15m_v3"

    def __init__(self, *, kernel: SubingThs15mKernel | None = None) -> None:
        self._kernel = kernel or SubingThs15mKernel()
        self._cursors: dict[str, _SubingCursor] = {}

    def evaluate_candidates(
        self,
        market_read: MarketReadService,
        window: MarketReadWindow,
    ) -> tuple[AlertObservationCandidate, ...]:
        self._validate_window(window)
        cursor = self._cursors.get(window.symbol)
        if cursor is not None and cursor.contract == window.contract and window.cutoff <= cursor.last_bar_end:
            return ()
        after = cursor.last_bar_end if cursor is not None and cursor.contract == window.contract else None
        try:
            replay = market_read.current_contract_replay_window(window, after=after)
        except MarketReadWindowError as exc:
            raise AlertEvaluationError(_market_read_error_code(exc)) from None
        self._validate_replay(window, replay)
        state = cursor.state if cursor is not None and cursor.contract == window.contract else self._kernel.initial_state()
        final = None
        for bar in replay.bars:
            state, final = self._kernel.step(state, float(bar.close), bar_end=bar.bar_end.isoformat())
        if replay.bars:
            self._cursors[window.symbol] = _SubingCursor(
                contract=window.contract,
                last_bar_end=replay.bars[-1].bar_end,
                state=state,
            )
        if final is None:
            return ()
        if not final.valid:
            raise AlertEvaluationError("ALERT_EVALUATION_INPUT_INVALID")
        if not final.ready:
            raise AlertEvaluationError("ALERT_EVALUATION_WARMING_UP")
        if final.result_codes not in {(), ("buy",), ("sell",)}:
            raise AlertEvaluationError("ALERT_EVALUATION_FAILED")
        if not final.result_codes:
            return ()
        last = replay.bars[-1]
        return (
            AlertObservationCandidate(
                bar_end=last.bar_end,
                trading_day=last.trading_day,
                contract=window.contract,
                observation_types=final.result_codes,
            ),
        )

    @staticmethod
    def _validate_window(window: MarketReadWindow) -> None:
        if (
            window.series_kind != SUBING_THS_RULE.series_kind
            or window.frequency != "15m"
            or not window.bars
            or window.bars[-1].bar_end != window.cutoff
            or len(window.bar_contracts) != len(window.bars)
            or window.bar_contracts[-1] != window.contract
        ):
            raise AlertEvaluationError("ALERT_EVALUATION_INPUT_INVALID")

    @staticmethod
    def _validate_replay(
        decision: MarketReadWindow,
        replay: CurrentContractReplayWindow,
    ) -> None:
        if (
            replay.symbol != decision.symbol
            or replay.frequency != decision.frequency
            or replay.contract != decision.contract
            or replay.cutoff != decision.cutoff
            or (replay.bars and replay.bars[-1].bar_end != decision.cutoff)
        ):
            raise AlertEvaluationError("ALERT_EVALUATION_INPUT_INVALID")


def _market_read_error_code(error: MarketReadWindowError) -> str:
    code = str(error)
    if code in {
        "MARKET_READ_AFTER_EXCEEDS_CUTOFF",
        "MARKET_READ_AFTER_TIMEZONE_REQUIRED",
        "MARKET_READ_WINDOW_INVALID",
    }:
        return "ALERT_EVALUATION_INPUT_INVALID"
    return "ALERT_EVALUATION_FAILED"

def _observation_types(result: HtdyOriginalResult, index: int) -> tuple[str, ...]:
    observations: list[str] = []
    if bool(result.buy_observation[index]):
        observations.append("buy")
    if bool(result.sell_observation[index]):
        observations.append("sell")
    return tuple(observations)
