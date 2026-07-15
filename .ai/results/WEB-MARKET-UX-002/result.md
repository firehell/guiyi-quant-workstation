# WEB-MARKET-UX-002 Result

status: READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND
updated_at: 2026-07-14

## Summary

Ran read-only `JM 1d` duplicate K diagnosis after `WEB-MARKET-UX-001 GATE_PASSED`.

No duplicate K was reproduced in the current worktree Web chart path. A read-only API check did find `JM2609 1d quote_mode=true` data quality warning: `cross_file_conflicts=10`.

## Scope

Read-only only:

- No code changes for A02.
- No DB writes.
- No Parquet writes.
- No RQData download.
- No quality status or manifest mutation.

## Evidence

API base: `http://127.0.0.1:8010`

Web base: `http://127.0.0.1:5174`

API counts:

| case | response_count | unique_time | unique_trading_day | unique_chart_key | dedupe_count | merge_self_count | quality |
|---|---:|---:|---:|---:|---:|---:|---|
| `jm.MAIN 1d` | 3231 | 3231 | 3231 | 3231 | 3231 | 3231 | `unchecked`, `cross_file_conflicts=0` |
| `JM2609 1d quote_mode` | 76 | 76 | 76 | 76 | 76 | 76 | `warning`, `cross_file_conflicts=10` |

Chart evidence:

- URL: `http://127.0.0.1:5174/market/chart?symbol=jm&contract=JM2609&period=1d`
- Sidebar: `K线数量 3,231`, `1d / passed`
- Network: `bars jm.MAIN 1d`, EMA21 indicators, and MACD returned 200.
- Console: 0 errors, 0 warnings.
- Screenshot: `output/playwright/web-market-ux/WEB-MARKET-UX-002/current-1d-chart.png`

## Earliest Duplicate Layer

Not identified for the Web chart duplicate. Duplicate was not reproduced in:

- API response
- Web normalize
- Web merge
- Chart observation

## A03 Recommendation

Do not enter frontend A03 yet.

If later work targets the `JM2609 1d quote_mode=true` `cross_file_conflicts=10`, mark A03 as `REPLAN` for data-fact conflict review/repair before any fix. Do not hide it with Web-side silent dedupe.
