# TASK-STAGE45-FINAL-ACCEPTANCE-R4505

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | TASK-STAGE45-FINAL-ACCEPTANCE-R4505 |
| Handbook Task | STAGE45-FINAL-ACCEPTANCE-R4505 / R45-05 |
| Work Level | L2 |
| GitHub Issue | #35 |
| Branch | codex/stage45-final-acceptance-r4505 |
| Worktree | /private/tmp/guiyi-stage45-final-acceptance-r4505 |
| Status | COMPLETED |
| Risk Level | R3 |
| Approval Scope | Read-only Stage 4/5 final acceptance; canonical docs only after all gates pass |
| Required Mounts | /Volumes/扩展盘 |
| Base Commit | cde065eeb00d677f668cb63960942c765ba307ed |
| Created At | 2026-07-20 |
| Owner | local-user |

```json
{
  "schema_version": 1,
  "task_id": "TASK-STAGE45-FINAL-ACCEPTANCE-R4505",
  "work_level": "L2",
  "github_issue": "#35",
  "branch": "codex/stage45-final-acceptance-r4505",
  "worktree": "/private/tmp/guiyi-stage45-final-acceptance-r4505",
  "status": "COMPLETED",
  "owner": "local-user",
  "allowed_paths": [
    "docs/tasks/TASK-STAGE45-FINAL-ACCEPTANCE-R4505.md",
    "data/reports/stage45_final_acceptance_r4505/",
    "PROJECT_SOURCE.md",
    "STATUS.md",
    "CODEX_TASKS.md",
    "TESTING.md",
    "tasks/current.md",
    "docs/BACKTEST_ENGINE.md",
    "docs/INDICATOR_KERNEL.md",
    "docs/CODEX_HANDOFF.md"
  ],
  "forbidden_paths": [
    ".env", ".env.*", "data/raw/", "data/parquet/", "data/processed/",
    "configs/", "packages/quant-core/guiyi_quant/strategies/",
    "services/quant-api/app/", "services/quant-api/alembic/",
    "apps/quant-web/src/", "data/reports/htdy_trusted_backtest_candidate_x5_03/",
    "data/reports/htdy_oos_validation_x5_04/", "data/reports/htdy_rolling_oos_x5_05/",
    "data/reports/htdy_strategy_review_x5_06b/", "data/reports/htdy_stage5_acceptance_x5_07/",
    "data/reports/htdy_stage45_closeout_r45/", "data/reports/htdy_stage5_acceptance_r45_v2/"
  ],
  "permissions": {
    "production_access_allowed": false,
    "database_write_allowed": false,
    "database_read_only_allowed": true,
    "external_network_allowed": true,
    "push_allowed": false,
    "merge_allowed": false,
    "deploy_allowed": false,
    "trading_execution_allowed": false
  }
}
```

## 5. 目标

先以只读方式复核阶段 4/5 全部 Gate、测试矩阵以及 report14/report15/task23、X5/R45 原始证据、协议、参数、Profile binding 和 Parquet 的不可变性。仅当全部通过，才更新指定 canonical 文档并输出：

```text
STAGE4_COMPLETED
STAGE5_COMPLETED
READY_TO_ENTER_STAGE6
```

HTDY 的合法研究终态必须保持 `REJECTED_RESEARCH_CANDIDATE`，不得描述为工程失败。

## 6. 不做事项

- 不修改策略、指标实现、协议、参数、报告、数据库、Profile binding、Parquet 或任何 X5/R45 原始证据。
- 不运行策略/OOS，不调用 RQData，不发送通知或交易指令。
- 不 push、merge、deploy，不执行 Stage 6。
- 只读验收失败时不更新任何 canonical 文档。

## 7. 实现约束

**允许修改**：

- `docs/tasks/TASK-STAGE45-FINAL-ACCEPTANCE-R4505.md`
- `data/reports/stage45_final_acceptance_r4505/*`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `CODEX_TASKS.md`
- `TESTING.md`
- `tasks/current.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/INDICATOR_KERNEL.md`
- `docs/CODEX_HANDOFF.md`

**禁止修改**：

- `.env`、`.env.*`
- `data/raw/*`、`data/parquet/*`、`data/processed/*`
- `configs/*`
- `packages/quant-core/guiyi_quant/strategies/*`
- `services/quant-api/app/*`、`services/quant-api/alembic/*`
- `apps/quant-web/src/*`
- `data/reports/htdy_trusted_backtest_candidate_x5_03/*`
- `data/reports/htdy_oos_validation_x5_04/*`
- `data/reports/htdy_rolling_oos_x5_05/*`
- `data/reports/htdy_strategy_review_x5_06b/*`
- `data/reports/htdy_stage5_acceptance_x5_07/*`
- `data/reports/htdy_stage45_closeout_r45/*`
- `data/reports/htdy_stage5_acceptance_r45_v2/*`

## 8. 验收步骤

1. 固定执行前 immutable file hashes、Git blob identity、PostgreSQL repeatable-read read-only snapshot、active binding 与实际 Parquet checksum。
2. 复算阶段 4 acceptance、R45-04 Stage 5 V2 acceptance、trust audits 与 prerequisite packet hash 链。
3. 运行阶段 4、R45-01/02/03/04、Review exact-bars、Web Review/Market、Ruff、diff 和 sensitive scan。
4. 再次采集不可变对象与数据库/binding/Parquet 快照并与执行前逐项对账。
5. 全部通过后生成版本化最终验收证据并对齐 canonical 文档。

## 18.0 自动化测试命令

具体命令以仓库当前 X4-06、X5-06B、R45-01/02/03/04 TASK 与测试事实为准，必须覆盖：

- Stage 4 indicator registry / policy / strict formal / protocol tests；
- R45-01/02/03/04 tests 与 X5-03/04/05/06B/07 回归；
- report14/report15 trust audit；
- Review exact-bars backend tests 与 Web Review/Market tests；
- scoped Ruff、`git diff --check`、scope/forbidden-path 与 sensitive output scan。

## 19. 验收标准

- 阶段 4 五个 marker 全部可由当前证据和测试复核。
- 阶段 5 trusted candidate、numeric hard reject、rolling rejection、Review、R45-01/02/03 与 R45-04 全部通过。
- 所有冻结对象执行前后 identity 完全一致，数据库事务为 PostgreSQL `REPEATABLE READ READ ONLY`。
- canonical 文档只在只读 Gate 通过后更新，且统一表述 Stage 4/5 工程闭环与 HTDY research rejection。
- 最终三个 Gate 精确为 `STAGE4_COMPLETED / STAGE5_COMPLETED / READY_TO_ENTER_STAGE6`。

## 20. 回滚

仅撤销本分支新增 TASK、最终验收证据和 canonical 文档更新；冻结策略、数据、报告、数据库及历史证据不受影响。

## 21. 执行结果

- `STAGE4_COMPLETED`。
- `STAGE5_COMPLETED`。
- `READY_TO_ENTER_STAGE6`。
- 阶段 5 保持 `STRATEGY_EVALUATION_PIPELINE_READY / REJECTED_RESEARCH_CANDIDATE / STAGE5_CLOSEOUT_V2_READY`。
- PostgreSQL 前后快照均为 `REPEATABLE READ READ ONLY`；report14、report15/task23、active binding 和绑定 Parquet SHA256 前后相等。
- 65 个 X5/R45/protocol/strategy 冻结输入与 12 个阶段 4 evidence 文件保持不变。
- 最终证据：`data/reports/stage45_final_acceptance_r4505/STAGE45_FINAL_ACCEPTANCE.json`。
- packet hash：`4df77fad49cab2783aca672f363595917e31beda3b9bbfadce9e0b3cc4d72cee`。

## 22. 测试结果

```text
Stage 4 backend affected: 132 passed
Stage 4 Web indicators: 13 passed
R45-01/02/03/04 + X5 regression: 123 passed
Review exact-bars + trust audit: 22 passed
Web Review/Market full tests: 76 passed, 1 optional skipped
Web build: passed, existing chunk-size warning only
Ruff: passed
read-only pre/post invariance: passed
packet self-hash: passed
git diff --check: passed
sensitive evidence scan: passed
forbidden-path audit: passed
```
