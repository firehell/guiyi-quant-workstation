---
name: lean-matrix-ai-team
description: Route Guiyi tasks into a minimal reviewed AI team. Use only when a user asks to use the lean matrix team, generate a Task Charter, select or route experts, coordinate implementation and independent review, or organize a Guiyi task through this model.
---

# Lean Matrix AI Team

Create one bounded, independently testable Task Charter. This skill does not replace canonical sources or Gatekeepers, and it adds no control plane. It does not merge main, does not promote Runtime, does not write real data, and does not send real notifications.

## Workflow

1. Read the applicable current facts before choosing a target: `STATUS.md`, `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/DEVELOPMENT.md`, the active task canonical, relevant Issue/PR, and exact Git branch/worktree facts. Stop on conflicts; do not guess or change the active target.
2. Perform a value and complexity check. State one independently testable goal, the Lane, allowed paths, forbidden paths, acceptance, and any external Gates.
3. Prepare schema-v1 JSON, then run:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py charter --input - --format markdown
   ```

   The CLI is advisory and stdout-only: it creates no worktree, makes no repository or external change, and does not replace `task-worktree.sh` or the GitHub workflow.
4. Freeze the Charter before using the existing `task-worktree.sh` and GitHub workflow. Do not duplicate either tool or expand task state.
5. Route the minimum team using [roles.md](references/roles.md) and [routing.md](references/routing.md). Assign at most two specialists; split a task with three or more domains. Use separate implementer and reviewer contexts. Keep quant research and backtest audit in separate contexts when both are needed.
6. Let code, tests, and independent review proceed only within existing permissions. Preserve human Gates for real data/DB, strategy/backtest semantics, notifications, live, main/release/tag, Runtime, deletion, candidate promotion, and GitHub rules.
7. After three failed implementation-validation-review rounds, stop. Report verified facts, attempts, the blocker, and the decision needed. Do not use another round to bypass a Gate.
8. Use [task-charter.md](assets/task-charter.md) and [stage-report.md](assets/stage-report.md) to distinguish code, tests, CI, independent review, real Gate, release, and Runtime status exactly.

## Output discipline

Keep the Charter and reports traceable to current canonical sources and exact heads. A passed test, CI run, or review never authorizes a real Gate, release, or Runtime action.
