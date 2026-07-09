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
9. The task file for the current job (`.ai/tasks/<TASK_ID>.md` or user-specified path)

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

Follow [`docs/workflows/ai_delivery_workflow.md`](docs/workflows/ai_delivery_workflow.md). Summary:

1. Print the current working directory and git root:

   ```bash
   pwd
   git rev-parse --show-toplevel
   git status --short --branch
   ```

2. Read the task file and required project files.
3. **Issue Gate**: verify `## 0. 元信息` → `GitHub Issue` is filled (e.g. `#12`).
   - If empty: **stop**. Ask the user to run `create_issue_from_task.sh` and `link_task_issue.sh` first.
   - If filled: continue.
4. Update task status toward `REQUIREMENT_READY` / confirm ready for plan.
5. Run only a read-only plan first:

   ```bash
   TASK_ID=<TASK_ID> scripts/ai/codex_plan.sh <task_file>
   ```

6. Copy the latest plan output for Issue trace:

   ```bash
   cp .ai/results/<TASK_ID>/codex_plan_*.md .ai/results/<TASK_ID>/plan_result.md
   scripts/ai/comment_issue_result.sh <TASK_ID> plan <task_file>
   scripts/ai/update_issue_status.sh <TASK_ID> PLAN_READY <task_file>
   ```

7. Update task status to `PLAN_READY`. Wait for explicit user confirmation.
8. After approval, update status to `APPROVED_DEV` and develop on a dedicated branch:

   ```bash
   scripts/ai/update_issue_status.sh <TASK_ID> APPROVED_DEV <task_file>
   scripts/ai/codex_dev.sh <task_file> codex/<short-task-name>
   ```

9. Update status to `TESTING`. Run checks:

   ```bash
   scripts/ai/update_issue_status.sh <TASK_ID> TESTING <task_file>
   TASK_ID=<TASK_ID> scripts/ai/run_tests.sh
   scripts/ai/collect_result.sh <TASK_ID> <task_file>
   scripts/ai/make_delivery_summary.sh <TASK_ID> <task_file>
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
- `codex_dev.sh`: workspace-write allowed; no push / merge / deploy.
- `collect_result.sh`: mandatory after dev; does not auto-fix or commit.
- `make_delivery_summary.sh`: optional but recommended before WorkBuddy delivery report.
- `create_issue_from_task.sh`: create GitHub Issue from TASK file; does not modify code.
- `link_task_issue.sh`: write Issue number into TASK meta section.
- `comment_issue_result.sh`: post plan / test / delivery results as Issue comments.
- `update_issue_status.sh`: sync `status/*` labels; does not close Issue unless `--close` is passed.

## GitHub Issue Trace

For every TASK:

1. If the task has no GitHub Issue linked in `## 0. 元信息`, do **not** start plan or development. Ask the user to create or link an Issue first.
2. After plan, write the plan result to `.ai/results/<TASK_ID>/plan_result.md` (copy from latest `codex_plan_*.md`).
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
- If the working tree is dirty before dev, stop and report the changed files.

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
