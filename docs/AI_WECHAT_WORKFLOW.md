# AI WeChat Workflow

> **V1.1 主流程（canonical）**：[`docs/workflows/ai_delivery_workflow.md`](workflows/ai_delivery_workflow.md)
> **V3 控制平面**：[`docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`](workstation/GITHUB_NATIVE_CONTROL_PLANE.md)
> **任务状态机**：[`docs/workflows/status_machine.md`](workflows/status_machine.md)
> **WorkBuddy 角色**：[`docs/workflows/workbuddy_role.md`](workflows/workbuddy_role.md)

This document defines the **Enterprise WeChat entry** for the safe semi-automatic workflow with WorkBuddy, CodeBuddy, and Codex CLI in the Guiyi Quant repository. For the full V1.1 pipeline, start with `ai_delivery_workflow.md`; this file adds WeChat-specific smoke tests and Gate details.

## Goal

Build a local-first development loop:

```text
GitHub Issue / Draft PR
-> WeChat / Enterprise WeChat
-> WorkBuddy: remote PM, QA, visual acceptance, delivery summary
-> CodeBuddy: Issue-first local remote entrypoint
-> Codex CLI: plan and code execution
-> Git working tree
-> user / Cursor manual review
```

This workflow is semi-automatic. The user remains the gate for development, git operations, deployment, and any real notification smoke.

## Roles

| Tool | Role |
|---|---|
| GPT + GitHub | Requirement analysis, architecture, Issue / TASK / Draft PR creation, external PR Review |
| WorkBuddy | Remote PM, requirement cleanup, QA checklist, visual acceptance, delivery summary; no second task state |
| CodeBuddy | Issue-first Enterprise WeChat remote entrypoint into the local repository |
| Codex CLI | Main local execution agent, called through controlled scripts |
| Cursor | Manual diff review and small hand edits |
| GitHub | Global project control plane |
| Git | Checkpoint and review safety rope |
| User | Final approval for Plan, production writes, merge, deploy, and Issue/PR closure |

WorkBuddy may prepare QA notes and delivery reports from existing Issue / TASK / PR context, but it must not create a duplicate task state or directly change business logic or data-chain code. CodeBuddy may run local commands, but development must start with a read-only Codex plan and an explicit user confirmation.

## Daily Flow

1. The user sends an Issue #N, TASK_ID, PR #N, or idea to WorkBuddy in Enterprise WeChat.
2. WorkBuddy returns:
   - linked Issue / TASK / PR context when available
   - requirement conclusion
   - stage boundary
   - non-goals
   - technical plan
   - QA checklist
   - CodeBuddy execution prompt
   - Codex task prompt only when a TASK does not already exist
3. The user reviews scope and safety.
4. The user sends the approved Issue #N or TASK_ID to CodeBuddy.
5. CodeBuddy resolves the existing TASK and branch; if Issue-first bootstrap is not yet available, it requests TASK_ID and uses the compatibility path:

   ```bash
   scripts/ai/dispatch_task.sh <TASK_ID> plan --json
   ```

6. The user reviews the read-only plan.
7. Only after explicit confirmation, CodeBuddy runs:

   ```bash
   scripts/ai/approve_task.sh --task <TASK_ID>
   scripts/ai/dispatch_task.sh <TASK_ID> dev --json
   scripts/ai/dispatch_task.sh <TASK_ID> test --json
   scripts/ai/dispatch_task.sh <TASK_ID> review --json
   scripts/ai/dispatch_task.sh <TASK_ID> result --json
   ```

8. CodeBuddy returns branch, diff, test, risk summary, and `.ai/results/<TASK_ID>/execution_summary.md`.
9. WorkBuddy can turn that result into a delivery report without creating a second status source.
10. The user or Cursor performs manual review and decides whether to commit, push, or merge.

Remote flow details: [`docs/workstation/REMOTE_DEVELOPMENT.md`](workstation/REMOTE_DEVELOPMENT.md).

## Required Gates

### Gate 1: Read-Only Plan

The first Codex pass must be read-only. It may inspect files and propose work, but it must not edit repository files.

Use:

```bash
scripts/ai/dispatch_task.sh <TASK_ID> plan --json
```

Internally this calls `codex_plan.sh` with read-only sandbox and verifies tracked diff unchanged.

### Gate 2: User Confirmation

Development may start only after the user confirms the plan in plain language. CodeBuddy must not infer approval from a broad request or a background task.

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

## CodeBuddy Enterprise WeChat Smoke

Use this message for the first remote check:

```text
请在 guiyi-quant-workstation 本地仓库执行只读检查，不要修改任何文件。

请运行：
1. pwd
2. git rev-parse --show-toplevel
3. git status --short --branch
4. codex --version
5. codebuddy --version
6. scripts/ai/codex_plan.sh prompts/codex-readonly-plan.md

完成后只返回：
- 当前目录
- git root
- 分支和工作区状态
- Codex / CodeBuddy 版本
- plan 输出文件路径
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
- `docs/workstation/GITHUB_NATIVE_V3_BASELINE.md`
- `docs/workstation/ROUTING_POLICY.md`
- `docs/delivery_checklist.md`
- `prompts/workbuddy-delivery-team.md`
- `prompts/codebuddy-execution.md`
- `prompts/codex-readonly-plan.md`
- `scripts/ai/dispatch_task.sh`
- `scripts/ai/make_delivery_summary.sh`
