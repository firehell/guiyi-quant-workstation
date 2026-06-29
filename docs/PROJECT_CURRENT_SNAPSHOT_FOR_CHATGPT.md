# 归一量化项目当前快照

## 1. 快照生成信息

- 生成时间：2026-06-29 23:20:12 CST，补充验证完成于同日 23:20 后。
- 当前分支：`main`。
- git status 摘要：本轮开始时 `git status --short` 为空；运行测试和前端构建后再次检查仍为空。
- 当前是否有未提交修改：否。
- 本次盘点是否修改业务代码：否。本轮只更新本文档。
- 本文档用途：给 ChatGPT 后续深入讨论归一量化下一阶段路线使用，作为当前仓库代码、docs、tests 和本轮运行结果的合并快照。
- 证据优先级：当前代码和本轮运行结果优先，其次是当前 docs；历史聊天、旧计划和过期文档不作为最终事实。
- 敏感信息处理：仓库存在 `.env`，本轮未读取、未复制、未记录任何账号、密码、Token、API Key、交易密钥。
- checkpoint 建议：本轮开始时工作区干净，若进入下一轮业务代码修改，建议先由用户或 Cursor 执行 `git status && git add . && git commit -m "checkpoint: before project current snapshot"` 或等价 checkpoint。

## 2. 项目一句话定位

归一量化当前是一个本地运行的国内期货研究工作站，不是公开 SaaS、不是普通展示网站，也不是无人值守交易系统。第一版围绕“数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号 -> 复盘”的 V1 Web 研究闭环展开。当前实际工程重点是用 RQData / local standard Parquet 支撑焦煤 JM 真实数据研究、vn.py CTA 回测、PostgreSQL 归档和 Vue Web 复盘。信号扫描只做提醒和观察，不触发自动下单。

## 3. 当前 V1 闭环状态总览

| 链路 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 数据 | 基本可用 | 运行结果 + 当前代码 + docs | JM RQData canonical Parquet 已存在 1d/15m/5m/1m；数据中心模型、API、RQData ingest、质量报告脚本存在。未连接本地 DB 复核最新入库状态。 |
| K线 | 基本可用 | 当前代码 + tests | `/api/v1/market/bars`、`MarketDataReader`、Vue `/market`、Lightweight Charts 组件存在；浏览器 smoke 本轮未做。 |
| 策略 | 部分可用 | 当前代码 + tests + docs | 有 `jm_v1b_daily_direction_fast_entry`、`su_bing_jm_v1b_short_hold`、日线 EMA21/MACD/量能策略和 EMA21 草稿；策略中心 Web/后端版本治理不完整。 |
| 回测 | 基本可用 | 当前代码 + tests | vn.py runner、任务 API、RQ worker、result converter、报告/交易/曲线入库模型存在；prepared-only 和旧自研 `/run` 路径仍保留。 |
| 报告 | 基本可用 | 当前代码 + docs + 导出文件 | report/trades/orders/equity/drawdown API 存在，`backtests/reports/` 有 review package；报告口径仍需做 trade 事实源一致性验收。 |
| 信号 | 部分可用 | 当前代码 + tests | 通用扫描和 JM V1-B 扫描 API、RQ/inline 路径、Web `/signal` 存在；真实触发信号样本和定时调度未验证。 |
| 复盘 | 基本可用 | 当前代码 + tests | 可从 backtest trade 创建 review note，复盘标签/统计/附件模型和 API 存在；K线联动体验未浏览器验证。 |
| Web 展示 | 部分可用 | 当前代码 + 前端 build | Dashboard/Data/Market/Strategy/Backtest/Signal/Review/Settings 路由存在；Dashboard 是 mock，Strategy/Settings 可能是壳子。 |
| worker / scheduler | 部分可用 | 当前代码 + scripts | Redis/RQ backtests/signals worker 存在，`dev-up.sh` 会启动；APScheduler 仅为依赖，未发现正式调度实现。 |
| 测试 | 基本可用 | 运行结果 | `ruff` 通过，后端 `155 passed`，前端 build 通过，指标测试 4 passed；缺浏览器 smoke、真实 DB/Alembic current、worker 非 inline 端到端验收。 |

## 4. 当前仓库结构

| 目录 | 作用 | 关键文件 | 当前完成度 | 风险点 |
|---|---|---|---|---|
| `apps/quant-web/` | Vue 3 Web 工作台 | `src/app/router.ts`、`src/pages/*`、`src/api/*`、`package.json` | 部分可用 | `dist/` 为忽略构建产物；Dashboard mock，Strategy/Settings 与后端不完全一致。 |
| `services/quant-api/` | FastAPI、ORM、回测、数据读取、RQ worker | `app/main.py`、`app/api/*`、`app/backtest/*`、`app/vnpy_integration/*`、`app/models/*` | 基本可用 | 旧自研回测路径和 vn.py 路径并存，需明确正式入口。 |
| `packages/quant-core/` | 策略共享包和 vn.py CtaTemplate 策略 | `guiyi_quant/strategies/*` | 部分可用 | 多个策略版本并存，当前主线需冻结。 |
| `docs/` | 架构、路线、验收、策略 spec、外部审查上下文 | `ROADMAP.md`、`V1B1_REQUIREMENTS.md`、`BACKTEST_RESULT_V1_STANDARD.md`、本文 | 部分可用 | 文档之间存在阶段口径冲突：`AGENTS.md`/交接文档偏 V1-B，`ROADMAP.md` 写 V1-Final。 |
| `tasks/` | Codex 任务模板和流转目录 | `tasks/current.md` | 未完成 | 当前 `tasks/current.md` 仍是模板，不是本轮任务实录。 |
| `scripts/` | 本地启动、RQData/TqSdk 同步、审计、导出 | `dev-up.sh`、`dev-down.sh`、`rqdata_*`、`tqsdk_*`、`export_*` | 基本可用 | 同时包含 TqSdk validation 脚本，容易和 V1 主链路混淆。 |
| `tests/` | 后端测试在服务目录，前端指标测试在 Web 目录 | `services/quant-api/tests/`、`apps/quant-web/tests/indicators.test.ts` | 基本可用 | 缺浏览器级页面 smoke 和 DB migration current 验收。 |
| `services/quant-api/alembic/` | Alembic migration | `env.py`、`versions/20260623_0001...20260628_0012...` | 基本可用 | 本轮未执行 migration，也未连接 DB 检查当前 head。 |
| `data/` | 本地数据湖、manifest、质量报告 | `data/parquet/`、`data/manifests/`、`data/reports/` | 部分可用 | 含正式 RQData 和 legacy/validation 数据，必须靠 `data_role` 隔离。 |
| `backtests/` | 本地导出报告和 review package | `backtests/reports/*` | 部分可用 | 本地 CSV/MD 导出不等于当前数据库事实。 |

## 5. 后端服务状态

- 启动方式：`cd services/quant-api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`；也可用 `./scripts/dev-up.sh`。
- FastAPI 入口：`services/quant-api/app/main.py`。
- 健康检查：`GET /health`、`GET /api/health`。
- Dashboard：`GET /api/dashboard/summary`，当前代码明确返回 `data_status: mock`。
- 主要路由：
  - 数据中心：`services/quant-api/app/api/data_center.py`，`/api/v1/data/sources`、`/exchanges`、`/instruments`、`/contracts`、`/download-tasks`、`/quality-reports`、`/coverage`。
  - K线查询：`services/quant-api/app/api/market.py`，`/api/v1/market/workbench/coverage`、`/api/v1/market/bars`。
  - 兼容 K线：`/api/symbols`、`/api/klines`。
  - 回测：`services/quant-api/app/api/backtests.py`，`/api/backtests/tasks`、`/api/backtests/v1b/jm/{15m|5m}/tasks`、`/api/backtests/v1b/jm/daily-ema21-macd-volume/tasks`、`/api/backtests/reports`、report trades/orders/equity/drawdown。
  - 信号：`services/quant-api/app/api/signals.py`，`/api/signals/scan`、`/api/signals/v1b/jm/scan`、`/api/signals/latest`、信号 ack/status。
  - 复盘：`services/quant-api/app/api/reviews.py`，backtest trades source、`/from-backtest-trade/{trade_id}`、reviews、tags、stats、attachments。
- WebSocket：`services/quant-api/app/websocket/backtests.py`、`services/quant-api/app/websocket/signals.py`。
- 当前缺口：
  - 未发现后端 `/api/strategies*` 路由，但前端存在 strategy API/page。
  - Dashboard summary 仍是 mock。
  - 本轮未启动 API 做浏览器/HTTP smoke。
  - 本轮未连接数据库验证 Alembic current、report_id、任务状态和 worker 实际消费。

## 6. 数据中心状态

- 当前使用的数据源：
  - V1 主口径：RQData / local standard Parquet，依据 `AGENTS.md`、`README.md`、`docs/DATA_CENTER.md`、`app/data_sources/roles.py`、`app/backtest/v1b_jm_tasks.py`。
  - DuckDB：用于读取 Parquet，见 `services/quant-api/app/services/market_data_reader.py`。
  - PostgreSQL：用于元数据、任务、报告、信号、复盘事实表。
  - TqSdk：存在 ingest 和审计脚本，但当前定位为 validation / V2 候选。
  - trader_future_data：磁盘上有大量 `data/parquet/market/provider=trader_future_data/...`，应视为 legacy/reference，不进入正式回测。
- 当前已有数据范围：
  - 运行结果显示 JM canonical RQData Parquet：`1d` 727 行、`15m` 16569 行、`5m` 49707 行、`1m` 248535 行。
  - 文件路径：`data/parquet/canonical/bars/provider=rqdata/period={1d,15m,5m,1m}/exchange=DCE/symbol=jm/contract=jm.MAIN/...20230103_20251231.parquet`。
  - Parquet 字段包含 `source`、`provider`、`data_role`、`quality_status`、`data_version`。
- 当前支持的品种：
  - 正式 V1-B 研究主线：焦煤 JM。
  - 磁盘 legacy/validation 层存在多品种 trader_future_data 和 TqSdk manifest；不等同正式 V1 主数据能力。
- 当前支持周期：
  - JM RQData canonical：1m、5m、15m、1d。
  - trader_future_data 中还可见 15m、1d、30m 等，但属于 legacy/reference。
- 数据存储方式：
  - 大体量行情：Parquet。
  - 查询：DuckDB `read_parquet()`。
  - 元数据和业务事实：PostgreSQL。
  - 数据 manifest / 报告：CSV/MD 在 `data/manifests/`、`data/reports/`。
- 数据质量检查能力：
  - 模型：`DataQualityReport`。
  - API：`/api/v1/data/quality-reports`。
  - 脚本：`scripts/rqdata_audit.py`、`scripts/rqdata_field_audit.py`、`scripts/rqdata_coverage_audit.py`、`scripts/tqsdk_data_audit.py`。
  - 文档/结果：`data/reports/rqdata_field_audit.md`、`data/reports/rqdata_product_coverage_summary.md`、`data/reports/tqsdk_quality_report.csv`。
- 主力合约 / 连续合约处理状态：
  - 代码有 `main_contract_map`、`futures_continuous_contract_map` 模型和 `scripts/rqdata_main_mapping_sync.py`、`scripts/rqdata_continuous_contracts_sync.py`。
  - JM V1-B 当前研究合约为 `jm.MAIN`，需要继续明确“研究连续合约”和“真实可交易合约”转换口径。
- price_tick / 合约乘数 / 手续费 / 滑点：
  - 解析器：`services/quant-api/app/backtest/contract_resolver.py`。
  - 数据模型：`futures_trading_parameters`、`fee_margin_rules`。
  - 成本增强：`jm_v1b_result_enricher.py`、`jm_daily_ema21_result_enricher.py`。
  - 回测配置：`rate`、`slippage`、`size`、`pricetick`。
- 已知数据问题：
  - 多数据源并存，正式回测必须强制 `provider=rqdata/local_parquet`、`data_role=primary`、`quality_status=passed`。
  - 本轮未连接 DB 检查 `market_data_files` 是否与磁盘 Parquet 完全一致。
  - `README.md`、`ROADMAP.md`、V1-B/V1-Final 文档对阶段完成度有不同表述。
- 需要后续验证：
  - Alembic head 与本地 DB schema 是否一致。
  - `price_tick` 补齐结果是否在当前 DB 中仍完整。
  - 交易参数、手续费、保证金是否能覆盖每一笔真实合约日期。

## 7. 策略中心状态

- 当前已有策略列表：
  - `jm_v1b_daily_direction_fast_entry`：`packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/`。
  - `su_bing_jm_v1b_short_hold`：`packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/`。
  - `su_bing_jm_daily_ema21_macd_volume`：`packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/`。
  - `su_bing_ema21`：`packages/quant-core/guiyi_quant/strategies/su_bing_ema21/` 和 `services/quant-api/app/strategy/su_bing_ema21.py`。
  - 说明性目录：`strategies/ma_breakout/`、`strategies/n_structure/`、`strategies/su_bing_ema21/`。
- 当前主策略：
  - 代码固定任务主线仍是 `jm_v1b_daily_direction_fast_entry`，版本 `v1b.0`。
  - 苏冰 JM 短持有策略 `su_bing_jm_v1b_short_hold` 也有完整策略包和测试，但未发现公开 API 固定入口直接暴露它。
- 苏冰策略当前版本和逻辑：
  - `su_bing_jm_v1b_short_hold` 版本 `v0.1.1-spec`，使用日线方向、15m/5m 入场、短持有、止损/止盈、成本和保证金字段。
  - `su_bing_jm_daily_ema21_macd_volume` 版本 `v0.2.0-daily`，日线 EMA21/MACD/量能版本。
  - 策略 spec 文档在 `docs/strategy_specs/su_bing_jm_v1b_short_hold/` 和 `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`。
- 日线策略当前状态：有日线 EMA21/MACD/量能任务 builder 和策略包；报告导出目录存在 `backtests/reports/su_bing_jm_daily_ema21_macd_volume/`。
- 15m / 5m 策略当前状态：JM V1-B 固定任务支持 15m/5m；策略参数含 `max_hold_bars_min=5`、`max_hold_bars_max=8`、`fill_policy=signal_on_close_fill_next_bar_open`。
- 策略参数配置：
  - `packages/quant-core/.../default_params.json`。
  - `packages/quant-core/.../config_schema.py`。
  - `services/quant-api/app/backtest/v1b_jm_tasks.py` 的固定任务参数。
- 策略版本记录：回测任务/报告 schema 有 `strategy_code`、`strategy_version`；完整策略版本产品治理仍不完善。
- 是否支持多空对称：策略参数有 `allow_long`、`allow_short`；测试覆盖部分多空行为。是否交易表现对称，需要后续回测复核。
- 是否有未来函数风险检查：
  - 测试中有 `test_future_bar_does_not_change_prior_decision` 类用例。
  - 策略逻辑有 `daily_effective_policy=confirmed_daily_bar_effective_next_trading_day` 和下一根开盘成交。
  - 仍建议外部审查逐条检查日线确认、分型/突破确认和成交时点。
- 当前策略测试覆盖：
  - `test_su_bing_ema21_vnpy_draft.py`、`test_su_bing_jm_v1b_short_hold.py`、`test_jm_v1b_daily_direction_fast_entry.py`、`test_su_bing_jm_daily_ema21_macd_volume.py`。
- 目前策略最大问题：
  - 多个“苏冰/JM”策略版本并存，下一阶段必须先冻结一个正式策略 spec，再做参数和表现讨论。
  - 回测已可跑不等于策略可用于交易决策。

## 8. 回测系统状态

- 当前回测引擎：
  - 正式路线：vn.py / VeighNa CTA `BacktestingEngine`，封装在 `services/quant-api/app/vnpy_integration/backtest_runner.py`。
  - 旧/兼容路径：`services/quant-api/app/backtest/engine.py` 自研 bar 级回测仍存在，`POST /api/backtests/run` 使用该路径。
- 是否真实调用 vn.py：是。`VnpyBacktestRunner.run()` 加载 `vnpy_ctastrategy.backtesting.BacktestingEngine`，注入标准 bars，执行 `run_backtesting()`、`calculate_result()`、`calculate_statistics()`。
- 是否还有 prepared-only / mock / fake 路径：
  - `GuiyiBacktestRequest.prepared_only` 存在。
  - Dashboard summary 是 mock。
  - 旧 `/api/backtests/run` 自研路径仍存在。
- 回测任务如何创建：
  - 通用：`POST /api/backtests/tasks`。
  - JM 固定：`POST /api/backtests/v1b/jm/15m/tasks`、`POST /api/backtests/v1b/jm/5m/tasks`。
  - 日线：`POST /api/backtests/v1b/jm/daily-ema21-macd-volume/tasks`。
  - 批量：`POST /api/backtests/run-batch`。
- 回测结果如何生成：
  - `app/tasks/backtests.py` -> `BacktestService` -> `app/backtest/runner.py` -> `VnpyBacktestRunner` -> `result_converter` -> enricher -> 入库。
- trade / order / daily / equity / drawdown 如何落地：
  - 表模型：`backtest_reports`、`backtest_trades`、`backtest_orders`。
  - 迁移：`20260627_0010_backtest_result_detail_tables.py`、`20260628_0012_backtest_result_v1_summary_trades.py`。
  - equity/drawdown API 存在，当前是否仍物理表存储需以后续 DB schema 复核为准。
- 手续费、滑点、合约乘数、price_tick：
  - `contract_resolver.py` 解析合约参数。
  - `jm_*_result_enricher.py` 将真实合约成本、滑点、保证金写入 trade/report。
  - `report_metrics.py` 汇总 `total_commission`、`total_slippage`、`max_margin_required`、`max_margin_usage_pct`。
- 回测报告如何入库：`services/quant-api/app/backtest/service.py`、`app/services/batch_backtest.py`。
- 当前回测可信度评价：
  - 工程链路基本可用，测试通过。
  - 可信研究仍需要按 `docs/BACKTEST_RESULT_V1_STANDARD.md` 做 report/trades 一致性验收。
  - 未经浏览器 smoke、DB current、worker 非 inline 验收前，不建议视为 V1-Final 彻底完成。
- 已知风险：
  - 未来函数：有防护和测试，但仍需外部逐条审查。
  - 数据泄露：日线辅助数据必须确保只用已确认日线。
  - 过拟合：目前是 JM 单品种/特定窗口，不能直接推广。
  - 成交撮合偏差：以 `next_bar_open` 为主，需验证所有策略入口一致。
  - 成本：已有字段和增强器，但需要逐笔和 summary 复算。
- 关键测试命令：
  - `uv run --project services/quant-api pytest -q`
  - `uv run --project services/quant-api ruff check .`

## 9. Web 前端状态

- 前端技术栈：Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts / vue-echarts。
- 启动方式：`cd apps/quant-web && pnpm dev --host 127.0.0.1 --port 5173`；或 `./scripts/dev-up.sh`。
- 页面列表：
  - `/dashboard`：`apps/quant-web/src/pages/dashboard/index.vue`。
  - `/data`：`apps/quant-web/src/pages/data/index.vue`。
  - `/market`：`apps/quant-web/src/pages/market/index.vue`。
  - `/strategy`：`apps/quant-web/src/pages/strategy/index.vue`。
  - `/backtest`：`apps/quant-web/src/pages/backtest/index.vue`。
  - `/backtest/batch`：`apps/quant-web/src/pages/backtest/batch.vue`。
  - `/signal`：`apps/quant-web/src/pages/signal/index.vue`。
  - `/review`：`apps/quant-web/src/pages/review/index.vue`。
  - `/settings`：`apps/quant-web/src/pages/settings/index.vue`。
- Dashboard 状态：页面存在；后端 summary 是 mock。
- 数据中心页面状态：接 `/api/v1/data/*`，基本可用。
- K线图页面状态：接 market API，使用 Lightweight Charts；本轮未浏览器验收。
- 策略页面状态：页面存在，但后端未发现 `/api/strategies*`，接口一致性风险高。
- 回测任务页面状态：接 tasks/reports/trades/orders/equity/drawdown API，基本可用。
- 回测报告页面状态：支持 report_id 查询、交易明细、导出、跳转 K线/复盘。
- 交易明细页面状态：嵌在回测页。
- 复盘页面状态：接 reviews API，支持从交易源创建/查看 note。
- 信号页面状态：接 signals API；前端代码中对 watchlist 有 JM fallback。
- 当前 K线图能力：K线、指标、marker 相关代码存在。
- 买卖点标记能力：`apps/quant-web/src/utils/tradeMarker.ts`、`src/components/kline/KlineChart.vue`、Market/Backtest 页面中有交易 marker 逻辑。
- 十字星 / MACD / 副图联动是否已修复：不确定，需要后续浏览器 smoke。指标函数测试通过不等于 UI 联动已验收。
- 页面刷新 / 路由切换是否已修复：不确定，需要浏览器 smoke。
- 当前 Web 已知问题：
  - 前端 build 有 `BaseChart-Z2_qqnFf.js 501.85 kB` chunk warning。
  - Dashboard mock。
  - Strategy/Settings 可能是壳子或接口不完整。
  - 本轮未检查浏览器 console 和 Network。

## 10. 报告与复盘能力

- 当前报告字段：
  - `BacktestReportModel` 包含策略、数据、引擎、收益、回撤、胜率、盈亏比、成本、保证金、连亏等字段。
  - `BacktestTradeModel` 包含 entry/exit、方向、价格、volume、gross/net pnl、commission、slippage、holding bars、reason、price_tick、multiplier、margin 等字段。
- `daily_report_summary.md` 类产物状态：
  - 已存在：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_report_summary.md`、`.json`。
- `daily_trades.csv / daily_orders.csv` 类产物状态：
  - 已存在：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_trades.csv`、`daily_orders.csv`。
- 交易明细是否可读：API 和 CSV 导出都存在；本轮未人工打开 CSV 逐行审查。
- K线买卖点是否可定位：代码路径存在；浏览器体验未验收。
- 单笔复盘能力：`POST /api/reviews/from-backtest-trade/{trade_id}` 存在。
- 复盘标签能力：`ReviewTag` 模型、`GET /api/reviews/tags` 和策略 review_tags JSON 存在。
- 当前报告最大不足：
  - 需要按 `BACKTEST_RESULT_V1_STANDARD.md` 进一步收敛事实源，避免 report/trades/equity/drawdown 口径不一致。
  - 回测导出文件、DB report 和 Web 展示之间需要做一轮端到端复核。

## 11. 信号扫描与准实时检查能力

- 当前是否支持信号扫描：支持代码路径和 API。
- 支持哪些周期：
  - `SignalScanRequest` 支持 periods；JM V1-B 专用扫描由 `services/quant-api/app/signal/jm_v1b.py` 定义。文档与前端重点是 15m / 5m。
  - 是否完整支持 1m / 30m / 日线收盘检查：不确定，需要查 JM 扫描实现和实际任务输出后确认。
- 扫描结果如何保存：
  - `signal_scan_tasks`、`strategy_signals`、`signal_notifications`。
- 是否接 Web：接 `/signal` 页面和 `apps/quant-web/src/api/signal.ts`。
- 是否接通知：有 `SignalNotification` 表和 WebSocket；未发现企业微信/邮件正式实现。
- 是否涉及自动下单：没有。V1 不做自动实盘，不做 AI 自动下单。
- 当前适合怎么实现苏冰信号扫描：
  - 先冻结苏冰策略 spec 和“信号时点/成交时点/日线确认”规则。
  - 用本地 Parquet + 已确认日线 + 5m/15m 最新收盘 bar 做只读扫描。
  - 保存 signal + no_signal reason + 风控字段，不生成订单。
  - 先用 `run_inline=true` 验证逻辑，再用 RQ worker 和 WebSocket 验收非 inline 链路。

## 12. worker / scheduler / 任务队列状态

- 当前是否使用 RQ / Redis / scheduler：
  - Redis/RQ：使用，`services/quant-api/app/queue.py`、`app/worker.py`。
  - Scheduler：`apscheduler` 是依赖，但本轮未发现正式 APScheduler job 定义。
- 哪些任务走 worker：
  - 回测：`run_backtest_task`、`run_batch_backtest_task`。
  - 信号：`run_signal_scan_task`。
- 哪些任务仍是同步执行：
  - `/api/backtests/run` 是同步旧路径。
  - `/api/backtests/run-batch` 支持 `run_inline`。
  - `/api/signals/scan` 和 `/api/signals/v1b/jm/scan` 支持 `run_inline`。
- 回测任务是否异步：固定任务和通用 tasks 默认入 RQ。
- 数据下载是否异步：有 `DataDownloadTask` 模型和脚本，但未看到完整 Web/RQ 下载任务闭环。
- 信号扫描是否定时：未发现正式 scheduler；当前更多是 API 触发。
- 当前任务系统风险：
  - Redis/RQ 不可用时 API 会把任务标为 failed 并返回 503。
  - 非 inline worker 真实消费、失败重试、幂等和状态流转需要单独验收。

## 13. 数据库与 migration 状态

- ORM / Alembic 状态：
  - ORM：`services/quant-api/app/models/data_center.py`、`backtest.py`、`signal.py`、`review.py`。
  - Alembic：`services/quant-api/alembic/versions/`，当前文件到 `20260628_0012_backtest_result_v1_summary_trades.py`。
- 当前关键表：
  - 数据中心：`data_sources`、`exchanges`、`instruments`、`contracts`、`trading_calendars`、`trading_sessions`、`fee_margin_rules`、`main_contract_map`、`futures_*`、`data_download_tasks`、`market_data_files`、`data_quality_reports`。
  - 回测：`watchlists`、`watchlist_items`、`backtest_tasks`、`backtest_reports`、`backtest_trades`、`backtest_orders`。
  - 信号：`signal_scan_tasks`、`strategy_signals`、`signal_notifications`。
  - 复盘：`review_notes`、`review_tags`、`review_attachments`。
- 是否存在未执行 migration：不确定。本轮未连接本地 DB，未运行 `alembic current`，未执行 migration。
- 是否存在破坏性 migration 风险：当前未逐行审查所有 migration；下一步如动表结构必须先外部审查和备份。
- 数据库初始化方式：
  - Docker Compose 提供 PostgreSQL。
  - `services/quant-api/alembic.ini` + Alembic。
  - README 提供 `docker compose up -d` 和后端启动方式。
- 本地 DB 验收状态：本轮未验收。
- 下一步是否建议 migration：不建议本轮做。下一阶段如果仅做快照确认，也先运行只读 `alembic current` / `alembic heads`；只有发现模型和 DB schema 明确不一致时再计划 migration。

## 14. 测试与验收状态

- 已发现的测试目录：
  - `services/quant-api/tests/`
  - `apps/quant-web/tests/`
- 后端测试命令：
  - `uv run --project services/quant-api pytest -q`
  - 本轮结果：155 passed in 12.29s。
- 后端 lint：
  - `uv run --project services/quant-api ruff check .`
  - 本轮结果：All checks passed。
- 前端测试命令：
  - `cd apps/quant-web && pnpm build`
  - 本轮结果：通过，保留 501.85 kB chunk warning。
  - `cd apps/quant-web && pnpm test:indicators`
  - 本轮结果：4 passed。
- 回测测试命令：
  - 已包含在后端 pytest 中，关键文件有 `test_backtest_service_runner.py`、`test_backtest_task_api.py`、`test_vnpy_integration.py`、`test_backtest_contract_resolver.py`、`test_v1b_jm_fixed_backtest_tasks.py`。
- 策略测试命令：
  - 已包含在后端 pytest 中，关键文件有 `test_jm_v1b_daily_direction_fast_entry.py`、`test_su_bing_jm_v1b_short_hold.py`、`test_su_bing_jm_daily_ema21_macd_volume.py`、`test_su_bing_ema21_vnpy_draft.py`。
- 最近验收文档：
  - `docs/V1B1_ACCEPTANCE_CHECKLIST.md`
  - `docs/V1B1_REQUIREMENTS.md`
  - `docs/V1_FINAL_ACCEPTANCE.md`
  - `docs/V1B_JM_3Y_FAST_ENTRY.md`
- 稳定通过：
  - 本轮后端 pytest、ruff、前端 build、前端指标测试均通过。
- 测试缺失：
  - 浏览器 console/Network smoke。
  - 本地 DB Alembic current/head 验收。
  - RQ worker 非 inline 端到端。
  - report/trades/equity/drawdown 真实 DB report 一致性复算。
  - 策略样本外验证和参数过拟合检查。
- 建议下一步补测：
  - `/backtest`、`/market`、`/review`、`/signal` 浏览器验收。
  - `report_id` 对应 summary/trades/equity/drawdown 复算脚本。
  - 信号扫描 worker 消费 + no_signal/triggered_signal 双样本。

## 15. 当前已知问题与阻塞点

### P0

| 问题描述 | 影响范围 | 证据文件 | 建议处理方式 |
|---|---|---|---|
| 当前 docs 阶段口径冲突：V1-B、V1-B.1、V1-Final 同时出现 | 后续路线判断、外部审查 | `AGENTS.md`、`docs/ROADMAP.md`、`docs/CODEX_HANDOFF.md`、`docs/V1B1_REQUIREMENTS.md` | 先以当前代码和本快照确认真实状态，再统一 ROADMAP/交接文档。 |
| 回测报告事实源仍需最终统一 | 回测可信度、报告可信度 | `docs/BACKTEST_RESULT_V1_STANDARD.md`、`app/vnpy_integration/result_converter.py`、`app/backtest/report_metrics.py` | 以 trade 为唯一盈亏事实源，复算 summary、曲线、Web 字段。 |
| 正式数据和 legacy/validation 数据共存 | 数据正确性、回测可信度 | `data/parquet/canonical/...provider=rqdata`、`data/parquet/market/provider=trader_future_data`、`app/data_sources/roles.py` | 正式回测继续强制 primary/passed，Web/API 显示数据角色。 |
| 策略版本并存，主策略未最终冻结 | 策略信号正确性、讨论焦点 | `packages/quant-core/guiyi_quant/strategies/*`、`app/backtest/v1b_jm_tasks.py` | 下一阶段先冻结 JM/Su Bing 策略 spec 和正式入口。 |

### P1

| 问题描述 | 影响范围 | 证据文件 | 建议处理方式 |
|---|---|---|---|
| 前端策略页面疑似无匹配后端路由 | Web 使用体验、接口一致性 | `apps/quant-web/src/api/strategy.ts`、`apps/quant-web/src/pages/strategy/index.vue`、`app/main.py` 路由列表 | 要么补策略 API，要么将页面明确标记为规划中。 |
| Dashboard summary 是 mock | Web 总览可信度 | `services/quant-api/app/main.py` | 后续接真实数据、任务、报告、信号统计。 |
| 浏览器级 smoke 未做 | Web 复盘效率 | `docs/V1B1_ACCEPTANCE_CHECKLIST.md` | 用 Browser/Chrome 验收 `/backtest`、`/market`、`/review`、`/signal`。 |
| RQ worker 非 inline 链路未实测 | 回测/信号任务可靠性 | `app/worker.py`、`app/api/backtests.py`、`app/api/signals.py` | 启动 Redis/RQ worker，创建任务并检查状态流转。 |
| `settings` 页面持久化不确定 | Web 一致性 | `apps/quant-web/src/pages/settings/index.vue` | 明确 V1 是否需要真实系统设置。 |

### P2

| 问题描述 | 影响范围 | 证据文件 | 建议处理方式 |
|---|---|---|---|
| 前端 build chunk warning | 前端性能 | `pnpm build` 输出 | 后续拆分 `BaseChart` 或调整代码分割。 |
| `tasks/current.md` 仍是模板 | Agent 协作 | `tasks/current.md` | 下一轮实际任务前同步任务包。 |
| 旧文档较多，容易让 ChatGPT 读偏 | 文档体验 | `docs/V1_ACCEPTANCE.md`、`docs/V1_FINAL_ACCEPTANCE.md`、旧阶段文档 | 不删除文件；先在 README/ROADMAP 标注“历史参考/当前入口”。 |
| 企业微信/邮件通知未实现 | 后续增强 | `SignalNotification` 模型、未见外部通知 adapter | V1 先不做，信号 Web 展示稳定后再评估。 |

## 16. 当前项目真实完成度评估

- V1 是否完成：谨慎判断为“工程闭环基本跑通，但 V1 尚未完全完成”。原因是浏览器 smoke、DB current、worker 非 inline、报告事实源一致性仍需验收。
- V1-Final 是否完成：不建议直接认定完成。`ROADMAP.md` 写 V1-Final 已通过，但本轮以当前代码审查和运行结果看，仍有若干验收缺口。
- 已经可用于研究的部分：
  - JM RQData Parquet 数据检查。
  - 后端 API 和 vn.py 回测链路开发验证。
  - 策略规则单元测试和本地报告导出。
  - Web 回测/复盘/信号页面的开发联调。
- 还不能用于交易决策的部分：
  - 策略收益结论。
  - 参数优化结论。
  - 自动/半自动实盘准入。
  - 未经报告复算和样本外验证的信号。
- 当前是否可以开始重点优化策略：
  - 可以开始“准备策略优化”，但第一步应是冻结策略 spec、确认数据/报告可信度和建立复盘分析基线。
  - 不建议直接大规模调参。
- 当前是否适合接实盘：不适合。V1 明确不接实盘，不自动下单；当前也缺模拟、小资金、风控拦截、人工确认、日志归档等实盘前置验收。

## 17. 下一阶段建议

| 顺序 | 目标 | 为什么排在这一步 | 验收标准 | 是否需要 Codex Plan 模式 |
|---|---|---|---|---|
| 1 | 当前快照确认 | 先统一“现在到底是什么状态” | 用户确认本文档作为 ChatGPT 讨论入口 | 否 |
| 2 | 数据可信度最终验收 | 数据错，策略和回测都无意义 | DB `market_data_files` 与磁盘 Parquet 一致，JM 1m/5m/15m/1d primary/passed，交易参数可解析 | 是 |
| 3 | 苏冰日线策略规则冻结 | 避免一边改规则一边评估表现 | `STRATEGY_SPEC.md`、当前代码规则、测试一致 | 是 |
| 4 | 焦煤 3 年回测复核 | 核心样本必须可复现 | 15m/5m/日线 report 可重跑，summary/trades/成本/回撤可复算 | 是 |
| 5 | 交易明细与 K线复盘联合分析 | 找出亏损结构和信号问题 | trades 可跳 K线，marker 正确，复盘 note 可创建 | 是 |
| 6 | 信号扫描设计 | 研究闭环下一步是提醒，不是交易 | run_inline 和 RQ worker 都可跑，no_signal/triggered_signal 都可展示，不下单 | 是 |
| 7 | 策略优化迭代 | 前面可信后再讨论优化才有意义 | 有版本、参数、样本内/样本外、复盘标签和回测报告对比 | 是 |
| 8 | Web 复盘体验补齐 | 提高研究效率 | `/backtest`、`/market`、`/review`、`/signal` 浏览器 smoke 通过 | 可直接执行，涉及架构则 Plan |
| 9 | 最后再考虑模拟 / 实盘 | 当前 V1 不做自动实盘 | 只有信号、风控、人工确认、模拟验证成熟后才进入 V1.5/V2 | 是 |

## 18. 给 ChatGPT 的重点摘要

- 当前项目已经能做什么：
  - 本地 FastAPI + Vue Web + PostgreSQL/Alembic + Redis/RQ 框架已成形。
  - JM RQData standard Parquet 数据存在 1m/5m/15m/1d 四个周期。
  - vn.py 回测 runner、结果转换、成本增强、报告入库模型和 API 存在。
  - Web 有数据中心、K线、回测、信号、复盘页面。
  - 后端 155 个 pytest、ruff、前端 build、指标测试本轮通过。
- 当前最重要的风险：
  - 文档阶段口径冲突。
  - 多策略版本并存，正式策略未冻结。
  - 报告/trades/曲线/成本还需要最终一致性复算。
  - legacy/validation 数据不能混进正式回测。
  - Web 和 worker 尚缺端到端验收。
- 当前最值得讨论的下一步：
  - 先确认本文快照。
  - 然后做“数据可信度 + 回测报告事实源一致性 + 苏冰策略规则冻结”三件事。
- 如果继续做策略优化，ChatGPT 最需要关注：
  - `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/`
  - `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/`
  - `services/quant-api/app/backtest/v1b_jm_tasks.py`
  - `services/quant-api/app/backtest/jm_v1b_result_enricher.py`
  - `services/quant-api/app/backtest/report_metrics.py`
  - `docs/strategy_specs/su_bing_jm_v1b_short_hold/`
  - `backtests/reports/`
- 用户下一次上传给 ChatGPT 时，建议同时上传：
  - `docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`
  - `docs/V1B1_REQUIREMENTS.md`
  - `docs/V1B1_ACCEPTANCE_CHECKLIST.md`
  - `docs/BACKTEST_RESULT_V1_STANDARD.md`
  - `docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md`
  - `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/vnpy_strategy.py`
  - `services/quant-api/app/backtest/v1b_jm_tasks.py`
  - 最新回测报告 CSV/MD，如 `backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_report_summary.md`、`daily_trades.csv`。

## 19. 附录：关键文件清单

### 项目文档

- `AGENTS.md`
- `README.md`
- `docs/ROADMAP.md`
- `docs/CODEX_HANDOFF.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/BACKTEST_RESULT_V1_STANDARD.md`
- `docs/V1B1_REQUIREMENTS.md`
- `docs/V1B1_ACCEPTANCE_CHECKLIST.md`
- `docs/V1B_JM_3Y_FAST_ENTRY.md`
- `docs/V1B_JM_3Y_SHORT_HOLD.md`
- `docs/PROJECT_INVENTORY.md`
- `docs/PROJECT_PROGRESS.md`

### 数据中心

- `services/quant-api/app/api/data_center.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/services/market_data_reader.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/app/data_sources/roles.py`
- `services/quant-api/app/data_sources/local_parquet_provider.py`
- `services/quant-api/app/data_sources/rqdata_provider.py`
- `services/quant-api/app/services/rqdata_ingest/`
- `scripts/rqdata_v1b_jm_asset.py`
- `scripts/rqdata_*`
- `data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_1d_20230103_20251231.parquet`
- `data/parquet/canonical/bars/provider=rqdata/period=15m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_15m_20230103_20251231.parquet`
- `data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_5m_20230103_20251231.parquet`
- `data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_1m_20230103_20251231.parquet`

### 策略

- `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/`
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/`
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/`
- `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/`
- `services/quant-api/app/strategy/su_bing_ema21.py`
- `docs/strategy_specs/su_bing_jm_v1b_short_hold/`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`

### 回测

- `services/quant-api/app/api/backtests.py`
- `services/quant-api/app/backtest/runner.py`
- `services/quant-api/app/backtest/service.py`
- `services/quant-api/app/backtest/v1b_jm_tasks.py`
- `services/quant-api/app/backtest/contract_resolver.py`
- `services/quant-api/app/backtest/jm_v1b_result_enricher.py`
- `services/quant-api/app/backtest/jm_daily_ema21_result_enricher.py`
- `services/quant-api/app/backtest/report_metrics.py`
- `services/quant-api/app/vnpy_integration/backtest_runner.py`
- `services/quant-api/app/vnpy_integration/result_converter.py`

### 报告

- `backtests/reports/report_5_jm_15m_trade_review.md`
- `backtests/reports/report_5_jm_15m_trade_review.csv`
- `backtests/reports/report_10_signal_funnel.md`
- `backtests/reports/report_10_su_bing_daily_trade_review.md`
- `backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_report_summary.md`
- `backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_trades.csv`
- `backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_orders.csv`
- `backtests/reports/su_bing_jm_daily_ema21_macd_volume/equity_curve.csv`
- `backtests/reports/su_bing_jm_daily_ema21_macd_volume/drawdown_curve.csv`
- `backtests/reports/su_bing_jm_daily_ema21_macd_volume/future_leakage_self_check.md`

### Web

- `apps/quant-web/src/app/router.ts`
- `apps/quant-web/src/api/backtestApi.ts`
- `apps/quant-web/src/api/data.ts`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/api/review.ts`
- `apps/quant-web/src/api/signal.ts`
- `apps/quant-web/src/pages/dashboard/index.vue`
- `apps/quant-web/src/pages/data/index.vue`
- `apps/quant-web/src/pages/market/index.vue`
- `apps/quant-web/src/pages/strategy/index.vue`
- `apps/quant-web/src/pages/backtest/index.vue`
- `apps/quant-web/src/pages/backtest/batch.vue`
- `apps/quant-web/src/pages/signal/index.vue`
- `apps/quant-web/src/pages/review/index.vue`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/src/utils/tradeMarker.ts`

### 测试

- `services/quant-api/tests/conftest.py`
- `services/quant-api/tests/test_health.py`
- `services/quant-api/tests/test_data_center_api.py`
- `services/quant-api/tests/test_market_data_api.py`
- `services/quant-api/tests/test_backtest_task_api.py`
- `services/quant-api/tests/test_backtest_service_runner.py`
- `services/quant-api/tests/test_vnpy_integration.py`
- `services/quant-api/tests/test_backtest_contract_resolver.py`
- `services/quant-api/tests/test_su_bing_jm_v1b_short_hold.py`
- `services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py`
- `services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`
- `services/quant-api/tests/test_signal_scanner_api.py`
- `services/quant-api/tests/test_review_center_api.py`
- `apps/quant-web/tests/indicators.test.ts`

### 任务队列

- `services/quant-api/app/queue.py`
- `services/quant-api/app/worker.py`
- `services/quant-api/app/tasks/backtests.py`
- `services/quant-api/app/tasks/signals.py`
- `services/quant-api/app/services/batch_backtest.py`
- `services/quant-api/app/services/signal_scanner.py`
- `scripts/dev-up.sh`
- `scripts/dev-down.sh`

### 数据库

- `services/quant-api/app/db/session.py`
- `services/quant-api/app/db/base.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/backtest.py`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/models/review.py`
- `services/quant-api/alembic.ini`
- `services/quant-api/alembic/env.py`
- `services/quant-api/alembic/versions/20260623_0001_data_center_v0.py`
- `services/quant-api/alembic/versions/20260624_0002_batch_backtest_v0.py`
- `services/quant-api/alembic/versions/20260624_0003_signal_scanner_v0.py`
- `services/quant-api/alembic/versions/20260624_0004_review_center_v0.py`
- `services/quant-api/alembic/versions/20260624_0005_rqdata_structured_ingest.py`
- `services/quant-api/alembic/versions/20260625_0006_market_data_file_symbol_unique.py`
- `services/quant-api/alembic/versions/20260625_0007_rqdata_contract_universe.py`
- `services/quant-api/alembic/versions/20260626_0008_vnpy_backtest_metadata.py`
- `services/quant-api/alembic/versions/20260626_0009_market_data_file_data_role.py`
- `services/quant-api/alembic/versions/20260627_0010_backtest_result_detail_tables.py`
- `services/quant-api/alembic/versions/20260628_0011_backtest_real_contract_cost_fields.py`
- `services/quant-api/alembic/versions/20260628_0012_backtest_result_v1_summary_trades.py`
