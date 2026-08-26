# Task 1 report — 后端、API 与 CLI 收敛

## Status

`CODE_COMPLETE` and `TEST_COMPLETE`.  No external Gate was requested or used.

## Implementation

- Removed the JDJ research package, replay strategy package, and JDJ Active60 robustness implementation, plus all JDJ composition builders and callers.
- Removed the JDJ strategy historical HTTP endpoint and its Pydantic request/action/response DTOs.  The N Structure bands router remains mounted and its existing identity/error contracts remain covered.
- Reduced `guiyi research` to the retained `subing-calibration`, `subing-lifecycle`, and `n-structure` commands.  The public candidate-validation and candidate-robustness command surfaces, factories, requests, dispatch and render adapters were removed.
- Kept SuBing and N candidate-validation services, multi-candidate robustness, `ActualDominantResearchSegmentLoader`, N Historical routing, and MarketDataService composition intact.
- Removed JDJ-only implementation-shape, replay, candidate, robustness and CLI tests rather than converting them to tombstone/source-grep tests.  Updated the executable public CLI contract to the three retained commands.

## RED evidence

Before production changes:

```text
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_research_cli_parser_requests.py::test_research_parser_exposes_only_the_retained_readonly_commands \
  services/quant-api/tests/test_market_research_overlays_api.py::test_public_overlay_schemas_keep_only_retained_projection_families \
  services/quant-api/tests/test_market_research_overlays_api.py::test_historical_overlay_api_keeps_n_structure_as_the_only_research_overlay
```

Result: `2 failed, 1 passed`.  The parser still exposed `jdj-1m`, `candidate-validation`, and `candidate-robustness`; OpenAPI still exposed `/api/v1/market/research/jdj-strategy/history`.

## GREEN and final verification

- Same focused contract command after implementation: `17 passed`.
- `uv run --project services/quant-api guiyi research subing-calibration --help`; `subing-lifecycle --help`; `n-structure --help`: all exit 0.
- `PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests`: `2125 passed, 3 skipped, 1 deselected`.
- `PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py`: `8 passed`.
- `PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant`: `Success: no issues found in 131 source files`.
- `uv run --project services/quant-api python -m ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering`: `All checks passed!`.
- `git diff --check`: exit 0.

## Files

- Modified CLI: `services/quant-api/app/guiyi_cli/main.py`, `research_parser.py`, `research_requests.py`, `research_commands.py`, `research_payloads.py`.
- Modified Historical API/composition: `services/quant-api/app/research/composition.py`, `historical_overlay_api.py`, and `services/quant-api/app/schemas/research_overlays.py`.
- Deleted JDJ backend implementation from `services/quant-api/app/research/jdj/`, `jdj_strategy/`, and the JDJ robustness modules; deleted their JDJ-only test/fixture files.
- Updated retained API/CLI/composition contracts and engineering entrypoint expectation tests.

## Self-review

- Confirmed no JDJ reference remains in `services/quant-api/app`.
- Confirmed no migration, strategy formula, Scope, Runtime, DB/Redis, notification, Web, report/data artifact or documentation change was made in this task.
- The only post-change regressions were a missing N router composition import and one boundary test still naming a removed renderer; both were root-caused and fixed, then the final full validation passed.

## Concerns

JDJ policy/candidate/protocol/profile data and historical report artifacts intentionally remain for Task 3.  This task does not release, promote Runtime, mutate data, or perform external operations.
