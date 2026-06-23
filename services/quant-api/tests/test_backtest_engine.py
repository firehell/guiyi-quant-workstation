from datetime import datetime, timedelta

from app.backtest.engine import BacktestConfig, BacktestEngine, ContractSpec
from app.strategy.su_bing_ema21 import SignalSnapshot, SuBingParams


TEST_STRATEGY_PARAMS = SuBingParams(
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


def _bars(closes: list[float], lows: list[float] | None = None, highs: list[float] | None = None) -> list[dict]:
    rows = []
    timestamp = datetime(2024, 1, 1, 9, 0)
    previous_close = closes[0]
    for index, close in enumerate(closes):
        open_price = previous_close
        rows.append(
            {
                "symbol": "rb",
                "contract": "rb.MAIN",
                "exchange": "SHFE",
                "datetime": timestamp + timedelta(minutes=index * 5),
                "trading_day": "2024-01-01",
                "open": open_price,
                "high": highs[index] if highs else max(open_price, close) + 2,
                "low": lows[index] if lows else min(open_price, close) - 2,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "period": "5m",
            }
        )
        previous_close = close
    return rows


def _empty_signals(bars: list[dict]) -> list[SignalSnapshot]:
    return [
        SignalSnapshot(
            datetime=bar["datetime"],
            status="空仓",
            direction="neutral",
            signal_level=0,
            reasons=["no signal"],
            features={"atr": 1.0},
            trade_intent={"action": "none", "execution_timing": "next_bar", "order_draft": False},
        )
        for bar in bars
    ]


def _set_signal(signals: list[SignalSnapshot], index: int, action: str, direction: str, reason: str = "test signal") -> None:
    signals[index] = SignalSnapshot(
        datetime=signals[index].datetime,
        status="测试信号",
        direction=direction,  # type: ignore[arg-type]
        signal_level=60,
        reasons=[reason],
        features={"atr": 1.0},
        trade_intent={"action": action, "execution_timing": "next_bar", "order_draft": False},
    )


def _engine(initial_capital: float = 100000, max_margin_usage_pct: float = 0.35, enable_take_profit: bool = False) -> BacktestEngine:
    return BacktestEngine(
        config=BacktestConfig(
            initial_capital=initial_capital,
            max_margin_usage_pct=max_margin_usage_pct,
            enable_take_profit=enable_take_profit,
            strategy_params=TEST_STRATEGY_PARAMS,
        ),
        contract_spec=ContractSpec(price_tick=1, volume_multiple=10, margin_rate=0.10, open_fee=0.0001, close_fee=0.0001),
    )


def test_signal_executes_on_next_bar_open_with_costs_and_margin() -> None:
    bars = _bars([100, 100, 101, 103], lows=[98, 95, 99, 101])
    signals = _empty_signals(bars)
    _set_signal(signals, 1, "trial_entry", "long", "轻仓试多")

    report = _engine().run(bars, signals=signals)

    fill = report.fills[0]
    assert fill.time == bars[2]["datetime"]
    assert fill.base_price == bars[2]["open"]
    assert fill.price == bars[2]["open"] + 1
    assert fill.commission > 0
    assert fill.slippage == fill.volume * 10
    assert fill.margin > 0
    assert len(report.equity_curve) == len(bars)
    assert report.summary["total_commission"] == fill.commission


def test_add_reduce_and_exit_generate_trade_details() -> None:
    bars = _bars([100, 100, 103, 106, 109, 112, 115, 118, 120], lows=[98, 95, 99, 102, 105, 108, 111, 114, 116])
    signals = _empty_signals(bars)
    _set_signal(signals, 1, "trial_entry", "long", "entry")
    _set_signal(signals, 3, "add_watch", "long", "add")
    _set_signal(signals, 5, "reduce", "long", "reduce")
    _set_signal(signals, 7, "exit", "neutral", "exit")

    report = _engine().run(bars, signals=signals)

    assert len(report.fills) >= 4
    assert len(report.trades) >= 2
    assert sum(trade.volume for trade in report.trades) > 0
    assert report.trades[-1].exit_reason == "exit"
    assert report.summary["total_trades"] == len(report.trades)


def test_insufficient_margin_rejects_order_and_records_warning() -> None:
    bars = _bars([100, 100, 101, 102])
    signals = _empty_signals(bars)
    _set_signal(signals, 1, "trial_entry", "long")

    report = _engine(initial_capital=1000, max_margin_usage_pct=0.01).run(bars, signals=signals)

    assert not report.fills
    assert report.summary["rejected_orders"] == 1
    assert any("保证金不足" in warning or "无可成交手数" in warning for warning in report.warnings)


def test_stop_loss_is_conservative_when_stop_and_take_profit_touch_same_bar() -> None:
    bars = _bars(
        [100, 100, 102, 103],
        lows=[98, 98, 97, 101],
        highs=[102, 102, 110, 105],
    )
    signals = _empty_signals(bars)
    _set_signal(signals, 1, "trial_entry", "long", "entry")

    report = _engine(enable_take_profit=True).run(bars, signals=signals)

    assert report.trades
    trade = report.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.net_pnl < 0
    assert trade.close_time == bars[2]["datetime"]


def test_summary_contains_drawdown_win_rate_profit_loss_and_consecutive_losses() -> None:
    bars = _bars([100, 100, 102, 104, 101, 101, 99, 97, 98])
    signals = _empty_signals(bars)
    _set_signal(signals, 1, "trial_entry", "long", "win")
    _set_signal(signals, 3, "exit", "neutral", "win exit")
    _set_signal(signals, 5, "trial_entry", "long", "loss")

    report = _engine().run(bars, signals=signals)

    assert "max_drawdown" in report.summary
    assert "win_rate" in report.summary
    assert "profit_loss_ratio" in report.summary
    assert "max_consecutive_losses" in report.summary
    assert len(report.drawdown_curve) == len(bars)
    assert max(point.drawdown_pct for point in report.drawdown_curve) >= 0


def test_backtest_does_not_change_past_fills_when_future_bars_are_removed() -> None:
    bars = _bars([100, 100, 102, 104, 106, 108, 110, 112])
    signals = _empty_signals(bars)
    _set_signal(signals, 1, "trial_entry", "long")
    _set_signal(signals, 5, "exit", "neutral")
    full = _engine().run(bars, signals=signals)

    for end in range(3, len(bars) + 1):
        truncated = _engine().run(bars[:end], signals=signals[:end])
        cutoff = bars[end - 1]["datetime"]
        full_past = [(fill.time, fill.action, fill.direction, fill.volume, fill.price) for fill in full.fills if fill.time <= cutoff]
        truncated_fills = [(fill.time, fill.action, fill.direction, fill.volume, fill.price) for fill in truncated.fills]
        assert truncated_fills == full_past
