# CURRENT_CODE_RULES_v0.2.0

## Scope

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- strategy_version: `v0.2.0-daily`
- report_id: `10`
- task_id: `17`
- data_source: `local_parquet`
- data_role: `primary`
- data_version: `rqdata_jm_standard_1d_20230103_20251231_v1`

## Current Entry Logic

The actual code in `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/vnpy_strategy.py` only accepts daily bars.

- Warm-up requires `max(21, 12, 26, 9) + 2` completed daily bars.
- Indicators use completed daily close/volume only: EMA21, MACD DIF/DEA/histogram with `12/26/9`.
- MACD near-zero is `abs(DIF) <= 25 and abs(DEA) <= 25`.
- Volume confirmation is `current_volume > previous_volume`.
- Long signal: `close > EMA21`, MACD near zero, golden cross, volume expansion.
- Short signal: `close < EMA21`, MACD near zero, dead cross, volume expansion.
- Signal is produced on completed daily close and filled on the next daily open with one adverse tick.

## Current Exit Logic

- Long exit: completed daily close below EMA21, filled on next daily open.
- Short exit: completed daily close above EMA21, filled on next daily open.
- Fixed stop loss, take profit, time exit, pyramiding, same-day reverse, live trading, and auto ordering are disabled.

## Current Parameters

See `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/config_schema.py` and `default_params.json`.

- `ema_period=21`
- `macd_fast=12`
- `macd_slow=26`
- `macd_signal=9`
- `jm_macd_zero_band=25`
- `volume_confirm_enabled=True`
- `volume_rule=current_volume_gt_previous_volume`
- `maximum_position=1`
- `allow_long=True`
- `allow_short=True`
- `slippage_ticks=1`
- `submit_vnpy_orders=False`
- `live_trading_enabled=False`
- `auto_order_enabled=False`

## submit_vnpy_orders=False

`submit_vnpy_orders=False` means this strategy records internal research trades in `strategy_trades` and runtime events in `execution_events`.
It does not submit vn.py order objects for the engine order ledger.

Therefore `orders_count=0` and `strategy_execution_events_count=14` can coexist with 7 completed research trades.
The 14 execution events map to 7 opens and 7 closes.

## Rejected Reason Generation

The code evaluates rejected reasons in this order:

1. `macd_not_near_zero`
2. `volume_not_expanded`
3. `daily_entry_conditions_not_met`

Report 10 runtime rejected reasons:

- `macd_not_near_zero`: 310
- `volume_not_expanded`: 87
- `daily_entry_conditions_not_met`: 79

## Possible Code vs Su Bing Thought Gaps

These are疑点 only, not conclusions:

- EMA21 is used as a strict close-position filter, but no trend-strength or structure context is encoded.
- MACD near-zero threshold `25` is a current spec decision, not proven here as a course rule.
- Volume confirmation is reduced to `current_volume > previous_volume`.
- No explicit anti-chase, range filter, fixed stop loss, floating profit protection, or review-tag feedback is used in signal generation.
- Holding can last many daily bars because time exit is disabled.
- Cross-contract PnL needs extra review when entry and exit mapped contracts differ.
