# WorkBuddy Unified V3 运营检查清单

更新时间：2026-07-16

适用状态：

```text
WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING
```

本文是 Demo 与日常远程使用前的操作清单。它不授权 WorkBuddy 自动 push、merge、deploy、close Issue 或执行真实交易。

## 会话开始

```bash
pwd
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
git worktree list
scripts/ai/writer_lock.sh status --worktree "$PWD" || true
```

确认：

- 当前在 TASK 指定 worktree。
- 当前 branch 与 TASK / Issue / PR 一致。
- 没有活跃 writer lock。
- 没有 `.env*`、凭据、数据文件被加入 Git。
- WorkBuddy memory 不作为状态源。

## WorkBuddy 固定命令

只允许通过 facade 执行：

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
scripts/ai/workbuddy_task.sh status --issue #N
scripts/ai/workbuddy_task.sh cancel --issue #N
scripts/ai/workbuddy_task.sh sync-pr --task <TASK_ID> --pr <PR_NUMBER> --confirm-github-write
scripts/ai/workbuddy_task.sh record-external-review --task <TASK_ID> --pr <PR_NUMBER>
```

禁止：

- 自由 shell。
- `eval`。
- 裸调 `codex`。
- 直调 `codex_plan.sh` / `codex_dev.sh`。
- 自动串联 stage。
- 无确认 approve。
- 无确认 GitHub 写回。
- push / merge / deploy / close。

## Gate 检查

| Gate | 检查 |
|---|---|
| Issue/TASK | Issue、TASK file path、branch、Draft PR 一致 |
| Plan | 第一轮只读，不修改 tracked files |
| Approval | `approve` 必须包含 `--confirm-user-approval` |
| Scope | allowed_paths / forbidden_paths 与 TASK 对齐 |
| Writer lock | Codex writer lock 串行；不新增 workbuddy writer |
| Tests | TASK required_tests 和相关最小测试必须记录 |
| Result | `.ai/results/<TASK_ID>/` local-first，Issue/PR 只回填脱敏摘要 |
| External Review | R0/R1 或要求 Review 的任务必须记录真实 PR review |
| Delivery | delivery 只生成交付输入，不宣称通过 |

## 故障处理

如果 stage 失败：

1. 停止，不自动 retry。
2. 返回 Issue / TASK / PR / stage / Gate / tests / risks / next_action。
3. 保留 `.ai/results/<TASK_ID>/` 证据。
4. 不 reset、不删除用户文件。
5. 必要时进入 `WORKBUDDY_V3_MIGRATION_BLOCKED`，而不是伪造通过。

## Demo 后人工检查

```bash
bash -n scripts/ai/*.sh
python3 -m pytest -q tests/workstation
make workstation-doctor
git diff --check
git status --short
git ls-files '.ai/**'
git ls-files '.workbuddy/**'
```

人工确认：

- CodeBuddy 仍可作为 compatibility-only 回退读取。
- active 文档不把 archive 当 current rule。
- 业务代码和数据目录无无关修改。
- GitHub lifecycle cleanup 没有自动执行。
- 用户决定是否 commit / push / merge / close。
