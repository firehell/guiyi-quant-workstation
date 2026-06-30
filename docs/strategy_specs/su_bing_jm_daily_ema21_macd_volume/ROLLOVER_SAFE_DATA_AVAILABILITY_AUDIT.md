# ROLLOVER_SAFE_DATA_AVAILABILITY_AUDIT

## Summary

- strategy: `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`
- report_id: `10`
- target trade: `SB-JM-D-3`
- target holding window: `2024-03-12` to `2024-04-11`
- conclusion: `implementation_blocked`

Raw RQData actual-contract daily files exist for `JM2405` and `JM2409`, including the SB-JM-D-3 holding window. However, the formal V1 backtest input currently remains canonical primary `jm.MAIN` daily data. The actual-contract daily files have not been promoted into the standard primary data lake and are not registered as the formal backtest input for this strategy.

Therefore this round must not implement forced rollover exit or use new-contract prices to close an old-contract position. The allowed output is a cross-contract exclusion trusted report.

## Checked Files

| item | path | status |
|---|---|---|
| canonical JM main daily | `data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_1d_20230103_20251231.parquet` | available, formal primary input |
| raw JM2405 daily | `data/raw/rqdata/futures_daily_provider/contract=JM2405/JM2405_2005_2026.parquet` | available, raw audit source only |
| raw JM2409 daily | `data/raw/rqdata/futures_daily_provider/contract=JM2409/JM2409_2005_2026.parquet` | available, raw audit source only |
| raw JM2505 daily | `data/raw/rqdata/futures_daily_provider/contract=JM2505/JM2505_2005_2026.parquet` | available, raw audit source only |
| raw JM2601 daily | `data/raw/rqdata/futures_daily_provider/contract=JM2601/JM2601_2005_2026.parquet` | available, raw audit source only |

## Field Coverage

| source | datetime field | OHLC | volume | open_interest | contract id | standard metadata |
|---|---|---|---|---|---|---|
| canonical `jm.MAIN` daily | `datetime`, `trading_day` | yes | yes | yes | `contract`, `source_symbol` | `source`, `provider`, `data_role`, `quality_status`, `data_version` |
| raw `JM2405` daily | `date` | yes | yes | yes | `order_book_id`, `contract` | no formal `data_role` / `quality_status` columns |
| raw `JM2409` daily | `date` | yes | yes | yes | `order_book_id`, `contract` | no formal `data_role` / `quality_status` columns |

## SB-JM-D-3 Window

| source | window rows | finding |
|---|---:|---|
| canonical `jm.MAIN` | 20 | Formal report 10 research bars. |
| raw `JM2405` | 21 | Old-contract daily prices exist through the holding window. |
| raw `JM2409` | 21 | New-contract daily prices also exist through the holding window. |

## Decision

Do not implement `v0.2.1-daily-rollover-safe` in this round.

Required data task before forced rollover:

1. Normalize actual-contract daily bars into canonical standard parquet.
2. Register actual-contract files with `data_role=primary` and passing quality status.
3. Define runner/enricher logic that closes an old-contract position using old-contract prices only.
4. Add tests proving a `JM2405` position is never closed with `JM2409` prices.

