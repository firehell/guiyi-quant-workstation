# PROJECT_FULL_CONTEXT_FOR_CHATGPT.md

> 生成时间：2026-06-28  
> 工作区：`/Volumes/扩展盘/guiyi-quant-workstation`  
> 用途：给外部 ChatGPT 做项目全景理解、架构审查、回测/风控审查和下一步建议。  
> 本文只描述当前仓库与本地数据库事实，不包含任何账号、密码、token、license、API Key、米筐账号、天勤账号或 CTP 信息。

## 1. 项目一句话定位

归一量化是一个本地运行的国内期货量化研究、数据、回测、报告、复盘、信号扫描和后期人工确认交易辅助工作台。

它不是公开 SaaS，不是普通营销网站，不是自动交易机器人，也不是第一版全自动实盘系统。当前重点是 V1 Web 研究闭环：数据中心、K线、策略、vn.py 回测、报告入库、Web 展示、单笔复盘、信号扫描和人工观察。

V1 明确不做无人值守自动实盘，不让信号直接下单，不接 CTP / TqSdk 交易接口作为当前主链路。

## 2. 当前阶段目标

当前阶段是：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

V1-B 的目标是围绕焦煤 JM 一个品种，用最近 3 年真实 RQData / local standard parquet 数据跑通研究闭环：

- JM 焦煤，当前冻结为单品种验收样板，不扩多品种。
- 最近 3 年真实数据，正式样本范围为 2023-01-03 至 2025-12-31。
- 日线只用于确定方向，不作为入场周期。
- 15m 可以独立入场，形成独立报告。
- 5m 可以独立入场，形成独立报告。
- 入场后持有 5-8 根当前周期 K线。
- 行情不利时按止损退出，止损可早于 5 根 K线发生。
- 回测报告必须入库并能在 Web 展示。
- K线上必须显示回测买卖点 marker。
- 单笔交易必须可以创建复盘 note。
- 信号扫描只提醒、解释和记录，不自动下单。

旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再是当前目标。

## 3. 当前技术栈

| 模块 | 当前技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios |
| 图表 | TradingView Lightweight Charts、Apache ECharts / vue-echarts |
| 后端 | Python 3.13、FastAPI、Pydantic / pydantic-settings |
| 数据库 | PostgreSQL、SQLAlchemy 2、Alembic |
| 数据文件 | Parquet、PyArrow，本地标准化数据湖 |
| 数据查询 | DuckDB、MarketDataReader |
| 数据源 | V1 主链路为 RQData / 米筐；Local Parquet 是正式本地数据湖 |
| 回测底座 | vn.py / VeighNa CTA BacktestingEngine，通过自定义 adapter / runner 调用 |
| 任务队列 | Redis + RQ，当前代码存在；当前本地证据显示仍需强化非 inline 联调 |
| 调度候选 | APScheduler / RQ Scheduler，当前不是 V1-B 验收核心 |
| 测试体系 | pytest、ruff、前端 `vue-tsc -b && vite build` |
| 代码规范 | ruff；mypy 在技术栈规划中，但本次验收未运行 mypy |

## 4. 当前目录结构

| 目录 | 作用 | 当前状态 |
|---|---|---|
| `apps/quant-web` | 自定义 Web 工作台，Vue 3 + Vite + TypeScript + Naive UI | 已有 data / market / backtest / signal / review 等页面，部分页面仍是壳子 |
| `services/quant-api` | FastAPI 后端、数据库模型、API、任务、数据读取、vn.py 集成 | V1-B 核心后端链路已存在 |
| `packages/quant-core` | 共享策略与参数配置，包含 vn.py 策略草稿和 JM V1-B 策略 | `jm_v1b_daily_direction_fast_entry` 可跑 |
| `strategies` | 策略说明目录 | 苏冰 EMA21、均线突破、N 字结构主要作为策略文档入口 |
| `docs` | 项目文档、架构、路线图、交接、验收记录 | 文档较完整，但少量历史文档口径不一致 |
| `data` | 本地数据湖，包含 raw / parquet / validation / legacy_reference 等数据 | 真实数据目录，不应由外部审查或文档任务修改 |
| `prompts` | Codex / ChatGPT / WorkBuddy 提示模板 | 已存在 |
| `tasks` | 当前任务和任务流转目录 | 已存在；`tasks/current.md` 曾与 V1-B 完成状态存在口径差异 |
| `experiments` | RQData、vn.py demo、样本验收脚本和输出 | 包含实验和验收用途，不等同于正式产品功能 |
| `backtests` | 回测输出和报告候选目录 | 不是当前报告权威事实库，正式报告以 PostgreSQL 为准 |

## 5. 数据系统当前状态

### 5.1 JM 正式数据

当前正式 JM V1-B 数据已经注册在 `market_data_files`，并位于项目约定的 canonical parquet 数据湖：

| 周期 | provider | data_type | data_role | quality_status | 时间范围 | 行数 |
|---|---|---|---|---|---|---:|
| 1d | rqdata | bars | primary | passed | 2023-01-03 15:00:00 UTC 至 2025-12-31 15:00:00 UTC | 727 |
| 15m | rqdata | bars | primary | passed | 2023-01-03 09:15:00 UTC 至 2025-12-31 15:00:00 UTC | 16569 |
| 5m | rqdata | bars | primary | passed | 2023-01-03 09:05:00 UTC 至 2025-12-31 15:00:00 UTC | 49707 |

对应 data_version：

- `rqdata_jm_standard_1d_20230103_20251231_v1`
- `rqdata_jm_standard_15m_20230103_20251231_v1`
- `rqdata_jm_standard_5m_20230103_20251231_v1`

这些数据的质量报告为 `passed`，`missing_bars=0`、`duplicated_bars=0`、`abnormal_price_count=0`、`abnormal_volume_count=0`。

### 5.2 支持周期

数据库中可见 JM 相关周期包括：

- 正式 V1-B：`1d`、`15m`、`5m`。
- RQData primary 还存在 `1m` 数据，范围 2023-01-03 至 2025-12-31，行数 248535。
- legacy / validation 数据中还存在 `30m`、`60m`、`120m` 等周期，但不作为 V1-B 正式回测默认数据。

### 5.3 数据来源分层

| 数据类别 | 当前角色 | 是否可用于 V1-B 正式回测 |
|---|---|---|
| RQData `bars` + canonical parquet + `primary/passed` | 正式数据 | 可以 |
| Local Parquet | 正式本地数据湖 | 可以，前提是 metadata 为 `primary/passed` |
| RQData `candidate` 样本 | 候选/样本 | 不默认作为正式报告依据 |
| RQData `market_sample` | 样本/实验数据 | 不等同正式 V1-B 报告数据 |
| TqSdk / 天勤旧数据 | validation | 只做交叉验证，不做默认正式回测 |
| trader_future_data | legacy_reference | 只做页面测试、历史参考或对照，不做正式回测 |
| mock | 前端或后端静态展示 | 不能写成真实功能完成 |

### 5.4 当前数据库关键记录数量

只读统计结果：

| 表 | 数量 |
|---|---:|
| `data_sources` | 4 |
| `exchanges` | 8 |
| `instruments` | 135 |
| `contracts` | 11185 |
| `watchlists` | 3 |
| `watchlist_items` | 16 |
| `market_data_files` | 33022 |
| `data_quality_reports` | 32102 |
| `fee_margin_rules` | 911831 |
| `main_contract_map` | 575156 |
| `futures_trading_parameters` | 911831 |

## 6. 合约 / 品种池 / 交易参数模型

### 6.1 模型是否存在

已存在的核心模型包括：

- `instruments`
- `contracts`
- `watchlists`
- `watchlist_items`
- `fee_margin_rules`
- `main_contract_map`
- `futures_trading_parameters`
- `market_data_files`
- `data_quality_reports`

### 6.2 JM 合约和主力映射

JM 主力映射相关数据存在：

- `main_contract_map` 全表记录数为 575156。
- JM 有 RQData `main_contract_mapping` 记录，`data_role=primary`、`quality_status=passed`。
- V1-B 研究回测使用 `jm.MAIN` 作为主力连续研究合约标识。

注意：`jm.MAIN` 是研究连续合约，不等同于实盘可直接下单合约。V1-B 不接实盘，因此当前不会把它转换成实盘委托。

### 6.3 交易参数位置

交易参数来源和配置分两层：

- 数据库层：`fee_margin_rules`、`futures_trading_parameters` 存储合约乘数、手续费、保证金、最小变动价位等交易基础字段。
- V1-B 固定任务配置层：`build_jm_v1b_task_config()` 中固定 `rate=0.0001`、`slippage=1.0`、`size=60`、`pricetick=0.5`、`capital=100000.0`。

重要缺口：当前正式报告 3/4 中 `total_commission=0.0`、`total_slippage=0.0`，说明成本字段落库或归因口径仍需加固，不能把成本口径写成完全验收。

### 6.4 当前是否只冻结为 JM

V1-B 是焦煤 JM 单品种闭环，不扩多品种。其他品种、watchlist 和合同数据存在，但不应被外部审查误解为 V1-B 已完成多品种批量研究闭环。

## 7. 策略系统当前状态

### 7.1 已有策略列表

当前可见策略或策略目录：

- `jm_v1b_daily_direction_fast_entry`：当前 V1-B 核心策略，位于 `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/`。
- `su_bing_ema21`：苏冰 EMA21 vn.py 策略草稿，位于 `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/`。
- `ma_breakout`：策略说明目录。
- `n_structure`：策略说明目录。

### 7.2 苏冰 EMA21 策略状态

苏冰 EMA21 已有 vn.py `CtaTemplate` 草稿、参数 schema、默认参数和 README。它是 V1 优先策略方向之一，但当前 V1-B 正式报告采用的是专门的 `jm_v1b_daily_direction_fast_entry`。

### 7.3 JM V1-B 策略状态

`jm_v1b_daily_direction_fast_entry` 是当前真实可跑策略：

- 策略代码：`packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/vnpy_strategy.py`
- 参数 schema：`packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/config_schema.py`
- 默认参数：`packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/default_params.json`
- API 固定任务配置：`services/quant-api/app/backtest/v1b_jm_tasks.py`

已支持：

- `entry_interval=15m` / `5m`
- 日线方向过滤
- `max_hold_bars_min=5`
- `max_hold_bars_max=8`
- `stop_loss_atr_multiple=1.5`
- ATR + 结构止损
- `entry_reason`
- `exit_reason`
- `hold_bars`
- `stop_loss_price`
- `daily_direction`

### 7.4 真实可跑与壳子区分

| 策略 | 当前状态 | 真实/壳子 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | 已用于 report_id 3/4 | 真实可跑 |
| `su_bing_ema21` | 有 vn.py 草稿和测试 | 可验证草稿，非 V1-B 正式报告策略 |
| `ma_breakout` | README/目录存在 | 策略方向/壳子 |
| `n_structure` | README/目录存在 | 策略方向/壳子 |

## 8. JM V1-B 策略逻辑细节

### 8.1 日线如何定方向

策略只使用当前入场 bar 交易日之前的已确认日线：

- 当前 intraday bar 的交易日为 `current_trading_day`。
- 日线过滤只取 `_bar_trading_day(daily_bar) < current_trading_day` 的日线。
- 最小日线窗口取日线 EMA、MACD、ATR、EMA 斜率所需窗口的最大值。

方向规则：

- `long`：最新已确认日线 close > EMA21，EMA 斜率向上，DIF >= DEA，且不是过近或过远状态。
- `short`：最新已确认日线 close < EMA21，EMA 斜率向下，DIF <= DEA，且不是过近或过远状态。
- `neutral`：价格靠近 EMA21、距离 EMA21 过远、EMA 斜率过平或条件冲突。
- `unavailable`：日线数量不足或 ATR 无效。

日线方向生效策略为：

```text
confirmed_daily_bar_effective_next_trading_day
```

### 8.2 多头条件

在日线方向为 `long` 时，入场周期满足：

- 当前 close > entry EMA。
- 近几根 K线曾回踩或接近 EMA。
- 当前 close 突破前一根 high，或 MACD 出现金叉。
- DIF > DEA，或当前形成金叉。
- 当前成交量满足周期对应量能阈值。
- 当前 close 距 EMA 不超过 ATR 限制。

入场原因：

```text
daily_long_ema21_pullback_macd_confirmed
```

### 8.3 空头条件

在日线方向为 `short` 时，入场周期满足：

- 当前 close < entry EMA。
- 近几根 K线曾反抽或接近 EMA。
- 当前 close 跌破前一根 low，或 MACD 出现死叉。
- DIF < DEA，或当前形成死叉。
- 当前成交量满足周期对应量能阈值。
- 当前 close 距 EMA 不超过 ATR 限制。

入场原因：

```text
daily_short_ema21_pullback_macd_confirmed
```

### 8.4 禁止交易条件

以下情况不入场：

- 日线方向为 `neutral` 或 `unavailable`。
- 入场周期预热 bar 数不足。
- ATR 无效。
- 量能不足。
- close 距 EMA 太远。
- 多空条件不满足。
- 下一根开盘直接穿越止损，策略会跳过入场。

### 8.5 15m / 5m 如何入场

15m 和 5m 是两条独立入场链路：

- API 固定入口分别是 `POST /api/backtests/v1b/jm/15m/tasks` 和 `POST /api/backtests/v1b/jm/5m/tasks`。
- 两者都使用 1d 作为辅助日线过滤。
- 两者分别形成独立 backtest task、report、trades 和 K线 marker。
- 15m 的 `volume_multiplier` 使用 `volume_multiplier_15m=1.0`。
- 5m 的 `volume_multiplier` 使用 `volume_multiplier_5m=1.1`。

### 8.6 信号生成时点和成交时点

策略口径：

```text
signal_on_close_fill_next_bar_open
```

实际逻辑：

- 当前 bar 收盘后判定入场或退出信号。
- 生成 pending order。
- 下一根 bar 开盘执行入场或退出。

这避免了“当前 bar 产生信号，却用当前 bar 开盘成交”的未来函数问题。

### 8.7 初始止损如何计算

多头止损：

- ATR 止损：`current_close - ATR * stop_loss_atr_multiple`
- 结构止损：近 `structure_stop_lookback_bars` 根 low 的最低值减 `stop_buffer_ticks * pricetick`
- 实际止损取更靠近当前价的一侧：`max(atr_stop, structure_stop)`

空头止损：

- ATR 止损：`current_close + ATR * stop_loss_atr_multiple`
- 结构止损：近 `structure_stop_lookback_bars` 根 high 的最高值加 buffer
- 实际止损取更靠近当前价的一侧：`min(atr_stop, structure_stop)`

因此当前实现同时使用 ATR 止损和结构止损。

### 8.8 时间退出和第 5-8 根 K线处理

当前实现中：

- `max_hold_bars_min` 被参数校验固定为 5。
- `max_hold_bars_max` 被参数校验固定为 8。
- 止损可以在 1-4 根时提前退出。
- 未触发止损时，达到第 8 根后安排下一根开盘退出，`exit_reason=max_hold_bars_exit`。

当前代码没有看到“第 5-8 根之间按盈利或反向信号选择退出”的完整动态逻辑；已落库交易显示持仓范围为 1-8，其中小于 5 的交易来自止损提前退出。

### 8.9 反向信号是否退出

当前实现主要退出方式是：

- `stop_loss_atr_or_structure`
- `max_hold_bars_exit`

未看到已实现的反向信号主动退出规则。因此不能把“反向信号退出”写成已完成能力。

## 9. 回测系统当前状态

### 9.1 是否使用 vn.py

是。`VnpyBacktestRunner` 确实调用 vn.py CTA `BacktestingEngine`：

- 创建 `BacktestingEngine`
- `set_parameters`
- `add_strategy`
- 注入 `history_data`
- `run_backtesting`
- `calculate_result`
- `calculate_statistics`

数据通过标准 Parquet 读入后注入 vn.py，不调用实盘 gateway，不修改 vn.py 源码。

### 9.2 vn.py adapter / runner 路径

核心路径：

- `services/quant-api/app/vnpy_integration/backtest_runner.py`
- `services/quant-api/app/vnpy_integration/result_converter.py`
- `services/quant-api/app/vnpy_integration/strategy_loader.py`
- `services/quant-api/app/vnpy_integration/symbol_mapper.py`
- `services/quant-api/app/backtest/service.py`
- `services/quant-api/app/backtest/runner.py`
- `services/quant-api/app/tasks/backtests.py`

### 9.3 回测任务 API

主要 API：

- `POST /api/backtests/tasks`
- `GET /api/backtests/tasks`
- `GET /api/backtests/tasks/{task_ref}`
- `POST /api/backtests/v1b/jm/{entry_interval}/tasks`
- `GET /api/backtests/reports`
- `GET /api/backtests/reports/{report_id}`
- `GET /api/backtests/reports/{report_id}/trades`
- `GET /api/backtests/reports/{report_id}/orders`
- `GET /api/backtests/reports/{report_id}/equity-curve`
- `GET /api/backtests/reports/{report_id}/drawdown-curve`

### 9.4 RQ worker 和 Redis 状态

代码存在：

- `services/quant-api/app/queue.py`
- `services/quant-api/app/tasks/backtests.py`
- `services/quant-api/app/tasks/signals.py`
- `services/quant-api/app/worker.py`
- WebSocket 通过 Redis Pub/Sub 推送任务和信号快照。

但当前只读证据显示：

- 当前 `docker ps` 只看到 `guiyi-postgres` 运行，没有看到 Redis 容器。
- `signal_scan_tasks` 中有一条失败任务，错误为 Redis 连接 127.0.0.1:6379 被拒绝。
- JM V1-B 信号扫描成功样本使用 `run_inline=true`。

结论：任务队列封装存在，后端 API 会尝试入队；但当前本地环境中 Redis/RQ 非 inline 真实联调证据不足，应列为 P1。

### 9.5 固定 JM V1-B 任务入口

已存在：

- `POST /api/backtests/v1b/jm/15m/tasks`
- `POST /api/backtests/v1b/jm/5m/tasks`

接口会检查 JM V1-B 1d + 入场周期正式数据是否存在、是否 `primary/passed`、文件是否在磁盘上存在。

### 9.6 错误记录

`backtest_tasks` 有 `error_type`、`error_message`、`traceback` 字段。

当前任务记录：

- 7 个 backtest task。
- 其中 report 3/4 对应成功任务。
- 曾有 `StrategyLoadError` 失败任务。
- 曾有 `ManualInterrupt` 失败任务。

## 10. 回测结果和数据库入库状态

### 10.1 表是否存在

已存在：

- `backtest_reports`
- `backtest_trades`
- `backtest_orders`
- `backtest_equity_curve`
- `backtest_drawdown_curve`

当前记录数量：

| 表 | 数量 |
|---|---:|
| `backtest_tasks` | 7 |
| `backtest_reports` | 4 |
| `backtest_trades` | 454 |
| `backtest_orders` | 740 |
| `backtest_equity_curve` | 1940 |
| `backtest_drawdown_curve` | 1940 |

### 10.2 当前报告列表

| report_id | 类型 | strategy_code | period | trades | 说明 |
|---:|---|---|---|---:|---|
| 1 | smoke | `vnpy_smoke_round_trip` | 5m | 2 | smoke report，不是正式 V1-B |
| 2 | smoke | `vnpy_smoke_round_trip` | 15m | 2 | smoke report，不是正式 V1-B |
| 3 | 正式 V1-B | `jm_v1b_daily_direction_fast_entry` | 15m | 127 | V1-B 15m report |
| 4 | 正式 V1-B | `jm_v1b_daily_direction_fast_entry` | 5m | 323 | V1-B 5m report |

### 10.3 V1-B 报告指标

| report_id | entry interval | initial_capital | final_equity | total_return | annual_return | max_drawdown | win_rate | profit_loss_ratio | max_consecutive_losses | commission | slippage |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 15m | 100000.0 | 151350.0070 | 0.5135000700 | 0.0 | 452714.6910 | 0.4330708661 | 1.0070937937 | 8 | 0.0 | 0.0 |
| 4 | 5m | 100000.0 | 362823.5110 | 2.6282351100 | 0.0 | 1257709.1220 | 0.4829721362 | 1.3476551196 | 6 | 0.0 | 0.0 |

### 10.4 交易明细字段

V1-B reports 已有：

- `hold_bars` / `holding_bars`
- `entry_interval`
- `entry_reason`
- `exit_reason`
- `stop_loss_price`
- `daily_direction`
- `raw_payload`

字段统计：

| report_id | trades | min_hold | max_hold | entry_reason count | exit_reason count | raw_payload count |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 127 | 1 | 8 | 127 | 127 | 127 |
| 4 | 323 | 1 | 8 | 323 | 323 | 323 |

### 10.5 曲线

| report_id | equity points | drawdown points |
|---:|---:|---:|
| 1 | 243 | 243 |
| 2 | 243 | 243 |
| 3 | 727 | 727 |
| 4 | 727 | 727 |

### 10.6 报告口径缺口

当前只有工程闭环完成，报告口径仍需加固：

- `annual_return` 当前为 0.0。
- `total_commission` 当前为 0.0。
- `total_slippage` 当前为 0.0。
- `max_drawdown` 当前记录为金额字段，Web 需要同时明确金额 / 百分比口径。
- 当前报告结果不等于策略可实盘，不等于可进入模拟盘。

## 11. Web 前端当前状态

Web 技术栈：Vue 3 + Vite + TypeScript + Naive UI + Pinia + Vue Router + Axios + Lightweight Charts + ECharts。

当前路由：

- `/dashboard`
- `/data`
- `/market`
- `/strategy`
- `/backtest`
- `/backtest/batch`
- `/signal`
- `/review`
- `/settings`

页面真实度：

| 页面 | 当前状态 | 真实/Mock |
|---|---|---|
| Dashboard | 静态统计数字，页面文案写明待对接后端 API；后端 `/api/dashboard/summary` 返回 `data_status=mock` | mock / 壳子 |
| Data | 调用 data API 展示 sources、exchanges、instruments、contracts、tasks、quality reports、coverage | 真实接 API |
| Market | 调用 market bars / coverage API，可联动 report trades 生成 marker | 真实接 API |
| Strategy | 空表和“新建策略”按钮，未看到真实策略管理闭环 | 壳子 |
| Backtest | 调用报告、交易、订单、资金曲线、回撤曲线 API，支持 JM V1-B report_id | 真实接 API |
| Backtest Batch | 批量回测页面存在，需区分其与 V1-B 固定任务 | 部分真实 |
| Signal | 调用信号扫描、latest signals、task signals、ack/status API | 真实接 API |
| Review | 调用复盘 sources、reviews、tags、stats、update API | 真实接 API |
| Settings | 表单壳子，未看到持久化设置 API | 壳子 |

## 12. K线工作台当前状态

### 12.1 图表与数据

K线组件使用 TradingView Lightweight Charts。后端 `MarketDataReader` 使用 DuckDB 读取 canonical Parquet。

市场工作台 API：

- `GET /api/v1/market/workbench/coverage`
- `GET /api/v1/market/bars`

前端 Market 页面会：

- 获取 coverage。
- 选择 symbol / contract / period。
- 读取 bars。
- 展示质量摘要。
- 通过 report_id 加载 backtest report 和 trades。
- 将 trades 转成 K线 marker。

### 12.2 支持指标

前端 KlineChart 支持：

- K线。
- EMA21。
- MACD。
- ATR。
- 回测买卖点 marker。

### 12.3 买卖点 marker 来源

当前 marker 来自回测交易明细：

- `GET /api/backtests/reports/{report_id}/trades`
- 前端把每笔 trade 的开仓、平仓时间和价格转成 marker。

### 12.4 15m / 5m 展示

15m 和 5m 可分别通过 report_id 展示：

- `report_id=3` 对应 15m。
- `report_id=4` 对应 5m。

### 12.5 缺口

- 本次未做浏览器截图级 UI smoke。
- 未验证所有 viewport 下 marker、指标、tooltip 是否无重叠。
- 未验证真实触发信号与 K线工作台联动。

## 13. 回测报告 Web 展示状态

Web 回测页已接 API，可显示：

- 报告列表。
- 报告详情。
- `report_id=3` / `report_id=4`。
- 15m / 5m 区分。
- 资金曲线。
- 回撤曲线。
- 交易明细。
- `entry_reason`。
- `exit_reason`。
- `hold_bars`。
- K线 marker。
- 跳转 K线复盘。

缺口：

- 报告口径中的年化收益、手续费、滑点仍需修正。
- 最大回撤金额和百分比显示需进一步明确。
- `report_id=1/2` 是 smoke，不应与正式 V1-B 报告混为一谈。

## 14. 复盘中心当前状态

### 14.1 表和 API

已存在：

- `review_notes`
- `review_tags`
- `review_attachments`

API：

- `GET /api/reviews/sources/backtest-trades`
- `POST /api/reviews/from-backtest-trade/{trade_id}`
- `GET /api/reviews`
- `GET /api/reviews/{review_id}`
- `PUT /api/reviews/{review_id}`
- `GET /api/reviews/tags`
- `GET /api/reviews/stats`

### 14.2 当前数量和样本

只读统计：

- `review_notes`：1
- `review_tags`：29

当前复盘 note：

- `review_id=1`
- `source_type=backtest_trade`
- `source_id=5`
- `report_id=3`
- `trade_id=5`
- `symbol=jm`
- `contract=jm.MAIN`
- `period=15m`
- `strategy_name=jm_v1b_daily_direction_fast_entry`
- `strategy_version=v1b.0`
- `open_time=2023-03-01 09:30:00 UTC`
- `close_time=2023-03-01 13:45:00 UTC`
- `hold_bars=8`
- `entry_reason=daily_long_ema21_pullback_macd_confirmed`
- `exit_reason=max_hold_bars_exit`

### 14.3 当前完成度

复盘中心已能从 backtest trade 创建 note，并关联 report/trade/symbol/entry/exit 信息。当前更准确地说是“单笔回测复盘闭环已打通，有一个样本”，还不是完整成熟的复盘体系。

缺口：

- 复盘样本只有 1 条。
- 未做浏览器级复盘编辑和保存 smoke。
- 截图附件、AI summary 等字段是预留，不是当前 V1-B 完成能力。

## 15. 信号扫描当前状态

### 15.1 后端和表

已存在：

- `signal_scan_tasks`
- `strategy_signals`
- `signal_notifications`

当前数量：

- `signal_scan_tasks`：2
- `strategy_signals`：2
- `signal_notifications`：0

### 15.2 JM V1-B 扫描入口

固定入口：

```text
POST /api/signals/v1b/jm/scan?run_inline=true
```

当前成功任务：

- `task_no=SIG-JM-V1B-20260627164705-de1e8889`
- `status=completed`
- `periods=['15m', '5m']`
- `completed_items=2`
- `failed_items=0`

### 15.3 当前信号结果

| id | period | status | direction | daily_direction | no_signal_reason | auto_order |
|---:|---|---|---|---|---|---|
| 1 | 15m | no_signal | neutral | neutral | `daily_direction_blocked|daily_close_near_ema21_neutral` | false |
| 2 | 5m | no_signal | neutral | neutral | `daily_direction_blocked|daily_close_near_ema21_neutral` | false |

信号字段已包含：

- `daily_direction`
- `entry_reason`
- `no_signal_reason`
- `stop_loss_price`
- `max_hold_bars`
- `data_role`
- `signal_only=true`
- `auto_order=false`

### 15.4 WebSocket 状态

WebSocket 代码存在：

- `/ws/signals`
- `/ws/backtests/{task_no}`

它们依赖 Redis Pub/Sub。当前本地 Redis/RQ 非 inline 联调证据不足，需要单独 smoke。

### 15.5 自动下单确认

当前 V1-B 信号扫描只提醒和记录：

- `auto_order=false`
- `signal_only=true`
- `open_volume=0`
- 未看到任何自动下单、CTP 发单或 TqSdk 发单逻辑进入 V1-B 信号路径。

## 16. API 当前状态

| API 类别 | 路径 | 用途 | 测试/真实度 |
|---|---|---|---|
| health | `GET /health`、`GET /api/health` | 服务健康检查 | 真实 |
| dashboard | `GET /api/dashboard/summary` | 仪表盘摘要 | mock，返回 `data_status=mock` |
| data | `/api/v1/data/sources`、`/exchanges`、`/instruments`、`/contracts`、`/download-tasks`、`/quality-reports`、`/coverage` | 数据中心元数据 | 真实接 DB |
| compat market | `/api/symbols`、`/api/klines` | 兼容旧前端接口 | 真实读取 DB / Parquet |
| market | `/api/v1/market/workbench/coverage`、`/api/v1/market/bars` | K线工作台 coverage 和 bars | 真实读取 DB / DuckDB / Parquet |
| watchlists | `/api/watchlists`、`/api/watchlists/{code}/items` | 品种池 | 真实接 DB，可能会 ensure 默认 watchlists |
| backtest tasks | `/api/backtests/tasks`、`/api/backtests/v1b/jm/{entry_interval}/tasks` | 回测任务创建/查询 | 真实接 DB / RQ |
| backtest reports | `/api/backtests/reports`、`/reports/{id}`、`/trades`、`/orders`、`/equity-curve`、`/drawdown-curve` | 报告展示 | 真实接 DB |
| signal | `/api/signals/scan`、`/api/signals/v1b/jm/scan`、`/api/signals/latest`、`/api/signals/tasks/{task_no}` | 信号扫描和展示 | 真实接 DB；JM 成功样本为 inline |
| review | `/api/reviews/*` | 单笔复盘 | 真实接 DB |
| settings | 未看到完整后端 settings API | 系统设置 | 前端壳子 |
| websocket | `/ws/backtests/{task_no}`、`/ws/signals` | 状态推送 | 代码存在，依赖 Redis，需联调 |

## 17. 数据库模型和迁移

### 17.1 当前 Alembic head

当前只读命令结果：

```text
20260627_0010 (head)
```

迁移文件包括：

- `20260623_0001_data_center_v0.py`
- `20260624_0002_batch_backtest_v0.py`
- `20260624_0003_signal_scanner_v0.py`
- `20260624_0004_review_center_v0.py`
- `20260624_0005_rqdata_structured_ingest.py`
- `20260625_0006_market_data_file_symbol_unique.py`
- `20260625_0007_rqdata_contract_universe.py`
- `20260626_0008_vnpy_backtest_metadata.py`
- `20260626_0009_market_data_file_data_role.py`
- `20260627_0010_backtest_result_detail_tables.py`

### 17.2 核心表列表

实际使用较多：

- 数据中心：`data_sources`、`exchanges`、`instruments`、`contracts`、`market_data_files`、`data_quality_reports`
- RQData 结构化：`main_contract_map`、`futures_trading_parameters`、`fee_margin_rules`
- 回测：`backtest_tasks`、`backtest_reports`、`backtest_trades`、`backtest_orders`、`backtest_equity_curve`、`backtest_drawdown_curve`
- 信号：`signal_scan_tasks`、`strategy_signals`
- 复盘：`review_notes`、`review_tags`
- 品种池：`watchlists`、`watchlist_items`

预留或当前样本较少：

- `signal_notifications` 当前 0。
- `review_attachments` 当前未见样本。
- AI summary 相关字段在 review note 中是预留。

### 17.3 seed 数据

watchlist 有默认数据逻辑，`ensure_default_watchlists()` 会在 API 调用时确保默认 watchlists。当前 `watchlists=3`，`watchlist_items=16`。

## 18. 任务队列状态

代码中 Redis/RQ 封装存在：

- backtest queue
- signal queue
- worker 函数
- WebSocket Pub/Sub

启动命令参考：

```bash
docker compose up -d
uv run --project services/quant-api uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
uv run --project services/quant-api python -m app.worker
cd apps/quant-web && pnpm dev --host 127.0.0.1 --port 5173
```

当前事实：

- 当前只读环境只看到 PostgreSQL 容器运行。
- 一条信号任务曾因 Redis 连接失败而失败。
- JM V1-B 信号成功样本使用 `run_inline=true`。
- 回测任务 API 会尝试 enqueue，失败会记录 `RQUnavailable`。

结论：任务队列代码路径存在，HTTP 创建任务和错误记录存在；当前仍需要一次完整 Redis/RQ worker 非 inline 联调作为 V1-B.1 验收项。

## 19. 测试体系

本次验证命令结果：

```bash
uv run --project services/quant-api pytest -q
# 153 passed in 17.34s
```

```bash
uv run --project services/quant-api ruff check .
# All checks passed!
```

```bash
cd apps/quant-web && pnpm build
# vue-tsc -b && vite build passed
# warning: BaseChart-Z2_qqnFf.js 501.85 kB
```

```bash
cd services/quant-api && uv run alembic current
# 20260627_0010 (head)
```

测试覆盖方向包括：

- health API。
- data center API。
- data source role。
- MarketDataReader。
- RQData ingest。
- vn.py integration。
- JM V1-B 策略规则。
- V1-B 固定 backtest tasks。
- signal scanner API。
- review center API。
- backtest API。

仍缺：

- 浏览器截图级 UI smoke。
- Redis/RQ worker 非 inline 端到端测试。
- 真实触发入场信号的 signal Web 展示样本。
- 报告成本、年化收益、回撤百分比口径回归测试。

## 20. 当前真实完成度表

| 模块 | 状态 | 真实/Mock | 说明 | 缺口 |
|---|---|---|---|---|
| 数据系统 | 已有正式 JM V1-B 数据 | 真实 | RQData primary/passed，1d/15m/5m 已注册 | 数据口径需持续防止 validation/legacy 混入 |
| 合约 / 品种池 | 模型和数据存在 | 真实 | contracts、watchlists、main_contract_map 存在 | V1-B 只冻结 JM，多品种闭环未验收 |
| K线工作台 | 已接 API 和 marker | 真实为主 | Lightweight Charts + MarketDataReader + trades marker | 未做浏览器级 smoke |
| 策略中心 | 策略代码存在，Web 策略页为空表 | 混合 | JM V1-B 策略真实可跑 | Web 策略管理仍是壳子 |
| JM V1-B 策略 | 已跑 report 3/4 | 真实 | 日线方向、15m/5m、止损、8 根退出 | 反向信号退出未见实现 |
| vn.py 回测 | Runner 真实调用 BacktestingEngine | 真实 | 注入 standard bars，不走实盘 gateway | 成本字段归档需审查 |
| 回测任务 | 任务模型/API 存在 | 真实 | 固定 JM V1-B 任务入口存在 | Redis/RQ 非 inline 联调不足 |
| 回测报告 | report 3/4 入库 | 真实 | reports/trades/orders/curves 均有记录 | 年化、手续费、滑点、回撤百分比待加固 |
| 回测入库 | 已入库 | 真实 | detail tables 有数据 | raw/normalized path 未持久化，当前 DB 内存储为主 |
| Web 报告 | 已接报告 API | 真实 | 可展示列表、详情、曲线、交易 | 未做浏览器级 UI 验收 |
| K线复盘 | 可从 trades 生成 marker，review 有样本 | 真实但样本少 | review_id=1 | 复盘样本少，附件/AI 字段未完成 |
| 信号扫描 | JM V1-B inline 扫描成功 | 真实 | 15m/5m no_signal，auto_order=false | 缺真实触发信号样本，非 inline 需联调 |
| 后端 API | 核心 API 存在 | 真实为主 | data/market/backtest/signal/review 接 DB | dashboard mock，settings 不完整 |
| 数据库模型 | 迁移到 head | 真实 | `20260627_0010 (head)` | 仍需防止开发库漂移 |
| 任务队列 | 封装存在 | 部分真实 | 代码路径完整 | 当前 Redis/RQ 环境证据不足 |
| 测试体系 | 后端和前端 build 通过 | 真实 | 153 passed，ruff/build passed | 缺浏览器 smoke 和 worker e2e |
| 文档体系 | 较完整 | 真实但有矛盾 | 多份 V1-B 文档存在 | 少量历史口径不一致，需以本文件和 DB 为准 |

## 21. 当前 P0 / P1 / P2 缺口

### P0：影响 V1-B 闭环验收，必须马上修

1. 报告成本和年化口径不完整  
   涉及文件：`services/quant-api/app/vnpy_integration/result_converter.py`、`services/quant-api/app/backtest/service.py`、前端报告展示。  
   重要性：V1-B 报告 3/4 的 `annual_return`、`total_commission`、`total_slippage` 仍为 0.0，容易误导策略评估。  
   建议：统一年化收益计算、手续费/滑点归集、回撤金额/百分比字段，并补测试。  
   是否需要新 Codex 会话：建议需要，独立任务。

2. 浏览器级 Web smoke 未完成  
   涉及文件：`apps/quant-web/src/pages/backtest/index.vue`、`market/index.vue`、`review/index.vue`、`signal/index.vue`。  
   重要性：build 通过不代表 K线 marker、报告曲线、复盘跳转和信号页面真实可用。  
   建议：启动 API + Web，用浏览器验证 report 3/4、market marker、review 1、signal 页。  
   是否需要新 Codex 会话：建议需要，可由 UI bugfix 或前端 smoke 任务处理。

3. 文档口径不一致  
   涉及文件：`tasks/current.md`、`docs/ROADMAP.md`、`docs/PROJECT_PROGRESS.md`、`docs/PROJECT_SNAPSHOT.md`。  
   重要性：部分历史文档曾写真实 vn.py 尚未打通，部分文档写 V1-B 已完成，外部审查容易困惑。  
   建议：以后以 DB、源码、本文件和 `docs/V1B_JM_3Y_FAST_ENTRY.md` 为准，单独做文档一致性收尾。  
   是否需要新 Codex 会话：可作为文档小任务。

### P1：本阶段建议修

1. Redis/RQ 非 inline 联调证据不足  
   涉及文件：`services/quant-api/app/queue.py`、`tasks/backtests.py`、`signal/scanner.py`、`websocket/*`。  
   重要性：V1-B 当前成功信号样本是 inline，真实 worker 和 WebSocket 仍需 smoke。  
   建议：启动 Redis + worker，创建 backtest/signal 非 inline 任务，验证状态流和错误记录。  
   是否需要新 Codex 会话：建议需要。

2. 真实触发信号样本缺失  
   涉及文件：`services/quant-api/app/signal/jm_v1b.py`、`apps/quant-web/src/pages/signal/index.vue`。  
   重要性：当前只有 `no_signal`，未验证 entry signal 展示、确认、跳转。  
   建议：用 fixture 或可解释历史窗口构造触发信号样本，仍不自动下单。  
   是否需要新 Codex 会话：建议需要。

3. 反向信号退出未实现或未明确  
   涉及文件：`packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/vnpy_strategy.py`。  
   重要性：目标描述可能被理解为行情反向也应退出，但当前主要是止损和第 8 根退出。  
   建议：先产品确认是否需要反向信号退出，再实现和测试。  
   是否需要新 Codex 会话：需要，属于策略逻辑变更。

### P2：后续优化

1. 前端 chunk warning  
   涉及文件：`apps/quant-web` build 配置和 chart 组件。  
   重要性：当前不阻塞 V1-B，但影响长期加载。  
   建议：对 ECharts / BaseChart 做动态拆包。  
   是否需要新 Codex 会话：可选。

2. Dashboard / Strategy / Settings 壳子补齐  
   涉及文件：`apps/quant-web/src/pages/dashboard/index.vue`、`strategy/index.vue`、`settings/index.vue`。  
   重要性：不影响 V1-B 核心验收，但影响产品完整性。  
   建议：先围绕真实数据状态、策略版本只读展示和本地设置持久化做最小实现。  
   是否需要新 Codex 会话：建议拆任务。

3. 样本外验证和参数稳定性  
   涉及文件：策略、回测任务、报告。  
   重要性：决定策略是否能进入模拟观察前置审查。  
   建议：V1-B.1 报告口径加固后，再做样本外和敏感性分析。  
   是否需要新 Codex 会话：需要。

## 22. 下一阶段建议

下一阶段建议限定为 V1-B.1 报告口径加固与验收收尾，不扩散到多品种、自动实盘或 AI 策略进化。

建议顺序：

1. 修正年化收益、手续费、滑点、最大回撤百分比口径，并补充后端测试。
2. 做浏览器级 Web smoke，覆盖 report 3/4、K线 marker、review_id=1、signal 页面。
3. 做 Redis/RQ worker 非 inline 联调，确认任务状态和 WebSocket 可用。
4. 做 JM V1-B 策略严谨性审查：未来函数、数据泄露、成交时点、成本、合约乘数、保证金、最大回撤、连续亏损。
5. 构造或寻找真实触发信号样本，验证信号展示和确认流程，保持 `auto_order=false`。
6. 统一文档口径，明确 V1-B 已完成工程闭环，但报告口径和浏览器 smoke 尚未最终验收。

暂不建议：

- 多品种批量扩展。
- 参数优化和网格搜索。
- AI 自动生成策略。
- 模拟盘或实盘接入。
- 自动下单。
- CTP / TqSdk 交易链路。

## 23. 给 ChatGPT 的项目摘要

归一量化是一个本地运行的国内期货量化研究工作台，当前不是 SaaS，也不是自动交易机器人。项目 V1 主线是 RQData / 米筐数据进入本地 standard Parquet 数据湖，通过 DuckDB 和 MarketDataReader 查询，再交给 vn.py CTA BacktestingEngine 做 bar 级回测，结果转换为归一量化统一结构后写入 PostgreSQL，最后由 Vue 3 + Vite + TypeScript + Naive UI 的自定义 Web 展示报告、K线、复盘和信号扫描结果。V1 明确不做自动实盘、不接 CTP/TqSdk 交易接口、不让信号直接下单。

当前阶段是 V1-B：焦煤 JM 3 年真实数据短持有策略闭环。这个阶段只围绕 JM 一个品种，不扩多品种。正式数据来自 RQData / local standard parquet，数据库中已有 `rqdata`、`bars`、`primary`、`passed` 的 1d、15m、5m 三套 JM 数据，范围是 2023-01-03 到 2025-12-31，行数分别是 727、16569、49707，质量报告显示 missing 和 duplicate 为 0。系统中还存在 TqSdk validation 数据、trader_future_data legacy_reference 数据、RQData candidate/sample 数据，但这些不能被当作 V1-B 正式回测数据。

V1-B 策略是 `jm_v1b_daily_direction_fast_entry`。它使用已确认日线判断方向，15m 和 5m 分别独立入场。入场逻辑围绕 EMA21 回踩、MACD 确认、量能和 ATR 距离过滤；信号在当前 bar 收盘生成，下一根 bar 开盘成交，以避免当前信号当前开盘成交的未来函数问题。止损结合 ATR 止损和结构止损，未触发止损时最多第 8 根本周期 K线退出；止损可让交易早于 5 根 K线退出。当前未看到反向信号主动退出作为正式实现。

回测链路已经不是纯壳子。`VnpyBacktestRunner` 会创建 vn.py `BacktestingEngine`、设置参数、加载策略、注入标准 bars、运行回测、计算结果并转换入库。当前 PostgreSQL 中有 4 份报告，其中 `report_id=1/2` 是 smoke report，不应当作正式策略结论；`report_id=3` 是 V1-B 15m 正式报告，127 笔交易，资金曲线和回撤曲线各 727 点；`report_id=4` 是 V1-B 5m 正式报告，323 笔交易，资金曲线和回撤曲线各 727 点。两份正式报告都包含 `entry_reason`、`exit_reason`、`hold_bars`、`stop_loss_price` 和 raw payload。复盘中心已有 1 条 note，关联 `report_id=3` / `trade_id=5`。信号扫描已有 2 条记录，15m 和 5m 当前均为 `no_signal`，原因是日线方向 neutral，且 `auto_order=false`。

Web 端需要区分真实功能和壳子。Data、Market、Backtest、Signal、Review 页面已经接入后端 API；Market 页使用 Lightweight Charts，可把回测交易明细转成买卖点 marker；Backtest 页可展示报告、曲线和交易明细；Review 页能从 backtest trade 创建/查看复盘 note；Signal 页能运行 JM V1-B 扫描和显示 latest signals。但是 Dashboard 仍是静态数字和 mock summary，Strategy 页面是空表壳子，Settings 是未持久化的表单壳子。不能把这些页面写成完整真实功能。

当前验证结果较好：`pytest` 153 passed，`ruff` 通过，前端 `pnpm build` 通过，Alembic 在 `20260627_0010 (head)`。但仍有关键缺口：V1-B 正式报告的 `annual_return`、`total_commission`、`total_slippage` 当前为 0.0，最大回撤金额/百分比口径也需要明确；浏览器截图级 UI smoke 尚未完成；Redis/RQ 非 inline worker 和 WebSocket 联调证据不足，当前成功信号扫描样本是 `run_inline=true`，且有一条历史任务因 Redis 连接失败；当前信号样本都是 `no_signal`，尚未验证真实触发入场信号时的 Web 展示和确认流程。

下一步最合理的方向不是扩多品种、参数优化、模拟盘或实盘，而是进入 V1-B.1 报告口径加固与验收收尾。优先修正年化收益、手续费、滑点、最大回撤百分比和成本归集；随后做浏览器级 smoke，验证 report 3/4、K线 marker、review_id=1 和 signal 页面；再做 Redis/RQ worker 非 inline 联调；最后请外部审查未来函数、成交时点、数据泄露、成本、合约乘数、保证金、最大回撤和连续亏损。只有这些完成后，才适合讨论样本外验证或下一阶段扩展。
