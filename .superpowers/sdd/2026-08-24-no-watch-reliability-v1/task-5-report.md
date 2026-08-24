## Task 5 report: opt-in data audit progress

### Status

`CODE_COMPLETE / TEST_COMPLETE`; no external operation was attempted.

### RED

- `test_audit_progress_writes_compact_ndjson_to_stderr` failed before implementation because `--progress` was rejected with exit code `2`.
- The two observer tests failed before implementation because `HistoricalDataManager.audit()` did not accept `observer`.
- The default audit stdout byte-for-byte regression test remained green before the new behavior, confirming the existing contract baseline.

### GREEN and verification

```text
PYTHONPATH=services/quant-api:packages/quant-core UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/data_foundation
606 passed in 3.89s

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/guiyi_cli/data_commands.py services/quant-api/app/guiyi_cli/data_parser.py services/quant-api/app/guiyi_cli/main.py services/quant-api/app/market_data/historical_data_manager.py services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/data_foundation/test_historical_data_manager.py
All checks passed!

MYPYPATH=services/quant-api:packages/quant-core UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/guiyi_cli/data_commands.py services/quant-api/app/guiyi_cli/data_parser.py services/quant-api/app/guiyi_cli/main.py services/quant-api/app/market_data/historical_data_manager.py
Success: no issues found in 4 source files

git diff --check
exit 0
```

### Changed files

- `services/quant-api/app/guiyi_cli/data_parser.py`: audit-only `--progress` flag.
- `services/quant-api/app/guiyi_cli/data_commands.py` and `main.py`: opt-in stderr NDJSON writer with first-failure disablement.
- `services/quant-api/app/market_data/historical_data_manager.py`: optional structured observer and per-product started/completed events.
- `services/quant-api/tests/data_foundation/test_cli.py` and `test_historical_data_manager.py`: stdout compatibility, NDJSON, writer-failure, event timing, known-gap, and unknown-exception coverage.
- `TESTING.md` and `docs/DATA_CENTER.md`: opt-in, stderr, provider-free/default-compatible behavior.

### Self-review

- Default audit keeps the old manager method invocation and exact stdout output; it neither constructs an observer nor writes stderr.
- The observer is modelled as a structured value. It emits started before each symbol, completed only after that symbol's findings are determined, uses normalized symbols and fixed total, and does not emit completed for unknown exceptions.
- The progress writer catches only its own output failure, permanently disables later records, and leaves audit exceptions and final stdout handling untouched.
- Audit remains provider-free with `provider_requests=0`; no quick mode or MaintenanceResult/stdout schema change was introduced.

### Concerns and boundaries

- No real `guiyi data audit`, RQData call, Canonical/DB write, Runtime operation, release, or main change was run.
- The worktree contains only the Task 5 files listed above before commit.
