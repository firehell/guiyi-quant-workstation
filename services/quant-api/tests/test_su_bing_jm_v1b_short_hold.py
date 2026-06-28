from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "su_bing_jm_v1b_short_hold"

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
    price_tick: float = 0.5
    contract_multiplier: int = 60
    commission_rate: float = 0.0001
    margin_rate: float = 0.12
    symbol: str = "jm2405"
    exchange: str = "DCE"


def _daily_bars(closes: list[float], *, start: date = date(2024, 1, 1)) -> list[TimedBar]:
    bars = []
    for index, close in enumerate(closes):
        trading_day = start + timedelta(days=index)
        bars.append(
            TimedBar(
                datetime=datetime.combine(trading_day, datetime.min.time()).replace(hour=15),
                trading_day=trading_day,
                open=close - 1.0,
                high=close + 2.0,
                low=close - 2.0,
                close=close,
                volume=1000.0,
            )
        )
    return bars


def _entry_bars(start: datetime, *, minutes: int, closes: list[float]) -> list[TimedBar]:
    bars = []
    for index, close in enumerate(closes):
        moment = start + timedelta(minutes=index * minutes)
        low = close - 0.4
        high = close + 0.4
        if index == len(closes) - 2:
            low = close - 1.5
        bars.append(
            TimedBar(
                datetime=moment,
                trading_day=moment.date(),
                open=close - 0.1,
                high=high,
                low=low,
                close=close,
                volume=250.0,
            )
        )
    return bars


def _base_setting(entry_interval: str = "15m") -> dict:
    return {
        "entry_interval": entry_interval,
        "submit_vnpy_orders": False,
        "price_tick": 0.5,
        "contract_multiplier": 60,
        "commission_rate": 0.0001,
        "margin_rate": 0.12,
    }


def _make_strategy(entry_interval: str = "15m", daily_bars: list[TimedBar] | None = None, **overrides):
    from guiyi_quant.strategies.su_bing_jm_v1b_short_hold import SuBingJmV1bShortHoldStrategy

    setting = _base_setting(entry_interval)
    setting.update(overrides)
    setting["_guiyi_auxiliary_bars"] = {"1d": daily_bars or _daily_bars([100 + index for index in range(30)])}
    return SuBingJmV1bShortHoldStrategy(None, "su-bing-jm-v1b-test", "jm_MAIN.DCE", setting)


def _long_signal_bars(start: datetime, *, minutes: int) -> list[TimedBar]:
    closes = [100.0 for _ in range(22)]
    closes.extend([99.8, 100.4])
    return _entry_bars(start, minutes=minutes, closes=closes)


def test_default_params_json_is_valid_and_frozen_to_v011_spec() -> None:
    from guiyi_quant.strategies.su_bing_jm_v1b_short_hold import STRATEGY_CLASS_PATH, validate_params

    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        raw_params = json.load(file)

    params = validate_params(raw_params)

    assert STRATEGY_CLASS_PATH.endswith("SuBingJmV1bShortHoldStrategy")
    assert params.strategy_code == "su_bing_jm_v1b_short_hold"
    assert params.strategy_version == "v0.1.1-spec"
    assert params.pullback_lookback_bars == 3
    assert params.pullback_interaction_ticks == 1
    assert params.max_entry_ema_distance_ticks == 8
    assert params.stop_buffer_ticks == 1
    assert params.max_initial_stop_distance_ticks == 30
    assert params.take_profit_r_multiple == 1.5
    assert params.planned_time_exit_bars == 8
    assert params.slippage_ticks == 1
    assert params.initial_capital == 1_000_000
    assert params.risk_per_trade_ratio == 0.005
    assert params.maximum_position == 1
    assert params.breakout_breakdown_enabled is False
    assert params.volume_confirmation_enabled is False
    assert params.macd_usage == "record_only_not_filter"


def test_strategy_class_loads_via_strategy_loader() -> None:
    from app.vnpy_integration.strategy_loader import load_strategy_class
    from guiyi_quant.strategies.su_bing_jm_v1b_short_hold import (
        STRATEGY_CLASS_PATH,
        SuBingJmV1bShortHoldStrategy,
    )

    assert load_strategy_class(STRATEGY_CLASS_PATH) is SuBingJmV1bShortHoldStrategy


def test_daily_direction_filter_uses_only_prior_confirmed_daily_bar() -> None:
    from guiyi_quant.strategies.su_bing_jm_v1b_short_hold import (
        confirmed_daily_direction_snapshot,
        validate_params,
    )

    daily = _daily_bars([100 + index for index in range(25)] + [80], start=date(2024, 1, 1))
    current_bar = TimedBar(
        datetime=datetime(2024, 1, 26, 9, 0),
        trading_day=date(2024, 1, 26),
        open=124,
        high=125,
        low=123,
        close=124,
    )

    snapshot = confirmed_daily_direction_snapshot(
        current_bar=current_bar,
        daily_bars=daily,
        params=validate_params(_base_setting()),
    )

    assert snapshot.direction == "long"
    assert snapshot.trading_day == date(2024, 1, 25)
    assert snapshot.reason == "confirmed_daily_long_ema21"


def test_15m_signal_is_pending_then_fills_next_bar_open_with_slippage() -> None:
    strategy = _make_strategy("15m")
    signal_bars = _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15)

    for bar in signal_bars:
        strategy.on_bar(bar)

    assert strategy.pending_action == "open_long"
    assert strategy.position_direction == "flat"
    assert strategy.execution_events == []
    assert strategy.signal_reason.startswith("signal_on_close_pending_next_bar_open")

    fill_bar = TimedBar(
        datetime=datetime(2024, 2, 1, 14, 45),
        trading_day=date(2024, 2, 1),
        open=100.8,
        high=101.4,
        low=100.6,
        close=101.0,
    )
    strategy.on_bar(fill_bar)

    assert strategy.position_direction == "long"
    assert strategy.execution_events[-1]["action"] == "open_long"
    assert strategy.execution_events[-1]["signal_datetime"] == signal_bars[-1].datetime.isoformat()
    assert strategy.execution_events[-1]["fill_datetime"] == fill_bar.datetime.isoformat()
    assert strategy.execution_events[-1]["fill_price"] == pytest.approx(101.3)
    assert strategy.execution_events[-1]["entry_interval"] == "15m"


def test_5m_chain_uses_own_interval_and_same_next_open_policy() -> None:
    strategy = _make_strategy("5m")
    signal_bars = _long_signal_bars(datetime(2024, 2, 1, 9), minutes=5)

    for bar in signal_bars:
        strategy.on_bar(bar)
    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 2, 1, 11, 5),
            trading_day=date(2024, 2, 1),
            open=100.8,
            high=101.4,
            low=100.6,
            close=101.0,
        )
    )

    assert strategy.entry_interval == "5m"
    assert strategy.position_direction == "long"
    assert strategy.execution_events[-1]["entry_interval"] == "5m"
    assert strategy.execution_events[-1]["fill_price"] == pytest.approx(101.3)


def test_missing_trade_parameters_rejects_signal_instead_of_using_zero_defaults() -> None:
    strategy = _make_strategy("15m", price_tick=None)

    for bar in _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15):
        strategy.on_bar(bar)

    assert strategy.pending_action == ""
    assert strategy.position_direction == "flat"
    assert strategy.rejected_signals
    assert strategy.rejected_signals[-1]["rejected_reason"] == "missing_price_tick"


def test_macd_breakout_volume_flags_do_not_participate_in_v011_entry_decision() -> None:
    from guiyi_quant.strategies.su_bing_jm_v1b_short_hold import DEFAULT_PARAMS

    assert DEFAULT_PARAMS["macd_usage"] == "record_only_not_filter"
    assert DEFAULT_PARAMS["breakout_breakdown_enabled"] is False
    assert DEFAULT_PARAMS["volume_confirmation_enabled"] is False

    strategy = _make_strategy("15m")
    assert "macd" not in strategy.entry_reason.lower()
    for bar in _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15):
        strategy.on_bar(bar)

    assert strategy.pending_action == "open_long"
    assert "macd" not in strategy.entry_reason.lower()
    assert "breakout" not in strategy.entry_reason.lower()
    assert "volume" not in strategy.entry_reason.lower()


def test_stop_loss_has_priority_over_take_profit_when_same_bar_hits_both() -> None:
    strategy = _make_strategy("15m")
    for bar in _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15):
        strategy.on_bar(bar)
    strategy.on_bar(TimedBar(datetime=datetime(2024, 2, 1, 14, 45), trading_day=date(2024, 2, 1), open=100.8, high=101.4, low=100.6, close=101.0))
    stop_price = strategy.stop_loss_price
    take_profit_price = strategy.take_profit_price

    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 2, 1, 15, 30),
            trading_day=date(2024, 2, 1),
                open=101.0,
                high=take_profit_price + 1.0,
                low=stop_price - 1.0,
                close=101.0,
        )
    )

    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == pytest.approx(stop_price - 0.5)


def test_take_profit_uses_one_and_half_r() -> None:
    strategy = _make_strategy("15m")
    for bar in _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15):
        strategy.on_bar(bar)
    strategy.on_bar(TimedBar(datetime=datetime(2024, 2, 1, 14, 45), trading_day=date(2024, 2, 1), open=100.8, high=101.4, low=100.6, close=101.0))
    expected_take_profit = strategy.entry_price + abs(strategy.entry_price - strategy.stop_loss_price) * 1.5

    assert strategy.take_profit_price == pytest.approx(expected_take_profit)

    strategy.on_bar(
        TimedBar(
            datetime=datetime(2024, 2, 1, 15, 30),
            trading_day=date(2024, 2, 1),
                open=101.0,
                high=expected_take_profit + 0.1,
                low=strategy.stop_loss_price + 0.1,
            close=expected_take_profit,
        )
    )

    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_price"] == pytest.approx(expected_take_profit - 0.5)


def test_time_exit_closes_on_next_open_after_eighth_holding_bar() -> None:
    strategy = _make_strategy("15m")
    for bar in _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15):
        strategy.on_bar(bar)
    strategy.on_bar(TimedBar(datetime=datetime(2024, 2, 1, 14, 45), trading_day=date(2024, 2, 1), open=100.8, high=101.4, low=100.6, close=101.0))

    for index in range(7):
        moment = datetime(2024, 2, 1, 15, 0) + timedelta(minutes=15 * index)
        strategy.on_bar(
            TimedBar(
                datetime=moment,
                trading_day=date(2024, 2, 1),
                open=101.0,
                high=101.2,
                low=100.8,
                close=101.0,
            )
        )

    assert strategy.pending_action == "close"
    assert strategy.position_direction == "long"

    exit_bar = TimedBar(
        datetime=datetime(2024, 2, 1, 16, 45),
        trading_day=date(2024, 2, 1),
        open=101.2,
        high=101.4,
        low=100.9,
        close=101.1,
    )
    strategy.on_bar(exit_bar)

    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "time_exit_bar_8"
    assert trade["holding_bars"] == 8
    assert trade["exit_price"] == pytest.approx(100.7)


def test_future_bar_does_not_change_prior_decision_state() -> None:
    bars = _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15)
    prefix_strategy = _make_strategy("15m")
    replay_strategy = _make_strategy("15m")

    for bar in bars[:-1]:
        prefix_strategy.on_bar(bar)
    prior_state = (
        prefix_strategy.last_signal,
        prefix_strategy.signal_reason,
        prefix_strategy.pending_action,
        prefix_strategy.position_direction,
    )

    for bar in bars[:-1]:
        replay_strategy.on_bar(bar)

    assert (
        replay_strategy.last_signal,
        replay_strategy.signal_reason,
        replay_strategy.pending_action,
        replay_strategy.position_direction,
    ) == prior_state


def test_review_tags_are_post_trade_only_and_not_strategy_inputs() -> None:
    with (STRATEGY_DIR / "review_tags.json").open(encoding="utf-8") as file:
        payload = json.load(file)

    assert payload["is_post_trade_only"] is True
    assert payload["can_affect_same_trade_signal"] is False
    assert {tag["tag_id"] for tag in payload["tags"]} == {f"TAG-{index:03d}" for index in range(1, 15)}

    strategy = _make_strategy("15m", review_tags=["TAG-001", "TAG-010"])
    for bar in _long_signal_bars(datetime(2024, 2, 1, 9), minutes=15):
        strategy.on_bar(bar)

    assert strategy.pending_action == "open_long"
    assert "TAG-" not in strategy.entry_reason


def test_strategy_directory_avoids_live_trading_and_secret_keywords() -> None:
    forbidden = [
        "TqApi",
        "TqAuth",
        "TqAccount",
        "send_order",
        "insert_order",
        "password",
        "api_key",
        "自动下单",
    ]

    for path in STRATEGY_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".md"}:
            content = path.read_text(encoding="utf-8")
            assert not any(keyword in content for keyword in forbidden), path
