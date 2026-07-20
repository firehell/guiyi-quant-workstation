# JM Historical Catch-up Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the JM-only, no-write S6-02 foundation that can generate a hash-bound S6-03 execution packet and enforce historical/live freshness before any real apply.

**Architecture:** A dedicated catch-up service owns target-day resolution, immutable snapshot binding, gap planning, expected version/path planning, packet hashing and apply preflight. Existing RQData download, aggregation and Profile switch services remain the eventual write executors; the new foundation does not add a parallel market reader. `LiveTargetContractResolver` consumes the same required-date freshness semantics.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pandas, pathlib, hashlib, argparse, pytest.

## Global Constraints

- Scope is JM-only; no other product can be planned or applied.
- This task does not call RQData or write canonical DB, Parquet, manifests, Profile bindings or live tables.
- Existing assets are immutable; planned outputs are create-only and packet-specific.
- `warning` and `failed` never satisfy the formal binding Gate.
- No live runtime, SignalEvent, notification, strategy, backtest or order changes.

---

### Task 1: Dynamic target and gap plan

**Files:**
- Create: `services/quant-api/app/services/rqdata_ingest/jm_historical_catchup.py`
- Test: `services/quant-api/tests/test_jm_historical_catchup.py`

**Interfaces:**
- Produce `resolve_latest_completed_trading_day(...)`, `build_gap_plan(...)`, `build_rqdata_request_plan(...)` and immutable plan dataclasses.

- [x] Write failing tests for missing calendar, incomplete sessions, provider finality, weekend/holiday, one-day/multi-day gaps, complete week and mapping roll segments.
- [x] Run the focused tests and confirm behavior failures.
- [x] Implement the minimum pure planning functions and rerun to green.

### Task 2: Hash-bound packet and apply preflight

**Files:**
- Modify: `services/quant-api/app/services/rqdata_ingest/jm_historical_catchup.py`
- Create: `services/quant-api/scripts/jm_historical_catchup.py`
- Test: `services/quant-api/tests/test_jm_historical_catchup.py`

**Interfaces:**
- Produce `build_approval_packet(...)`, `packet_hash(...)`, `verify_approval_packet(...)` and CLI `packet`/`verify` commands.

- [x] Write failing tests for deterministic hash, bound fact drift, non-JM rejection, existing output collision, warning quality and dry-run zero side effects.
- [x] Implement canonical JSON hashing, exact invalidators, create-only output templates and redacted CLI output.
- [x] Rerun focused tests to green.

### Task 3: Live target required-date freshness

**Files:**
- Modify: `services/quant-api/app/services/live_target_contracts.py`
- Create: `services/quant-api/tests/test_live_target_freshness.py`

**Interfaces:**
- Extend `resolve_product(..., required_date=None)` and `resolve_ready_actual_contract(..., required_date=None)` without changing callers that omit the date.

- [x] Write failing tests for stale mapping, stale parameters, stale actual 1m/5m/15m and passed current coverage.
- [x] Implement fail-closed required-date checks using existing metadata and MarketDataFile models.
- [x] Run focused and live-runtime regression tests.

### Task 4: Verification and handoff

**Files:**
- Modify: `docs/tasks/JM-HISTORICAL-CATCHUP-FOUNDATION-S6-02.md`

- [x] Run the full task test matrix, ruff, sensitive scan and `git diff --check`.
- [x] Confirm no `data/**`, DB, Profile, live, SignalEvent or notification writes occurred.
- [x] Record `JM_HISTORICAL_CATCHUP_IMPLEMENTED` only if all code/test gates pass; leave S6-03 real Gates pending.
