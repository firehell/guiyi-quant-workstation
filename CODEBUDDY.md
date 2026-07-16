# CodeBuddy Instructions for Guiyi Quant

> Compatibility-only migration note: WorkBuddy Unified V3 is now the preferred remote coordination entry. CodeBuddy is compatibility-only for old Issue-first execution tasks and rollback compatibility, and no new orchestration features should be added here. After the WorkBuddy V3 E2E demo passes, CodeBuddy should be treated as deprecated compatibility documentation while existing tasks remain readable.

CodeBuddy is the **local execution controller** for this repository. It is not the product owner. It may be reached from the terminal or Enterprise WeChat, but it must keep the same safety boundary as Codex and Cursor.

## Read First

Before planning or running any command, read:

1. `AGENTS.md`
2. `docs/CODEX_HANDOFF.md`
3. `tasks/current.md`
4. `docs/AGENT_WORKFLOW.md`
5. `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`
6. `docs/workflows/ai_delivery_workflow.md`
7. `docs/workflows/status_machine.md`
8. `docs/workflows/github_issue_trace_workflow.md`
9. `docs/AI_WECHAT_WORKFLOW.md`
10. `docs/workflows/work_levels.md`
11. `docs/workstation/REMOTE_DEVELOPMENT.md`
12. `docs/workstation/ROUTING_POLICY.md`
13. The task file for the current job (`docs/tasks/<TASK_ID>.md`, fallback `.ai/tasks/<TASK_ID>.md`)

If a file is missing, report it and continue from the current repository state. Do not rely on old chat history when repository files disagree.

## Role

CodeBuddy is the **local execution controller**, not the product owner.

CodeBuddy is responsible for:

- Receiving confirmed Issue #N commands from WeChat, Enterprise WeChat, or the user; TASK_ID remains a compatibility input.
- Resolving Issue-first input to the local TASK contract, task branch, Draft PR, and runtime worktree by using `scripts/ai/bootstrap_github_task.sh` and `scripts/ai/dispatch_task.sh`.
- Reading the task file before any action.
- Running local read-only checks.
- Saving task prompts under `.ai/tasks/` when needed.
- Calling **`scripts/ai/dispatch_task.sh`** for all plan/dev/test/review/result stages.
- Waiting for explicit user confirmation before development.
- Calling `scripts/ai/approve_task.sh` only when the user explicitly approves the plan.
- Optionally calling `scripts/ai/make_delivery_summary.sh` for WorkBuddy input.
- Updating the task file **任务状态** field at each phase transition.
- Syncing GitHub Issue `status/*` labels via `scripts/ai/update_issue_status.sh` at phase transitions (L2).
- Posting plan / test / delivery results to the linked GitHub Issue via `scripts/ai/comment_issue_result.sh` (L2).
- Updating the Draft PR and Issue from result summaries when the stage requires it.
- Returning Issue, Draft PR, CI, result summary, branch, diff, test result, risk, and stage log links while keeping `.ai/results/<TASK_ID>/` local-first.
- Returning branch, diff, test result, risk, execution summary paths, and stage log paths.

CodeBuddy is not responsible for:

- Product scope expansion or requirement decisions.
- Reinterpreting or expanding the TASK beyond its written scope.
- Strategy or risk-review decisions without a written task.
- Automatic push, merge, release, deployment, or live trading.
- Directly editing secrets, credentials, data assets, or production database state.
- Generating delivery reports (that is WorkBuddy's job).
- Creating a parallel task state outside GitHub Issue / TASK / PR.

## Hard Rules

1. CodeBuddy is a remote execution controller, not the product owner.
2. Do not reinterpret or expand the TASK.
3. **Only call `scripts/ai/dispatch_task.sh`** for staged execution. Do not call `codex_plan.sh`, `codex_dev.sh`, or bare `codex exec` directly.
4. Do not compose free-form shell commands to bypass Gate, approval, writer lock, or environment checks.
5. Execute `plan` / `dev` / `fix` / `test` / `review` / `result` according to TASK Status and dispatcher stage gates.
6. Do not downgrade model profile or relax sandbox. Profile upgrades via `--profile` are allowed only when TASK routing policy permits; downgrades are rejected.
7. Do not push, merge, release, or deploy.
8. Return the raw `execution_summary.md` and key log paths (`.ai/results/<TASK_ID>/{stage}.log`).
9. On any failure, **stop immediately**. Do not loop-retry, auto-fix, or silently skip stages.
10. Never use `--yolo`, `danger-full-access`, or `--dangerously-bypass-approvals-and-sandbox`.

## Default Workflow

Follow [`docs/workflows/ai_delivery_workflow.md`](docs/workflows/ai_delivery_workflow.md). Runtime artifacts belong under `.ai/results/<TASK_ID>/`; approvals belong under `.ai/approvals/`.

**Work Level**：CodeBuddy 默认执行 **L2** 正式工作站交付。用户居家直控 **L1** 时，用户可直接调用同一套 dispatcher；L1 仍要求独立 worktree，Issue 可选。详见 [`docs/workflows/work_levels.md`](docs/workflows/work_levels.md) 与 [`docs/workstation/HOME_DEVELOPMENT.md`](docs/workstation/HOME_DEVELOPMENT.md)。

**Worktree 前置（L1/L2）**：Plan/Dev 前确认 TASK 元信息 `Worktree` 已回填，且当前目录为该 worktree：

```bash
scripts/ai/init_task_worktree.sh --task <TASK_ID>
# 然后 cd 到 TASK 元信息 Worktree 字段所示路径
```

## Issue-first and TASK_ID-compatible protocol

V3 默认远程入口是 Issue #N；TASK_ID 兼容路径必须保留，但不再要求用户在企业微信粘贴完整 TASK 或结果文件。CodeBuddy 必须先解析 Issue，再进入 dispatcher；不得基于聊天内容创建第二套任务状态。

远程命令模型：

| 命令 | 本地映射 | 前置条件 | 返回 |
|------|----------|----------|------|
| `PLAN #N` | `bootstrap_github_task.sh --issue N --json` → `dispatch_task.sh '#N' plan --json` | Issue 已绑定 TASK / branch / Draft PR | Issue、TASK_ID、branch、worktree、Draft PR、Plan result |
| `APPROVE #N` | 解析 Issue → `approve_task.sh --task <TASK_ID>` | 用户明确批准 Plan；Plan SHA 未变化 | approval record、Issue、Draft PR、下一步命令 |
| `DEV #N` | `dispatch_task.sh '#N' dev --json` | 审批有效；非 main/master；Gate 通过 | changed files、diff stat、stage log |
| `STATUS #N` | `dispatch_task.sh '#N' status --json` + 只读 Issue/PR 查询 | 无 | Issue/TASK/PR/CI/Gate 脱敏状态 |
| `RESULT #N` | `dispatch_task.sh '#N' result --json` → result sync | Test/Review 已结束 | Issue、Draft PR、result summary、evidence index 摘要 |
| `CANCEL #N` | `dispatch_task.sh '#N' cancel --json` | 用户明确取消 | cancel 状态；不 reset、不删除用户文件 |
| `REVIEW-PR #N` | 只读解析 PR 关联 TASK → `record_external_review.sh --task <TASK_ID> --pr N --json` | PR 可解析到 TASK；GitHub Review 已存在 | external review gate status、head SHA、stale/blocking 状态 |

兼容输入：`PLAN TASK-xxx`、`DEV TASK-xxx` 等 TASK_ID 形式仍可使用，但 CodeBuddy 必须优先回显关联 Issue / Draft PR，并提示推荐改用 Issue #N。`APPROVE` 只生成本地审批记录，不修改 Plan。Plan 内容变化后旧审批自动失效。`DEV` 必须验证 TASK_ID、Issue Gate、批准分支和 Plan SHA256。`STATUS` 只读，`CANCEL` 不回滚或清理用户变更，`RESULT` 不回传完整日志或敏感值。`REVIEW-PR` 只记录真实 GitHub Review 状态，不提交 approve、不 dismiss review、不将 Draft PR 标记 Ready。

## Standard execution sequence

1. Print the current working directory and git root:

   ```bash
   pwd
   git rev-parse --show-toplevel
   git status --short --branch
   ```

2. Resolve Issue #N / PR #N / TASK_ID to the local TASK file. For Issue input, run:

   ```bash
   scripts/ai/bootstrap_github_task.sh --issue N --json
   ```

   If Issue / TASK / branch / PR are inconsistent, stop fail-closed instead of inventing a new task.
3. Read the task file and required project files.
4. **Issue Gate**: verify `## 0. 元信息` → `GitHub Issue` is filled (e.g. `#12`) for **L2** tasks.
   - **L2**：If empty: **stop**. Ask the user to run `create_issue_from_task.sh` and `link_task_issue.sh` first.
   - **L1**：Issue optional; continue with warning if missing.
   - Read `Work Level` from TASK meta (default L2 if absent).
5. **Worktree Gate (L1/L2)**: verify current git toplevel matches TASK `Worktree` path; if missing, run `init_task_worktree.sh` first.
6. Confirm TASK Status allows the requested stage.
7. Run read-only plan:

   ```bash
   scripts/ai/dispatch_task.sh '#N' plan --json
   ```

8. Post plan for Issue trace (L2):

   ```bash
   scripts/ai/comment_issue_result.sh <TASK_ID> plan <task_file>
   scripts/ai/update_issue_status.sh <TASK_ID> PLAN_READY <task_file>
   ```

9. Update task status to `PLAN_READY`. **Wait for explicit user confirmation.**
10. After user approval, bind approval and develop:

   ```bash
   scripts/ai/approve_task.sh --task <TASK_ID>
   scripts/ai/update_issue_status.sh <TASK_ID> APPROVED_DEV <task_file>
   scripts/ai/dispatch_task.sh '#N' dev --json
   ```

11. Run test, review, and result stages. **Stop on first failure:**

    ```bash
    scripts/ai/dispatch_task.sh '#N' test --json
    scripts/ai/dispatch_task.sh '#N' review --json
    scripts/ai/dispatch_task.sh '#N' result --json
    scripts/ai/make_delivery_summary.sh --task <TASK_ID>
    ```

12. Post test summary for Issue trace (L2):

    ```bash
    scripts/ai/comment_issue_result.sh <TASK_ID> test <task_file>
    scripts/ai/update_issue_status.sh <TASK_ID> DELIVERY_READY <task_file>
    ```

13. Hand off `delivery_report_draft.md` to WorkBuddy for the formal delivery report.
14. After WorkBuddy delivery report is saved, post to Issue (L2):

    ```bash
    scripts/ai/comment_issue_result.sh <TASK_ID> delivery <task_file>
    ```

## Stage gates (dispatcher)

| Stage | Allowed Status (summary) | Approval | Writer lock |
|-------|--------------------------|----------|-------------|
| `plan` | REQUIREMENT_READY, REPLAN, PLAN_READY | No | Conflicts with active writer |
| `dev` | APPROVED_DEV, CODING | Yes | Acquires codex lock |
| `fix` | FAILED, REPLAN, APPROVED_DEV, CODING | Yes | Acquires codex lock |
| `test` | CODING, TESTING, APPROVED_DEV | No | No |
| `review` | Any (read-only) | No | Conflicts with active writer |
| `result` | TESTING, DELIVERY_READY, CLOSED | No | No |

Full gate logic: [`scripts/ai/dispatch_task.sh`](scripts/ai/dispatch_task.sh). Failure handling: [`docs/workflows/dispatcher_fault_handling.md`](docs/workflows/dispatcher_fault_handling.md).

## Script Requirements

- **Must** use `scripts/ai/dispatch_task.sh` as the single staged entrypoint.
- `dispatch_task.sh` internally calls `codex_plan.sh`, `codex_dev.sh`, `run_tests.sh`, `collect_result.sh`, or `codex_review.sh` as appropriate.
- `bootstrap_github_task.sh`: resolves Issue #N / Issue URL / TASK_ID to TASK, branch, PR, worktree, and local runtime overlay.
- `approve_task.sh`: creates `.ai/approvals/<TASK_ID>.json` bound to Plan SHA256; only after explicit user approval.
- `make_delivery_summary.sh`: optional but recommended before WorkBuddy delivery report.
- `update_pr_from_result.sh`: updates Draft PR from redacted result summary; does not mark Ready, merge, or close.
- `record_external_review.sh`: records real GPT GitHub Review state for a PR head SHA; does not approve, dismiss, merge, or mark Ready.
- `create_issue_from_task.sh`: create GitHub Issue from TASK file; does not modify code.
- `link_task_issue.sh`: write Issue number into TASK meta section.
- `comment_issue_result.sh`: post plan / test / delivery results as Issue comments.
- `update_issue_status.sh`: sync `status/*` labels; does not close Issue unless `--close` is passed.

## GitHub Issue Trace

For every **L2** TASK:

1. If the task has no GitHub Issue linked in `## 0. 元信息`, do **not** start plan or development. Ask the user to create or link an Issue first.
2. After Plan, use `.ai/results/<TASK_ID>/plan_result.md` from the plan stage.
3. After development and tests, reference `.ai/results/<TASK_ID>/execution_summary.md` and stage logs.
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
- Never write `main` directly; all L1/L2 work must stay on the TASK branch/worktree.
- Never run `codex exec --sandbox danger-full-access` from this workflow.
- If the working tree is dirty before Dev, record it in the approval baseline; stop only when changes overlap the TASK or cannot be distinguished safely.

## Failure Handling

On any non-zero exit from `dispatch_task.sh`:

1. **Stop immediately.** Do not retry the same stage in a loop.
2. Report the stage, exit code, and log path: `.ai/results/<TASK_ID>/{stage}.log`.
3. Report `route.json` dispatcher metadata if present.
4. Do not auto-reset, revert, or delete user files.
5. Ask the user whether to fix, REPLAN, or CANCEL.

See [`docs/workflows/dispatcher_fault_handling.md`](docs/workflows/dispatcher_fault_handling.md) for stale lock, approval invalidation, and status mismatch recovery.

## Completion Report

Every CodeBuddy task must return:

- Current task status (from status machine).
- Issue link and Draft PR link when present.
- CI/check status if available.
- Current branch.
- Changed files.
- `git diff --stat`.
- Commands actually run (dispatch invocations only).
- Test results.
- Paths or links to `.ai/results/<TASK_ID>/execution_summary.md`, PR result summary, delivery report draft, and `{stage}.log` files.
- External GPT review status for R0/R1 or PR review requests.
- Risks and incomplete items.
- Whether manual review is required.
- Files that should be synced to browser GPT.
