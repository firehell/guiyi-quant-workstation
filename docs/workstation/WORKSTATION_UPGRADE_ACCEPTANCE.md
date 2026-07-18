# WorkBuddy Unified V3 迁移验收

更新时间：2026-07-17

当前结论：

```text
WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
```

该结论表示 WorkBuddy Unified V3 的代码、Skill、Prompt、canonical 文档、归档和 runtime artifact hygiene 已进入 Demo 前候选状态，同时工作站已转入非阻塞支持模式。它不表示 FROZEN；Demo、旧 Issue / PR 清理和文档迁移可继续，但不得阻塞全历史盘点或 Audit V2，也不引入自动交易或自动 GitHub 生命周期动作。

控制面修复证据：实现提交 `c209cdbf`，`main` 合并提交 `d54e0198`；2026-07-17 定向复核为 `63 passed`。未发现需要在本任务修改 `scripts/ai` 的可复现缺陷。

## Commit 链

| Commit | 主题 | 说明 |
|---|---|---|
| `85785d15` | `feat(workstation): add WorkBuddy Unified V3 coordination` | Commit A：WorkBuddy V3 canonical、facade、Skill、Prompt、active 文档核心迁移 |
| `3dbc99dd` | `chore(workstation): consolidate legacy docs and runtime artifacts` | Commit B：历史工作站文档/任务/运行产物收敛与归档 |
| 本提交 | `docs(workstation): finalize WorkBuddy V3 migration readiness` | Commit C：全量回归、引用修复、GitHub 生命周期清单与最终状态 |

## 验收范围

包含：

- WorkBuddy Unified V3 facade：`scripts/ai/workbuddy_task.sh`。
- WorkBuddy orchestrator skill：`.agents/skills/guiyi-workstation-orchestrator/SKILL.md`。
- Delivery team skill 与 WorkBuddy prompts。
- active 工作站文档、工作流文档、README / PROJECT_SOURCE / STATUS / DECISIONS / CODEX_TASKS / TESTING。
- runtime artifact tracking hygiene。
- GitHub Issue / PR 生命周期人工清理清单。

不包含：

- 业务代码功能扩展。
- 数据修复、DB migration、生产写入。
- 自动 push / merge / deploy / close Issue。
- JM T3-real、long-running runtime、OOS / walk-forward。
- 策略盈利、实盘准入或自动交易。

## 当前事实模型

```text
GitHub main canonical docs
-> task branch TASK
-> GitHub Issue lifecycle
-> Draft PR / PR delivery
-> local .ai/results evidence
```

- GitHub 是事实源。
- TASK 是执行契约。
- Issue 是生命周期，不替代 TASK。
- PR 是交付容器，不代表自动 merge。
- WorkBuddy 对话和 memory 不是状态源。
- CodeBuddy compatibility-only。

## Demo 前测试矩阵

| 检查 | 命令 | Step 4 结果 |
|---|---|---|
| Bash syntax | `bash -n scripts/ai/*.sh` | PASS |
| Workstation tests | `python3 -m pytest -q tests/workstation` | PASS：486 passed |
| Doctor | `make workstation-doctor` | PASS：passed=14 failed=0 warn=0 skipped=2 |
| Diff whitespace | `git diff --check` | PASS |
| Markdown links | changed Markdown relative-link check | PASS：33 files checked |
| Runtime tracking | `git ls-files '.ai/**'` / `git ls-files '.workbuddy/**'` | PASS：`.ai/schema/task.schema.json` only; `.workbuddy/**` none |
| Canonical references | `git grep` CodeBuddy / old path terms | PASS：active invalid 引用已修复；剩余为 compatibility / historical / label / archive |
| Sensitive path check | static grep for token/webhook/password patterns | PASS_WITH_REVIEW：命中规则文本、占位示例和 synthetic test fixtures；未发现本轮新增真实凭据 |
| Business/data diff | `git diff --name-only HEAD -- apps services packages strategies experiments data database migrations scripts/runtime scripts/deploy .env*` | PASS：无业务、数据、DB、运行部署或 `.env*` diff |

## Demo 命令

Demo 应由用户确认后在专用 Issue / TASK / worktree 执行：

```bash
scripts/ai/workbuddy_task.sh analyze --issue #N
scripts/ai/workbuddy_task.sh bootstrap --issue #N
scripts/ai/workbuddy_task.sh plan --issue #N
scripts/ai/workbuddy_task.sh approve --issue #N --confirm-user-approval
scripts/ai/workbuddy_task.sh dev --issue #N
scripts/ai/workbuddy_task.sh test --issue #N
scripts/ai/workbuddy_task.sh review --issue #N
scripts/ai/workbuddy_task.sh result --issue #N
scripts/ai/workbuddy_task.sh delivery --task <TASK_ID>
```

外部 PR Review gate：

```bash
scripts/ai/workbuddy_task.sh record-external-review --task <TASK_ID> --pr <PR_NUMBER>
```

GitHub 写回必须显式确认：

```bash
scripts/ai/workbuddy_task.sh sync-pr --task <TASK_ID> --pr <PR_NUMBER> --confirm-github-write
```

## Rollback

如果 Demo 发现 V3 facade / Skill / Prompt 口径不一致：

1. 不关闭旧 Issue / PR。
2. 不删除 CodeBuddy compatibility 文档。
3. 使用 Commit A/B/C 之前的 task branch 或 Git history 回看旧流程。
4. 继续通过 `scripts/ai/dispatch_task.sh <TASK_ID> plan|dev|test|review|result` 直接执行 L1/L2。
5. 将状态改为 `WORKBUDDY_V3_MIGRATION_BLOCKED` 并记录阻塞原因。

## 剩余风险

- WorkBuddy V3 尚未跑真实端到端 Demo。
- GitHub 生命周期清理清单需要用户逐项确认后才能执行。
- Issue #27 / Draft PR #28 已按 `DEMO-WB-V3-001` 收口为未完成归档；仓库历史 Demo 文档仅作为历史占位快照。
- `make workstation-doctor` 可能因当前分支不是 `main`、本机 GitHub/环境策略或未启动服务而失败；失败不能被写成通过。
- 数据层仍处于全历史重审阶段，JM runtime 仍 pending；以上业务 Gate 均不依赖 WorkBuddy Demo 完成。

## 支持模式边界

- 业务 P0 始终排在 WorkBuddy Demo 和生命周期清理之前。
- 后续只修复真实业务 Task 暴露且可复现的控制面问题，并独立建立 follow-up。
- 不扩展多项目、复杂模型路由、自动 merge/deploy、Dashboard 或代理团队模拟。
- 对业务阶段 B 的影响：`不阻塞`。
