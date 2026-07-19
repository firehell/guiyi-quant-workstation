# TASK-HTDY-SAMPLE-END-LIQUIDATION-R4502

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | TASK-HTDY-SAMPLE-END-LIQUIDATION-R4502 |
| Handbook Task | HTDY-SAMPLE-END-LIQUIDATION-R4502 / R45-02 |
| Work Level | L2 |
| GitHub Issue | #32 |
| Branch | codex/htdy-sample-end-liquidation-r4502 |
| Worktree | /private/tmp/guiyi-htdy-sample-end-liquidation-r4502 |
| Status | COMPLETED / OOS_STRUCTURAL_AUDIT_AMENDED + NUMERIC_HARD_REJECT_PRESERVED |
| Risk Level | R3 |
| Approval Scope | Plan, read-only audit code, tests, versioned evidence |
| Required Env | canonical PostgreSQL read-only access |
| Required Mounts | /Volumes/扩展盘 |
| Created At | 2026-07-19 |
| Owner | local-user |

```json
{
  "schema_version": 1,
  "task_id": "TASK-HTDY-SAMPLE-END-LIQUIDATION-R4502",
  "work_level": "L2",
  "github_issue": "#32",
  "branch": "codex/htdy-sample-end-liquidation-r4502",
  "worktree": "/private/tmp/guiyi-htdy-sample-end-liquidation-r4502",
  "status": "COMPLETED",
  "owner": "local-user",
  "allowed_paths": [
    "docs/tasks/TASK-HTDY-SAMPLE-END-LIQUIDATION-R4502.md",
    "tasks/current.md",
    "services/quant-api/app/backtest/htdy_sample_end_audit.py",
    "services/quant-api/scripts/htdy_sample_end_audit.py",
    "services/quant-api/tests/test_htdy_sample_end_audit_r4502.py",
    "data/reports/htdy_stage45_closeout_r45/sample_end_audit/"
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

验证 X5-04 唯一 `sample_end_forced_exit` 是否为窗口末端 accounting liquidation；若满足严格有限条件，仅新增版本化审计契约和证据，使普通事件继续要求 `fill_time > signal_time`，并保持 numeric hard reject 与所有原始事实不变。

## 6. 不做事项

- 不修改 HTDY v0.1.0 策略、`finalize_sample_end()`、frozen protocol 或参数。
- 不修改 report14/report15/task23、trade/order/equity/PnL。
- 不修改数据库、Profile binding、Parquet、manifest 或 RQData。
- 不修改或覆盖 X5-03/04/05/06B/07 原始 packet、artifact 或证据。
- 不执行策略重跑、调参、live、通知、交易、push、merge 或 deploy。

## 7. 实现约束

- 前置 Gate 必须为 `STAGE45_CLOSEOUT_BASELINE_READY` 与 `HTDY_FROZEN_DATA_WINDOW_EQUIVALENT`，R45-01 acceptance 指针和 hash 必须可复算。
- accounting liquidation 必须是唯一且最终的 sample-end close event/trade，发生在 frozen window end；持仓由更早 signal 建立，matching open event 在 finalizer close 前出现。
- 除精确 liquidation close 外，所有 signal-bearing event/trade 继续严格执行 `fill > signal`；entry fill 永不豁免。
- 任一身份、顺序、数量、reason/source、窗口或 hash 漂移均输出 `STRATEGY_VALIDATION_BLOCKED_FILL_POLICY_DRIFT`。
- 成功仅输出 `OOS_STRUCTURAL_AUDIT_AMENDED` 与 `NUMERIC_HARD_REJECT_PRESERVED`；numeric reject 原因和值必须保持不变。

## 18.0 自动化测试命令

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/test_htdy_sample_end_audit_r4502.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py \
  services/quant-api/tests/test_htdy_frozen_data_completion_r4501b.py

PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/ruff check \
  services/quant-api/app/backtest/htdy_sample_end_audit.py \
  services/quant-api/scripts/htdy_sample_end_audit.py \
  services/quant-api/tests/test_htdy_sample_end_audit_r4502.py

git diff --check
```

## 19. 验收标准

- 精确 sample-end accounting liquidation 通过并生成固定目录证据。
- 普通同时间 signal/fill、非窗口末端、多笔 sample-end、entry 同时间、伪造 reason/source、event-order 漂移均 fail-closed。
- X5-04 numeric hard reject、result/trade/order/equity hash 与 report14/report15/task23 不变。
- 禁止路径无修改。

## 20. 回滚

仅删除本分支新增 helper、CLI、测试、TASK/current-task 记录和 `sample_end_audit/` 证据；原始策略、报告、数据库与 X5 证据没有写入。

## 21. 执行结果

```text
OOS_STRUCTURAL_AUDIT_AMENDED
NUMERIC_HARD_REJECT_PRESERVED
packet_hash=4c4978f84e5806801e9917003ca22f38a29f8cc1fd3843e5f9b68b93937371f8
```

- X5-04 唯一 event `357 / HTDY-179` 被精确分类为 accounting liquidation；window end 为 `2026-07-10T15:00:00`。
- matching `open_long` event `356` 的 signal 为 `14:45`、fill 为 `15:00`，在 finalizer close event 前出现；该 event-order 仅证明窗口末端会计平仓，不声称普通 next-bar fill。
- 所有 entry 和其他 signal-bearing event/trade 继续要求 `fill > signal`；任何同刻、非末端、多笔、伪造 reason/source 或 event-order 漂移均 fail-closed。
- numeric hard reject 保持 `max_consecutive_losses=12`、`profit_factor=0.16355909337101607`，研究结论继续为 `REJECTED_RESEARCH_CANDIDATE`。
- PostgreSQL 前后均使用 `REPEATABLE READ READ ONLY`；report15/task23、report14 trust audit/facts hash 和 report15 最后一笔 `HTDY-1255` 不变。
- X5-04 result/trade/order/equity/PnL 及全部原始 X5 文件 hash 不变；未运行策略、未写数据库。

验证结果：R45-02 单测 `16 passed`；R45-02 + X5-04 + X5-03 + R4501B 回归 `66 passed`（最终复跑结果）；Ruff、`git diff --check`、禁止路径审计通过。
