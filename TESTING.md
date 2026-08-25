# 测试与验证命令

以下命令仅验证代码和本地只读行为；不授权 RQData、Canonical、生产 DB、Runtime、Scope、通知或 release 操作。

## 后端

```bash
uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
```

Isolated PostgreSQL 测试只能指向专用、空白、可销毁的 isolated DB；未设置该变量时不得运行：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql services/quant-api/tests
```

## RQAlpha local-only automated validation

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/backtest
pnpm --dir apps/quant-web test tests/backtestCapability.test.ts tests/backtestPresentation.test.ts tests/backtests.test.ts
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/backtests.spec.mjs
```

这些 fake-runner、TestClient 与 route-intercepted browser 测试不加载 sidecar，也不运行真实 RQAlpha smoke。
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
uv run --project services/quant-api python -m ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

## Research CLI help

```bash
uv run --project services/quant-api guiyi research subing-calibration --help
uv run --project services/quant-api guiyi research subing-lifecycle --help
uv run --project services/quant-api guiyi research n-structure --help
uv run --project services/quant-api guiyi research jdj-1m --help
uv run --project services/quant-api guiyi research candidate-validation --help
uv run --project services/quant-api guiyi research candidate-robustness --help
```

## Web

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

## Contract and static checks

```bash
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Runtime health、data audit 与 alert status 是只读入口；它们不能推导 Runtime promotion、自然 evidence 或外部操作授权。
