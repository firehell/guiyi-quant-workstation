# 当前任务：DIRECTION-A-DATA-FINAL-SEALING

生成时间：2026-07-12

状态：`DIRECTION_A_PHASE1_DELIVERY_READY`

## 本轮完成（方向 A）

| Step | 任务 | 状态 |
|---|---|---|
| 0 | Git checkpoint | `CLEAN_BASELINE` |
| A1 | Final Sealing 只读审计 | `PASSED` |
| A2 | 三套 Profile registry 最小实现 | `MINIMAL_PASS` |
| A3 | Schema contract + 日周重叠对账 CLI | `MINIMAL_PASS` |
| A4 | Warning / 旧资产 disposition | `PASS`（继承 A1） |
| A5 | 唯一 active 机制 | `MINIMAL_PASS` |
| A6 | 增量 Gate 默认收紧 | `P0_FIXED` |
| A7 | Web/API + 最终验收文档 | `MINIMAL_PASS` |

## A1 关键证据

```text
report_dir=data/reports/data_sealing_audit_20260712_162941
physical_inventory_rows=15056
checksum_matched=15049
unclassified_dispositions=0
db_snapshot_source=database
```

运行命令：

```bash
uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py \
  --products-file data/universe/full_products_90.txt \
  --sealing-mode \
  --require-direct-db
```

## Profile Registry

- migration：`20260712_0021_data_profiles`
- profiles：`intraday_research_v1` / `long_horizon_daily_v1` / `live_observation_v1`
- API：`/api/v1/data/profiles`、`/api/v1/data/profiles/{id}/active-versions`

## 硬约束

- report_id=14 冻结，未回写
- 105 quality_warning 未升级为 passed
- A1 只读：未写 Parquet/manifest/DB 行情资产

## 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_schema_contract.py \
  services/quant-api/tests/test_dominant_v2_incremental.py
```

## 下一步建议

1. 本地启动 API 后做 Data 页浏览器 smoke（Profile/Active/更新时间列）
2. 人工复核 3 checksum_mismatch + 4 missing_physical_file
3. 全品种 Profile binding 扩展（JM pilot 之后）
4. POST-DATA-CLOSURE：T3-real / OOS 全窗口（与方向 A 可并行）

## 任务单

- `docs/tasks/DIRECTION-A1-FINAL-DATA-SEALING-AUDIT.md`
- `docs/tasks/DIRECTION-A-FINAL-ACCEPTANCE.md`
- `data/reports/data_sealing_audit_20260712_162941/DIRECTION-A1-SEALING-SUMMARY.md`
