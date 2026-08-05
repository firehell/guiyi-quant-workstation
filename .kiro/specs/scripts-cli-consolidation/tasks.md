# Implementation Plan: Scripts CLI Consolidation

## Overview

Implement the design in Python by extending the existing `guiyi` argparse entrypoint and delegating to `app.data_core` and `app.services.rqdata_ingest`. Every implementation task must run in a dedicated task worktree; before editing, verify the current worktree is not the `develop` main worktree and preserve unrelated user changes. New commands and automated equivalence evidence must exist before any legacy entrypoint is deleted.

## Tasks

- [x] 1. Establish shared Python CLI contracts and target expansion
  - [x] 1.1 Implement validated request/result contracts and the safe JSON boundary
    - Add Python enums/dataclasses for dataset kinds, direct/derived frequencies, targets, effects, public errors, and command results under `app.services.data_operations`.
    - Extract the versioned JSON serializer/redactor from the monolithic CLI while keeping current commands operational.
    - Validate aware time windows, enum allow-lists, bounded inputs, and normalized allowed-root paths before dependency construction.
    - _Requirements: 1.5, 1.6, 1.7, 8.4, 8.6_
  - [x] 1.2 Implement deterministic single and batch target expansion
    - Add mutually exclusive single-symbol and bounded batch-manifest parsing.
    - Normalize and deduplicate exact identities without inferring Dataset_Kind or accepting caller-controlled output paths.
    - Keep batch ordering deterministic and report schema errors with stable public codes.
    - _Requirements: 1.2, 1.3, 1.4, 8.1_
  - [x]* 1.3 Write property test for explicit deterministic target expansion
    - **Property 1: Explicit and Deterministic Target Expansion**
    - Run at least 100 Hypothesis cases and tag `Feature: scripts-cli-consolidation, Property 1`.
    - **Validates: Requirements 1.2, 1.3, 1.4, 8.1**
  - [x]* 1.4 Write property test for invalid input effect isolation
    - **Property 2: Invalid Input Has No Effects**
    - Generate selector, enum, time, manifest and path failures; spy on all constructors/writers.
    - **Validates: Requirements 1.5, 1.6**
  - [x]* 1.5 Write property test for result-envelope completeness
    - **Property 3: Result Envelope Is Total**
    - Generate every outcome variant and validate serialization/redaction schema.
    - **Validates: Requirements 1.7**

- [x] 2. Implement direct historical download including pre-2020 coverage
  - [x] 2.1 Implement `DownloadApplicationService` over V2 historical synchronization
    - Create plan/apply orchestration for exact DatasetKeys and explicit `(start, end]` windows.
    - Reuse `HistoricalSynchronizer`, RQData adapter, staging, quality, canonical writer, Catalog/Manifest/Gap and bounded retries; do not copy algorithms into CLI code.
    - Support single and batch targets and preserve per-target results.
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 2.6, 2.7, 2.8_
  - [x] 2.2 Generalize listing/provider bounds and batching across all calendar eras
    - Remove fixed-2020 behavior from the new path and express unavailable prefixes as exact DataGap intervals.
    - Apply the same batch-size/retry controls to pre-2020 and later windows.
    - Do not import legacy pre-2020 file-anchor, CSV resume, or supersede-path code.
    - _Requirements: 3.1, 3.2, 3.3, 3.5_
  - [x] 2.3 Wire `guiyi data download` and reject legacy backfill aliases
    - Register the target command grammar with explicit Dataset_Kind, Direct_Frequency, start/end and `--apply` plan semantics.
    - Keep existing routes temporarily available for migration tests, but add no forwarding shim or pre-2020 alias.
    - _Requirements: 1.1, 2.1, 2.3, 3.2, 3.4_
  - [x]* 2.4 Write property test for date-agnostic exact missing windows
    - **Property 4: Exact Date-Agnostic Missing-Window Planning**
    - Compare generated covered intervals with a reference interval-difference model across the 2020 boundary.
    - **Validates: Requirements 2.1, 3.1, 3.5**
  - [x]* 2.5 Write property test for closed frequency sets
    - **Property 5: Frequency Sets Are Disjoint and Closed**
    - Generate supported and unsupported frequency values for download and aggregate parser/service boundaries.
    - **Validates: Requirements 2.3, 3.2, 4.5**
  - [x]* 2.6 Write property test for download identity preservation
    - **Property 6: Download Preserves Dataset Identity**
    - Generate both Dataset_Kind values and arbitrary valid identities/windows; assert provider and publication identity equality.
    - **Validates: Requirements 2.2, 2.4, 2.8**
  - [x]* 2.7 Write property test for batch outcome confluence
    - **Property 7: Batch Outcome Confluence**
    - Generate arbitrary ordered result vectors and execution chunkings.
    - **Validates: Requirements 2.7**
  - [x]* 2.8 Write property test for explicit unavailable historical prefixes
    - **Property 8: Unavailable Historical Prefix Is Explicit**
    - Generate listing/provider lower bounds and verify exact DataGap intervals without clamping.
    - **Validates: Requirements 3.3**
  - [x]* 2.9 Write download integration and boundary tests
    - Cover `1m/1d/1w`, successful atomic publish, each validation failure, retry exhaustion, partial batches, partial first week, and old-canonical preservation using mocks/isolated stores.
    - Assert plan mode performs no RQData or write effect.
    - _Requirements: 2.1–2.8, 3.1–3.5_

- [x] 3. Implement canonical-only aggregation
  - [x] 3.1 Implement `AggregateApplicationService`
    - Resolve exact Trusted_Canonical_1m through `MarketDataService` and existing Catalog/Gap rules.
    - Reuse `app.data_core.aggregation.aggregate_bars` and canonical publication for `5m/15m/30m/60m`.
    - Make RQData client construction unavailable from the aggregation dependency graph.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7_
  - [x] 3.2 Wire `guiyi data aggregate`
    - Add single/batch, explicit kind/identity/window, Derived_Frequency and plan/apply parsing and dispatch.
    - Reject direct frequencies before canonical reads.
    - _Requirements: 1.1, 4.1, 4.5_
  - [x]* 3.3 Write property test for deterministic identity-preserving aggregation
    - **Property 9: Trusted Aggregation Is Deterministic and Identity-Preserving**
    - Generate complete session-aligned minute bars and compare against a simple reference bucket model.
    - **Validates: Requirements 4.1, 4.2, 4.6, 4.7**
  - [x]* 3.4 Write property test proving aggregation never uses RQData
    - **Property 10: Aggregation Never Uses RQData**
    - Exercise valid and invalid requests with constructor/call spies.
    - **Validates: Requirements 4.3**
  - [x]* 3.5 Write property test for incomplete aggregate source rejection
    - **Property 11: Incomplete Aggregate Source Cannot Publish**
    - Remove or ambiguate generated minute/session/quality/coverage evidence and assert zero publication.
    - **Validates: Requirements 4.4, 4.7**
  - [x]* 3.6 Write aggregate integration tests
    - Cover each derived frequency, session boundaries, actual-dominant mapping, DataGap, incompatible duplicates, batch outcomes and canonical writer wiring.
    - _Requirements: 4.1–4.7_

- [x] 4. Implement observation-only live listening
  - [x] 4.1 Implement `LiveObservationApplicationService`
    - Accept explicit single/batch 1m identities and route received bars only to the existing live observation repository.
    - Enforce disabled/missing/expired/inconsistent configuration failure and expose no historical promotion method.
    - Keep Runtime promotion, notifications and orders disabled.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 4.2 Wire `guiyi data live`
    - Add explicit source-frequency and observation-write confirmation parsing with safe status output.
    - Treat confirmation as an effect selector, not persisted authorization.
    - _Requirements: 1.1, 5.1, 8.5_
  - [x]* 4.3 Write property test for live observation isolation
    - **Property 12: Live Writes Remain Observation-Only**
    - Generate target/bar streams and assert observation-only writes plus false historical/notification/order effects.
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.6**
  - [x]* 4.4 Write live unit and integration tests
    - Cover single/batch listeners, backpressure/failure, all disabled configuration states, repository wiring and safe cancellation.
    - Use finite fake streams; do not start a development server or long-running watcher.
    - _Requirements: 5.1–5.6_

- [x] 5. Consolidate metadata synchronization by delegation
  - [x] 5.1 Implement `MetadataSyncApplicationService`
    - Map six stable scopes to existing `app.services.rqdata_ingest` services.
    - Provide read-only plan and transactional apply orchestration without copying provider queries, normalization, mapping, reconciliation or upsert logic.
    - Execute `all` in instruments→contracts→calendar→sessions→main-contract-map order.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - [x] 5.2 Wire metadata-only `guiyi data sync`
    - Replace the current historical-sync meaning with explicit metadata scope grammar after download is available.
    - Keep plan as default and require `--apply` only as an effect selector.
    - _Requirements: 1.1, 6.1, 6.2, 8.5_
  - [x]* 5.3 Write property test for read-only metadata delegation
    - **Property 13: Metadata Plan Is Read-Only Delegation**
    - Generate scopes/filters with service fakes and compare delegated normalized results.
    - **Validates: Requirements 6.2, 6.3, 6.4**
  - [x]* 5.4 Write metadata sync unit and integration tests
    - Cover each scope, exact all-scope order, delegated failure rollback, MainContractMap ambiguity and static dependency rules against duplicate CLI algorithms.
    - _Requirements: 6.1–6.6_

- [x] 6. Implement read-only Audit V2
  - [x] 6.1 Implement `AuditV2ApplicationService`
    - Compose catalog, coverage, schema, physical and gap checks with stable finding codes and bounded non-sensitive facts.
    - Exclude provider and mutating repository capabilities from the audit dependency graph.
    - Preserve every component result for `all` and perform no repairs.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_
  - [x] 6.2 Wire `guiyi data audit`
    - Add stable scope/filter grammar without phase, stage, closeout or fixed-date names.
    - _Requirements: 1.1, 7.1, 7.5_
  - [x]* 6.3 Write property test for read-only complete audit composition
    - **Property 14: Audit Is Read-Only and Complete**
    - Generate inconsistent fixtures and sensitive facts; assert complete findings, redaction and zero effects.
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.6**
  - [x]* 6.4 Write audit unit and integration tests
    - Cover every scope, all-scope composition, Catalog/Manifest/physical/schema/coverage/DataGap disagreements, stable naming and no repair calls.
    - _Requirements: 7.1–7.6_

- [x] 7. Apply shared fail-closed V2 safety rules
  - [x] 7.1 Centralize trusted identity and gap guards
    - Reuse DatasetKey, Catalog/Manifest/Gap and MainContractMap authorities across download, aggregate and live target validation.
    - Reject incomplete/ambiguous rank=1 mappings, failed quality and intersecting DataGap without substitution or fallback.
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 7.2 Complete safe exception and effect reporting
    - Ensure every new command redacts exception text and sensitive details, distinguishes plan/apply effects, and reports `auto_order=false`.
    - _Requirements: 8.4, 8.5, 8.6_
  - [x]* 7.3 Write property test for ambiguous/untrusted data refusal
    - **Property 15: Ambiguous or Untrusted Data Fails Closed**
    - Generate mapping/gap/quality combinations and assert no fallback.
    - **Validates: Requirements 8.2, 8.3**
  - [x]* 7.4 Write property test for error redaction and disabled orders
    - **Property 16: Errors Are Redacted and Orders Stay Disabled**
    - Generate exceptions containing secret/SQL/path/URL/stack-like text for every command.
    - **Validates: Requirements 8.4, 8.6**
  - [x]* 7.5 Write shared safety integration tests
    - Assert argument failures precede dependency construction and effect flags never serve as persisted authorization.
    - _Requirements: 1.5, 1.6, 8.1–8.6_

- [x] 8. Codify the 145-script disposition and move retained operations
  - [x] 8.1 Implement the ordered disposition validator
    - Encode the design's family/glob plus exact-exception rules and regenerate tracked inventory at task start.
    - Fail on baseline drift, rule overlap, unmatched paths or incorrect 9/14/122 totals.
    - Keep protected resources and `.kiro/specs/personal-development-mode` outside all deletion plans.
    - _Requirements: 9.1, 9.2, 9.3, 11.2, 11.5_
  - [x]* 8.2 Write property test for total disposition partition
    - **Property 17: Disposition Manifest Is a Total Partition**
    - Mutate generated inventories/rules to cover additions, removals, overlaps and unmatched paths.
    - **Validates: Requirements 9.1, 9.2, 9.3**
  - [x] 8.3 Move retained operational scripts into target directories
    - Move four local development scripts to `scripts/dev/`, six launchd/Mac mini scripts to `scripts/ops/macos/`, `server-status.sh` to `scripts/ops/linux/`, and three health/tunnel scripts to `scripts/ops/network/`.
    - Preserve `scripts/engineering/` and reconcile independent worktree changes instead of overwriting them.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_
  - [x] 8.4 Update operational references and entrypoint tests
    - Update scripts, deploy templates, docs, Make targets and tests that invoke moved paths.
    - Add platform/layout and executable-reference validation.
    - _Requirements: 10.6_

- [x] 9. Complete replacement gates and active-reference cutover
  - [x] 9.1 Switch active data entrypoints and documentation to the new CLI
    - Update callers, Make targets, schedulers and active docs to download/aggregate/live/metadata sync/audit commands.
    - Retain protected historical evidence wording without converting historical receipts/reports into active authorization.
    - _Requirements: 9.4, 9.5, 9.7, 11.2_
  - [x] 9.2 Implement replacement-gate and reference-closure validation
    - Require passing replacement behavior checks, zero active non-historical references and all required validations before producing a repository deletion plan.
    - Reject forwarding wrappers, compatibility shims, Profile aliases and phase-numbered aliases.
    - _Requirements: 9.4, 9.5, 9.6, 9.7, 12.2, 12.6_
  - [x]* 9.3 Write property test for replacement-gate state transitions
    - **Property 18: Replacement Gate Permits No Early Deletion**
    - Generate replacement-test, reference and validation result vectors.
    - **Validates: Requirements 9.4, 9.5, 12.6**
  - [x]* 9.4 Write property test for protected-resource exclusion
    - **Property 19: Protected Resources Never Enter Repository Deletion**
    - Generate migration plans containing repository and protected resource types and assert protected exclusions.
    - **Validates: Requirements 11.2, 11.5**
  - [x]* 9.5 Write full replacement and reference integration tests
    - Exercise all new command paths with mocks/isolated fixtures, verify old/new supported behavior vectors, and run the active-reference scanner.
    - Confirm tests use at least 100 cases per property and no long-running process.
    - _Requirements: 9.4–9.7, 12.2, 12.3, 12.4_

- [x] 10. Remove superseded repository entrypoints only after the gate passes
  - [x] 10.1 Remove replaced data scripts and old data CLI routes
    - Delete all 71 `scripts/rqdata_*` paths and the five exact data replacement scripts after Tasks 2–9 and their tests pass.
    - Remove old `data plan`, historical meaning of old `data sync`, `data migrate`, `data task07`, pre-2020 aliases, Shell wrappers and their dedicated tests/active references.
    - Preserve reusable algorithms only under `app.data_core` or `app.services.rqdata_ingest`.
    - _Requirements: 3.4, 9.4, 9.5, 9.6, 11.1_
  - [x] 10.2 Remove backup/restore, S6/runtime, Profile and one-off script families
    - Delete the 5 backup, 3 restore, 27 old Runtime/history, 5 Profile/compat/history, 5 one-off export/audit and 1 old EOD Runtime Gate scripts plus dedicated code/tests/active references.
    - Do not delete receipts, reports, evidence, formal data, database state, Runtime state or external resources.
    - _Requirements: 11.1, 11.2, 11.3_
  - [x] 10.3 Remove remaining compatibility implementations and verify final source layout
    - Remove no-longer-referenced compatibility services/tests for Profile, old Runtime Gate, after-market and S6-07 through S6-10 where the replacement/reference gate authorizes repository deletion.
    - Assert final tracked scripts match the disposition manifest, old paths/commands have zero active references, and no shim remains.
    - _Requirements: 9.6, 9.7, 10.1–10.6, 11.1_
  - [x]* 10.4 Write final deletion-boundary and rollback checks
    - Verify source rollback relies on Git history and no backup directory, rollback tag, approval packet or deletion receipt is introduced.
    - Verify `.kiro/specs/personal-development-mode` is byte-for-byte untouched and protected resources never appear in deletion code.
    - _Requirements: 11.2, 11.3, 11.4, 11.5_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all affected CLI, data-core, backend, engineering, reference, documentation, secret, Shell/PowerShell and build checks pass; ask the user if questions arise.
  - Confirm implementation occurred in the Task_Worktree, no formal data/DB/Runtime/receipt/report/evidence operation was performed, and the migration is incomplete if any required check failed.
  - _Requirements: 12.1, 12.5, 12.6_

## Notes

- Tasks marked with `*` are optional test tasks in the task UI, but the Replacement_Gate must remain blocked if required replacement/property/integration evidence is absent.
- Property tests use Hypothesis with at least 100 generated cases and the exact feature/property tags from design.md.
- No task authorizes RQData production calls, formal Parquet/PostgreSQL mutations, Runtime/live enablement, notification sending, or protected deletion. Those operations require a separate exact human Gate when proposed.
- Source deletion uses Git history for rollback; do not create backup/restore artifacts, rollback tags, approval packets or deletion receipts.
- Do not modify `.kiro/specs/personal-development-mode`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "1.5", "2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3"] },
    { "id": 5, "tasks": ["2.4", "2.5", "2.6", "2.7", "2.8", "2.9"] },
    { "id": 6, "tasks": ["3.1", "4.1", "5.1", "6.1", "7.1", "8.1"] },
    { "id": 7, "tasks": ["3.2"] },
    { "id": 8, "tasks": ["3.3", "3.4", "3.5", "3.6", "4.2"] },
    { "id": 9, "tasks": ["4.3", "4.4", "5.2"] },
    { "id": 10, "tasks": ["5.3", "5.4", "6.2"] },
    { "id": 11, "tasks": ["6.3", "6.4", "7.2"] },
    { "id": 12, "tasks": ["7.3", "7.4", "7.5", "8.2"] },
    { "id": 13, "tasks": ["8.3"] },
    { "id": 14, "tasks": ["8.4"] },
    { "id": 15, "tasks": ["9.1"] },
    { "id": 16, "tasks": ["9.2"] },
    { "id": 17, "tasks": ["9.3", "9.4", "9.5"] },
    { "id": 18, "tasks": ["10.1"] },
    { "id": 19, "tasks": ["10.2"] },
    { "id": 20, "tasks": ["10.3"] },
    { "id": 21, "tasks": ["10.4"] }
  ]
}
```
