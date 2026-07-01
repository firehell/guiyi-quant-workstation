# V0.3.1 Trend Cross Score2 Design

## Version

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- strategy_version: `v0.3.1-daily-trend-cross-score2`
- class_path: `guiyi_quant.strategies.su_bing_jm_daily_trend_cross_score2.vnpy_strategy.SuBingJmDailyTrendCrossScore2Strategy`
- frozen baselines: `v0.2.0-daily`, `v0.3.0-daily-score2of4`

## Purpose

`v0.3.1` narrows the `v0.3.0` two-of-four entry rule by requiring the two conditions that best match the current discretionary hypothesis:

1. Trend environment must align with direction.
2. MACD must cross in the same direction.

MACD near zero and volume expansion remain scoring conditions and review labels, but they cannot replace the trend-cross gate by default.

## Entry Conditions

Long scoring conditions:

- `long_trend_ok`: daily close is above EMA21.
- `macd_near_zero`: `abs(DIF) <= 25` and `abs(DEA) <= 25`.
- `long_macd_cross`: previous DIF <= previous DEA and current DIF > current DEA.
- `volume_expanded`: current volume > previous volume.

Short scoring conditions:

- `short_trend_ok`: daily close is below EMA21.
- `macd_near_zero`: `abs(DIF) <= 25` and `abs(DEA) <= 25`.
- `short_macd_cross`: previous DIF >= previous DEA and current DIF < current DEA.
- `volume_expanded`: current volume > previous volume.

Default entry gate:

- `entry_score >= min_entry_score`
- `require_trend_alignment = true`
- `require_macd_cross = true`
- no long/short tie
- no existing position

## Exit

- Long exit: daily close falls below EMA21, filled at next daily open.
- Short exit: daily close rises above EMA21, filled at next daily open.
- No stop loss, take profit, time exit, or automatic reversal in this version.

## Default Parameters

```json
{
  "ema_period": 21,
  "macd_fast": 12,
  "macd_slow": 26,
  "macd_signal": 9,
  "macd_zero_threshold": 25,
  "min_entry_score": 2,
  "require_trend_alignment": true,
  "require_macd_cross": true,
  "volume_rule": "current_volume_gt_previous_volume",
  "maximum_position": 1,
  "submit_vnpy_orders": false,
  "live_trading_enabled": false,
  "auto_order_enabled": false
}
```

## Data And Execution

- Product: JM.
- Interval: `1d`.
- Data source: RQData standardized local parquet.
- Data role: `primary`.
- Quality status: `passed`.
- Signal timing: completed daily close.
- Fill timing: next daily open.
- Metric scope: raw and trusted excluding cross-contract PnL.

## Future Function Controls

- Indicators use only current and previous completed daily bars.
- Entry uses current close for signal and next daily open for fill.
- `previous_volume`, `previous_dif`, and `previous_dea` come from the immediately previous completed bar.
- Review-only tags, MFE, MAE, and immediate-failure labels are not strategy inputs.
- Version changes must be recorded as new strategy versions, not by mutating frozen defaults.
