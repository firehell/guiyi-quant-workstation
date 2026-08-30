# 测试与验证命令

以下命令仅验证代码和本地只读行为；不授权 RQData、Canonical、生产 DB、Runtime、Scope、通知或 release 操作。

## 后端

```bash
uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
```

Isolated PostgreSQL 测试只能指向专用、空白、可销毁的 isolated DB；未设置该变量时不得运行：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql services/quant-api/tests
```

## 工程一致性与静态检查

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
uv run --project services/quant-api python -m ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

## Research CLI help

```bash
uv run --project services/quant-api guiyi research subing-calibration --help
uv run --project services/quant-api guiyi research subing-lifecycle --help
```

## Web

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

## Contract and static checks

本地 Homebrew 或 PATH 中的 `openspec` CLI（`uv run --with openspec` 不可执行，PyPI 无对应包）：

```bash
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Runtime health、data audit 与 alert status 是只读入口；它们不能推导 Runtime promotion、自然 evidence 或外部操作授权。

`guiyi runtime acknowledge-alert-notification --failure-at <exact ISO timestamp>` 是受控 Redis 写入，
不是只读测试命令。它不发送通知或重放 Event，但实际 Runtime 执行仍需单次明确授权；普通验证只运行
对应 pytest，不执行该命令。

## SuBing Strategy 全历史效果

定向验证：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_strategy_direction_context.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_lineage.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_incremental.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_market_research_overlays_api.py
pnpm -C apps/quant-web test
pnpm -C apps/quant-web exec vue-tsc -b
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-research.spec.mjs --grep "full-history performance|old full-history performance request"
```

真实 schema-v2 采纳、active60 刷新与 CLI `--warm-cache` 会写 Git 外派生 cache，须在独立数据写入 Gate 后执行：`guiyi research subing-strategy-performance --scope active --warm-cache`。测试、HTTP 读取与盘后 derived 代码路径不替代该 Gate，也不授权 Runtime promotion。
