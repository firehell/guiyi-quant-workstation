from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "su_bing_jm_daily_ema21_macd_volume"

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
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume import (
        SuBingJmDailyEma21MacdVolumeStrategy,
    )

    return SuBingJmDailyEma21MacdVolumeStrategy(None, "jm-daily-test", "jm2405.DCE", _setting(**overrides))


def _long_signal_bars(*, expanded_volume: bool = True) -> list[DailyBar]:
    volumes = [1000] * 29 + ([1200] if expanded_volume else [1000])
    return [_bar(index, close=close, volume=volumes[index]) for index, close in enumerate([100] * 28 + [80, 112])]


def _short_signal_bars(*, expanded_volume: bool = True) -> list[DailyBar]:
    volumes = [1000] * 29 + ([1200] if expanded_volume else [1000])
    return [_bar(index, close=close, volume=volumes[index]) for index, close in enumerate([100] * 29 + [80])]


def _feed(strategy, bars: list[DailyBar]) -> None:
    for bar in bars:
        strategy.on_bar(bar)


def test_strategy_imports_and_default_params_validate() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume import (
        STRATEGY_CLASS_PATH,
        SuBingJmDailyEma21MacdVolumeStrategy,
        validate_params,
    )

    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        raw_params = json.load(file)

    params = validate_params(raw_params)

    assert STRATEGY_CLASS_PATH.endswith("SuBingJmDailyEma21MacdVolumeStrategy")
    assert SuBingJmDailyEma21MacdVolumeStrategy.__name__ == "SuBingJmDailyEma21MacdVolumeStrategy"
    assert params.strategy_code == "su_bing_jm_daily_ema21_macd_volume"
    assert params.strategy_version == "v0.2.0-daily"
    assert params.interval == "1d"
    assert params.jm_macd_zero_band == 25


def test_interval_and_disabled_runtime_features_are_rejected() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume import validate_params

    for interval in ("15m", "5m"):
        with pytest.raises(ValueError, match="interval must be 1d"):
            validate_params({"interval": interval})
    for disabled_flag in (
        "stop_loss_enabled",
        "take_profit_enabled",
        "time_exit_enabled",
        "submit_vnpy_orders",
        "live_trading_enabled",
        "auto_order_enabled",
    ):
        with pytest.raises(ValueError, match=f"{disabled_flag} must stay false"):
            validate_params({disabled_flag: True})

    strategy = _make_strategy()
    intraday = _bar(0, close=100)
    intraday.interval = "5m"
    strategy.on_bar(intraday)

    assert strategy.pending_action == ""
    assert strategy.rejected_signals[-1]["rejected_reason"] == "non_daily_bar_rejected"


def test_volume_confirmation_and_macd_cross_decisions() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume import validate_params
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.vnpy_strategy import (
        calculate_indicators,
        decide_signal,
    )

    params = validate_params()
    long_snapshot = calculate_indicators(_long_signal_bars(), params)
    short_snapshot = calculate_indicators(_short_signal_bars(), params)
    no_volume_snapshot = calculate_indicators(_long_signal_bars(expanded_volume=False), params)

    assert long_snapshot.golden_cross is True
    assert decide_signal(long_snapshot, params).direction == "long"
    assert short_snapshot.dead_cross is True
    assert decide_signal(short_snapshot, params).direction == "short"
    assert no_volume_snapshot.volume_expanded is False
    assert decide_signal(no_volume_snapshot, params).rejected_reason == "volume_not_expanded"


def test_long_short_entries_are_symmetric_on_bar() -> None:
    long_strategy = _make_strategy()
    short_strategy = _make_strategy()

    _feed(long_strategy, _long_signal_bars())
    _feed(short_strategy, _short_signal_bars())

    assert long_strategy.pending_action == "open_long"
    assert long_strategy.position_direction == "flat"
    assert "daily_close_above_ema21" in long_strategy.entry_reason
    assert "macd_near_zero_golden_cross" in long_strategy.entry_reason
    assert "volume_expansion" in long_strategy.entry_reason
    assert short_strategy.pending_action == "open_short"
    assert short_strategy.position_direction == "flat"
    assert "daily_close_below_ema21" in short_strategy.entry_reason
    assert "macd_near_zero_dead_cross" in short_strategy.entry_reason
    assert "volume_expansion" in short_strategy.entry_reason


def test_ema21_failure_exit_for_long_and_short() -> None:
    long_strategy = _make_strategy()
    _feed(long_strategy, _long_signal_bars())
    long_strategy.on_bar(_bar(30, close=112, open_price=100, volume=1300))
    long_strategy.on_bar(_bar(31, close=80, open_price=98, volume=900))

    assert long_strategy.position_direction == "long"
    assert long_strategy.pending_action == "close"
    assert long_strategy.exit_reason == "long_close_below_ema21_exit_next_daily_open"

    short_strategy = _make_strategy()
    _feed(short_strategy, _short_signal_bars())
    short_strategy.on_bar(_bar(30, close=80, open_price=100, volume=1300))
    short_strategy.on_bar(_bar(31, close=120, open_price=98, volume=900))

    assert short_strategy.position_direction == "short"
    assert short_strategy.pending_action == "close"
    assert short_strategy.exit_reason == "short_close_above_ema21_exit_next_daily_open"


def test_review_tags_are_post_trade_only_and_not_signal_inputs() -> None:
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.vnpy_strategy import (
        SuBingJmDailyEma21MacdVolumeStrategy,
        decide_signal,
    )

    with (STRATEGY_DIR / "review_tags.json").open(encoding="utf-8") as file:
        payload = json.load(file)

    signal_source = inspect.getsource(decide_signal)
    on_bar_source = inspect.getsource(SuBingJmDailyEma21MacdVolumeStrategy.on_bar)

    assert payload["is_post_trade_only"] is True
    assert payload["can_affect_same_trade_signal"] is False
    assert "review_tags" not in signal_source
    assert "TAG-" not in signal_source
    assert "review_tags" not in on_bar_source
    assert "TAG-" not in on_bar_source
