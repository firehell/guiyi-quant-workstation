# Lean Matrix Local Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Do not implement AI-TEAM-007 GitHub merge control in this task.

**Goal:** Reconstruct local task state from `ExecutionPlanV1` and Git facts, then permit exactly one guarded Lane 1/2 transition per explicit apply.

**Architecture:** `lean_matrix_team.py` remains a thin CLI. Focused modules observe local Git, derive a deterministic proposal, delegate one action to the existing `task-worktree.sh`, and store non-canonical recovery evidence under ignored `.ai/lean-matrix/<plan-digest>/`.

**Tech Stack:** Python 3.13 standard library, frozen V1 contracts, argparse, subprocess argv arrays, Git, pytest.

## Global Constraints

- Issue #109; Lane 2; branch `feature/AI-TEAM-005-local-orchestrator`; base `origin/develop@ea16e4f2fcd9f025dba0b66545ef9b4e63ad8e15`.
- Preserve byte-compatible `charter` and `plan`; do not change `ExecutionPlanV1` schema.
- `observe`, `next`, and `apply` without `--apply` are read-only and create no runtime workspace.
- External Gates identify Lane 3 and permanently block generic apply.
- No business code, data/DB, daemon, GitHub inspection/merge controller, `main`, release, Runtime, live, or notification change.

---

### Task 1: Local observation and state digest

- [x] Add RED tests using temporary Git repositories and a complete fake at the Git executable boundary.
- [x] Reconstruct exact base, task refs, registered worktree identity, HEAD, dirty state, committed/staged/unstaged/untracked paths, and dual-develop ancestry.
- [x] Compute `state_digest` from canonical material facts excluding the digest field itself.
- [x] Keep all observation commands local, fixed argv, `shell=False`, `GIT_OPTIONAL_LOCKS=0`, and free of fetch/network/writes.

### Task 2: Deterministic one-step transition policy

- [x] Add RED tests for base drift, scope drift, Lane 3, replay, interrupted integrate, cleanup ancestry, and recursive `/**` allowlists.
- [x] Derive deterministic transition IDs from plan digest, action, and before-state digest.
- [x] Permit only `task-create`, `local-integrate-to-draft-pr`, and `local-cleanup-after-merge-observed` as executable actions.
- [x] Return non-executable wait proposals for implementation, AI-TEAM-007/develop merge, human Gate, and closed states.

### Task 3: Adapter and ignored recovery evidence

- [x] Generate one fixed `task-worktree.sh` argv command per executable action and select its exact cwd.
- [x] Execute exactly one subprocess and persist only command digest, exit code, result, and stable error type—never raw stdout/stderr or environment values.
- [x] Store plan/proposal/receipt/log JSON atomically under `.ai/lean-matrix/<plan-digest>/` with content-bound filenames.
- [x] Reject cross-plan evidence, tamper, incomplete pairs, duplicate actions, state mismatch, and successful exit without an observed state change.

### Task 4: CLI, policy, and delivery

- [x] Add `observe`, `next`, and guarded `apply` while retaining the stable JSON error boundary.
- [x] Update the Lean Matrix Skill and Phase 4 design boundary without modifying project/business canonical status.
- [x] Run targeted, compatibility, skill validation, engineering, all-safe, secret, and diff checks.
- [ ] Commit and push the exact task head, create a Draft PR to `develop`, obtain independent exact-head Review and CI, then use the existing integration workflow only if every Gate passes.
