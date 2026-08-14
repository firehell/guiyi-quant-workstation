# 测试与验证入口

更新时间：2026-08-14

所有写入测试必须使用 `tmp_path`、临时 Canonical root 和隔离数据库；测试 URL 不得指向 Runtime 或
生产数据库。真实数据、Runtime switch 和通知不属于测试命令的隐含权限。

## 工程与仓库检查

```bash
python3 scripts/engineering/secret_scan.py --json
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q tests/engineering
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
git diff --check
```

Secret scan 默认只扫描 `git ls-files`，只报告文件、行号和规则类别，不输出命中内容。

## 后端与前端基线

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

## SuBing Factor / Calibration / Signal Observation V1

### 无副作用实现与回归验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py::test_latest_dominant_segment_returns_current_contiguous_rank1_segment \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py::test_latest_dominant_segment_fails_closed_for_missing_map_after_known_contract \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

这些命令覆盖 strict slope-only Calibration loader、MarketDataService-only research/CLI、scoped MACD
equivalence、Signal pure core、`SubingReadService` reciprocal orchestration、API、Web unit/E2E、
current-rank1 segment、Historical/completed Live seam 和有效当前合约视图。测试只使用 fixture、mock、
临时目录或隔离数据库，不运行 provider、Canonical/DB/Redis 写入、Runtime switch 或通知。

`guiyi research subing-calibration` 本身是只读 Historical research：只通过 `MarketDataService` 取数，
输出 stdout JSON，不直接读 provider，也不写 DB、Canonical 或 Redis，不自动 promotion。Discovery/
Validation stdout 不能作为正式 artifact；测试只验证 CLI 合同，不运行真实研究窗口。当前 accepted
intraday Calibration 仅由 Git-tracked slope-only artifact 提供，zero-distance 不参与 executable Signal。

## Alert V1

### 无副作用单元、集成与浏览器验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_wecom.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_market_read.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  tests/engineering/test_alert_runtime_launchd.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/alert-v1.spec.mjs

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
```

这些命令只使用隔离数据库、mock sender、mock API 或 render-only，不启动真实 AlertRuntime、不执行生产
migration，也不发送真实企业微信。`--confirm-alert-runtime` 不是测试参数。

### 三个独立受控外部 Gate

- production PostgreSQL migration：仅在明确授权后升级到 `20260813_0037`，并读回八表 Market Catalog
  未变、两张 Alert Application 表和空 Scope seed；不发送通知。
- real WeCom canary：仅在独立明确授权后执行 `guiyi runtime alert-canary`；不写 AlertEvent、不改 Scope、
  不启用 Runtime。
- Alert Runtime activation：仅在 migration/canary 前置已满足且再次明确授权后执行
  `install-local-services.sh --confirm-alert-runtime`；必须读回独立 activation marker 与健康状态。

三个 Gate 不能相互授权，失败或重试也需要新的明确请求。代码、fixture、render-only 或 mock 通过只证明
实现，不证明 production migration、真实通知通道或 Alert Runtime 已启用。

## OpenSpec

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
```

已归档 change 只保留历史意图；当前行为合同只看 `openspec/specs/`。

## Data Foundation 只读验证

```bash
uv run --project services/quant-api guiyi data update --universe active --through 2026-08-11
uv run --project services/quant-api guiyi data refresh --symbol jm --since 2024-03-01 --through 2024-03-31
uv run --project services/quant-api guiyi data audit --symbol jm --through 2026-08-11
uv run --project services/quant-api guiyi data audit --universe active --through 2026-08-11
```

无 `--apply` 的 update/refresh 只规划，audit 始终只读。任何真实 RQData、PostgreSQL 或 Canonical 写入
仍需执行前范围明确的单次意图。

## Market Runtime V1

### 无副作用验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_operational_universe.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_websocket.py

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
```

`--render-only` 不安装、重载或启用 Runtime。禁止用 fixture、手工 after-market 或旧状态冒充自然触发。

### 最终隔离 Runtime 验收

部署属于受控外部操作。取得本次明确意图后，将 Runtime worktree 固定到已验证 commit，构建 Web，安装
API 依赖并仅执行一次对应 Runtime switch。部署后至少读回：

- Runtime clean/detached 且等于批准 commit；
- API/Web/Live/after-market 的 launchd 根只指向该 worktree；
- `operational_products.txt` 与 active 60 完全一致，Live subscription/heartbeat 与 after-market status
  均报告同一 60 品种集合；
- API、Web、Runtime health 和实际 Market 业务字段可读；
- Historical/Live seam 保持分离，Live 不写 Parquet，`auto_order=false`。

`--confirm-market-runtime` 才会启用或重载 Market Runtime 并更新 marker。完成或失败后，本次执行意图即
消耗；重试必须取得新的明确请求。

### 18:05 自然盘后验收

不得手工执行 `guiyi data after-market` 代替 launchd 证据。自然触发后只读核对：

- launchd `runs` 增加且 `.run/after-market-status.json` 的 products 精确为 operational 60；
- `status=passed`、`attempts=1|2`，或在真实非交易日精确为 `NON_TRADING_DAY`；
- 当天 TradingSession / MainContractMap 已推进，正式 rank1 与同日 Live snapshot 一致；
- Canonical edge 与 Web Historical/Live seam 随正式发布更新，Live 从未写入 Parquet；
- intended same-day Live 清理完成，随后 Runtime health 不再因旧 Session 报 `UNKNOWN=56`。

代码、fixture、render-only 或手工命令只能证明实现，不得写成自然盘后通过。

## 最终检查

```bash
git diff --check
git status --short
```
