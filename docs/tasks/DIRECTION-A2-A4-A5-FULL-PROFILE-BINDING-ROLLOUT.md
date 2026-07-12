# DIRECTION-A2-A4-A5-FULL-PROFILE-BINDING-ROLLOUT

生成时间：2026-07-12

状态：`IMPLEMENTED`

TASK_ID：`DIRECTION-A2-A4-A5-FULL-PROFILE-BINDING-ROLLOUT`

## 目标

对 10,339 个 multi-primary 组合建立确定性 rulebook，生成三套 Profile 全品种 binding 候选，并完成 JM / pilot5 / full90 分批 dry-run 与 apply。

## 实施内容

### Rulebook

- [`multi_primary_rulebook.py`](../services/quant-api/app/services/multi_primary_rulebook.py)
- lexicographic 排序：disposition → sealing → coverage → data_version → path → duplicate canonical → id
- 分类：`current` / `excluded` / `blocked`

### 候选生成

- [`profile_binding_candidate_generator.py`](../services/quant-api/app/services/profile_binding_candidate_generator.py)
- JOIN A1 sealing CSV + A3 repair_classification + DB primary 行

### Rollout CLI

- [`profile_binding_rollout.py`](../services/quant-api/app/services/profile_binding_rollout.py)
- [`scripts/profile_binding_rollout.py`](../scripts/profile_binding_rollout.py)
- 模式：`generate` / `dry-run` / `apply` / `verify` / `rollback-batch`

### 配置

- [`configs/data_profiles/*.json`](../configs/data_profiles/) 增加 `binding_scope` / `excluded_paths`

### Inventory 修复

- [`scripts/rqdata_multi_primary_inventory.py`](../scripts/rqdata_multi_primary_inventory.py) 过滤空 identity，输出 `invalid_identity_rows.csv`

## Phase 0 Generate 结果

证据目录：[`data/reports/profile_binding_rollout_20260712/`](../data/reports/profile_binding_rollout_20260712/)

| 指标 | 值 |
|------|---:|
| binding_candidate_rows | 5756 |
| current_rows | 4285 |
| blocked_rows | 9792 |
| intraday_research_v1 current | 535 |
| long_horizon_daily_v1 current | 3743 |
| live_observation_v1 current | 7 |

## 分批 Apply 结果

| Batch | Scope | Applied | Skipped | Verify |
|-------|-------|--------:|--------:|--------|
| jm_pilot_001 | jm × 3 profiles | 38 | 6 | passed |
| pilot5_001 | a,ad,ag,al,ao | 210 | 0 | passed |
| full90_001 | 90 品种全 profile | 4031 | 254 | passed |

- rollback-batch：JM 38 条首次绑定无 previous binding，rollback 正确 skip
- apply 使用单事务 commit（批末一次提交）

## 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_primary_rulebook.py \
  services/quant-api/tests/test_profile_binding_candidate_generator.py \
  services/quant-api/tests/test_profile_binding_rollout.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_binding_validator.py \
  services/quant-api/tests/test_profile_active_binding_migration.py
```

结果：27 passed

## 硬约束确认

- [x] 未删除 DB 行（仅 insert active + supersede 历史链）
- [x] 未覆盖 Parquet
- [x] 未升级 warning 为 passed
- [x] 未改 report_id=14
- [x] 未接 Backtest/Signal 消费者
- [x] Phase B（market_data_files.data_role supersede）未执行，留待 A3 dup-supersede Gate

## 遗留

1. `live_observation_v1` 部分周期选中 warning/active_entry 候选（如 1m file_id 33205），需人工确认是否符合观测 profile 预期
2. multi-primary inventory 空 identity 脏行需 DB 侧根因排查
3. long_horizon 1w overlap 契约风险仍 open（A3 已知）

## 运行命令

```bash
# 只读生成
uv run --project services/quant-api python scripts/profile_binding_rollout.py \
  --mode generate --profiles all \
  --products-file data/universe/full_products_90.txt \
  --sealing-dir data/reports/data_sealing_audit_20260712_162941 \
  --multi-primary-csv data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv \
  --output-dir data/reports/profile_binding_rollout_20260712

# dry-run / apply / verify
uv run --project services/quant-api python scripts/profile_binding_rollout.py \
  --mode dry-run --profiles all --products jm \
  --output-dir data/reports/profile_binding_rollout_20260712
```
