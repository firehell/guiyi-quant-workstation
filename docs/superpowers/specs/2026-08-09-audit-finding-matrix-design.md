# Audit Finding Matrix Design

## Purpose

Make `HistoricalDataManager.audit()` complete a read-only active-universe
inspection even when individual products lack metadata. The result must expose
structured, per-product findings that can drive DFD-07 rebuild waves without
adding another audit engine or an operator script.

## Scope

Audit runs each requested product independently. A recognized metadata
integrity failure becomes an `AuditFinding` and the next product is audited.
The returned findings retain the exact failure code and add one category:

- `metadata_session` for historical Session facts and prior-day session context;
- `metadata_calendar` for Calendar and complete-trading-day facts;
- `metadata_window` for product-window or exchange identity facts;
- `main_contract_map` for rank-1 map coverage;
- `partition` for missing expected Canonical partitions;
- `physical` for Catalog/path, Parquet readability, row-count, or coverage
  inconsistency.

`year` and `month` are nullable only when a metadata failure prevents the
audit from locating a meaningful month. Existing partition and map findings
retain their current concrete month.

## Failure Policy

Only the known read-only coverage codes are converted to findings. Unexpected
exceptions still propagate through the existing CLI error boundary; audit must
not silently downgrade a programming, database, or storage-system failure.

The partition check returns the precise detected reason instead of a boolean.
This lets audit distinguish an absent expected partition from an unreadable or
inconsistent physical asset. Update and refresh continue to treat any such
reason as a whole-month rebuild target; their write semantics do not change.

## Data Flow

For every requested symbol, audit resolves that symbol's latest complete day,
product start, rank-1 map and expected month sequence. It records known
metadata failures at the boundary where they occur and continues with the next
symbol. For reachable months it records map, partition, and physical findings.
The result `through` is the minimum successful per-product complete day, or
`null` when no product can establish one.

## Verification

TDD tests must prove that a missing Session for one product yields a
`metadata_session` finding while another product is still audited, that a
missing Calendar becomes `metadata_calendar`, that a physical read failure
keeps its physical reason, and that an unknown exception still escapes.

After local tests pass, a production read-only active-universe audit at the
current fixed operational waterline produces the real 58-product matrix. It
must not initialize RQData or write PostgreSQL or Canonical Parquet.

## Non-Goals

This change does not synchronize metadata, repair Calendar/Session/Map rows,
rebuild partitions, add a batch update CLI, alter Runtime, enable live
services, or authorize any later `--apply` command.
