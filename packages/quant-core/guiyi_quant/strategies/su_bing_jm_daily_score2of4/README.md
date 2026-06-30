# Su Bing JM Daily Score 2 of 4

This package implements the independent `v0.3.0-daily-score2of4` research
version for the `su_bing_jm_daily_ema21_macd_volume` strategy family.

It does not modify or inherit mutable behavior from `v0.2.0-daily`.

## Class Path

```text
guiyi_quant.strategies.su_bing_jm_daily_score2of4.vnpy_strategy.SuBingJmDailyScore2Of4Strategy
```

## Rules

- Interval: daily bars only.
- Signal timing: completed daily close.
- Fill timing: next daily open with one adverse tick of slippage.
- Entry: long/short score is computed from trend location, MACD near-zero,
  MACD cross, and volume expansion.
- Default entry threshold: any 2 of 4 conditions plus at least one directional
  anchor.
- Ambiguous equal long/short score: reject.
- Exit: same as v0.2, opposite-side EMA21 daily close exits next daily open.
- Review labels are emitted as research metadata only.

## Boundaries

No live trading, auto ordering, ATR stop, fast-fail, profit protection, Web,
database migration, or vn.py source changes are included in this version.
