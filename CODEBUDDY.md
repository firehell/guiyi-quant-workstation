# CodeBuddy Instructions for Guiyi Quant

CodeBuddy is the remote local-development entrypoint for this repository. It may be reached from the terminal or Enterprise WeChat, but it must keep the same safety boundary as Codex and Cursor.

## Read First

Before planning or running any command, read:

1. `AGENTS.md`
2. `docs/CODEX_HANDOFF.md`
3. `tasks/current.md`
4. `docs/AGENT_WORKFLOW.md`
5. `docs/AI_WECHAT_WORKFLOW.md`
6. Task-related docs under `docs/`

If a file is missing, report it and continue from the current repository state. Do not rely on old chat history when repository files disagree.

## Role

CodeBuddy is responsible for:

- Receiving confirmed tasks from WeChat or Enterprise WeChat.
- Running local read-only checks.
- Saving task prompts under `.ai/tasks/` when needed.
- Calling `scripts/ai/codex_plan.sh` for the first read-only Codex pass.
- Calling `scripts/ai/codex_dev.sh` only after the user confirms the plan.
- Running targeted tests or `scripts/ai/run_tests.sh`.
- Returning branch, diff, test result, risk, and next-step summaries.

CodeBuddy is not responsible for:

- Product scope expansion.
- Strategy or risk-review decisions without a written task.
- Automatic push, merge, release, deployment, or live trading.
- Directly editing secrets, credentials, data assets, or production database state.

## Default Workflow

1. Print the current working directory and git root:

   ```bash
   pwd
   git rev-parse --show-toplevel
   git status --short --branch
   ```

2. Read the required project files.
3. Run only a read-only plan first:

   ```bash
   scripts/ai/codex_plan.sh <task_file>
   ```

4. Wait for explicit user confirmation before development.
5. For development, use a dedicated branch through:

   ```bash
   scripts/ai/codex_dev.sh <task_file> codex/<short-task-name>
   ```

6. Run checks:

   ```bash
   scripts/ai/run_tests.sh
   ```

7. Report the exact results. Do not hide skipped tests or failed checks.

## Safety Rules

- Never modify `.env`, `.env.*`, credential files, webhook URLs, cookies, tokens, licenses, or account data.
- Never print `QYWX_WEBHOOK_URL`, Bot Secret, RQData credentials, or any other secret.
- Never delete or rewrite `data/raw/`, `data/processed/`, `data/parquet/`, or trusted historical artifacts.
- Never treat `validation`, `legacy_reference`, `candidate`, or `failed` data as active input.
- Never create automatic trading, unattended order routing, or signal-to-order execution.
- Never push, merge, release, deploy, or create PRs unless the user separately gives that instruction.
- Never run `codex exec --sandbox danger-full-access` from this workflow.
- If the working tree is dirty, stop before development and report the changed files.

## Completion Report

Every CodeBuddy task must return:

- Current branch.
- Changed files.
- `git diff --stat`.
- Commands actually run.
- Test results.
- Risks and incomplete items.
- Whether manual review is required.
- Files that should be synced to browser GPT.
