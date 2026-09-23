# Unified Reference Trading P8 acceptance

## Scope and fixed baseline

- Task branch: `codex/unified-reference-trading-p8`, based on `develop@636d70059466b6ab9089b8627afdf817331d2de3`.
- Plan: `docs/superpowers/plans/2026-09-23-unified-reference-trading-p8-plan.md`, SHA256 `4e5c05bd4922dc6461dc77719163efd85c307e3c3d15d5abed0a0b4001571375`.
- Source: isolated generated Canonical Bar fixtures, `MarketCatalog`, `MarketDataService`, and existing strategy kernels. Fixture evidence does not open a production product capability.
- Stores: disposable PostgreSQL 16 on loopback port 55433 with a tmpfs data directory and database `guiyi_reference_isolated_test`; disposable Redis 7 on loopback port 56380 with persistence disabled. Both are separate from the existing 5432/6379 services. No production `.env` was read.
- Environment: macOS, Python 3.13.9, `uv` project environment; no RQData/provider call.
- Performance goals frozen before benchmark work: warm keyset page p95 ≤500 ms; fixed-window summary p95 ≤1 s; 60 minute streams one round ≤60 s; 300 streams ≤15 minutes; no full historical replay per normal append; bounded queue/payload and no sustained RSS growth after repeated equal loads. First build/rebuild report size and time without an arbitrary pass threshold. Each measured scenario needs five independent repetitions and at least 100 warm queries per query repetition.

## Canonical requirement coverage map

| Canonical requirement | Existing or P8 evidence | Remaining P8 gap |
|---|---|---|
| Forward activation/capture separation | `test_activation`, `test_forward_capture`, `test_forward_service`, `test_newow_worker_recovery`; P8 PostgreSQL restart and disable race | Unknown commit on actual PostgreSQL and all strategy families |
| HTDY first-seen | `test_htdy_reference_model`, `test_htdy_reference_capture`, `test_forward_inputs` | Consecutive captured windows with later repaint and real PostgreSQL/API |
| Recording mode isolation | `test_contracts`, `test_query`, `test_forward_query` | Cross-mode Web readback |
| Action identity/ownership | `test_contracts`, `test_reducer`, `test_multi_owner_historical` | No additional synonymous unit test planned |
| Pure deterministic reducer | `test_reducer`, `test_checkpoint_parity` | No additional synonymous unit test planned |
| Capability evidence | `test_historical_planning`, `test_forward_inputs`, `test_worker_entry` | Product-specific independent evidence remains outside P8 fixture scope |
| Atomic durable revisions | `test_repository`, `test_repository_postgresql`; P8 PostgreSQL worker restart/race/lost acknowledgment readback | Process termination and unreadable acknowledgment receipt |
| Strict checkpoint/seed | `test_repository_seed`, `test_strategy_checkpoint`, `test_checkpoint_parity` | No additional synonymous unit test planned |
| Snapshot and future-fact isolation | `test_repository_snapshots`, `test_query`, `test_forward_query`; P8 PostgreSQL forward window summary | Real PostgreSQL historical/forward cutoff after later revisions |
| Historical plans and budgets | `test_historical_planning`, `test_multi_owner_historical`; P8 13-stream temporary Canonical/Catalog/MDS→PostgreSQL integration | More owner/Session revision combinations in same storage chain |
| Build/resume/advance/rebuild | `test_bootstrap`, `test_historical_incremental`, `test_revision_rebuild`; P8 PostgreSQL build/advance | Combined rebuild/old-snapshot PostgreSQL readback |
| Historical CLI | `test_reference_cli` | No additional synonymous unit test planned |
| Persisted presentation | `test_presentation`, `test_historical_integration`; P8 PostgreSQL build/advance | Browser source identity readback |
| Bounded P5 query | `test_query`, `test_query_postgresql`, `test_api`; P8 100/1000/10000 synthetic row query pagination | Five repetitions, exact query index plans, past cutoff at scale |
| Fail-closed page adapters | `test_persisted_subing_window`, `test_newow_persisted_query`, `test_api`; P8 PostgreSQL pipeline checks both adapters | Isolated real API/Web/browser acceptance |

## Runs to date

| Case | Level and input | Command/result | Status |
|---|---|---|---|
| P8-B0 | Fixture-only baseline, `develop@636d70059` | Reference tests plus 0047/0048 migration, `-m 'not isolated_postgresql'`: 202 passed, 1 skipped, 12 deselected, exit 0 | PASS for selected fixtures; Redis skip does not pass Redis acceptance |
| P8-PG0 | Disposable PostgreSQL 16, existing repository/query/migration cases | Four selected files, `-m isolated_postgresql`: 12 passed, 3 deselected, exit 0 | PASS |
| P8-RD0 | Disposable Redis 7, publish/wake | `test_live_wake.py` with `GUIYI_ISOLATED_REDIS_URL`: 2 passed, exit 0 | PASS |
| P8-H1 | Generated temporary Canonical/Catalog/MDS, 13 supported historical streams, SQLite | `test_historical_integration.py -m 'not isolated_postgresql'`: 1 passed, exit 0 | PASS fixture chain |
| P8-H2 | Same historical chain persisted in disposable PostgreSQL | `test_historical_integration.py -m isolated_postgresql`: 1 passed, exit 0 | PASS isolated PG chain |
| P8-F1 | Typed Newow canonical capture, durable PostgreSQL, restart worker, checkpoint and registered FastAPI readback | `test_newow_worker_recovery.py -m isolated_postgresql`: restart case passed | PASS for this fixture |
| P8-F2 | Disable before prepared worker commit, independent PostgreSQL sessions | Same command: passed | PASS for tested interleaving |
| P8-F3 | Durable commit followed by lost caller acknowledgment | Same command: receipt readback, one commit, no second calculation; passed | PASS for tested fault |
| P8-Q1 | Forward trade page and summary after close before window | `test_forward_query.py`: failed before fix (`initial_count=1` with empty page), then SQLite and PostgreSQL pass | PASS |
| P8-Q2 | Synthetic 100/1000/10000 trade-version rows | `test_query_capacity_postgresql.py`: 3 passed; 10,000-row case traversed 201 pages | PASS for generated query load only |
| P8-W1 | Route-intercepted SuBing browser UI | Playwright `e2e/subing-reference.spec.mjs`: 10 passed; API proxy 502 logs reflect the intentionally absent backend | PASS UI fixture only; real browser chain pending |
| P8-R1 | Reference and 0047/0048 migration fixture regression after fixes | `pytest ... -m 'not isolated_postgresql'`: 213 passed, 1 skipped, 20 deselected, exit 0 | PASS for selected fixtures; the Redis skip is not Redis evidence |
| P8-R2 | Complete selected isolated PostgreSQL regression after fixes | `pytest ... -m isolated_postgresql`: 20 passed, 214 deselected, exit 0 | PASS on dedicated PG; initial run with wrong role failed at connection and was corrected before this run |
| P8-R3 | Benchmark guard regression and changed Python lint | `test_benchmark_safety.py`: 11 passed; Ruff on changed Python files: exit 0; `git -c core.fsmonitor=false diff --check`: exit 0 | PASS |

The PostgreSQL tests use a new random schema per run and drop only that schema. The historical fixture creates its own temporary Canonical files. The tested Newow forward stream is a fixture candidate; its Runtime remains disabled. The benchmark rejects URL query overrides and libpq `PG*` environment routing before connecting; both bypasses were found in independent Review and shown to fail before the fix.

## Exploratory measurements before final commit

Raw uncommitted-worktree results: `/var/folders/5f/3h8_rqbd2nnf_yz0rg3zhhym0000gn/T/guiyi-p8-historical-25f9.json` and `guiyi-p8-forward-25f9.json` in the same directory. Both report `develop@636d70059` as HEAD, so they are **not** final-SHA evidence.

| Workload | Independent repeats | Observed result | Limit |
|---|---:|---|---|
| 13-stream temporary Canonical/Catalog/MDS→PG build/advance/API | 5 | wall median 18.337 s, range 18.258–18.364 s | First build has no frozen seconds target; this fixture has no trade records |
| Newow forward capture/restart/API over PG | 5 | wall median 2.659 s, range 2.631–2.908 s | One stream/one Bar; excludes 60/300 stream budget |
| 10,001 synthetic trade versions, 201 keyset pages, 100 reads per query kind | 1 exploratory run | warm p95: first page 88.514 ms, summary 180.438 ms; earlier deep-page 24.714 ms measured only the final one-row page and is invalid for a full 50-row deep page | Must repeat five times under final SHA; rows bypass strategy calculation |

The 13-stream historical fixture uses fixed close 3500 and produced zero trades. Its query timings, if emitted, are empty-trade-table measurements and cannot establish 100/1000/10000 trade capacity. The synthetic rows all share one entry action and presentation identity and contain no CLOSED trades, marks, or version history; they exercise SQL pagination/summary only, not full trade semantics or past-cutoff behavior.

## Independent review

GPT-6 Astra independently inspected the integration, forward summary and identity fixes, benchmark guard, and synthetic capacity test. Three confirmed defects were repaired with failing-then-passing tests: connection override protection, forward summary initial-count alignment, and invalid test identity. A follow-up review found that the initial deep-page benchmark sampled a one-row tail page; the fixture now asserts a full 50-row deep page, and the old deep-page number above is invalid. No new code blocker was found for committing this partial engineering increment. Remaining risks are the incomplete workload coverage and unmeasured P8 cases listed below; this review does not grant P8 overall acceptance.

## Current acceptance boundary

P8 is in progress. The matrix still lacks real isolated API/Web browser evidence, all-family forward end-to-end evidence, crash-process recovery, 60/300 stream throughput and fairness, five repeated final-SHA capacity results, and normal D1/W1 incremental input cost evidence. The D1/W1 reader currently starts at recording start on every capture and needs a measured bounded-input repair before the normal-incremental target can pass. No release candidate or P9 production action follows from the passing cases above. The exact final commit/tree and independent Review will be recorded after remaining work.
