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
| HTDY first-seen | `test_htdy_reference_model`, `test_htdy_reference_capture`, `test_forward_inputs`; P8 PostgreSQL consecutive-window checkpoint, old snapshot and repaint rejection | Independent HTDY model acceptance, natural Live and broader input patterns |
| Recording mode isolation | `test_contracts`, `test_query`, `test_forward_query` | Cross-mode Web readback |
| Action identity/ownership | `test_contracts`, `test_reducer`, `test_multi_owner_historical` | No additional synonymous unit test planned |
| Pure deterministic reducer | `test_reducer`, `test_checkpoint_parity` | No additional synonymous unit test planned |
| Capability evidence | `test_historical_planning`, `test_forward_inputs`, `test_worker_entry` | Product-specific independent evidence remains outside P8 fixture scope |
| Atomic durable revisions | `test_repository`, `test_repository_postgresql`; P8 PostgreSQL worker restart/race/lost acknowledgment readback and child `os._exit` before/after commit | Host power loss and production storage failure remain outside isolated evidence |
| Strict checkpoint/seed | `test_repository_seed`, `test_strategy_checkpoint`, `test_checkpoint_parity` | No additional synonymous unit test planned |
| Snapshot and future-fact isolation | `test_repository_snapshots`, `test_query`, `test_forward_query`; P8 PostgreSQL forward window summary | Real PostgreSQL historical/forward cutoff after later revisions |
| Historical plans and budgets | `test_historical_planning`, `test_multi_owner_historical`; P8 13-stream temporary Canonical/Catalog/MDS→PostgreSQL integration | More owner/Session revision combinations in same storage chain |
| Build/resume/advance/rebuild | `test_bootstrap`, `test_historical_incremental`, `test_revision_rebuild`; P8 PostgreSQL build/advance and rebuild/old-snapshot readback | Rebuild at larger realistic stream scale |
| Historical CLI | `test_reference_cli` | No additional synonymous unit test planned |
| Persisted presentation | `test_presentation`, `test_historical_integration`; P8 PostgreSQL build/advance | Browser source identity readback |
| Bounded P5 query | `test_query`, `test_query_postgresql`, `test_api`; P8 synthetic pagination plus five 10,000-Bar actual-trade changed-price rebuild repetitions with old cutoff and warm queries | Production distribution, longer-duration planner stability and natural Runtime readback |
| Fail-closed page adapters | `test_persisted_subing_window`, `test_newow_persisted_query`, `test_api`; P8 PostgreSQL pipeline checks both adapters; Playwright CLI readback through actual Market detail route, FastAPI, MDS and PG | Broader page error matrix and natural Runtime readback |

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
| P8-B2 | Actual `/market/chart` router/MainLayout/Newow/Subing/HTDY workspaces, temporary Canonical/Catalog/MDS, disposable PG/Redis | Playwright CLI navigation and Tab switching; Newow historical 50 CLOSED + 1 OPEN, second page 51 rows; SuBing 60m persisted forward coverage; HTDY 15m first-seen signal; no route interception | PASS unified-reference full-route E2E for fixture data; legacy reference panels fail closed on fixture Calendar boundary |
| P8-B3 | Full Market route with a one-year synthetic Calendar/Session horizon and isolated persisted SuBing AlertEvent | Playwright CLI: bounded Newow legacy 1d 200, bounded SuBing legacy 15m 200, separate AlertEvent S↑ and unified forward panels, HTDY 15m first-seen; direct SuBing API 200 | PASS for explicit fixture windows; default current-date legacy requests still exceed the fixture horizon and return typed 409 |
| P8-S4 | Repeat 300 real-MDS fixture streams on current dirty task tree | `reference_trading_benchmark.py --case stream_300_mds --repeats 5 --timeout-seconds 180`: five passes, 300 calculations, 360 MDS reads and zero pending each | PASS isolated implementation throughput; generated Canonical and observation adapter |
| P8-S5 | Same-process equal-load 300 real-MDS waves, with a fresh worker/schema per wave | `test_postgresql_300_mds_same_process_rss_soak`: five waves, each 300 calculations and zero pending; settled RSS 170240, 157088, 157520, 157936, 157968 KiB | PASS process RSS after five teardown/rebuild waves; long-lived worker memory remains unmeasured |
| P8-Q3 | 10,000 actual projected Bars, 9,948 CLOSED trades, changed-price rebuild and prior-revision cutoff | `query_real_rebuild_10000 --repeats 5`: five passes, 100 warm first/deep/summary queries per run; worst p95 317.739/335.243/299.623 ms against 500/500/1000 ms limits | PASS isolated real-trade query/rebuild capacity on dirty task tree |
| P8-H3 | PostgreSQL rebuild with changed source manifest, old token and new active revision | `test_revision_rebuild.py -m isolated_postgresql`: 1 passed | PASS isolated revision switch/old-snapshot rejection on one fixture stream; scale remains open |
| P8-H4 | HTDY two consecutive completed windows, old first-seen point snapshot, then later overlapping-bar repaint | `test_newow_worker_recovery.py -k htdy_successive_windows -m isolated_postgresql`: 1 passed | PASS isolated PG checkpoint/first-seen-point retention and `OBSERVATION_GAP` fail-closed; buy/sell model/Live acceptance remains separate |
| P8-H5 | HTDY valid buy→sell windows and same-Bar conflicting signals against isolated PostgreSQL | `test_newow_worker_recovery.py -k 'actual_buy_then_sell or actual_same_bar_conflict' -m isolated_postgresql`: 2 passed, 33 deselected | PASS isolated model/capture/worker behavior; wider real-data and Live acceptance remains separate |
| P8-R5 | Final affected reference-trading PostgreSQL module regression | `pytest -q -m isolated_postgresql services/quant-api/tests/reference_trading`: 38 passed, 219 deselected, exit 0; non-PG affected query/rebuild/snapshot/forward files: 19 passed, 2 deselected; Web production build and Ruff passed | PASS for this branch increment; does not clear remaining performance or develop-integration gates |
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

On 2026-09-24 the same 300-stream MDS case was rerun five times after the
Market-route fixture edits on the dirty task tree at `e6a8ff347`. Capture-to-worker
totals were 24.009, 24.198, 24.009, 22.113 and 26.004 seconds; each run read
360 MDS pages, committed 300 calculations and drained pending to zero. Observed
child peak RSS was 168912–169984 KiB. A separate single-process soak then ran
five equal 300-stream waves against five disposable schemas; settled RSS was
170240, 157088, 157520, 157936 and 157968 KiB after garbage collection and
schema disposal. Each wave constructs a new worker; the first-to-last
difference was -12272 KiB. This measures process RSS after repeated teardown,
not a continuously running worker or production Live behavior.

The real-trade query follow-up builds and rebuilds 10,000 completed Bars with a
changed source price, yielding 9,948 CLOSED trades. It checks that the rebuilt
trade amounts differ while an earlier cutoff of the new revision preserves the
same historical prefix; old-revision snapshots are rejected after activation.
An initial SQL summary implementation intermittently exceeded PostgreSQL's
30-second statement timeout: the planner nested a full trade scan under a
windowed latest-version subquery. The corrected query uses a scalar latest
version lookup backed by the stream/revision/trade primary key. After that
change, five independent `query_real_rebuild_10000` runs passed 100 warm
first-page, full deep-page and summary queries each. The worst p95 was
317.739/335.243/299.623 ms, within the frozen 500/500/1000 ms limits.
This exercises generated prices and a test-only dataset, not natural data.
The exact production-shaped index scan range, PostgreSQL index size and
cold-start/steady-state split are still unmeasured.

## Full Market route browser readback

The isolated browser fixture uses the same temporary Canonical root, random PostgreSQL
schema and app DB dependency for the Market APIs and persisted reference endpoints.
It pins Redis to the disposable loopback instance. The historical integration test
changes the first Session as a negative test; the fixture restores that Session before
serving Market pages, so `/market/bars/page` reads the published 15m/60m bars.
Vite proxies `/api` to this FastAPI instance; Playwright CLI visited the real
`/market/chart` route and clicked its strategy tabs without intercepting requests.

Newow's real chart ended on 2026-03-27. Passing that chart trading day to the unified
historical panel produced 50 CLOSED and one OPEN record, with all 51 visible after
`加载更多`; summary reported `已平 50 · 未平 1 · 窗口初始 0`. In a separate API
probe for 2026-06-26–09-24, Newow's `entry_in_window_v1` contract keeps earlier
trades in the initial group: the summary returned zero new CLOSED/OPEN and 51
initial records, while the first page retained 50 older records with another page
available. The browser initially hid the initial count; it is now shown explicitly.
Regression cases cover earlier CLOSED and interrupted trades.
Switching the actual route to SuBing 60m returned a
persisted forward coverage ending 2026-09-23 10:00; switching to HTDY 15m returned
the persisted 2026-09-23 15:45 first-seen signal. Product casing and HTDY forward
date filtering were corrected after the browser showed 422 and a hidden signal.

The initial legacy-widget check exposed three fixture limits: the SuBing service
requires a one-year Calendar and Session horizon even for the shorter selected
window; the fixture lacked an AlertRule/Event; and the reused integration-test
monkeypatch deliberately disabled legacy projection. The browser fixture now
restores the real kernel, adds disposable Calendar/Session facts from 2025-03-27,
and seeds one disabled test Rule with a persisted S↑ AlertEvent. In the real
`/market/chart` route, a Newow 1d window of 2026-01-05–03-27 rendered its legacy
statistics; a SuBing 15m window for the same dates returned 200 and rendered
historical statistics independently of the unified forward panel and persisted
AlertEvent. The direct bounded SuBing API returned 200 with a 195478-byte body.
The default legacy request still extends to the actual current day beyond this
generated fixture and returns a typed Calendar 409 until a bounded window is
chosen. No production Calendar or default-current-window pass is claimed. Real provider acquisition,
natural Runtime and upstream 1m aggregation remain outside this isolated E2E.

On the P8 + `develop@10e6805665` combined tree, the browser reopened the actual
`/market/chart` route through Vite/FastAPI and a fresh disposable PostgreSQL
schema. Newow's bounded 2026-01-05–03-27 1d legacy statistics returned a
completed calculation; SuBing's bounded 15m historical reference returned
statistics separately from the persisted S↑ AlertEvent; HTDY showed its 15m
first-seen observation. A first pass exposed a fixture-only 404
`ALERT_RULE_NOT_FOUND` for the HTDY Event pane because only the SuBing test
Rule had been seeded. The fixture now seeds a disabled HTDY test Rule, and the
read-only HTDY Event API returns 200 with an empty Event set. Default-current
legacy requests remain typed 409 outside this generated Calendar horizon.

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

The requested follow-up groups now have isolated passing results: full Market-route
browser/API/PG readback for bounded fixture windows, all supported strategy-family
forward fixtures, child-process crash recovery, 60/300 real-MDS fixture throughput,
D1/W1 bounded append, changed-price rebuild at 10,000 Bars, same-process memory
soak and HTDY model buy/sell plus same-Bar conflict. The successive HTDY-window
fixture also retained the old first-seen point and rejected a repaint with exact
`OBSERVATION_GAP`, leaving the capture pending. These are fixture and engineering
Gates. The browser default-current-date legacy request remains outside the
generated Calendar horizon; real provider, natural Live, upstream 1m aggregation
and production acceptance were not exercised. No fixture opens HTDY acceptance
or any production capability.

P8 engineering increment was **integrated into develop** at `867b75c625bf084db46d7d90bd64ea7fc86687d3`. The combined-tree
PostgreSQL ReferenceTrading suite passed 43 tests (219 deselected) in 354.04 s,
and an independent GPT-6 Astra Review found no remaining code blocker. The
later evidence for a retained worker and index-plan/size is recorded below.
True cold-cache, natural Live and production data gaps still prevent a claim of full P8 acceptance.
`develop@10e6805665` was merged into the P8 worktree
without a textual conflict; the shared `market_data_service.py` method additions
were retained. Combined-tree non-PostgreSQL ReferenceTrading/data/Newow tests
passed 448 cases when the three root-import tests were rerun with the documented
`PYTHONPATH`; Web tests passed 684 with one skip, and `pnpm build` passed.
Release, Runtime promotion, Canonical writes and P9 remain separate Gates.

## 2026-09-24 remaining engineering evidence

Exact evidence code commit: `a62e5014b05dcf3791e78ca6335aa7b3a413a89a` on
`codex/unified-reference-trading-p8`, from integrated `develop@867b75c625`.
Both five-process benchmark files report `dirty_worktree=false`, PostgreSQL
16.14 and Python 3.13.9. Raw JSON is preserved in
[`evidence/guiyi-p8-stream_300_mds_retained.json`](evidence/guiyi-p8-stream_300_mds_retained.json)
and [`evidence/guiyi-p8-query_real_rebuild_10000_index.json`](evidence/guiyi-p8-query_real_rebuild_10000_index.json).
Their SHA-256 values are respectively `49b6510e0d67adf78fc654263144bb06bebfd68684a0bcedb857190eea9bafe3`
and `0d8c991363c5da24e2bd812510855badd4a23f75f5ca87e6ab8257669f5e9679`.
Both cases used only the dedicated disposable loopback PostgreSQL test database.
The retained-worker case published generated Canonical/Catalog/MDS data and used
a test-only observation adapter; the historical rebuild case used a generated
`Reader` feeding the real strategy kernel and PostgreSQL persistence, without MDS.

| Gate | Actual command and result | Boundary |
|---|---|---|
| Retained 300-stream worker | `reference_trading_benchmark.py --case stream_300_mds_retained --repeats 5 --timeout-seconds 180`: 5/5 passed; process wall median 59.178 s (58.820–59.535); each process retained one worker, MDS, schema and 300 stream identities across five completed Bar boundaries, 1,800 MDS reads, 1,500 calculations and zero pending | Worker processing per wave 8.006–10.276 s; settled RSS wave 5 minus wave 2 = 64, 128, 96, 352, 112 KiB; peak child RSS 169,712–171,184 KiB. This is a bounded five-Bar test, not long-duration or natural Live proof |
| Forward action-bearing path | Strengthened `test_postgresql_300_mds_retained_worker_five_completed_bars`: 1 passed in 60.75 s; 44 isolated PostgreSQL ReferenceTrading tests passed in 388.50 s; 218 non-PostgreSQL tests passed, 1 Redis skip, 44 deselected | First four waves have zero actions; fifth persists exactly 60 `newow_main_rise` **HINT** actions, one per stream, with `bar_end=2026-09-23T09:00Z` and `observed_at=09:01Z`. This does not prove OPEN/CLOSE/reversal on the retained load |
| Real-trade query/rebuild plan | `reference_trading_benchmark.py --case query_real_rebuild_10000_index --repeats 5 --timeout-seconds 300`: 5/5 passed; 10,000 completed Bars, 9,948 CLOSED trades; each run samples 100 warm requests per page/summary kind | Worst repetition warm p95: first page 220.886 ms, deep page 222.400 ms, summary 214.937 ms; all below frozen 500/500/1,000 ms limits. Across runs p50 ranges: 180.382–193.586, 180.904–192.883, 169.627–181.176 ms. Process wall median 175.609 s (171.499–199.912), peak child RSS 157,744–165,280 KiB |
| First-use and storage | After rebuild, first business page call 486.427–496.517 ms, first summary 173.402–196.775 ms; `pg_table_size`/`pg_indexes_size` captured before/after rebuild | Four reference relations together: table 22.06–22.09 → 43.98 MiB; indexes 33.53–33.71 → 71.07–71.23 MiB. These are PostgreSQL allocated bytes for this generated dataset, not a production storage forecast. First business call follows build/query activity, so it is **not** a cold-cache measurement |
| Actual PostgreSQL plan | Five `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans each for first page, deep page and summary | First/deep page plans each scan 10,027 trade versions, pass 9,949 through a subquery and perform 9,949 primary-key lookups; summary scans 10,027 index entries and 10,027 primary-key lookups. Root shared buffer hits are 40,201–40,230 for pages and 41,128 for summary; shared reads were 0 in these warmed plans. The query meets this fixture latency target but scan work is **not bounded by page size** |

The real-MDS load exposed a forward Newow defect in the fifth action-bearing Bar:
`SourceAction` was constructed before `observed_at` was attached, so it rejected
a forward action. `_newow_step` now receives `observed_at` before constructing
the source action; historical calls continue to pass no observation time.
The strengthened PostgreSQL test above fails on the previous implementation
and passes with the fix. Benchmark-safety tests passed 11/11, Ruff and
`git diff --check` passed. The repository secret scan exited 1 on the
pre-existing test-only `reader.token = "source-revised-tail-price"` assignment
(present at line 181 in the parent commit); no credential was added.
Independent GPT-6 Astra review initially found missing buffer output and a
weak cumulative action assertion. Both were repaired and re-reviewed; its
final conclusion found no confirmed code blocker for this engineering increment.

## Gate decision and external boundary

The retained-worker, real-MDS 300-stream throughput, 10,000-Bar real-trade
warm query, actual index-plan/size, process-crash, bounded D1/W1 append and
bounded-window full Market-route browser engineering evidence is sufficient
for **develop integration / release-candidate consideration**. The actual
index work scales with the tested stream history, and true cold-cache and
long-duration worker behavior remain unmeasured. The prior Browser fixture
still returns typed 409 when an unbounded current-day legacy request extends
past its generated Calendar horizon; no production default-window result is claimed.

The current production readback in `STATUS.md` is `v1.10.30@120c5c94` with
six existing services and **no installed Reference worker**. Its runtime
checkout does not contain this evidence commit. The Reference worker install
path is render-only, requires an exact local enable marker, and forward streams
remain disabled by default. Thus P8 natural Live observation, actual production
data freshness, production capability/model acceptance and final release or
Runtime promotion are **external Gates pending**. Closing them requires an
approved exact release/runtime/stream scope and a subsequent natural completed
Bar readback; isolated fixtures cannot supply that receipt. No provider,
production Canonical, production DB, notification, release or Runtime mutation was made
for this evidence run.
