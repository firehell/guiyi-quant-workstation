# V0_2_1_ROLLOVER_SAFE_BLOCKED_BY_DATA

## Summary

`v0.2.1-daily-rollover-safe` is not implemented in this round.

The blocker is not strategy logic. It is formal data eligibility: raw RQData actual-contract daily prices are present, but they have not been standardized and registered as primary canonical inputs for the daily strategy backtest path.

## Why Forced Rollover Is Blocked

- `v0.2.0-daily` trades on `jm.MAIN` research bars.
- Report 10 resolves entry/exit contracts by timestamp after the fact.
- SB-JM-D-3 opens as `JM2405` and exits after the main mapping has moved to `JM2409`.
- A correct forced exit must close the old `JM2405` position with real `JM2405` prices.
- This round must not substitute `jm.MAIN` or `JM2409` prices for an old-contract `JM2405` exit.

## Current Safe Output

Use `REPORT_10_TRUSTED_EXCLUDING_CROSS_CONTRACT.md` and `report_10_trusted_excluding_cross_contract.csv`.

These outputs exclude SB-JM-D-3 from trusted metrics and mark `metric_scope=trade_level_only`.

## Next Required Data Work

Before implementation, add a separate data-center task to promote actual-contract daily data into the formal data lake:

1. Standardize `JM2405`, `JM2409`, `JM2505`, and `JM2601` daily bars.
2. Add or verify `datetime`, `trading_day`, OHLC, `volume`, `open_interest`, contract id, provider, role, quality, and data version fields.
3. Register the files in `market_data_files` or the current formal data index.
4. Add data quality checks for SB-JM-D-3's holding window.
5. Only then implement a new versioned rollover-safe task/config.

## Gate

P0 status is `partially_closed`.

The cross-contract trade is excluded from trusted report 10 metrics, but no new rollover-safe baseline exists yet.

