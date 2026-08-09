## Context

See proposal.md — Why. Active universe is file-driven (`active_products.txt`，现行 **60**)。
Catalog rows come from RQData metadata sync and are not auto-removed when a code leaves the file.
Prior 21-product retirement tooling was deleted during V2 convergence; DFD-07 already wiped most
formal Canonical data (JM remains the main published set), so parquet purge for retired codes is
often a no-op while DB metadata rows may still exist until `retire-products --apply`.

## Goals / Non-Goals

**Goals:**

- Single source of truth: **60** active + **9** retired files, mutual exclusion enforced at load time.
- Fail-closed exact-match guards on CLI and MDS/sync write and read entry points.
- Minimal `retire-products` command with dry-run default and ordered hard delete + path purge.
- Docs and active OpenSpec counts updated to 60; task contract records production executions.

**Non-Goals:**

- Restoring the old `data_core/product_retirement` framework.
- Schema/Alembic changes to the eight tables.
- Deleting shared `exchanges` / `trading_calendars`.
- Treating change approval alone as production `--apply` authorization.

## Decisions

1. **Retired list file + loader module**  
   Use `data/universe/retired_products.txt` plus `market_data/product_retirement.py` (load frozenset, `assert_not_retired`, inventory/apply helpers) instead of a hardcoded-only constant, so universe files remain the audit trail.  
   Alternative considered: code-only frozenset — rejected to keep parity with `active_products.txt`.

2. **Exact membership only**  
   Normalize with `strip().lower()` then `in retired`. No prefix/suffix matching.  
   Alternative: regex — rejected (historical `T` vs `TA` risk class).

3. **Guard placement**  
   CLI `_products` / `_active_products`, maintenance update/refresh, MetadataSynchronizer, and MarketDataService query/list paths.  
   Alternative: CLI-only — rejected (API/Web could still surface or sync residuals).

4. **Minimal retire CLI, not a general framework**  
   `guiyi data retire-products [--apply]` fixed to the retired file list; no free-form symbol args that could widen blast radius.  
   Alternative: one-shot SQL scripts — rejected for testability and residual reporting.

5. **Delete order**  
   partitions → datasets → main_contract_map → sessions → contracts → instruments → filesystem under canonical root. Single DB transaction then filesystem.  
   Alternative: deactivate `is_active=false` — rejected (ghost dominants).

6. **Production gate**  
   Implementation ships the tool; each production `--apply` waits for a fresh scoped intent naming env + retired boundary.

## Risks / Trade-offs

- [Residual Web dominants before apply] → MDS filters retired symbols from `list_latest_dominants`; apply removes rows.
- [Accidental wide delete] → No free-form symbol list on retire command; only file-backed retired codes.
- [Path escape] → Resolve and require canonical-root containment before delete.
- [DFD-07 already empty parquet] → Apply reports zero path deletes; still succeeds.

## Migration Plan

1. Land repo: universe 60 + retired file + guards + CLI + tests + docs.
2. Dry-run against target DB/canonical root; review inventory JSON.
3. User issues one-shot intent → `--apply` → verify residual=0.
4. Mark `GY-DATA-PRODUCT-RETIREMENT-5` / STATUS with executed fact (non-sensitive counts only).

Rollback: restore codes to active files from Git and re-sync metadata from RQData; deleted parquet requires rebuild, not file undelete.
