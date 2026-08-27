# SuBing Performance Incremental Snapshots Design

**Status:** Approved by user on 2026-08-27

**Date:** 2026-08-27

**Repository base:** `origin/develop@f896730554d57149b27b675e5346b59563a951b9`

## 1. Goal

Replace the current full-window performance read path with two explicit operations:

1. after-market refresh recomputes only the affected physical-contract tail and atomically publishes one complete current product snapshot;
2. the HTTP performance endpoint reads and validates that published snapshot directly, without invoking Historical replay or writing cache data.

The initial active60 warm remains the only normal all-history bootstrap. Later refreshes are segment-tail incremental. A broad source or semantic identity change fails closed with `SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED`; it never silently mixes incompatible history.

## 2. Current problem

The current `SubingStrategyPerformanceService.performance()` always calls the Historical projection before it can inspect the performance cache. Consequently:

- an HTTP request can load and digest the full `actual_dominant + 15m` window before reporting a cache hit;
- the natural after-market derived stage traverses all active60 full windows;
- immutable historical segment projections may hit their nested cache, but the caller still loads the complete product window and rebuilds the aggregate response;
- the immutable performance files have no authoritative current pointer, so a consumer cannot select a snapshot without recomputing its identity or globbing files.

## 3. Scope

### In scope

- a deep `SubingStrategyPerformanceSnapshotStore` module with a small read/publish interface;
- immutable content-addressed product snapshots plus one atomic current manifest per product;
- strict adoption of the existing schema-v2 snapshots produced by the in-progress initial warm;
- segment-tail incremental refresh for the after-market derived phase;
- direct, read-only HTTP snapshot serving;
- exact freshness, lineage, rollover, atomicity, parity, and fail-closed tests;
- canonical documentation and testing-command updates required by the change.

### Out of scope

- strategy, Factor, Lifecycle, Action, Episode, fill timing, or exit-formula changes;
- serializing or persisting `SubingStrategyMachineState`;
- bar-by-bar checkpoints;
- PostgreSQL or Alembic changes;
- RQData calls, Canonical writes, MainContractMap writes, Runtime promotion, Alert Scope, notifications, or orders;
- a generic backtest/result platform, worker, queue, scheduler, account, position, PnL, or equity-curve domain;
- automatic full rebuild or automatic retry after an identity mismatch.

## 4. Safety and execution boundaries

The implementation must not stop, signal, restart, inspect private process state, write into, rename, or delete artifacts used by the currently running full warm. It is developed in a separate worktree and uses only temporary test roots.

The current production-format warm remains a separate, single-use external write Gate. This repository change does not authorize:

- adopting its results into current manifests;
- executing a new active60 refresh;
- changing the deployed Runtime;
- writing production DB/Redis/Scope state;
- sending notifications.

If implementation or verification cannot proceed without affecting the running warm, work stops and reports `BLOCKED`; the warm is not interrupted.

## 5. Design principles

1. **Canonical lineage remains authoritative.** Historical reads continue through `MarketDataService`; no consumer globs Canonical files or infers rank1.
2. **One strategy implementation.** Incremental refresh reuses the existing Historical projection and pure machine for the affected tail; it does not copy formulas.
3. **Physical-segment isolation.** SuBing state never crosses a rank1 physical contract segment, so the earliest affected segment is the safe recomputation seam.
4. **Snapshot reads are shallow in cost, deep in validation.** HTTP callers learn only `read_current(symbol, expected_through)`, while the store owns path validation, hash validation, schema parsing, and freshness.
5. **No silent compatibility.** Identity drift outside the recomputed tail requires a new explicit full rebuild.
6. **Publication is atomic.** A current manifest changes only after the immutable snapshot has been written, fsynced, read back, and validated.

## 6. Modules and interfaces

### 6.1 `SubingStrategyPerformanceSnapshotStore`

The external seam is:

```python
class SubingStrategyPerformanceSnapshotStore(Protocol):
    def read_current(
        self,
        *,
        symbol: str,
        expected_through: date,
    ) -> SubingStrategyPerformanceSnapshot: ...

    def publish_current(
        self,
        snapshot: SubingStrategyPerformanceSnapshot,
    ) -> SubingStrategyPerformanceSnapshotReceipt: ...
```

`read_current` performs no Historical read and no write. Missing, stale, future-dated, malformed, symlinked, identity-mismatched, or hash-mismatched artifacts raise the fixed public cache-unavailable error.

`publish_current` writes an immutable snapshot first, reads it back through the same parser, then atomically replaces the current manifest. A failed snapshot write or readback preserves the last current manifest.

### 6.2 `SubingStrategyPerformanceIncrementalRefresher`

The after-market seam is:

```python
class SubingStrategyPerformanceIncrementalRefresher:
    def refresh(
        self,
        *,
        symbol: str,
        through: date,
    ) -> SubingStrategyPerformanceProjection: ...
```

The refresher owns bootstrap/adoption, lineage comparison, tail selection, Historical tail replay, merge, summary recomputation, and snapshot publication. Callers do not select files or determine segments.

### 6.3 Read-only query module

The HTTP route depends on a read-only query interface:

```python
class SubingStrategyPerformanceSnapshotQuery:
    def current(self, symbol: str) -> SubingStrategyPerformanceProjection: ...
```

The query resolves the expected complete day from existing Catalog coverage and dominant-mapping metadata, then calls `snapshot_store.read_current`. It does not construct `SubingStrategyHistoricalService`.

## 7. Artifact layout

All files remain under the existing Git-external validated root:

```text
cache/subing-strategy-v1/performance/
  snapshots/<symbol>/<through>/<snapshot_sha256>.json
  current/<symbol>.json
  legacy/<existing schema-v2 layout remains read-only>
```

The implementation does not move or rewrite files created by the in-progress warm. The `legacy/` name above is conceptual: existing `performance/<symbol>/<through>/<identity>.json` paths remain where they are and are eligible only for one-time strict adoption.

### 7.1 Immutable snapshot schema v3

Each snapshot contains:

- fixed `schema_version=3`;
- strategy/formula/engine identities;
- `symbol`, `actual_dominant`, `15m`, `coverage_since`, `coverage_through`, and `resolved_cutoff`;
- complete display payload and Episodes;
- prefix aggregate counts for segments older than the mutable tail;
- ordered tail-segment facts: contract, rank1 start/end, loaded-through, source identity, Bar counts, context-unavailable count;
- source-manifest identity derived from existing Catalog dataset/partition lineage and MainContractMap facts;
- payload, identity, and whole-snapshot SHA-256 values;
- aware UTC generation timestamp.

The snapshot contains no credentials, internal absolute paths, provider references, account/order facts, or mutable DB identifiers.

### 7.2 Current manifest schema v1

Each `current/<symbol>.json` contains only:

- `schema_version=1`;
- symbol and through date;
- relative immutable snapshot path;
- snapshot, identity, and payload SHA-256 values;
- generation timestamp;
- manifest SHA-256.

The store rejects absolute paths, `..`, symlinks, paths outside the validated root, non-regular files, duplicate keys, unexpected schema versions, and mismatches between manifest and snapshot.

## 8. Initial schema-v2 adoption

Adoption is a write-capable operation and is never performed by the HTTP route.

For each exact active product and exact expected through date, the adopter:

1. resolves the exact legacy directory under the validated root;
2. requires exactly one owner-controlled regular JSON candidate and no temporary files;
3. parses the schema-v2 envelope and verifies symbol, through, fixed product identity, identity hash, payload hash, snapshot hash, and payload structure;
4. resolves the ordered rank1 segment list from Catalog and requires its count/order to agree with the legacy segment identity list;
5. replays only the legacy mutable tail through the legacy cutoff to establish tail counts and derive prefix aggregates;
6. publishes a schema-v3 immutable snapshot and current manifest;
7. leaves the schema-v2 artifact untouched.

Any ambiguity or mismatch returns `SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED`. Adoption does not guess the newest file and does not retain multiple active manifests.

Executing adoption against the real Git-external root requires a fresh, explicit one-time cache-write authorization after implementation is released to the selected Runtime.

## 9. Incremental refresh algorithm

For a product with a valid current schema-v3 snapshot:

1. resolve the new expected window and ordered rank1 segment facts through `through`;
2. require monotonic coverage: the new through date cannot precede the current snapshot;
3. compare strategy/formula/engine and Catalog/MainContractMap source-manifest identities;
4. find the earliest affected physical segment;
5. require every segment before that seam to be identical to the current snapshot prefix;
6. replay Historical only from the affected segment start through the new date with `publish_cache=True`;
7. discard prior Episodes belonging to the affected tail and merge the new tail Episodes with the immutable prefix Episodes;
8. recompute full summary statistics from the merged Episodes;
9. recompute total counts as immutable prefix counts plus new tail counts;
10. publish and read back the new immutable snapshot;
11. atomically replace the current manifest.

### 9.1 Normal daily append

Normally the earliest affected segment is the current rank1 physical segment. Older segments and their Episodes are not loaded or replayed.

### 9.2 Rollover

When rank1 rolls, refresh starts at the previously mutable segment. The old tail is replayed through its terminal day, the new segment starts from a flat isolated state, and completed old-tail facts are compacted into the immutable prefix after successful publication.

### 9.3 Same-day/no-change refresh

If through date, source-manifest identity, and engine identity are unchanged, refresh returns the validated current snapshot as a cache hit and performs no write.

### 9.4 Broad drift

The refresher returns `SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED` without publishing when:

- strategy, calibration, Lifecycle, Daily Context, or engine identity changes;
- a MainContractMap change affects a segment before the mutable tail;
- a Canonical dataset/partition lineage change affects the immutable prefix;
- coverage moves backward;
- the current manifest or snapshot is missing/corrupt;
- the tail replay does not reach the requested through date;
- merged Episodes violate physical-segment, identity, uniqueness, or ordering invariants.

No automatic fallback to a full rebuild is allowed.

## 10. HTTP behavior

`GET /api/v1/market/research/subing-strategy/performance?symbol=<symbol>`:

1. validates the active product;
2. resolves `expected_through` using existing lightweight Catalog coverage and dominant-mapping metadata;
3. calls `snapshot_query.current(symbol)`;
4. returns the existing response schema from the parsed snapshot.

The route must not:

- call Historical replay;
- read Canonical Bar files;
- publish/adopt/repair cache;
- glob directories;
- fall back to stale or older snapshots.

Missing or stale snapshots retain the current `409` fail-closed response with a fixed public code. No internal path, hash detail, SQL, or stack trace is exposed.

## 11. After-market behavior

The derived phase still receives the exact operational product tuple and reports one result per product. Each product is refreshed independently through the incremental refresher.

- one product failure makes only the derived phase `degraded`;
- successful Canonical publication remains successful;
- there is no derived retry, notification, AlertEvent, Scope mutation, or Runtime switch;
- status continues to expose only fixed counts, batch identity, and fixed public error codes;
- the batch identity binds exact products, through date, current snapshot identities, and resulting snapshot identities.

The first release may remain serial. Parallel workers are not part of this change; correctness and deterministic publication precede throughput tuning.

## 12. Compatibility and cleanup

- Existing schema-v2 performance artifacts are accepted only by the explicit adopter.
- HTTP and normal incremental refresh use only current schema-v3 manifests after adoption.
- Existing nested Historical segment caches remain expendable and compatible; no second Historical data path is introduced.
- Old immutable snapshots may remain for recovery/audit until a separately approved cache-pruning policy exists. They are never selected by glob or mtime.
- No legacy reader remains on the normal request path after adoption.

## 13. Verification requirements

### Store and codec

- publish writes immutable snapshot before current manifest;
- failed write/readback preserves the previous current manifest;
- direct read validates every hash and path invariant;
- stale/future/malformed/symlinked artifacts fail closed;
- schema-v2 adoption is exact and leaves source files unchanged.

### Incremental parity

- same-day no-change produces a hit and zero writes;
- one new trading day replays only the prior mutable tail;
- merged result equals an independent full replay for Actions, Episodes, summaries, Bar counts, cutoff, and source identities;
- rollover parity covers terminal close, flat reset, no cross-segment position, and pending-action cancellation semantics;
- prefix canonical or mapping drift produces `FULL_REBUILD_REQUIRED` and preserves the previous manifest;
- causality, strict-before, future-leak, prefix invariance, and golden parity tests remain green.

### HTTP

- a successful request exercises the real snapshot store and never invokes Historical replay;
- missing/stale/corrupt snapshot returns fixed `409` unavailable;
- requests are read-only and create no files;
- the existing wire response and Web normalization remain compatible.

### After-market

- exact active60 accounting remains enforced;
- partial failures remain derived-only degraded;
- Canonical success, Live cleanup, notification behavior, and retry behavior are unchanged;
- no production operation is executed during repository tests.

## 14. Acceptance criteria

The change is accepted only when:

1. direct API tests prove zero Historical calls and zero writes;
2. incremental-tail results are byte/field equivalent to independent full replay fixtures;
3. rollover and prefix-drift cases fail or merge exactly as specified;
4. snapshot and manifest atomicity tests pass;
5. targeted backend, data-foundation, API, after-market, Ruff, Mypy, canonical consistency, OpenSpec, secret scan, and diff checks pass;
6. independent exact-head Review finds no strategy-semantic, lineage, authorization, or data-path regression;
7. the implementation is merged only to `develop` under normal repository workflow;
8. no real cache adoption, Runtime promotion, production write, Scope change, notification, release, or tag is performed.

## 15. Rollback

Repository rollback is a normal Git revert of the feature commits before any Runtime promotion. Existing schema-v2 artifacts remain untouched.

If a later authorized adoption or Runtime promotion has occurred, rollback must point Runtime back to the previously approved release and retain the last valid immutable snapshots. Manifests are expendable derived state; deleting or replacing real manifests still requires an explicit cache-write authorization. No rollback modifies Canonical, Catalog, MainContractMap, Alert, Scope, or notification facts.
