# GY-DATA-CORE-V2 Task 07 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Every behavior change follows red-green-refactor.

**Goal:** Complete Task 07 with trusted direct K-line migration, on-demand derived minutes, zero legacy active references, exact retirement/deletion evidence, a disabled code-only Runtime cutover, and develop integration.

**Architecture:** Active historical data is canonical RQData direct `1m/1d/1w` through `MarketDataService`; `5m/15m/30m/60m` is deterministically derived from canonical `1m`. Existing derived files remain cold and inactive. Migration is create-only and precedes Runtime cutover; retirement and deletion require zero checkout/Runtime active references.

**Tech Stack:** Python, FastAPI, SQLAlchemy/PostgreSQL, PyArrow/Parquet, Vue/Vite/TypeScript, shell-based engineering Gates.

## Global Constraints

- Do not restore or require `/Volumes/扩展盘/GuiyiApprovals`; the mandatory inventory evidence root is always protected.
- Never delete Canonical, Catalog, Manifest, DataGap, MainContractMap, reports 14/15, receipts, task evidence, ResearchSample, Git history, or historical business rows.
- Preserve legacy `5m/15m/30m/60m` files as cold inactive data; active derived bars are computed only from canonical `1m`.
- Unique, warning, damaged, or conflicting K-line files are quarantined/registered as DataGap and are not deleted without an exact canonical replacement receipt.
- Deletion may cover non-K-line retirement candidates and direct K-line sources with exact verified canonical replacement receipts only.
- Runtime work is code-only and must keep live/EOD/notification/trading disabled and `auto_order=false`.
- Do not enter `main`, create a release/tag, call RQData by default, send notifications, or enable trading.
- Real Canonical/PostgreSQL, Runtime, and deletion apply each require a freshly generated exact-hash owner approval packet.

---

### Task 1: Finish protected-root hardening checkpoint

- Complete the interrupted protected-root work: optional extra `--protected-root`, automatic evidence-root protection, and lexical plus resolved-path protection against symlink escape.
- Replace misleading active fixtures only where needed; historical documents remain historical.
- Run the symlink regression, complete Task 07 orchestration tests, Ruff, docs Gate, secret scan, and diff check.
- Update canonical Task 07 status/evidence accurately and commit the checkpoint.

### Task 2: Synchronize latest develop and restore a clean baseline

- Merge current `develop` into the task branch without reverting AI-TEAM-004/005 or unrelated user work.
- Resolve Status/Data Center/task documentation conflicts using current develop as the general project state and Task 07 ledger as task-specific evidence.
- Run focused backend/frontend consumer tests and establish a clean committed baseline.

### Task 3: Split migration, Runtime, retirement, and deletion Gates

- Make migration eligibility depend only on exact inventory/data/source/target validity, not active-reference zero.
- Add a single migration approval envelope binding every batch digest and a deterministic Merkle root while retaining per-batch preflight/apply/verify/journal semantics.
- Keep Runtime cutover eligibility dependent on every migration batch verification.
- Keep retirement and deletion eligibility dependent on zero checkout and detached Runtime active/review references.
- Add drift, incomplete receipt, and batch failure tests before implementation.

### Task 4: Complete canonical consumer cutover on latest develop

- Converge Market/Web/Indicator/Backtest/Signal/Review active paths on `MarketDataService + DatasetKey/BarsResult`.
- Remove active `profile_id`/`market_data_file_id` request selection; historical response lineage remains read-only.
- Ensure direct `1m/1d/1w` and deterministic `5m/15m/30m/60m` behavior, with actual-dominant `1w` prohibited.
- Run focused API/service/frontend tests and build.

### Task 5: Add exact deletion orchestration

- Add `deletion-plan`, `deletion-preflight`, `deletion-apply`, and `deletion-verify` Task 07 CLI commands.
- Freeze absolute path, approved root, device/inode, size, mtime, SHA-256, disposition, canonical replacement receipt, and recoverability per file.
- Exclude protected evidence, cold derived minutes, DataGap/conflict/unique K-lines, Canonical and historical evidence.
- Apply via same-filesystem atomic quarantine plus fsync journal; verify all invariants before permanent unlink. Any path, mount, stat, checksum, reference, or canonical drift fails closed.
- Preserve `market_data_files` and historical business metadata; retirement DML only supersedes/cancels/deactivates exact active rows.

### Task 6: Add Task 07 code-only Runtime cutover Gate

- Bind source/develop merge SHA, current detached Runtime SHA, target tree, service parents, flags, environment digest, Web bundle digest, rollback SHA, and approval hash.
- Preflight requires all migration receipts verified, flags disabled, no unexpected live/SignalEvent increments, and clean exact source/runtime state.
- Stop the exact API/scheduler/worker/Web service set, switch detached Runtime, restart the same set, run disabled smoke and active-reference scan, and rollback on failure.
- Never enable live/EOD/notification/trading.

### Task 7: Final repository and production Gate execution

- Run full backend, frontend, Ruff, engineering all-safe, secret scan, docs links, diff check, and independent whole-branch review.
- Merge the reviewed task branch into develop through the normal protected flow; do not touch main/release/tag.
- From the clean develop merge SHA, collect final production inventory and produce the single exact migration packet.
- After owner approval, apply and verify every eligible batch; record explicit DataGap/quarantine dispositions for all remaining K-lines.
- Generate and obtain approval for the Runtime packet, perform code-only cutover, and verify checkout/develop/Runtime legacy active/review references are zero.
- Generate and obtain approval for exact retirement plus deletion packets, apply/verify them, confirm Canonical checksums unchanged, and update Task 07 evidence/status to `READY_FOR_TASK_08` only if every Gate passes.
