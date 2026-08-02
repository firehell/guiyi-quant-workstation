# Lean Matrix Phase 3 Status Consistency Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the merged Phase 2 status and produce a source-bound Phase 3 controlled-trial record for one ordinary reversible Lane 2 task without expanding automation or authority.

**Architecture:** GitHub Issue #102 is the frozen Task Charter and task-start metric source. The existing Lean Matrix design remains the canonical phase contract; one retrospective records the controlled trial, and one engineering test file enforces phase truth, metric provenance, and no-authority boundaries. Final self-referential PR/head/merge facts live in GitHub exact-head evidence rather than being guessed inside the task commit.

**Tech Stack:** Markdown, Python 3 standard library, pytest, existing Lean Matrix skill/templates, existing engineering worktree and CI flow.

## Global Constraints

- Work only in `/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-003-phase3-status-consistency-pilot` on `research/AI-TEAM-003-phase3-status-consistency-pilot`.
- Immutable task base is `origin/develop@7a668eeb802b50d140591b75895398550f6c3ae8`; Issue is #102.
- Allowed tracked paths are exactly the existing Lean Matrix design, this plan, the Phase 3 retrospective, and `tests/engineering/test_lean_matrix_phase3_evidence.py`.
- Do not modify `STATUS.md`, any active Task 06 path, scripts, CLI, workflow automation, services, database, migrations, backend, frontend, or Runtime code.
- Do not modify `main`, detached Runtime, real data, PostgreSQL, notifications, deployment, release/tag, GitHub rules, or any sibling worktree.
- Use the four base roles with no specialist. Implementer and independent quality reviewer must use separate contexts.
- Metrics start at Issue #102 `createdAt=2026-08-02T07:22:32Z`. Do not estimate or reconstruct missing metrics from conversation memory.
- `MANUALLY_RECORDED` observations are process evidence only and cannot satisfy or drive a Gate.
- Phase 4 defaults to `NO_GO_PENDING_SEPARATE_APPROVAL`; Phase 5 remains `NO_GO`.
- At most three failed implementation-review rounds before reporting the task blocked; the SDD five-round breaker remains an absolute cap.

---

### Task 1: Correct the canonical Lean Matrix phase status

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`
- Create: `tests/engineering/test_lean_matrix_phase3_evidence.py`

**Interfaces:**
- Consumes: PR #101 merge facts, Issue #102 Charter, and the existing Phase 2/3 design contract.
- Produces: a current design status that later report tests treat as the canonical phase truth.

- [ ] **Step 1: Write failing status tests**

  Require the design to record Phase 2 merged through PR #101 at `develop@7a668eeb`, bind Phase 3 to Issue #102 and the planned task branch, and retain PR #100 as non-Phase-3 history. Reject the stale Phase 2 pending-PR sentence and affirmative Phase 4/5, `main`, Runtime, data-write, notification, release, or deployment authority.

- [ ] **Step 2: Run RED**

  ```bash
  python3 -m pytest -q tests/engineering/test_lean_matrix_phase3_evidence.py
  ```

  Expected: fail because the design still says Phase 2 is pending Draft PR/CI/merge and has no Issue #102 status.

- [ ] **Step 3: Make the minimal design update**

  Update only the top status line and Phase 2/3 current-status prose. Preserve the frozen Phase 3 workflow rules and Phase 4/5 contracts. State that Phase 3 is implemented on its task branch only after tracked evidence exists; until then it is active under Issue #102 and not merged.

- [ ] **Step 4: Run GREEN and regression tests**

  ```bash
  python3 -m pytest -q \
    tests/engineering/test_lean_matrix_phase3_evidence.py \
    tests/engineering/test_lean_matrix_phase2_evidence.py \
    tests/engineering/test_lean_matrix_skill_policy.py \
    tests/engineering/test_lean_matrix_team.py
  git diff --check
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md \
    tests/engineering/test_lean_matrix_phase3_evidence.py
  git commit -m "docs(workstation): record lean matrix phase 2 merge"
  ```

### Task 2: Add the source-bound Phase 3 controlled-trial report

**Files:**
- Create: `docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md`
- Modify: `tests/engineering/test_lean_matrix_phase3_evidence.py`

**Interfaces:**
- Consumes: the existing eight-section trial-report contract, Issue #102 Charter/checkpoints, Task 1 phase truth, and exact Git facts.
- Produces: the versioned Phase 3 evidence artifact and metric blocks used by final review.

- [ ] **Step 1: Add failing report-contract tests**

  Require all eight level-two sections: `Identity`, `Sample classification`, `Routing prediction`, `Observed execution`, `Metrics`, `Gate preservation`, `Findings`, and `Decision`. Validate each section locally rather than through global phrase presence.

  Parse every metric block and require exactly one non-empty name, value, provenance, and evidence source. Accept only `MEASURED`, `MANUALLY_RECORDED`, or `NOT_MEASURABLE`; require recognized repository/GitHub sources for measured facts, a named process observation plus no-Gate statement for manual facts, and explicit absence evidence for unmeasurable facts.

- [ ] **Step 2: Run RED**

  ```bash
  python3 -m pytest -q tests/engineering/test_lean_matrix_phase3_evidence.py
  ```

  Expected: fail because the Phase 3 retrospective does not exist.

- [ ] **Step 3: Write the minimal report**

  Use `controlled_trial`. Record Issue #102, base `7a668eeb`, four base roles, zero specialists, separate implementation/review contexts, start timestamp `2026-08-02T07:22:32Z`, baseline evidence, and current process checkpoints. Mark the PR number, final task head, merge SHA, and merge time as external GitHub exact-head facts pending at the versioned task snapshot; do not invent a self-referential SHA.

  State explicitly that the narrow docs/test sample can validate workflow mechanics but cannot authorize Phase 4. Use `NO_GO_PENDING_SEPARATE_APPROVAL` for Phase 4 and `NO_GO` for Phase 5.

- [ ] **Step 4: Run GREEN and mutation-oriented regression tests**

  ```bash
  python3 -m pytest -q \
    tests/engineering/test_lean_matrix_phase3_evidence.py \
    tests/engineering/test_lean_matrix_phase2_evidence.py \
    tests/engineering/test_lean_matrix_skill_policy.py \
    tests/engineering/test_lean_matrix_team.py
  git diff --check
  ```

  Confirm in-memory mutations fail for a missing metric source, invalid provenance, PR #100 reclassification, stale Phase 2 state, and positive Runtime/Phase 4 authority.

- [ ] **Step 5: Commit**

  ```bash
  git add docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md \
    tests/engineering/test_lean_matrix_phase3_evidence.py
  git commit -m "docs(workstation): record lean matrix phase 3 trial"
  ```

### Task 3: Finalize the process snapshot and delivery evidence

**Files:**
- Modify: `docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md`
- Modify: `tests/engineering/test_lean_matrix_phase3_evidence.py`

**Interfaces:**
- Consumes: Issue #102 metric checkpoints, the SDD ledger, Task 1/2 review results, and the final pre-review Git history.
- Produces: a final versioned metric snapshot plus external exact-head evidence requirements for the Draft PR.

- [ ] **Step 1: Add failing closeout tests**

  Require explicit metrics for logical sessions through the versioned snapshot, user interruptions, review-fix rounds, Charter-to-local-complete timing when source timestamps exist, three-round stop status, changed-path isolation, and the Phase 4/5 no-go decision. Require final reviewer/PR/merge counts to be identified as external evidence when they cannot exist inside the self-referential task head.

- [ ] **Step 2: Run RED**

  ```bash
  python3 -m pytest -q tests/engineering/test_lean_matrix_phase3_evidence.py
  ```

- [ ] **Step 3: Update the metric snapshot from recorded evidence only**

  Copy the recorded Issue/SDD checkpoints without estimation. Count a review-fix round only when an independent Critical/Important finding caused a tracked-file fix wave. Keep final PR/head/merge values external and require them in the PR evidence comment.

- [ ] **Step 4: Run GREEN and commit**

  ```bash
  python3 -m pytest -q \
    tests/engineering/test_lean_matrix_phase3_evidence.py \
    tests/engineering/test_lean_matrix_phase2_evidence.py \
    tests/engineering/test_lean_matrix_skill_policy.py \
    tests/engineering/test_lean_matrix_team.py
  git diff --check
  git add docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md \
    tests/engineering/test_lean_matrix_phase3_evidence.py
  git commit -m "docs(workstation): finalize lean matrix phase 3 evidence"
  ```

- [ ] **Step 5: Obtain final exact-head review and verification**

  Require a separate final reviewer to return Critical/Important/Minor findings, `Spec PASS/FAIL`, `Quality APPROVED/CHANGES_REQUIRED`, and Draft PR readiness. Then run:

  ```bash
  bash scripts/engineering/test.sh all-safe
  bash scripts/engineering/check-secrets.sh
  python3 /Users/zhangzhao/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/lean-matrix-ai-team
  git diff --check
  ```

- [ ] **Step 6: Push a Draft PR and bind external facts**

  Run the Lane 2 integration dry-run, push the existing commits, and create a Draft PR to `develop`. Record its number, exact `headRefOid`, CI, final logical-session count, final review-fix count, and later merge facts in GitHub evidence comments. Do not invoke merge, ready-for-review, Issue close, or cleanup.

  If the user merges externally, stop branch writes and verify all PR checks, post-merge CI, merge actor/SHA, ancestry, `main`, Runtime, and Task 06 isolation before reporting Phase 3 complete.
