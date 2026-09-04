# Newow Futures Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the fail-closed research seam needed to evaluate the frozen Newow page formulas on completed Canonical actual-dominant futures bars with same-contract indicator state, sourced costs, conservative execution constraints, and fixed-formula walk-forward folds.

**Architecture:** Keep `MarketDataService` as the only market-data authority and adapt each returned frequency independently into Quant Core research bars. Quant Core owns causal signal generation, next-open execution, immutable cost/limit facts, and walk-forward scoring; it does not connect to RQData, PostgreSQL, Redis, notifications, orders, or Runtime. Real production evidence remains a separate read-only Gate after code and fixture integration are accepted.

**Tech Stack:** Python 3.13, dataclasses, Decimal, FastAPI application services, Canonical market-domain value objects, pytest, Ruff, Mypy.

**Spec:** `docs/tasks/2026-09-04-newow-page-parity-research-kernels.md`

## Global Constraints

- Historical input is completed `actual_dominant` only and must come through `MarketDataService`; no Parquet globbing, continuous fallback, self-selected dominant contract, or cross-frequency aggregation.
- Every Quant Core Bar and cost snapshot must carry a legal physical contract whose prefix matches its product; strategy, declared formula lineage, and intent formulas must be one frozen identity set.
- Indicator recursion and warm-up reset whenever `(physical_contract, segment_id)` changes.
- A signal observed on one completed Bar may only attempt one fill at the next Bar open; an untradable next open is rejected and never silently retried.
- Costs, multiplier, tick and price limits are Decimal facts with explicit source identity and effective bounds; missing, overlapping, inconsistent, or stale facts fail closed.
- `1d`, `1w`, and `60m` are independent series. Weekly owner semantics come from the `MarketDataService` response and are not inferred from daily data.
- Walk-forward uses frozen formulas and training history only as causal warm-up. It performs no parameter fitting, optimization, strategy promotion, persistence, notification, or order creation.
- Do not access real RQData, production PostgreSQL/Redis, mutate Canonical, send notifications, change Scope, merge `main`, create a tag/release, or promote Runtime without a fresh matching user authorization.

---

### Task 1: Expose the existing segment-safe intent builder

**Files:**
- Modify: `services/quant-api/tests/newow/test_research_backtest.py`
- Modify: `packages/quant-core/guiyi_quant/newow/research_backtest.py`

**Interfaces:**
- Consumes: `tuple[NewowResearchBar, ...]` ordered by `bar_end`.
- Produces: `build_strategy_intents(bars, strategy) -> tuple[tuple[BacktestIntent, ...], tuple[str, ...]]` while preserving the primitive-level reset at every `(physical_contract, segment_id)` boundary.

- [x] **Step 1: Write the failing public-seam test**

Import `build_strategy_intents` from `guiyi_quant.newow`, pass an `RB2610 -> RB2701` sequence, and assert the new segment produces the same intents as that segment evaluated from a fresh state. The test fails before implementation because the public seam does not exist. Existing primitive tests remain the behavioral authority for trend, oscillation, and main-rise rollover reset.

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=packages/quant-core:services/quant-api \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/newow/test_research_backtest.py \
  -k 'build_strategy_intents'
```

Expected: collection fails because `build_strategy_intents` is not exported.

- [x] **Step 3: Implement the public intent seam**

Rename `_strategy_intents` to `build_strategy_intents` and export it from `guiyi_quant.newow`. Do not add a second reset layer: `step_trend_band`, `step_oscillation`, and `step_main_rise` already reset their own state at a physical segment change.

- [x] **Step 4: Run GREEN and the full research-backtest file**

```bash
PYTHONPATH=packages/quant-core:services/quant-api \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/newow/test_research_backtest.py
```

Expected: all tests pass and existing next-open/roll exclusion behavior is unchanged.

---

### Task 2: Add sourced futures cost and execution facts

**Files:**
- Modify: `services/quant-api/tests/newow/test_research_backtest.py`
- Modify: `packages/quant-core/guiyi_quant/newow/research_backtest.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`

**Interfaces:**
- Produces: `BacktestCostSnapshot`, `BacktestExecutionConstraint`, and `RejectedFill`.
- Extends: `run_causal_long_only_backtest(..., cost_snapshots=(), execution_constraints=(), require_execution_facts=False)`.
- Preserves: existing static `costs=BacktestCosts(...)` calls for synthetic/unit research only.

- [x] **Step 1: Write failing validation tests**

Cover these literal failures:

```text
NEWOW_BACKTEST_COST_SNAPSHOT_INVALID
NEWOW_BACKTEST_COST_SNAPSHOT_MISSING
NEWOW_BACKTEST_COST_SNAPSHOT_OVERLAP
NEWOW_BACKTEST_EXECUTION_CONSTRAINT_INVALID
NEWOW_BACKTEST_EXECUTION_CONSTRAINT_MISSING
NEWOW_BACKTEST_EXECUTION_CONSTRAINT_CONFLICT
NEWOW_BACKTEST_STRATEGY_FORMULA_MISMATCH
```

Bars and snapshots must reject a physical contract from another product. Snapshots must match product + physical contract and cover the Bar trading day with a half-open `[effective_from, effective_to)` interval. Execution constraints must match the exact Bar `source_identity` and physical contract. When a strategy identity is present, its declared formula versions must equal the frozen strategy set and every intent must belong to that set.

- [x] **Step 2: Run the new validation tests and verify RED**

Use the command from Task 1 with `-k 'cost_snapshot or execution_constraint'`. Expected: import or signature failures because the contracts do not yet exist.

- [x] **Step 3: Implement immutable facts and resolution**

`BacktestCostSnapshot` stores product, physical contract, effective dates, captured timestamp, source identity, and `BacktestCosts`. `BacktestExecutionConstraint` stores exact Bar identity, contract, limit-up, limit-down, and source identity. When `require_execution_facts=True`, resolve one cost snapshot with a non-null price tick for every Bar in the causal prefix, compare multiplier on every Bar while a position is open, require one execution constraint for each attempted fill, and require tick-aligned Canonical OHLC plus limit prices.

- [x] **Step 4: Write failing no-fill tests**

Assert a BUILD at `open >= limit_up`, CLEAR at `open <= limit_down`, or either side with zero Canonical volume produces one `RejectedFill` with respectively:

```text
BUY_AT_LIMIT_UP
SELL_AT_LIMIT_DOWN
ZERO_VOLUME
```

The intent is consumed once, not retried on a later Bar. An exit rejection leaves the position open and it becomes `END_OF_SAMPLE_EXCLUDED` or `DOMINANT_ROLL_EXCLUDED` under the existing rules.

- [x] **Step 5: Implement minimal no-fill behavior and per-fill lineage**

Add `contract_multiplier` and `cost_source_identity` to `BacktestFill`, record the distinct used snapshot identities in the result, and use the entry fill multiplier for PnL. Reject a trade if entry and exit multipliers differ within one physical contract.

- [x] **Step 6: Run GREEN and exports**

Run the complete research-backtest test file, then import all new public contracts from `guiyi_quant.newow` in one smoke assertion.

---

### Task 3: Adapt authoritative actual-dominant responses per frequency

**Files:**
- Create: `services/quant-api/app/market_data/newow/futures_validation.py`
- Create: `services/quant-api/tests/newow/test_futures_validation.py`

**Interfaces:**
- Consumes: one `MarketSeriesResult` returned by `MarketDataService` plus the query-invariant segments restored by `ActualDominantResearchSegmentLoader`.
- Produces: `build_newow_research_bars(result, authoritative_segments, expected_product, expected_frequency) -> tuple[NewowResearchBar, ...]`.

- [x] **Step 1: Write failing adapter tests**

Build complete `MarketSeriesResult` fixtures for `1d`, `1w`, and `60m`. Supply loader-restored full segments and assert that every Canonical Bar has one matching owner in both the clipped response and the authoritative segments, source/segment identities are deterministic and prefix invariant, volume/OI are integral, and weekly ownership is accepted from the weekly response rather than copied from daily segments.

- [x] **Step 2: Add fail-closed tests**

Reject wrong `series_kind`, symbol or frequency; empty bars or segments; uncovered/overlapping segments; non-integral volume/OI; inconsistent coverage; and duplicate output identity. Use one stable public error code: `NEWOW_FUTURES_SERIES_INVALID`.

- [x] **Step 3: Run RED**

```bash
PYTHONPATH=packages/quant-core:services/quant-api \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/newow/test_futures_validation.py
```

Expected: module import failure.

- [x] **Step 4: Implement the pure adapter**

Use the response identity, bars, coverage, clipped segments, requested trading-day window, and the loader-restored full segments. Historical Canonical rows are marked completed/eligible. Require clipped and authoritative owners to agree on contract, then build segment IDs from the full authoritative boundaries; do not query another source or infer a replacement owner.

- [x] **Step 5: Run GREEN, Ruff and Mypy**

Run the new test file, Ruff on the new files, and canonical Mypy over `services/quant-api/app/market_data/newow` plus `packages/quant-core/guiyi_quant/newow`.

---

### Task 4: Evaluate frozen formulas in anchored walk-forward folds

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/research_walk_forward.py`
- Create: `services/quant-api/tests/newow/test_research_walk_forward.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`

**Interfaces:**
- Produces: `WalkForwardFold`, `WalkForwardFoldResult`, `WalkForwardValidationResult`.
- Produces: `run_fixed_formula_walk_forward(bars, folds, strategy, cost_snapshots, execution_constraints) -> WalkForwardValidationResult`.
- Consumes: `build_strategy_intents` and `run_causal_long_only_backtest` from Task 1/2.

- [x] **Step 1: Write failing fold-contract tests**

Reject overlapping test windows, `train_through >= test_since`, windows outside available bars, empty explicit `[train_since, train_through]` or test selections, and mixed product/frequency input with `NEWOW_WALK_FORWARD_PLAN_INVALID`. Gap Bars before `test_since` may extend causal warm-up but never satisfy the explicit training-selection requirement.

- [x] **Step 2: Write failing causality tests**

Use hand-derived Bars where training history creates indicator warm-up but only signals whose source Bar lies in `[test_since, test_through]` may create fills. Assert the fold starts flat, uses only a next-Bar open, excludes an open end position, and does not mutate formula parameters.

- [x] **Step 3: Run RED**

Run the new test file and confirm module import failure.

- [x] **Step 4: Implement fixed-formula folds**

Validate the full input identity and order before slicing folds. For each fold, require at least one Bar in the explicit training interval, select the full causal prefix from `train_since` through `test_through`, clear any training-only strategy position state at `test_since`, retain only intents signaled in the test window, and execute with `require_execution_facts=True`. Aggregate only closed OOS trades and preserve each fold's complete result and lineage.

- [x] **Step 5: Run GREEN and full Newow regression**

```bash
PYTHONPATH=packages/quant-core:services/quant-api \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/newow
```

Expected: all tests pass.

---

### Task 5: Record evidence boundaries and prepare the real-data Gate

**Files:**
- Modify: `docs/tasks/2026-09-04-newow-page-parity-research-kernels.md`
- Create: `docs/tasks/2026-09-04-newow-futures-validation.md`

**Interfaces:**
- Records: exact branch/ref, commands, test counts, implemented contracts, and unresolved external evidence.
- Does not create: a production CLI, API, DB table, Runtime job, Alert, order path, or promotion decision.

- [x] **Step 1: Document fixture evidence separately from real evidence**

State explicitly that production-shaped tests prove contracts but not real futures returns. Record that the eight-table Catalog intentionally contains no fee table and that costs/limits require an external, dated research snapshot.

- [x] **Step 2: Define the later read-only evidence matrix**

Require at least three economically different futures products and all of `1d`, `1w`, `60m`, with at least two observed dominant rollovers per product when history permits. Report bar/segment counts, missing facts, rejected fills, closed/incomplete trades, OOS fold results, cost stress, and source hashes; never substitute individual-stock parity for futures evidence.

- [x] **Step 3: Run final checks**

```bash
git diff --check
PYTHONPATH=packages/quant-core:services/quant-api \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/ruff check \
  packages/quant-core/guiyi_quant/newow \
  services/quant-api/app/market_data/newow \
  services/quant-api/tests/newow
PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
PYTHONPATH=packages/quant-core:services/quant-api \
  /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
  services/quant-api/tests/newow
```

- [x] **Step 4: Commit only this task's files**

Use a task-scoped commit and preserve unrelated worktrees and untracked `.playwright-cli/`.

## External Evidence Gate

After Tasks 1-5 pass and receive independent review, request one fresh user authorization for a bounded, read-only production Catalog query. That later run may read existing Canonical/Catalog facts but must not call RQData, write PostgreSQL/Redis/Parquet, create Events, send notifications, or alter Runtime. Missing cost/limit snapshots keep the result `EXTERNAL_GATE_PENDING`; they must not be replaced with guessed defaults.
