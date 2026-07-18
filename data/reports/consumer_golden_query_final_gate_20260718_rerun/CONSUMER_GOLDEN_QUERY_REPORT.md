# CONSUMER-GOLDEN-QUERY-FINAL-GATE-005 — independent rerun

## Conclusion

```text
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
```

The final Gate was rerun from merged `origin/main@f7f8ad2b` against direct PostgreSQL in a forced `READ ONLY` transaction and the canonical Parquet data root. All 49 consumer matrix rows and all 13 Hard Gates passed.

## Fixed Golden Queries

The rerun covered JM continuous 1m/15m/1d/1w, JM2609 actual dominant 1m, old-product full-history 1m/1d/1w, first-week semantics, a real Browser warning, a strict blocked identity, a different-value cross-file conflict, and an intentionally missing Profile binding.

For every applicable strict query, Market research bars, EMA, Backtest resolver/input and Review exact-bars used the same `market_data_file_id`, data version, immutable binding snapshot and explicit `source_interval`. JM2609 actual 1m additionally passed Signal mapping, confirmed-bar and trigger-price lineage. Continuous `.MAIN` samples remained blocked as Signal actual-contract evidence.

## Hard Gate

| Gate | Result |
|---|---|
| strict consumer escape paths | PASS / 0 |
| arbitrary path formal Backtest | PASS / 0 |
| warning enters Backtest or Signal | PASS / 0 |
| `.MAIN` used as actual | PASS / 0 |
| bars/indicator binding mismatch | PASS / 0 |
| daily/weekly duplicate | PASS / 0 |
| different-value conflict silently swallowed | PASS / 0 |
| duplicate active binding groups | PASS / 0 |
| report 14 unchanged | PASS |
| DB snapshot source | PASS / direct database |
| Stage B data root and commit | PASS |
| required Golden samples | PASS / 12 of 12 |
| source interval comparable | PASS / explicit |

## Historical protection

- report 14 MD5: `ae807ef77f7d9a4ce3067996558b57e8`
- report 14 trades/orders: `155 / 239`
- RQData calls: `0`
- DB/Parquet/manifest/Profile-binding writes during rerun: `0 / 0 / 0 / 0`
- live runtime, notification and orders: not invoked

The earlier `data/reports/consumer_golden_query_final_gate_20260718/` report remains an immutable failed historical snapshot. This rerun is the acceptance evidence that closes its four blockers.
