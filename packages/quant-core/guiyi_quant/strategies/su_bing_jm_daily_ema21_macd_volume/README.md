# Su Bing JM Daily EMA21 MACD Volume

This package implements the independent `su_bing_jm_daily_ema21_macd_volume`
strategy from `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md`
version `v0.2.0-daily`.

It is not a patch to `su_bing_jm_v1b_short_hold`, and it does not import or
inherit rules from `su_bing_ema21`.

## Class Path

```text
guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.vnpy_strategy.SuBingJmDailyEma21MacdVolumeStrategy
```

## Frozen v0.2.0-daily Rules

- Product scope: JM research bars supplied by the adapter or tests.
- Interval: `1d` daily bars only.
- Indicators: EMA21, MACD DIF/DEA/histogram with 12/26/9 periods.
- MACD near-zero band: `abs(DIF) <= 25` and `abs(DEA) <= 25`.
- Volume confirmation: current daily volume must be greater than previous daily volume.
- Long entry: daily close above EMA21 plus near-zero MACD golden cross plus volume expansion.
- Short entry: daily close below EMA21 plus near-zero MACD dead cross plus volume expansion.
- Signal and fill: completed daily close creates a pending order; the next daily open fills it with one tick of adverse slippage.
- Exit: long exits after daily close below EMA21; short exits after daily close above EMA21. Exit fills at the next daily open.
- Disabled in this version: fixed stop loss, fixed take profit, time exit, pyramiding, same-day reverse, live trading, and auto ordering.

## Review Tags

`review_tags.json` is post-trade metadata. Tags are not read by `on_bar`, cannot
affect the same-trade signal, and may only support review notes or later version
review.

## Boundaries

The strategy records internal research trades through `strategy_trades`,
`execution_events`, and `rejected_signals`. It does not modify the backtest
engine, Web, database migrations, vn.py source, or gateway layers.

## Tests

```bash
cd /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api
uv run pytest -q tests/test_su_bing_jm_daily_ema21_macd_volume.py
uv run ruff check tests/test_su_bing_jm_daily_ema21_macd_volume.py ../../packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume
```
