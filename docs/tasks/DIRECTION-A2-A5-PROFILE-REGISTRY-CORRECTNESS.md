# DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS

生成时间：2026-07-12

状态：`IMPLEMENTED`

TASK_ID：`DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS`

分支：`feature/direction-a1-final-sealing-audit`

## 目标

修正 Data Profile active binding 的数据库约束、目标校验、连续切换和回滚机制，使同一 identity 可保留多条 superseded 历史，且每个 Profile × symbol × contract × period 最多只有一条 active binding。

## 根因

`uq_profile_active_binding_identity_status` 将 `binding_status` 纳入唯一键，导致同一 identity 最多 1 active + 1 superseded；第三次 switch 在 supersede 当前 active 时触发唯一键冲突。

## 实施内容

### Migration `20260712_0022`

- 删除 `uq_profile_active_binding_identity_status`
- 新增 partial unique index `uq_profile_active_binding_active_identity`（仅 `binding_status='active'`）
- JM 六周期现有 active binding 无需数据迁移

### Validator

- 新增 `app/services/profile_binding_validator.py`
- 校验 profile / period / contract_role / market_data_file identity / provider / data_role=primary / quality_policy / 物理文件存在性

### Switch / Rollback

- switch 前强制 validator；`dry_run` 也返回 `validation` 字段
- rollback 前驱解析改为 `id < current.id` 的 LIFO 链
- rollback 写库顺序：先 supersede current，再 activate previous
- 移除 service 内默认 commit；调用方显式 `commit=True`

## 变更文件

- `services/quant-api/alembic/versions/20260712_0022_profile_active_binding_partial_unique.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/services/profile_binding_validator.py`
- `services/quant-api/app/services/profile_active_switch.py`
- `services/quant-api/tests/test_data_profile_registry.py`
- `services/quant-api/tests/test_profile_binding_validator.py`
- `services/quant-api/tests/test_profile_active_binding_migration.py`

## 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_profile_binding_validator.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_active_binding_migration.py

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_schema_contract.py \
  services/quant-api/tests/test_dominant_v2_incremental.py \
  services/quant-api/tests/test_market_data_reader.py
```

结果：17 + 32 passed

## Migration Gate（本地 PostgreSQL）

```bash
cd services/quant-api && uv run alembic upgrade head
```

说明：若环境已有 superseded 历史，**不要 downgrade 0022**（旧唯一约束无法重建）。

## 验收标准

- [x] 同一 identity 可保留多条 superseded，且最多 1 条 active
- [x] 连续 3 次 switch 不触发唯一键冲突
- [x] rollback 恢复紧邻前驱；rollback 后再 switch 正常
- [x] 无 previous binding 时 rollback 为 no-op
- [x] switch 前 validator 拦截不匹配目标
- [x] service 不在校验失败或半完成状态提交
- [x] SQLite / PostgreSQL 测试策略已覆盖

## 未处理范围

- 10,339 multi-primary 组合
- 全品种 binding 扩展
- Parquet / manifest / report_id=14
- 前端 / Backtest / Signal / Review 接入
