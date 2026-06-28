# 归一量化当前项目上下文

生成时间：2026-06-28  
工作区：`/Volumes/扩展盘/guiyi-quant-workstation`  
执行范围：只读审查 + 新增本文档。未修改业务代码、策略代码、数据库 schema、迁移、artifacts、环境变量或任何回测数据；未运行写库回测任务；未自动 commit。  
敏感信息处理：本文只描述配置项名称和本地服务角色，不输出任何真实账号、密码、API Key、token、license、米筐账号、天勤账号或 CTP 密码。

## 1. 项目一句话定位

归一量化当前是一个本地运行的国内期货量化研究工作台，核心服务对象是“V1 Web 研究闭环”：RQData / local standard parquet 数据、DuckDB 查询、vn.py CTA 回测、PostgreSQL 报告归档、Vue Web 展示、K线复盘、信号扫描和人工观察。

当前项目没有进入全自动实盘系统阶段。V1 不接 CTP / TqSdk 实盘交易接口，不做无人值守自动下单，不把信号直接转成委托。信号扫描当前只提醒和记录。

当前最核心研究品种是焦煤 JM。当前最核心策略是 `jm_v1b_daily_direction_fast_entry v1b.0`：日线只做方向过滤，15m / 5m 独立入场，持有 5-8 根本周期 K线，行情不利时按 ATR / 结构止损退出。当前阶段最重要目标不是扩多品种，而是把 JM V1-Final 的报告、交易、资金曲线、回撤曲线、Web 复盘口径彻底对齐。

## 2. 当前 git 状态

只读确认结果：

| 项目 | 当前状态 |
|---|---|
| 当前分支 | `main` |
| 与远端关系 | `main...origin/main` |
| 生成本文前工作区 | `git status --short --branch` 无未提交业务代码改动 |
| 最近 5 条 commit | `2247e780 bug 修改`、`b8f3c6dc bug 修复`、`fff3734e bug 修复`、`fa41ad97 修改 bug`、`aa555e55 web 报告页面增加` |
| 是否有未提交改动 | 生成本文后会出现 `docs/PROJECT_CONTEXT_FOR_CHATGPT.md` |
| 是否有未跟踪文件 | 本轮生成本文前未见未跟踪文件 |
| 当前是否适合继续开发 | 不建议直接在 `main` 上继续大改；建议先为下一任务创建 checkpoint 或新分支 |
| 是否建议 git checkpoint | 建议。尤其在修复 report 5/6 曲线口径前先保存当前审查文档 |

## 3. 项目目录结构

核心目录树：

```text
guiyi-quant-workstation/
├── apps/quant-web/          Vue 3 + Vite + TypeScript + Naive UI 前端工作台
├── services/quant-api/      FastAPI 后端、SQLAlchemy 模型、API、RQ worker、vn.py 集成
├── packages/quant-core/     策略与参数配置，当前含 JM V1-B 策略和苏冰 EMA21 草稿
├── strategies/              策略说明目录，含 su_bing_ema21 / ma_breakout / n_structure
├── scripts/                 本地开发、RQData/TqSdk 数据同步、审计、受控 backfill 脚本
├── docs/                    架构、路线图、交接、验收、进度和外部审查上下文
├── tasks/                   当前任务与任务流转
├── data/                    本地数据湖和报告数据；正式行情不应由文档任务修改
├── backtests/               回测导出报告与结果候选，目前有 report_id=5 复盘 CSV/Markdown
├── experiments/             RQData/vn.py demo 与样本验收实验
├── screenshots/             UI 截图存档目录，目前只有占位文件
└── prompts/                 Codex / ChatGPT / WorkBuddy 提示模板
```

职责说明：

- `apps/quant-web`：自定义 Web 工作台，负责 Dashboard、数据中心、K线、回测、批量回测、信号、复盘、设置等页面。核心计算不在前端完成。
- `services/quant-api`：FastAPI 后端，负责数据中心 API、MarketDataReader、回测任务、vn.py runner、报告入库、信号扫描、复盘 API、WebSocket。
- `packages/quant-core`：共享策略代码与参数 schema。当前 JM V1-B 策略在这里。
- `scripts`：数据同步、数据审计、受控修复和本地 dev 启停脚本。
- `docs`：当前项目事实、计划、验收和交接文档。存在少量历史口径滞后，需要统一。
- `artifacts`：仓库无顶层 `artifacts/` 目录；当前实际输出在 `backtests/reports/`、`data/reports/`、`screenshots/`。
- `tests`：后端测试在 `services/quant-api/tests/`，前端指标测试在 `apps/quant-web/tests/`。
- `migrations / alembic`：迁移位于 `services/quant-api/alembic/versions/`，当前 DB head 为 `20260628_0011`。

## 4. 技术栈现状

### 4.1 前端技术栈

基于 `apps/quant-web/package.json` 和源码确认：

- Vue 3：已使用。
- Vite：已使用，dev server 默认 `5173`。
- TypeScript：已使用。
- UI 库：Naive UI。
- K线图：TradingView Lightweight Charts。
- 统计图：ECharts / vue-echarts。
- 状态与路由：Pinia、Vue Router。
- API：Axios。

当前页面：

| 路由 | 页面 | 状态 |
|---|---|---|
| `/dashboard` | Dashboard | 仅原型，静态统计卡片 |
| `/data` | 数据中心 | 已对接 API |
| `/market` | K线工作台 | 部分完成，支持 report_id/trade_id marker 和定位 |
| `/strategy` | 策略中心 | 仅原型，空表格 |
| `/backtest` | 回测中心 | 部分完成，支持 report_id、报告详情、交易表、曲线、K线联动、复盘入口 |
| `/backtest/batch` | 批量回测 | 部分完成，支持批量任务和 WebSocket 进度框架 |
| `/signal` | 信号扫描 | 部分完成，JM V1-B 扫描可用 |
| `/review` | 复盘中心 | 部分完成，可从 trade 创建 note，可展示 K线和 marker |
| `/settings` | 系统设置 | 仅原型，未持久化 |

前端完成度：V1 研究闭环主页面已能串起来，但 Dashboard / Strategy / Settings 仍明显是壳；Web 报告页目前会使用后端曲线 API，因此 report_id=5/6 曲线表口径错误会直接影响 Web 展示可信度。

### 4.2 后端技术栈

基于 `services/quant-api/pyproject.toml`、模型和 API 文件确认：

- FastAPI：已使用。
- SQLAlchemy 2 / Alembic：已使用，当前 Alembic head 为 `20260628_0011`。
- PostgreSQL：已使用，当前本地容器 `guiyi-postgres` 正在运行。
- Redis / RQ：代码和容器均存在，当前 `guiyi-redis` 正在运行。
- WebSocket：存在 `/ws/backtests/{task_no}`、`/ws/signals`。
- API 路由结构：`data_center.py`、`market.py`、`backtests.py`、`signals.py`、`reviews.py`。

后端完成度：数据中心、回测任务、报告、交易明细、曲线、复盘、信号扫描等 V1 核心 API 已存在；仍需修正 report 5/6 的曲线和回撤口径。

### 4.3 数据层技术栈

当前行情和业务数据分层：

- PostgreSQL：元数据、任务、策略信号、回测报告、交易明细、曲线、复盘。
- Parquet：历史 K线和大体量行情数据。
- DuckDB：通过 MarketDataReader 查询 Parquet。
- RQData：V1 主数据源。
- TqSdk：保留 validation / V2 候选，不是 V1 主链路。
- legacy 数据：存在 `legacy_reference`，只用于对照或页面测试，不用于正式回测。

只读数据库统计：

| data_role | 文件数 |
|---|---:|
| `primary` | 23072 |
| `validation` | 9564 |
| `legacy_reference` | 382 |
| `candidate` | 4 |

JM primary/passed 数据：

| 周期 | 时间范围 | 行数 | data_version |
|---|---|---:|---|
| 1d | 2023-01-03 15:00:00 UTC 至 2025-12-31 15:00:00 UTC | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` |
| 15m | 2023-01-03 09:15:00 UTC 至 2025-12-31 15:00:00 UTC | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` |
| 5m | 2023-01-03 09:05:00 UTC 至 2025-12-31 15:00:00 UTC | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` |
| 1m | 2023-01-03 09:01:00 UTC 至 2025-12-31 15:00:00 UTC | 248535 | `rqdata_v1b_jm_1m_20230103_20251231_v1` |

数据质量：上述 primary 文件 `missing_bars=0`、`duplicated_bars=0`、`abnormal_price_count=0`、`abnormal_volume_count=0`。

数据层完成度：足够支持 JM V1-Final 数据验收；不等于回测报告曲线已可信。

### 4.4 回测与策略技术栈

- 当前使用 vn.py / VeighNa CTA BacktestingEngine。
- 自研封装位于 `services/quant-api/app/vnpy_integration/` 和 `services/quant-api/app/backtest/`。
- 回测任务通过 FastAPI 创建，RQ worker 或 inline 路径执行。
- 回测结果通过 `ResultConverter` 和 JM enricher 转为归一格式，再入库到 `backtest_reports`、`backtest_trades`、`backtest_orders`、`backtest_equity_curve`、`backtest_drawdown_curve`。
- 策略版本当前主要在代码、参数文件和 report 字段中管理；数据库中没有独立 `strategies` / `strategy_versions` 表。
- report_id=5/6 的 trade 级真实手续费、滑点、合约乘数、`price_tick`、保证金字段已入库。

完成度判断：回测执行、成本入库和 Web 查询主链路存在；但 report_id=5/6 的 equity/drawdown 曲线仍沿用旧口径，是当前 P0。

## 5. 数据中心当前能力

已实现能力：

- 合约表 / 品种表：`contracts`、`instruments` 已存在。
- K线数据读取：`MarketDataReader` 通过 PG 元数据定位 Parquet，并用 DuckDB 读取。
- 主连 / 主力合约处理：`main_contract_map` 存在，JM 有 6438 行映射。
- 数据下载：有 `data_download_tasks` 表和多个 RQData / TqSdk 同步脚本。
- 数据质量检查：`data_quality_reports` 存在，JM primary 数据为 passed。
- 缺失数据检查：质量报告包含 missing / duplicated / abnormal 字段。
- `price_tick` 来源：`futures_trading_parameters.price_tick` 优先，`fee_margin_rules.price_tick` 兜底；JM 2023-2025 已通过受控脚本补齐。
- `size` 来源：回测配置 / resolver 的 contract multiplier；JM trade 中 `contract_multiplier` 已非空。
- `margin_rate` 来源：`futures_trading_parameters` long/short margin 或 `fee_margin_rules.margin_rate`。
- `commission` 来源：`futures_trading_parameters` open/close/close_today commission 或 `fee_margin_rules`。

JM 交易参数统计：

| 项目 | JM 行数 |
|---|---:|
| `main_contract_map` | 6438 |
| `contracts` | 174 |
| `futures_trading_parameters` | 38522 |
| `futures_trading_parameters.price_tick non-null` | 8724 |
| `fee_margin_rules` | 38522 |
| `fee_margin_rules.price_tick non-null` | 8724 |

相关脚本：

| 脚本 | 用途 |
|---|---|
| `scripts/rqdata_v1b_jm_asset.py` | JM V1-B 标准数据资产处理 |
| `scripts/rqdata_trading_params_sync.py` | RQData 交易参数同步 |
| `scripts/rqdata_main_mapping_sync.py` | 主力映射同步 |
| `scripts/rqdata_contract_universe_sync.py` | 合约池同步 |
| `scripts/rqdata_coverage_audit.py` | 覆盖率审计 |
| `scripts/rqdata_field_audit.py` | 字段审计 |
| `scripts/backfill_jm_price_tick.py` | 受控补齐 JM `price_tick`，不覆盖已有非空值 |
| `scripts/tqsdk_*` | 天勤 validation / 候选数据链路，不是 V1 主链路 |

结论：数据中心足够支持 JM V1-Final 验收，但正式回测只能读取 `data_role=primary`、`quality_status=passed` 的 RQData / local parquet。validation / legacy_reference 不能混入正式报告。

## 6. 回测中心当前能力

回测链路：

```text
Web / API 创建回测任务
→ backtest_tasks 入库
→ RQ Worker 或 inline 执行
→ LocalParquetProvider / MarketDataReader 读标准 K线
→ VnpyBacktestRunner 调用 vn.py BacktestingEngine
→ ResultConverter 转统一结果
→ JM enricher 补实际合约、成本、保证金、换月/交割字段
→ backtest_reports / trades / orders / equity_curve / drawdown_curve 入库
→ FastAPI + Vue Web 查询展示
```

关键位置：

| 项 | 路径 |
|---|---|
| 回测入口 API | `services/quant-api/app/api/backtests.py` |
| 固定 JM 任务配置 | `services/quant-api/app/backtest/v1b_jm_tasks.py` |
| 回测 service | `services/quant-api/app/backtest/service.py` |
| RQ runner | `services/quant-api/app/backtest/runner.py` |
| vn.py runner | `services/quant-api/app/vnpy_integration/backtest_runner.py` |
| 结果转换 | `services/quant-api/app/vnpy_integration/result_converter.py` |
| JM 成本/实际合约补充 | `services/quant-api/app/backtest/jm_v1b_result_enricher.py` |
| 合约解析 | `services/quant-api/app/backtest/contract_resolver.py` |

是否真实调用 vn.py：是。`VnpyBacktestRunner` 创建 `BacktestingEngine`、注入 `history_data`、运行 `run_backtesting()`、`calculate_result()`、`calculate_statistics()`。

是否还有 prepared-only 或 mock：有。`prepared_only=true` 可用于配置校验；Dashboard 是 mock；legacy `/api/backtests/run` 仍存在自研 engine 路径。

字段计算现状：

| 字段 | 当前计算 / 风险 |
|---|---|
| report summary | `backtest_reports.summary` + 明细字段；report 5/6 的成本汇总与 trade 一致 |
| trade 明细 | `backtest_trades`，report 5/6 有真实合约、成本、保证金 |
| equity_curve | `backtest_equity_curve`；report 5/6 当前末值仍是旧未扣成本曲线，P0 |
| drawdown_curve | `backtest_drawdown_curve`；report 5/6 回撤 pct 与 report 字段不一致，P0 |
| 手续费 | report 5/6 trade 汇总与 report 汇总一致 |
| 滑点 | report 5/6 trade 汇总与 report 汇总一致 |
| gross_pnl | trade 级已入库 |
| net_pnl | trade 级已扣成本；report final_equity = initial_capital + sum(net_pnl) |
| margin_required | trade 级已入库，report 5/6 有 max_margin_required |

P0 证据：

| report_id | report final_equity | 100000 + sum(trade.net_pnl) | equity_curve 末值 |
|---:|---:|---:|---:|
| 5 | 89523.0100 | 89523.0100 | 151350.0070 |
| 6 | 91384.3676 | 91384.3676 | 362823.5110 |

结论：report 表和 trade 表已经对齐，但 equity_curve / drawdown_curve 仍是旧口径。Web 报告页调用曲线 API，因此当前 Web 曲线会误导 ChatGPT 或人工审查。

## 7. 策略中心当前能力

已有策略：

| 策略 | 路径 | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/` | 当前 JM V1-Final 核心策略，v1b.0 |
| `su_bing_ema21` | `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/` | vn.py 草稿和参数文件存在 |
| `ma_breakout` | `strategies/ma_breakout/README.md` | 策略方向文档 |
| `n_structure` | `strategies/n_structure/README.md` | 策略方向文档 |

JM V1-Final 当前固定策略：

- 策略名称：`jm_v1b_daily_direction_fast_entry`
- 策略版本：`v1b.0`
- 策略代码：`packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/vnpy_strategy.py`
- 参数 schema：`config_schema.py`
- 默认参数：`default_params.json`

策略能力：

| 能力 | 状态 |
|---|---|
| 日线方向过滤 | 已实现，`confirmed_daily_bar_effective_next_trading_day` |
| 15m / 5m 快速入场 | 已实现，`entry_interval` 可选 15m/5m |
| ATR 或结构止损 | 已实现 |
| `max_hold_bars` 出场 | 已实现，最大 8；止损可早于 5 根退出 |
| 真实成本 | 策略本身不算成本；enricher / resolver 在回测结果阶段补齐 |
| 真实合约字段 | report 5/6 的 trade 已补齐 |
| v1b.0 是否当前基准 | 是 |
| 是否有 v1b.1 | 未发现 |
| 策略版本 DB 记录 | 未发现独立 `strategies` / `strategy_versions` 表 |
| 策略 README | JM 策略目录未发现 README；苏冰 EMA21 有 README |

不确定或未完成：未看到“第 5-8 根之间按盈利或反向信号动态退出”的完整逻辑；当前主要退出是 `stop_loss_atr_or_structure` 和 `max_hold_bars_exit`。

## 8. Web 当前能力

| 页面 / 能力 | 路径 | 状态 | 说明 |
|---|---|---|---|
| Dashboard | `/dashboard` | 仅原型 | 静态卡片，未接真实 API |
| 数据中心 | `/data` | 部分完成 | 对接 sources/exchanges/instruments/contracts/tasks/quality/coverage |
| 合约 / 品种池 | `/data` | 部分完成 | 数据表可展示；管理能力有限 |
| K线页 / market 页 | `/market` | 部分完成 | 支持 coverage、bars、marker、report_id/trade_id |
| 回测任务页 | `/backtest` | 部分完成 | 支持任务列表、报告列表、详情 |
| 回测报告页 | `/backtest?report_id=5` | 部分完成 | report 表和交易表可看；曲线受 P0 影响 |
| 交易明细表 | `/backtest` | 已完成基础版 | 支持分页、筛选、导出 |
| 买卖点 marker | `/market`、`/backtest` 内嵌 K线 | 部分完成 | 从 trade 生成 open/close marker |
| `report_id` 参数 | `/backtest`、`/market` | 已完成基础版 | 可加载报告和联动 K线 |
| `trade_id` 参数 | `/market`、`/review` | 部分完成 | 可定位关联 trade |
| K线跳转定位 | `/market`、`/review` | 部分完成 | `focusTime()` 支持开/平仓定位 |
| 复盘窗口 | `/review` | 部分完成 | 可创建/更新 note，但人工标签和截图不足 |
| 策略中心 | `/strategy` | 仅原型 | 空表格 |
| 信号扫描 | `/signal` | 部分完成 | JM V1-B inline scan 已可用 |
| 复盘中心 | `/review` | 部分完成 | 有 note、tags、stats、K线 marker |

## 9. JM V1-Final 当前验收状态

数据层：JM 1d / 15m / 5m / 1m primary/passed 数据完整，足够支持 V1-Final 数据验收。

报告层：

| 项 | 状态 |
|---|---|
| 15m 报告 | 已生成，`report_id=5` |
| 5m 报告 | 已生成，`report_id=6` |
| 当前最新 15m report_id | 5 |
| 当前最新 5m report_id | 6 |
| report_id=5 | JM V1-Final 15m，trade 成本真实，曲线旧口径 |
| report_id=6 | JM V1-Final 5m，trade 成本真实，曲线旧口径 |
| 是否还有更新后的 report_id | 未发现 5/6 之后的新报告 |
| report_id=5/6 是否标记 invalid / diagnostic_only | DB 未标记；建议临时标为 diagnostic_only 或在 Web 明确提示 |
| report / trades 是否一致 | final_equity、成本、滑点、保证金汇总一致 |
| equity_curve / drawdown_curve 是否一致 | 不一致，P0 |

当前判断：JM V1-Final “数据 + 真实合约成本入库”已完成；“报告曲线 / 回撤 / Web 展示可信口径”未完成。不能把 report_id=5/6 直接作为策略效果或模拟盘准入依据。

## 10. report_id=5 JM 15m 交易复盘状态

只读数据库和 `backtests/reports/report_5_jm_15m_trade_review.md` 确认：

| 项 | 值 |
|---|---:|
| report_id | 5 |
| period | 15m |
| strategy | `jm_v1b_daily_direction_fast_entry v1b.0` |
| initial_capital | 100000 |
| final_equity(report) | 89523.01 |
| total_return(report) | -10.48% |
| trade_count | 127 |
| sum_gross_pnl(trades) | 397.27 |
| sum_net_pnl(trades) | -10476.99 |
| total_cost(trades) | 10874.26 |
| commission | 3254.26 |
| slippage | 7620.00 |
| win_rate(trades) | 40.16% |
| avg_win | 1017.57 |
| avg_loss | -820.70 |
| max_margin_required | 24996.00 |

按方向统计：

| 方向 | 笔数 | gross_pnl | net_pnl | 胜率 |
|---|---:|---:|---:|---:|
| long | 52 | 3925.97 | -570.74 | 42.31% |
| short | 75 | -3528.70 | -9906.25 | 38.67% |

按 exit_reason 统计：

| exit_reason | 笔数 | gross_pnl | net_pnl | 单笔均值 |
|---|---:|---:|---:|---:|
| `max_hold_bars_exit` | 71 | 51540.00 | 45636.53 | 642.77 |
| `stop_loss_atr_or_structure` | 56 | -51142.73 | -56113.52 | -1002.03 |

按日夜盘统计：

| 分组 | 笔数 | gross_pnl | net_pnl | 胜率 |
|---|---:|---:|---:|---:|
| day | 75 | -173.28 | -6881.44 | 41.33% |
| night | 52 | 570.55 | -3595.55 | 38.46% |

复盘产物状态：

| 项 | 状态 |
|---|---|
| 按月份统计 | 已生成在 Markdown / CSV |
| 最大亏损 20 笔 | 已生成 |
| 止损亏损 20 笔 | 已生成 |
| max_hold 盈利 20 笔 | 已生成 |
| CSV / Markdown | 已生成 |
| 是否接入 Web | 部分接入，Web 可看 trade 和 marker，但该 Markdown/CSV 不是 Web 页面原生数据集 |
| 点击 trade 定位 K线 | 前端已支持基础定位 |
| K线截图 | 未发现已生成截图文件 |
| enriched trade_review_dataset | 未发现独立 enriched dataset 文件；DB trade 有 enriched 字段 |

## 11. 当前 artifacts 和分析文件

| 文件 | 用途 | 是否最新 | 是否可继续使用 | 是否诊断样本 | 是否已接入 Web |
|---|---|---|---|---|---|
| `backtests/reports/report_5_jm_15m_trade_review.csv` | report 5 交易复盘表 | 是，针对 report 5 | 可用于人工复盘 | 是，分析样本 | 否 |
| `backtests/reports/report_5_jm_15m_trade_review.md` | report 5 复盘 Markdown | 是，针对 report 5 | 可用于 ChatGPT / 人工复盘 | 是，分析样本 | 否 |
| `docs/V1_FINAL_ACCEPTANCE.md` | V1-Final 验收记录 | 部分滞后 | 可参考，但需补充 P0 曲线问题 | 否 | 否 |
| `docs/PROJECT_CONTEXT_AFTER_V1_FINAL.md` | 上一次上下文整理 | 内部前后口径不一致 | 可参考历史 | 否 | 否 |
| `docs/PROJECT_FULL_CONTEXT_FOR_CHATGPT.md` | 旧全景上下文 | 已明显滞后 | 仅作历史参考 | 否 | 否 |
| `screenshots/.gitkeep` | 截图目录占位 | 不适用 | 无实际截图 | 否 | 否 |

未发现：

- `trade_review_dataset` 独立文件。
- enriched dataset 独立文件。
- `compare_summary`。
- report 5/6 K线截图。
- `manual_review_queue` 独立文件。

## 12. 数据库表结构和核心表

当前 public 表：

```text
alembic_version
backtest_drawdown_curve
backtest_equity_curve
backtest_orders
backtest_reports
backtest_tasks
backtest_trades
contracts
data_download_tasks
data_quality_reports
data_sources
exchanges
fee_margin_rules
futures_basis
futures_continuous_contract_map
futures_contract_universe
futures_ex_factors
futures_roll_yields
futures_trading_parameters
futures_warehouse_stocks
instruments
main_contract_map
market_data_files
review_attachments
review_notes
review_tags
signal_notifications
signal_scan_tasks
strategy_signals
trading_calendars
trading_sessions
watchlist_items
watchlists
```

核心表状态：

| 用户关心表 | 当前实际表名 / 状态 |
|---|---|
| contracts | 存在 |
| instruments | 存在 |
| market_data_files | 存在，实际使用 |
| data_quality_reports | 存在，实际使用 |
| strategies | 不存在独立表 |
| strategy_versions | 不存在独立表 |
| backtest_tasks | 存在，实际使用 |
| backtest_reports | 存在，实际使用 |
| backtest_trades | 存在，实际使用 |
| backtest_orders | 存在，实际使用 |
| backtest_daily_results | 不存在 |
| backtest_equity_curve | 存在，实际使用但 report 5/6 口径错误 |
| backtest_drawdown_curve | 存在，实际使用但 report 5/6 口径错误 |
| signals | 实际为 `strategy_signals` |
| review_notes | 存在，实际使用 |
| risk_profiles | 不存在 |

report_id=5/6 相关数据在：

- `backtest_reports`
- `backtest_trades`
- `backtest_orders`
- `backtest_equity_curve`
- `backtest_drawdown_curve`
- `backtest_tasks`

迁移文件存在于 `services/quant-api/alembic/versions/`，当前迁移版本为 `20260628_0011`。

## 13. API 路由清单

| method | path | 用途 | 前端调用 | 测试状态 |
|---|---|---|---|---|
| GET | `/health`、`/api/health` | 健康检查 | 启动验收 | 有 `test_health.py` |
| GET | `/api/dashboard/summary` | Dashboard mock summary | Dashboard 未实际调用 | mock |
| GET | `/api/v1/data/sources` | 数据源 | `/data` | 有数据中心测试 |
| GET | `/api/v1/data/exchanges` | 交易所 | `/data` | 有测试 |
| GET | `/api/v1/data/instruments` | 品种 | `/data` | 有测试 |
| GET | `/api/v1/data/contracts` | 合约 | `/data` | 有测试 |
| GET | `/api/v1/data/download-tasks` | 下载任务 | `/data` | 有测试 |
| GET | `/api/v1/data/quality-reports` | 质量报告 | `/data` | 有测试 |
| GET | `/api/v1/data/coverage` | 数据覆盖 | `/data` | 有测试 |
| GET | `/api/v1/market/workbench/coverage` | K线 coverage | `/market` | 有市场数据测试 |
| GET | `/api/v1/market/bars` | K线 bars | `/market`、`/backtest`、`/review` | 有测试 |
| POST | `/api/backtests/tasks` | 创建通用回测任务 | `/backtest` | 有测试 |
| POST | `/api/backtests/v1b/jm/{entry_interval}/tasks` | 创建 JM 固定任务 | API 可用 | 有测试 |
| POST | `/api/backtests/run` | legacy 同步回测 | legacy | 有旧测试 |
| POST | `/api/backtests/run-batch` | 批量回测 | `/backtest/batch` | 部分测试 |
| GET | `/api/backtests/tasks` | 任务列表 | `/backtest` | 有测试 |
| GET | `/api/backtests/tasks/{task_ref}` | 任务详情 | `/backtest` | 有测试 |
| GET | `/api/backtests/tasks/{task_no}/reports` | 任务报告 | `/backtest/batch` | 有测试 |
| GET | `/api/backtests/reports` | 报告列表 | `/backtest` | 有测试 |
| GET | `/api/backtests/reports/{report_id}` | 报告详情 | `/backtest` | 有测试 |
| GET | `/api/backtests/reports/{report_id}/trades` | 交易明细 | `/backtest`、`/market` | 有测试 |
| GET | `/api/backtests/reports/{report_id}/trades/export` | 交易导出 | `/backtest` | 有测试 |
| GET | `/api/backtests/reports/{report_id}/orders` | 订单 | `/backtest` API | 有测试 |
| GET | `/api/backtests/reports/{report_id}/equity-curve` | 资金曲线 | `/backtest` | 有测试，但当前数据 P0 |
| GET | `/api/backtests/reports/{report_id}/drawdown-curve` | 回撤曲线 | `/backtest` | 有测试，但当前数据 P0 |
| POST | `/api/signals/scan` | 通用扫描 | `/signal` | 有测试 |
| POST | `/api/signals/v1b/jm/scan` | JM V1-B 扫描 | `/signal` | 有测试 |
| GET | `/api/signals/latest` | 最新信号 | `/signal` | 有测试 |
| GET | `/api/signals/tasks/{task_no}` | 扫描任务 | `/signal` | 有测试 |
| GET | `/api/signals/tasks/{task_no}/signals` | 任务信号 | `/signal` | 有测试 |
| POST | `/api/signals/{signal_id}/ack` | 确认信号 | `/signal` | 有测试 |
| PATCH | `/api/signals/{signal_id}/status` | 更新信号状态 | `/signal` | 有测试 |
| GET | `/api/reviews/sources/backtest-trades` | 可复盘 trade | `/review`、`/backtest` | 有测试 |
| GET | `/api/reviews/sources/paper-trades` | 模拟/实盘来源预留 | `/review` | 当前空列表 |
| POST | `/api/reviews/from-backtest-trade/{trade_id}` | 从 trade 创建复盘 note | `/review`、`/backtest` | 有测试 |
| GET | `/api/reviews` | 复盘列表 | `/review` | 有测试 |
| GET | `/api/reviews/tags` | 标签 | `/review` | 有测试 |
| GET | `/api/reviews/stats` | 统计 | `/review` | 有测试 |
| GET | `/api/reviews/{review_id}` | 复盘详情 | `/review` | 有测试 |
| PUT | `/api/reviews/{review_id}` | 更新复盘 | `/review` | 有测试 |
| POST | `/api/reviews/{review_id}/attachments` | 附件 | `/review` | 有测试 |
| WS | `/ws/backtests/{task_no}` | 回测进度 | batch/backtest 预留 | 部分 |
| WS | `/ws/signals` | 信号推送 | signal 预留 | 部分 |

## 14. 前端页面和组件清单

| 文件路径 | 作用 | 完成度 | 依赖 API | 已知问题 |
|---|---|---|---|---|
| `apps/quant-web/src/pages/backtest/index.vue` | 回测任务、报告详情、曲线、交易表、K线联动、导出、复盘入口 | 部分完成 | `/api/backtests/*`、`/api/v1/market/bars`、`/api/reviews/*` | report 5/6 曲线来自错误曲线表 |
| `apps/quant-web/src/pages/market/index.vue` | K线页、report_id/trade_id marker、定位 | 部分完成 | market bars、backtest report/trades | 依赖曲线以外数据；无截图验收产物 |
| `apps/quant-web/src/pages/review/index.vue` | 复盘列表/详情/K线定位/标签 | 部分完成 | `/api/reviews/*`、market bars | 人工标签和截图为空 |
| `apps/quant-web/src/pages/signal/index.vue` | 信号扫描和最新信号 | 部分完成 | `/api/signals/*` | 当前真实样本均 no_signal |
| `apps/quant-web/src/pages/data/index.vue` | 数据中心 | 部分完成 | `/api/v1/data/*` | 管理/写入能力有限 |
| `apps/quant-web/src/pages/strategy/index.vue` | 策略中心 | 仅原型 | 无真实策略 API | 空表格 |
| `apps/quant-web/src/pages/dashboard/index.vue` | 仪表盘 | 仅原型 | 未接真实 summary | 静态数字 |
| `apps/quant-web/src/components/kline/KlineChart.vue` | Lightweight Charts K线、marker、hover、focusTime | 部分完成 | props | 需要浏览器截图验收 |
| `apps/quant-web/src/components/charts/BaseChart.vue` | ECharts 通用容器 | 已可用 | props | build 有 500k chunk warning |
| `apps/quant-web/src/api/backtestApi.ts` | 回测 API | 已可用 | 后端 backtests | 无 |
| `apps/quant-web/src/api/market.ts` | K线 API 和 report -> market query 归一 | 已可用 | market bars | 候选合约 fallback 逻辑复杂，需继续测 |
| `apps/quant-web/src/api/review.ts` | 复盘 API | 已可用 | reviews | 无 |

## 15. 测试与运行命令

后端：

```bash
cd services/quant-api
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
uv run python -m app.worker backtests
uv run python -m app.worker signals
uv run alembic upgrade head
uv run alembic current
uv run pytest -q
uv run ruff check .
```

前端：

```bash
cd apps/quant-web
pnpm install
pnpm dev --host 127.0.0.1 --port 5173
pnpm build
pnpm test:indicators
```

本地一键启动：

```bash
./scripts/dev-up.sh
./scripts/dev-down.sh
./scripts/dev-down.sh --keep-docker
```

回测：

```bash
# JM 15m 固定任务，注意：这是写库任务，本次未执行
curl -X POST 'http://127.0.0.1:8000/api/backtests/v1b/jm/15m/tasks'

# JM 5m 固定任务，注意：这是写库任务，本次未执行
curl -X POST 'http://127.0.0.1:8000/api/backtests/v1b/jm/5m/tasks'
```

导出 report_id=5 复盘表：

```bash
# API 已存在，可导出交易明细；当前 backtests/reports/report_5_jm_15m_trade_review.* 的生成脚本未在仓库中发现
curl -L 'http://127.0.0.1:8000/api/backtests/reports/5/trades/export?format=csv' -o backtests/reports/report_5_trades_export.csv
```

不存在或未发现：

- enriched dataset 生成命令：未发现。
- K线截图生成命令：未发现。
- 独立 `compare_summary` 生成命令：未发现。

## 16. 当前阻塞点

### P0

1. **report_id=5/6 的 report / trade 与 equity_curve / drawdown_curve 口径不一致。**  
   report 表 final_equity 与 trade net_pnl 汇总一致，但 equity_curve 末值仍是旧未扣真实成本结果：report 5 曲线末值 151350.0070，report final_equity 89523.0100；report 6 曲线末值 362823.5110，report final_equity 91384.3676。

2. **Web 报告页会使用错误曲线。**  
   前端 `backtest/index.vue` 调用 `/equity-curve` 和 `/drawdown-curve`，所以 report_id=5/6 在 Web 上展示的资金曲线 / 回撤曲线不可信。

3. **report_id=5/6 不应作为实盘、模拟盘或策略效果可信依据。**  
   它们可以作为“真实合约成本 trade 级入库成功”的诊断样本，但在曲线修复前不应作为最终策略效果报告。

### P1

1. `trade_review_dataset` 缺少独立 enriched 文件；目前只有 report 5 的 CSV/Markdown 和 DB trade 字段。
2. 人工复盘标签基本为空：`review_notes` 有 4 条，但 mistake/rule tags 均为空，lesson 为空。
3. K线页支持 trade 定位，但缺少截图级验收产物。
4. 未发现 v1b.1 设计文档。
5. 文档口径不一致：`README.md`、`tasks/current.md`、`PROJECT_CONTEXT_AFTER_V1_FINAL.md` 中部分内容仍把 3/4 或 5/6 的状态写混。

### P2

1. 5m 夜盘专项审查未做。
2. 样本外验证和参数稳定性未做。
3. 多品种扩展未做，当前也不建议优先做。
4. 信号扫描真实触发提醒未验证，当前 JM 结果为 no_signal。
5. Web 复盘体验仍需优化：人工标签、截图、复盘队列、K线窗口保存。

## 17. 下一步建议

1. **最应该先做什么**：修复 report_id=5/6 的 equity_curve / drawdown_curve 口径，使曲线从真实 net_pnl / 成本后权益生成，并让 report summary、trade 汇总、curve 末值、drawdown pct 全部一致。
2. **为什么**：当前 report 5/6 trade 级成本已经可信，但 Web 曲线会误导策略效果判断；这是 V1-Final 报告可信度 P0。
3. **Plan 模式还是直接执行**：建议 Codex 用 Plan 模式。涉及数据库事实、报告口径和 Web 展示，必须先写清允许修改文件、禁止修改文件、验收 SQL 和回滚方案。
4. **是否应该开新会话**：建议开新会话或新分支，避免文档整理上下文和修复任务混在一起。
5. **推荐分支名**：`codex/fix-v1-final-report-curves`
6. **允许修改范围**：`services/quant-api/app/backtest/`、`services/quant-api/app/vnpy_integration/`、`services/quant-api/tests/`、必要的前端展示提示文件、相关 docs。
7. **禁止修改范围**：`.env`、账号密钥、原始数据文件、Parquet 正式行情、vn.py 源码、旧 report_id=5/6 原始记录覆盖、实盘/CTP/TqSdk 交易逻辑。
8. **验收标准**：report 5/6 或新 report 的 `final_equity = initial_capital + sum(trade.net_pnl)`；equity_curve 首值为 initial_capital、末值等于 report final_equity；drawdown_curve pct 与 report max_drawdown_pct 口径一致；Web 报告显示正确曲线；新增回归测试覆盖。
9. **测试命令**：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py \
  services/quant-api/tests/test_backtest_task_api.py \
  services/quant-api/tests/test_backtest_service_runner.py
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```

10. **回滚建议**：先 checkpoint；修复任务尽量生成新 report_id 做对照，不覆盖 5/6；若必须修复历史曲线，先导出 `backtest_reports`、`backtest_trades`、`backtest_equity_curve`、`backtest_drawdown_curve` 中 report_id=5/6 的只读备份 SQL/CSV，由用户确认后再写库。

## 18. 给 ChatGPT 的摘要

归一量化当前是本地运行的国内期货量化研究工作台，不是公开 SaaS，也不是自动实盘系统。当前阶段围绕 V1 Web 研究闭环：RQData / local standard parquet 数据进入本地 Parquet 数据湖，PostgreSQL 保存元数据、任务、报告、交易明细、信号和复盘，DuckDB 负责批量读取 Parquet，vn.py / VeighNa CTA BacktestingEngine 负责 bar 级回测，FastAPI 提供查询和任务 API，Vue 3 + Vite + TypeScript + Naive UI Web 负责数据中心、K线、回测报告、交易明细、信号扫描和复盘展示。V1 明确不接全自动实盘，不让信号直接下单，TqSdk / CTP 只属于后续候选。

当前核心研究品种是焦煤 JM，核心策略是 `jm_v1b_daily_direction_fast_entry v1b.0`。策略使用日线只做方向过滤，15m 和 5m 独立入场，当前 bar 收盘后产生信号，下一根 K线开盘成交；持仓最长 8 根本周期 K线，行情不利时按 ATR / 结构止损提前退出。JM 1d、15m、5m、1m 数据已经以 `rqdata`、`primary`、`passed` 注册，范围为 2023-01-03 至 2025-12-31，质量报告 missing、duplicate、abnormal 均为 0。交易参数层面，JM 的 `price_tick` 曾经缺失，导致任务 10/11 失败；后来通过受控脚本补齐，report_id=5（15m）和 report_id=6（5m）已经生成，trade 级 `entry_contract`、`exit_contract`、`price_tick`、手续费、滑点、保证金均非空。

最关键的问题是：report_id=5/6 不能直接当作最终可信策略效果报告。数据库只读核验显示，report 表和 trade 表已经一致，例如 report 5 的 final_equity 是 89523.01，等于 100000 + sum(trade.net_pnl)，手续费 3254.26、滑点 7620.00、最大保证金 24996.00 也与 trade 汇总一致。但 equity_curve 仍是旧未扣成本/旧口径结果：report 5 的曲线末值是 151350.0070，而 report 表 final_equity 是 89523.0100；report 6 的曲线末值是 362823.5110，而 report 表 final_equity 是 91384.3676。drawdown_curve 的百分比口径也和 report 字段不一致。由于 Web 报告页调用 `/equity-curve` 和 `/drawdown-curve`，当前 Web 上 report 5/6 的资金曲线和回撤曲线会误导策略效果判断。

Web 方面，`/backtest` 支持通过 `report_id` 加载报告、交易明细、资金曲线、回撤曲线和内嵌 K线 marker；`/market` 支持通过 `report_id` 和 `trade_id` 显示买卖点并定位；`/review` 可以从 backtest trade 创建复盘 note，并展示 K线和 marker；`/signal` 可以运行 JM V1-B 扫描，当前最新 15m/5m 都是 `no_signal`，并且 `auto_order=false`、`signal_only=true`。Dashboard 和 Strategy 仍是明显原型，Settings 未持久化。

下一步最优先任务不是扩多品种、参数优化或实盘，而是修复 V1-Final 报告曲线口径：让 report summary、trade 汇总、equity_curve、drawdown_curve、Web 展示全部一致。建议新开 `codex/fix-v1-final-report-curves` 分支，用 Plan 模式执行，禁止覆盖旧 report_id=5/6，优先生成新 report 或只读备份后再处理历史曲线。验收标准是 equity_curve 首值等于 initial_capital、末值等于 report final_equity，drawdown pct 与 report max_drawdown_pct 口径一致，Web 报告显示正确曲线，并新增后端测试覆盖该一致性。

