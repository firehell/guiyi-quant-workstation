# GY-DATA-CORE-V2 Task 07 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Every behavior change follows red-green-refactor.

**Goal:** Complete Task 07 with trusted direct K-line migration, direct reuse of already verified aggregate-minute K-lines, zero legacy active references, exact retirement/deletion evidence, a disabled code-only Runtime cutover, and develop integration.

**Architecture:** Active historical data is canonical RQData direct `1m/1d/1w` plus already verified aggregate `5m/15m/30m/60m`, all read at the requested frequency through `MarketDataService`. Aggregate migration performs deterministic canonical schema conversion only: it does not reaggregate from `1m`, compare bars bucket-by-bucket, call RQData, or fall back to on-demand historical aggregation. Old derived `1d` is not migrated. Migration is create-only and precedes Runtime cutover; retirement and deletion require zero checkout/Runtime active references.

**Tech Stack:** Python, FastAPI, SQLAlchemy/PostgreSQL, PyArrow/Parquet, Vue/Vite/TypeScript, shell-based engineering Gates.

## Global Constraints

- Do not restore or require `/Volumes/扩展盘/GuiyiApprovals`; the mandatory inventory evidence root is always protected.
- Never delete Canonical, Catalog, Manifest, DataGap, MainContractMap, reports 14/15, receipts, task evidence, ResearchSample, Git history, or historical business rows.
- Preserve every K-line source file. Eligible passed aggregate `5m/15m/30m/60m` files are imported as same-frequency canonical datasets; warning, damaged, missing-evidence, or conflicting files remain preserved and receive an explicit DataGap/blocked disposition.
- No K-line file is a deletion candidate, including direct, aggregate, warning, damaged, conflicting, and unique files.
- Deletion may cover only exact non-K-line retirement candidates after the trusted Runtime and retirement receipts exist.
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
- Freeze `1m/5m/15m/30m/60m/1d/1w` as persisted same-frequency historical datasets; actual-dominant `1w` uses the last trading day's rank=1 concrete contract.
- Run focused API/service/frontend tests and build.

### Task 5: Add exact deletion orchestration

- Add `deletion-plan`, `deletion-preflight`, `deletion-apply`, and `deletion-verify` Task 07 CLI commands.
- Freeze absolute path, approved root, device/inode, size, mtime, SHA-256, disposition, canonical replacement receipt, and recoverability per file.
- Exclude protected evidence, every K-line file, Canonical and historical evidence.
- Apply via same-filesystem atomic quarantine plus fsync journal; verify all invariants before permanent unlink. Any path, mount, stat, checksum, reference, or canonical drift fails closed.
- Preserve `market_data_files` and historical business metadata; retirement DML only supersedes/cancels/deactivates exact active rows.

### Task 5A: Persist verified aggregate-minute datasets

- Extend `DatasetKey` and PostgreSQL dataset constraints to accept all seven stored frequencies, retain direct-provider `1m/1d/1w`, and reject old derived `1d` imports as direct sources.
- Add Alembic `0032` with a fail-closed downgrade when persisted aggregate datasets exist.
- Add digest-bound manifest lineage distinguishing `provider_direct` from `preaggregated_from_1m`, including legacy source checksum and quality-evidence digest.
- Classify an aggregate as reusable only when it is primary/passed, physically present and readable, its registered checksum/row count/min/max/frequency match, `source_interval=1m`, and every value is representable by the canonical writer.
- Convert the existing aggregate rows to canonical Decimal/UTC schema without changing bar values or computing new bars. Never call RQData or perform bucket-by-bucket comparison.
- Include direct and aggregate batches in the same exact migration approval envelope. Preserve every source K-line after successful import.

### Task 5B: Remove historical on-demand aggregation

- Read `1m/5m/15m/30m/60m/1d/1w` from the same-frequency canonical Catalog partition through `MarketDataService`.
- Remove the historical `1m -> 5m/15m/30m/60m` fallback. A missing same-frequency dataset returns a DataGap and never silently reaggregates.
- Keep confirmed live aggregation unchanged and keep all consumers on `DatasetKey/BarsResult`.
- Run focused Market/Web/Indicator/Backtest/Signal/Review regressions and update canonical data documentation.

### Task 6: Add Task 07 code-only Runtime cutover Gate

- Provide only read-only `runtime-cutover-plan` and `runtime-cutover-verify`; no apply/stop/switch/restart path.
- Bind exact target/previous tags and SHAs, DB `20260803_0032`, all feature flags disabled, health/smoke passed, rollback-ready, and checkout/Runtime reference zero.
- Do not add PID, environment/Web bundle, generic row-set digest, or multi-stage lineage fields; a fixture receipt never unlocks retirement/deletion.

### Future production closeout (not part of this code-only PR)

- Run full backend, frontend, Ruff, engineering all-safe, secret scan, the repository docs profile, diff check, and independent whole-branch review.
- Merge the reviewed task branch into develop through the normal protected flow; do not touch main/release/tag.
- From the clean develop merge SHA, collect final production inventory and produce the single exact migration packet.
- After owner approval, apply and verify every eligible direct and aggregate batch; record explicit DataGap/blocked dispositions for all remaining K-lines and preserve all source K-lines.
- Generate and obtain approval for the Runtime packet, perform code-only cutover, and verify checkout/develop/Runtime legacy active/review references are zero.
- Generate and obtain approval for exact retirement plus deletion packets, apply/verify them, confirm Canonical checksums unchanged, and update Task 07 evidence/status to `READY_FOR_TASK_08` only if every Gate passes.
