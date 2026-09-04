# Newow page-v2 Real Futures Evidence Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans`. Stop at every Owner Gate named below. This packet never authorizes a production read, snapshot capture, real OOS run, profile change, promotion, or Final Cutover.

**Goal:** Determine whether `newow_trend_d1_page_v2` has sufficiently trustworthy real-futures evidence to enter the Owner-reviewed candidate gate for V1 default Trend.

**Architecture:** All market facts flow through `MarketDataService`. `ActualDominantResearchSegmentLoader` supplies full rank-1 authority and independent `1d`, `1w`, and `60m` observed-owner subsets. Formula state is rebuilt from the complete same-physical-contract prefix while only actual-dominant Bars are eligible for signals and execution. Quant Core performs fixed-formula, next-open, costed evaluation. Reviewer artifacts contain per-product, per-frequency, per-fold results and no automatic promotion function.

**Tech Stack:** Python 3.13, SQLAlchemy read-only PostgreSQL session, Canonical Parquet through `MarketDataService`, immutable dataclasses, `Decimal`, JSON/CSV with SHA-256, pytest, Ruff, Mypy.

**Spec:** `docs/tasks/2026-09-04-newow-page-parity-research-kernels.md`, `docs/tasks/2026-09-04-newow-futures-validation.md`, and this packet.

**BASE_SHA:** `a6ea680ed8d9150e0b9920e71563a3de18f7dd1e`

## Global Constraints

- Use a clean worktree based on the execution-time clean `origin/develop`; if it differs from `BASE_SHA`, stop with `BASE_SHA_DRIFT` and re-review the diff before changing this packet.
- Do not call RQData, Redis Live, direct SQL行情 queries, Parquet globbing, continuous fallback, or a consumer-owned dominant resolver.
- A production PostgreSQL read requires a separate, explicit Owner authorization. Repository inspection and fixture tests do not grant it.
- Do not write PostgreSQL, Redis, Canonical, Scope, profile definitions, Runtime, notifications, tags, releases, or orders.
- Do not create or populate cost/execution snapshots until the Owner separately approves the exact source and capture operation.
- Do not run real Canonical evidence, OOS, or Walk-forward until the data-read, mapping-causality, and cost-authority gates all pass.
- Fixed formulas only. Test returns cannot select products, folds, frequencies, costs, parameters, or replacement strategies.
- Trend is the promotion subject. Oscillation and Main-rise are controls only. Repainting strategies are excluded from formal backtests.
- Missing or conflicting facts fail closed and remain visible in artifacts.

## Current Trusted-Definition Audit

| Required behavior | File and symbol | Test authority | Current behavior |
|---|---|---|---|
| Actual-dominant adapter | `services/quant-api/app/market_data/newow/futures_validation.py::build_newow_research_bars` | `test_futures_validation.py` | Requires exact actual-dominant identity, independent frequency, unique observed and authoritative owner, completed Bars, physical contract and stable segment identity. |
| Physical prefix replay | same file, `build_newow_strategy_replay_segments` | `test_futures_validation.py`, `test_research_walk_forward.py` | Full same-contract prefix warms formula state; only rank-1-matched Bars are eligible; OHLCV/OI mismatches and truncated prefix pages fail closed. |
| Read seam assembly | `futures_evidence_service.py::build_newow_futures_evidence_inputs` | `test_futures_evidence_service.py` | Uses `MarketDataService.query_contract_trading_days(ContractTradingDayQuery(...))`; Catalog contract lifecycle clamps the complete prefix. A frequency may omit a rank-1 segment with no completed Bar, as in the SC2302-shaped regression. |
| Strategy intents | `research_backtest.py::build_strategy_intents_from_replay_segments` | `test_research_walk_forward.py` | Fresh state per physical segment; eligible intents only; frozen formula lineage. |
| Causal executor | `research_backtest.py::run_causal_long_only_backtest` | `test_research_backtest.py` | Completed-Bar signal, one next-open attempt, no silent retry. |
| Costs | `BacktestCostSnapshot` | `test_research_backtest.py` | Product, contract, half-open effective dates, captured timestamp, source identity and Decimal costs; missing/overlap fails. |
| Constraints | `BacktestExecutionConstraint` | `test_research_backtest.py` | Exact Bar identity, contract, limits and source; missing/conflict fails. |
| Rejected fills | `RejectedFill` | `test_research_backtest.py` | `ZERO_VOLUME`, `BUY_AT_LIMIT_UP`, `SELL_AT_LIMIT_DOWN`. |
| Roll exclusion | executor | `test_research_backtest.py` | Pending intent cancelled and open position recorded as `DOMINANT_ROLL_EXCLUDED`. |
| End exclusion | executor | `test_research_backtest.py` | Pending intent cancelled and open position recorded as `END_OF_SAMPLE_EXCLUDED`. |
| Fixed-formula WF | `research_walk_forward.py::run_fixed_formula_walk_forward` | `test_research_walk_forward.py` | Non-overlapping test windows, explicit warm-up, flat test portfolio, exact replay/execution Bar equality, sourced execution facts. |
| Evidence rows | `research_evidence.py::build_walk_forward_evidence_rows` | `test_research_evidence.py` | Emits non-aggregate fold facts; no promotion score. |
| Repainting rejection | frozen causal formula allowlist in `research_backtest.py` | `test_research_backtest.py` | Formula outside causal allowlist fails. 照妖镜 is not in formal lineage. |

Current Web identity is `newow_trend_d1_page_v2`. Trend formal backtest lineage is `newow_trend_band_page_v2`; the Web profile additionally displays `newow_escape_d123_page_v2` and `newow_cup_handle_v1`, which are not Trend entry/exit formulas.

## Deterministic Selection and Coverage

Selected frequencies are exactly `1d`, `1w`, `60m`.

Coverage discovery must run before returns are calculated:

1. Load `operational_products.txt` with `load_operational_products()`, which fail-closes unless the set is an active-universe subset, then load the accepted product taxonomy.
2. For every validated operational product, call `MarketCatalog.main_map_before(product, None)` to obtain the bounded rank-1 date range and physical contracts. Construct each `DatasetKey(DatasetKind.CONTRACT, product, contract, frequency)` from those facts; call `MarketCatalog.all_partitions(key)` only for those exact keys. Do not attempt to enumerate datasets with `all_partitions`.
3. Intersect the partition coverage for contract-backed `1d`, `1w`, and `60m`, then validate the proposed interval through `MarketDataService.actual_dominant_segments(product, since, through)` and the normal query seam. Count contract changes and require at least two actual rollovers.
4. Exclude candidates with a missing frequency, failed physical read, identity conflict, quality failure, or fewer than two rollovers.
5. Form frozen buckets: black=`sector == black`; energy/chemical=`sector in {energy, chemical}`; agriculture=`sector == agriculture`.
6. Within each bucket choose the candidate with the longest common three-frequency coverage; break an exact duration tie by ascending product code.
7. Persist selection before formula execution. Never replace a selected loss-maker.

The executable pure rule is `futures_evidence_plan.py::select_futures_evidence_products`. Concrete products are `BLOCKING_UNKNOWN` until the authorized read-only coverage discovery completes.

## Real Data Read Gate

| Purpose | Query seam | Resources | Class | Expected scale | Zero-mutation proof |
|---|---|---|---|---|---|
| Universe and sectors | `load_operational_products`, `load_product_taxonomy` | repository text/CSV | repository-local read-only | 60 or fewer rows | normal file reads; before/after hashes equal |
| Dataset coverage | `MarketCatalog.main_map_before(product, None)` → exact contract `DatasetKey` → `MarketCatalog.all_partitions(key)` | `main_contract_map`, `market_datasets`, `market_partitions`, Canonical file metadata | production PostgreSQL plus workstation Canonical read-only | below 10,000 map rows/product and hundreds of partition rows/selected scope | PostgreSQL transaction must be `READ ONLY`; no ORM add/flush/commit; Canonical tree manifest equal |
| Rank-1 ownership | `MarketDataService.actual_dominant_segments` | `main_contract_map`, `trading_calendars`, `instruments` | production PostgreSQL read-only | below 10,000 daily facts per product | same transaction guard; SQLAlchemy dirty/new/deleted sets empty |
| Actual Bars | `ActualDominantResearchSegmentLoader.load` | prior resources, `trading_sessions`, plus Canonical contract partitions | production PostgreSQL plus workstation Canonical read-only | bounded by selected coverage | only `MarketDataService` read methods are called inside an enforced read-only transaction; file manifest equal |
| Physical prefix | `MarketDataService.query_contract_trading_days(ContractTradingDayQuery(product, contract, frequency, date.min, last_owner_day))` | `contracts`, Calendar/Session, Catalog and Canonical contract partitions | production PostgreSQL plus workstation Canonical read-only | full listed-contract prefix through the last owner day | `contract_fact` validates provider and lifecycle; enforced read-only transaction; no mutation method is called |

Production read required: **yes**. It is not authorized by this packet. No production resource is needed for fixture tests, code review, schema review, or snapshot-file validation.

Exact production tables are `contracts`, `instruments`, `trading_calendars`, `trading_sessions`, `main_contract_map`, `market_datasets`, and `market_partitions`. The authorized runner must use a database role proven to have SELECT-only privileges on exactly these tables in addition to transaction-level `READ ONLY`; availability of that role is `BLOCKING_UNKNOWN`.

`main_contract_map` currently has no pre-open publication/availability timestamp. Therefore the claim “rank-1 owner was knowable before the tested session opened” is `BLOCKING_UNKNOWN`. A trusted upstream dated mapping snapshot or an accepted as-known semantic is required; current `created_at/updated_at` ingestion timestamps cannot be silently substituted.

## Cost, Multiplier, Tick, and Limit Evidence

The eight-table Catalog is not historical fee authority. `contracts.contract_multiplier` is not sufficient because it is not a complete versioned cost record. Retired `FeeMarginRule` must remain retired.

| Field | Required granularity | Effective-date semantics | Source candidate | Authority | captured_at | Hash | Missing behavior |
|---|---|---|---|---|---|---|---|
| contract multiplier | product or physical contract | half-open effective interval covering every causal Bar | dated exchange contract specification | exchange publication | timezone-aware capture time | source file SHA-256 plus canonical record SHA-256 | block |
| price tick | product or physical contract | same | dated exchange contract specification | exchange publication | same | same | block |
| open commission | product/contract and fee mode | half-open interval | dated exchange/member schedule used by the research account | publisher named in Owner approval | same | same | block |
| close commission | product/contract and fee mode | half-open interval | same | same | same | same | block |
| close-today commission | product/contract and fee mode | half-open interval | same | same | same | same | block |
| price limit | physical contract and trading day | exact session/Bar availability | dated exchange daily limit fact | exchange publication | same | same | block |
| slippage | scenario assumption, product/frequency | frozen run-wide assumption | Owner-approved research assumption | Owner decision, not market fact | packet freeze time | packet SHA-256 | block |

Minimum external snapshot envelope:

```json
{
  "schema_version": "newow-futures-execution-facts-v1",
  "publisher": "string",
  "source_document_identity": "string",
  "source_effective_at": "timezone-aware timestamp",
  "captured_at": "timezone-aware timestamp",
  "source_sha256": "64 lowercase hex",
  "records_sha256": "64 lowercase hex",
  "cost_records": [],
  "daily_limit_records": []
}
```

Each `cost_records` item is exactly:

```text
record_id, product, physical_contract, effective_from, effective_to,
contract_multiplier, price_tick,
open_commission_rate, open_commission_per_contract,
close_commission_rate, close_commission_per_contract,
close_today_commission_rate, close_today_commission_per_contract,
source_document_identity, source_location, source_effective_at
```

Each `daily_limit_records` item is exactly:

```text
record_id, product, physical_contract, execution_bar_source_identity,
execution_bar_end, execution_trading_day, known_at, limit_up, limit_down,
source_document_identity, source_location, source_effective_at
```

All dates are ISO calendar dates; all timestamps are timezone-aware ISO-8601; every numeric market/cost value is a canonical Decimal string. Effective intervals are half-open. `known_at` must be at or before the session-open decision point. `execution_bar_source_identity` joins exactly to `BacktestExecutionConstraint.bar_source_identity`; contract, Bar end and execution trading day must also agree. For `1d` and `60m`, execution trading day is the fill Bar's trading day. For `1w`, it is the first exchange trading day contributing to that weekly Bar, proven from accepted aggregation lineage plus Calendar/Session facts, not the week-end `trading_day`; if that first-day lineage cannot be proven, W1 execution evidence is blocked. `records_sha256` hashes UTF-8 canonical JSON with sorted object keys, source record order sorted by `record_id`, no insignificant whitespace, and a terminating newline. Missing fee modes cannot be collapsed into a generic fee.

Current repository/user-provided authority for historical commission and daily price limits: none verified. Current executor models one commission formula per fill and cannot distinguish open, close, and close-today schedules. If the approved source requires those distinctions, add a new versioned execution-cost contract under Task 2 below. Until both source authority and expressiveness pass, emit `REAL_FUTURES_COST_EVIDENCE_BLOCKED`.

## Fold Construction

After selection, compute one common coverage intersection across all selected products and all three frequencies. For each calendar year, use `MarketCatalog.exchange_for_symbol()` and `MarketCatalog.calendar_days()` to identify the first and last exchange trading days, then require the normal `MarketDataService` reads to cover those endpoints and pass all gap/identity checks. Pass only Calendar-proven consecutive complete years to `futures_evidence_plan.py::build_natural_year_folds`; it then:

- uses the first complete calendar year only as causal warm-up;
- creates an expanding fold for every subsequent complete calendar year;
- requires at least two non-overlapping complete test years;
- sets `train_since=common_since`, `train_through=December 31 of the prior year`, `test_since=January 1`, and `test_through=December 31`;
- starts the portfolio flat in each test and does not truncate same-contract physical prefix state.

The window fields remain natural-year January 1/December 31 boundaries, but completeness is proven from exchange trading days rather than requiring Bars on holidays. Concrete fold dates are `BLOCKING_UNKNOWN` until coverage discovery. If fewer than two complete test years exist, emit `NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED`; do not shorten the gate.

## Strategies and Formula Lineage

- Promotion subject: `ResearchStrategy.TREND` → `newow_trend_band_page_v2`.
- Control: `ResearchStrategy.OSCILLATION` → exact lineage `("newow_oscillation_hhv_llv10_page_v1", "newow_hhv_llv_channel_page_v1")`.
- Control: `ResearchStrategy.MAIN_RISE` → `newow_main_rise_ma35_ma45_page_v1`, `newow_main_rise_j_reduce_page_v1`, `newow_escape_d123_page_v2`, `newow_buy_d456_page_v1`, `newow_magic11_page_v1`.
- Executor: `newow_causal_next_open_costed_v1`.
- Web profile identity: `newow_trend_d1_page_v2`.
- 照妖镜/repainting formula: excluded from every formal execution and artifact lineage.

## Cost Stress

Run exactly:

1. `baseline_sourced_costs` — approved sourced commission plus frozen sourced/approved slippage.
2. `double_commission` — multiply every commission rate and per-contract commission component by two; preserve multiplier, tick, limit, effective interval and source identity.
3. `double_slippage` — multiply `slippage_bps` and `slippage_ticks` by two; preserve commission, multiplier, tick, limit, effective interval and source identity.

`research_evidence.py::stress_cost_snapshots` implements this transformation for the current contract. Results must be reported by product × frequency × fold × strategy × scenario.

## Decision Matrix

Hard correctness gates, all required at zero:

- identity conflicts
- future leaks
- cross-contract state carries
- missing mandatory execution facts
- invalid cost lineage
- parameter mutations
- repainting strategy formal uses
- unexplained data mismatches

Research interpretation metrics, never an automatic decision function:

- net return and closed-trade drawdown
- closed trades and win/loss counts
- rejected fills by reason
- roll and end exclusions
- cancelled and ignored intents
- baseline versus cost-stress sensitivity

Reviewer recommendation is exactly one of:

- `REJECT_PAGE_V2_PROMOTION`
- `CONTINUE_PAGE_V2_SHADOW_RESEARCH`
- `ALLOW_PAGE_V2_AS_V1_DEFAULT_CANDIDATE`

Every recommendation waits for final Owner approval.

## Task 1: Physical-Prefix Parity Repair

**Files:** `research_backtest.py`, `research_walk_forward.py`, `futures_validation.py`, `futures_evidence_service.py`, their exports and tests.

- [x] RED: add prefix eligibility, truncation, mismatch, SC2302-style missing-frequency-segment, and replay/execution equality tests.
- [x] GREEN: add `NewowStrategyReplaySegment`, replay-safe intent construction, validated application adapter, and lifecycle-bounded `MarketDataService.query_contract_trading_days` assembly.
- [x] Verify targeted tests without real data.

## Task 2: Reviewer Metrics and Deterministic Planning

**Files:** `research_evidence.py`, `futures_evidence_plan.py`, their exports and tests.

- [x] RED: require fold-level counts and exact stress transformations.
- [x] GREEN: emit per-fold evidence rows; freeze sector selection and complete-natural-year folds.
- [x] Verify targeted tests without real data.

## Task 3: Resolve Mapping Causality and Cost Authority

**Files to modify only after Owner accepts the sources:** `research_backtest.py`, `futures_validation.py`, a new read-only runner under `scripts/`, tests, and this packet.

- [ ] Obtain an accepted source that proves rank-1 knowledge availability before each session; otherwise stop `REAL_FUTURES_MAPPING_CAUSALITY_BLOCKED`.
- [ ] Obtain accepted dated multiplier/tick/commission/limit sources; otherwise stop `REAL_FUTURES_COST_EVIDENCE_BLOCKED`.
- [ ] RED: encode source timestamp, hash, effective interval, fee-mode and no-lookahead failures.
- [ ] GREEN: implement only the minimum versioned contracts needed by the accepted sources.
- [ ] Owner Gate: approve the exact snapshot capture target and one capture attempt.

## Task 4: Add the Bounded Read-Only Runner

**Files:** create `scripts/newow_page_v2_futures_evidence.py`; create `services/quant-api/tests/newow/test_page_v2_futures_evidence_runner.py`.

- [x] RED: reject base drift, non-read-only PostgreSQL transaction, dirty SQLAlchemy session, invalid SELECT-only role facts, wrong products/frequencies/rollover count, missing actual-dominant Bars, unmatched Owner run ID/output directory, and any output path under Canonical.
- [x] GREEN: implement `discover` only in `scripts/newow_page_v2_futures_evidence.py` and `futures_evidence_discovery.py`. It freezes Catalog candidates before any strategy work, reads only the three frozen actual-dominant frequencies for selected candidates, and writes only `selection.json`, `coverage.csv`, `input_hashes.json`, and `zero_write_proof.json` below the explicit Owner run ID directory.
- [x] Add an automatic before/after proof: issue `SET TRANSACTION READ ONLY` then verify `SHOW transaction_read_only = on`; keep SQLAlchemy `session.new`, `session.dirty`, and `session.deleted` empty; always roll back and close. Hash only exact Catalog-resolved Canonical files before and after, comparing path, size, mtime and SHA-256. Reject a dirty Git worktree before discovery and require the only post-run Git change to be the approved report directory.
- [ ] `validate-inputs`, `execute`, and `verify-artifacts` remain excluded until Task 3 source authorities have been accepted. They are not part of the Owner-approved local-only runner implementation.

## Task 5: Authorized Discovery and Freeze

- [ ] Re-run base/worktree checks.
- [ ] Owner Gate: authorize one bounded production read for `discover`.
- [ ] Run discovery, freeze products and folds, then stop for review before returns.
- [ ] Owner Gate: approve accepted snapshot files and one real evidence execution.

## Task 6: Real Evidence Execution and Review

- [ ] Validate hashes and immutable inputs.
- [ ] Execute Trend plus two controls for all products, frequencies, folds and stress scenarios.
- [ ] Write artifacts only under the approved report directory.
- [ ] Run independent Review A for strategy/causality/OOS.
- [ ] Run independent Review B for data identity/cost/execution/scope.
- [ ] Correct every Critical or Important finding and re-verify.
- [ ] Present one reviewer recommendation and stop at Owner Gate.

## Commands

Engineering verification now:

```bash
git diff --check
PYTHONPATH=packages/quant-core:services/quant-api /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q services/quant-api/tests/newow
PYTHONPATH=packages/quant-core:services/quant-api /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/ruff check packages/quant-core/guiyi_quant/newow services/quant-api/app/market_data/newow services/quant-api/tests/newow
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
```

Authorized discovery command after Task 4 exists and the Owner grants the matching read:

```bash
PYTHONPATH=services/quant-api:packages/quant-core PYTHONDONTWRITEBYTECODE=1 /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python scripts/newow_page_v2_futures_evidence.py discover --base-sha a6ea680ed8d9150e0b9920e71563a3de18f7dd1e --owner-approved-run-id OWNER_APPROVED_RUN_ID --frequencies 1d 1w 60m --minimum-rollovers 2 --output data/reports/newow_page_v2_real_futures_evidence/OWNER_APPROVED_RUN_ID
```

Real execution command after both subsequent Owner Gates:

```bash
PYTHONPATH=services/quant-api:packages/quant-core /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python scripts/newow_page_v2_futures_evidence.py execute --selection data/reports/newow_page_v2_real_futures_evidence/OWNER_APPROVED_RUN_ID/selection.json --folds data/reports/newow_page_v2_real_futures_evidence/OWNER_APPROVED_RUN_ID/folds.json --execution-facts OWNER_APPROVED_EXTERNAL_SNAPSHOT_PATH --output data/reports/newow_page_v2_real_futures_evidence/OWNER_APPROVED_RUN_ID
```

`OWNER_APPROVED_RUN_ID` and `OWNER_APPROVED_EXTERNAL_SNAPSHOT_PATH` are `BLOCKING_UNKNOWN` until the named Owner Gates. The discovery runner now exists but must not be invoked until the Owner supplies one explicit new run ID for one bounded production read. The execution command remains unavailable until Task 3 clears.

## Artifact Plan

Approved run directory only:

```text
data/reports/newow_page_v2_real_futures_evidence/<run-id>/
  run_manifest.json
  selection.json
  coverage.csv
  folds.json
  input_hashes.json
  formula_lineage.json
  evidence.json
  evidence.csv
  rejected_fills.csv
  exclusions.csv
  hard_gates.json
  zero_write_proof.json
  review_a.md
  review_b.md
```

Every JSON file uses sorted keys, UTF-8, newline termination and Decimal-as-string. Every CSV has an explicit header and Decimal-as-string. `input_hashes.json` contains SHA-256 for every accepted source and frozen input. `run_manifest.json` hashes every artifact except itself and records its own canonical-payload hash.

Required evidence row fields:

```text
base_sha, run_id, product, sector, frequency, strategy, formula_versions,
executor_version, scenario, fold_name, train_since, train_through, test_since,
test_through, train_bar_count, gap_bar_count, warmup_bar_count, test_bar_count,
test_segment_count, physical_prefix_segment_count, physical_prefix_bar_count,
earliest_physical_prefix_trading_day,
physical_prefix_segments, closed_trade_count, rejected_fill_count, roll_exclusion_count,
end_exclusion_count, cancelled_intent_count, ignored_intent_count,
closed_trade_compounded_return_on_entry_cash_outlay_pct,
closed_trade_drawdown_on_entry_cash_outlay_pct, win_count, loss_count,
breakeven_count,
cost_source_hashes, limit_source_hashes, canonical_source_identities
```

## Review Checklist

- Base, branch, worktree and dirty state recorded.
- Selected products came from the frozen rule before returns.
- Three frequencies were independently read and no owner tuple equality was imposed across frequencies.
- Every strategy replay used a complete physical prefix; every execution Bar was actual-dominant and exactly matched its eligible replay Bar.
- Rank-1 knowledge time passed; no ingestion timestamp substituted for source availability.
- Every causal Bar had one cost fact; every attempted fill had one limit fact. Each fold exposes every replay segment's contract, segment ID, prefix count, eligible count, and first/last trading day.
- All source files, normalized records, inputs and outputs have verified SHA-256.
- Folds are expanding, natural-year, non-overlapping tests with flat starting portfolios.
- Formula versions and parameters are byte-identical across folds/scenarios.
- Trend remains the promotion subject; controls did not replace it.
- All hard-gate counts are zero or the recommendation is fail-closed.
- Review A and Review B have no unresolved Critical or Important findings.
- No profile, production data, Runtime, Scope, notification, release or order mutation occurred.

## Stop Conditions

Stop immediately on base drift, dirty overlapping files, missing Owner authorization, unavailable complete-year coverage, fewer than two rollovers, missing/ambiguous owner, unknown owner availability time, physical-prefix truncation, Bar mismatch, missing or invalid source/hash/effective date, cost-contract mismatch, any formula/parameter mutation, any future leak, any cross-contract state carry, any write attempt, any unexplained artifact mismatch, or any unresolved Critical/Important review finding.

If blocked, safe alternatives are:

- **Option A:** keep unified detail explicit Trend and do not cut over ordinary-product defaults.
- **Option B:** open a separate Lane 3 trusted-definition task to select an already well-validated older Trend profile. Do not change a profile in this task.

## Resource Estimate

- Engineering fixture verification: 5–10 minutes CPU/wall time.
- Authorized discovery: 10–30 minutes, bounded by Catalog and Canonical metadata reads.
- Snapshot source review/capture: `BLOCKING_UNKNOWN` because source volume and Owner-approved format are not established.
- Full 3-product × 3-frequency × 3-strategy × 3-scenario run: estimated 30–120 minutes after coverage is known.
- Two independent reviews and corrections: 30–90 minutes.

Current gate status: `PAGE_V2_EVIDENCE_PLAN_BLOCKED`. No real evidence has been run.
