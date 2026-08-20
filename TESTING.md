# 测试与验证入口

更新时间：2026-08-20

所有写入测试必须使用 `tmp_path`、临时 Canonical root 和隔离数据库；测试 URL 不得指向 Runtime 或
生产数据库。真实数据、Runtime switch 和通知不属于测试命令的隐含权限。

首次检出或锁文件变化后先联网完成一次依赖同步；后续 `--offline` 命令只依赖该
venv 与同一 cache：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

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
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

需要运行 Alembic 或 PostgreSQL 约束测试时，必须显式提供一个库名包含 `test` 或 `isolated`、且与
Runtime `DATABASE_URL` 物理身份不同的 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`。测试 guard 会以
数据库名和 OID 双重拒绝 production/Runtime 库；禁止为了让测试运行而放宽该校验。

## 主力照妖镜 Observation V0

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/main-force-mirror.spec.mjs
pnpm --dir apps/quant-web build
```

这些命令验证 frozen designed-v0、Python/Web deterministic parity、“小心”的 HHV5/BARSLAST
rising-edge 边界，以及同一副图内默认 MACD 的 Tab 切换。它们不授权公式调整、Alert/Runtime 接入、
Canonical/DB 写入、通知或订单行为。

## 主力照妖镜·期货 V1

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

pnpm --dir apps/quant-web test

pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs \
  e2e/main-force-mirror-futures.spec.mjs \
  e2e/market-runtime.spec.mjs \
  e2e/market-research.spec.mjs \
  e2e/alert-v1.spec.mjs

pnpm --dir apps/quant-web build
```

这些命令验证 V0 runtime 精确源码 hash、独立 `.pyi` 静态 facade、V1 exact identity、60m physical-contract segment reset、readiness、五状态、
双向警戒、conflict/latch/re-arm、Python/Web 单一 golden parity、动态 marker/hover、合法 5m/15m Alert
在 MACD/V0 切换中的保留行为与 historical-only Shadow
CLI，包括 `(long+short)*1000/caution_ready` 的 6 位 half-away 事件率、conflict 不计事件、零分母 JSON
`null`，以及不可执行的 `("jm", "ag", "cu", "m", "sc")` 代表参数 tuple。它们不执行真实 Shadow 代表
矩阵。真实 A→B resolved segments 还会验证 Pane 只取最右侧当前 block、B 第 10/21/31 根 readiness、
两端 Hover 的 B 合约身份与 marker 不继承。Futures V1 仅支持 60m，persistent Alert markers 仅支持 actual-dominant 5m/15m，因此两者按各自合法
identity 独立验证，不用生产测试注入伪造重叠状态；这些测试也不授权 Canonical/DB 写入、
Alert/notification、Runtime、订单、release 或策略晋升。

## Execution Review V1

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_execution_review_contracts.py \
  services/quant-api/tests/test_execution_review_pnl.py \
  services/quant-api/tests/test_execution_review_models.py \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_execution_review_api.py \
  services/quant-api/tests/test_execution_review_reconstruction.py \
  services/quant-api/tests/test_execution_review_reconciler.py \
  services/quant-api/tests/alembic/test_execution_review_v1_migration.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/execution-review.spec.mjs
pnpm --dir apps/quant-web build
```

这些测试覆盖 trusted-partial reference/evidence 一一对应、缺失 multiplier 的 nullable RMB 估算、
Episode snapshot、四状态工作流、reconstruction、roll estimate、stats 和 Web unavailable 展示。测试
不执行 production migration、release、Runtime switch、roll marker、Scope/notification、Canonical 或订单行为。

## SuBing Factor / Calibration / Signal Observation V1

### 无副作用实现与回归验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
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

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli services/quant-api/app/alerts \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

这些命令覆盖 strict slope-only Calibration loader、exact research-only Lifecycle Policy、causal
ConfirmedPivot/Breakout/Retest 和 Lifecycle reducer、MarketDataService-only research/CLI、scoped MACD
equivalence、Signal pure core、`SubingReadService` reciprocal/lifecycle orchestration、API、Web unit/E2E、
current-rank1 segment、Historical/completed Live seam 和有效当前合约视图。测试只使用 fixture、mock、
临时目录或隔离数据库，不运行 provider、Canonical/DB/Redis 写入、Runtime switch 或通知。

`guiyi research subing-calibration` 本身是只读 Historical research：只通过 `MarketDataService` 取数，
输出 stdout JSON，不直接读 provider，也不写 DB、Canonical 或 Redis，不自动 promotion。Discovery/
Validation stdout 不能作为正式 artifact；测试只验证 CLI 合同，不运行真实研究窗口。当前 accepted
intraday Calibration 仅由 Git-tracked slope-only artifact 提供，zero-distance 不参与 executable Signal。

`guiyi research subing-lifecycle` 同样只读 Historical Canonical：它通过 `MarketDataService`
按 exact trading-day Session window 与 current-rank1 segment 独立复算 research-only lifecycle
Shadow，只输出 stdout JSON。测试只验证命令、分段因果与报告合同，不运行真实当前市场观察，
也不表示正式回测、策略有效或可晋升。

`guiyi research candidate-validation` 只接受 Git-tracked exact Candidate/Protocol，通过既有
`SubingLifecycleResearchService` 投影 frozen retrospective、10 个 12m+3m rolling folds 和从
`2026-08-20` 开始的 prospective OOS。命令只输出 stdout JSON，保持 `research_only=true` 与
`readonly=true`；测试使用 fake source 验证合同和时间边界，不运行真实 Candidate report，也不授权
Candidate 晋升、Alert/Runtime 接入、DB/Canonical/Redis 写入、通知或订单。

## Alert V2

### 无副作用单元、集成与 render-only 验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_current_trading_day.py \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_clawbot_owner.py \
  services/quant-api/tests/test_alert_clawbot.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/alembic/test_alert_v2_migration.py \
  services/quant-api/tests/data_foundation/test_aggregation.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_market_phase.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_market_runtime_launchd.py

node --test tests/engineering/openclaw_weixin_single_shot.test.mjs

pnpm --dir apps/quant-web test
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
```

这些命令只使用隔离数据库、mock sender、fake exact-version plugin tree、tmp_path/fake process 或 render-only，
不启动真实 AlertRuntime，不写真实 owner，不执行真实 Clawbot preflight/canary/send，也不修改或监督
OpenClaw。它们不授权 Runtime switch/release、production migration 或 SuBing Scope write/activation。
当前 production exact-tag 已运行 `clawbot-openclaw-weixin`；本节测试不会改变该事实，也不授权任何后续
真实 Gate。`alembic upgrade/current`、`runtime clawbot-owner-bootstrap
--confirm-write-owner`、`runtime clawbot-preflight`、`runtime alert-canary`、`--confirm-alert-runtime` 与真实
Scope PUT 禁止作为本节验证命令。测试路由 Scope PUT 只证明 API 合同，不授权生产 DB mutation。

### 独立受控外部 Gate

- production PostgreSQL migration：仅在明确授权的短维护窗口升级到目标 revision；读回两张
  Alert Application Domain 表与八表 Market Catalog 未变。
- release/tag 与 Alert Runtime promotion/switch：分别取得明确授权；不得让 Runtime 与其所需
  Alert schema 版本不一致。
- SuBing Scope write/activation：对精确 `subing_entry_signal_v1 × product` 另行授权；seed
  必须保持空集，不从 HTDY Scope 或 `operational_products.txt` 自动扩张。
- Clawbot owner bootstrap/write、zero-send preflight、真实 canary/send：每次执行仍需自身精确 Gate；
  已完成的 G2～G8、测试或历史批准不授权重试、owner/Scope/transport 变更、rollback 或 G9 cleanup。
  这些命令不写 AlertEvent、不改 Scope、不修改 OpenClaw、不自动启用或切换 Runtime。

这些 Gate 不能相互授权，失败或重试也需要新的明确请求。代码、fixture、render-only 或
mock 通过只证明实现，不证明任何生产 Gate 已执行。

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

- Runtime clean/detached 且等于批准 commit 或 release tag 的 peeled commit；
- API/Web/Live/after-market/Alert 的 launchd 根只指向该 worktree，已加载 commit 与 checkout 一致；
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
