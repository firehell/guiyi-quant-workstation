# Stage 8.6 Active Gate Snapshot - 2026-07-11

## 1. Conclusion

This is a read-only Stage 8.6 active asset snapshot for `TASK-2026-07-11-001-data-asset-audit`.

This delivery is accepted only as the first baseline of the broader historical data asset inventory. It does not prove full target coverage for 2020+ daily/weekly assets, 2023+ minute assets, derived multi-period assets, target-vs-actual coverage, duplicate active versions, orphan files, missing manifests, trading calendars, trading sessions, dominant mappings, contract parameters, continuous contracts, or ex-factors.

The intended CLI command was attempted first, but this `data-audit` worktree has no `.env` / `DATABASE_URL`, so direct PostgreSQL authentication failed with `fe_sendauth: no password supplied`. To keep the no-secret boundary, DB metadata was then read through the already-running local readonly API:

```text
http://127.0.0.1:8000/api/v1/data/coverage
http://127.0.0.1:8000/api/v1/data/quality-reports
```

No DB writes, parquet writes, RQData calls, live runtime actions, signal scans, or enterprise WeChat sends were performed.

Final data sealing still requires a same-code-version, same-time-point audit using direct readonly PostgreSQL plus local manifest/parquet evidence. The API fallback is acceptable for this snapshot, but it is not the final data-sealing evidence.

## 2. Active Gate Snapshot

Source layers used:

| Layer | Evidence | Result |
|---|---|---|
| manifest | `data/manifests/rqdata_*_v2_history_*.csv`, `data/manifests/rqdata_actual_contract_bars_*.csv` | readable |
| processed summary | `data/processed/v1b/*/*_v2_parquet_*.json` fallback when manifest is absent | available as fallback |
| DB metadata | local API snapshot of `market_data_files` and `data_quality_reports` | readable through API |
| canonical parquet | DuckDB `read_parquet()` row count and datetime boundary checks | readable for audited assets |

Active data rule remains:

```text
provider/source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

Strict research still prefers `quality_status = passed`.

Snapshot-only limitations:

- This profile is limited to existing Stage 8.6 discovered active records.
- It does not define the final target asset catalog.
- It does not compare expected target assets against actual assets.
- It does not independently prove every checksum.
- It must not be used as evidence that full historical data coverage is complete.

## 3. Full Universe Result

Profile: `stage8_6_1d_first`

| Metric | Count |
|---|---:|
| products | 90 |
| product active_passed | 82 |
| product active_partial | 8 |
| asset active_passed | 1326 |
| asset audit_pending | 8 |
| asset failed | 0 |
| Stage 9 stage9_blocked | 90 |

The original task sheet recorded an earlier asset baseline of `176 active_passed / 8 audit_pending`. The current 2026-07-11 snapshot contains more manifest-level actual-contract records, so the product-level result is unchanged while the asset-level discovered record count is higher. This is not evidence of target coverage improvement by itself.

## 4. Asset Count Semantics

The `1326 active_passed` count means current manifest-level discovered active records that the Stage 8.6 snapshot classified as passed. It must not be read as "1326 target assets are fully covered."

Current matrix rows use this limited unique key:

```text
product + asset_scope + contract + period + standard_path
```

This differs from a future target coverage key, which must include product, contract role, symbol/contract, period, year, expected start/end, and target status.

| Dimension | Group | Count |
|---|---|---:|
| total matrix rows | all records | 1334 |
| gate_status | active_passed | 1326 |
| gate_status | audit_pending | 8 |
| asset_scope | actual_contract | 1244 |
| asset_scope | actual_contract / active_passed | 1241 |
| asset_scope | actual_contract / audit_pending | 3 |
| asset_scope | dominant_main | 90 |
| asset_scope | dominant_main / active_passed | 85 |
| asset_scope | dominant_main / audit_pending | 5 |
| period | 1d | 1334 |
| provider inferred from path | rqdata | 1334 |
| physical check in this snapshot | DuckDB row count and datetime boundary checked | 1334 |
| checksum check in this snapshot | not independently proven for every file | 0 |
| DB registration | registered active_passed records | 1326 |
| DB registration | missing market_data_file pending records | 3 |
| quality warning | registered pending records | 5 |

This snapshot therefore separates three concepts:

| Concept | Meaning in this delivery |
|---|---|
| metadata passed | DB/API metadata, manifest, and quality status are consistent enough for this Stage 8.6 snapshot |
| physical checked | DuckDB could read the parquet and confirm row count / datetime boundary |
| target coverage passed | not evaluated in this task |

## 5. JM V1-B Baseline

Profile: `jm_main_six_period_latest`

| period | rows | max datetime | status |
|---|---:|---|---|
| 1m | 290715 | 2026-07-10 15:00:00 | active_passed |
| 5m | 58143 | 2026-07-10 15:00:00 | active_passed |
| 15m | 19381 | 2026-07-10 15:00:00 | active_passed |
| 30m | 10116 | 2026-07-10 15:00:00 | active_passed |
| 60m | 5909 | 2026-07-10 15:00:00 | active_passed |
| 1d | 851 | 2026-07-10 00:00:00 | active_passed |

JM V1-B remains `6/6 active_passed`. The 8 full-universe pending assets do not block the JM V1-B trusted baseline.

## 6. Pending Assets

| product | asset | contract | period | reason | current evidence | next repair task |
|---|---|---|---|---|---|---|
| bb | dominant_main | bb.MAIN | 1d | `quality_report_abnormal_price` | manifest/DB/quality are all `warning`; DuckDB rows match 851 | read-only abnormal price review, then decide redownload vs keep warning |
| rs | dominant_main | rs.MAIN | 1d | `quality_report_abnormal_price` | manifest/DB/quality are all `warning`; DuckDB rows match 851 | read-only abnormal price review, then decide redownload vs keep warning |
| wh | dominant_main | wh.MAIN | 1d | `quality_report_abnormal_price` | manifest/DB/quality are all `warning`; DuckDB rows match 851 | read-only abnormal price review, then decide redownload vs keep warning |
| wr | dominant_main | wr.MAIN | 1d | `quality_report_abnormal_price` | manifest/DB/quality are all `warning`; DuckDB rows match 851 | read-only abnormal price review, then decide redownload vs keep warning |
| zc | dominant_main | zc.MAIN | 1d | `quality_report_abnormal_price` | manifest/DB/quality are all `warning`; DuckDB rows match 851 | read-only abnormal price review, then decide redownload vs keep warning |
| l | actual_contract | L2609F | 1d | `missing_market_data_file` | manifest/parquet passed; DuckDB rows 76; DB registration missing | controlled DB metadata registration task after manifest/path verification |
| pp | actual_contract | PP2609F | 1d | `missing_market_data_file` | manifest/parquet passed; DuckDB rows 76; DB registration missing | controlled DB metadata registration task after manifest/path verification |
| v | actual_contract | V2609F | 1d | `missing_market_data_file` | manifest/parquet passed; DuckDB rows 76; DB registration missing | controlled DB metadata registration task after manifest/path verification |

The 5 abnormal-price assets must not be upgraded to `passed` in this task. The 3 missing-registration assets must not be registered in this task.

These 8 pending assets are not the only possible historical data gaps. They are only the gaps found by the current `stage8_6_1d_first` snapshot profile.

## 7. Stage 9 Readiness

Stage 9 remains blocked for all 90 products.

This inventory does not authorize:

- enterprise WeChat sending;
- scheduler or retry worker runs;
- signal scan writes;
- treating `jm.MAIN` as a directly tradable actual contract.

Stage 9 still requires the formal signal-event gate with actual contract, bar end, trigger price, and active passed data.

## 8. Output Files

| File | Purpose |
|---|---|
| `data/reports/data_audit_20260711/stage8_6_active_gate_matrix.csv` | full-universe asset matrix |
| `data/reports/data_audit_20260711/stage8_6_product_summary.csv` | product-level status |
| `data/reports/data_audit_20260711/stage8_6_stage9_readiness.csv` | Stage 9 readiness matrix |
| `data/reports/data_audit_20260711/stage8_6_active_gate_summary.md` | full-universe summary |
| `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv` | JM six-period matrix |
| `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_summary.md` | JM six-period summary |

## 9. Next Read-Only Target Coverage Audit

Before repairing the 8 pending records, open a separate Plan-mode task for the target asset catalog and full coverage matrix. That stage must answer:

1. What data assets should exist.
2. What data assets actually exist.
3. What is missing, partial, duplicated, orphaned, or inconsistent.

Expected outputs:

- `target_asset_catalog.csv`
- `asset_physical_inventory.csv`
- `target_coverage_matrix.csv`
- `metadata_consistency_matrix.csv`
- `issue_register.csv`
- `coverage_summary.md`

The target matrix grain is:

```text
product x contract_role x symbol/contract x period x year x status
```

It must cover 90 products, 2020+ main `1d`, 2020+ main `1w`, 2023+ main `1m`, 2023+ derived `5m/15m/30m/60m/1d`, historical actual dominant-contract assets, dominant mappings, trading calendars, trading sessions, contract parameters, manifest/checksum/DB/physical consistency, and a clear `metadata_passed / physical_passed / target_coverage_passed / partial / missing / not_applicable` status split.

## 10. P1 Repair Checklist

After the target coverage audit is planned, handle pending repair as separate controlled tasks:

1. Open a separate Plan-mode task for `bb/rs/wh/wr/zc` abnormal price review.
2. For each warning asset, inspect abnormal price samples from the matching quality report before deciding whether to redownload, keep warning, or add a documented exception.
3. Open a separate controlled registration task for `L2609F/PP2609F/V2609F`.
4. Before registration, verify manifest checksum, canonical parquet path, DuckDB row count, and expected product/contract naming.
5. After any repair, rerun `stage8_6_1d_first` and keep JM six-period verification separate.
