# REPORT_10_ROLLOVER_AUDIT

## Summary

- report_id: `10`
- strategy: `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`
- research symbol: `jm.MAIN`
- trade count: `7`
- cross-contract trades: `1`
- conclusion: SB-JM-D-3 is `needs_review` and its current PnL is `untrusted_cross_contract_pnl` for strategy evaluation.

## Current Implementation Evidence

| Item | Finding |
|---|---|
| 主力映射来源 | `services/quant-api/app/backtest/contract_resolver.py` uses `main_contract_map` with provider `rqdata`, rule `volume_open_interest`, rank `1`. |
| entry/exit contract enrichment | `services/quant-api/app/backtest/jm_daily_ema21_result_enricher.py` resolves entry and exit contracts by trade timestamps. |
| PnL price source | Strategy trades are generated on `jm.MAIN` research bars; the daily enricher recomputes cost and PnL from the research entry/exit prices plus resolved contract parameters. |
| Existing rollover handling | Daily v0.2 summary explicitly records `forced_rollover_exit_policy=not_applied_for_daily_v0_2_0`. |
| Baseline behavior | `v0.2.0-daily` must remain frozen; no forced rollover exit is silently applied to existing baseline reports. |

## Trade-Level Rollover Review

| trade_id | direction | entry_contract | exit_contract | holding_bars_current_value | net_pnl | trust_status | decision |
|---|---|---|---|---:|---:|---|---|
| SB-JM-D-1 | long | JM2401 | JM2401 | 28 | 12550.461 | traceable_same_contract | Same-contract PnL is traceable, subject to normal cost review. |
| SB-JM-D-2 | long | JM2405 | JM2405 | 1 | -4823.208 | traceable_same_contract | Same-contract PnL is traceable. |
| SB-JM-D-3 | short | JM2405 | JM2409 | 20 | 4060.38 | cross_contract_needs_review | Mark as `untrusted_cross_contract_pnl`; do not use as optimization target. |
| SB-JM-D-4 | short | JM2409 | JM2409 | 26 | 7449.663 | traceable_same_contract | Same-contract PnL is traceable. |
| SB-JM-D-5 | short | JM2505 | JM2505 | 5 | -1933.308 | traceable_same_contract | Same-contract PnL is traceable. |
| SB-JM-D-6 | short | JM2505 | JM2505 | 6 | -1842.909 | traceable_same_contract | Same-contract PnL is traceable. |
| SB-JM-D-7 | long | JM2601 | JM2601 | 9 | -6104.463 | traceable_same_contract | Same-contract PnL is traceable. |

## Why SB-JM-D-3 Is Not Trusted Yet

- It opens in `JM2405` and closes after the main mapping has moved to `JM2409`.
- The strategy did not force an exit before the main contract change.
- The report has no evidence that the trade was rolled as two executable real-contract legs.
- The `+4060.38` net PnL mixes a continuous research bar path with timestamp-aware real-contract labels.
- This trade can support rule review and K-line context review, but not direct parameter or version selection.

## Rollover-Safe Design

Recommended separate behavior:

1. Add a new strategy version or task mode, not a silent change to `v0.2.0-daily`.
2. Suggested version: `v0.2.1-daily-rollover-safe`.
3. When a position entry contract is `A` and the current mapped main contract changes to `B`, schedule a forced exit on the latest available daily open before or at the switch boundary.
4. Record `exit_reason=forced_rollover_exit` or `main_contract_roll_exit`.
5. Set `rollover_forced_exit=true`.
6. Do not auto-reopen on the new contract; the next completed daily bar must satisfy entry rules again.
7. Report `rollover_exit_count` separately and keep cross-contract trades excluded from optimization metrics.

## Implementation Gate

The short-hold V1-B path already has a forced-exit pattern in `jm_v1b_result_enricher.py`, but the daily v0.2 path has no versioned rollover-safe task/config yet. Hard-wiring the behavior into `jm_daily_ema21_result_enricher.py` would change the frozen baseline. Therefore this stage does not implement rollover-safe behavior.

## Safety Result

- P0 remains open for strategy evaluation: cross-contract PnL is not trusted.
- Stage 5 may produce a condition ablation plan only.
- Stage 7 v0.3 implementation is blocked until a rollover-safe report or explicit cross-contract exclusion policy exists.
