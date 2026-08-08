# Task 4 report — documentation and repository-only validation

## Scope and result

Completed the repository-only C2.5 documentation and validation work. The active data contract now
describes the existing `guiyi data update/audit` Candidate target, environment-only Candidate DB
configuration, fresh/extend metadata, root containment, no reset/resume operations, historical provider
Calendar/Session facts, and direct-weekly ISO alignment. The report and status do not expose a connection
string or credentials.

No Gate A, Gate B, or Gate C was executed. This task did not call RQData, write Candidate/production DB,
write Canonical data, start services, change Runtime, send notifications, or create a Gate artifact.

## Documentation changed

- `docs/DATA_CENTER.md`: Candidate CLI/env boundary and C2.5 invariants.
- `docs/tasks/GY-DATA-CORE-V2.md`: active business contract and external-Gate separation.
- `TESTING.md`: focused C2.5 fixture suite and retired-operator scan command.
- `STATUS.md`: C2.5 repository-only facts and this worktree's exact validation state.
- `openspec/changes/converge-canonical-data-foundation/tasks.md`: task 8.2 marked complete; 8.3–8.9 remain unchecked.

## Validation

Passed:

```text
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation/test_composition.py services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/data_foundation/test_infrastructure.py services/quant-api/tests/data_foundation/test_maintenance.py
# 52 passed

PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation
# 95 passed

uv run --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant
# All checks passed

MYPYPATH=services/quant-api uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/market_data services/quant-api/app/guiyi_cli services/quant-api/app/api/market.py services/quant-api/app/models/data_center.py services/quant-api/app/models/data_core.py
# Success: no issues found in 19 source files

cd services/quant-api && PYTHONPATH=. uv run alembic upgrade 20260808_0035:20260808_0036 --sql
# passed; static SQL generation only

openspec validate converge-canonical-data-foundation --strict
# valid

git diff --check
# passed
```

The retired operator scan found no active source/test/UI/document reference.

Not run: the isolated PostgreSQL migration suite, because `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` was not
configured and this task must not create external DB writes.

Blocked environment checks: `npm --prefix apps/quant-web test` ran 53 tests (51 passed, 1 skipped, 1 failed)
because `apps/quant-web/node_modules/vite/bin/vite.js` is absent; `npm --prefix apps/quant-web run build`
stopped before compilation because `vue-tsc` is absent. No dependency installation or frontend source change
was performed.
