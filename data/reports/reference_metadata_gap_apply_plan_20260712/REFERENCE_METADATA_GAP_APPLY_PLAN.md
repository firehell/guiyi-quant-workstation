# Reference Metadata Gap Apply Plan

## Result

- candidate_rows: 831
- batch_count: 11
- needs_continuous_contract_sync: 546
- needs_contract_universe_sync: 285

## Safety Boundary

- writes_database=False
- writes_parquet=False
- writes_manifest=False
- calls_rqdata=False
- This is an apply plan only. It does not run generated commands.
- Human approval is required before any RQData call or PostgreSQL metadata write.

## Allowed Future Apply Scope

- May write only `futures_contract_universe` and `futures_continuous_contract_map` plus related task/manifest metadata after approval.
- Must not write K-line Parquet, `market_data_files`, `data_quality_reports`, quality status, strategy, signal, live runtime, or trading logic.

## Batch Strategy

- Run `contract_universe` years first, oldest to newest.
- Then run `continuous_contract_map` years, oldest to newest.
- Execute one product-year command at a time, with per-command logging and rerunnable manifests.
- After each dataset or year batch, rerun reference metadata gap reconcile and target coverage audit.
