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

## SuBing Strategy Stage 2 no-write shadow

默认命令不构成真实 read-only scope 授权，且 manual acceptance 必须 skipped：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m manual_acceptance \
  services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py
```

以下 recorded production-format stream 仅使用提交内 fixture、sealed Null Event/notification/cache/status 依赖与只读 fake readers，属于普通仓库验证：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py \
  -k recorded_stream
```

真实 read-only shadow 只有在用户对目标 PostgreSQL、Canonical 与 completed-Live reader 给出当次精确只读授权，并且 operator 已注入 sealed Null Event/notification、no cache/status writer、已验证 read-only PostgreSQL transaction 与只读 reader adapter 后，才可额外设置 `GUIYI_SUBING_STAGE2_SHADOW=1` 运行同一 `-m manual_acceptance` 命令。环境变量本身不是授权；未满足任一依赖时必须 fail-closed。该命令不创建 AlertEvent、不改 Scope/Redis/Canonical、不发送 PushPlus、不启动 Runtime。

## Contract and static checks

```bash
uv run --with openspec openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Runtime health、data audit 与 alert status 是只读入口；它们不能推导 Runtime promotion、自然 evidence 或外部操作授权。

`guiyi runtime acknowledge-alert-notification --failure-at <exact ISO timestamp>` 是受控 Redis 写入，
不是只读测试命令。它不发送通知或重放 Event，但实际 Runtime 执行仍需单次明确授权；普通验证只运行
对应 pytest，不执行该命令。
