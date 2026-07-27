# TASK-HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | TASK-HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503 |
| Handbook Task | HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503 / R45-03 |
| Work Level | L2 |
| GitHub Issue | #33 |
| Branch | codex/htdy-rolling-oos-decision-semantics-r4503 |
| Worktree | /private/tmp/guiyi-htdy-rolling-oos-decision-semantics-r4503 |
| Status | COMPLETED |
| Risk Level | R3 |
| Approval Scope | Rolling decision semantics, X5-07 blocked precedence, tests, versioned file-only evidence |
| Required Mounts | /Volumes/扩展盘 |
| Base Commit | d5891c6b1dfd7ad626ad5c47392828939e8dd8c0 |
| Created At | 2026-07-20 |
| Owner | local-user |

```json
{
  "schema_version": 1,
  "task_id": "TASK-HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503",
  "work_level": "L2",
  "github_issue": "#33",
  "branch": "codex/htdy-rolling-oos-decision-semantics-r4503",
  "worktree": "/private/tmp/guiyi-htdy-rolling-oos-decision-semantics-r4503",
  "status": "COMPLETED",
  "owner": "local-user",
  "allowed_paths": [
    "docs/tasks/TASK-HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503.md",
    "tasks/current.md",
    "services/quant-api/app/backtest/htdy_rolling_oos.py",
    "services/quant-api/app/backtest/htdy_rolling_decision_recheck.py",
    "services/quant-api/app/services/htdy_stage5_acceptance.py",
    "services/quant-api/scripts/htdy_rolling_decision_recheck.py",
    "services/quant-api/tests/test_htdy_rolling_oos_x505.py",
    "services/quant-api/tests/test_htdy_stage5_acceptance_x507.py",
    "services/quant-api/tests/test_htdy_rolling_decision_r4503.py",
    "data/reports/htdy_stage45_closeout_r45/rolling_decision_recheck/"
  ],
  "forbidden_paths": [
    ".env", ".env.*", "data/raw/", "data/parquet/", "data/processed/",
    "configs/oos/", "packages/quant-core/guiyi_quant/strategies/",
    "services/quant-api/app/models/", "services/quant-api/alembic/",
    "data/reports/htdy_trusted_backtest_candidate_x5_03/",
    "data/reports/htdy_oos_validation_x5_04/",
    "data/reports/htdy_rolling_oos_x5_05/",
    "data/reports/htdy_strategy_review_x5_06b/",
    "data/reports/htdy_stage5_acceptance_x5_07/"
  ],
  "permissions": {
    "production_access_allowed": false,
    "database_write_allowed": false,
    "external_network_allowed": false,
    "push_allowed": false,
    "merge_allowed": false,
    "deploy_allowed": false,
    "trading_execution_allowed": false
  }
}
```

## 5. 目标

使 rolling OOS decision 严格区分 structural/execution blocked 与 numeric rejected；修复 X5-07 blocked 优先级，并基于既有 X5-05 artifacts 生成不可覆盖的 R45-03 recheck 证据。

## 6. 不做事项

- 不覆盖 X5-05 或 X5-07 原始 packet/artifact。
- 不重跑策略、不改参数、protocol、报告、数据库、Profile binding、Parquet、PnL、live、通知或交易。
- 不 push、merge、deploy，不执行 R45-04。

## 7. 决策契约

- required fold 缺失/乱序、execution exception、`status != completed`、`audit_status != passed`、structural reasons、binding/config/hash drift、cost timeline incomplete 或 artifact/hash error：`STRATEGY_VALIDATION_BLOCKED`。
- 只有全部 folds 结构通过且 numeric reasons 非空，才允许 rejected；X5-04 hard reject 时为 `DIAGNOSTIC_CONFIRMS_REJECTION`，否则为 `PROPOSED_REJECTED_RESEARCH_CANDIDATE`。
- 全部 folds 结构和 numeric 均通过时，X5-04 executed 才允许 `PROPOSED_VALIDATED_RESEARCH_CANDIDATE`；既有 hard reject 只能保持 `DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS`。
- X5-07 必须先判 rolling blocked，再处理 X5-04 hard reject。

## 18.0 自动化测试命令

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/test_htdy_rolling_decision_r4503.py \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py \
  services/quant-api/tests/test_htdy_stage5_acceptance_x507.py \
  services/quant-api/tests/test_htdy_strategy_review_x506b.py \
  services/quant-api/tests/test_htdy_sample_end_audit_r4502.py

PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/ruff check \
  services/quant-api/app/backtest/htdy_rolling_oos.py \
  services/quant-api/app/backtest/htdy_rolling_decision_recheck.py \
  services/quant-api/app/services/htdy_stage5_acceptance.py \
  services/quant-api/scripts/htdy_rolling_decision_recheck.py \
  services/quant-api/tests/test_htdy_rolling_decision_r4503.py \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py \
  services/quant-api/tests/test_htdy_stage5_acceptance_x507.py

git diff --check
```

## 19. 验收标准

- `ROLLING_OOS_DECISION_SEMANTICS_READY`。
- `CURRENT_HTDY_DIAGNOSTIC_REJECTION_PRESERVED`。
- current real folds 继续为 `DIAGNOSTIC_CONFIRMS_REJECTION`。
- X5-04 hard reject 不可翻转；original X5-05/X5-07 文件 hash 不变。
- 禁止路径无修改。

## 20. 回滚

仅撤销本分支 code/test/TASK/current-task 和新 recheck evidence；原始策略、报告、数据库和 X5 证据没有写入。

## 21. 执行结果

- Gate：`ROLLING_OOS_DECISION_SEMANTICS_READY`。
- Gate：`CURRENT_HTDY_DIAGNOSTIC_REJECTION_PRESERVED`。
- 当前 A/B/C 三个 real folds 均为 `completed + audit passed + structural_reasons=[]`，数值拒绝继续独立复现，rolling decision 保持 `DIAGNOSTIC_CONFIRMS_REJECTION`。
- X5-07 已修复 blocked 优先级：rolling blocked 不再被 X5-04 hard reject 误标为 rejected。
- recheck packet：`data/reports/htdy_stage45_closeout_r45/rolling_decision_recheck/ROLLING_DECISION_RECHECK.json`。
- packet hash：`9fc9d4a803631a70c018b17f919631291f93ffe03b23284f890cb0c2642d1195`。
- 原 X5-05 packet 文件 SHA256 保持 `b1293b8b49865092c71affb7c9ef46b7b3617de758f0b152b0cabfe7f99922ef`。
- 原 X5-07 packet 文件 SHA256 保持 `6f214b69fec1ade5d285572bc871a3c0a71f757d92512cdd613d677948a3efcd`。

## 22. 测试结果

```text
pytest required matrix: 56 passed
ruff scoped files: All checks passed
git diff --check: passed
formal CLI: exit 0; both required gates emitted
formal CLI idempotency rerun: exit 0; packet hash unchanged
```

未修改策略、protocol、报告、数据库、Profile binding、Parquet 或原始 X5-04/05/06B/07 证据；未执行 R45-04。
