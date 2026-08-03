# Lean Matrix V1 End-to-End Bootstrap Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development and superpowers:test-driven-development. The implementer reads only the generated RoleBriefV1 and repository context allowed by that brief.

**Goal:** Execute AI-TEAM-008 as a real Lane 2 Team Path and prove V06/V07 can move an ordinary scoped task from document intake through exact-head review, CI, develop merge, readback, cleanup, and versioned retrospective evidence.

**Architecture:** Keep Lean Matrix a thin Harness. Repair only the stage-ownership defect that currently asks a pre-review implementer for post-review and post-PR evidence. V06 continues to bind local implementation evidence and independent FinalDecision; V07 consumes fresh normalized GitHub facts and remains a pure evaluator; Connector/Codex performs GitHub mutations.

**Tech Stack:** Python 3, pytest, Git temporary repositories, existing Lean Matrix V06/V07 contracts, GitHub Connector, Markdown.

## Global Constraints

- Task ID is `AI-TEAM-008`, Issue is `#120`, Lane is `2`, and exact base is `origin/develop@b379b0e469fb5cb713e25f01cf3debe6b12e0f9f` unless strict base drift forces a wholly fresh intake/review/CI chain.
- Actual security specialist, implementer, and independent reviewer contexts use Sol high; the frozen Lane 2 ExecutionPlan prediction remains recorded as Terra medium and grants no authority.
- Allowed tracked paths are exactly the Charter allowlist. No services, apps, packages, data, deploy, alembic, `.env`, Runtime, notification, `PROJECT_SOURCE.md`, business canonical, main, release/tag, real data/DB/live, deletion, GitHub-rules, or trading change is permitted.
- AI delivery lead combines project and technical leadership. Do not add project-lead or technical-lead public RoleBriefV1 roles.
- No daemon, state database, agent runtime, GitHub client inside V06/V07, or second canonical state source.
- Initial review is round 0; only rounds 1, 2, and 3 may repair Critical/Important findings. Round 3 load-bearing findings stop as `阻塞`.
- Evidence labels are exactly `MEASURED`, `MANUALLY_RECORDED`, and `NOT_MEASURABLE`; conversation memory never supplies a metric.

---

### Task 1: Truthful stage ownership and negative matrix

**Files:**
- Modify: `scripts/engineering/lean_matrix/contracts.py`
- Modify: `scripts/engineering/lean_matrix/planning.py`
- Modify: `scripts/engineering/lean_matrix_team.py`
- Test: `tests/engineering/test_lean_matrix_v1_bootstrap.py`

**Interfaces:**
- Preserve the ExecutionPlanV1 wire schema and old-plan loading.
- Classify `diff-check` and `secret-scan` as pre-review implementer evidence, `independent-review` as FinalDecision evidence, and `exact-head-ci` as fresh V07 GitHub evidence.
- V07 checks only the CI-owned required checks and independently validates Review evidence.

- [ ] Add RED tests proving the present pre-review package cannot honestly require review/CI receipts and proving V07 must not treat local/review evidence as CI checks.
- [ ] Add RED tests for the complete Owner Gate, provenance, scope, recovery, three-round, CI/thread/conflict, timeout/readback, cleanup/ancestry, prompt-injection, and sensitive-operation matrix.
- [ ] Run the focused test and confirm it fails for the missing stage ownership behavior.
- [ ] Implement the smallest stage-ownership repair without changing authority or adding a service.
- [ ] Run focused and full Lean Matrix tests to GREEN.
- [ ] Commit the task implementation and tests.

### Task 2: Skill and protocol alignment

**Files:**
- Modify only if behavior changed: `.agents/skills/lean-matrix-ai-team/SKILL.md`
- Modify only if behavior changed: `.agents/skills/lean-matrix-ai-team/references/execution.md`
- Modify only if behavior changed: `.agents/skills/lean-matrix-ai-team/references/review.md`
- Modify only if behavior changed: `.agents/skills/lean-matrix-ai-team/references/recovery.md`
- Test: `tests/engineering/test_lean_matrix_skill_policy.py`

**Interfaces:**
- Human/agent protocol must state the same stage ownership as executable contracts.
- V06 remains network/merge-free and V07 remains a pure evaluator.

- [ ] Add or update behavior-level policy tests before changing protocol text.
- [ ] Make the minimum protocol edits required by Task 1.
- [ ] Run Skill policy tests and quick validator.
- [ ] Commit protocol alignment.

### Task 3: Exact-head evidence, independent decision, and main PR integration

**Files:**
- Runtime evidence only: `.ai/lean-matrix/<plan-digest>/<intake-digest>/`
- No additional tracked path unless a review finding requires an allowed repair.

**Interfaces:**
- Produce direct-written specialist and implementer HandoffReportV1, exact-head ReviewPackageV1, independent FinalDecisionV1, review ledger, and V07 facts/decisions/merge receipt.

- [ ] Generate specialist, implementer, and reviewer briefs with globally disjoint identities.
- [ ] Run the security specialist, then the implementer, then an independent Sol whole-branch reviewer.
- [ ] Resolve Critical/Important findings within the V06 three-round cap.
- [ ] Run focused, full Lean Matrix, engineering, all-safe, Skill validator, Ruff, secret scan, and diff checks on exact HEAD.
- [ ] Push and create a Draft PR; wait for exact-head CI.
- [ ] Use fresh V07 pre_merge facts for ready and expected-head merge-commit transitions.
- [ ] Confirm merge_readback, write a digest-bound receipt, then pass a separate cleanup Gate and remove only the clean merged task worktree/branch.

### Task 4: Versioned retrospective closeout

**Files:**
- Create: `docs/superpowers/retrospectives/2026-08-03-lean-matrix-v1-bootstrap-trial.md`
- Create: `tests/engineering/test_lean_matrix_v1_bootstrap_evidence.py`

**Interfaces:**
- Record the main trial PR's post-merge facts with strict evidence classifications.
- The closeout is a separate evidence-only Lane 2 PR and cannot backfill its own future merge facts into the main-trial retrospective.

- [ ] Create an evidence-only worktree from post-main-merge `origin/develop`.
- [ ] Write the retrospective from Git, GitHub, and fixed artifact evidence only.
- [ ] Add tests that reject missing classifications, unsupported success claims, or forbidden-operation counts above zero.
- [ ] Run the complete closeout verification set and independent exact-head review.
- [ ] Use V07 for Draft ready, expected-head merge commit, readback, ancestry, and cleanup.
- [ ] Conclude exactly `允许继续实现` only if every V1 Gate passes; otherwise conclude `阻塞`.
