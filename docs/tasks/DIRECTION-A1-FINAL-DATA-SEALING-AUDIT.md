# DIRECTION-A1-FINAL-DATA-SEALING-AUDIT

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | DIRECTION-A1-FINAL-DATA-SEALING-AUDIT |
| Branch | feature/direction-a1-final-sealing-audit |
| Status | DELIVERY_READY |
| Baseline | main @ POST-DATA-CLOSURE clean checkpoint |

## 1. 任务类型

方向 A / 数据最终封存 / 只读审计（A1）

## 2. 目标

在 `target_coverage_audit` 基础上扩展 Final Sealing 能力：

- 逐文件 sha256 重算与 manifest/DB/processed 四方比对
- Schema fingerprint（列集 hash）
- 空文件、重复 datetime、重复路径/版本检测
- Orphan parquet 反向扫描
- 已知异常 disposition 登记
- 产出 `DIRECTION-A1-SEALING-SUMMARY.md` 与 sealing 专用矩阵

## 3. 硬约束

- 不写 PostgreSQL / Parquet / manifest
- 不调用 RQData
- 105 条 quality_warning 不升级为 passed
- report_id=14 不回写
- sealing 模式要求 `db_snapshot_source=database`

## 4. 允许修改

- `services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py`
- `scripts/rqdata_target_coverage_audit.py`
- `services/quant-api/tests/test_target_coverage_audit.py`
- `data/reports/data_sealing_audit_*/`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- 本任务单

## 5. 验收标准

1. 物理文件均有独立 checksum 证明（非 `checksum_unverified`）
2. orphan / duplicate / empty 全部进入 disposition_register，零 `unclassified`
3. 8 条已知异常有明确 disposition
4. `db_snapshot_source=database`
5. pytest 全绿
6. 产出 sealing summary 报告

## 6. 运行命令

```bash
uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py \
  --products-file data/universe/full_products_90.txt \
  --output-dir data/reports/data_sealing_audit_20260712_162941 \
  --sealing-mode \
  --require-direct-db
```

## 7. 运行结果

- 输出目录：`data/reports/data_sealing_audit_20260712_162941/`
- physical_inventory_rows：15056
- checksum_matched：15049
- unclassified_dispositions：0
- pytest：11 passed
