# REPORT_10_TRUSTED_EXCLUDING_CROSS_CONTRACT

## Summary

- report_id: `10`
- strategy: `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`
- metric_scope: `trade_level_only`
- raw_trade_count: `7`
- trusted_trade_count: `6`
- excluded_trade_count: `1`
- excluded_trade_ids: `SB-JM-D-3`
- conclusion: P0 partially closed: report 10 has trade-level trusted metrics after excluding cross-contract PnL.

## Raw vs Trusted Metrics

| metric | raw | trusted |
|---|---:|---:|
| net_pnl | 9356.616 | 5296.236 |
| win_rate | 0.4285714286 | 0.3333333333 |
| profit_loss_ratio | 2.1817815805 | 2.7203857918 |
| max_drawdown | 0.0828656832 | 0.0857869818 |
| max_consecutive_losses | 3 | 3 |

## Excluded Trades

| trade_id | entry_contract | exit_contract | net_pnl | pnl_trust_status | exclusion_reason |
|---|---|---|---:|---|---|
| SB-JM-D-3 | JM2405 | JM2409 | 4060.38 | cross_contract_needs_review | entry_contract_differs_from_exit_contract;cross_contract_needs_review |

## Metric Scope

- This file does not change `v0.2.0-daily` strategy behavior.
- Trusted metrics are recomputed from ordered trade-level net PnL only.
- The trusted drawdown is a trade-level equity reconstruction, not a full daily equity-curve recomputation.
- Report 10 remains unsuitable for parameter optimization or v0.3 implementation until a true rollover-safe baseline exists.
