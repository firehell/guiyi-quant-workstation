# HTDY Strict Formal Backtest Candidate

This package implements `huotian_dayou_strict / v0.1.0-backtest-candidate`.

It is a formal backtest candidate for `huotian_dayou_strict_v1`; it does not
upgrade `huotian_dayou_original_v0`, does not use XMA, and does not connect to
scanner, live evaluator, signal events, enterprise WeChat, or any trading
gateway.

## Class Path

```text
guiyi_quant.strategies.huotian_dayou_strict.vnpy_strategy.HuoTianDaYouStrictStrategy
```

## Frozen Candidate Rules

- Signal fields come only from strict backward-looking `huotian_dayou_strict_v1`.
- `buy_observation` or `xg_observation` is interpreted as a long candidate.
- `sell_observation` is interpreted as a short candidate or reverse-exit candidate.
- Current closed bar confirms a signal; the next same-interval bar open fills it.
- Stop loss uses signal-bar extreme plus one tick.
- Take profit is fixed at `1.5R`.
- Time exit is scheduled after bar 8 and filled at the next bar open.
- Same-bar long/short conflict is skipped and recorded as `conflict_candidate_skipped`.
- Stop loss has priority over take profit when one bar touches both levels.
- Same-bar reverse is forbidden; reverse observation closes first and waits for a later closed bar to re-enter.

## Cost Boundary

The strategy rejects candidate entries when `price_tick`, `contract_multiplier`,
commission rule, or `margin_rate` is unavailable. It records research trades and
mapped order rows for dry-run/report conversion, but it never submits live or
gateway orders.

## Version Boundary

```text
indicator_version = huotian_dayou_strict_v1
strategy_code = huotian_dayou_strict
strategy_version = v0.1.0-backtest-candidate
candidate_policy = strict_v1_15m_formal_candidate_v0
fill_policy = signal_on_close_fill_next_bar_open
execution_scope = formal_backtest_candidate
```
