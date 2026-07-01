from __future__ import annotations

from typing import Any

from .config_schema import DEFAULT_PARAMS, SuBingJmDailyTrendCrossScore2Params, validate_params

from guiyi_quant.strategies.su_bing_jm_daily_score2of4.vnpy_strategy import (
    CtaTemplate,
    IndicatorSnapshot,
    PendingOrder,
    Score2Of4Decision as TrendCrossScore2Decision,
    SuBingJmDailyScore2Of4Strategy,
    calculate_indicators,
    _bar_datetime,
    _min_bars,
)


STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.su_bing_jm_daily_trend_cross_score2.vnpy_strategy."
    "SuBingJmDailyTrendCrossScore2Strategy"
)


class SuBingJmDailyTrendCrossScore2Strategy(SuBingJmDailyScore2Of4Strategy):
    author = "guiyi_quant"
    parameters = list(DEFAULT_PARAMS)
    variables = [
        "last_signal",
        "signal_reason",
        "pending_action",
        "position_direction",
        "entry_reason",
        "exit_reason",
        "entry_price",
        "ema21",
        "dif",
        "dea",
        "histogram",
        "current_volume",
        "previous_volume",
        "long_score",
        "short_score",
    ]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        CtaTemplate.__init__(self, cta_engine, strategy_name, vt_symbol, setting)
        strategy_setting = {key: value for key, value in setting.items() if not key.startswith("_guiyi_")}
        self._explicit_none_trade_params = {
            key
            for key in ("price_tick", "contract_multiplier", "commission_rate", "commission_per_contract", "margin_rate")
            if key in strategy_setting and strategy_setting[key] is None
        }
        self._params: SuBingJmDailyTrendCrossScore2Params = validate_params(strategy_setting)
        for name, value in self._params.to_dict().items():
            setattr(self, name, value)

        self._bars: list[Any] = []
        self._pending_order: PendingOrder | None = None
        self._position_state = None
        self.strategy_trades: list[dict[str, Any]] = []
        self.execution_events: list[dict[str, Any]] = []
        self.rejected_signals: list[dict[str, Any]] = []
        self.signal_candidates: list[dict[str, Any]] = []

        self.last_signal = "none"
        self.signal_reason = "not_started"
        self.pending_action = ""
        self.position_direction = "flat"
        self.entry_reason = ""
        self.exit_reason = ""
        self.entry_price = 0.0
        self.ema21 = 0.0
        self.dif = 0.0
        self.dea = 0.0
        self.histogram = 0.0
        self.current_volume = 0.0
        self.previous_volume = 0.0
        self.long_score = 0
        self.short_score = 0

    def on_init(self) -> None:
        self.write_log("Su Bing JM daily trend-cross score2 strategy initialized")

    def on_start(self) -> None:
        self.write_log("Su Bing JM daily trend-cross score2 strategy started")

    def on_stop(self) -> None:
        self.write_log("Su Bing JM daily trend-cross score2 strategy stopped")

    def _schedule_entry_if_available(self, bar: Any, bar_index: int) -> None:
        if len(self._bars) < _min_bars(self._params):
            self.last_signal = "none"
            self.signal_reason = "warming_up"
            return

        trade_params, missing_reason = self._resolve_trade_params(bar)
        if missing_reason is not None:
            self._reject_signal(bar, missing_reason)
            return

        indicators = calculate_indicators(self._bars, self._params)
        self._set_indicators(indicators)
        decision = evaluate_trend_cross_score2_signal(indicators, self._params)
        self._append_signal_candidate(bar, decision)
        if decision.direction == "none":
            self._reject_signal(bar, decision.rejected_reason or decision.reason)
            return

        assert trade_params is not None
        action = "open_long" if decision.direction == "long" else "open_short"
        self._pending_order = PendingOrder(
            action=action,
            direction=decision.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=bar_index,
            reason=decision.reason,
            trade_params=trade_params,
            indicators=indicators,
            decision=decision,
        )
        self.pending_action = action
        self.last_signal = decision.direction
        self.signal_reason = f"signal_on_daily_close_pending_next_daily_open|{decision.reason}"
        self.entry_reason = decision.reason

    def _close_position(
        self,
        bar: Any,
        *,
        exit_price: float,
        exit_reason: str,
        exit_signal_datetime: Any,
        exit_indicators: IndicatorSnapshot,
    ) -> None:
        previous_count = len(self.strategy_trades)
        super()._close_position(
            bar,
            exit_price=exit_price,
            exit_reason=exit_reason,
            exit_signal_datetime=exit_signal_datetime,
            exit_indicators=exit_indicators,
        )
        if len(self.strategy_trades) > previous_count:
            self.strategy_trades[-1]["trade_id"] = f"SB-JM-TC-D-{len(self.strategy_trades)}"


def evaluate_trend_cross_score2_signal(
    indicators: IndicatorSnapshot,
    params: SuBingJmDailyTrendCrossScore2Params,
) -> TrendCrossScore2Decision:
    long_conditions = {
        "long_trend_ok": indicators.close > indicators.ema21,
        "macd_near_zero": indicators.macd_near_zero,
        "long_macd_cross": indicators.golden_cross,
        "volume_expanded": indicators.volume_expanded,
    }
    short_conditions = {
        "short_trend_ok": indicators.close < indicators.ema21,
        "macd_near_zero": indicators.macd_near_zero,
        "short_macd_cross": indicators.dead_cross,
        "volume_expanded": indicators.volume_expanded,
    }
    long_score = sum(long_conditions.values())
    short_score = sum(short_conditions.values())
    long_gate = bool(long_conditions["long_trend_ok"] and long_conditions["long_macd_cross"])
    short_gate = bool(short_conditions["short_trend_ok"] and short_conditions["short_macd_cross"])
    long_eligible = params.allow_long and long_score >= params.min_entry_score and long_gate
    short_eligible = params.allow_short and short_score >= params.min_entry_score and short_gate

    if not long_eligible and not short_eligible:
        rejected_reason = _trend_cross_reject_reason(
            long_conditions=long_conditions,
            short_conditions=short_conditions,
            long_score=long_score,
            short_score=short_score,
            params=params,
        )
        return _decision(
            "none",
            rejected_reason,
            indicators,
            rejected_reason,
            long_conditions,
            short_conditions,
            long_score,
            short_score,
        )

    if long_eligible and short_eligible:
        if long_score == short_score:
            return _decision(
                "none",
                "ambiguous_direction_score_tie",
                indicators,
                "ambiguous_direction_score_tie",
                long_conditions,
                short_conditions,
                long_score,
                short_score,
            )
        direction = "long" if long_score > short_score else "short"
    elif long_eligible:
        direction = "long"
    else:
        direction = "short"

    selected_conditions = long_conditions if direction == "long" else short_conditions
    selected_score = long_score if direction == "long" else short_score
    trend_key = f"{direction}_trend_ok"
    cross_key = f"{direction}_macd_cross"
    reason = "+".join(name for name, passed in selected_conditions.items() if passed)
    return _decision(
        direction,
        reason,
        indicators,
        None,
        long_conditions,
        short_conditions,
        long_score,
        short_score,
        selected_score=selected_score,
        directional_anchor=f"{trend_key}+{cross_key}",
    )


def _trend_cross_reject_reason(
    *,
    long_conditions: dict[str, bool],
    short_conditions: dict[str, bool],
    long_score: int,
    short_score: int,
    params: SuBingJmDailyTrendCrossScore2Params,
) -> str:
    if max(long_score, short_score) < params.min_entry_score:
        return "entry_score_below_minimum"
    long_has_trend = long_conditions["long_trend_ok"]
    short_has_trend = short_conditions["short_trend_ok"]
    long_has_cross = long_conditions["long_macd_cross"]
    short_has_cross = short_conditions["short_macd_cross"]
    if not long_has_trend and not short_has_trend:
        return "trend_alignment_required"
    if (long_has_trend and not long_has_cross) or (short_has_trend and not short_has_cross):
        return "macd_cross_required"
    if (long_has_cross and not long_has_trend) or (short_has_cross and not short_has_trend):
        return "trend_alignment_required"
    return "trend_cross_entry_conditions_not_met"


def _decision(
    direction: str,
    reason: str,
    indicators: IndicatorSnapshot,
    rejected_reason: str | None,
    long_conditions: dict[str, bool],
    short_conditions: dict[str, bool],
    long_score: int,
    short_score: int,
    *,
    selected_score: int | None = None,
    directional_anchor: str = "",
) -> TrendCrossScore2Decision:
    selected_conditions = long_conditions if direction == "long" else short_conditions if direction == "short" else {}
    entry_score = selected_score if selected_score is not None else max(long_score, short_score)
    satisfied = [name for name, passed in selected_conditions.items() if passed] if selected_conditions else []
    failed = [name for name, passed in selected_conditions.items() if not passed] if selected_conditions else []
    return TrendCrossScore2Decision(
        direction=direction,
        reason=reason,
        indicators=indicators,
        rejected_reason=rejected_reason,
        long_score=long_score,
        short_score=short_score,
        entry_score=entry_score,
        entry_grade=_entry_grade(entry_score) if direction in {"long", "short"} else "",
        satisfied_conditions=satisfied,
        failed_conditions=failed,
        scene_tags=_scene_tags(direction, indicators, entry_score, selected_conditions),
        skill_notes=_skill_notes(direction, selected_conditions),
        directional_anchor=directional_anchor,
    )


def _entry_grade(score: int) -> str:
    return "A" if score >= 4 else "B" if score == 3 else "C" if score == 2 else ""


def _scene_tags(direction: str, indicators: IndicatorSnapshot, score: int, selected_conditions: dict[str, bool]) -> list[str]:
    if direction not in {"long", "short"}:
        return []
    tags = ["trend_cross_confirmed"]
    tags.append("standard_trend" if score >= 4 else "trend_cross_without_full_confirmation")
    if not selected_conditions.get("volume_expanded"):
        tags.append("no_volume_expansion")
    if not selected_conditions.get("macd_near_zero"):
        tags.append("macd_zero_band_missing")
    if score == 2:
        tags.append("minimum_trend_cross_only")
    distance = abs(indicators.close - indicators.ema21)
    if indicators.ema21 and distance / max(abs(indicators.ema21), 1e-9) > 0.08:
        tags.append("chase_risk")
    return tags


def _skill_notes(direction: str, selected_conditions: dict[str, bool]) -> list[str]:
    if direction not in {"long", "short"}:
        return []
    notes = ["trend_cross_score2_research_signal"]
    if selected_conditions.get("volume_expanded"):
        notes.append("volume_is_confirmation_not_hard_skill_rule")
    if not selected_conditions.get("macd_near_zero"):
        notes.append("macd_zero_band_missing")
    return notes
