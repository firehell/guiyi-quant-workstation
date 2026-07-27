# DIRECTION-A3-DATA-CONTRACT-AND-RESIDUAL-ROOT-CAUSE

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | DIRECTION-A3-DATA-CONTRACT-AND-RESIDUAL-ROOT-CAUSE |
| Status | FULL_READONLY_PASS |
| 前置 | A1 Final Sealing PASS、A2–A5 Profile Registry |

## 1. 目标

1. 补齐 canonical bar 数据契约 v1（20 字段 embedded/sidecar 边界）
2. 全区间 1m 聚合 vs 存储日周线只读对账
3. A1 残留异常只读根因分类与独立 Apply Gate 登记

## 2. 硬约束

- 只读：不写 Parquet / DB / manifest
- 不调 RQData
- 105 `quality_warning` 保持 `accepted_warning`，禁止升级 `passed`
- 不做 Profile binding

## 3. 实现文件

| 文件 | 说明 |
|------|------|
| `services/quant-api/app/services/rqdata_ingest/schema_contract.py` | 契约 v1、fingerprint、全量 overlap、容差 |
| `services/quant-api/app/services/rqdata_ingest/daily_weekly_overlap_batch.py` | JM pilot / batch / contract-audit |
| `services/quant-api/app/services/rqdata_ingest/residual_root_cause_audit.py` | 根因分类 |
| `scripts/rqdata_daily_weekly_overlap_reconcile.py` | 对账 CLI |
| `scripts/rqdata_residual_root_cause_audit.py` | 根因审计 CLI |

## 4. 运行命令

```bash
# 契约审计
uv run --project services/quant-api python scripts/rqdata_daily_weekly_overlap_reconcile.py \
  --mode contract-audit \
  --sealing-dir data/reports/data_sealing_audit_20260712_162941 \
  --output-dir data/reports/canonical_bar_contract_audit_20260712

# JM pilot
uv run --project services/quant-api python scripts/rqdata_daily_weekly_overlap_reconcile.py \
  --mode jm-pilot \
  --product jm \
  --contract jm.MAIN \
  --sealing-dir data/reports/data_sealing_audit_20260712_162941 \
  --output-dir data/reports/daily_weekly_overlap_reconcile_20260712_jm_pilot

# 全品种 batch（可先 --limit-products 5 smoke）
uv run --project services/quant-api python scripts/rqdata_daily_weekly_overlap_reconcile.py \
  --mode batch \
  --products-file data/universe/full_products_90.txt \
  --sealing-dir data/reports/data_sealing_audit_20260712_162941 \
  --output-dir data/reports/daily_weekly_overlap_reconcile_20260712_full90 \
  --max-workers 4

# 根因审计
uv run --project services/quant-api python scripts/rqdata_residual_root_cause_audit.py \
  --sealing-dir data/reports/data_sealing_audit_20260712_162941 \
  --multi-primary data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv \
  --output-dir data/reports/residual_root_cause_audit_20260712 \
  --require-direct-db
```

## 5. 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_schema_contract.py \
  services/quant-api/tests/test_daily_weekly_overlap_batch.py \
  services/quant-api/tests/test_residual_root_cause_audit.py
```

## 6. 报告产物

| 目录 | 内容 |
|------|------|
| `data/reports/canonical_bar_contract_audit_20260712/` | schema_contract_matrix |
| `data/reports/daily_weekly_overlap_reconcile_20260712_jm_pilot/` | JM 1d/1w pilot |
| `data/reports/daily_weekly_overlap_reconcile_20260712_full90/` | 批次对账 |
| `data/reports/residual_root_cause_audit_20260712/` | 根因 + Gate 登记 |

## 7. 验收结论

- 契约 v1 + fingerprint：已实现
- JM `1d` pilot：`passed`（851 overlap rows, block=0）
- JM `1w` pilot：`failed`（预期：生产为 RQData 直拉，只读 1m 聚合仅为一致性假说验证）
- 根因 register：覆盖 checksum / orphan / duplicate / missing_physical / row_count / quality_warning
- pytest：18 passed

## 8. 后续 Apply Gate（本轮不执行）

| Gate | 任务 |
|------|------|
| Gate-A3-APPLY-PROCESSED-SYNC | ad/ec/op processed checksum |
| Gate-A3-APPLY-ROWCOUNT | fb/lu/nr/pf row_count |
| Gate-A3-APPLY-DUP-SUPERSEDE | 385 duplicate DB 行 |
| Gate-A3-APPLY-ORPHAN-ARCHIVE | bb/rs/wh orphan |
| Gate-A3-APPLY-JM-EXPERIMENT-CLEANUP | JM experiment 路径 |
