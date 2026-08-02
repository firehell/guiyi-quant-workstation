# Lean Matrix Phase 3 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the self-referential Phase 3 pending snapshot with durable PR #103 merge and post-merge CI evidence, then close and clean the completed task without enabling Phase 4.

**Architecture:** Treat GitHub PR #103, Issue #102, and the post-merge engineering run as the external facts that could not exist inside the original task head. Update only the Lean Matrix canonical design, retrospective, and evidence contract in a new Lane 2 docs worktree; merge and cleanup remain fail-closed on exact-head review, CI, ancestry, and cleanliness.

**Tech Stack:** Markdown, pytest, repository engineering scripts, GitHub CLI.

## Global Constraints

- Immutable closeout base: `c59cda243c141d68ae006c6879da5ce5822a0044`.
- Allowed tracked paths are this plan, the Lean Matrix design, the Phase 3 retrospective, and the Phase 3 evidence test.
- Do not modify `STATUS.md`, Task 06 paths, CLI, workflow, service, database, backend, frontend, `main`, Runtime, real data, notifications, release, or deployment.
- Phase 4 remains `NO_GO_PENDING_SEPARATE_APPROVAL`; Phase 5 remains `NO_GO`.
- The user's one-time ready/merge authorization applies only to this docs/test closeout PR after all review and CI gates pass.

---

### Task 1: Close the versioned Phase 3 evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`
- Modify: `docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md`
- Test: `tests/engineering/test_lean_matrix_phase3_evidence.py`

**Interfaces:**
- Consumes: GitHub Issue #102, PR #103 metadata, and post-merge engineering run `30742215606`.
- Produces: canonical merged Phase 3 status and a source-bound completed controlled-trial report.

- [ ] Add failing tests that reject the stale active/unmerged and pending-external snapshot.
- [ ] Run the Phase 3 evidence test and confirm the expected RED failures.
- [ ] Record PR #103 head, merge SHA/time, post-merge CI, final review/process counts, and the `2h17m29s` Charter-to-develop cycle.
- [ ] Keep manual process counts non-gating and all Phase 4/5 authority fail-closed.
- [ ] Run focused, combined, all-safe, secret, validator, and diff checks.
- [ ] Obtain independent exact-diff and exact-head approval before integration.
- [ ] Push a Draft PR, wait for CI, use the one-time ready/merge authorization, verify post-merge CI, close Issue #102, and clean only integrated clean worktrees.
