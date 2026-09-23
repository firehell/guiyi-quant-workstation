# Unified Reference Trading P8 acceptance

## Scope and fixed baseline

- Task branch: `codex/unified-reference-trading-p8`, based on `develop@636d70059466b6ab9089b8627afdf817331d2de3`.
- Plan: `docs/superpowers/plans/2026-09-23-unified-reference-trading-p8-plan.md`, SHA256 `4e5c05bd4922dc6461dc77719163efd85c307e3c3d15d5abed0a0b4001571375`.
- Source: isolated generated Canonical Bar fixtures, `MarketCatalog`, `MarketDataService`, and existing strategy kernels. Fixture evidence does not open a production product capability.
- Stores: disposable PostgreSQL 16 on loopback port 55433 with a tmpfs data directory and database `guiyi_reference_isolated_test`; disposable Redis 7 on loopback port 56380 with persistence disabled. Both are separate from the existing 5432/6379 services. No production `.env` was read.
- Environment: macOS, Python 3.13.9, `uv` project environment; no RQData/provider call.
- Performance goals frozen before benchmark work: warm keyset page p95 ≤500 ms; fixed-window summary p95 ≤1 s; 60 minute streams one round ≤60 s; 300 streams ≤15 minutes; no full historical replay per normal append; bounded queue/payload and no sustained RSS growth after repeated equal loads. First build/rebuild report size and time without an arbitrary pass threshold. Each measured scenario needs five independent repetitions and at least 100 warm queries per query repetition.
- Query baseline measured at `90755ccf26be4887f69921ed6065bbef266777b9`. The five new evidence cases below were measured at clean code commit `e54840e0cb630731370c6dbe346cde528f965669`; this documentation update follows those runs.

## Canonical requirement coverage map

| Canonical requirement | Existing or P8 evidence | Remaining P8 gap |
|---|---|---|
| Forward activation/capture separation | `test_activation`, `test_forward_capture`, `test_forward_service`, `test_newow_worker_recovery`; P8 PostgreSQL restart, disable race, all Newow strategies on D1/W1/60m, SuBing 15m/30m/60m and HTDY first-seen | Actual multi-Bar action/reversal coverage across every family remains narrower than the fixture matrix |
| HTDY first-seen | `test_htdy_reference_model`, `test_htdy_reference_capture`, `test_forward_inputs` | Consecutive captured windows with later repaint and real PostgreSQL/API |
| Recording mode isolation | `test_contracts`, `test_query`, `test_forward_query` | Cross-mode Web readback |
| Action identity/ownership | `test_contracts`, `test_reducer`, `test_multi_owner_historical` | No additional synonymous unit test planned |
| Pure deterministic reducer | `test_reducer`, `test_checkpoint_parity` | No additional synonymous unit test planned |
| Capability evidence | `test_historical_planning`, `test_forward_inputs`, `test_worker_entry` | Product-specific independent evidence remains outside P8 fixture scope |
| Atomic durable revisions | `test_repository`, `test_repository_postgresql`; P8 PostgreSQL worker restart/race/lost acknowledgment readback and child `os._exit` before/after commit | Host power loss and production storage failure remain outside isolated evidence |
| Strict checkpoint/seed | `test_repository_seed`, `test_strategy_checkpoint`, `test_checkpoint_parity` | No additional synonymous unit test planned |
| Snapshot and future-fact isolation | `test_repository_snapshots`, `test_query`, `test_forward_query`; P8 PostgreSQL forward window summary | Real PostgreSQL historical/forward cutoff after later revisions |
| Historical plans and budgets | `test_historical_planning`, `test_multi_owner_historical`; P8 13-stream temporary Canonical/Catalog/MDS→PostgreSQL integration | More owner/Session revision combinations in same storage chain |
| Build/resume/advance/rebuild | `test_bootstrap`, `test_historical_incremental`, `test_revision_rebuild`; P8 PostgreSQL build/advance | Combined rebuild/old-snapshot PostgreSQL readback |
| Historical CLI | `test_reference_cli` | No additional synonymous unit test planned |
| Persisted presentation | `test_presentation`, `test_historical_integration`; P8 PostgreSQL build/advance | Browser source identity readback |
| Bounded P5 query | `test_query`, `test_query_postgresql`, `test_api`; P8 100/1000/10000 synthetic row query pagination and five code-commit-bound repetitions | Exact query index plans, realistic closed/versioned trade mix, past cutoff at scale |
| Fail-closed page adapters | `test_persisted_subing_window`, `test_newow_persisted_query`, `test_api`; P8 PostgreSQL pipeline checks both adapters; Playwright CLI readback through actual Vue panel, FastAPI and PG | Complete Market detail route, broader page error matrix and natural Runtime readback |

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
| P8-W1 | Route-intercepted SuBing browser UI | Playwright `e2e/subing-reference.spec.mjs`: 10 passed; API proxy 502 logs reflect the intentionally absent backend | PASS UI fixture only; superseded for real API readback by P8-B1 |
| P8-R1 | Reference and 0047/0048 migration fixture regression after fixes | `pytest ... -m 'not isolated_postgresql'`: 213 passed, 1 skipped, 20 deselected, exit 0 | PASS for selected fixtures; the Redis skip is not Redis evidence |
| P8-R2 | Complete selected isolated PostgreSQL regression after fixes | `pytest ... -m isolated_postgresql`: 20 passed, 214 deselected, exit 0 | PASS on dedicated PG; initial run with wrong role failed at connection and was corrected before this run |
| P8-R3 | Benchmark guard regression and changed Python lint | `test_benchmark_safety.py`: 11 passed; Ruff on changed Python files: exit 0; `git -c core.fsmonitor=false diff --check`: exit 0 | PASS |
| P8-F4 | All three Newow strategies × D1/W1/60m, SuBing × 15m/30m/60m, HTDY first-seen, persisted PostgreSQL worker/readback | `test_newow_worker_recovery.py -m isolated_postgresql`: 18 passed, 8 deselected | PASS fixture-only; not a production capability opening |
| P8-C1 | Child process exits before and after PG commit, parent opens new connection/restarts worker and checks one outcome | `test_newow_worker_recovery.py -k process_crash -m isolated_postgresql`: 2 passed × 5 independent runs, exit 0 | PASS isolated process-crash recovery |
| P8-I1 | D1/W1 unconsumed Canonical window with original owner/calculation IDs; comparison to full reader; gap, unfinished day and 45-day refusal | `test_historical_integration.py -m isolated_postgresql`: 1 passed × 5 independent clean-code runs | PASS bounded append within fixture window; missing published Canonical still fails closed |
| P8-S1 | 60 products × Newow trend 60m; typed capture, PG persistence, kernel worker and queue drain | `reference_trading_benchmark.py --case stream_60 --repeats 5`: all pass | PASS isolated fixture capacity |
| P8-S2 | 60 products × Newow three strategies 60m, SuBing 60m, HTDY 15m | `reference_trading_benchmark.py --case stream_300 --repeats 5`: all pass | PASS isolated fixture capacity; no real 300-stream MDS load |
| P8-S3 | Same 300 streams; temporary physical Canonical, Catalog/rank-1, real `MarketDataService.query_page`, durable capture and kernel worker | `reference_trading_benchmark.py --case stream_300_mds --repeats 5 --timeout-seconds 120`: five passes at clean code commit `159d3ecf3`; 300 calculations and zero pending each | PASS isolated real-MDS implementation throughput; generated bars and test-only observation adapter |
| P8-B1 | Actual Vue panel/Vite proxy/FastAPI/PG, Newow oscillation 1d historical and three forward families; no route interception | Playwright CLI open/snapshot/click; 50 CLOSED + 1 OPEN, page 2 appends row 51, HTDY first-seen, disabled-mode readback; API requests 200, sole console error was missing fixture favicon | PASS isolated component/API/DB E2E; not full Market route |
| P8-R4 | Final affected Python/Web verification | non-PG selected suite: 438 passed, 1 skipped, 35 deselected; isolated PG selected suite: 36 passed, 213 deselected; targeted query/input/guard: 132 passed; `pnpm -C apps/quant-web build`: exit 0 | PASS; skip is not Redis evidence |

The PostgreSQL tests use a new random schema per run and drop only that schema. The historical fixture creates its own temporary Canonical files. The tested Newow forward stream is a fixture candidate; its Runtime remains disabled. The benchmark rejects URL query overrides and libpq `PG*` environment routing before connecting; both bypasses were found in independent Review and shown to fail before the fix.

## Final code-commit measurements

The raw JSON files are in the local system temporary directory `/var/folders/5f/3h8_rqbd2nnf_yz0rg3zhhym0000gn/T/`, named `guiyi-p8-<case>.json`. All five files report the measured commit above, `dirty_worktree=false`, PostgreSQL 16.14, Python 3.13.9, and five successful independent processes. Each query process makes 100 warm requests per query kind. A larger wall time in some repetitions is preserved in the ranges; its cause was not isolated.

| Case | Rows / scope | Five-process wall median (range) | Worst repetition warm p95 | Peak observed child RSS |
|---|---|---|---|---|
| `query_100` | 101 synthetic versions; 3 keyset pages | 5.780 s (5.709–5.888) | first 19.361 ms; full deep 19.336 ms; summary 14.998 ms | 111,584 KiB |
| `query_1000` | 1,001 synthetic versions; 21 pages | 59.639 s (10.551–60.346) | first 201.459 ms; full deep 201.598 ms; summary 542.801 ms | 115,376 KiB |
| `query_10000` | 10,001 synthetic versions; 201 pages | 118.278 s (63.990–119.982) | first 109.064 ms; full deep 58.215 ms; summary 199.981 ms | 144,480 KiB |
| `historical_13_streams` | Temporary Canonical/Catalog/MDS→PG build/advance/API; 576 actions, 288 trade versions, 285 marks across all streams | 22.409 s (21.819–22.933) | one stream: trades 22.198 ms; summary 23.115 ms | 277,008 KiB |
| `forward_recovery` | One Newow canonical Bar, durable capture/restart/API | 2.671 s (2.642–2.715) | no query timing sampled | 237,488 KiB |

The three synthetic SQL workloads met the frozen warm page and summary p95 limits in all five repetitions. This is a **limited capacity pass**, not P8 performance acceptance: the generated versions all share one entry action and presentation identity and contain no CLOSED trades, marks, or version history. The 13-stream total includes real projected rows, but its query timing targets one stream and does not prove the 100/1,000/10,000-row shape. The earlier exploratory deep-page result was invalid because it measured a one-row tail page; it is superseded by the full 50-row measurements above. The follow-up 60/300 and bounded-append measurements are recorded below; rebuild, index-plan, and sustained-memory goals remain unmeasured.

## Follow-up clean-commit measurements

The three JSON files `guiyi-p8-stream_60.json`, `guiyi-p8-stream_300.json`, and
`guiyi-p8-historical_13_streams.json` are in the system temporary directory named above.
They all report code commit `e54840e0cb630731370c6dbe346cde528f965669`, `dirty_worktree=false`,
PostgreSQL 16.14, Python 3.13.9, five independent successful processes and zero pending
captures after worker drain.

| Case | Workload | Five-process median, range | Peak child RSS range | Result boundary |
|---|---|---|---|---|
| `stream_60` | 60 products, Newow trend 60m; typed capture + PG + kernel | capture-to-project 2.969 s (2.950–3.024); worker 1.580 s (1.575–1.607) | 155,616–156,496 KiB | 60/60 calculations, four queue rounds, under frozen 60 s |
| `stream_300` | 60 products × five fixture strategy families | capture-to-project 15.128 s (15.104–15.322); worker 7.948 s (7.945–8.139) | 156,880–158,080 KiB | 300/300 calculations, 19 queue rounds, under frozen 15 min |
| `historical_13_streams` | Temporary Canonical/Catalog/MDS→PG; each run also checks D1/W1 bounded append against full Bar identity | whole run 20.590 s (20.399–20.683); worst warm query p95 19.777 ms trade and 19.300 ms summary | 238,288–242,592 KiB | 576 actions, 288 trade versions, 285 marks; five passes |

The D1/W1 test asserts no full reader invocation after a durable watermark, equivalent
physical Bar hash/owner/calculation identity, at most four physical partitions read per
normal append in its 84-day fixture, a typed two-Bar gap, no read on an unfinished day,
and rejection before MDS if the watermark is older than 45 days. The bound applies to
normal appends; an overdue or missing Canonical input remains blocked for explicit
recovery. The 60/300 timer includes fixture seed, typed capture and PostgreSQL writes
before worker projection; MarketRead is a controlled in-memory fixture, so these numbers
do not measure 300 real MDS reads or production data freshness. Repeated independent
process peak RSS was stable in this workload, but this is not a sustained single-process
memory soak or PostgreSQL index-plan proof.

## Real MDS acquisition follow-up

The `stream_300_mds` benchmark publishes 60 products × two physical period partitions
into a temporary Canonical root and registers them with an isolated PostgreSQL Catalog.
Each of the 300 stream captures calls the real `MarketDataService.query_page` on the
rank-1 actual-dominant series; 60 HTDY captures also read a 32-Bar MDS context page.
The test checks returned Bar and physical owner on every read, then persists all
captures and runs the real strategy worker. Fixture publication/setup occurs before
the timed window. The five independent processes used clean code commit
`159d3ecf34d3599ac38a9a81c7eab3e2131347bc`, PostgreSQL 16.14 and Python 3.13.9.
Raw results: `guiyi-p8-stream_300_mds.json` in the same system temporary directory.

| Five-run metric | Median | Range |
|---|---:|---:|
| 360 MDS reads within capture loop | 2.429 s | 2.402–2.466 s |
| MDS + typed capture + PostgreSQL seed/write | 9.696 s | 9.625–9.797 s |
| Worker projection and queue drain | 8.071 s | 7.916–8.124 s |
| Capture-to-projection total | 17.828 s | 17.548–17.913 s |
| Observed child peak RSS | — | 169,568–170,528 KiB |

All five runs produced 300/300 calculations, 19 queue rounds, and zero pending
captures, within the frozen 15-minute target. The first real MDS run exposed a
previously hidden Newow forward defect: Parquet readback encodes integral volume and
open interest as scale-18 Decimal text; direct `int(text)` blocked 180 Newow streams.
The evaluator now accepts only finite, integral Decimal encodings before converting
to integer. The affected isolated PostgreSQL capacity/recovery/safety regression
passed `46 passed`, and the focused non-PostgreSQL recovery suite passed `14 passed`.

The data are generated, one-day and one-contract fixture facts; all products use a
test exchange/session and common prices. `_MdsMarketRead` is a test adapter that
presents completed historical MDS results to the capture path as observations.
These results establish real Catalog/Parquet/MDS implementation throughput, not
production data freshness, real Live acquisition, or natural Runtime behavior.
Direct test publication of 15m/60m partitions does not exercise the upstream
Canonical 1m aggregation Gate.

## Independent review

GPT-6 Astra independently inspected the integration, forward summary and identity fixes, benchmark guard, and synthetic capacity test. Three confirmed defects were repaired with failing-then-passing tests: connection override protection, forward summary initial-count alignment, and invalid test identity. A follow-up review found that the initial deep-page benchmark sampled a one-row tail page; the fixture now asserts a full 50-row deep page, and the old deep-page number above is invalid. No new code blocker was found for committing this partial engineering increment. Remaining risks are the incomplete workload coverage and unmeasured P8 cases listed below; this review does not grant P8 overall acceptance.

A second independent P8 review found two confirmed issues in the follow-up: the D1/W1
reader could scan an unfinished day, and simultaneous dash/underscore strategy identities
could make a previously readable stream ambiguous. The code now bounds the day by
authoritative completed Session and chooses readable exact identity before readable alias
using separate limited queries; targeted PostgreSQL evidence passed. The reviewer
rechecked both fixes and found no remaining blocker in those two areas. The review also
classified the 60/300 in-memory MarketRead and fixture browser input as scope limits,
not production or natural-run evidence.

An independent review of `stream_300_mds` and the Decimal boundary found no
confirmed code defect. It verified 300 distinct actual MDS page calls plus 60 HTDY
context calls, and classified the synthetic data/observation adapter as an evidence
limit. The five-run measurements above were completed after that review.

## Current acceptance boundary

The five requested follow-up evidence groups now have isolated passing results: actual
browser panel/API/PG, all supported strategy-family forward fixtures, real child-process
crash recovery, 60/300 typed-capture/worker throughput, and D1/W1 bounded normal append.
P8 as a whole remains **PARTIAL**: the full Market route, deeper historical
rebuild/revision/cutoff at scale, index-plan and
sustained-memory evidence, and HTDY successive-window repaint acceptance still need
separate proof. No fixture opens HTDY acceptance or any production capability. This
branch is an engineering candidate only; develop integration, release, Runtime
promotion, Canonical writes and P9 remain separate Gates.
The current `develop@476263116` has five commits beyond the P8 base, including changes
to `market_data_service.py` and Newow capability contracts. Since the listed P8
acceptance gaps remain, develop integration is **not approved by this evidence**;
before integration, reconcile those dependencies and rerun affected checks on the
combined tree.
