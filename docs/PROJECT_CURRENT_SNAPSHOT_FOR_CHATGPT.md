# 归一量化项目当前状态快照

## 1. 本次快照信息

- 生成日期：2026-06-28 20:40:19 CST
- 当前 git 分支：`feature/su-bing-skill`
- 最近 10 个 commit：
  - `c53e1b17 策略优化`
  - `a44432b4 提交`
  - `dbbb3efd 提交`
  - `420c4091 提交数据`
  - `2247e780 bug 修改`
  - `b8f3c6dc bug 修复`
  - `fff3734e bug 修复`
  - `fa41ad97 修改 bug`
  - `aa555e55 web 报告页面增加`
  - `b2e6ff21 问题修复`
- 当前工作区是否干净：否。
- 当前未提交文件列表：

```text
 M .agents/skills/su-bing-strategy/references/SU_BING_RULEBOOK.md
 M README.md
 M docs/PROJECT_INVENTORY.md
 M docs/V1_FINAL_ACCEPTANCE.md
 M docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md
 D services/quant-api/tests/test_backtest_api.py
 D services/quant-api/tests/test_backtest_consistency.py
 D services/quant-api/tests/test_backtest_engine.py
 D services/quant-api/tests/test_jm_price_tick_backfill.py
 D services/quant-api/tests/test_rqdata_sample_acceptance.py
 D services/quant-api/tests/test_su_bing_ema21.py
 D services/quant-api/tests/test_tqsdk_ingest.py
 D services/quant-api/tests/test_trader_future_importer.py
 D services/quant-api/tests/test_v1_refactor_acceptance.py
 D services/quant-api/tests/test_vnpy_rqdata_demo_cli.py
 M tasks/current.md
```

- 当前是否存在明显未完成修改：是。工作区已有多份文档和苏冰 rulebook 修改，且多份后端测试文件处于删除状态；这些不是本次快照任务产生的改动，需要人工确认是否保留。
- 本次 Codex 是否修改了业务代码：否。
- 敏感配置检查：仓库存在 `.env`，且 `docker-compose.yml` / `scripts/dev-up.sh` 涉及本地开发配置；发现疑似敏感配置位置，需要人工检查。本文不复制任何具体凭据值。

## 2. 项目一句话定位

规划定位：归一量化是本地运行的国内期货量化研究、回测、复盘、信号扫描和后期人工确认交易辅助系统，V1 只做 Web 研究闭环，不做全自动实盘。

当前代码实际做到的程度：仓库已经具备 Vue Web、FastAPI、PostgreSQL ORM、Alembic、Redis/RQ、RQData/Local Parquet 数据读取、DuckDB K线查询、vn.py 回测适配、回测报告、信号扫描和复盘等主要模块，但部分页面仍是壳子或半成品。

当前最核心闭环：数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号 -> 复盘的工程链路已经大体打通；但报告成本/回撤口径、浏览器级 smoke、RQ worker 非 inline 联调、测试文件删除状态仍需要优先收敛。

## 3. 当前目录结构总览

```text
guiyi-quant-workstation/
├── AGENTS.md
├── README.md
├── CLAUDE.md
├── docker-compose.yml
├── apps/
│   └── quant-web/
├── services/
│   └── quant-api/
├── packages/
│   └── quant-core/
├── docs/
├── scripts/
├── experiments/
├── strategies/
├── tasks/
├── prompts/
├── data/
├── backtests/
├── screenshots/
├── .agents/
├── .cursor/
└── .codex/
```

| 目录 | 用途 | 当前是否活跃 | 重要文件 | 废弃 / 实验 / 遗留内容 |
|---|---|---|---|---|
| `apps/quant-web/` | Vue 3 Web 工作台 | 活跃 | `src/app/router.ts`、`src/pages/*`、`src/api/*`、`package.json` | `dist/` 存在构建产物；Dashboard、Strategy、Settings 有明显原型状态 |
| `services/quant-api/` | FastAPI 后端、任务、ORM、回测和数据读取 | 活跃 | `app/main.py`、`app/api/*`、`app/models/*`、`app/backtest/*`、`app/vnpy_integration/*` | `app/backtest/engine.py` 自研引擎仍存在，当前 vn.py 链路也存在；测试目录有多份删除状态 |
| `packages/quant-core/` | 策略共享包和 vn.py `CtaTemplate` 草稿 | 活跃 | `guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/*`、`su_bing_ema21/*` | 苏冰 EMA21 是草稿/候选，不等同当前 V1-B 正式策略 |
| `docs/` | 架构、路线、验收、ChatGPT 上下文 | 活跃 | `ROADMAP.md`、`PROJECT_INVENTORY.md`、`PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`、`V1B1_REQUIREMENTS.md`、`V1B1_ACCEPTANCE_CHECKLIST.md` | 当前外部审查入口已收敛到本文和 V1-B.1 需求/验收文档 |
| `scripts/` | 本地启动、RQData/TqSdk 同步、审计、backfill | 活跃 | `dev-up.sh`、`dev-down.sh`、`rqdata_v1b_jm_asset.py`、`rqdata_*`、`tqsdk_*` | TqSdk 脚本属于 validation/V2 候选，不是 V1 主链路 |
| `experiments/` | RQData 和 vn.py demo / 样本验收 | 实验性活跃 | `vnpy_rqdata_demo/run_demo.py`、`rqdata_sample_acceptance/run_sample.py` | 不应被当作正式产品入口 |
| `strategies/` | 策略说明文档 | 低活跃/说明性 | `su_bing_ema21/README.md`、`ma_breakout/README.md`、`n_structure/README.md` | 更像策略说明目录，正式代码在 `packages/quant-core/` 和 `services/quant-api/app/strategy/` |
| `data/` | 本地数据湖、manifest、审计报告 | 活跃但不应随意修改 | `data/manifests/*`、`data/reports/*`、`data/parquet/` | 含 RQData、TqSdk validation、legacy 相关数据；正式回测口径需隔离 |
| `backtests/` | 回测报告和结果导出 | 活跃 | `backtests/reports/report_5_jm_15m_trade_review.*` | 本地结果文件不等同数据库当前状态 |
| `.agents/skills/` | 项目 Agent 技能 | 活跃 | `su-bing-strategy/SKILL.md`、`docs-product-manager/SKILL.md`、`quant-*` | 苏冰 skill 有本次未提交修改 |
| `tasks/` | 当前任务和任务流转 | 活跃 | `tasks/current.md` | 当前文件也处于未提交修改状态 |
| `prompts/` | AI 协作提示模板 | 辅助 | `code-review.md`、`workbuddy-bugfix.md` | 无明显问题 |

根目录未发现 `package.json`、`pyproject.toml`、`Makefile`；Python 项目配置在 `services/quant-api/pyproject.toml`，前端配置在 `apps/quant-web/package.json`。根目录未发现 `alembic/`，Alembic 位于 `services/quant-api/alembic/`。

## 4. 技术栈现状

### 4.1 前端

- 是否存在 Web 前端：存在，路径 `apps/quant-web/`。
- 前端框架：Vue 3 + Vite + TypeScript，见 `apps/quant-web/package.json`。
- UI 组件库：Naive UI。
- 图表库：`lightweight-charts`、`echarts`、`vue-echarts`。
- K线图实现方式：K线工作台使用 TradingView Lightweight Charts，核心页面为 `apps/quant-web/src/pages/market/index.vue`，指标辅助在 `apps/quant-web/src/utils/indicators.ts`。
- 路由结构：`apps/quant-web/src/app/router.ts` 定义 `/dashboard`、`/data`、`/market`、`/strategy`、`/backtest`、`/backtest/batch`、`/signal`、`/review`、`/settings`。
- API 调用位置：`apps/quant-web/src/api/data.ts`、`market.ts`、`strategy.ts`、`backtestApi.ts`、`signal.ts`、`review.ts`。
- 前端启动命令：`cd apps/quant-web && pnpm dev --host 127.0.0.1 --port 5173`，也可用 `./scripts/dev-up.sh`。
- 前端构建/测试命令：`cd apps/quant-web && pnpm build`；指标测试为 `pnpm test:indicators`。
- 当前主要页面：Dashboard、数据中心、行情看板/K线工作台、策略管理、回测中心、批量回测、信号监控、复盘分析、系统设置。

### 4.2 后端

- 是否存在 FastAPI 或其他后端：存在 FastAPI，路径 `services/quant-api/`。
- 后端入口文件：`services/quant-api/app/main.py`；根入口 `services/quant-api/main.py` 只是简单 CLI hello。
- API 路由位置：`services/quant-api/app/api/data_center.py`、`market.py`、`backtests.py`、`signals.py`、`reviews.py`。
- WebSocket 路由位置：`services/quant-api/app/websocket/backtests.py`、`signals.py`。
- 服务层位置：`services/quant-api/app/services/*`，包括 `market_data_reader.py`、`market_workbench.py`、`batch_backtest.py`、`signal_scanner.py`、`review_center.py`。
- ORM / 数据库模型位置：`services/quant-api/app/models/data_center.py`、`backtest.py`、`signal.py`、`review.py`。
- 配置读取方式：`services/quant-api/app/core/env.py`、`app/db/url.py`、`.env` / 环境变量；`.env` 需要人工检查，不复制具体值。
- 后端启动命令：`cd services/quant-api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`。
- 后端测试命令：`uv run --project services/quant-api pytest -q`；静态检查为 `uv run --project services/quant-api ruff check .`。

### 4.3 数据库与数据仓

- PostgreSQL：使用，`docker-compose.yml` 定义 PostgreSQL 服务；ORM 位于 `services/quant-api/app/models/`。
- DuckDB：使用，`services/quant-api/app/services/market_data_reader.py` 通过 DuckDB 读取 Parquet。
- Parquet：使用，标准行情数据在 `data/parquet/`；RQData/TqSdk/legacy 写入逻辑分布在 `services/quant-api/app/services/rqdata_ingest/`、`tqsdk_ingest/`、`trader_future_importer.py` 和 `scripts/`。
- Alembic migration 状态：迁移文件存在到 `services/quant-api/alembic/versions/20260628_0012_backtest_result_v1_summary_trades.py`。本次未连接数据库执行 `alembic current`，实际 DB head 为未知 / 待确认。
- 核心表：数据中心表、RQData 结构化表、watchlist、backtest、signal、review 表均存在。
- 行情数据保存位置：大体量 K线在 Parquet；元数据在 PostgreSQL 的 `market_data_files`、`data_quality_reports` 等表。
- 回测报告保存位置：PostgreSQL `backtest_tasks`、`backtest_reports`、`backtest_trades`、`backtest_orders`、`backtest_equity_curve`、`backtest_drawdown_curve`；另有本地 `backtests/reports/` 导出文件。

### 4.4 任务队列 / 定时任务

- Redis / RQ：使用，依赖在 `services/quant-api/pyproject.toml`，队列封装在 `services/quant-api/app/queue.py`，worker 入口在 `services/quant-api/app/worker.py`。
- Celery：未发现。
- APScheduler：依赖存在，但当前是否有正式调度任务为未知 / 待确认。
- 回测任务是否异步：是，`services/quant-api/app/api/backtests.py` 创建任务后进入 RQ；同时存在 `/api/backtests/run` 同步/legacy 风格入口。
- 数据下载任务是否异步：有 `data_download_tasks` 模型和脚本，但当前 Web/API 是否完整异步编排为未知 / 待确认。
- 信号扫描是否异步：是，`services/quant-api/app/api/signals.py` 支持 RQ；`/api/signals/v1b/jm/scan` 还支持 `run_inline`。
- worker 启动命令：`cd services/quant-api && uv run python -m app.worker backtests`、`cd services/quant-api && uv run python -m app.worker signals`；`./scripts/dev-up.sh` 会启动两个 worker。

### 4.5 回测引擎

- 当前到底使用什么：两者都有。`services/quant-api/app/backtest/engine.py` 保留自研 bar 级引擎；当前 V1-B/vn.py 路线使用 `services/quant-api/app/vnpy_integration/backtest_runner.py` 和 `services/quant-api/app/backtest/runner.py`。
- 回测 runner 位置：`services/quant-api/app/backtest/runner.py`、`services/quant-api/app/vnpy_integration/backtest_runner.py`。
- 回测任务流程：API 创建 `BacktestTask` -> RQ worker 执行 `app/tasks/backtests.py` -> `BacktestService` / vn.py runner 读取标准 bars -> `result_converter` 转换 -> `backtest_reports`、trades、orders、equity/drawdown 入库。
- 回测结果如何入库：`services/quant-api/app/services/batch_backtest.py` 和 `app/backtest/service.py` 负责持久化报告和明细。
- 是否存在 prepared-only / mock / stub 逻辑：存在 `prepared_only` 配置校验路径；`/api/dashboard/summary` 明确返回 mock 状态；早期 smoke report 和自研引擎仍存在。
- 是否真实调用 vn.py BacktestingEngine：代码中存在真实调用路径，见 `services/quant-api/app/vnpy_integration/backtest_runner.py`；实际本地 DB 最新执行状态未在本次连接数据库验证。
- 严谨性限制：`backtest_runner.py` 检查标准 bars 的 `data_role=primary`、`quality_status=passed`；`contract_resolver.py` 解析 `price_tick`、手续费、保证金；`report_metrics.py` 汇总成本、回撤、连亏等。但当前文档和任务仍提示报告成本/年化/回撤百分比口径需要继续加固。

### 4.6 数据源

| 数据源 | 当前角色 | 依据 |
|---|---|---|
| RQData / 米筐 | V1 主数据源 | `AGENTS.md`、`README.md`、`services/quant-api/app/data_sources/rqdata_provider.py`、`scripts/rqdata_*` |
| Local Parquet | V1 本地正式数据湖 | `services/quant-api/app/data_sources/local_parquet_provider.py`、`market_data_reader.py` |
| DuckDB | 本地研究查询和 K线读取 | `services/quant-api/app/services/market_data_reader.py` |
| TqSdk | validation / V2 候选 | `services/quant-api/app/data_sources/roles.py`、`scripts/tqsdk_*`、`services/quant-api/app/services/tqsdk_ingest/*` |
| trader_future_data / trader_trainer | legacy_reference | `services/quant-api/app/data_sources/roles.py`、`trader_future_importer.py` |
| TuShare | 后期辅助候选 | `services/quant-api/pyproject.toml` 仍保留依赖，README 明确不是 V1 主链路 |

- 是否有数据下载脚本：有，主要是 `scripts/rqdata_*`、`scripts/tqsdk_*`。
- 是否有数据质量检查脚本：有，`scripts/rqdata_audit.py`、`rqdata_coverage_audit.py`、`rqdata_field_audit.py`、`tqsdk_coverage_audit.py`、`tqsdk_data_audit.py`。
- 是否存在数据口径冲突：存在风险。仓库同时保留 RQData primary、TqSdk validation、trader legacy、实验样本和历史文档，需要持续防止 validation / legacy 混入正式回测。

## 5. 当前已实现功能清单

### 5.1 数据中心

- 合约管理：ORM `Contract` 在 `services/quant-api/app/models/data_center.py`，API `GET /api/v1/data/contracts` 在 `app/api/data_center.py`，Web `apps/quant-web/src/pages/data/index.vue`。
- 品种池管理：`Instrument`、`Watchlist`、`WatchlistItem` 存在；watchlist API 在 `app/api/backtests.py`。
- 数据下载：`DataDownloadTask` 模型存在，RQData/TqSdk 同步脚本存在；Web 是否能直接发起完整下载任务为未知 / 待确认。
- 数据导入：RQData ingest 在 `services/quant-api/app/services/rqdata_ingest/`，TqSdk ingest 在 `tqsdk_ingest/`，legacy importer 在 `trader_future_importer.py`。
- 数据质量检查：`DataQualityReport` 模型和 `/api/v1/data/quality-reports` 存在；脚本层也有审计。
- K线查询 API：`/api/v1/market/workbench/coverage`、`/api/v1/market/bars`，兼容接口 `/api/symbols`、`/api/klines`。
- 数据覆盖范围：文档记录 JM 1d/15m/5m/1m primary 数据已存在；本次未查询数据库，当前实际 DB 行数未知 / 待确认。
- 已知数据缺口：多数据源共存，正式回测需继续强制 `primary/passed`；交易参数、手续费、保证金口径仍需对报告结果做一致性验收。

### 5.2 K线工作台

- K线页面路径：`apps/quant-web/src/pages/market/index.vue`。
- K线 API：`services/quant-api/app/api/market.py`。
- 支持周期：由后端 coverage 和前端选择项决定；文档和代码重点出现 1d、15m、5m、1m。
- 是否支持买卖点标记：回测报告交易明细可转换为 marker，相关逻辑在 `apps/quant-web/src/api/market.ts` 和 Market 页面。
- 是否支持 MACD / EMA / 成交量：指标工具在 `apps/quant-web/src/utils/indicators.ts`，页面支持程度需浏览器 smoke 复核。
- 是否支持十字星联动：未知 / 待确认。
- 当前已知显示问题：文档提到浏览器截图级 UI smoke 未完成，交易明细/K线 marker 需要继续验收。

### 5.3 策略中心

- 策略目录：`packages/quant-core/guiyi_quant/strategies/`、`services/quant-api/app/strategy/`、根目录 `strategies/`。
- 当前已有策略列表：
  - `jm_v1b_daily_direction_fast_entry`：当前 V1-B 专用策略，位于 `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/`。
  - `su_bing_ema21`：苏冰 EMA21 草稿/候选，位于 `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/` 和 `services/quant-api/app/strategy/su_bing_ema21.py`。
  - `ma_breakout`、`n_structure`：根目录 `strategies/` 下主要是 README 说明。
- 是否有策略版本记录：回测报告模型有 `strategy_code`、`strategy_version` 字段；正式策略版本治理仍偏工程化，Web 策略中心不完整。
- 是否有参数 schema：`packages/quant-core/.../config_schema.py` 和 `default_params.json` 存在。
- 是否有苏冰策略 skill / rulebook / spec：存在 `.agents/skills/su-bing-strategy/` 和 `docs/strategy_knowledge/su_bing/`。
- 策略是否已经和回测联动：JM V1-B 已联动；苏冰 EMA21 草稿有测试和自研/候选路径，但不应当作当前正式 V1-B 报告策略。

### 5.4 回测中心

- 回测任务创建 API：`POST /api/backtests/tasks`、`POST /api/backtests/v1b/jm/{entry_interval}/tasks`、`POST /api/backtests/run`、`POST /api/backtests/run-batch`。
- 回测任务列表 API：`GET /api/backtests/tasks`、`GET /api/backtests/tasks/{task_ref}`。
- 回测执行流程：`app/api/backtests.py` -> `app/tasks/backtests.py` -> `app/backtest/service.py` / `app/backtest/runner.py` -> vn.py integration。
- 回测报告入库流程：`BacktestReportModel`、`BacktestTradeModel`、`BacktestOrderModel`、equity/drawdown 表；转换代码在 `app/vnpy_integration/result_converter.py`。
- 回测报告详情 API：`GET /api/backtests/reports`、`GET /api/backtests/reports/{report_id}`。
- 交易明细 API：`GET /api/backtests/reports/{report_id}/trades`、`/trades/export`、`/orders`。
- 资金曲线 / 回撤曲线 API：`GET /api/backtests/reports/{report_id}/equity-curve`、`/drawdown-curve`。
- 最近一次可用报告情况：仓库文档记录 report 3/4、后续 report 5/6 等历史；本次未连接 DB，实际当前可用报告 ID 未确认。
- 是否支持 5m / 15m / 日线联动：JM V1-B 任务 builder 和策略支持 15m/5m 入场、日线方向过滤，见 `app/backtest/v1b_jm_tasks.py` 和 quant-core 策略。

### 5.5 回测报告与复盘

- 报告页面路径：`apps/quant-web/src/pages/backtest/index.vue`。
- 复盘页面路径：`apps/quant-web/src/pages/review/index.vue`。
- 交易明细展示方式：Backtest 页面调用 `apps/quant-web/src/api/backtestApi.ts` 的 report trades API，支持分页/导出。
- 点击查看报告是否会刷新：前端代码存在 report_id 查询与加载逻辑，但具体 UX 需浏览器 smoke。
- K线是否能定位到交易：Market/Backtest API 有根据 report/trades 组装 K线查询和 marker 的逻辑；需 UI smoke 验证。
- 是否支持单笔交易复盘：支持 `POST /api/reviews/from-backtest-trade/{trade_id}`。
- 是否有复盘标签：`review_tags` 模型和 `GET /api/reviews/tags` 存在；苏冰 review tags 文档也存在。
- 当前已知 UX 问题：浏览器截图级验收未完成；Dashboard 和 Strategy/Settings 仍有原型状态。

### 5.6 信号扫描

- 是否已有信号扫描模块：有。
- 信号生成逻辑位置：通用服务 `services/quant-api/app/services/signal_scanner.py`，JM V1-B 专用逻辑 `services/quant-api/app/signal/jm_v1b.py`。
- 信号表 / API：`signal_scan_tasks`、`strategy_signals`、`signal_notifications`；API 在 `services/quant-api/app/api/signals.py`。
- Web 展示位置：`apps/quant-web/src/pages/signal/index.vue`。
- 是否接企业微信 / 邮件 / 站内通知：当前看到 WebSocket/站内状态和通知表；企业微信/邮件未见正式实现，未知 / 待确认。
- 是否只是提醒，不下单：是。未发现 V1 信号路径中自动下单逻辑；项目规则也禁止 V1 自动实盘。

### 5.7 风控

- 是否有风控配置：回测配置含 `max_margin_usage_pct`、`slippage_ticks`、手续费/保证金参数；策略参数 schema 存在。
- 是否有单笔风险：信号模型有 `risk_amount`、`margin_required`、`account_equity`；回测 trade 有 `margin_required`、`commission`、`slippage`。
- 是否有最大回撤：`report_metrics.py`、`drawdown_curve_generator.py`、`BacktestReportModel` 均有相关字段。
- 是否有连续亏损统计：`BacktestReportModel.max_consecutive_losses` 和 `report_metrics.py` 有字段/计算入口。
- 是否有保证金估算：`contract_resolver.py`、`backtest/engine.py`、`backtest_trades.margin_required` 存在。
- 是否用于回测：是，至少在自研引擎和报告汇总层使用；vn.py 结果 enrichment 也包含真实合约成本字段。
- 是否用于实盘：否。V1 不做实盘，不下单；V2 也必须人工确认和风控拦截后再评估。

## 6. 当前 Web 页面清单

| 页面 | 路径 | 对应路由 | 对应 API | 当前状态 | 已知问题 |
|---|---|---|---|---|---|
| Dashboard | `apps/quant-web/src/pages/dashboard/index.vue` | `/dashboard` | `/api/dashboard/summary` | 存在 | 后端 summary 明确为 mock 状态 |
| 数据中心 | `apps/quant-web/src/pages/data/index.vue` | `/data` | `/api/v1/data/*` | 存在且接 API | 下载任务是否完整可操作未知 |
| K线工作台 | `apps/quant-web/src/pages/market/index.vue` | `/market` | `/api/v1/market/*`、兼容 `/api/klines` | 存在且接 API | 浏览器 smoke、十字星联动待确认 |
| 策略中心 | `apps/quant-web/src/pages/strategy/index.vue` | `/strategy` | 前端请求 `/api/strategies*` | 页面存在 | 后端未发现 `/api/strategies` 路由，疑似壳子/接口不一致 |
| 回测任务/报告 | `apps/quant-web/src/pages/backtest/index.vue` | `/backtest` | `/api/backtests/*` | 存在且接 API | 报告口径和 UI smoke 待验收 |
| 批量回测 | `apps/quant-web/src/pages/backtest/batch.vue` | `/backtest/batch` | `/api/backtests/run-batch`、tasks/reports | 存在 | 与 V1-B 固定任务边界需说明 |
| 交易明细 | `apps/quant-web/src/pages/backtest/index.vue` | `/backtest?report_id=...` | `/api/backtests/reports/{id}/trades` | 嵌在回测页 | 表格空间和筛选 UX 待验收 |
| 复盘中心 | `apps/quant-web/src/pages/review/index.vue` | `/review` | `/api/reviews/*` | 存在且接 API | K线定位和 marker 需 smoke |
| 信号扫描 | `apps/quant-web/src/pages/signal/index.vue` | `/signal` | `/api/signals/*` | 存在且接 API | 非 inline worker、真实触发信号样本待确认 |
| 系统设置 | `apps/quant-web/src/pages/settings/index.vue` | `/settings` | 未见专用 settings 后端路由 | 页面存在 | 可能未持久化，属于壳子 |

## 7. 当前 API 清单

| 方法 | 路径 | 文件位置 | 功能 | 当前状态 |
|---|---|---|---|---|
| GET | `/health`、`/api/health` | `services/quant-api/app/main.py` | 健康检查 | 可用 |
| GET | `/api/dashboard/summary` | `services/quant-api/app/main.py` | 仪表盘摘要 | mock |
| GET | `/api/v1/data/sources` | `app/api/data_center.py` | 数据源列表 | 存在 |
| GET | `/api/v1/data/exchanges` | `app/api/data_center.py` | 交易所 | 存在 |
| GET | `/api/v1/data/instruments` | `app/api/data_center.py` | 品种 | 存在 |
| GET | `/api/v1/data/contracts` | `app/api/data_center.py` | 合约 | 存在 |
| GET | `/api/v1/data/download-tasks` | `app/api/data_center.py` | 下载任务 | 存在 |
| GET | `/api/v1/data/quality-reports` | `app/api/data_center.py` | 数据质量 | 存在 |
| GET | `/api/v1/data/coverage` | `app/api/data_center.py` | 数据覆盖 | 存在 |
| GET | `/api/v1/market/workbench/coverage` | `app/api/market.py` | K线工作台覆盖 | 存在 |
| GET | `/api/v1/market/bars` | `app/api/market.py` | K线 bars | 存在 |
| GET | `/api/symbols`、`/api/klines` | `app/api/data_center.py` compat | 旧前端兼容 | 存在 |
| POST | `/api/backtests/tasks` | `app/api/backtests.py` | 创建回测任务 | 存在 |
| POST | `/api/backtests/v1b/jm/{entry_interval}/tasks` | `app/api/backtests.py` | JM V1-B 固定任务 | 存在 |
| POST | `/api/backtests/run` | `app/api/backtests.py` | 同步/legacy 回测入口 | 存在 |
| POST | `/api/backtests/run-batch` | `app/api/backtests.py` | 批量回测 | 存在 |
| GET | `/api/backtests/tasks` | `app/api/backtests.py` | 任务列表 | 存在 |
| GET | `/api/backtests/tasks/{task_ref}` | `app/api/backtests.py` | 任务详情 | 存在 |
| GET | `/api/backtests/tasks/{task_no}/reports` | `app/api/backtests.py` | 任务报告 | 存在 |
| GET | `/api/backtests/reports` | `app/api/backtests.py` | 报告列表 | 存在 |
| GET | `/api/backtests/reports/{report_id}` | `app/api/backtests.py` | 报告详情 | 存在 |
| GET | `/api/backtests/reports/{report_id}/trades` | `app/api/backtests.py` | 交易明细 | 存在 |
| GET | `/api/backtests/reports/{report_id}/trades/export` | `app/api/backtests.py` | 交易导出 | 存在 |
| GET | `/api/backtests/reports/{report_id}/orders` | `app/api/backtests.py` | 委托明细 | 存在 |
| GET | `/api/backtests/reports/{report_id}/equity-curve` | `app/api/backtests.py` | 资金曲线 | 存在 |
| GET | `/api/backtests/reports/{report_id}/drawdown-curve` | `app/api/backtests.py` | 回撤曲线 | 存在 |
| GET | `/api/watchlists` | `app/api/backtests.py` | 观察池列表 | 存在 |
| GET | `/api/watchlists/{code}/items` | `app/api/backtests.py` | 观察池品种 | 存在 |
| POST | `/api/signals/scan` | `app/api/signals.py` | 信号扫描任务 | 存在 |
| POST | `/api/signals/v1b/jm/scan` | `app/api/signals.py` | JM V1-B 扫描 | 存在 |
| GET | `/api/signals/latest` | `app/api/signals.py` | 最新信号 | 存在 |
| GET | `/api/signals/tasks/{task_no}` | `app/api/signals.py` | 扫描任务详情 | 存在 |
| GET | `/api/signals/tasks/{task_no}/signals` | `app/api/signals.py` | 任务信号 | 存在 |
| POST | `/api/signals/{signal_id}/ack` | `app/api/signals.py` | 确认信号 | 存在 |
| PATCH | `/api/signals/{signal_id}/status` | `app/api/signals.py` | 更新信号状态 | 存在 |
| GET | `/api/reviews/sources/backtest-trades` | `app/api/reviews.py` | 可复盘回测交易 | 存在 |
| GET | `/api/reviews/sources/paper-trades` | `app/api/reviews.py` | 纸面交易来源 | 存在 |
| POST | `/api/reviews/from-backtest-trade/{trade_id}` | `app/api/reviews.py` | 创建复盘 note | 存在 |
| GET | `/api/reviews` | `app/api/reviews.py` | 复盘列表 | 存在 |
| GET | `/api/reviews/tags` | `app/api/reviews.py` | 复盘标签 | 存在 |
| GET | `/api/reviews/stats` | `app/api/reviews.py` | 复盘统计 | 存在 |
| GET/PUT | `/api/reviews/{review_id}` | `app/api/reviews.py` | 复盘详情/更新 | 存在 |
| POST | `/api/reviews/{review_id}/attachments` | `app/api/reviews.py` | 附件记录 | 存在 |
| WS | backtest / signal websocket | `app/websocket/backtests.py`、`signals.py` | 任务推送 | 存在 |
| 未发现 | `/api/strategies*` | 前端 `apps/quant-web/src/api/strategy.ts` 调用 | 策略接口 | 前后端不一致 |
| 未发现 | `/api/settings*` | 无明确后端路由 | 设置持久化 | 不存在 / 待确认 |

## 8. 当前数据库表 / 模型清单

| 表名 / 模型 | 文件位置 | 用途 | 当前是否被 API 使用 |
|---|---|---|---|
| `data_sources` / `DataSource` | `app/models/data_center.py` | 数据源配置 | 是，`/api/v1/data/sources` |
| `exchanges` / `Exchange` | `app/models/data_center.py` | 交易所 | 是 |
| `instruments` / `Instrument` | `app/models/data_center.py` | 品种 | 是 |
| `contracts` / `Contract` | `app/models/data_center.py` | 合约 | 是 |
| `trading_calendars` / `TradingCalendar` | `app/models/data_center.py` | 交易日历 | 间接/未知 |
| `trading_sessions` / `TradingSession` | `app/models/data_center.py` | 交易时段 | 间接/未知 |
| `fee_margin_rules` / `FeeMarginRule` | `app/models/data_center.py` | 手续费/保证金规则 | 是，回测参数解析 |
| `main_contract_map` / `MainContractMap` | `app/models/data_center.py` | 主力映射 | 是，合约解析/数据 |
| `futures_ex_factors` / `FuturesExFactor` | `app/models/data_center.py` | 复权因子 | 存在，使用程度待确认 |
| `futures_trading_parameters` / `FuturesTradingParameter` | `app/models/data_center.py` | 交易参数 | 是，`contract_resolver.py` |
| `data_download_tasks` / `DataDownloadTask` | `app/models/data_center.py` | 数据下载任务 | 是，数据中心 API |
| `market_data_files` / `MarketDataFile` | `app/models/data_center.py` | 行情文件元数据 | 是，MarketDataReader |
| `data_quality_reports` / `DataQualityReport` | `app/models/data_center.py` | 数据质量报告 | 是 |
| `watchlists` / `Watchlist` | `app/models/backtest.py` | 观察池 | 是，watchlist API |
| `watchlist_items` / `WatchlistItem` | `app/models/backtest.py` | 观察池品种 | 是 |
| `backtest_tasks` / `BacktestTask` | `app/models/backtest.py` | 回测任务 | 是 |
| `backtest_reports` / `BacktestReportModel` | `app/models/backtest.py` | 回测报告 | 是 |
| `backtest_trades` / `BacktestTradeModel` | `app/models/backtest.py` | 交易明细 | 是 |
| `backtest_orders` / `BacktestOrderModel` | `app/models/backtest.py` | 委托明细 | 是 |
| `backtest_equity_curve` | migration / API | 资金曲线 | 是 |
| `backtest_drawdown_curve` | migration / API | 回撤曲线 | 是 |
| `signal_scan_tasks` / `SignalScanTask` | `app/models/signal.py` | 信号扫描任务 | 是 |
| `strategy_signals` / `StrategySignal` | `app/models/signal.py` | 策略信号 | 是 |
| `signal_notifications` / `SignalNotification` | `app/models/signal.py` | 信号通知记录 | 是/部分 |
| `review_notes` / `ReviewNote` | `app/models/review.py` | 单笔复盘 note | 是 |
| `review_tags` / `ReviewTag` | `app/models/review.py` | 复盘标签 | 是 |
| `review_attachments` / `ReviewAttachment` | `app/models/review.py` | 复盘附件记录 | 是/部分 |
| `risk_profiles` | 未发现对应 ORM | 风控配置 | 不存在 / 待确认 |
| `strategies`、`strategy_versions` | 未发现对应 ORM | 策略中心版本表 | 不存在 / 待确认 |

## 9. 当前策略与策略知识文件

- 苏冰课程内容是否已经整理成 skill：是。`.agents/skills/su-bing-strategy/SKILL.md` 定义了通用苏冰课程知识资产，引用 `references/source-map.md`、`STRATEGY_GENERATION_PROTOCOL.md`、rulebook/review tags 等。
- 当前 skill 的作用：整理课程资料索引、规则候选、复盘标签、Strategy Spec 生成协议和审查边界；明确不直接生成代码、不绑定 JM、不绑定 V1-B、不把旧策略规格当默认实现。
- 当前是否已有由 skill 生成的新策略：未能从代码中确认。已有 `su_bing_ema21` 和 `jm_v1b_daily_direction_fast_entry`，但 skill 明确禁止默认继承旧策略或把课程内容直接转成交易信号。
- 当前是否还在引用旧苏冰策略：是，`services/quant-api/app/strategy/su_bing_ema21.py`、`packages/quant-core/guiyi_quant/strategies/su_bing_ema21/`、`docs/strategy_knowledge/su_bing/SU_BING_QUANT_SPEC_V0_1.md` 均存在；它们应视为草稿/历史参考，不能直接替代新的策略规格审查。
- 当前策略代码和策略知识文档之间的关系：知识文档提供候选规则和审查边界；正式策略代码在 `packages/quant-core/` 和 `services/quant-api/app/strategy/`；当前 V1-B 正式代码更接近 JM 专用策略，而不是通用苏冰 skill。
- 是否存在版权或大段课程原文风险：skill 文档已明确不要复制私有 Notion exports、课程长文、截图或图片案例；当前仍需人工检查苏冰 rulebook 修改内容是否只保留短摘要/规则候选，尤其是当前 rulebook 文件处于未提交修改状态。
- 后续更合理的策略开发流程：先用 skill 生成独立 Strategy Spec -> 审查未来函数、数据泄露、成交假设、成本、风控和版本边界 -> 用户确认允许修改文件 -> 再实现 vn.py `CtaTemplate`、参数 schema、测试和回测任务。

## 10. 当前运行方式

### 10.1 后端启动

```bash
cd services/quant-api
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

或使用一键脚本：

```bash
./scripts/dev-up.sh
```

### 10.2 前端启动

```bash
cd apps/quant-web
pnpm dev --host 127.0.0.1 --port 5173
```

### 10.3 数据库启动

```bash
docker compose up -d
```

迁移：

```bash
cd services/quant-api
uv run alembic upgrade head
```

### 10.4 Worker 启动

```bash
cd services/quant-api
uv run python -m app.worker backtests
uv run python -m app.worker signals
```

### 10.5 回测运行

固定 JM V1-B API：

```text
POST /api/backtests/v1b/jm/15m/tasks
POST /api/backtests/v1b/jm/5m/tasks
```

通用任务 API：

```text
POST /api/backtests/tasks
POST /api/backtests/run
POST /api/backtests/run-batch
```

Demo：

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --check-env
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --sample
```

### 10.6 测试命令

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
cd apps/quant-web && pnpm test:indicators
```

本次文档任务未运行上述测试，因为没有修改业务代码；当前测试文件删除状态会影响后续测试结果，需要先人工确认。

## 11. 当前最混乱的地方

### P0：会阻塞继续开发或导致方向错误的问题

1. 工作区不干净且有测试文件删除状态。路径见 `git status --short`，尤其是 `services/quant-api/tests/test_*.py` 多个 `D`。这会直接影响任何后续测试和交接判断。
2. 前端策略中心调用 `/api/strategies*`，但后端未发现对应路由。涉及 `apps/quant-web/src/api/strategy.ts`、`services/quant-api/app/main.py`、`services/quant-api/app/api/`。
3. 文档口径已初步收敛。当前外部审查入口是 `docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`，V1-B.1 需求和验收分别以 `docs/V1B1_REQUIREMENTS.md`、`docs/V1B1_ACCEPTANCE_CHECKLIST.md` 为准；旧 V1/V1-B/V1-Final 记录仅作为历史参考。
4. 回测引擎口径同时存在自研引擎和 vn.py runner。涉及 `services/quant-api/app/backtest/engine.py`、`app/vnpy_integration/backtest_runner.py`、`app/backtest/runner.py`，需要明确当前正式入口。
5. 数据源多线并存。RQData primary、Local Parquet、TqSdk validation、legacy_reference、实验样本都在仓库中，正式回测必须继续强制 primary/passed。

### P1：影响体验或验收的问题

1. 报告指标口径仍需加固：年化收益、成本、最大回撤百分比、保证金占用、连亏统计需要与交易明细一致。涉及 `services/quant-api/app/backtest/report_metrics.py`、`jm_v1b_result_enricher.py`、`app/api/backtests.py`、前端 Backtest 页。
2. 浏览器截图级 UI smoke 未完成。重点是 `/backtest`、`/market`、`/review`、`/signal`。
3. 信号扫描缺少非 inline worker 联调证据和真实触发信号样本。涉及 `app/api/signals.py`、`app/tasks/signals.py`、`app/signal/jm_v1b.py`、Web Signal 页。
4. Dashboard 明确是 mock summary，Settings 可能未持久化，Strategy 页面是壳子。
5. K线十字星联动、交易定位、marker 显示等交互需浏览器验证。

### P2：后续优化问题

1. 文档冗余较多，ChatGPT 上下文文档已有多份，需要指定最新单一入口。
2. 根目录无统一 package/workspace 配置，前后端命令分散在子目录和脚本。
3. 构建产物、缓存、`.DS_Store`、`.run/logs` 在 `find` 中可见，虽然可能未跟踪，但会干扰项目盘点。
4. 策略知识、策略代码、策略规格之间的命名和版本关系需要进一步制度化。
5. `risk_profiles`、`strategies`、`strategy_versions` 这类长期产品表未见 ORM，后续如果要做策略中心，需要补齐设计。

## 12. 当前项目真实完成度判断

| 模块 | 完成度 | 判断依据 | 是否建议继续扩展 |
|---|---:|---|---|
| 数据中心 | 75% | `app/models/data_center.py`、`app/api/data_center.py`、`scripts/rqdata_*`、`market_data_files` | 暂不扩，先稳定口径 |
| K线工作台 | 70% | `app/api/market.py`、`market_data_reader.py`、`apps/quant-web/src/pages/market/index.vue` | 是，但先做 smoke |
| 策略中心 | 35% | 策略代码存在，但 Web 调 `/api/strategies*` 后端未见路由 | 否，先补接口/版本设计 |
| 回测中心 | 75% | `app/api/backtests.py`、`app/backtest/*`、`app/vnpy_integration/*`、报告表 | 是，但先加固报告口径 |
| 报告中心 | 65% | report/trades/orders/equity/drawdown API 存在，Web 页面存在 | 是，优先加固 |
| 信号扫描 | 60% | `app/api/signals.py`、`app/signal/jm_v1b.py`、Web Signal 页 | 是，但先非 inline 联调 |
| 复盘中心 | 65% | `app/api/reviews.py`、`app/models/review.py`、Web Review 页 | 是，先补 UX 验收 |
| 风控 | 45% | 回测/信号已有成本、保证金、回撤字段，但缺系统性风控配置表 | 否，先确保回测口径真实 |
| 实盘 | 0% | V1 明确不接实盘、不下单 | V1 不建议 |

## 13. 下一步最应该聚焦的方向

方向 1：
目标：先清理/确认当前未提交改动，尤其是被删除的后端测试文件。
为什么现在做：当前工作区脏会污染所有后续判断，测试删除会让“是否通过验收”失真。
完成效果：明确哪些改动是用户有意保留，哪些需要恢复或重新提交；后续 Codex/ChatGPT 可以基于可信 diff 审查。
涉及文件：`services/quant-api/tests/test_*.py`、`README.md`、`docs/PROJECT_INVENTORY.md`、`docs/V1_FINAL_ACCEPTANCE.md`、苏冰 rulebook、`tasks/current.md`。
Codex 会话建议：适合新开一个“工作区整理/测试文件删除确认”会话，先只做 git 状态和 diff 审查，不改业务逻辑。

方向 2：
目标：做 V1-B.1 报告口径加固，统一年化收益、手续费、滑点、最大回撤百分比、保证金和连续亏损统计。
为什么现在做：回测报告是项目闭环的核心事实，如果指标口径不稳，后续策略审查和 Web 展示都会误导。
完成效果：报告 summary、trade 明细、equity/drawdown 曲线和 Web 展示口径一致，可交给外部 ChatGPT 做风控/未来函数审查。
涉及文件：`services/quant-api/app/backtest/report_metrics.py`、`jm_v1b_result_enricher.py`、`app/api/backtests.py`、`apps/quant-web/src/pages/backtest/index.vue`、相关测试。
Codex 会话建议：适合新开独立开发会话，先恢复/确认测试状态，再 TDD 修改。

方向 3：
目标：完成浏览器级 smoke 和前后端接口一致性检查。
为什么现在做：当前 Web 页面已经不少，但 Dashboard/Strategy/Settings 有壳子，策略接口疑似前后端不一致，K线 marker/复盘/信号需要截图验证。
完成效果：明确每个页面是真功能、半功能还是壳子，避免把 UI 展示误写成已完成产品能力。
涉及文件：`apps/quant-web/src/pages/*`、`apps/quant-web/src/api/*`、`services/quant-api/app/api/*`。
Codex 会话建议：适合新开 UI smoke 会话，启动本地服务，用浏览器截图逐页验证。

## 14. 给 ChatGPT 的摘要

归一量化是一个本地运行的国内期货量化研究工作站，不是公开 SaaS，也不是自动交易机器人。当前 V1 主线是：RQData / 米筐数据进入本地 standard Parquet 数据湖，由 DuckDB 和 MarketDataReader 查询，交给 vn.py CTA BacktestingEngine 做 bar 级回测，结果转换成统一结构后写入 PostgreSQL，再由 Vue 3 + Vite + TypeScript + Naive UI 的自定义 Web 展示数据、K线、回测报告、交易明细、信号扫描和复盘。V1 明确不接全自动实盘，不把信号直接下单，TqSdk / CTP 只作为后续候选或 validation 来源。

当前阶段口径是 V1-B / V1-B.1：围绕焦煤 JM 最近 3 年真实 RQData / local standard parquet 数据，跑通日线定方向、15m 和 5m 独立入场、短持有、止损退出、回测报告入库、Web 报告/K线 marker、单笔复盘和信号扫描提醒。代码层面已经存在 FastAPI、PostgreSQL ORM、Alembic、Redis/RQ worker、RQData/Parquet 数据读取、vn.py runner、JM V1-B 策略、回测报告 API、交易明细 API、资金曲线/回撤曲线 API、信号扫描 API 和复盘 API。Web 也已经有 Dashboard、数据中心、K线工作台、策略中心、回测中心、批量回测、信号监控、复盘分析、系统设置等页面。

当前最乱的问题不是继续加功能，而是先把事实收敛。第一，仓库工作区不干净：多份文档和苏冰 rulebook 被修改，同时多份后端测试文件处于删除状态，需要先确认这些改动是不是用户有意保留。第二，文档口径很多，V1-B、V1-Final、report 3/4、report 5/6 等历史记录容易混淆，后续审查必须以当前代码和数据库实证为准。第三，回测指标口径仍需加固，尤其是年化收益、手续费、滑点、最大回撤百分比、保证金和连续亏损，必须确保报告 summary、trade 明细、equity/drawdown 曲线和 Web 展示一致。第四，前后端有接口不一致风险：前端策略中心调用 `/api/strategies*`，后端当前未发现对应路由；Dashboard 和 Settings 也更像壳子。最建议下一步先做工作区清理确认，再做 V1-B.1 报告口径加固，最后做浏览器级 smoke 验证 `/backtest`、`/market`、`/review`、`/signal`。

## 15. 本次 Codex 变更说明

- 本次新增 / 修改文件：`docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`。
- 是否修改业务代码：否。
- 是否修改配置：否。
- 是否发现敏感信息：发现疑似敏感配置位置，需要人工检查；本文未复制具体值。
- 建议用户下一步怎么把这个 Markdown 发给 ChatGPT：直接打开 `docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`，复制全文给 ChatGPT，并要求它优先审查“工作区脏状态、测试删除、回测报告口径、前后端接口不一致、V1 不做实盘边界”；如需验收准绳，再附上 `docs/V1B1_REQUIREMENTS.md` 和 `docs/V1B1_ACCEPTANCE_CHECKLIST.md`。
