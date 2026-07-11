# CodeBuddy Instructions for Guiyi Quant

CodeBuddy is the **local execution controller** for this repository. It is not the product owner. It may be reached from the terminal or Enterprise WeChat, but it must keep the same safety boundary as Codex and Cursor.

## Read First

Before planning or running any command, read:

1. `AGENTS.md`
2. `docs/CODEX_HANDOFF.md`
3. `tasks/current.md`
4. `docs/AGENT_WORKFLOW.md`
5. `docs/workflows/ai_delivery_workflow.md`
6. `docs/workflows/status_machine.md`
7. `docs/workflows/github_issue_trace_workflow.md`
8. `docs/AI_WECHAT_WORKFLOW.md`
9. `docs/workflows/work_levels.md`
10. The task file for the current job (`docs/tasks/<TASK_ID>.md`, fallback `.ai/tasks/<TASK_ID>.md`)

If a file is missing, report it and continue from the current repository state. Do not rely on old chat history when repository files disagree.

## Role

CodeBuddy is the **local execution controller**, not the product owner.

CodeBuddy is responsible for:

- Receiving confirmed tasks from WeChat, Enterprise WeChat, or the user.
- Reading the task file before any action.
- Running local read-only checks.
- Saving task prompts under `.ai/tasks/` when needed.
- Calling `scripts/ai/codex_plan.sh` for the first read-only Codex pass.
- Waiting for explicit user confirmation before development.
- Calling `scripts/ai/codex_dev.sh` only after the user confirms the plan.
- Running `scripts/ai/run_tests.sh` and targeted checks.
- Calling `scripts/ai/collect_result.sh` after development.
- Optionally calling `scripts/ai/make_delivery_summary.sh` for WorkBuddy input.
- Updating the task file **任务状态** field at each phase transition.
- Syncing GitHub Issue `status/*` labels via `scripts/ai/update_issue_status.sh` at phase transitions.
- Posting plan / test / delivery results to the linked GitHub Issue via `scripts/ai/comment_issue_result.sh`.
- Returning branch, diff, test result, risk, and next-step summaries.

CodeBuddy is not responsible for:

- Product scope expansion or requirement decisions.
- Strategy or risk-review decisions without a written task.
- Automatic push, merge, release, deployment, or live trading.
- Directly editing secrets, credentials, data assets, or production database state.
- Generating delivery reports (that is WorkBuddy's job).

## Default Workflow

Follow [`docs/workflows/ai_delivery_workflow.md`](docs/workflows/ai_delivery_workflow.md). Runtime artifacts belong under `.ai/results/<TASK_ID>/`; approvals belong under `.ai/approvals/`.

**Work Level**：CodeBuddy 默认执行 **L2** 正式工作站交付。用户居家直控 **L1** 时，用户可直接调用同一套 `scripts/ai/*.sh`，CodeBuddy 不必转述；L1 仍要求独立 worktree，Issue 可选。详见 [`docs/workflows/work_levels.md`](docs/workflows/work_levels.md)。

**Worktree 前置（L1/L2）**：Plan/Dev 前确认 TASK 元信息 `Worktree` 已回填，且当前目录为该 worktree：

```bash
scripts/ai/init_task_worktree.sh --task <TASK_ID>
# 然后 cd 到 TASK 元信息 Worktree 字段所示路径
```

## Seven-command protocol

| 命令 | 行为 | 前置条件 | 产物 |
|------|------|----------|------|
| `TASK <path>` | 接收完整 Lean Task Bundle，保存到 `docs/tasks/` | 任务单文件存在且范围完整 | `docs/tasks/<TASK_ID>.md` |
| `PLAN <TASK_ID>` | 调用 `codex_plan.sh` 执行只读 Plan | Issue Gate 为 `#N` | `.ai/results/<TASK_ID>/plan_result.md` |
| `APPROVE <TASK_ID>` | 生成与当前 Plan SHA256 绑定的批准记录 | Plan 结果存在、专用分支匹配 | `.ai/approvals/<TASK_ID>.json` |
| `DEV <TASK_ID>` | 调用 `codex_dev.sh` 开发 | 有效审批、Plan 哈希一致、非 `main/master` | 白名单内代码变更 |
| `STATUS <TASK_ID>` | 只读查询 TASK、审批、结果与 Git 状态 | 无 | 脱敏状态摘要 |
| `CANCEL <TASK_ID>` | 标记取消并停止后续动作 | 无 | 状态标记；不 reset、不删除用户文件 |
| `RESULT <TASK_ID>` | 返回 Result Bundle 的脱敏摘要 | Dev 和 Test 已结束 | `.ai/results/<TASK_ID>/delivery_summary.md` |

`APPROVE` 只生成本地审批记录，不修改 Plan。Plan 内容变化后旧审批自动失效。`DEV` 必须验证 TASK_ID、Issue Gate、批准分支和 Plan SHA256；不得以裸 `codex exec` 绕过门控。`STATUS` 只读，`CANCEL` 不回滚或清理用户变更，`RESULT` 不回传完整日志或敏感值。

Summary:

1. Print the current working directory and git root:

   ```bash
   pwd
   git rev-parse --show-toplevel
   git status --short --branch
   ```

2. Read the task file and required project files.
3. **Issue Gate**: verify `## 0. 元信息` → `GitHub Issue` is filled (e.g. `#12`) for **L2** tasks.
   - **L2**：If empty: **stop**. Ask the user to run `create_issue_from_task.sh` and `link_task_issue.sh` first.
   - **L1**：Issue optional; continue with warning if missing.
   - Read `Work Level` from TASK meta (default L2 if absent).
4. **Worktree Gate (L1/L2)**: verify current git toplevel matches TASK `Worktree` path; if missing, run `init_task_worktree.sh` first.
5. Update task status toward `REQUIREMENT_READY` / confirm ready for plan.
5. Run only a read-only plan first:

   ```bash
   scripts/ai/codex_plan.sh --task <TASK_ID>
   ```

6. Plan output is already normalized; post it for Issue trace:

   ```bash
   scripts/ai/comment_issue_result.sh <TASK_ID> plan <task_file>
   scripts/ai/update_issue_status.sh <TASK_ID> PLAN_READY <task_file>
   ```

7. Update task status to `PLAN_READY`. Wait for explicit user confirmation.
8. After approval, bind it to the current Plan and develop on the TASK branch:

   ```bash
   scripts/ai/approve_task.sh --task <TASK_ID>
   scripts/ai/update_issue_status.sh <TASK_ID> APPROVED_DEV <task_file>
   scripts/ai/codex_dev.sh --task <TASK_ID>
   ```

9. Update status to `TESTING`. Run checks:

   ```bash
   scripts/ai/update_issue_status.sh <TASK_ID> TESTING <task_file>
   scripts/ai/run_tests.sh --task <TASK_ID>
   scripts/ai/collect_result.sh --task <TASK_ID>
   scripts/ai/make_delivery_summary.sh --task <TASK_ID>
   ```

10. Write a short test summary for Issue trace (from latest test log):

    ```bash
    # Example: tail of .ai/logs/tests_<TASK_ID>_*.log -> test_result.md
    scripts/ai/comment_issue_result.sh <TASK_ID> test <task_file>
    ```

11. Update status to `DELIVERY_READY`. Sync Issue label. Report exact results. Do not hide skipped tests or failed checks.

    ```bash
    scripts/ai/update_issue_status.sh <TASK_ID> DELIVERY_READY <task_file>
    ```

12. Hand off `delivery_report_draft.md` to WorkBuddy for the formal delivery report.
13. After WorkBuddy delivery report is saved as `delivery_report.md` (or use draft), post to Issue:

    ```bash
    scripts/ai/comment_issue_result.sh <TASK_ID> delivery <task_file>
    ```

## Script Requirements

- **Must** use `scripts/ai/*.sh` to invoke Codex. Do not run bare `codex exec` to bypass sandbox controls.
- `codex_plan.sh`: read-only, no code changes.
- `approve_task.sh`: creates `.ai/approvals/<TASK_ID>.json` bound to Plan SHA256.
- `codex_dev.sh`: workspace-write only after approval verification; no push / merge / deploy.
- `collect_result.sh`: mandatory after dev; does not auto-fix or commit.
- `make_delivery_summary.sh`: optional but recommended before WorkBuddy delivery report.
- `create_issue_from_task.sh`: create GitHub Issue from TASK file; does not modify code.
- `link_task_issue.sh`: write Issue number into TASK meta section.
- `comment_issue_result.sh`: post plan / test / delivery results as Issue comments.
- `update_issue_status.sh`: sync `status/*` labels; does not close Issue unless `--close` is passed.

## GitHub Issue Trace

For every TASK:

1. If the task has no GitHub Issue linked in `## 0. 元信息`, do **not** start plan or development. Ask the user to create or link an Issue first.
2. After Plan, use the normalized `.ai/results/<TASK_ID>/plan_result.md` generated by `codex_plan.sh`.
3. After development and tests, write execution summary to `.ai/results/<TASK_ID>/execution_summary.md` and a short `test_result.md` from the latest test log.
4. Post plan / test / delivery results to the linked Issue via `comment_issue_result.sh`.
5. Do **not** close GitHub Issues automatically unless the user explicitly passes `--close` to `update_issue_status.sh`.
6. Do **not** create PRs automatically unless explicitly instructed.
7. Never push, merge, deploy, or modify secrets.

## Safety Rules

- Never modify `.env`, `.env.*`, credential files, webhook URLs, cookies, tokens, licenses, or account data.
- Never print `QYWX_WEBHOOK_URL`, Bot Secret, RQData credentials, or any other secret.
- Never delete or rewrite `data/raw/`, `data/processed/`, `data/parquet/`, or trusted historical artifacts.
- Never treat `validation`, `legacy_reference`, `candidate`, or `failed` data as active input.
- Never create automatic trading, unattended order routing, or signal-to-order execution.
- Never push, merge, release, deploy, or create PRs unless the user separately gives that instruction.
- Never run `codex exec --sandbox danger-full-access` from this workflow.
- If the working tree is dirty before Dev, record it in the approval baseline; stop only when changes overlap the TASK or cannot be distinguished safely.

## Completion Report

Every CodeBuddy task must return:

- Current task status (from status machine).
- Current branch.
- Changed files.
- `git diff --stat`.
- Commands actually run.
- Test results.
- Paths to `.ai/results/<TASK_ID>/execution_summary.md` and `delivery_report_draft.md` if generated.
- Risks and incomplete items.
- Whether manual review is required.
- Files that should be synced to browser GPT.
