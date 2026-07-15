# DIRECTION-A-FINAL-ACCEPTANCE

生成时间：2026-07-12

最新验收时间：2026-07-12 21:32 CST

状态：`DIRECTION_A_FINAL_BLOCKED`

## 总判定

```text
DIRECTION-A_FINAL_BLOCKED
```

本轮按 `DIRECTION-A-FINAL-CLOSURE-ACCEPTANCE` 重新执行新鲜验收。A1、A4、A5、report_id=14 trust audit 和前端 build 通过；A3 存在已知周线 overlap mismatch；A6 dry-run 被周线日历 Gate 阻断；后端 Direction A 聚合测试中 `test_profile_active_binding_migration.py` 在当前 PostgreSQL 数据上失败；A7 Data 页浏览器专项 smoke 仍未执行。

因此本轮不建议标记 `DIRECTION-A_FINAL_PASSED`，也不建议以最终通过状态合并。

## A1-A7 验收矩阵

| 步骤 | 本轮状态 | 新鲜证据 / 命令结果 | PASS/BLOCK 判断 |
|---|---|---|---|
| A1 Final Sealing | PASS | `test_target_coverage_audit.py`: 11 passed；`data_sealing_audit_20260712_162941` 显示 checksum 15056/15056、`unclassified_dispositions=0` | PASS |
| A2 Profile Registry | PARTIAL PASS | 三套 Profile 配置、`data_profiles` / `profile_active_bindings` 仍为当前事实源；Alembic current 为 `20260712_0023 (head)` | 被 migration roundtrip 测试失败牵连，不能 final pass |
| A3 Data Contract | RISK ACCEPTED / NOT FINAL PASS | `test_schema_contract.py` + overlap/residual 测试：18 passed；JM `1d` overlap passed，但 JM `1w` failed 49 block；full90 smoke 5 个目标 4 failed / 1 passed | 周线 mismatch 必须保留为风险 |
| A4 Warning Disposition | PASS | final coverage：`covered_warning=105`、`issue_register_rows=105`、`quality_warning=105`；Stage 8.6 pending 分流 5 accepted_warning / 3 registration_not_needed | PASS，105 warning 未升级 passed |
| A5 Unique Active | PASS | `profile_binding_rollout --mode verify --batch-id full90_001`: `passed=true`、4031 checksum checked、`duplicate_active_groups=0`、`validator_errors=0` | PASS |
| A6 Incremental Gate | BLOCK | `closure --mode dry-run --batch-id jm_a6_dry_run_001`: `status=blocked`、`failure_count=1`、`reason=weekly_calendar_incomplete`、`writes_database=false` | BLOCK，需要周线日历/目标日期 Gate 复核 |
| A7 Web / API | PARTIAL PASS | `npm --prefix apps/quant-web run build`: passed；Data 页专项浏览器 smoke 未执行 | BLOCK for final acceptance，需人工或浏览器验收 |
| report_id=14 trust audit | PASS | `backtest_trust_audit.py --report-id 14 --format markdown`: `audit_status=passed`，10/10 checks passed | PASS，未回写 report |

## 本轮实际命令与结果

```bash
git rev-parse --show-toplevel
git status --short --branch
git diff --stat
git diff --check
```

结果：仓库根目录正确；`git diff --check` 通过。工作区已有与本验收无关的未提交/未跟踪变更，未回退、未覆盖。

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_target_coverage_audit.py
```

结果：11 passed。

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_schema_contract.py \
  services/quant-api/tests/test_daily_weekly_overlap_batch.py \
  services/quant-api/tests/test_residual_root_cause_audit.py
```

结果：18 passed。

```bash
uv run --project services/quant-api python scripts/profile_binding_rollout.py \
  --mode verify \
  --output-dir data/reports/profile_binding_rollout_20260712 \
  --batch-id full90_001
```

结果：

```json
{
  "batch_id": "full90_001",
  "candidate_count": 4031,
  "duplicate_active_groups": 0,
  "validator_errors": 0,
  "checksum_checked": 4031,
  "passed": true
}
```

```bash
uv run --project services/quant-api python scripts/rqdata_dominant_v2_incremental_tail.py closure \
  --mode dry-run \
  --end-date 2026-07-11 \
  --product jm \
  --period 1m --period 1d --period 1w \
  --profiles all \
  --batch-id jm_a6_dry_run_001
```

结果：exit code 1；dry-run 写出 `data/reports/profile_incremental_closure_latest/jm_a6_dry_run_001_dry_run.json`，`writes_database=false`，但总状态为 `blocked`：

```text
failure_count=1
period=1w
reason=weekly_calendar_incomplete
week_trading_days=2026-07-06,2026-07-07
switch_target_count=0
committed=false
```

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_binding_validator.py \
  services/quant-api/tests/test_profile_active_binding_migration.py \
  services/quant-api/tests/test_dominant_v2_incremental.py \
  services/quant-api/tests/test_multi_primary_rulebook.py \
  services/quant-api/tests/test_profile_binding_candidate_generator.py \
  services/quant-api/tests/test_profile_binding_rollout.py \
  services/quant-api/tests/test_profile_aware_incremental.py
```

结果：35 passed / 1 failed。失败项：

```text
services/quant-api/tests/test_profile_active_binding_migration.py::test_migration_0022_upgrade_and_downgrade_roundtrip
UniqueViolation: could not create unique index "uq_profile_active_binding_identity_status"
Key (profile_id, instrument_symbol, contract_code, period, binding_status)=(intraday_research_v1, jm, jm.MAIN, 15m, superseded) is duplicated.
```

复核：

```bash
cd services/quant-api && uv run python -m alembic current
```

结果：`20260712_0023 (head)`。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

结果：`audit_status=passed`；`data_lineage`、`execution_policy`、`lineage_mapping`、`trade_order_consistency`、`equity_consistency`、`fee_slippage`、`contract_multiplier`、`trusted_metrics`、`reproducibility`、`sensitive_output` 全部 passed。

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_backtest_trust_audit.py
```

结果：8 passed。

```bash
npm --prefix apps/quant-web run build
```

结果：build passed；仍有既有大 chunk 警告：`dist-Cfb9QPbe.js 650.95 kB`。

```bash
git diff --check
rg -n -i '(password|secret|api[_-]?key|token|webhook|license|QYWX_WEBHOOK)\s*[:=]' \
  docs/tasks/DIRECTION-A-FINAL-ACCEPTANCE.md tasks/current.md docs/DATA_CENTER.md docs/STAGE13_BACKTEST_TRUST_AUDIT.md
```

结果：`git diff --check` 通过；核心验收文档敏感关键词无命中。对变更/未跟踪文件的数组式 `rg` 扫描无命中（`rg` exit code 1 表示 no matches）。

## PASS 证据路径

- A1 sealing：`data/reports/data_sealing_audit_20260712_162941/DIRECTION-A1-SEALING-SUMMARY.md`
- A1 disposition：`data/reports/data_sealing_audit_20260712_162941/disposition_register.csv`
- A3 overlap：`data/reports/daily_weekly_overlap_reconcile_20260712_jm_pilot/JM-PILOT-OVERLAP-SUMMARY.md`
- A3 full90 smoke：`data/reports/daily_weekly_overlap_reconcile_20260712_full90/BATCH-OVERLAP-SUMMARY.md`
- A4 final coverage：`data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/coverage_summary.md`
- Stage 8.6 pending：`data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`
- A5 binding verify：`data/reports/profile_binding_rollout_20260712/verify_report.json`
- A6 dry-run：`data/reports/profile_incremental_closure_latest/jm_a6_dry_run_001_dry_run.json`
- report_id=14 trust audit source：`docs/STAGE13_BACKTEST_TRUST_AUDIT.md`

## BLOCK / 风险项

1. A6 `jm_a6_dry_run_001` 被 `weekly_calendar_incomplete` 阻断，不能证明 profile-aware 增量闭包最终通过。
2. Direction A 后端聚合测试中 migration roundtrip 失败：当前真实 DB 已存在多个 `superseded` binding，无法 downgrade 到旧的 `(profile_id, instrument_symbol, contract_code, period, binding_status)` 全状态唯一约束。
3. A7 Data 页 Profile / Active / 更新时间列尚未做浏览器专项 smoke；本轮只证明前端 build 通过。
4. A3 overlap 仍有已知周线 mismatch：JM `1w` failed 49 block；full90 smoke 5 个目标中 4 failed。
5. A1 sealing 仍保留 3 条 `checksum_mismatch`、4 条 `missing_physical_file`、3 orphan、385 duplicate disposition；这些已有明确状态，但不是“修复完成”。
6. `live_observation_v1` warning 候选仍需人工 Gate；105 条 `quality_warning` 不得升级为 `passed`。
7. 工作区存在与本验收无关的未提交/未跟踪变更，本轮未回退也未审查其业务正确性。

## 硬约束确认

- [x] 未执行 live。
- [x] 未发送企业微信。
- [x] 未自动 commit / push / merge。
- [x] 未修改 `.env`。
- [x] 未回写 `report_id=14`。
- [x] 未将 105 条 warning 升级为 passed。
- [x] A6 dry-run 输出显示 `writes_database=false`、`committed=false`。
- [x] 未触碰 `data/raw/`。

## 是否建议合并

不建议以 `DIRECTION-A_FINAL_PASSED` 合并。

建议先处理或明确豁免以下合并前 Gate：

1. 修正或隔离 `test_profile_active_binding_migration.py` 对真实 PostgreSQL 降级的假设，确保不会在已有 superseded 重复历史的库上误判。
2. 重新选择已确认完整交易周的 `target_end`，或补齐交易日历证据后重跑 A6 dry-run，使 `failure_count=0`。
3. 启动本地 API / Web 后执行 Data 页专项 smoke，检查 Profile / Active / 更新时间列、控制台错误和空状态。
4. 人工确认 A3 周线 mismatch 是已知风险还是 final closure 阻断项。

## GPT 同步清单

- `tasks/current.md`
- `docs/tasks/DIRECTION-A-FINAL-ACCEPTANCE.md`
- `docs/DATA_CENTER.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `data/reports/data_sealing_audit_20260712_162941/DIRECTION-A1-SEALING-SUMMARY.md`
- `data/reports/daily_weekly_overlap_reconcile_20260712_jm_pilot/JM-PILOT-OVERLAP-SUMMARY.md`
- `data/reports/daily_weekly_overlap_reconcile_20260712_full90/BATCH-OVERLAP-SUMMARY.md`
- `data/reports/profile_binding_rollout_20260712/verify_report.json`
- `data/reports/profile_incremental_closure_latest/jm_a6_dry_run_001_dry_run.json`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/coverage_summary.md`
- `data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`

## 合并前人工检查清单

- [ ] `git status --short --branch` 中无未解释的无关变更。
- [ ] `git diff --check` 通过。
- [ ] 敏感信息扫描无命中，尤其是 `.env`、webhook、token、license、password。
- [ ] `report_id=14` trust audit 仍为 passed。
- [ ] 105 条 `quality_warning` 仍保持 warning，不升级 passed。
- [ ] A6 dry-run 使用人工确认过的 `target_end`，且 `failure_count=0`。
- [ ] Data 页浏览器 smoke 通过。
- [ ] 如需保留周线 mismatch，必须在合并说明中作为已知风险明确标注。
