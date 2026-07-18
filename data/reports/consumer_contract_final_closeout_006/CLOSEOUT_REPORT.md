# CONSUMER-CONTRACT-FINAL-CLOSEOUT-006

## Result

```text
IMPLEMENTED_AND_CANONICAL_BINDING_VERIFIED
FINAL_GOLDEN_RERUN_PENDING
```

The direct PostgreSQL plan was generated in a read-only transaction, frozen by SHA, and then applied under a PostgreSQL advisory transaction lock.

| Check | Result |
|---|---:|
| Frozen operation count | 397 |
| Replace | 381 |
| Deactivate | 14 |
| Add | 2 |
| Remaining operations | 0 |
| Duplicate active groups | 0 |
| Protected snapshot diffs | 0 |
| report 14 MD5 | `ae807ef77f7d9a4ce3067996558b57e8` |

The apply changed only `profile_active_bindings`. It did not write market files, quality reports, Parquet, manifests, Backtest/Signal/Review history, live tables, notifications, or orders.

The Ready markers are intentionally not updated here. They require an independent read-only rerun of `CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` from the merged implementation.
