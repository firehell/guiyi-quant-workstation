# DIRECTION-A-FINAL-ACCEPTANCE

生成时间：2026-07-12

状态：`DIRECTION_A_PHASE1_DELIVERY_READY`

## 总判定

```text
DIRECTION-A = A1_PASSED / A2-A7_MINIMAL_IMPLEMENTED
```

方向 A 的第一阶段（A1 Final Sealing + A2–A7 最小实现）已完成。report_id=14 保持冻结，未回写。

## A1 Final Sealing — PASS

证据目录：[`data/reports/data_sealing_audit_20260712_162941/`](../data/reports/data_sealing_audit_20260712_162941/)

| 验收项 | 结果 |
|---|---|
| 物理文件 checksum 证明 | 15056/15056（非 `checksum_unverified`） |
| unclassified disposition | 0 |
| db_snapshot_source | `database` |
| writes_database / writes_parquet | False |
| pytest | 11 passed (`test_target_coverage_audit.py`) |

摘要：[`DIRECTION-A1-SEALING-SUMMARY.md`](../data/reports/data_sealing_audit_20260712_162941/DIRECTION-A1-SEALING-SUMMARY.md)

## A2 Profile Registry — MINIMAL PASS

- Alembic：`20260712_0021_data_profiles`
- 表：`data_profiles`、`profile_active_bindings`
- 配置：[`configs/data_profiles/`](../configs/data_profiles/)
- 服务：[`data_profile_registry.py`](../services/quant-api/app/services/data_profile_registry.py)
- API：`GET /api/v1/data/profiles`、`GET /api/v1/data/profiles/{id}/active-versions`
- JM pilot：`intraday_research_v1` 六周期 active binding 已由 migration seed

## A3 Data Contract — MINIMAL PASS

- Schema contract：[`schema_contract.py`](../services/quant-api/app/services/rqdata_ingest/schema_contract.py)
- 重叠对账 CLI：[`scripts/rqdata_daily_weekly_overlap_reconcile.py`](../scripts/rqdata_daily_weekly_overlap_reconcile.py)
- pytest：`test_schema_contract.py` passed

## A4 Warning Disposition — PASS（继承 A1）

- 105 条 warning → `accepted_warning`（15 文件 / 9 品种）
- 4 条 row_count mismatch → `metadata_mismatch_requires_review`
- 3 orphan + 385 duplicate → 已登记 disposition
- 证据：A1 `disposition_register.csv`

## A5 Unique Active — CORRECTNESS FIXED

- `ProfileActiveBinding` partial unique index：`20260712_0022`（仅 `binding_status=active`）
- `profile_binding_validator.py`：switch 前完整目标校验
- `profile_active_switch.py`：连续切换 / id 链 rollback / 显式 `commit=True`
- `MarketDataReader.load_bars(profile_id=...)` 唯一 active 解析
- 多 primary 清查：[`data/reports/multi_primary_inventory_latest/`](../data/reports/multi_primary_inventory_latest/)
- 全品种 binding rollout：[`data/reports/profile_binding_rollout_20260712/`](../data/reports/profile_binding_rollout_20260712/)（4285 current / full90 apply passed）

## A6 Incremental Gate — P0 FIXED

| 文件 | 改动 |
|---|---|
| `dominant_v2_incremental.py` | `allow_quality_failed` 默认 `False` |
| `rqdata_dominant_v2_incremental_tail.py` | CLI 默认 `False` |
| `rqdata_incremental_tail_universe.sh` | `ALLOW_QUALITY_FAILED` 默认 `0` |

## A7 Web / API — MINIMAL PASS

- Data API coverage 增加 `active_profile_ids`、`binding_status`、`updated_at`
- Web Data 页增加 Profile / Active / 更新时间列
- 浏览器 smoke：未在本轮自动执行（需本地 API 启动后人工验收）

## 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_binding_validator.py \
  services/quant-api/tests/test_profile_active_binding_migration.py \
  services/quant-api/tests/test_schema_contract.py \
  services/quant-api/tests/test_dominant_v2_incremental.py
```

结果：32+ passed（含 profile registry / validator / migration 测试）

## 硬约束确认

- [x] report_id=14 未回写
- [x] 105 warning 未升级为 passed
- [x] A1 只读审计未写 DB/Parquet/manifest
- [x] 未调用 RQData 下载

## 遗留与后续 Gate

1. ~~全品种 Profile binding 扩展（当前 JM pilot）~~ → **已完成**（full90_001: 4031 bindings applied）
2. 周线最后实际交易日确认 Gate（生产脚本）
3. 浏览器 Data 页 smoke（API 启动后）
4. ~~`multi_primary_inventory` 10339 组合需规则化 supersede~~ → **Profile binding 层已完成**；DB primary supersede 留 Phase B
5. 3 条 checksum_mismatch + 4 条 missing_physical_file 需人工复核
6. `live_observation_v1` warning 候选需人工 Gate

## 任务单索引

- [`DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS.md`](DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS.md)
- [`DIRECTION-A1-FINAL-DATA-SEALING-AUDIT.md`](DIRECTION-A1-FINAL-DATA-SEALING-AUDIT.md)
- [`DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md`](DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md)
