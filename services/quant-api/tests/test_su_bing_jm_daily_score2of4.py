from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "su_bing_jm_daily_score2of4"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass
class DailyBar:
    datetime: datetime
    trading_day: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0
    interval: str = "1d"
    price_tick: float = 0.5
    contract_multiplier: int = 60
    commission_rate: float = 0.0001
    margin_rate: float = 0.12
    symbol: str = "jm2405"
    exchange: str = "DCE"


def _bar(index: int, *, close: float, open_price: float | None = None, volume: float = 1000.0) -> DailyBar:
    trading_day = date(2024, 1, 1) + timedelta(days=index)
    open_value = close if open_price is None else open_price
    return DailyBar(
        datetime=datetime.combine(trading_day, datetime.min.time()).replace(hour=15),
        trading_day=trading_day,
        open=open_value,
        high=max(open_value, close) + 10,
        low=min(open_value, close) - 10,
        close=close,
        volume=volume,
    )


def _setting(**overrides) -> dict:
    setting = {
        "price_tick": 0.5,
        "contract_multiplier": 60,
        "commission_rate": 0.0001,
        "margin_rate": 0.12,
        "submit_vnpy_orders": False,
        "live_trading_enabled": False,
        "auto_order_enabled": False,
    }
    setting.update(overrides)
    return setting


def _make_strategy(**overrides):
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import SuBingJmDailyScore2Of4Strategy

    return SuBingJmDailyScore2Of4Strategy(None, "jm-score-test", "jm2405.DCE", _setting(**overrides))


def _snapshot(
    *,
    close: float,
    ema21: float = 100.0,
    dif: float = 1.0,
    dea: float = 0.0,
    previous_dif: float = -1.0,
    previous_dea: float = 0.0,
    current_volume: float = 1200.0,
    previous_volume: float = 1000.0,
):
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import IndicatorSnapshot

    return IndicatorSnapshot(
        ema21=ema21,
        fast_ema=0.0,
        slow_ema=0.0,
        dif=dif,
        dea=dea,
        histogram=dif - dea,
        previous_dif=previous_dif,
        previous_dea=previous_dea,
        current_volume=current_volume,
        previous_volume=previous_volume,
        close=close,
        macd_near_zero=abs(dif) <= 25 and abs(dea) <= 25,
        golden_cross=previous_dif <= previous_dea and dif > dea,
        dead_cross=previous_dif >= previous_dea and dif < dea,
        volume_expanded=current_volume > previous_volume,
    )


def _long_signal_bars(*, expanded_volume: bool = True) -> list[DailyBar]:
    volumes = [1000] * 29 + ([1200] if expanded_volume else [1000])
    return [_bar(index, close=close, volume=volumes[index]) for index, close in enumerate([100] * 29 + [112])]


def _short_signal_bars(*, expanded_volume: bool = True) -> list[DailyBar]:
    volumes = [1000] * 29 + ([1200] if expanded_volume else [1000])
    return [_bar(index, close=close, volume=volumes[index]) for index, close in enumerate([100] * 29 + [80])]


def _feed(strategy, bars: list[DailyBar]) -> None:
    for bar in bars:
        strategy.on_bar(bar)


def test_default_params_identify_independent_score2of4_version() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import STRATEGY_CLASS_PATH, validate_params

    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        raw_params = json.load(file)

    params = validate_params(raw_params)

    assert STRATEGY_CLASS_PATH.endswith("SuBingJmDailyScore2Of4Strategy")
    assert params.strategy_code == "su_bing_jm_daily_ema21_macd_volume"
    assert params.strategy_version == "v0.3.0-daily-score2of4"
    assert params.min_entry_score == 2
    assert params.macd_zero_threshold == 25
    assert params.require_directional_anchor is True
    assert params.ambiguous_tie_action == "reject"
    assert params.emit_skill_tags is True
    assert params.submit_vnpy_orders is False


def test_four_of_four_and_two_of_four_long_signals_are_accepted() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import evaluate_score2of4_signal, validate_params

    params = validate_params()
    full = evaluate_score2of4_signal(_snapshot(close=112), params)
    two = evaluate_score2of4_signal(
        _snapshot(
            close=112,
            dif=80,
            dea=70,
            previous_dif=70,
            previous_dea=60,
            current_volume=1200,
            previous_volume=1000,
        ),
        params,
    )

    assert full.direction == "long"
    assert full.entry_score == 4
    assert full.entry_grade == "A"
    assert full.satisfied_conditions == ["long_trend_ok", "macd_near_zero", "long_macd_cross", "volume_expanded"]
    assert "standard_trend" in full.scene_tags
    assert two.direction == "long"
    assert two.entry_score == 2
    assert two.entry_grade == "C"
    assert two.satisfied_conditions == ["long_trend_ok", "volume_expanded"]
    assert "weak_two_condition" in two.scene_tags


def test_one_condition_and_no_directional_anchor_are_rejected() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import evaluate_score2of4_signal, validate_params

    params = validate_params()
    one_condition = evaluate_score2of4_signal(
        _snapshot(
            close=112,
            dif=80,
            dea=70,
            previous_dif=70,
            previous_dea=60,
            current_volume=1000,
            previous_volume=1000,
        ),
        params,
    )
    no_anchor = evaluate_score2of4_signal(
        _snapshot(
            close=100,
            dif=1,
            dea=0,
            previous_dif=0.5,
            previous_dea=0,
            current_volume=1200,
            previous_volume=1000,
        ),
        params,
    )

    assert one_condition.direction == "none"
    assert one_condition.rejected_reason == "entry_score_below_minimum"
    assert one_condition.long_score == 1
    assert no_anchor.direction == "none"
    assert no_anchor.rejected_reason == "directional_anchor_missing"
    assert no_anchor.long_score == 2
    assert no_anchor.short_score == 2


def test_ambiguous_long_short_score_tie_is_rejected() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import evaluate_score2of4_signal, validate_params

    params = validate_params()
    decision = evaluate_score2of4_signal(
        _snapshot(
            close=112,
            dif=-1,
            dea=0,
            previous_dif=1,
            previous_dea=0,
            current_volume=1000,
            previous_volume=1000,
        ),
        params,
    )

    assert decision.direction == "none"
    assert decision.long_score == 2
    assert decision.short_score == 2
    assert decision.rejected_reason == "ambiguous_direction_score_tie"


def test_macd_cross_can_be_directional_anchor_without_trend_location() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4 import evaluate_score2of4_signal, validate_params

    params = validate_params()
    long_cross_anchor = evaluate_score2of4_signal(_snapshot(close=100), params)
    short_cross_anchor = evaluate_score2of4_signal(
        _snapshot(close=100, dif=-1, dea=0, previous_dif=1, previous_dea=0),
        params,
    )

    assert long_cross_anchor.direction == "long"
    assert long_cross_anchor.entry_score == 3
    assert long_cross_anchor.directional_anchor == "long_macd_cross"
    assert short_cross_anchor.direction == "short"
    assert short_cross_anchor.entry_score == 3
    assert short_cross_anchor.directional_anchor == "short_macd_cross"


def test_long_short_entries_are_symmetric_on_bar_and_fill_next_daily_open() -> None:
    long_strategy = _make_strategy()
    short_strategy = _make_strategy()

    _feed(long_strategy, _long_signal_bars())
    _feed(short_strategy, _short_signal_bars())

    assert long_strategy.pending_action == "open_long"
    assert long_strategy.position_direction == "flat"
    assert long_strategy.signal_candidates[-1]["final_signal"] == "long"
    assert long_strategy.signal_candidates[-1]["long_score"] == 4
    assert short_strategy.pending_action == "open_short"
    assert short_strategy.position_direction == "flat"
    assert short_strategy.signal_candidates[-1]["final_signal"] == "short"
    assert short_strategy.signal_candidates[-1]["short_score"] == 4

    long_strategy.on_bar(_bar(30, close=112, open_price=100, volume=1300))

    assert long_strategy.position_direction == "long"
    assert long_strategy.entry_price == 100.5
    assert long_strategy.execution_events[-1]["signal_datetime"] == _long_signal_bars()[-1].datetime.isoformat()
    assert long_strategy.execution_events[-1]["fill_datetime"] == _bar(30, close=112, open_price=100).datetime.isoformat()


def test_strategy_trade_records_score_tags_and_v02_exit_logic() -> None:
    strategy = _make_strategy()

    _feed(strategy, _long_signal_bars())
    strategy.on_bar(_bar(30, close=112, open_price=100, volume=1300))
    strategy.on_bar(_bar(31, close=80, open_price=98, volume=900))
    strategy.on_bar(_bar(32, close=79, open_price=97, volume=900))

    assert len(strategy.strategy_trades) == 1
    trade = strategy.strategy_trades[0]
    assert trade["strategy_version"] == "v0.3.0-daily-score2of4"
    assert trade["entry_score"] == 4
    assert trade["entry_grade"] == "A"
    assert trade["satisfied_conditions"] == ["long_trend_ok", "macd_near_zero", "long_macd_cross", "volume_expanded"]
    assert "standard_trend" in trade["scene_tags"]
    assert trade["exit_reason"] == "long_close_below_ema21_exit_next_daily_open"
    assert trade["holding_bars"] == 2


def test_future_bars_and_review_tags_are_not_signal_inputs() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4.vnpy_strategy import (
        SuBingJmDailyScore2Of4Strategy,
        evaluate_score2of4_signal,
    )

    strategy = _make_strategy()
    _feed(strategy, _long_signal_bars())
    before_future_bar = dict(strategy.signal_candidates[-1])
    strategy.on_bar(_bar(30, close=400, open_price=100, volume=9000))

    signal_source = inspect.getsource(evaluate_score2of4_signal)
    on_bar_source = inspect.getsource(SuBingJmDailyScore2Of4Strategy.on_bar)

    assert before_future_bar["final_signal"] == "long"
    assert before_future_bar["entry_score"] == 4
    assert "immediate_failure_later" not in signal_source
    assert "immediate_failure_later" not in on_bar_source
    assert "review_tags" not in signal_source
    assert "TAG-" not in signal_source
