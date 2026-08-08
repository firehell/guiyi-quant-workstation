# Task 2 Report — Candidate target consolidation

## Scope completed

- Replaced the one-off Candidate/Gate A operator surface with the existing
  `guiyi data update` and `guiyi data audit` commands.
- Added reusable `HistoricalDataTarget` composition. Active and Candidate both
  use the same `HistoricalDataManager` builder; Candidate is always
  `RQData-only/legacy=None`.
- Candidate selection accepts an explicit root and fresh/extend mode, while
  accepting Candidate database configuration only from
  `GUIYI_CANDIDATE_DATABASE_URL`; no CLI database URL exists.
- Enforced a normalized, non-symlink Candidate root beneath
  `data/canonical-candidates`, disjoint from the active Canonical root, with
  no implicit root.
- Added single-root `candidate.json` provenance: immutable digested identity
  (isolated catalog/session, root, universe, floor, source policy, code SHA)
  and monotonic `recorded_through`; writes use same-directory atomic replace.
- Fresh requires an empty root with no metadata and all ten active Candidate
  tables empty. Extend requires matching metadata/identity and non-regressing
  through. Candidate precondition failures occur before manager/provider
  construction and emit only bounded reason-code diagnostics.
- Deleted `candidate_rqdata_operator.py`, `gate_a_candidate_operator.py`,
  `gate_a_operator.py`, and their task-named tests after replacement tests
  passed.

## TDD evidence

1. Added replacement tests to the existing composition and CLI modules.
2. RED command:

   ```bash
   PYTHONPATH=services/quant-api:packages/quant-core \
   /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
   services/quant-api/tests/data_foundation/test_composition.py \
   services/quant-api/tests/data_foundation/test_cli.py
   ```

   Result before implementation: 4 failed. The new failures were missing
   `HistoricalDataTarget` / `CandidateTargetError` and unrecognized Candidate
   CLI arguments. One pre-existing legacy fixture also required isolated raw
   roots; its test setup was made self-contained without changing legacy code.

3. The bounded Candidate diagnostic test was mutation-checked: temporarily
   routing Candidate failures through the generic CLI exception wrapper made
   the test fail because generic keys were present; the bounded handler was
   restored before final validation.

## Final validation

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
services/quant-api/tests/data_foundation/test_composition.py \
services/quant-api/tests/data_foundation/test_cli.py
# 14 passed

PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
services/quant-api/tests/data_foundation
# 87 passed

PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/ruff check \
services/quant-api/app/market_data/composition.py \
services/quant-api/app/guiyi_cli \
services/quant-api/tests/data_foundation/test_composition.py \
services/quant-api/tests/data_foundation/test_cli.py
# All checks passed
```

The documented mypy command was also run. It reported one existing unrelated
error in `app/services/runtime_health.py` (`BaseWorker` passed where `Worker`
is required); no error was reported in Task 2 files.

## External boundary

No RQData client call, Candidate/production DB mutation, Candidate/production
Canonical write, Runtime action, notification, or order was performed. Actual
Candidate construction remains Gate A and needs a new, scoped execution intent.

## Review amendment

Follow-up review fixed the fresh metadata sequencing: the strict empty-root
check remains in `validate_update` before manager/provider construction, while
`record_through` now permits Canonical files published by that same validated
fresh run and still refuses a pre-existing metadata file. The regression test
publishes a fixture file between fresh preflight and metadata write, then
confirms extend and audit validation remain usable.

The Candidate-root check now explicitly derives relative paths from
`PROJECT_ROOT` before walking symlink components; a regression test changes to
an unrelated current directory and verifies a symlink inside the project
Candidate parent is rejected. `services/quant-api/README.md` now lists the
current `update|bootstrap|repair|audit` data CLI surface.

Review RED:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
services/quant-api/tests/data_foundation/test_composition.py
# 1 failed, 7 passed (fresh metadata sequencing regression)
```

Review GREEN:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
services/quant-api/tests/data_foundation/test_composition.py \
services/quant-api/tests/data_foundation/test_cli.py
# 15 passed

PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/pytest -q \
services/quant-api/tests/data_foundation
# 88 passed
```
