# TASK-2026-07-12-025：数据层 Phase 2 受控补齐

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-025-data-layer-phase2-remediation |
| Branch | `feature/data-layer-phase2` |
| Status | DELIVERY_READY_PARTIAL |
| Phase | Phase 2 controlled remediation |
| Depends on | TASK-2026-07-12-024 (Phase 1 readonly audit) |

## 1. 目标

在 Phase 1 审计证据基础上，受控修复阻塞 READY 的数据层问题：

1. duplicate active primary supersede（3816 → 0）
2. 孤儿 Parquet 登记（8 文件）
3. pre-2020 周线补齐（63 品种，`listed_date` → 现有 1w 前缀）
4. 主连 / actual 缺口收口

## 2. 允许修改范围

- `scripts/rqdata_duplicate_active_supersede.py`
- `scripts/rqdata_orphan_file_register.py`
- `scripts/rqdata_weekly_pre2020_backfill.py`
- `services/quant-api/app/services/rqdata_ingest/duplicate_active_supersede.py`
- `services/quant-api/app/services/rqdata_ingest/orphan_file_register.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_pre2020_backfill.py`
- `services/quant-api/tests/test_duplicate_active_supersede.py`
- `services/quant-api/tests/test_orphan_file_register.py`
- `services/quant-api/tests/test_weekly_pre2020_backfill.py`
- `data/reports/data_layer_phase2_*/**`
- `docs/tasks/TASK-2026-07-12-025-data-layer-phase2-remediation.md`
- `tasks/current.md`

## 3. 禁止修改范围

- 不把 105 条 `quality_warning` 升级为 `passed`
- 不删除 canonical Parquet
- 不改 Alembic / 策略 / 回测 / live runtime
- 不自动创建空数据根目录
- live DB 不自动进入 historical active

## 4. Gate 条件

| Step | Gate |
|------|------|
| 2A supersede apply | `duplicate_active_rows=0` |
| 2B orphan register | `orphan_file_rows=0` |
| 2C weekly pre-2020 | `weekly_pre2020_missing=0` |
| 2D main/actual | claim_6 dominant 90/90; actual 1244/1244 |

## 5. 运行命令

```bash
# 2A duplicate active supersede
uv run --project services/quant-api python scripts/rqdata_duplicate_active_supersede.py \
  --output-dir data/reports/data_layer_phase2_supersede_20260712
uv run --project services/quant-api python scripts/rqdata_duplicate_active_supersede.py \
  --apply --confirm-duplicate-active-supersede \
  --output-dir data/reports/data_layer_phase2_supersede_20260712

# 2B orphan register
uv run --project services/quant-api python scripts/rqdata_orphan_file_register.py \
  --orphan-csv data/reports/data_layer_final_audit_20260712/orphan_files.csv \
  --dry-run
uv run --project services/quant-api python scripts/rqdata_orphan_file_register.py \
  --orphan-csv data/reports/data_layer_final_audit_20260712/orphan_files.csv \
  --apply --confirm-orphan-register

# 2C weekly pre-2020 (batch)
uv run --project services/quant-api python scripts/rqdata_weekly_pre2020_backfill.py \
  --dry-run --output-dir data/reports/data_layer_phase2_weekly_pre2020_20260712
uv run --project services/quant-api python scripts/rqdata_weekly_pre2020_backfill.py \
  --run-write --register --batch-size 15 \
  --output-dir data/reports/data_layer_phase2_weekly_pre2020_20260712

# Re-audit
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --output-dir data/reports/data_layer_final_audit_phase3_20260712
```

## 6. required_tests

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_duplicate_active_supersede.py \
  services/quant-api/tests/test_orphan_file_register.py \
  services/quant-api/tests/test_weekly_pre2020_backfill.py \
  services/quant-api/tests/test_data_layer_final_audit.py
```
