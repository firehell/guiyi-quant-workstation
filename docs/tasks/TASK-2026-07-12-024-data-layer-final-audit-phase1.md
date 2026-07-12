# TASK-2026-07-12-024：数据层最终封板 Phase 1 全量只读审计

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-024-data-layer-final-audit-phase1 |
| Branch | main |
| Status | DELIVERY_READY_PHASE1_READONLY_AUDIT |
| Phase | Phase 1 readonly audit only |

## 1. 目标

在不写 DB / Parquet / manifest、不调用 RQData 下载的前提下，产出 `data/reports/data_layer_final_audit_20260712/` 全套只读审计产物，逐条验证用户声明的候选事实与旧 Stage 8.6 数字是否仍成立。

## 2. 允许修改范围

- `scripts/rqdata_data_layer_final_audit.py`
- `services/quant-api/app/services/rqdata_ingest/data_layer_final_audit.py`
- `services/quant-api/tests/test_data_layer_final_audit.py`
- `data/reports/data_layer_final_audit_20260712/**`
- `docs/tasks/TASK-2026-07-12-024-data-layer-final-audit-phase1.md`
- `tasks/current.md`

## 3. 禁止修改范围

- 不写 PostgreSQL / 不改 Alembic
- 不写 raw / processed / canonical parquet / manifests
- 不调用 RQData 下载
- 不把 105 条 quality_warning 升级为 passed
- 不修改策略、回测、信号、live runtime

## 4. 运行命令

```bash
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --output-dir data/reports/data_layer_final_audit_20260712

uv run --project services/quant-api pytest \
  services/quant-api/tests/test_data_layer_final_audit.py \
  services/quant-api/tests/test_target_coverage_audit.py -q
```

## 5. 预期产物

```text
data/reports/data_layer_final_audit_20260712/
├── target_asset_catalog.csv
├── asset_physical_inventory.csv
├── target_coverage_matrix.csv
├── metadata_consistency_matrix.csv
├── quality_issue_register.csv
├── duplicate_active_assets.csv
├── orphan_files.csv
├── main_contract_mapping_audit.csv
├── reference_data_audit.csv
├── weekly_history_audit.csv
├── daily_intraday_crosscheck.csv
├── DATA_LAYER_FINAL_AUDIT.md
├── audit_evidence.json
├── stage8_6_1d/
└── jm_six_period/
```

## 6. Phase 1 结果（2026-07-12）

```text
covered_passed=17203
covered_warning=105
not_applicable=1943
issue_register_rows=105
duplicate_active_rows=3816
orphan_file_rows=8
weekly_pre2020_missing=63
weekly_direct_present=90/90
legacy_82_90_still_valid=True
legacy_1326_still_valid=True
legacy_8_pending_still_valid=True
```

pytest：`test_data_layer_final_audit.py` + `test_target_coverage_audit.py` = 12 passed

## 7. Phase 1 边界

- 只登记问题，不修复
- 不宣布数据层最终封板完成
- crosscheck 差异不静默选择 primary 来源
