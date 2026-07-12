# 当前任务：DIRECTION-A6-PROFILE-AWARE-INCREMENTAL-CLOSURE

生成时间：2026-07-12

状态：`IMPLEMENTED`

## 本轮完成（方向 A）

| Step | 任务 | 状态 |
|---|---|---|
| A2-A5 | Profile registry correctness | `CORRECTNESS_FIXED` |
| PBR | 全品种 Profile binding rollout | `IMPLEMENTED` |
| A6 | Profile-aware 增量闭包 | `IMPLEMENTED` |

## A6 关键结果

- 新增 profile-aware 增量闭包编排层：候选 Parquet / DB metadata / profile validation / active switch 在同一 session 事务中完成。
- 增量闭包默认禁止 `allow_quality_failed`，不把 `failed` 降级为 `warning`。
- active switch 增加幂等 no-op：目标 `market_data_file_id` / `data_version` 已 active 时不再新增第二条 active。
- 周线 `1w` 增加最后实际交易日 Gate，支持节假日缩短周。
- 失败时 DB 回滚、旧 active 保留，并输出 failure ledger / orphan report 供安全重试或人工归档。
- 新增 batch rollback，可按 success ledger 反向恢复上一条 active。

## PBR 关键证据

```text
generate=data/reports/profile_binding_rollout_20260712/
current_rows=4285 (intraday=535, long_horizon=3743, live=7)
jm_pilot_001: applied=38, verify=passed
pilot5_001: applied=210, verify=passed
full90_001: applied=4031, verify=passed
```

## 运行命令

```bash
# A2-A5 只读生成
uv run --project services/quant-api python scripts/profile_binding_rollout.py \
  --mode generate --profiles all \
  --products-file data/universe/full_products_90.txt \
  --sealing-dir data/reports/data_sealing_audit_20260712_162941 \
  --multi-primary-csv data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv \
  --output-dir data/reports/profile_binding_rollout_20260712

# dry-run
uv run --project services/quant-api python scripts/profile_binding_rollout.py \
  --mode dry-run --profiles all --products jm \
  --output-dir data/reports/profile_binding_rollout_20260712

# A6 dry-run：不调用 RQData，不写 DB，不写 Parquet
uv run --project services/quant-api python scripts/rqdata_dominant_v2_incremental_tail.py closure \
  --mode dry-run \
  --end-date 2026-07-11 \
  --product jm \
  --period 1m --period 1d --period 1w \
  --profiles all \
  --batch-id jm_a6_dry_run_001

# A6 JM pilot/apply：需要人工确认后才允许加 --commit
uv run --project services/quant-api python scripts/rqdata_dominant_v2_incremental_tail.py closure \
  --mode pilot \
  --end-date 2026-07-11 \
  --product jm \
  --period 1m --period 1d --period 1w \
  --profiles all \
  --batch-id jm_a6_pilot_001 \
  --commit

# A6 rollback 演练
uv run --project services/quant-api python scripts/rqdata_dominant_v2_incremental_tail.py closure \
  --mode rollback \
  --batch-id jm_a6_pilot_001 \
  --commit

# A6 orphan recovery 检查
uv run --project services/quant-api python scripts/rqdata_dominant_v2_incremental_tail.py closure \
  --mode orphan-report \
  --batch-id jm_a6_pilot_001
```

## 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_primary_rulebook.py \
  services/quant-api/tests/test_profile_binding_candidate_generator.py \
  services/quant-api/tests/test_profile_binding_rollout.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_binding_validator.py \
  services/quant-api/tests/test_profile_active_binding_migration.py

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_profile_aware_incremental.py \
  services/quant-api/tests/test_dominant_v2_incremental.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_binding_validator.py
```

结果：

- A2-A5 记录：27 passed
- A6 本轮：23 passed

## 硬约束

- report_id=14 冻结，未回写
- 105 quality_warning 未升级为 passed
- 未删 DB 行 / 未覆盖 Parquet
- Phase B（market_data_files primary supersede）未执行
- 本轮未运行真实 RQData 增量下载
- 本轮未开启 scheduler / live event / 企业微信
- 本轮未自动 push / merge

## A6 人工 Gate

1. JM pilot 前人工确认目标 `END_DATE` 是否为已收盘交易日；`1w` 必须是当周最后实际交易日。
2. 小批品种 pilot 前先跑 `closure --mode dry-run`，确认 `failure_count=0`。
3. 90 品种扩展前先检查 failure ledger、orphan report、duplicate active verify。
4. 任意失败不得半切 active；先检查 `data/reports/profile_incremental_closure_latest/*_failure.json`。
5. 回滚必须使用明确 `batch-id`，先 dry-run，再人工确认 `--commit`。

## 下一步建议

1. 人工 Gate 后执行 JM `closure --mode dry-run`。
2. JM pilot 通过后执行小批品种 dry-run/pilot。
3. 小批通过后再进入 90 品种扩展 Gate。
4. Backtest/Signal 接入 `profile_id` 强制读取路径。

## 任务单

- `docs/tasks/DIRECTION-A2-A4-A5-FULL-PROFILE-BINDING-ROLLOUT.md`
- `docs/tasks/DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS.md`
- `docs/tasks/DIRECTION-A-FINAL-ACCEPTANCE.md`
