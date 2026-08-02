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
4. Freeze the Charter, then render its version-one Execution Plan when an exact local base is required:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py plan --charter - --format markdown
   ```

   The plan command uses `GIT_OPTIONAL_LOCKS=0` and may run only
   `git -c core.fsmonitor=false rev-parse --verify origin/develop^{commit}`. It does not fetch,
   does not call GitHub or the network, never executes a transition, and writes no receipt or repository file.
   Its transition list is descriptive only.
5. Reconstruct local state and request the unique next proposal without changing Git or runtime evidence:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py observe --plan <plan.json> --format json
   python3 scripts/engineering/lean_matrix_team.py next --plan <plan.json> --format json
   ```

   `observe` and `next` are read-only. They use local Git/worktree facts, do not fetch, and do not
   inspect GitHub. Runtime evidence under `.ai/lean-matrix/<plan-digest>/` is ignored recovery
   evidence, never editable canonical task state. Run these commands from the clean surviving
   `develop` controller checkout. The state digest binds the task HEAD, index, changed path set,
   changed working-tree bytes, and Git-effective file mode; content or chmod drift invalidates it.
6. Apply at most one transition by binding the proposal and the immediately re-observed state:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py apply \
     --plan <plan.json> \
     --expected-transition <transition-id> \
     --expected-state-digest <sha256:...> \
     --format json \
     --apply
   ```

   Without explicit `--apply`, this command is a read-only dry-run. With it, only a Lane 1/2 plan
   with no external Gate may delegate one transition to the existing `task-worktree.sh` entrypoint:
   `task-create`, `local-integrate-to-draft-pr`, or cleanup after dual-develop ancestry is observed.
   Lane is inferred at least privilege from the frozen dispatch and scope. Explicit forbidden paths
   override allowed paths, and changes to this controller or its workflow policy require manual
   integration instead of generic apply. Apply claims its transition atomically before execution;
   an interrupted or concurrent attempt remains blocked for inspection. The executed entrypoint is
   the absolute non-symlink file in the controller checkout, while task Git operations keep the exact
   task cwd; recovery command digests bind both argv and cwd.
   Lane 3 generic apply is always blocked. `develop-merge`, PR/CI/Review inspection, and uncertain
   remote recovery remain AI-TEAM-007 or human work.
7. Use the existing `task-worktree.sh` and GitHub workflow only after the Charter is frozen. Do not duplicate either tool or expand task state.
8. Route the minimum team using [roles.md](references/roles.md) and [routing.md](references/routing.md). Assign at most two specialists; split a task with three or more domains. Use separate implementer and reviewer contexts. Keep quant research and backtest audit in separate contexts when both are needed.
9. Let code, tests, and independent review proceed only within existing permissions. Preserve human Gates for real data/DB, strategy/backtest semantics, notifications, live, main/release/tag, Runtime, deletion, candidate promotion, and GitHub rules.
10. After three failed implementation-validation-review rounds, stop. Report verified facts, attempts, the blocker, and the decision needed. Do not use another round to bypass a Gate.
11. Use [task-charter.md](assets/task-charter.md) and [stage-report.md](assets/stage-report.md) to distinguish code, tests, CI, independent review, real Gate, release, and Runtime status exactly.

## Output discipline

Keep the Charter and reports traceable to current canonical sources and exact heads. A passed test, CI run, or review never authorizes a real Gate, release, or Runtime action.

For controlled trials and historical retrospectives, use [trial-report.md](assets/trial-report.md); metrics must never be estimated or inferred from conversation memory.
