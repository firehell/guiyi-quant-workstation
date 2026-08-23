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

## 十个只读 Research CLI

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
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-diagnostic --help
```

## MFM Diagnostic Phase A 代码边界

```bash
PYTHONPATH=services/quant-api:packages/quant-core UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_exact_json_contract.py services/quant-api/tests/test_main_force_mirror_v2.py services/quant-api/tests/test_main_force_mirror_v2_audit.py services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py services/quant-api/tests/research/test_main_force_mirror_diagnostic_contract.py services/quant-api/tests/research/test_main_force_mirror_diagnostic_analysis.py services/quant-api/tests/research/test_main_force_mirror_diagnostic_models.py services/quant-api/tests/research/test_main_force_mirror_diagnostic_cli.py services/quant-api/tests/test_research_composition.py services/quant-api/tests/test_research_cli_boundaries.py
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

path = Path("data/universe/active_products.txt")
expected = "d2f7e8387fa9dd92b8720ed703de3a7bbc1ef79d0d75340b246783bab079fd1d"
assert sha256(path.read_bytes()).hexdigest() == expected
PY
```

以下是未来需要单独授权的真实 Historical read-only evidence 命令；本轮不运行，也不在仓库内生成报告 artifact：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-diagnostic --protocol main_force_mirror_diagnostic_phase_a_v1
```

## MFM sequence forensic code path

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_main_force_mirror_v2.py services/quant-api/tests/test_indicator_registry_v1.py services/quant-api/tests/data_foundation/test_member_rank_snapshot.py services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py services/quant-api/tests/data_foundation/test_market_api.py services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/research/test_research_cli_parser_requests.py services/quant-api/tests/research/test_research_cli_mirror_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --symbol jm --series-kind actual_dominant --frequency 60m --since 2026-03-10 --through 2026-03-30 --forensic
```

## MFM sequence forensic active60 read-only evidence Gate

```bash
set -eu
tmp_dir="$(mktemp -d /private/tmp/guiyi-mfm-v2-sequence-forensic.XXXXXX)"
test -n "$tmp_dir"
test ! -L "$tmp_dir"
case "$(cd "$tmp_dir" && pwd -P)" in
  /private/tmp/guiyi-mfm-v2-sequence-forensic.*) ;;
  *) exit 1 ;;
esac
while IFS= read -r symbol || [ -n "$symbol" ]; do
  [ -z "$symbol" ] && continue
  case "$symbol" in
    *[!a-z0-9_]*) exit 1 ;;
  esac
done < data/universe/active_products.txt
duplicate_symbol="$(awk 'NF { print }' data/universe/active_products.txt | sort | uniq -d | head -n 1)"
test -z "$duplicate_symbol"
while IFS= read -r symbol || [ -n "$symbol" ]; do
  [ -z "$symbol" ] && continue
  command_status=0
  UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --symbol "$symbol" --series-kind actual_dominant --frequency 60m --since 2023-01-01 --through 2026-08-20 >"$tmp_dir/$symbol.json" 2>"$tmp_dir/$symbol.stderr" || command_status=$?
  printf '%s\n' "$command_status" >"$tmp_dir/$symbol.status"
done < data/universe/active_products.txt
printf '%s\n' "$tmp_dir"
```

## MFM sequence forensic OS-temp fail-closed cleanup

```bash
set -eu
test ! -L "$tmp_dir"
real_dir="$(cd "$tmp_dir" && pwd -P)"
case "$real_dir" in
  /private/tmp/guiyi-mfm-v2-sequence-forensic.*) ;;
  *) exit 1 ;;
esac
unexpected_node="$(find "$real_dir" -mindepth 1 -maxdepth 1 ! -type f -print -quit)"
test -z "$unexpected_node"
unexpected_name="$(find "$real_dir" -mindepth 1 -maxdepth 1 -type f ! \( -name '*.json' -o -name '*.stderr' -o -name '*.status' \) -print -quit)"
test -z "$unexpected_name"
active_count="$(awk 'NF { count += 1 } END { print count + 0 }' data/universe/active_products.txt)"
file_count="$(find "$real_dir" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')"
test "$file_count" -eq "$((active_count * 3))"
while IFS= read -r symbol || [ -n "$symbol" ]; do
  [ -z "$symbol" ] && continue
  rg -qx "$symbol" data/universe/active_products.txt
  test -f "$real_dir/$symbol.json"
  test ! -L "$real_dir/$symbol.json"
  test -f "$real_dir/$symbol.stderr"
  test ! -L "$real_dir/$symbol.stderr"
  test -f "$real_dir/$symbol.status"
  test ! -L "$real_dir/$symbol.status"
done < data/universe/active_products.txt
rm -rf -- "$real_dir"
```

## JDJ JM 1m 参考策略回放

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_jdj_strategy_contract.py services/quant-api/tests/research/test_jdj_strategy_engine.py services/quant-api/tests/research/test_jdj_strategy_replay_service.py services/quant-api/tests/test_jdj_context.py services/quant-api/tests/test_jdj_trend_follow.py services/quant-api/tests/test_jdj_trend_reentry.py services/quant-api/tests/test_jdj_key_level_breakout.py services/quant-api/tests/research/test_jdj_research_service.py services/quant-api/tests/research/test_jdj_candidate_validation_service.py services/quant-api/tests/research/test_jdj_robustness_service.py services/quant-api/tests/test_market_research_overlays_api.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/research/jdj_strategy services/quant-api/tests/research/test_jdj_strategy_*.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/research/jdj_strategy
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
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
