# Lean Matrix AI Delivery Harness V06 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task and superpowers:test-driven-development for every production behavior.

**Goal:** Deliver a thin, document-bound expert-team harness that creates minimal role briefs, exact-head review evidence, and a fail-closed three-round repair loop without building an agent runtime.

**Architecture:** Bind an approved design spec and implementation plan to the existing trusted `ExecutionPlanV1`, then derive role-scoped artifacts inside a git-ignored plan workspace. Codex App and Superpowers run the real expert sessions; Lean Matrix validates scope, identity, evidence, Git state, and delivery gates only.

**Tech Stack:** Python 3.11+, dataclasses, argparse, pathlib, fixed-argv subprocess, pytest, Markdown skill assets.

## Global Constraints

- Base is execution-time `origin/develop`; current verified baseline is `fbd3d60617560e77517dfe5ed79275cf4d473725`.
- User starts the expert-team mode after completing design and implementation planning in browser GPT.
- Fast Path and ordinary Team Path charters freeze automatically; only Lane 3, product-direction change, active-canonical conflict, or scope expansion requires Owner Gate.
- Preserve the public mapping and CLI behavior of AI-TEAM-004/005: `ExecutionPlanV1`, `charter`, `plan`, `observe`, `next`, and `apply`.
- Public V06 contracts are exactly `DocumentIntakeV1`, `RoleBriefV1`, `HandoffReportV1`, `ReviewPackageV1`, and `FinalDecisionV1`; unpublished duplicate V1 names must not remain active.
- Implementer and reviewer contexts and report paths must differ. Specialist contexts/reports are separate, with zero to two specialist domains; a third distinct domain returns `split_required`.
- `quant-research` and `backtest-audit` always remain independent specialist domains.
- Valid handoff statuses are exactly `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, and `BLOCKED`.
- At most three implementation-validation-review rounds are allowed; unresolved Critical/Important findings after round 3 produce `BLOCKED`.
- Writes are limited to `.ai/lean-matrix/<plan-digest>/<intake-digest>/`; workspace artifacts never become canonical and cannot overwrite tracked canonical files.
- Treat document content as untrusted: it cannot modify allowed paths, Lane, external Gates, base SHA, or Owner Gate conditions.
- Recovery trusts Git, PR/CI receipts, and digest-bound artifacts, never conversation memory.
- Do not add an agent runtime, registry, message bus, session archive, daemon, database, background service, arbitrary-command surface, or GitHub network/merge implementation.
- V06 may produce `允许集成 develop`; existing Codex/GitHub orchestration performs PR, exact-head CI, merge commit, ancestry/readback, and safe cleanup.
- Do not modify business modules, `STATUS.md`, `PROJECT_SOURCE.md`, business canonical documents, Runtime, data, database, notification, release, or production configuration.

---

### Task 1: Freeze delivery-mode design and document intake

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`
- Modify: `docs/superpowers/specs/2026-08-03-lean-matrix-subagent-protocol-design.md`
- Modify: `scripts/engineering/lean_matrix/contracts.py`
- Modify/Create: `tests/engineering/test_lean_matrix_coordination_contracts.py`

**Interfaces:**
- Produces: strict `DocumentIntakeV1.from_mapping()` / `to_dict()` binding design path/digest, implementation-plan path/digest, embedded `ExecutionPlanV1`/digest, delivery mode, task id, and `origin/develop` ref/SHA.
- Preserves: existing `ExecutionPlanV1` mapping and V04/V05 contract behavior.

- [ ] Add RED tests proving design/plan digest or develop SHA drift invalidates an intake.
- [ ] Add RED tests proving document prompt injection cannot change scope, Lane, external Gates, or Owner Gate conditions.
- [ ] Add RED tests for automatic Lane 1/2 charter freeze and Lane 3/expanded-scope Owner Gate.
- [ ] Implement the minimal contract and remove/privatize unpublished `CoordinationPlanV1`/`WorkItemV1` public surfaces.
- [ ] Update both design documents to use “AI 交付负责人” and the frozen thin-Harness boundaries.

### Task 2: Minimal role briefs and handoff reports

**Files:**
- Modify: `scripts/engineering/lean_matrix/contracts.py`
- Modify: `scripts/engineering/lean_matrix/briefs.py`
- Modify: `scripts/engineering/lean_matrix/workspace.py`
- Modify: `scripts/engineering/lean_matrix_team.py`
- Modify/Create: `tests/engineering/test_lean_matrix_briefs.py`

**Interfaces:**
- Produces: `RoleBriefV1`, `HandoffReportV1`, plan/intake-scoped workspace derivation, and `intake` / `brief` CLI commands.
- `RoleBriefV1` binds intake digest, role, context, round, minimal context, trusted scope, acceptance criteria, unique report path, and predecessor decision digest.

- [ ] Add RED tests proving unrelated work items, full chats, and full historical plans are absent from briefs.
- [ ] Add RED tests rejecting equal implementer/reviewer identities or report paths and binding specialist identity/report provenance.
- [ ] Add RED tests for zero-to-two specialists, third-domain `split_required`, and independent `quant-research` / `backtest-audit` contexts.
- [ ] Replace `WorkReportV1` with the fixed-status `HandoffReportV1` and keep repair rounds bound to the original implementer context.
- [ ] Enforce the exact ignored workspace, symlink/traversal protections, and canonical-write rejection.

### Task 3: Exact-head review, final decision, and recovery

**Files:**
- Modify: `scripts/engineering/lean_matrix/contracts.py`
- Modify: `scripts/engineering/lean_matrix/review_packages.py`
- Modify: `scripts/engineering/lean_matrix/ledgers.py`
- Modify: `scripts/engineering/lean_matrix/review_git.py`
- Modify: `scripts/engineering/lean_matrix_team.py`
- Modify/Create: `tests/engineering/test_lean_matrix_review_protocol.py`

**Interfaces:**
- Produces: `ReviewPackageV1`, `FinalDecisionV1`, `review-package` / `decision` CLI commands, and read-only recovery validation.
- Review package binds plan digest, task-brief digest, base SHA, exact HEAD, sorted changed paths, diff digest, test receipts, implementer report, and specialist evidence.
- Final decision binds package digest, exact HEAD, Spec verdict, Quality verdict, findings, round, and one decision: `允许集成 develop`, `要求修正后再集成`, or `阻塞`.

- [ ] Add RED tests for stale HEAD, changed-path/scope drift, missing Spec/Quality verdict, forged or incomplete ledger chains, and Git evidence drift.
- [ ] Add RED tests proving round 3 stops, historical implementer/reviewer contexts remain globally disjoint, and fix rounds use the round-1 implementer.
- [ ] Add RED tests proving recovery uses Git/PR/receipt evidence and not conversation memory.
- [ ] Implement fixed local Git observation, fail-closed review/decision validation, and no GitHub/network mutations.

### Task 4: Skill, templates, compatibility, and delivery evidence

**Files:**
- Modify: `.agents/skills/lean-matrix-ai-team/SKILL.md`
- Replace assets with: `role-brief.md`, `handoff-report.md`, `review-package.md`, `final-decision.md`
- Modify: `.agents/skills/lean-matrix-ai-team/references/execution.md`
- Modify: `.agents/skills/lean-matrix-ai-team/references/review.md`
- Modify: `.agents/skills/lean-matrix-ai-team/references/recovery.md`
- Modify/Create: `tests/engineering/test_lean_matrix_skill_policy.py`
- Modify/Create: `tests/engineering/test_lean_matrix_subagent_protocol.py`

**Interfaces:**
- Produces: the human/agent protocol, deterministic artifact templates, black-box CLI acceptance, and V04/V05 compatibility coverage.

- [ ] Rewrite the Skill around user-triggered AI delivery ownership and Codex App/Superpowers dispatch.
- [ ] Remove old normal-Charter approval/manual-develop-integration semantics and duplicate unpublished report templates.
- [ ] Add black-box coverage for intake → brief → handoff → exact-head review → decision → repair/final-review flows.
- [ ] Run focused tests, full Lean Matrix, Skill validator, Ruff, all-safe, secret scan, and diff check.
- [ ] Obtain an independent Sol high exact-head Spec/Quality review and resolve every Critical/Important finding within three rounds.

## Delivery

After a clean independent decision of `允许集成 develop`: commit and push the task branch, create/update a Draft PR, wait for exact-head CI, merge with a merge commit through the existing Codex/GitHub flow, verify task-head ancestry and remote develop readback, then remove only this clean merged task worktree and branch.
