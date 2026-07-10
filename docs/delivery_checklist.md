# AI Delivery Checklist

Use this checklist after any CodeBuddy or Codex-assisted task.

## Before Development

- [ ] Confirm the task has a written prompt.
- [ ] Confirm `AGENTS.md`, `CODEBUDDY.md`, `docs/CODEX_HANDOFF.md`, and `tasks/current.md` were read.
- [ ] Confirm `git status --short --branch` was checked.
- [ ] Confirm the first Codex pass was read-only.
- [ ] Confirm the user explicitly approved development.
- [ ] Confirm a dedicated `codex/` or `feature/` branch was used.

## Safety Checks

- [ ] `.env`, secrets, tokens, webhook URLs, cookies, and credentials were not touched.
- [ ] `data/raw/`, `data/processed/`, and `data/parquet/` were not deleted or rewritten.
- [ ] No automatic trading, order draft, or unattended execution logic was introduced.
- [ ] No automatic push, merge, release, deployment, or PR was performed.
- [ ] Any Enterprise WeChat behavior is preview, dry-run, or separately authorized.

## Verification

- [ ] `git diff --check` passed.
- [ ] Shell scripts pass `bash -n` when scripts changed.
- [ ] Targeted backend tests were run when backend changed.
- [ ] Frontend build or targeted frontend tests were run when frontend changed.
- [ ] Skipped tests have explicit reasons.
- [ ] `git diff --stat` was reviewed.

## Delivery Report

The final report must include:

- Branch name.
- Changed files.
- Key logic changes.
- Commands run.
- Test result.
- Risks and incomplete items.
- Manual checks required.
- Whether a new Codex session is recommended.
- Whether Plan mode is recommended for the next task.

## Browser GPT Sync Files

For this AI workflow foundation, sync:

- `AGENTS.md`
- `CODEBUDDY.md`
- `docs/AGENT_WORKFLOW.md`
- `docs/AI_WECHAT_WORKFLOW.md`
- `docs/delivery_checklist.md`
- `prompts/workbuddy-delivery-team.md`
- `prompts/codebuddy-execution.md`
- `prompts/codex-readonly-plan.md`
- `scripts/ai/codex_plan.sh`
- `scripts/ai/codex_dev.sh`
- `scripts/ai/run_tests.sh`

For normal project stages, also sync the current stage bundle:

- `tasks/current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
