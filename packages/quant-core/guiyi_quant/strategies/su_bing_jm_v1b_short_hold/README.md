# Su Bing JM V1-B Short Hold

This package implements the independent `su_bing_jm_v1b_short_hold` strategy from
`docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md` version `v0.1.1-spec`.

It is not a patch to `su_bing_ema21`, and it does not import or inherit that strategy.

## Class Path

```text
guiyi_quant.strategies.su_bing_jm_v1b_short_hold.vnpy_strategy.SuBingJmV1bShortHoldStrategy
```

## Frozen v0.1.1 Rules

- Product scope: JM research bars supplied by the adapter or tests.
- Direction filter: confirmed daily EMA21 only, using daily bars before the current trading day.
- Entry intervals: `15m` and `5m`, selected independently through `entry_interval`.
- Entry setup: `pullback_only`.
- Disabled in this version: breakout, breakdown, volume confirmation, and MACD filtering.
- Signal and fill: current completed bar creates the signal; the next same-interval bar open fills it with one tick of slippage.
- Stop: signal-bar extreme plus one tick.
- Take profit: `1.5R`.
- Time exit: bar 8, filled at the next bar open.
- Conflict rule: stop loss before take profit when one bar touches both levels.

## Review Tags

`review_tags.json` is post-trade metadata. Tags are not read by `on_bar`, cannot affect the same-trade signal, and may only support review notes or later version review.

## Boundaries

The strategy records internal research trades through `strategy_trades` and `execution_events`. It does not modify the backtest engine, Web, database migrations, or any gateway layer.

## Tests

```bash
cd /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api
uv run pytest -q tests/test_su_bing_jm_v1b_short_hold.py
```
