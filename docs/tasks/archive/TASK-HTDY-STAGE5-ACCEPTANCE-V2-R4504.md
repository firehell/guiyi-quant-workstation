# TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504 |
| Handbook Task | HTDY-STAGE5-ACCEPTANCE-V2-R4504 / R45-04 |
| Work Level | L2 |
| GitHub Issue | #34 |
| Branch | codex/htdy-stage5-acceptance-v2-r4504 |
| Worktree | /private/tmp/guiyi-htdy-stage5-acceptance-v2-r4504 |
| Status | COMPLETED |
| Risk Level | R3 |
| Approval Scope | Read-only Stage 5 V2 acceptance, tests, TASK/current docs, versioned evidence |
| Required Mounts | /Volumes/扩展盘 |
| Base Commit | 964a961ac9e553901dc8e231a851aae5dc8a1bda |
| Created At | 2026-07-20 |
| Owner | local-user |

```json
{
  "schema_version": 1,
  "task_id": "TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504",
  "work_level": "L2",
  "github_issue": "#34",
  "branch": "codex/htdy-stage5-acceptance-v2-r4504",
  "worktree": "/private/tmp/guiyi-htdy-stage5-acceptance-v2-r4504",
  "status": "COMPLETED",
  "owner": "local-user",
  "allowed_paths": [
    "docs/tasks/TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504.md",
    "tasks/current.md",
    "services/quant-api/app/services/htdy_stage5_acceptance_v2.py",
    "services/quant-api/scripts/htdy_stage5_acceptance_v2.py",
    "services/quant-api/tests/test_htdy_stage5_acceptance_v2_r4504.py",
    "data/reports/htdy_stage5_acceptance_r45_v2/"
  ],
  "forbidden_paths": [
    ".env", ".env.*", "data/raw/", "data/parquet/", "data/processed/",
    "configs/oos/", "packages/quant-core/guiyi_quant/strategies/",
    "services/quant-api/app/models/", "services/quant-api/alembic/",
    "data/reports/htdy_trusted_backtest_candidate_x5_03/",
    "data/reports/htdy_oos_validation_x5_04/",
    "data/reports/htdy_rolling_oos_x5_05/",
    "data/reports/htdy_strategy_review_x5_06b/",
    "data/reports/htdy_stage5_acceptance_x5_07/",
    "data/reports/htdy_stage45_closeout_r45/"
  ],
  "permissions": {
    "production_access_allowed": false,
    "database_write_allowed": false,
    "database_read_only_allowed": true,
    "external_network_allowed": false,
    "push_allowed": false,
    "merge_allowed": false,
    "deploy_allowed": false,
    "trading_execution_allowed": false
  }
}
```

## 5. 目标

以不可变 X5-03/04/05/06B/07 与 R45-01/02/03 证据、当前 canonical PostgreSQL 只读快照及 frozen strategy Git blob 为输入，生成 Stage 5 Acceptance V2。仅当十五项 Hard Gate 全部通过时输出：

```text
STRATEGY_EVALUATION_PIPELINE_READY
REJECTED_RESEARCH_CANDIDATE
STAGE5_CLOSEOUT_V2_READY
```

任一缺失或漂移必须为 `STRATEGY_VALIDATION_BLOCKED`。

## 6. 不做事项

- 不覆盖 X5-07 或任何 X5/R45 原 packet/artifact。
- 不修改策略、frozen protocol、报告、数据库、Profile binding、Parquet、PnL、trade 或 order。
- 不运行策略/OOS，不调用 RQData，不发送通知或交易指令。
- 不 push、merge、deploy，不执行后续 Task。

## 7. Hard Gate

1. candidate/report14 双 audit passed；
2. report14 invariance；
3. report15 identity 不变；
4. protocol/parameter hash 不变；
5. binding identity 不变；
6. frozen data window equivalence passed；
7. sample-end accounting liquidation audit passed；
8. 普通信号 fill timing passed；
9. numeric hard reject 保持；
10. rolling folds 结构 audit passed；
11. rolling numeric diagnostics 确认 rejection；
12. Review exact-bars/browser smoke passed；
13. 原始 packet 未覆盖；
14. canonical DB 无新增写入；
15. 策略和参数无变化。

## 18.0 自动化测试命令

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/test_htdy_stage5_acceptance_v2_r4504.py \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py \
  services/quant-api/tests/test_htdy_strategy_review_x506b.py \
  services/quant-api/tests/test_htdy_stage5_acceptance_x507.py \
  services/quant-api/tests/test_htdy_frozen_data_completion_r4501b.py \
  services/quant-api/tests/test_htdy_sample_end_audit_r4502.py \
  services/quant-api/tests/test_htdy_rolling_decision_r4503.py

PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/ruff check \
  services/quant-api/app/services/htdy_stage5_acceptance_v2.py \
  services/quant-api/scripts/htdy_stage5_acceptance_v2.py \
  services/quant-api/tests/test_htdy_stage5_acceptance_v2_r4504.py

git diff --check
```

## 19. 验收标准

- 三个成功 marker 精确输出，blocked packet 只保留 blocked marker。
- 十五项 Hard Gate 全部为 passed。
- 正式 CLI 使用 PostgreSQL `REPEATABLE READ READ ONLY`，前后 DB/binding 快照一致并匹配 R45-02。
- 原 X5/R45 packet/artifact SHA256 不变；原 X5-07 不覆盖。
- 固定输出可完全相同地幂等复跑，非同一内容拒绝覆盖。
- 禁止路径无修改，完整回归通过。

## 20. 回滚

仅撤销本分支新增 service/CLI/test/TASK/current-task 和新 V2 evidence；原始策略、数据、报告、数据库及 X5/R45 证据没有写入。

## 21. 执行结果

- `STRATEGY_EVALUATION_PIPELINE_READY`。
- `REJECTED_RESEARCH_CANDIDATE`。
- `STAGE5_CLOSEOUT_V2_READY`。
- 十五项 Hard Gate 全部 `passed`。
- 正式 packet：`data/reports/htdy_stage5_acceptance_r45_v2/STAGE5_ACCEPTANCE_V2.json`。
- packet hash：`0d40b075859de77f21bfab513fe3531dcf5d9a244256cf6fa7e89056fd38dbb8`。
- 两次正式 CLI 输出和 packet hash 完全一致。
- 两次 PostgreSQL 快照均为 `REPEATABLE READ READ ONLY`，前后相等且与 R45-02 冻结快照相等。
- 65 个不可变输入文件 SHA256 前后相等；6 个 frozen strategy/protocol 文件与 X5-03 source commit Git blob 相等。
- 首次因 worktree 环境缺少 DB 凭据而产生的 blocked attempt 保留在 `.ai/results/TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504/`，正式成功证据未覆盖该失败记录。

未修改 X5-07 或任何 X5/R45 原 packet/artifact、策略、protocol、报告、数据库、Profile binding 或 Parquet。

## 22. 测试结果

```text
baseline before implementation: 106 passed
R45-04 focused tests: 17 passed
final required matrix: 123 passed
ruff scoped files: All checks passed
git diff --check: passed
formal CLI idempotency: three runs succeeded with the same packet hash
packet self-hash and 15 Hard Gates: passed
forbidden-path audit: passed
```
