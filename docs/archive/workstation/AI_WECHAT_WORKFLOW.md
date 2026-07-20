# AI WeChat Workflow

> **WorkBuddy Unified V3 主流程（canonical）**：[`docs/workflows/ai_delivery_workflow.md`](workflows/ai_delivery_workflow.md)
> **V3 控制平面**：[`docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`](workstation/GITHUB_NATIVE_CONTROL_PLANE.md)
> **任务状态机**：[`docs/workflows/status_machine.md`](workflows/status_machine.md)
> **WorkBuddy 角色**：[`docs/workflows/workbuddy_role.md`](workflows/workbuddy_role.md)

This document defines the **Enterprise WeChat entry** for the safe semi-automatic workflow with WorkBuddy Unified V3 and Codex in the Guiyi Quant repository. For the full delivery pipeline, start with `ai_delivery_workflow.md`; this file adds WeChat-specific command and Gate details.

## Goal

Build a local-first development loop:

```text
GitHub Issue / Draft PR
-> WeChat / Enterprise WeChat
-> WorkBuddy: remote PM, QA, visual acceptance, delivery summary, fixed command facade
-> Codex CLI: plan and code execution through dispatcher
-> Git working tree
-> user / Cursor manual review
```

This workflow is semi-automatic. The user remains the gate for development, git operations, deployment, and any real notification smoke.

## Roles

| Tool | Role |
|---|---|
| GPT + GitHub | Requirement analysis, architecture, Issue / TASK / Draft PR creation, external PR Review |
| WorkBuddy | Remote PM, requirement cleanup, QA checklist, visual acceptance, delivery summary, fixed command facade; no second task state |
| CodeBuddy | Compatibility-only Issue-first remote entrypoint for old tasks; no new orchestration features |
| Codex CLI | Main local execution agent, called through dispatcher |
| Cursor | Manual diff review and small hand edits |
| GitHub | Global project control plane |
| Git | Checkpoint and review safety rope |
| User | Final approval for Plan, production writes, merge, deploy, and Issue/PR closure |

WorkBuddy may prepare QA notes and delivery reports from existing Issue / TASK / PR context, and may call `scripts/ai/workbuddy_task.sh` fixed commands. It must not create a duplicate task state, run arbitrary shell, infer approval, or directly change business logic or data-chain code. Development must start with a read-only plan and explicit user confirmation.

## Daily Commands

Enterprise WeChat defaults to Issue / PR numbers. The user should not paste full TASK files or result bundles into WeChat:

| Command | Owner | Meaning |
|---|---|---|
| `analyze --issue #123` | WorkBuddy facade | Resolve Issue/TASK and route only. |
| `bootstrap --issue #123` | WorkBuddy facade | Bootstrap Issue #123 through existing controlled script. |
| `plan --issue #123` | WorkBuddy facade | Run read-only plan through dispatcher. |
| `approve --issue #123 --confirm-user-approval` | WorkBuddy facade | Bind explicit user approval to the resolved TASK and current plan. |
| `dev --issue #123` | WorkBuddy facade | Run approved dev through dispatcher gates. |
| `status --issue #123` | WorkBuddy facade | Return Issue, TASK, Draft PR, result, and current Gate status. |
| `result --issue #123` | WorkBuddy facade | Run result stage. |
| `delivery --task TASK_ID` | WorkBuddy facade | Generate delivery input; does not imply acceptance. |
| `sync-pr --task TASK_ID --pr 123 --confirm-github-write` | WorkBuddy facade | Sync redacted PR summary when explicitly confirmed. |
| `record-external-review --task TASK_ID --pr 123` | WorkBuddy facade | Record real GitHub PR review status for the external GPT review gate. |

TASK_ID commands remain compatible, but the remote operator should return the linked Issue / Draft PR and recommend Issue-first commands for later stages.

## Daily Flow

1. The user sends an Issue #N, PR #N, or idea to WorkBuddy in Enterprise WeChat.
2. WorkBuddy returns:
   - linked Issue / TASK / PR context when available
   - requirement conclusion
   - stage boundary
   - non-goals
   - technical plan
   - QA checklist
   - WorkBuddy command sequence and Codex execution boundary
   - request to create the Issue in GPT + GitHub when no Issue exists
3. The user reviews scope and safety.
4. The user sends a fixed WorkBuddy command.
5. WorkBuddy facade runs existing controlled scripts:

   ```bash
   scripts/ai/workbuddy_task.sh bootstrap --issue #N
   scripts/ai/workbuddy_task.sh plan --issue #N
   ```

6. The user reviews the read-only plan.
7. Only after explicit confirmation, the user sends approve/dev commands:

   ```bash
   scripts/ai/workbuddy_task.sh approve --issue #N --confirm-user-approval
   scripts/ai/workbuddy_task.sh dev --issue #N
   scripts/ai/workbuddy_task.sh test --issue #N
   scripts/ai/workbuddy_task.sh review --issue #N
   scripts/ai/workbuddy_task.sh result --issue #N
   ```

8. The WorkBuddy facade / dispatcher returns Issue, Draft PR, CI/check status, branch, diff, test, risk summary, result summary links, and `.ai/results/<TASK_ID>/execution_summary.md`.
9. WorkBuddy reads Issue / Draft PR / result summary and turns that into PM or delivery reporting without creating a second status source.
10. The user or Cursor performs manual review and decides whether to commit, push, or merge.

Remote flow details: [`docs/workstation/REMOTE_DEVELOPMENT.md`](workstation/REMOTE_DEVELOPMENT.md).

## Required Gates

### Gate 1: Read-Only Plan

The first Codex pass must be read-only. It may inspect files and propose work, but it must not edit repository files.

Use:

```bash
scripts/ai/dispatch_task.sh '#N' plan --json
```

Internally this calls `codex_plan.sh` with read-only sandbox and verifies tracked diff unchanged.

### Gate 2: User Confirmation

Development may start only after the user confirms the plan in plain language. WorkBuddy and any CodeBuddy compatibility path must not infer approval from a broad request or a background task.

### Gate 3: Dedicated Branch

Development must happen on a dedicated branch. Branch names should use:

```text
codex/<short-task-name>
feature/<short-task-name>
```

### Gate 4: No Automatic Git Publishing

This workflow must not write `main`, push, merge, tag, release, deploy, create PRs, or close Issues automatically unless the user explicitly authorizes that specific GitHub operation.

## Forbidden Actions

- Automatic trading or unattended order execution.
- Writing or printing secrets, including `QYWX_WEBHOOK_URL`, CodeBuddy Bot Secret, WorkBuddy Bot Secret, RQData credentials, cookies, or license text.
- Editing `.env` or `.env.*`.
- Deleting or rewriting trusted historical data under `data/raw/`, `data/processed/`, or `data/parquet/`.
- Promoting `validation`, `legacy_reference`, `candidate`, or `failed` data to active input.
- Running real Enterprise WeChat notification smoke without a separate explicit instruction.
- Running `codex exec --sandbox danger-full-access`.
- Treating `message=started`, a background PID, or a wrapper exit code as proof that a stage succeeded.
- Requiring the user to paste complete TASK files, full logs, `.ai/results` contents, `.env`, secrets, or data samples into WeChat.
- Creating a second task status outside GitHub Issue / TASK / Draft PR.

## WorkBuddy Enterprise WeChat Smoke

Use this message for the first remote check:

```text
请在 guiyi-quant-workstation 本地仓库执行只读检查，不要修改任何文件。

请运行：
1. pwd
2. git rev-parse --show-toplevel
3. git status --short --branch
4. codex --version
5. scripts/ai/workbuddy_task.sh status --task <TASK_ID>

完成后只返回：
- 当前目录
- git root
- 分支和工作区状态
- Codex 版本
- Issue / TASK / PR / Gate 状态
- 是否有文件被修改
```

## Failure Handling

If a remote run appears stuck or ambiguous, verify:

- current working directory
- git root
- branch
- dirty files
- command exit code
- `.ai/logs/` output
- `.ai/results/` output

Do not treat a background start message as success. The proof is the final result file, command output, and git status.

## Browser GPT Sync Set

After workflow changes, sync these files to browser GPT when asking for review:

- `AGENTS.md`
- `CODEBUDDY.md`
- `docs/AGENT_WORKFLOW.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/status_machine.md`
- `docs/tasks/TASK_TEMPLATE.md`
- `docs/workstation/REMOTE_DEVELOPMENT.md`
- `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`
- `docs/workstation/WORKBUDDY_UNIFIED_V3.md`
- `docs/workstation/WORKSTATION_DOCUMENT_MAP.md`
- `docs/workstation/ROUTING_POLICY.md`
- `docs/delivery_checklist.md`
- `prompts/workbuddy-delivery-team.md`
- `prompts/workbuddy-workstation-orchestrator.md`
- `prompts/workbuddy-codex-execution.md`
- `prompts/workbuddy-delivery-report.md`
- `CODEBUDDY.md`（compatibility-only 参考）
- `prompts/gpt-github-pr-review.md`
- `prompts/codex-readonly-plan.md`
- `scripts/ai/dispatch_task.sh`
- `scripts/ai/workbuddy_task.sh`
- `scripts/ai/bootstrap_github_task.sh`
- `scripts/ai/make_delivery_summary.sh`
