# TASK-2026-07-12-007：Residual Data Risk Closeout Dry-run

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-007-residual-data-risk-closeout-dry-run |
| Work Level | L1 |
| GitHub Issue | 不创建 |
| Branch | codex/residual-data-risk-closeout |
| Worktree | /Volumes/扩展盘/guiyi-parallel/residual-data-risk-closeout |
| Base Commit | b42e41e4 |
| Status | DELIVERY_READY_DRY_RUN_NO_WRITE |
| Created At | 2026-07-12 |

## 1. 目标

在 `TASK-006` 证实 `missing_db_registration=0` 后，对剩余数据风险做只读收口：

1. 查明 105 条 `quality_failed` 的真实根因。
2. 对 `L2609F` 六周期同路径多版本做只读治理候选报告。
3. 对 831 条 reference metadata gaps 生成 product/year/dataset 级 dry-run ledger 和后续受控 sync 命令清单。
4. 修正 target coverage audit 的质量状态合并口径，避免 stale processed summary 把当前 warning 资产误报为 active failed。

## 2. 硬边界

- 不写 PostgreSQL。
- 不写 raw / processed / canonical Parquet。
- 不修改 manifest、checksum、`data_version`、`data_role`、`quality_status`。
- 不调用 RQData，不新增 Alembic migration 或 schema。
- 不删除、合并、归档或修改 `L2609F` 历史重复版本。
- 不修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行。

## 3. 实现结果

- 新增 `quality_failed_root_cause_audit` dry-run：
  - 输入 105 target rows，去重为 15 个唯一文件。
  - 15 个文件全部分类为 `stale_processed_summary_failed`。
  - 当前 DB、manifest、quality report 均为 `warning`，不是 active `failed`。
  - 根因是 `processed/v1b/*_v2_parquet_*.json` 保留旧 `quality_status=failed`。

- 新增 `duplicate_path_version_reconcile` dry-run：
  - 输入 6 条 `duplicate_path_versions`。
  - 6 条均分类为 `duplicate_path_versions`。
  - manifest/current version 为 `rq_acb_*`，旧 `rqdata_actual_contract_bars_*` 只作为 superseded candidate 报告。
  - 未做归档、删除或 DB 更新。

- 新增 `reference_metadata_gap_reconcile` dry-run：
  - 输入 831 rows。
  - `needs_contract_universe_sync=285`。
  - `needs_continuous_contract_sync=546`。
  - `partial_year_rows=0`，`not_applicable_review=0`。
  - 输出后续受控 sync 命令清单，但该清单不是授权。

- 修正 `target_coverage_audit`：
  - 合并质量状态时 DB/manifest 当前 active evidence 优先。
  - `processed_summary` 只在没有 active evidence 时参与质量状态兜底。
  - stale processed summary 不再把 warning 资产误报为 `quality_failed`。

## 4. 报告输出

- `data/reports/quality_failed_root_cause_audit_20260712/`
  - `QUALITY_FAILED_ROOT_CAUSE_AUDIT.md`
  - `quality_failed_root_cause_ledger.csv`
- `data/reports/duplicate_path_version_reconcile_20260712/`
  - `DUPLICATE_PATH_VERSION_RECONCILE.md`
  - `duplicate_path_version_ledger.csv`
- `data/reports/reference_metadata_gap_reconcile_20260712/`
  - `REFERENCE_METADATA_GAP_RECONCILE.md`
  - `reference_metadata_gap_ledger.csv`
  - `reference_metadata_sync_commands.csv`
- `data/reports/target_coverage_audit_20260712_after_residual_closeout/`
  - `coverage_summary.md`
  - `target_coverage_matrix.csv`
  - `issue_register.csv`
  - `metadata_consistency_matrix.csv`
  - `asset_physical_inventory.csv`
  - `target_asset_catalog.csv`

## 5. Target Coverage 复跑结果

- `target_catalog_rows=17581`。
- `physical_inventory_rows=15056`。
- `covered_passed=17203`。
- `covered_warning=105`。
- `not_applicable=273`。
- `metadata_gap=831`。
- `issue_register_rows=936`。
- Issue 类型：
  - `missing_continuous_contract_map=546`。
  - `missing_contract_universe=285`。
  - `quality_warning=105`。
- `quality_failed=0`。
- `missing_db_registration=0`。

## 6. 测试结果

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_quality_failed_root_cause_audit.py \
  services/quant-api/tests/test_duplicate_path_version_reconcile.py \
  services/quant-api/tests/test_reference_metadata_gap_reconcile.py
```

- 结果：10 passed。

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app/services/rqdata_ingest/ \
  scripts/rqdata_quality_failed_root_cause_audit.py \
  scripts/rqdata_duplicate_path_version_reconcile.py \
  scripts/rqdata_reference_metadata_gap_reconcile.py
```

- 结果：All checks passed。

```bash
python -m py_compile \
  services/quant-api/app/services/rqdata_ingest/quality_failed_root_cause_audit.py \
  services/quant-api/app/services/rqdata_ingest/duplicate_path_version_reconcile.py \
  services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_reconcile.py \
  scripts/rqdata_quality_failed_root_cause_audit.py \
  scripts/rqdata_duplicate_path_version_reconcile.py \
  scripts/rqdata_reference_metadata_gap_reconcile.py
```

- 结果：通过。

```bash
uv run --env-file /Volumes/扩展盘/guiyi-quant-workstation/.env \
  --project services/quant-api python scripts/rqdata_target_coverage_audit.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-dir data/reports/target_coverage_audit_20260712_after_residual_closeout
```

- 结果：通过，`db_snapshot_source=database`。

## 7. 人工 Gate

- 本任务不授权 DB 写入。
- 本任务不授权 RQData 调用。
- 本任务不授权修改 `quality_status`。
- 本任务不授权删除、归档或合并旧 `L2609F` data_version。
- 后续若要处理 reference metadata gaps，必须另开 metadata-only sync/apply 任务，只允许写 `futures_contract_universe`、`futures_continuous_contract_map` 及相关任务/manifest 元数据。
