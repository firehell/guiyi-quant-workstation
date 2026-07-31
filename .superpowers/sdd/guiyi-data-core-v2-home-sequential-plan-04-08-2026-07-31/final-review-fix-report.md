# Task 04 Final Review Fix Report

Date: 2026-07-31

Base reviewed head: `a858af7c2e8a956b7a923d485ad0a78d20b87128`

Implementation commit: recorded in the final handoff after this report and the fixes are committed together.

Status: `CODE_COMPLETE_EXTERNAL_GATE_PENDING`

No production migration, real RQData call, canonical/legacy Parquet write, production PostgreSQL
write, push, merge, Runtime operation, deletion, notification, or feature-flag enablement was
performed.

## Finding closure

### Critical

1. Loaded-source checkout binding
   - The migration CLI derives the repository root from the loaded `app` module and requires it
     to equal the caller project root before inventory, database, provider, or writer access.
   - A different-checkout bypass regression proves the command fails before inventory.

2. Complete immutable apply facts
   - Packet/current facts now bind Catalog/partition/gap/mapping digests, calendar/session facts,
     the direct frequency matrix, and the exact per-DatasetKey mapping-valid/missing-window write
     plan under one recomputed state digest.
   - Gate validation rejects a missing or altered current-state component and binds the partial
     receipt path.

3. Valid direct matrix and mapping-segment coverage
   - The matrix is frozen as continuous `1m/1d/1w` and actual-dominant `1m/1d`.
   - Actual-dominant coverage and reads are partitioned by rank=1 mapping-valid sessions; gaps
     outside a contract's active segment no longer invalidate that segment.
   - Semantic validation rejects actual-dominant weekly identity.

4. Web/API window and lineage contract
   - Canonical Web requests use timezone-bearing ISO/RFC3339 values and reject date-only values;
     the legacy route retains its prior date-only request shape.
   - Source lineage is stable across request windows, while `request_identity_token` binds each
     exact window. FastAPI integration tests cover offset normalization and differing windows.

### Important

1. EMA warm-up
   - The indicator endpoint expands the canonical source query by the required EMA lookback and
     returns only the display window; source/display counts and first ready value are tested.

2. Frozen Shadow execution and reasoned exceptions
   - Shadow execution requires the complete valid 13-query set (seven continuous plus six
     actual-dominant; weekly actual was removed by the Critical matrix correction), compares full
     identity/OHLCV/boundaries, and permits only field-scoped missing-value exceptions with a
     reason. The receipt has a deterministic digest.

3. Durable resumable apply receipt
   - Mapping and each committed dataset are recorded atomically with file and directory fsync.
     Re-open validates the bound facts digest; completed datasets reconcile and skip on resume.

4. DatasetKey/BarQuery semantic validation
   - Continuous identities require exact `{SYMBOL}.MAIN`; actual identities require a matching
     concrete contract, with the intentional unresolved actual query represented only by `None`.

5. Coverage integrity semantics
   - Catalog-only coverage now reports `catalog_only_unverified` rather than `passed`; read-time
     manifest/file checksum verification remains the authority.

6. Retry classification and evidence
   - Only transient timeout/connection failures retry. Deterministic contract, quality, schema,
     and store failures propagate immediately; exhausted transient failures retain attempt count,
     exception type, and error code in gap evidence.

### Directly touched minor items

- Weekly source reads retain seven-day padding for midweek windows.
- Tests cover Gate state, mapping-segment windows, RFC3339 Web/API behavior, variable request
  identity, EMA warm-up, durable receipts, and deterministic no-retry behavior.
- Canonical documents now state the 13-query set, valid direct matrix, split identity tokens, and
  distinguish current fix-wave evidence from older broad baselines.
- Inventory naming was not redesigned because the read-only inventory behavior was not modified;
  its existing evidence remains explicitly plan-only and performs no reuse write.

## TDD and verification evidence

Focused red/green cycles were captured while implementing the findings, including semantic
identity rejects, deterministic no-retry, mapping-segment reads, checkout bypass, Web RFC3339,
source/request identity separation, and EMA warm-up.

Final commands and results:

```text
services/quant-api/.venv/bin/python -m pytest -q services/quant-api/tests/data_core
exit_code=0; passed=371; failed=0; skipped=0

targeted pytest set covering the touched backend contracts, apply, reader, CLI, and API modules
exit_code=0; passed=195; failed=0; skipped=0

uv run --project services/quant-api ruff check <all touched backend Python files>
exit_code=0; result=All checks passed

pnpm --dir apps/quant-web test -- --run
exit_code=0; passed=169; failed=0; skipped=1

pnpm --dir apps/quant-web build
exit_code=0; result=vue-tsc and Vite build passed; 3616 modules transformed

git diff --check
exit_code=0
```

The pre-fix broader baseline remains `2242 passed, 36 skipped` for backend full,
`35 passed` for isolated PostgreSQL migration, and `18 passed` for canonical-enabled Playwright.
Those three broader commands were not rerun after this fix wave and are not presented as current
post-fix evidence.

## Remaining external Gates

- Independent review, CI, and integration into `develop` are pending.
- Production remains at the previously observed `20260721_0025`; no production migration ran.
- A clean exact-head packet must be regenerated after commit and separately approved before any
  real migration/apply or historical Shadow.
- Real RQData, canonical Parquet/PostgreSQL apply, and historical Shadow remain not run.
- The JM canonical Web flag remains disabled. This work does not establish Runtime readiness,
  profitability, live delivery, notification permission, order creation, or automatic trading.
