# 测试与验证命令

以下命令只验证代码和本地只读行为；不授权 RQData、Canonical、生产 DB、Runtime、Scope、通知或 release 操作。

## 后端

```bash
uv sync --project services/quant-api --locked
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

Market Home derived projection、API fallback 与 apply invalidation：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py \
  services/quant-api/tests/test_market_home_api.py \
  services/quant-api/tests/test_market_home_projection_api.py
```

这组测试只使用临时目录/fake service，验证 projection identity、strict/atomic file、API projection-hit/miss、`data update/refresh --apply` 在 maintenance lease 内的失效、after-market 顺序、default-off projection activation marker 与 maintenance lease；不得以测试为理由执行真实 `guiyi data ... --apply` 或创建 marker。真实 projection-hit 性能 `<200ms` 属于后续明确授权的本地 Runtime read-only manual acceptance，不在普通 pytest 中用 timing sleep 伪造。

EMA21 10K slope 与整体退役合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_subing_retirement.py \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py
```

SuBing S1-S4 公式、同物理合约 replay、Alert dispatch/Event/notification 与 Scope activation 定向合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_config.py \
  services/quant-api/tests/test_alert_pushplus.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_subing_scope_activation.py
```

RQData session 首分钟锚点、0045 与 shadow repair 的定向合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_session_anchor_repair.py \
  services/quant-api/tests/alembic/test_session_anchor_migration.py \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_subing_scope_activation.py
```

这些测试只使用 fake provider、临时 Parquet/SQLite 与可选 isolated PostgreSQL；不会调用真实 RQData、切换
Canonical、写 production DB/Redis 或停止 Runtime。`prepare/publish --apply` 不是测试命令，分别需要新的单次
真实数据/维护授权。

Isolated PostgreSQL 测试只能指向专用、空白、可销毁的数据库；未设置变量时不得运行：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic
```

0042 → 0043 → 0044 → 0045、disabled + empty-scope seed、session anchor 与 forward-only failure 的专用定向命令仍必须使用同一类隔离数据库：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py \
  services/quant-api/tests/alembic/test_subing_ths_alert_migration.py \
  services/quant-api/tests/alembic/test_session_anchor_migration.py
```

不得把 `guiyi-postgres`、production URL 或任何非空共享数据库用于 isolated PostgreSQL suite。dry-run、migration 测试与 activation 测试均不授权 production migration、Scope apply 或 Rule enable。

## Range Detector Lux V1

Range Detector 只验证 causal kernel、golden parity、v9 图表偏好、warm-up、primitive 与浏览器交互；不授权策略、Alert、数据写入或 Runtime promotion。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py

pnpm -C apps/quant-web exec node --test \
  tests/rangeDetectorLux.test.ts \
  tests/rangeDetectorGolden.test.ts \
  tests/rangeDetectorOverlayWarmup.test.ts \
  tests/rangeDetectorPrimitive.test.ts \
  tests/mainIndicators.test.ts \
  tests/kline-view-model.test.ts
```

## Web

SuBing Alert Rule/API/Event-backed `S↑/S↓` 与 Market Home 定向检查：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alertRuleOwnership.test.ts \
  tests/alerts.test.ts \
  tests/productCurrentAlertEvents.test.ts \
  tests/marketHomeTypes.test.ts \
  tests/marketHomeViewModel.test.ts \
  tests/marketHomeRoute.test.ts
```

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

Market Home targeted contracts、四个截图视口与三资源请求约束：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketHomeTypes.test.ts \
  tests/marketHomeIcons.test.ts \
  tests/marketHomeViewModel.test.ts \
  tests/marketHomeResource.test.ts \
  tests/marketHomeWorkspace.test.ts \
  tests/marketHomePreferences.test.ts \
  tests/marketHomeRoute.test.ts
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-home.spec.mjs
```

## 工程一致性与静态检查

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Runtime health、data audit 与 alert status 是只读入口，不能推导 Runtime promotion、自然 evidence 或外部操作授权。`guiyi runtime acknowledge-alert-notification --failure-at <exact ISO timestamp>` 是受控 Redis 写入，普通验证只运行对应 pytest，不执行该命令。
