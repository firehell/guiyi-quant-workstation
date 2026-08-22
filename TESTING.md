# 测试与验证命令

更新时间：2026-08-22

## 依赖

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

## 工程、版本与文档一致性

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_health.py services/quant-api/tests/test_runtime_entry.py
python3 scripts/engineering/secret_scan.py --json
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
find deploy/launchd -type f -name '*.plist.template' -print0 | xargs -0 -n1 plutil -lint
git diff --check
git status --short
```

## 后端基线与拆分目录

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/execution_review
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='<isolated-postgresql-url>' UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m isolated_postgresql services/quant-api/tests
```

## Ruff 与 Mypy

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/market_data services/quant-api/app/research services/quant-api/app/guiyi_cli services/quant-api/app/alerts services/quant-api/app/execution_review services/quant-api/app/runtime_entry.py services/quant-api/app/services/runtime_health.py services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py
```

## Research split tests

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_research_cli_parser_requests.py services/quant-api/tests/research/test_research_cli_candidate.py services/quant-api/tests/research/test_research_cli_convergence.py services/quant-api/tests/research/test_research_cli_mirror_robustness.py services/quant-api/tests/test_research_composition.py services/quant-api/tests/test_research_cli_boundaries.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_subing_lifecycle_contracts.py services/quant-api/tests/research/test_subing_lifecycle_transitions.py services/quant-api/tests/research/test_subing_lifecycle_causality.py services/quant-api/tests/research/test_subing_lifecycle_research_service.py services/quant-api/tests/research/test_subing_calibration_service.py services/quant-api/tests/research/test_subing_candidate_validation_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_n_structure_research_service.py services/quant-api/tests/research/test_n_candidate_validation_service.py services/quant-api/tests/research/test_jdj_research_service.py services/quant-api/tests/research/test_jdj_candidate_validation_service.py services/quant-api/tests/research/test_jdj_candidate_validation_calendar.py services/quant-api/tests/research/test_jdj_robustness_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_multi_candidate_robustness_service.py services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py
```

## Execution Review split tests

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache PYTHONPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api pytest -q services/quant-api/tests/execution_review/test_mutations.py services/quant-api/tests/execution_review/test_corrections_reviews.py services/quant-api/tests/execution_review/test_queries.py services/quant-api/tests/test_execution_review_contracts.py services/quant-api/tests/test_execution_review_pnl.py services/quant-api/tests/test_execution_review_models.py services/quant-api/tests/test_execution_review_api.py services/quant-api/tests/test_execution_review_reconstruction.py services/quant-api/tests/test_execution_review_reconciler.py
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='<isolated-postgresql-url>' UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache PYTHONPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api pytest -q services/quant-api/tests/execution_review/test_isolated_postgresql_concurrency.py services/quant-api/tests/alembic/test_execution_review_v1_migration.py
```

## 九个只读 Research CLI

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research subing-calibration --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research subing-lifecycle --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research n-structure --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research jdj-1m --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-validation --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-robustness --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-dossier --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-relationships --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --help
```

## MFM sequence forensic code path

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_main_force_mirror_v2.py services/quant-api/tests/test_indicator_registry_v1.py services/quant-api/tests/data_foundation/test_member_rank_snapshot.py services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py services/quant-api/tests/data_foundation/test_market_api.py services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/research/test_research_cli_parser_requests.py services/quant-api/tests/research/test_research_cli_mirror_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --symbol jm --series-kind actual_dominant --frequency 60m --since 2026-03-10 --through 2026-03-30 --forensic
```

## Web

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
pnpm --dir apps/quant-web build
```

## OpenSpec

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
```

## Runtime 无副作用入口测试

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_runtime_entry.py services/quant-api/tests/test_runtime_health.py services/quant-api/tests/data_foundation/test_operational_universe.py services/quant-api/tests/data_foundation/test_live_market.py services/quant-api/tests/data_foundation/test_after_market.py services/quant-api/tests/data_foundation/test_market_read.py services/quant-api/tests/data_foundation/test_market_websocket.py
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
```
