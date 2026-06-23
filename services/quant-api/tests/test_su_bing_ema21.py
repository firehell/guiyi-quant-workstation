from datetime import datetime, timedelta

import pytest

from app.strategy.su_bing_ema21 import (
    STATUS_CONFIRM_LONG,
    STATUS_CONFIRM_SHORT,
    STATUS_EXIT_LONG,
    STATUS_FLAT,
    STATUS_HOLD_LONG,
    STATUS_HOLD_SHORT,
    STATUS_REDUCE_LONG,
    STATUS_TRIAL_LONG,
    STATUS_TRIAL_SHORT,
    STATUS_WATCH_LONG,
    STATUS_WATCH_SHORT,
    SuBingParams,
    generate_signals,
)


BASE_PARAMS = SuBingParams(
    ema_period=3,
    macd_fast=2,
    macd_slow=4,
    macd_signal=2,
    atr_period=3,
    breakout_lookback=3,
    confirmation_bars=2,
    volume_ratio_intraday=1.5,
    zero_axis_atr_threshold=10,
    max_distance_from_ema_atr=99,
    confluence_threshold=3,
    volume_lookback=3,
    macd_cross_lookback=5,
    chop_cross_threshold=99,
    rapid_move_atr_threshold=99,
)


def _bars(
    closes: list[float],
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    period: str = "5m",
) -> list[dict]:
    rows = []
    timestamp = datetime(2024, 1, 1, 9, 0)
    previous_close = closes[0]
    volumes = volumes or [100] * len(closes)
    for index, close in enumerate(closes):
        open_price = previous_close
        high = highs[index] if highs else max(open_price, close) + 0.2
        low = lows[index] if lows else min(open_price, close) - 0.2
        rows.append(
            {
                "symbol": "rb",
                "contract": "rb.MAIN",
                "exchange": "SHFE",
                "datetime": timestamp + timedelta(minutes=index * 5),
                "trading_day": "2024-01-01",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volumes[index],
                "open_interest": 1000 + index,
                "period": period,
            }
        )
        previous_close = close
    return rows


def test_long_trend_progresses_from_watch_to_trial_confirm_and_hold() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2, 102.4]
    volumes = [100] * len(closes)
    volumes[7] = 300

    signals = generate_signals(_bars(closes, volumes), params=BASE_PARAMS)
    statuses = [signal.status for signal in signals]

    assert STATUS_WATCH_LONG in statuses
    assert STATUS_TRIAL_LONG in statuses
    assert STATUS_CONFIRM_LONG in statuses
    assert STATUS_HOLD_LONG in statuses
    trial = next(signal for signal in signals if signal.status == STATUS_TRIAL_LONG)
    assert trial.direction == "long"
    assert trial.trade_intent["action"] == "trial_entry"
    assert trial.trade_intent["execution_timing"] == "next_bar"
    assert trial.trade_intent["order_draft"] is False
    assert any("带量突破" in reason for reason in trial.reasons)


def test_short_trend_progresses_from_watch_to_trial_confirm_and_hold() -> None:
    closes = [100, 100.2, 100.4, 100.6, 100.8, 100.7, 100.5, 100.2, 98.5, 98.2, 98.0, 97.8, 97.6]
    volumes = [100] * len(closes)
    volumes[7] = 300

    signals = generate_signals(_bars(closes, volumes), params=BASE_PARAMS)
    statuses = [signal.status for signal in signals]

    assert STATUS_WATCH_SHORT in statuses
    assert STATUS_TRIAL_SHORT in statuses
    assert STATUS_CONFIRM_SHORT in statuses
    assert STATUS_HOLD_SHORT in statuses
    trial = next(signal for signal in signals if signal.status == STATUS_TRIAL_SHORT)
    assert trial.direction == "short"
    assert any("带量跌破" in reason for reason in trial.reasons)


def test_choppy_ema_crossing_keeps_strategy_flat() -> None:
    closes = [100, 99.8, 100.2, 99.7, 100.3, 99.6, 100.4, 99.5, 100.5, 99.4, 100.6, 99.3]
    volumes = [200] * len(closes)
    params = SuBingParams(
        **{**BASE_PARAMS.__dict__, "chop_cross_threshold": 2, "breakout_lookback": 2}
    )

    signals = generate_signals(_bars(closes, volumes), params=params)

    assert all(signal.status != STATUS_TRIAL_LONG for signal in signals)
    assert all(signal.status != STATUS_TRIAL_SHORT for signal in signals)
    assert any("反复穿越" in reason for signal in signals for reason in signal.reasons)


def test_macd_far_from_zero_blocks_entry_confirmation() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0]
    volumes = [100] * len(closes)
    volumes[7] = 300
    params = SuBingParams(**{**BASE_PARAMS.__dict__, "zero_axis_atr_threshold": 0.001})

    signals = generate_signals(_bars(closes, volumes), params=params)

    assert all(signal.status != STATUS_TRIAL_LONG for signal in signals)
    assert any("MACD未处于零轴附近" in reason for signal in signals for reason in signal.reasons)


def test_false_breakout_exits_trial_position() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 100.0, 99.65]
    highs = [100.2, 100.0, 99.8, 99.6, 99.4, 99.5, 99.7, 100.2, 100.2]
    lows = [99.8, 99.6, 99.4, 99.2, 99.0, 99.1, 99.3, 99.3, 99.4]
    volumes = [100] * len(closes)
    volumes[7] = 300

    signals = generate_signals(_bars(closes, volumes, highs=highs, lows=lows), params=BASE_PARAMS)

    assert STATUS_TRIAL_LONG in [signal.status for signal in signals]
    exit_signal = signals[-1]
    assert exit_signal.status == STATUS_EXIT_LONG
    assert any("假突破" in reason for reason in exit_signal.reasons)


def test_breaking_ema_or_previous_bar_reduces_or_exits_position() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 101.0]
    volumes = [100] * len(closes)
    volumes[7] = 300

    signals = generate_signals(_bars(closes, volumes), params=BASE_PARAMS)

    assert signals[-1].status in {STATUS_REDUCE_LONG, STATUS_EXIT_LONG}
    assert any("EMA21" in reason or "低点" in reason for reason in signals[-1].reasons)


def test_higher_timeframe_resonance_increases_signal_level() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5]
    volumes = [100] * len(closes)
    volumes[7] = 300
    primary = _bars(closes, volumes)
    higher = _bars([99, 99.2, 99.4, 99.6, 99.8, 100.0, 100.2, 100.4, 100.6])

    without_higher = generate_signals(primary, params=BASE_PARAMS)
    with_higher = generate_signals(primary, higher_timeframe_bars=higher, params=BASE_PARAMS)

    plain_trial = next(signal for signal in without_higher if signal.status == STATUS_TRIAL_LONG)
    resonant_trial = next(signal for signal in with_higher if signal.status == STATUS_TRIAL_LONG)
    assert resonant_trial.signal_level > plain_trial.signal_level
    assert resonant_trial.features["higher_timeframe_resonance"] is True


def test_non_flat_signals_always_have_reasons() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0]
    volumes = [100] * len(closes)
    volumes[7] = 300

    signals = generate_signals(_bars(closes, volumes), params=BASE_PARAMS)

    assert all(signal.reasons for signal in signals if signal.status != STATUS_FLAT)


def test_signal_generation_does_not_use_future_bars() -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2]
    volumes = [100] * len(closes)
    volumes[7] = 300
    bars = _bars(closes, volumes)

    full = generate_signals(bars, params=BASE_PARAMS)

    for end_index in range(7, len(bars) + 1):
        truncated = generate_signals(bars[:end_index], params=BASE_PARAMS)
        assert [signal.status for signal in truncated] == [signal.status for signal in full[:end_index]]
        assert [signal.reasons for signal in truncated] == [signal.reasons for signal in full[:end_index]]


def test_invalid_or_unsorted_bars_are_rejected() -> None:
    bars = _bars([100, 101])
    bars[1]["datetime"] = bars[0]["datetime"]

    with pytest.raises(ValueError, match="strictly sorted"):
        generate_signals(bars, params=BASE_PARAMS)
