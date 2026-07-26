# V1 HTDY Step 0 Integration and Contract Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit the three source worktrees, revoke the superseded JM V1-B S6-08 authorization, and freeze the exact HTDY original XMA realtime first-seen observation contract without enabling a new write path.

**Architecture:** Preserve the current formal confirmed-only and historical backtest policies. Add one identity-exact realtime repainting observation contract that reuses the existing StrategySignal, SignalEvent, and SignalNotification chain in later steps; Step 0 changes only documentation plus a bounded Runtime disable/restart action and create-only evidence.

**Tech Stack:** Git worktrees, Markdown/JSON canonical evidence, launchd, FastAPI Runtime health, PostgreSQL read-only verification.

## Global Constraints

- Work only on `codex/v1-htdy-realtime-closure` in the dedicated integration worktree.
- Do not modify S6-03 through S6-07 receipts or historical conclusions.
- Do not modify Runtime code, database rows, Profile bindings, canonical Parquet, report 14/15, notification rows, or trading paths.
- Preserve old packets and old worktrees; do not delete or rewrite them.
- Keep `GUIYI_WECHAT_AUTOSEND_ENABLED=false`.
- Do not claim HTDY historical validity, profitability, notification readiness, Runtime readiness, long-running readiness, or trading readiness.

---

### Task 1: Establish the inventory and safe baseline

**Files:**
- Create: `docs/tasks/V1-HTDY-00-INTEGRATION-AND-CONTRACT-FREEZE.md`
- Create: `data/reports/v1_htdy_integration_contract_freeze_20260726/revocation_evidence.json`

**Interfaces:**
- Consumes: `main@1805af2e`, `codex/htdy-original-realtime-alert@ebf172cc`, `codex/s6-08-live-signal-event-acceptance@c864a5a2`, detached Runtime `1805af2e`.
- Produces: KEEP/REWORK/DROP/HISTORICAL matrix and a sanitized before/after evidence record.

- [x] Record all worktree commits, status, commit graph, name-status diff, and diff stat.
- [x] Verify the old schema-v2 packet identity and that the current Runtime has SignalEvent disabled, empty packet/hash, and autosend disabled.
- [x] Record read-only PostgreSQL counts, revision, Profile hash, EOD checkpoint, and absence of `htdy_observation_alerts`.

### Task 2: Revoke the superseded authorization safely

**Files:**
- Modify outside Git only through the existing bounded script: Runtime `project.env` three SignalEvent keys.

**Interfaces:**
- Consumes: `scripts/configure-live-signal-events.sh --disable`.
- Produces: false/empty/empty SignalEvent configuration and a fresh live scheduler heartbeat.

- [x] Run the existing disable command idempotently.
- [x] Restart only `com.guiyi.quant-runtime-scheduler`.
- [x] Verify fresh Runtime/live/EOD health, autosend=false, authorization hash empty, and all protected PostgreSQL facts unchanged.

### Task 3: Freeze the exact contract and revised S6 task skeletons

**Files:**
- Modify: `AGENTS.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `docs/SIGNAL_EVENTS.md`
- Modify: `docs/tasks/JM-LIVE-SIGNAL-EVENT-S6-08.md`
- Create: `docs/tasks/JM-LIVE-WECOM-SINGLE-S6-09.md`
- Create: `docs/tasks/JM-LIVE-STABILITY-S6-10.md`
- Create: `docs/tasks/V1-FINAL-ACCEPTANCE-S6-11.md`

**Interfaces:**
- Consumes: the exact identity frozen in the user-supplied closure handbook.
- Produces: an exact allowlist contract and non-Ready task contracts for Steps 4 through 9.

- [x] Preserve the Registry's ordinary observation-only capability and formal backtest rejection.
- [x] Freeze `jm + actual rank=1 + 15m + htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting`.
- [x] Freeze first-seen/no-retraction, signal_created-only, no-migration, no-auto-order, and no-autosend boundaries.
- [x] Mark old JM V1-B schema-v2 S6-08 material as superseded historical evidence.

### Task 4: Verify and checkpoint

**Files:**
- Verify all files listed above.

**Interfaces:**
- Consumes: the completed Step 0 diff.
- Produces: a reviewable checkpoint with no external Ready claim.

- [x] Run `bash scripts/engineering/check-secrets.sh`.
- [x] Run `bash scripts/engineering/test.sh docs`.
- [x] Run `git diff --check`.
- [x] Review the diff so STATUS contains only frozen/pending/revoked facts and there are no S6-03 through S6-07 receipt, migration, Runtime code, data, or secret changes.
- [x] Commit one independent Step 0 checkpoint.
