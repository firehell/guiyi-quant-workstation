# CONSUMER-CONTRACT-FINAL-CLOSEOUT-006

- Risk level: L3
- Branch: `codex/consumer-contract-final-closeout-006`
- Status: `COMPLETED / CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`

## Scope

Close the four blockers recorded by `CONSUMER-GOLDEN-QUERY-FINAL-GATE-005`:

1. reconcile active Profile bindings that point to non-primary assets;
2. bind JM2609 actual 1m to `intraday_research_v1` and `live_observation_v1`;
3. preserve asset-level warning in Market browser mode;
4. expose immutable `source_interval` provenance and fail closed for strict consumers when it cannot be proved.

The controlled database apply may only update `profile_active_bindings`. It must not write Parquet, manifests, quality reports, historical Backtest/Signal/Review rows, live tables, notifications, or orders.

## Result

- Frozen plan: 397 operations, SHA `ac7512c2c5ea6d4f5473b9e0f2785ac755fe0fc75a9d41bf65eb3070ae1df7cc`.
- Applied: 381 replacements, 14 deactivations, 2 additions.
- Post-apply reconcile operations: 0.
- Duplicate active binding groups: 0.
- report 14 MD5: `ae807ef77f7d9a4ce3067996558b57e8`.
- Protected table/count snapshot: unchanged.
- Independent read-only Golden Query rerun completed with all 49 consumer-matrix rows and 13 hard gates passing; it is the final Ready evidence.

Evidence: `data/reports/consumer_contract_final_closeout_006/` and `data/reports/consumer_golden_query_final_gate_20260718_rerun/`.

The Ready markers apply to formal Market/Backtest/Signal/Review data access only. They do not close the separate Audit V2 full-history residual governance, live runtime, notification autosend or trading Gates.
