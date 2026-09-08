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

Newow P4 分区编排、typed API、统计截止、来源事实、快照/资源边界、旧 D1 兼容与只读保护：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_older_chart_windows.py \
  services/quant-api/tests/newow/test_historical_snapshot.py \
  services/quant-api/tests/newow/test_data_diagnostics.py \
  services/quant-api/tests/newow/test_product_source_facts.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py \
  services/quant-api/tests/newow/test_product_resource_gate.py \
  services/quant-api/tests/newow/test_product_inflight.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_product_readonly_compatibility.py \
  services/quant-api/tests/newow/test_market_newow_api.py
```

照妖镜专用绘图规则与生命周期定向验证（确定性显示输入，不代表真实行情或当前在线牛哇）：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowZhaoyaoMirrorPrimitive.test.ts tests/NewowProductChartStage.test.ts
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/newow-chart-panes.spec.mjs e2e/newow-product.spec.mjs
```

批量 Session 读取保留端点与交易日关联、缺失失败及查询数量有界：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py
```

真实性能验收须另行使用隔离开发 API 和显式只读数据连接，对相同固定历史快照采集至少五组新进程结果缓存未命中/同进程命中请求；记录 DB 数、读取/计算/序列化、字节与浏览器点击到绘制完成时间，声明未清除 OS/磁盘缓存，并比较完整稳定业务字段。不得借验收下载数据、修改 Canonical、清理系统缓存或切换现役服务。

隔离 fake MDS 的 P4 后端冷/热/长前缀复测入口（不代表浏览器或真实工作站验收）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -s \
  services/quant-api/tests/newow/test_product_performance.py
```

以上 Newow 命令只使用内存 fixture/fake MDS，不连接 RQData、production PostgreSQL/Redis、Runtime 或通知服务。

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

这组测试只使用临时目录/fake service，验证 projection identity、strict/atomic file、API projection-hit/miss、`data update/refresh/contract-warmup --apply` 在 maintenance lease 内的失效、after-market 顺序、default-off projection activation marker 与 maintenance lease；不得以测试为理由执行真实 `guiyi data ... --apply` 或创建 marker。真实 projection-hit 性能 `<200ms` 属于后续明确授权的本地 Runtime read-only manual acceptance，不在普通 pytest 中用 timing sleep 伪造。

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

Physical-contract warm-up（含 `--frequency 15m` / `--frequency 60m` 的 1m dependency、scope hash 隔离与 fail-stop）、同合约 Canonical + Live replay、CLI plan hash 与 projection invalidation：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py
```

该组测试仅使用 fake provider、临时 Catalog/Parquet 与临时路径。它不授权也不执行真实
`guiyi data contract-warmup --apply`；即使 dry-run 得到 plan hash，真实 RQData/Canonical apply 仍需
引用该 exact hash 的单次明确授权。

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

Newow P5 路由/偏好、typed section consumer、九组合图层、参考历史与解释面板定向回归：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowProductRoutes.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailPreferences.test.ts \
  tests/marketHomeRoute.test.ts \
  tests/marketHomePageRoute.test.ts \
  tests/marketHomeResource.test.ts \
  tests/MarketDetailPage.test.ts \
  tests/newowProductTypes.test.ts \
  tests/useNewowProduct.test.ts \
  tests/NewowProductChartStage.test.ts \
  tests/newowProductChartPrimitives.test.ts \
  tests/newowReferencePanel.test.ts \
  tests/newowExplanationPanel.test.ts \
  tests/NewowTrendChartStage.test.ts \
  tests/marketDetailController.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/marketChartEntry.test.ts \
  tests/marketDetailShellComponents.test.ts
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

Newow P6 浏览器验收使用 tracked route-intercept fixture，覆盖九个 strategy×frequency 组合、409 单次恢复、429 不循环重试、参考分页/精确信号定位、解释 evidence-required、既有详情/Home 回归，以及桌面和 `390×844` 移动视口：

```bash
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs e2e/market-home.spec.mjs
```

全量 `test:e2e` 同样包含这些用例。route-intercept timing 只证明浏览器交互，不替代真实 MDS、真实工作站性能或页面原站 parity 验收。

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

Market Home targeted contracts、1280/1440/1920/2560 桌面与390兼容截图、60品种本地排序及三资源请求约束（受控 fixture，不连接生产）。`newow-product` fixture 严格限制默认 origin `http://127.0.0.1:5182`，与其合跑时不覆盖端口；仅首页/详情可使用独立测试端口：

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketHomeTypes.test.ts \
  tests/marketHomeIcons.test.ts \
  tests/marketHomeViewModel.test.ts \
  tests/marketHomeResource.test.ts \
  tests/marketHomeWorkspace.test.ts \
  tests/marketHomePreferences.test.ts \
  tests/marketHomePresentation.test.ts \
  tests/marketHomePageRoute.test.ts \
  tests/marketHomeRoute.test.ts
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-home.spec.mjs
```

## 工程一致性与静态检查

Newow 白色详情 V2 的 MACD 只读适配、同身份图表和交互验收（内存 fixture，不连接生产）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_product_macd.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_product_readonly_compatibility.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py
pnpm -C apps/quant-web exec node --test \
  tests/newowProductTypes.test.ts tests/newowProductChartPrimitives.test.ts \
  tests/NewowProductChartStage.test.ts tests/useNewowProduct.test.ts \
  tests/newowReferencePanel.test.ts tests/newowExplanationPanel.test.ts \
  tests/newowDetailPresentation.test.ts tests/useNewowDailyQuote.test.ts
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs \
  e2e/market-home.spec.mjs e2e/market-detail.spec.mjs
```

上述 V2 测试入口已随实现提供；实际通过状态以本次命令结果为准，不代表发布或 Runtime 验收。
MACD 视觉 fixture 通过既有 Python 内核预生成，保留真实参数 hash 与同区段 Bar 输入；修改受控
输入后先去掉 `--check` 重新生成，再运行下述一致性检查与浏览器截图复核：

```bash
PYTHONPATH=packages/quant-core uv run --project services/quant-api python \
  apps/quant-web/e2e/fixtures/generate_newow_macd.py --check
```

浏览器原站观察只用于设计依据；受控截图与 API fixture 不证明真实工作站或原站完整 parity。

苏冰当日缺口、恢复水位、只读诊断及日志：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_live_recovery.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_recovery_boundary.py \
  services/quant-api/tests/test_live_recovery_guard.py \
  services/quant-api/tests/test_subing_readiness.py \
  services/quant-api/tests/test_runtime_logging.py
```

实际 Lua 测试仅接受显式 `GUIYI_TEST_REDIS_PORT` 指向一次性、无持久卷的隔离 Redis；不得填生产端口。
未配置时该项明确 skip，其余测试使用内存 provider/Redis、临时 SQLite/Parquet 与进程锁。测试不运行
现役 Runtime，不调用真实 RQData，不发送通知。

逐品种诊断命令为 `guiyi runtime subing-readiness --trading-day YYYY-MM-DD --as-of OFFSET_DATETIME`；
`as-of` 必须带时区且不晚于执行时刻。命令只读 PostgreSQL/Redis/Canonical，逐品种报告当前输入与 Scope，
非全部 ready 时退出 1；参数错误退出 2。该结果不证明 provider acceptance 或实际收件，真实连接仍须
位于用户明确授权的只读诊断范围。生产只读执行还必须使用与现役服务启动器相同的 authenticated
`REDIS_URL` 解析结果；只加载未提供该连接结果的 `project.env` 会在订阅快照读取处产生 Redis
authentication failure，此时外层的 `INPUT_DIAGNOSIS_UNAVAILABLE` 不是行情缺口或逐品种 readiness 结论。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

上述 repository-hygiene 命令只检查 Git tree、canonical identity 和安全边界，不授权 branch 删除、Issue/PR 修改、Release、Runtime 或生产写入。

Newow 复刻手册使用独立、锁定的文档工具环境重建：

```bash
uv sync --project tools/docs --locked
uv run --project tools/docs python scripts/docs/build_newow_replication_manual.py \
  --source docs/research/newow-v3.2.82/REPLICATION_MANUAL.md \
  --output output/pdf/newow-v3.2.82-futures-replication-manual.pdf
```

Runtime health、data audit 与 alert status 是只读入口，不能推导 Runtime promotion、自然 evidence 或外部操作授权。`guiyi runtime acknowledge-alert-notification --failure-at <exact ISO timestamp>` 是受控 Redis 写入，普通验证只运行对应 pytest，不执行该命令。


## 捕获源文件的有界 Live 恢复

代码验证在独立 worktree 的 `services/quant-api` 执行。测试使用合成 fixture、临时目录及内存 SQLite，
不读取生产配置、不调用 RQData、不写生产数据；实际 Lua 测试须显式设置 `GUIYI_TEST_REDIS_PORT`
指向本次创建、无持久卷且非 6379 的一次性 Redis，不得使用生产连接。

```bash
.venv/bin/python -m pytest tests/data_foundation/test_captured_live_recovery.py tests/data_foundation/test_live_recovery.py tests/test_live_recovery_guard.py tests/test_captured_recovery_cli.py tests/test_captured_recovery_runtime.py tests/test_alert_cli.py tests/test_subing_readiness.py tests/test_subing_ths_kernel.py -q
```

以下为人工操作语法，普通测试不得执行。CLI 默认只读，但连接生产前仍须明确只读范围。
须先部署通过审查的新 exact tag，证明 Live/Alert/After-market 同根同 commit、共享锁已启用、Live/Alert 心跳新鲜；开发 worktree
和 v1.10.3 的旧心跳不满足该 Gate。源文件必须来自已授权查询，不能为了运行此命令临时下载。

```text
guiyi runtime recover-live-captured --trading-day YYYY-MM-DD --symbol rs --contract RS2609 --source /absolute/captured-source.json --source-sha256 SOURCE_SHA256
```

将上述完整 JSON 输出保存为计划文件后，重新核对五根目标及水位/TTL 副作用，并取得一次明确 apply
授权；下列命令不构成授权，也不会部署/切换 Runtime：

```text
guiyi runtime recover-live-captured --trading-day YYYY-MM-DD --symbol rs --contract RS2609 --source /absolute/captured-source.json --source-sha256 SOURCE_SHA256 --apply --plan /absolute/plan.json --plan-sha256 PLAN_SHA256
```

日期、两种哈希和路径均须替换为当前仍有效的精确计划值，不允许沿用已过期的 2026-09-08 候选。
源和计划读取均有 512 KiB 上限；每次至多 225 行源数据，必须恰好五根增量。
成功返回 `passed`，证明已修复的重复调用仅只读 `noop`；错误非零退出，禁止自动重试。
验收核对五根/原值、恢复水位、provider 请求为零、预算/circuit 未变，再走独立只读 readiness；
不调用历史 evaluator、不重置错误或游标、不发送测试通知，不能由恢复成功宣称 RUNTIME_READY。
