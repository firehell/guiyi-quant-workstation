# ROLLOVER_SAFE_FINAL_HANDOFF

## Summary

- report_id: `10`
- strategy: `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`
- baseline behavior changed: no
- v0.3 implemented: no
- rollover-safe implemented: no
- trusted exclusion report generated: yes
- final gate: `P0 partially closed`

## Completed

1. Confirmed SB-JM-D-3 is the only report 10 cross-contract trade.
2. Confirmed forced rollover must not be implemented from `jm.MAIN` prices.
3. Added trade-level trusted metrics excluding SB-JM-D-3.
4. Preserved `v0.2.0-daily` strategy parameters and signal behavior.

## Raw vs Trusted

| metric | raw | trusted excluding cross-contract |
|---|---:|---:|
| trade_count | 7 | 6 |
| net_pnl | 9356.616 | 5296.236 |
| win_rate | 0.4285714286 | 0.3333333333 |
| profit_loss_ratio | 2.1817815805 | 2.7203857918 |
| max_drawdown | 0.0828656832 | 0.0857869818 |
| max_consecutive_losses | 3 | 3 |

## Files For ChatGPT Review

- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/ROLLOVER_SAFE_DATA_AVAILABILITY_AUDIT.md`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_TRUSTED_EXCLUDING_CROSS_CONTRACT.md`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_2_1_ROLLOVER_SAFE_BLOCKED_BY_DATA.md`
- `backtests/reports/report_10_trusted_excluding_cross_contract.csv`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_ROLLOVER_AUDIT.md`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_DAILY_STRATEGY_DESIGN.md`

## Gate Decision

Gate B: `P0 partially closed`.

Report 10 now has trusted trade-level metrics for review. It still does not have a fresh rollover-safe baseline, so do not use it for parameter optimization, condition-ablation PnL conclusions, or v0.3 implementation approval.

## Next TODO

1. Open a data-center task for actual-contract daily standardization.
2. After formal data promotion, implement `v0.2.1-daily-rollover-safe` as a separate version/config.
3. Re-run the same JM daily window and require `cross_contract_trades=0`.
4. Only then revisit the condition ablation matrix and v0.3 implementation.

