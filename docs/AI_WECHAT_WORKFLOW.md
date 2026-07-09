# AI WeChat Workflow

> **V1.1 主流程（canonical）**：[`docs/workflows/ai_delivery_workflow.md`](workflows/ai_delivery_workflow.md)
> **任务状态机**：[`docs/workflows/status_machine.md`](workflows/status_machine.md)
> **WorkBuddy 角色**：[`docs/workflows/workbuddy_role.md`](workflows/workbuddy_role.md)

This document defines the **Enterprise WeChat entry** for the safe semi-automatic workflow with WorkBuddy, CodeBuddy, and Codex CLI in the Guiyi Quant repository. For the full V1.1 pipeline, start with `ai_delivery_workflow.md`; this file adds WeChat-specific smoke tests and Gate details.

## Goal

Build a local-first development loop:

```text
WeChat / Enterprise WeChat
-> WorkBuddy: product framing, task breakdown, QA, delivery report
-> CodeBuddy: local remote entrypoint
-> Codex CLI: plan and code execution
-> Git working tree
-> user / Cursor manual review
```

This workflow is semi-automatic. The user remains the gate for development, git operations, deployment, and any real notification smoke.

## Roles

| Tool | Role |
|---|---|
| WorkBuddy | Product framing, requirement cleanup, QA checklist, delivery report, visible UI bug triage |
| CodeBuddy | Enterprise WeChat remote entrypoint into the local repository |
| Codex CLI | Main local execution agent, called through controlled scripts |
| Cursor | Manual diff review and small hand edits |
| Git | Checkpoint and review safety rope |
| Browser GPT | Architecture, data, strategy, and risk review from synced source files |

WorkBuddy may prepare prompts and delivery reports, but it must not directly change business logic or data-chain code. CodeBuddy may run local commands, but development must start with a read-only Codex plan and an explicit user confirmation.

## Daily Flow

1. The user sends an idea or issue to WorkBuddy in Enterprise WeChat.
2. WorkBuddy returns:
   - requirement conclusion
   - stage boundary
   - non-goals
   - technical plan
   - QA checklist
   - CodeBuddy execution prompt
   - Codex task prompt
3. The user reviews scope and safety.
4. The user sends the approved task to CodeBuddy.
5. CodeBuddy saves the task under `.ai/tasks/` if needed and runs:

   ```bash
   scripts/ai/codex_plan.sh .ai/tasks/<task>.md
   ```

6. The user reviews the read-only plan.
7. Only after explicit confirmation, CodeBuddy runs:

   ```bash
   scripts/ai/codex_dev.sh .ai/tasks/<task>.md codex/<task-branch>
   ```

8. CodeBuddy runs targeted checks or:

   ```bash
   scripts/ai/run_tests.sh
   ```

9. CodeBuddy returns branch, diff, test, and risk summary.
10. WorkBuddy can turn that result into a delivery report.
11. The user or Cursor performs manual review and decides whether to commit, push, or merge.

## Required Gates

### Gate 1: Read-Only Plan

The first Codex pass must be read-only. It may inspect files and propose work, but it must not edit repository files.

Use:

```bash
scripts/ai/codex_plan.sh <task_file>
```

### Gate 2: User Confirmation

Development may start only after the user confirms the plan in plain language. CodeBuddy must not infer approval from a broad request or a background task.

### Gate 3: Dedicated Branch

Development must happen on a dedicated branch. Branch names should use:

```text
codex/<short-task-name>
feature/<short-task-name>
```

### Gate 4: No Automatic Git Publishing

This workflow must not push, merge, tag, release, deploy, or create PRs automatically.

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
- `docs/AI_WECHAT_WORKFLOW.md`
- `docs/delivery_checklist.md`
- `prompts/workbuddy-delivery-team.md`
- `prompts/codebuddy-execution.md`
- `prompts/codex-readonly-plan.md`
- `scripts/ai/codex_plan.sh`
- `scripts/ai/codex_dev.sh`
- `scripts/ai/run_tests.sh`
- `scripts/ai/collect_result.sh`
- `scripts/ai/make_delivery_summary.sh`
