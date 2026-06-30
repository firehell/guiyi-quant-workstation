# su_bing_jm_daily_trend_cross_score2

Independent `v0.3.1-daily-trend-cross-score2` research version for the
`su_bing_jm_daily_ema21_macd_volume` strategy family.

This version keeps the v0.3 scoring artifacts, but tightens the default entry
rule: a trade must have both trend alignment and the matching MACD cross. The
near-zero MACD band and volume expansion remain score and review fields.

Class path:

```text
guiyi_quant.strategies.su_bing_jm_daily_trend_cross_score2.vnpy_strategy.SuBingJmDailyTrendCrossScore2Strategy
```

It is daily-only, research-only, and does not submit live or simulated orders.
