from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "jm_v1b_daily_direction_fast_entry"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass
class TimedBar:
    datetime: datetime
    trading_day: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 200.0


def _base_setting(entry_interval: str = "15m") -> dict:
    return {
        "entry_interval": entry_interval,
        "ema_period": 2,
        "macd_fast": 2,
        "macd_slow": 3,
        "macd_signal": 2,
        "atr_period": 2,
        "volume_window": 2,
        "volume_multiplier_15m": 1.0,
        "volume_multiplier_5m": 1.0,
        "pullback_lookback_bars": 2,
        "pullback_touch_ema_atr": 100.0,
        "max_ema_distance_atr_15m": 100.0,
        "max_ema_distance_atr_5m": 100.0,
        "stop_loss_atr_multiple": 1.0,
        "structure_stop_lookback_bars": 2,
        "stop_buffer_ticks": 0,
        "pricetick": 1.0,
        "submit_vnpy_orders": False,
        "daily_ema_period": 2,
        "daily_ema_slope_lookback": 1,
        "daily_ema_slope_min_atr": 0.0001,
        "daily_macd_fast": 2,
        "daily_macd_slow": 3,
        "daily_macd_signal": 2,
        "daily_atr_period": 2,
        "daily_neutral_ema_band_atr": 0.01,
        "daily_max_ema_distance_atr": 100.0,
    }


def _daily_bars(closes: list[float], *, start: date = date(2024, 1, 1)) -> list[TimedBar]:
    bars = []
    for index, close in enumerate(closes):
        trading_day = start + timedelta(days=index)
        bars.append(
            TimedBar(
                datetime=datetime.combine(trading_day, datetime.min.time()).replace(hour=15),
                trading_day=trading_day,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1000.0,
            )
        )
    return bars


def _entry_bars(start: datetime, *, minutes: int, closes: list[float]) -> list[TimedBar]:
    bars = []
    for index, close in enumerate(closes):
        moment = start + timedelta(minutes=index * minutes)
        bars.append(
            TimedBar(
                datetime=moment,
                trading_day=moment.date(),
                open=close,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=250.0,
            )
        )
    return bars


def _make_strategy(entry_interval: str = "15m", daily_bars: list[TimedBar] | None = None):
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry import JmV1bDailyDirectionFastEntryStrategy

    setting = _base_setting(entry_interval)
    setting["_guiyi_auxiliary_bars"] = {"1d": daily_bars or _daily_bars([100, 101, 102, 104, 106])}
    return JmV1bDailyDirectionFastEntryStrategy(None, "jm-v1b-test", "jm_MAIN.DCE", setting)


def test_default_params_json_is_valid_and_v1b_scoped() -> None:
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry import STRATEGY_CLASS_PATH, validate_params

    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        raw_params = json.load(file)

    params = validate_params(raw_params)

    assert STRATEGY_CLASS_PATH.endswith("JmV1bDailyDirectionFastEntryStrategy")
    assert params.entry_interval == "15m"
    assert params.max_hold_bars_min == 5
    assert params.max_hold_bars_max == 8


def test_daily_direction_filter_uses_only_completed_daily_bars() -> None:
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry import (
        confirmed_daily_direction_snapshot,
        validate_params,
    )

    daily = _daily_bars([100, 101, 102, 104, 106, 80], start=date(2024, 1, 1))
    current_bar = TimedBar(
        datetime=datetime(2024, 1, 6, 9, 0),
        trading_day=date(2024, 1, 6),
        open=105,
        high=106,
        low=104,
        close=105,
    )
    snapshot = confirmed_daily_direction_snapshot(
        current_bar=current_bar,
        daily_bars=daily,
        params=validate_params(_base_setting()),
    )

    assert snapshot.direction == "long"
    assert snapshot.trading_day == date(2024, 1, 5)
    assert snapshot.reason == "confirmed_daily_long_ema21_macd_atr"


def test_15m_entry_profile_generates_signal_then_fills_next_bar() -> None:
    strategy = _make_strategy("15m")
    signal_bars = _entry_bars(
        datetime(2024, 1, 6, 9, 0),
        minutes=15,
        closes=[100.0, 100.5, 101.0, 100.8, 101.2, 103.0],
    )

    for bar in signal_bars:
        strategy.on_bar(bar)

    assert strategy.entry_interval == "15m"
    assert strategy.pending_action == "open_long"
    assert strategy.position_direction == "flat"
    assert strategy.signal_reason.startswith("signal_on_close_pending_next_bar_open")

    fill_bar = TimedBar(
        datetime=datetime(2024, 1, 6, 10, 30),
        trading_day=date(2024, 1, 6),
        open=103.5,
        high=104.5,
        low=103.0,
        close=104.0,
        volume=250,
    )
    strategy.on_bar(fill_bar)

    assert strategy.position_direction == "long"
    assert strategy.execution_events[-1]["action"] == "open_long"
    assert strategy.execution_events[-1]["signal_datetime"] == signal_bars[-1].datetime.isoformat()
    assert strategy.execution_events[-1]["fill_datetime"] == fill_bar.datetime.isoformat()
    assert strategy.execution_events[-1]["entry_interval"] == "15m"


def test_5m_entry_profile_uses_5m_params_and_fills_next_bar() -> None:
    strategy = _make_strategy("5m")
    signal_bars = _entry_bars(
        datetime(2024, 1, 6, 9, 0),
        minutes=5,
        closes=[100.0, 100.5, 101.0, 100.8, 101.2, 103.0],
    )

    for bar in signal_bars:
        strategy.on_bar(bar)
    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 1, 6, 9, 30),
            trading_day=date(2024, 1, 6),
            open=103.5,
            high=104.0,
            low=103.0,
            close=103.8,
            volume=250,
        )
    )

    assert strategy.entry_interval == "5m"
    assert strategy.position_direction == "long"
    assert strategy.execution_events[-1]["entry_interval"] == "5m"
    assert strategy.entry_reason == "daily_long_ema21_pullback_macd_confirmed"


def test_max_hold_bars_exit_records_hold_bars_and_reason() -> None:
    strategy = _make_strategy("15m")
    signal_bars = _entry_bars(
        datetime(2024, 1, 6, 9, 0),
        minutes=15,
        closes=[100.0, 100.5, 101.0, 100.8, 101.2, 103.0],
    )
    for bar in signal_bars:
        strategy.on_bar(bar)

    for index in range(9):
        moment = datetime(2024, 1, 6, 10, 30) + timedelta(minutes=15 * index)
        strategy.on_bar(
            TimedBar(
                datetime=moment,
                trading_day=date(2024, 1, 6),
                open=103.5 + index * 0.1,
                high=104.5 + index * 0.1,
                low=103.0 + index * 0.1,
                close=104.0 + index * 0.1,
                volume=250,
            )
        )

    assert strategy.strategy_trades
    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "max_hold_bars_exit"
    assert trade["hold_bars"] == 8
    assert trade["daily_direction"] == "long"
    assert trade["entry_interval"] == "15m"
    assert trade["stop_loss_price"] > 0


def test_stop_loss_exit_records_required_reason_fields() -> None:
    strategy = _make_strategy("15m")
    signal_bars = _entry_bars(
        datetime(2024, 1, 6, 9, 0),
        minutes=15,
        closes=[100.0, 100.5, 101.0, 100.8, 101.2, 103.0],
    )
    for bar in signal_bars:
        strategy.on_bar(bar)
    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 1, 6, 10, 30),
            trading_day=date(2024, 1, 6),
            open=103.5,
            high=104.0,
            low=103.0,
            close=103.8,
            volume=250,
        )
    )
    stop_price = strategy.stop_loss_price

    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 1, 6, 10, 45),
            trading_day=date(2024, 1, 6),
            open=103.0,
            high=103.2,
            low=stop_price - 0.1,
            close=stop_price - 0.2,
            volume=250,
        )
    )

    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "stop_loss_atr_or_structure"
    assert trade["entry_reason"] == "daily_long_ema21_pullback_macd_confirmed"
    assert trade["hold_bars"] >= 1
    assert trade["stop_loss_price"] == pytest.approx(stop_price)
    assert strategy.position_direction == "flat"


def test_signal_fill_offset_has_no_current_close_fill() -> None:
    strategy = _make_strategy("15m")
    signal_bars = _entry_bars(
        datetime(2024, 1, 6, 9, 0),
        minutes=15,
        closes=[100.0, 100.5, 101.0, 100.8, 101.2, 103.0],
    )

    for bar in signal_bars:
        strategy.on_bar(bar)

    assert strategy.pending_action == "open_long"
    assert strategy.execution_events == []
    assert strategy.position_direction == "flat"

    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 1, 6, 10, 30),
            trading_day=date(2024, 1, 6),
            open=104.25,
            high=105.0,
            low=104.0,
            close=104.5,
            volume=250,
        )
    )

    fill_event = strategy.execution_events[-1]
    assert fill_event["signal_datetime"] == signal_bars[-1].datetime.isoformat()
    assert fill_event["fill_datetime"] == "2024-01-06T10:30:00"
    assert fill_event["fill_price"] == 104.25
