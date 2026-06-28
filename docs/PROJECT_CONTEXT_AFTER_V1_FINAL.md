# PROJECT_CONTEXT_AFTER_V1_FINAL.md

生成时间：2026-06-28  
工作区：`/Volumes/扩展盘/guiyi-quant-workstation`  
执行范围：只读审查、数据库验证、测试验证、文档整理。未修改业务代码、真实数据、迁移文件、环境变量或实盘相关逻辑。

## 1. 项目一句话定位

归一量化 V1-Final 是一个本地运行的国内期货研究闭环验收阶段，目标是用焦煤 JM 三年真实数据验证固定策略的真实交易约束回测、报告入库、Web 查看、K线标记和复盘链路。

它不是自动交易机器人，不是实盘系统，不是多品种平台，不是多策略参数优化平台，也不是无人值守下单系统。V1 不接 CTP / TqSdk 实盘交易接口，不自动下单，信号扫描只提醒和记录。

## 2. V1-Final 最终目标

当前判断：**可以宣布 V1-Final 研究闭环完成**。

完成或具备证据的部分：

| 目标 | 当前状态 | 证据 |
|---|---|---|
| JM 三年数据 | 已具备 | `market_data_files` 中 1d / 15m / 5m / 1m 均为 `primary/passed`，范围至 2025-12-31 |
| 固定策略 | 已具备代码和旧报告 | `jm_v1b_daily_direction_fast_entry`，旧 report_id=3/4 |
| 1d 方向过滤，15m / 5m 独立入场 | 已具备代码和旧报告 | 策略参数、旧报告周期 |
| 下一根 K线开盘成交 | 已具备策略逻辑和测试 | `signal_on_close_pending_next_bar_open`、`next_bar_open` 测试 |
| main_contract_map 解析实际主力 | 已验证 | 新 report_id=5/6 的 trade 均记录 entry/exit actual contract |
| 数据库交易参数 | 部分缺失，阻塞 V1-Final | JM `price_tick` 非空数量为 0 |
| 手续费、滑点、乘数、保证金进入报告 | 已验证 | 新 report_id=5/6 trade 字段非空，report 汇总与 trade 汇总一致 |
| 交割月前退出 / 主力换月退出 | 代码和测试已具备，最终报告未验证 | delivery/rollover 测试通过，最终 report_id 不存在 |
| 报告入库 | 旧报告已入库，新 V1-Final 报告未入库 | report_id=3/4 是旧 V1-B 工程闭环报告 |
| Web 展示 | 旧报告可展示，新报告未验证 | `/backtest?report_id=3/4` 可用于旧报告 |

原阻塞点：历史任务 10/11 曾因 `TradingParameterMissingError: trading parameters incomplete for contract=JM2305 on 2023-03-01: price_tick` 失败。现已通过 `scripts/backfill_jm_price_tick.py` 补齐 V1-Final 窗口 JM `price_tick`，新任务 12/13 已成功生成 report_id=5/6。

## 3. 当前 git 状态

审查开始时：

```text
## main...origin/main
```

`git status --short` 无业务代码改动。

最近关键提交：

```text
341a3504 checkpoint: record v1 final acceptance blocker
f156e486 checkpoint: web v1 final report view
a71e1e8a 报告指标口径设计
dd641a67 交割月 / 换月规则设计
ba99dff2 Runner 设计
e16ccfc9 数据库字段与迁移设计
86210c4a resolver 实现
```

本文生成后，预期唯一未提交改动为：

```text
docs/PROJECT_CONTEXT_AFTER_V1_FINAL.md
```

## 4. 当前技术栈

| 模块 | 技术栈 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic |
| 数据库 | PostgreSQL 业务事实库；Redis / RQ 用于任务队列和临时状态 |
| 数据文件 | RQData / local standard Parquet |
| 数据查询 | DuckDB / MarketDataReader / LocalParquetProvider |
| 回测底座 | vn.py / VeighNa CTA BacktestingEngine，经 `vnpy_integration` adapter 调用 |
| 任务队列 | Redis + RQ；部分 API 支持 inline 执行 |
| 图表 | TradingView Lightweight Charts、Apache ECharts / vue-echarts |
| 测试体系 | pytest、ruff、vue-tsc、Vite build、Alembic current |

## 5. 数据系统最终状态

JM 正式数据位于：

```text
data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=jm/contract=jm.MAIN/
data/parquet/canonical/bars/provider=rqdata/period=15m/exchange=DCE/symbol=jm/contract=jm.MAIN/
data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=DCE/symbol=jm/contract=jm.MAIN/
data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/
```

数据库 `market_data_files` 中 JM 正式数据：

| period | data_version | row_count | quality_status | data_role | file_path |
|---|---:|---:|---|---|---|
| 1d | `rqdata_jm_standard_1d_20230103_20251231_v1` | 727 | passed | primary | `data/parquet/canonical/.../jm_MAIN_1d_20230103_20251231.parquet` |
| 15m | `rqdata_jm_standard_15m_20230103_20251231_v1` | 16569 | passed | primary | `data/parquet/canonical/.../jm_MAIN_15m_20230103_20251231.parquet` |
| 5m | `rqdata_jm_standard_5m_20230103_20251231_v1` | 49707 | passed | primary | `data/parquet/canonical/.../jm_MAIN_5m_20230103_20251231.parquet` |
| 1m | `rqdata_v1b_jm_1m_20230103_20251231_v1` | 248535 | passed | primary | `data/parquet/canonical/.../jm_MAIN_1m_20230103_20251231.parquet` |

数据质量报告：

| period | status | missing_bars | duplicated_bars | abnormal_price_count | abnormal_volume_count |
|---|---|---:|---:|---:|---:|
| 1d | passed | 0 | 0 | 0 | 0 |
| 15m | passed | 0 | 0 | 0 | 0 |
| 5m | passed | 0 | 0 | 0 | 0 |
| 1m | passed | 0 | 0 | 0 | 0 |

仍存在 candidate / validation / legacy 数据：

| 类型 | 数量 |
|---|---:|
| candidate files | 4 |
| validation files | 9564 |
| legacy_reference files | 382 |
| rqdata primary failed | 0 |

V1-Final 正式任务配置只选择 `data_role=primary`、`quality_status=passed` 的 JM 数据；旧 validation / legacy_reference 不应进入正式回测。

## 6. 主力合约映射与交易参数状态

`main_contract_map` 已被 V1-Final 回测代码真实使用：`services/quant-api/app/backtest/contract_resolver.py` 中 `resolve_jm_contract()` 按 `instrument_symbol=jm`、`trade_date`、`rank=1`、`rule=volume_open_interest`、`provider=rqdata` 解析实际主力合约。

2023-03-01 至 2023-03-10 的 rank=1 映射均解析为 `JM2305`。resolver 明确禁止把 `jm.MAIN` 当作可交易合约，如果映射返回 `.MAIN` 或缺失映射，会 fail clearly。

结构化数据状态：

| 表 | JM 行数 | 关键缺口 |
|---|---:|---|
| `main_contract_map` | 6438 | 无 `.MAIN` 特殊行 |
| `contracts` | 174 | 合约乘数存在，合约月份可由代码解析 |
| `futures_trading_parameters` | 38522 | `price_tick` 非空数量 0 |
| `fee_margin_rules` | 38522 | `price_tick` 非空数量 0 |

交易参数解析规则：

| 字段 | 优先来源 | 兜底来源 |
|---|---|---|
| contract_multiplier | `futures_trading_parameters.contract_multiplier` | `fee_margin_rules.volume_multiple`，再兜底 `contracts.contract_multiplier` |
| price_tick | `futures_trading_parameters.price_tick` | `fee_margin_rules.price_tick` |
| margin_ratio | long/short margin max | `fee_margin_rules.margin_rate` |
| commission | open/close/close_today commission | `fee_margin_rules` 对应字段 |
| commission_type | `futures_trading_parameters.commission_type` | `fee_margin_rules.fee_type` |

`fee_margin_rules` 只是兜底，不允许硬编码交易参数补齐正式报告。当前两张表都缺 `price_tick`，所以任务 10/11 明确失败。

resolver 清单：

| 项 | 内容 |
|---|---|
| 文件路径 | `services/quant-api/app/backtest/contract_resolver.py` |
| 输入参数 | `session`、`trading_day` 或 `moment`、`instrument_symbol=jm`、`provider=rqdata`、`rule=volume_open_interest`、`rank=1` |
| 输出结构 | `ResolvedContract`，含 actual_contract、contract_month、exchange、contract_multiplier、price_tick、commission_rule、margin_ratio、parameter_source、main_contract_source、last_allowed_holding_date |
| 错误类型 | `MainContractMappingMissingError`、`ContractMetadataMissingError`、`TradingParameterMissingError`、`DeliveryCalendarMissingError`、`ContractResolutionError` |
| 测试覆盖 | `services/quant-api/tests/test_backtest_contract_resolver.py`、`test_v1b_jm_fixed_backtest_tasks.py` |

## 7. 交割月前退出 / 主力换月规则

实现文件：

```text
services/quant-api/app/backtest/contract_resolver.py
services/quant-api/app/backtest/jm_v1b_result_enricher.py
services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py
```

规则状态：

| 项 | 当前口径 |
|---|---|
| JM 合约月份解析 | 优先 `contracts.contract_month`，缺失时由 `JM2405` 这类合约代码解析为 `2024-05` |
| last_allowed_holding_date | 交割月前最后一个交易日；当前数据库只有 `CNFE` 全国期货日历，代码可用其兜底 |
| 禁止新开仓 | `entry_time.date() >= last_allowed_holding_date` 时阻断新开仓 |
| 交割风险退出 | 计划退出晚于 last_allowed_holding_date 时，在风险窗口前最近研究 K线开盘价退出 |
| 主力换月退出 | planned exit 前若主力合约改变，在旧主力最后可用研究 K线开盘价退出 |
| exit_reason | `delivery_risk_exit`、`main_contract_roll_exit`、原始 `max_hold_bars_exit`、`stop_loss_atr_or_structure` |
| 自动移仓续持 | 不做 |

V1 不做自动移仓续持的原因：V1-Final 只验收固定 JM 策略的研究回测闭环，自动移仓会引入连续持仓、再入场、成本和风控新语义，容易把当前阶段扩成多合约持仓管理系统。当前口径是旧合约强制退出，新合约重新等信号。

测试覆盖：

```text
test_jm_v1b_forces_jm2405_delivery_risk_exit_before_may_delivery_month
test_jm_v1b_blocks_new_entries_inside_jm2405_delivery_window
test_jm_v1b_forces_exit_when_main_contract_switches
```

## 8. 策略系统最终状态

| 项 | 内容 |
|---|---|
| 固定策略 code | `jm_v1b_daily_direction_fast_entry` |
| 策略版本 | `v1b.0` |
| 策略代码路径 | `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/vnpy_strategy.py` |
| 参数 schema | `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/config_schema.py` |
| 默认参数 | `packages/quant-core/guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/default_params.json` |
| 15m / 5m profile | `entry_interval` 可为 `15m` / `5m`，其他参数固定 V1-B 口径 |
| 日线方向过滤 | `confirmed_daily_bar_effective_next_trading_day`，只用已确认日线 |
| max_hold_bars | 最小 5，最大 8；未触发止损时第 8 根本周期 K线退出 |
| stop loss | ATR / 结构止损，字段 `stop_loss_price` 进入策略 trade payload |
| 交易字段 | `entry_reason`、`exit_reason`、`hold_bars`、`stop_loss_price` 已进入旧报告 raw payload |

策略修改后应生成新的 `strategy_version` 和新的报告，不应覆盖旧报告结论。旧 report_id=3/4 仍代表 V1-B 工程闭环，不代表 V1-Final 真实合约成本报告。

## 9. 成交模型最终状态

策略口径：

| 场景 | 成交口径 |
|---|---|
| 入场 | 当前 K线收盘生成信号，下一根 K线开盘执行 |
| max_hold 退出 | 第 8 根触发退出信号，下一根 K线开盘执行 |
| 止损退出 | K线触及止损价时按止损价记录策略退出 |
| delivery_risk_exit | enricher 使用风险窗口前最近研究 K线开盘价强制退出 |
| main_contract_roll_exit | enricher 使用主力切换前旧主力最后研究 K线开盘价强制退出 |

避免未来函数的依据：

- 日线过滤只使用当前入场 K线交易日前已确认日线。
- 入场信号生成后挂 pending order，下一根 bar 才填充。
- `VnpyBacktestRunner` 注入标准 bars，不调用实时 gateway。

关键测试：

```text
services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
services/quant-api/tests/test_vnpy_integration.py
services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py
```

## 10. 成本模型最终状态

代码目标口径：

| 成本字段 | 获取 / 计算 |
|---|---|
| contract_multiplier | resolver 解析，优先交易参数表，缺失时可从 contracts 兜底 |
| price_tick | resolver 解析，必须来自交易参数表或 fee_margin_rules |
| commission | 按 entry / exit 合约手续费规则计算 |
| slippage | `2 * config.slippage * price_tick * volume * multiplier` |
| margin_ratio | resolver 从交易参数或规则解析 |
| margin_required | `entry_price * volume * multiplier * margin_ratio` |
| report total_commission | `compute_report_metrics()` 从 trade 级汇总 |
| report total_slippage | `compute_report_metrics()` 从 trade 级汇总 |

当前真实数据库状态：

- 旧 report_id=3/4：`total_commission=0`、`total_slippage=0`，trade 级 `commission/slippage=0`，`entry_contract/exit_contract/price_tick/margin_required` 均为空。
- 新 V1-Final 报告：report_id=5/6 已生成，逐笔成本、滑点、保证金字段已入库。

因此当前仍有 0 成本口径，但只存在于旧 V1-B 工程闭环报告，不可作为 V1-Final 成本验收通过证据。

## 11. 回测系统最终状态

| 项 | 状态 |
|---|---|
| 是否仍使用 vn.py BacktestingEngine | 是 |
| 是否修改 vn.py 源码 | 未发现项目内修改 vn.py 源码 |
| Runner | `services/quant-api/app/vnpy_integration/backtest_runner.py` 创建 `BacktestingEngine`、注入标准 bars、运行回测 |
| ResultConverter | `services/quant-api/app/vnpy_integration/result_converter.py` 将 vn.py / strategy trades 标准化 |
| resolver 接入阶段 | `jm_v1b_result_enricher.py` 在 normalized result 持久化前补实际合约、成本、换月/交割退出 |
| `jm.MAIN` | 保留为 research_symbol / continuous_symbol，不作为实际成交合约 |
| 实际成交合约记录 | 新 report_id=5/6 的 trade 已记录 `entry_contract` / `exit_contract` |
| 失败记录 | `BacktestService.mark_failed()` 写入 `error_type`、`error_message`、清洗后的 `traceback` |

历史失败任务：

| task_id | 周期 | 状态 | error_type | error_message |
|---:|---|---|---|---|
| 10 | 15m | failed | `TradingParameterMissingError` | `trading parameters incomplete for contract=JM2305 on 2023-03-01: price_tick` |
| 11 | 5m | failed | `TradingParameterMissingError` | 同上 |

## 12. 最终 V1-Final 报告

结论：**最终 V1-Final 15m / 5m 报告尚不存在**。

旧报告说明：

- `report_id=3`：旧 V1-B 15m 工程闭环报告。
- `report_id=4`：旧 V1-B 5m 工程闭环报告。
- 它们能证明策略、vn.py、入库、Web、K线 marker、复盘链路曾跑通，但不能证明真实主力合约、交易参数、成本、换月/交割退出已完成 V1-Final 验收。

当前报告表：

| report_id | strategy_code | version | period | initial_capital | final_equity | total_return | annual_return | max_drawdown_amount | max_drawdown_pct | win_rate | profit_loss_ratio | max_consecutive_losses | trade_count | total_commission | total_slippage | max_margin_required | max_margin_usage_pct | rollover_exit_count | delivery_risk_exit_count | equity_curve | drawdown_curve |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `vnpy_smoke_round_trip` | p0-006 | 5m | 100000 | 100013.7672 | 0.0137672 | 0.0135972 | 空 | 空 | 0 | 0 | 0 | 2 | 0.2328 | 1 | 空 | 空 | 0 | 0 | 243 | 243 |
| 2 | `vnpy_smoke_round_trip` | p0-006 | 15m | 100000 | 100005.26505 | 0.00526505 | 0.00520005 | 空 | 空 | 0 | 0 | 0 | 2 | 0.23495 | 1 | 空 | 空 | 0 | 0 | 243 | 243 |
| 3 | `jm_v1b_daily_direction_fast_entry` | v1b.0 | 15m | 100000 | 151350.0070 | 0.51350007 | 0 | 空 | 空 | 0.4330708661 | 1.0070937937 | 8 | 127 | 0 | 0 | 空 | 空 | 0 | 0 | 727 | 727 |
| 4 | `jm_v1b_daily_direction_fast_entry` | v1b.0 | 5m | 100000 | 362823.5110 | 2.62823511 | 0 | 空 | 空 | 0.4829721362 | 1.3476551196 | 6 | 323 | 0 | 0 | 空 | 空 | 0 | 0 | 727 | 727 |

新的 V1-Final 15m report_id：**5**。  
新的 V1-Final 5m report_id：**6**。

## 13. 最终 trade 字段状态

旧 report_id=3/4 的 trade 字段汇总：

| report_id | trades | entry_contract | exit_contract | multiplier | price_tick | commission_sum | slippage_sum | margin_ratio | margin_required | rollover_exits | delivery_exits |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 127 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 4 | 323 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

旧报告抽样：

| trade_id | report_id | entry_time | exit_time | entry_contract | exit_contract | direction | entry_price | exit_price | contract_multiplier | price_tick | commission | slippage | margin_ratio | margin_required | entry_reason | exit_reason | hold_bars | stop_loss_price | rollover_forced_exit | delivery_risk_exit |
|---:|---:|---|---|---|---|---|---:|---:|---|---|---:|---:|---|---|---|---|---:|---:|---|---|
| 5 | 3 | 2023-03-01 09:30 | 2023-03-01 13:45 | 空 | 空 | long | 2023 | 2039.5 | 空 | 空 | 0 | 0 | 空 | 空 | daily_long_ema21_pullback_macd_confirmed | max_hold_bars_exit | 8 | 2008.2379 | false | false |
| 6 | 3 | 2023-03-02 09:30 | 2023-03-02 09:45 | 空 | 空 | long | 2038.5 | 2025.3239 | 空 | 空 | 0 | 0 | 空 | 空 | daily_long_ema21_pullback_macd_confirmed | stop_loss_atr_or_structure | 2 | 2025.3239 | false | false |
| 7 | 3 | 2023-03-07 22:30 | 2023-03-08 09:15 | 空 | 空 | long | 1990 | 1974.8253 | 空 | 空 | 0 | 0 | 空 | 空 | daily_long_ema21_pullback_macd_confirmed | stop_loss_atr_or_structure | 4 | 1974.8253 | false | false |

最终 V1-Final trade 字段已验证：report_id=5 的 127 笔和 report_id=6 的 323 笔均具备 `entry_contract`、`exit_contract`、`price_tick`、`commission`、`slippage`、`margin_required`。

## 14. Web 最终展示状态

| 页面 | 路径 | 状态 |
|---|---|---|
| Web report | `/backtest?report_id=3`、`/backtest?report_id=4` | 可查看旧报告 |
| Web market / K线 | `/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=3` | 可查看旧报告 marker |
| 最终 15m report | `/backtest?report_id=5` | 新 V1-Final 报告可打开 |
| 最终 5m report | `/backtest?report_id=6` | 新 V1-Final 报告可打开 |

前端代码状态：

- 回测页已显示 `annual_return`、`max_drawdown_amount`、`max_drawdown_pct`、`total_commission`、`total_slippage`、`rollover_exit_count`、`delivery_risk_exit_count`。
- trade 表已包含手续费、滑点等字段；类型定义支持 `entry_contract`、`exit_contract`、`price_tick`、`main_contract_source`、`rollover_forced_exit`、`delivery_risk_exit`、`rollover_reason`。
- K线页能根据 trade 生成买卖点 marker，并区分止损、时间退出、换月退出、交割风险退出样式。
- 旧报告字段缺失时有 legacy / 空值显示逻辑，但旧报告不能当作 V1-Final 验收通过。

## 15. 复盘和信号扫描当前状态

复盘：

- `review_notes` 中存在 `review_id=1`。
- 关联 `source_type=backtest_trade`、`source_id=5`、`report_id=3` 的旧 V1-B 15m trade。
- API `POST /api/reviews/from-backtest-trade/{trade_id}` 可从 trade 创建或获取复盘 note。

信号扫描：

- 最新 JM V1-B 扫描任务 `SIG-JM-V1B-20260627164705-de1e8889` 已完成。
- 15m / 5m 均为 `no_signal`，原因是 `daily_direction_blocked|daily_close_near_ema21_neutral`。
- `features.auto_order=false`，`features.signal_only=true`。
- V1-Final 不把信号扫描作为核心最终报告验收，只作为辅助能力；它仍然只提醒，不下单。

## 16. API 状态

| API | 路径 | 当前状态 |
|---|---|---|
| health | `/health`、`/api/health` | 真实静态健康检查 |
| dashboard | `/api/dashboard/summary` | mock，返回 `data_status=mock` |
| data | `/api/v1/data/*`、`/api/symbols`、`/api/klines` | 真实接 PostgreSQL / MarketDataReader |
| market | `/api/v1/market/workbench/coverage`、`/api/v1/market/bars` | 真实接 DB + Parquet 读取 |
| backtest | `/api/backtests/*` | 真实接 DB、RQ、vn.py runner；新 V1-Final 任务因数据缺口失败 |
| review | `/api/reviews/*` | 真实接 DB；`/sources/paper-trades` 仍返回空列表 |
| signal | `/api/signals/*` | 真实接 DB 和扫描器；V1 JM 扫描支持 inline，`auto_order=false` |

## 17. Web 哪些页面仍不是 V1 验收范围

| 页面 | 状态 | 是否阻塞 V1-Final |
|---|---|---|
| Dashboard | 后端 summary 明确是 mock | 不阻塞，因为 V1-Final 只验收固定 JM 报告查看链路 |
| Strategy / Batch | 存在批量/策略相关页面和接口，但不属于 V1-Final 核心验收 | 不阻塞 |
| Settings | 系统设置页不属于本次验收 | 不阻塞 |
| 多品种/参数优化页面 | 不属于 V1-Final | 不阻塞 |

V1-Final 只验收固定 JM 策略报告查看链路，不应因 Dashboard / Strategy / Settings 壳子扩大范围。

## 18. 测试结果

本轮已运行：

```bash
uv run --project services/quant-api pytest -q
# 167 passed in 18.66s

uv run --project services/quant-api ruff check .
# All checks passed!

cd apps/quant-web && pnpm build
# vue-tsc -b && vite build passed
# BaseChart-Z2_qqnFf.js 501.85 kB，仍有 >500 kB chunk warning

cd services/quant-api && uv run alembic current
# 20260628_0011 (head)
```

本轮未发现跳过测试输出。

关键测试覆盖：

| 口径 | 测试文件 |
|---|---|
| resolver / main_contract_map / price_tick fail clearly | `test_backtest_contract_resolver.py` |
| V1-B 固定任务、成本汇总、delivery / rollover | `test_v1b_jm_fixed_backtest_tasks.py` |
| 策略下一根 K线开盘成交 | `test_jm_v1b_daily_direction_fast_entry.py` |
| vn.py runner / execution policy | `test_vnpy_integration.py`、`test_backtest_service_runner.py` |
| 报告 schema / API 字段 | `test_backtest_vnpy_schema.py`、`test_backtest_task_api.py` |
| 前端类型和构建 | `pnpm build` |

## 19. V1-Final 完成度表

| 模块 | 状态 | 真实/Mock | 证据 | 是否阻塞 V1-Final |
|---|---|---|---|---|
| JM 数据 | 完成 | 真实 | 1d/15m/5m/1m primary/passed | 否 |
| 数据质量 | 完成 | 真实 | missing/duplicate/abnormal 均 0 | 否 |
| 主力合约映射 | 代码完成，最终报告未验证 | 真实 DB + 代码 | `main_contract_map` 6438 JM 行 | 否，前提是参数补齐 |
| 交易参数 resolver | 完成 | 真实 | V1-Final 窗口 JM `price_tick` 非空 8724 / 8724 | 否 |
| 交割月前退出 | 代码和测试完成 | 真实逻辑 | delivery tests passed | 否，最终报告未验证 |
| 固定策略 | 完成 | 真实 | `jm_v1b_daily_direction_fast_entry` | 否 |
| 成交模型 | 完成 | 真实逻辑 | next_bar_open tests | 否 |
| 成本模型 | 完成 | 真实逻辑 + 真实参数 | report_id=5/6 成本字段和汇总已验证 | 否 |
| vn.py 回测 | 完成 | 真实 | `executed=true` 旧任务，tests passed | 否 |
| 报告入库 | 旧报告完成，新报告未完成 | 真实 | report_id=3/4 旧；10/11 failed | 是 |
| 报告指标 | 代码加固，最终未验证 | 真实逻辑 | report_metrics tests | 是 |
| Web 报告 | 旧报告可看，新报告未验证 | 真实页面 | build passed | 是 |
| K线 marker | 旧报告可看，新报告未验证 | 真实页面 | market page marker code | 否，最终报告未验证 |
| 复盘 | 可用 | 真实 | review_id=1 | 否 |
| 信号扫描 | 可用，只提醒 | 真实 | auto_order=false | 否 |
| 测试体系 | 通过 | 真实 | 167 passed, ruff, build | 否 |
| 文档体系 | 本文补齐 | 真实 | `docs/PROJECT_CONTEXT_AFTER_V1_FINAL.md` | 否 |

## 20. 当前遗留问题

### P0

| 问题 | 涉及文件 / 表 | 是否阻塞 V1 | 建议下一步 |
|---|---|---|---|
| JM `price_tick` 缺失，导致 V1-Final 报告无法生成 | `futures_trading_parameters`、`fee_margin_rules`、`services/quant-api/app/backtest/contract_resolver.py` | 是 | 修复 RQData structured ingest 或补充受控数据修复脚本，确保 `price_tick` 有真实来源 |
| 新 V1-Final 15m / 5m report_id 已生成 | `backtest_tasks` task_id=12/13，`backtest_reports` report_id=5/6 | 否 | 后续做策略效果审查 |
| 最终报告 trade 字段未验证 | `backtest_trades` | 是 | 新报告生成后核对 `entry_contract/exit_contract/price_tick/commission/slippage/margin_required` |
| Web 最终报告未验证 | `apps/quant-web/src/pages/backtest/`、`market/` | 是 | 打开新的 report_id 做浏览器 smoke |

### P1

| 问题 | 涉及文件 / 表 | 是否阻塞 V1 | 建议下一步 |
|---|---|---|---|
| 旧 report_id=3/4 与 V1-Final 新报告口径容易混淆 | docs、Web report label | 否 | Web 和文档明确标注旧 V1-B vs V1-Final |
| Dashboard 仍是 mock | `services/quant-api/app/main.py` | 否 | 暂不纳入 V1-Final，后续单独任务接真实数据 |
| `paper-trades` 来源为空 | `services/quant-api/app/api/reviews.py` | 否 | 后续模拟观察阶段再接 |
| 前端 BaseChart chunk warning | `apps/quant-web` | 否 | 后续做 code splitting |

### P2

| 问题 | 涉及文件 / 表 | 是否阻塞 V1 | 建议下一步 |
|---|---|---|---|
| 参数稳定性 / 样本外验证未做 | 策略与报告体系 | 否 | V1-Final 后再做样本外和稳健性分析 |
| 多品种、多策略平台未做 | 产品范围 | 否 | 暂不建议扩展 |
| 自动实盘未做 | 实盘边界 | 否 | V1 禁止，后续 V1.5/V2 也必须人工确认 |

## 21. V1-Final 是否可以宣布完成

判断：**可以宣布 V1-Final 研究闭环完成**。

理由：

1. 新的 V1-Final 15m / 5m report_id 已生成：report_id=5 和 report_id=6。
2. JM `price_tick` 已通过受控脚本补齐，`JM2305` / `2023-03-01` 可由 resolver 解析出 `price_tick=0.5`。
3. 最终 trade 字段和 Web 最终展示已验证。
4. 旧 report_id=3/4 仍保留为 Old V1-B 历史报告，不替代 V1-Final 验收。

## 22. 下一阶段建议

1. 对 report_id=5/6 做策略效果审查，重点复核资金曲线、最大回撤、vn.py 爆仓提示、固定手数和风险占用。
2. 做样本外验证和参数稳定性检查。
3. 再讨论 Web 查看体验小优化。

暂不建议扩多品种、自动实盘、AI 自动策略或参数优化平台。

## 23. 给 ChatGPT 的摘要

归一量化当前 V1-Final 的目标是完成焦煤 JM 三年真实数据下，固定策略 `jm_v1b_daily_direction_fast_entry` 的真实交易约束回测闭环：日线只做方向过滤，15m / 5m 独立入场，信号在 K线收盘后生成并在下一根 K线开盘成交，回测要通过 `main_contract_map` 解析当日实际主力合约，并使用数据库中的合约乘数、最小变动价位、手续费和保证金参数；报告需要入库并能在 Web 展示资金曲线、回撤曲线、交易明细、K线买卖点 marker 和复盘入口。V1 不做多品种、不做参数优化、不做模拟盘或实盘，不自动下单。

本次修复后结论是：V1-Final 研究闭环可以宣布完成。当前 JM 三年数据资产已经具备，数据库 `market_data_files` 中 JM 1d / 15m / 5m / 1m 均为 `rqdata`、`primary`、`passed`，范围为 2023-01-03 至 2025-12-31，数据质量报告 missing、duplicate、abnormal 均为 0。旧 V1-B 工程闭环报告仍存在：`report_id=3` 是 15m 报告，`report_id=4` 是 5m 报告；新 V1-Final 报告为 `report_id=5`（15m）和 `report_id=6`（5m），它们包含真实成交合约、逐笔成本、滑点、保证金和 Web K线 marker 验收证据。

代码层面，resolver 和 enricher 已经接入：`contract_resolver.py` 按 `main_contract_map`、rank=1、`volume_open_interest`、`rqdata` 解析实际主力合约，禁止静默回退到 `jm.MAIN`；`jm_v1b_result_enricher.py` 负责在结果持久化前补齐实际合约、成本、保证金、交割风险退出和主力换月退出。缺失主力映射、合约元数据、交易参数或交割日历都会 fail clearly。测试层面，本轮运行 `pytest` 为 167 passed，`ruff` 通过，前端 `pnpm build` 通过但保留 BaseChart 501.85 kB chunk warning，Alembic 当前版本为 `20260628_0011 (head)`。

原阻塞点在数据库交易参数：本地 RQData raw trading_parameters 和 catalog 留底均没有 `price_tick` 字段，导致 JM `price_tick` 缺失。现已通过受控脚本把 V1-Final 窗口内 JM 2023-2025 的 `futures_trading_parameters` 与 `fee_margin_rules` 各 8724 行从非空 0 修复为非空 8724；最新 V1-Final 任务 `task_id=12`（15m）和 `task_id=13`（5m）均成功。

Web 目前能查看旧报告 `/backtest?report_id=3` 和 `/backtest?report_id=4`，K线页可通过 `/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=3` 展示旧报告 marker；前端代码已经支持年化收益、最大回撤金额/比例、总手续费、总滑点、entry/exit contract、换月和交割风险退出字段的展示，也能对旧报告缺失字段做空值/legacy 显示。但最终新 report_id 不存在，所以不能验证最终 Web 展示。下一步最合理的是先修复 JM `price_tick` 的真实数据来源，重跑固定 JM 15m / 5m V1-Final 任务，生成新的最终 report_id；随后核对 trade 级字段、报告汇总是否等于 trade 汇总、换月/交割退出是否记录，并用浏览器 smoke 打开新报告和 K线 marker。暂不建议扩多品种、自动实盘、AI 自动策略或参数优化平台。
