# 归一量化工作站 — 项目功能总览

生成时间：2026-07-08

## 一、项目定位

归一量化是一个**本地运行的国内期货量化研究工作站**，帮助用户从主观交易逐步过渡到规则化、数据化、回测化、复盘化、预警化的研究闭环。

- 当前阶段：**V1-B** — 焦煤 JM 3 年真实数据短持有策略闭环
- 核心目标：数据更新 → 质量检查 → K线查看 → 策略回测 → 报告 → 信号提醒 → 复盘 → 人工观察
- 安全边界：不做无人值守自动实盘，不把信号直接当成交易指令

## 二、技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3, Vite, TypeScript, Naive UI, Pinia, Vue Router, Lightweight Charts, ECharts, WebSocket |
| 后端 | Python 3.13, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Redis + RQ |
| 数据 | RQData (米筐), Local Standard Parquet, DuckDB, PostgreSQL, PyArrow |
| 回测 | vn.py / VeighNa CTA BacktestingEngine + 自定义 Adapter / Runner / ResultConverter |
| 部署 | 本地 Mac / Docker Compose；阿里云 Web 托管为当前远程访问设计主线 |

## 三、系统架构

```text
RQData / Local Standard Parquet
-> DuckDB (查询/周期合成)
-> PostgreSQL (业务事实库)
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web (K线复盘 / 信号提醒 / 人工观察)
```

### 目录结构

| 路径 | 作用 |
|---|---|
| `apps/quant-web/` | Vue 3 Web 工作台 |
| `services/quant-api/` | FastAPI 后端、RQ worker、ORM、API、WebSocket |
| `packages/quant-core/` | vn.py CtaTemplate 策略和共享配置 |
| `strategies/` | 策略设计说明文档 |
| `data/` | raw / standard parquet、manifest、质量报告 |
| `docs/` | 架构、数据、回测、策略、交接文档 |
| `scripts/` | 启停、RQData 下载、审计、导出脚本 |
| `experiments/` | 隔离 PoC，不属于正式 V1 报告链路 |
| `tasks/` | 当前任务和任务队列 |
| `prompts/` | AI 提示模板 |

## 四、核心功能模块

### 4.1 数据中心

负责把外部数据变成本地可信、可追溯、可复算的数据资产。

**数据链路：**
```text
RQData -> raw parquet -> standard parquet
-> manifest / checksum / quality report
-> PostgreSQL market_data_files / data_quality_reports
-> DuckDB read_parquet -> Market / Backtest / Signal / Review
```

**active 数据入口约束：**
- `source in ("rqdata", "local_parquet")`
- `data_role = "primary"`
- `quality_status != "failed"`（严格研究优先 `"passed"`）

**已具备能力：**
- RQData ingest（分钟数据、合约信息、主力映射、复权因子、交易参数）
- JM v2 六周期 raw / standard parquet 写入（1m/5m/15m/30m/60m/1d）
- manifest、checksum、quality report 生成与 PostgreSQL 登记
- DuckDB 读取 standard parquet
- 全品种下载脚本骨架（90 个候选品种，分层管理：进行中 → 待审计 → 可进入 active）
- 真实主力合约 historical bars 写入试点（JM2609）
- Stage 8.6 全品种 active Gate 只读审计

**关键代码：**
- `services/quant-api/app/api/data_center.py`
- `services/quant-api/app/services/rqdata_ingest/` (约 20 个模块)
- `scripts/rqdata_*.py` (20+ 下载/同步/审计脚本)

### 4.2 行情工作台 (Market)

**功能：**
- 多周期 K 线展示（TradingView Lightweight Charts）
- 技术指标叠加
- 回测买卖点 marker 联动
- 品种研究只读面板（主力映射、复权因子、交易参数、仓单、展期收益、合约池、连续合约、会员排名）
- historical / live 双模式，默认 historical
- actual-contract 与 continuous-contract 视图区分

**关键 API：**
- `GET /api/v1/market/workbench/coverage` — 数据覆盖范围
- `GET /api/v1/market/bars` — K 线数据
- `GET /api/v1/market/dominants` — 主力合约
- `GET /api/v1/market/live/targets` — live 目标合约池
- `GET /api/v1/market/live/bars` — live 行情
- `GET /api/v1/market/research/*` — 品种研究只读 API（9 个端点）

**前端页面：**
- `/market` — 行情看板
- `/market/chart` — 单品种 K 线详情 + 品种研究面板

### 4.3 回测中心 (Backtest)

**功能：**
- vn.py CTA BacktestingEngine 回测
- 创建回测任务（自定义策略 + 参数）
- JM V1-B 15m / 5m 固定任务
- 批量回测（watchlist + WebSocket 实时进度）
- 回测报告：资金曲线、回撤曲线、交易明细、订单明细
- ResultConverter 标准化 vn.py 输出
- K 线 marker 联动回测成交
- 真实合约成本增强（手续费、保证金、强平退出）

**关键代码：**
- `services/quant-api/app/api/backtests.py`
- `services/quant-api/app/backtest/engine.py` — 回测引擎核心
- `services/quant-api/app/backtest/runner.py` — 异步任务执行器
- `services/quant-api/app/backtest/v1b_jm_tasks.py` — JM V1B 任务构建
- `services/quant-api/app/vnpy_integration/` — vn.py 适配层（7 个模块）

**前端页面：**
- `/backtest` — 回测任务、报告、曲线、明细
- `/backtest/batch` — 批量回测 + WebSocket 进度

### 4.4 信号扫描 (Signal)

**功能：**
- JM V1-B 研究信号扫描（只提醒，不自动下单）
- `signal_events` append-only 信号事件账本
- 事件类型：`signal_created` / `signal_changed` / `signal_status_changed`
- 真实合约上下文绑定（product / continuous_contract / actual_contract / trigger_price）
- Live 信号实时评估器（preview-only，不写正式信号）
- Stage 9 Gate 准入检查
- 企业微信只读提醒 preview / dry-run / 受控发送

**关键代码：**
- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/signal/scanner.py` — 信号扫描
- `services/quant-api/app/signal/jm_v1b.py` — JM V1B 扫描核心
- `services/quant-api/app/signal/events.py` — 事件账本
- `services/quant-api/app/signal/stage9_gate.py` — Stage 9 准入 Gate
- `services/quant-api/app/signal/stage9_wechat.py` — 企业微信 preview
- `services/quant-api/app/signal/stage9_wechat_delivery.py` — 受控发送
- `services/quant-api/app/services/live_signal_evaluator.py` — Live 评估器

**前端页面：**
- `/signal` — 信号监控 + WebSocket 实时推送

### 4.5 复盘中心 (Review)

**功能：**
- 从回测成交创建复盘 note
- 复盘标签管理
- 复盘统计分析
- 附件上传

**关键代码：**
- `services/quant-api/app/api/reviews.py`
- `services/quant-api/app/services/review_center.py`
- `services/quant-api/app/review/backtest_trade.py`

**前端页面：**
- `/review` — 复盘 note、标签、统计

### 4.6 Live 行情

**功能：**
- RQData live 1m 数据独立表入库
- 5m / 15m / 30m / 60m live 聚合表
- Live 目标合约解析器（从 MainContractMap.rank=1 解析真实主力）
- LiveSignalEvaluator 实时信号评估（preview-only）
- 盘中观察和 preview，不登记 market_data_files

**关键代码：**
- `services/quant-api/app/services/live_1m_ingest.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/app/services/live_signal_evaluator.py`

### 4.7 企业微信只读提醒 (Stage 9)

**功能：**
- Stage 9 Gate：事件准入检查（真实合约、trigger price、质量 passed 等）
- Stage 9-A：企业微信 payload preview / dry-run（不真实发送）
- Stage 9-B1：受控发送框架（Gate → 发送 → 记录 → 重试）
- Stage 9-B2：单条历史回放 eligible event 生成
- 通知记录：`signal_notifications` 表（attempt_count、retry、HTTP status）
- 脱敏：过滤 webhook / token / password / cookie / secret

**发送流程：**
```text
eligible SignalEvent
-> evaluate_stage9_signal_event_gate()
-> 生成企业微信 markdown payload
-> 读取 QYWX_WEBHOOK_URL
-> 发送 (HTTP POST)
-> 记录 SignalNotification (sent/failed/retry_pending/skipped)
-> 失败最多重试 3 次
```

**当前状态：** 已完成单条历史回放 smoke（event_id=1, HTTP 200, sent）

## 五、策略实现

所有策略为 vn.py `CtaTemplate` 子类，位于 `packages/quant-core/guiyi_quant/strategies/`：

| 策略类 | 核心逻辑 |
|---|---|
| `JmV1bDailyDirectionFastEntryStrategy` | 日线方向确认 + 分钟级快速入场，JM V1B 历史主线 |
| `SuBingEma21VnpyStrategy` | EMA21 趋势跟踪，价格与 EMA21 相对位置判方向，ATR 止损/止盈 |
| `SuBingJmV1bShortHoldStrategy` | 日线方向 + 短持有（持仓 bar 数限制 / 止损止盈） |
| `SuBingJmDailyEma21MacdVolumeStrategy` | EMA21 + MACD + 量能三因子 |
| `SuBingJmDailyScore2Of4Strategy` | 4 因子打分，过 2 分触发 |
| `SuBingJmDailyTrendCrossScore2Strategy` | 继承 Score2Of4，趋势交叉变体 |

策略设计文档位于 `strategies/` 和 `docs/strategy_specs/`。

## 六、数据库模型

PostgreSQL 通过 SQLAlchemy 2 + Alembic 管理，共 18 个迁移版本，涵盖：

| 模块 | 主要表 |
|---|---|
| 数据中心 (24 表) | `DataSource`, `Exchange`, `Instrument`, `Contract`, `TradingCalendar`, `MainContractMap`, `FuturesExFactor`, `FuturesTradingParameter`, `FuturesWarehouseStock`, `FuturesRollYield`, `FuturesMemberRank`, `MarketDataFile`, `DataQualityReport`, `LiveMinuteBar`, `LiveAggregatedBar` 等 |
| 回测 | `BacktestTask`, `BacktestReportModel`, `BacktestTradeModel`, `BacktestOrderModel`, `Watchlist`, `WatchlistItem` |
| 信号 | `SignalScanTask`, `StrategySignal`, `SignalNotification`, `SignalEvent` |
| 复盘 | `ReviewNote`, `ReviewTag`, `ReviewAttachment` |

## 七、WebSocket

| 通道 | 功能 |
|---|---|
| `WS /ws/backtests/{task_no}` | 实时推送回测任务状态快照 |
| `WS /ws/signals` | 实时推送最新信号快照 |

前端 WebSocket 客户端支持自动重连（最多 5 次，3s 间隔）、事件订阅/取消。

## 八、数据资产状态

### JM v2 正式研究数据

| timeframe | rows | range | quality |
|---|---:|---|---|
| 1m | 290,490 | 2023-01-03 → 2026-07-09 | passed |
| 5m | 58,098 | 2023-01-03 → 2026-07-09 | passed |
| 15m | 19,366 | 2023-01-03 → 2026-07-09 | passed |
| 30m | 10,108 | 2023-01-03 → 2026-07-09 | passed |
| 60m | 5,904 | 2023-01-03 → 2026-07-09 | passed |
| 1d | 851 | 2023-01-03 → 2026-07-10 | passed |

### JM2609 真实主力合约试点

- 窗口：2026-07-06 ~ 2026-07-07
- 六周期均 `provider=rqdata, data_role=primary, quality_status=passed`

### 全品种下载

- 90 个候选品种
- 已出现一批 manifest / processed summary
- 当前按"进行中 / 待审计 / 可进入 active"分层管理
- Stage 8.6 全品种 1d：82 products active passed、8 partial；JM 最新主连六周期 6/6 active passed

## 九、当前阶段与路线

### 已完成

- Stage 1-8：数据链路、回测、信号扫描、复盘、Web 工作台
- Stage 8.5：数据主链路 Gate、schema 扩展、真实合约 bars 试点、live 收敛
- Stage 8.6：全品种 active Gate 只读审计
- Stage 9-A：企业微信 preview / dry-run adapter
- Stage 9-B1：受控发送 / 通知记录 / 重试框架
- Stage 9-B2：单条历史回放 smoke（HTTP 200 sent）

### 下一步

| Stage | 内容 |
|---|---|
| Stage 12 | 真实公网 TLS / 访问控制 / systemd 恢复 smoke |
| Stage 13 | Stage 13-G 已完成；下一步仅做样本外验证设计 |
| Data Gate | 8 个全品种 active_partial 独立修复 |
| Runtime | macOS 外接卷后台权限或本机磁盘运行副本决策 |
| Stage 14 | Web 复盘增强 |
| Stage 15 | 可选 Codex git 自动化 |

## 十、安全边界

- 不提交 `.env`、账号、密码、API Key、webhook、token、license
- 企业微信 webhook 只从环境变量 `QYWX_WEBHOOK_URL` 读取
- V1 不接实盘，不自动下单，不把信号直接变成交易指令
- 旧 TqSdk / 天勤、交易练习者数据不进入 active 回测
- `continuous_contract` (jm.MAIN) 只用于研究，不作为真实交易合约
- `actual_contract` 来自 `MainContractMap.rank=1`，不硬编码
- 未通过质量 Gate 的数据不登记为 `data_role=primary`
- live DB 不自动进入 historical active

## 十一、本地启动

```bash
cp .env.example .env
./scripts/dev-up.sh
```

访问地址：
- Web: http://127.0.0.1:5173
- API: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

健康检查：
```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/healthz
```
