# 当前任务：DIRECTION-A2-A4-A5-FULL-PROFILE-BINDING-ROLLOUT

生成时间：2026-07-12

状态：`IMPLEMENTED`

## 本轮完成（方向 A）

| Step | 任务 | 状态 |
|---|---|---|
| A2-A5 | Profile registry correctness | `CORRECTNESS_FIXED` |
| PBR | 全品种 Profile binding rollout | `IMPLEMENTED` |

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
# 只读生成
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
```

结果：27 passed

## 硬约束

- report_id=14 冻结，未回写
- 105 quality_warning 未升级为 passed
- 未删 DB 行 / 未覆盖 Parquet
- Phase B（market_data_files primary supersede）未执行

## 下一步建议

1. 人工 Gate 确认 `live_observation_v1` warning 候选 file_id
2. `DIRECTION-A3-APPLY-DUP-SUPERSEDE` Phase B primary supersede
3. Backtest/Signal 接入 `profile_id` 强制读取路径
4. 全品种 batch overlap overnight

## 任务单

- `docs/tasks/DIRECTION-A2-A4-A5-FULL-PROFILE-BINDING-ROLLOUT.md`
- `docs/tasks/DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS.md`
- `docs/tasks/DIRECTION-A-FINAL-ACCEPTANCE.md`
