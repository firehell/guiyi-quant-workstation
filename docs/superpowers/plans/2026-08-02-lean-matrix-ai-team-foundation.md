# Lean Matrix AI Team Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add one repository-level lean-matrix orchestration skill and a deterministic read-only CLI that validates task inputs, routes the minimum team, and renders a Task Charter.

**Architecture:** Keep judgment and orchestration in a concise repository skill. Put deterministic schema/path/lane validation and Markdown/JSON rendering in one pure Python CLI that reuses `task_workflow.py` and has no Git, GitHub, network, subprocess, or filesystem-write behavior.

**Tech Stack:** Markdown Agent Skills, Python 3.13 standard library, pytest, existing engineering gates.

## Global Constraints

- Work only in `feature/AI-TEAM-001-lean-matrix-foundation` at `/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-001-lean-matrix-foundation`, based on `origin/develop@6ead11f1` or a verified descendant.
- Do not modify `main`, the local `develop` checkout, detached Runtime, real data/DB, notifications, release/tag, or the existing Task 05 worktree.
- Do not modify `AGENTS.md`, `STATUS.md`, `DECISIONS.md`, `PROJECT_SOURCE.md`, or Task 05 business/canonical files.
- The CLI reads JSON and writes only stdout/stderr. It must not run Git/GitHub/network/subprocess commands or write files.
- The skill shapes Task Charter and routing output; existing canonical, scripts, CI, approval packets, receipts, and user Gates remain authoritative.

---

### Task 1: Align the design baseline

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`

- [ ] Replace stale Task 04 statements with the merged closeout fact and mark Task 04 as a retrospective example.
- [ ] State that the existing Task 05 worktree is not adopted or modified by this implementation.
- [ ] Record the owner-approved bounded exception: Phase 1 includes a read-only Task Charter CLI, while worktree/PR/CI/merge orchestration remains later-phase and continues using existing tools.
- [ ] Run `git diff --check` and a targeted stale-reference scan.

### Task 2: Implement the read-only Task Charter CLI with TDD

**Files:**
- Create: `scripts/engineering/lean_matrix_team.py`
- Create: `tests/engineering/test_lean_matrix_team.py`

**Interface:**
- Command: `python3 scripts/engineering/lean_matrix_team.py charter --input <path|-> --format <markdown|json>`
- Input schema v1 fields: `schema_version`, `issue_number`, `task_id`, `kind`, `slug`, `title`, `value`, `goal`, `current_facts`, `lane`, `domains`, `allowed_paths`, `forbidden_paths`, `acceptance`, `external_gates`.
- Output JSON: `schema_version`, `status`, `task`, `dispatch`, `charter_markdown`.
- Errors: stable JSON on stderr with `status=blocked` and `error_type`; exit code 2.

- [ ] Write failing tests for valid Lane 2 Markdown/JSON rendering, Lane 3 quant/backtest routing, specialist overflow, lane/gate mismatch, invalid identifiers/paths/domains, stdin input, and no filesystem writes.
- [ ] Run the tests and confirm failure because the CLI does not exist.
- [ ] Implement the minimum pure-Python CLI; reuse `task_workflow` base path validation for every Lane and its public `classify_paths` policy for Lane 1/2. Lane 3 is plan-only and must not widen or redefine the shared Lane 1/2 automation classifier.
- [ ] Run targeted tests until green and run representative stdin/file smoke commands.

### Task 3: Implement and forward-test the repository skill

**Files:**
- Create: `.agents/skills/lean-matrix-ai-team/SKILL.md`
- Create: `.agents/skills/lean-matrix-ai-team/agents/openai.yaml`
- Create: `.agents/skills/lean-matrix-ai-team/references/roles.md`
- Create: `.agents/skills/lean-matrix-ai-team/references/routing.md`
- Create: `.agents/skills/lean-matrix-ai-team/assets/task-charter.md`
- Create: `.agents/skills/lean-matrix-ai-team/assets/stage-report.md`
- Create: `tests/engineering/test_lean_matrix_skill_policy.py`

- [ ] Use the official `init_skill.py` to scaffold `lean-matrix-ai-team` with references/assets and deterministic UI metadata.
- [ ] Write failing static policy tests for required resources, four base roles, separate implementer/reviewer contexts, maximum two specialists, split-required behavior, three-round stop, CLI invocation, and unchanged external Gates.
- [ ] Implement the concise skill and progressive-disclosure references/templates based on the observed baseline output-shape gaps.
- [ ] Run `quick_validate.py`, static policy tests, and the same three fresh-context pressure scenarios with the skill explicitly loaded.
- [ ] Refine only observed routing/output-shape gaps; do not duplicate or redefine repository canonical.

### Task 4: Full verification, independent review, and Draft PR

- [ ] Run targeted new tests, skill validation, CLI smoke, `bash scripts/engineering/test.sh all-safe`, `bash scripts/engineering/check-secrets.sh`, and `git diff --check`.
- [ ] Verify the changed-path set has no overlap with the existing Task 05 diff and contains no protected/canonical/Runtime paths.
- [ ] Obtain independent exact-HEAD spec and quality review; fix all Critical/Important findings and re-run affected tests.
- [ ] Use `task-worktree.sh integrate --lane 2 --issue 97 --test-profile all-safe` to create one commit, push, and open a Draft PR to `develop`.
- [ ] Verify PR head, CI, and readback. Keep the worktree for review; do not touch `main` or Runtime.
