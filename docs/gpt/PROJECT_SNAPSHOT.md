# PROJECT_SNAPSHOT.md

生成时间：2026-07-09
用途：上传到浏览器 GPT，作为“归一量化开发主控台”的长期项目上下文。

## 1. 项目定位

归一量化是本地运行的国内期货量化研究、数据更新、回测、复盘、信号提醒和人工观察工作站。

当前 V1 只做研究闭环：

```text
数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号提醒 -> 复盘 -> 人工观察
```

项目不是公开 SaaS，不做无人值守自动实盘，不把预警信号直接当成交易指令。

## 2. 当前技术栈

| 层级 | 当前技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic |
| 队列 | Redis、RQ |
| 数据 | RQData、Local Standard Parquet、DuckDB、PostgreSQL |
| 回测 | vn.py / VeighNa CTA BacktestingEngine、自定义 Adapter / Runner / ResultConverter |
| 测试 | pytest、ruff、前端 build / node:test |
| 部署 | 本地 Mac / Docker Compose；阿里云 Web 托管是当前远程访问设计主线，Cloudflare Access 为历史备选 |

TqSdk / 天勤、TuShare、AKShare、CTP 不是 V1 主链路。

## 3. 当前主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

V1 active 数据入口只允许：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status=passed`。

## 4. 当前阶段

当前已完成到 Stage 13：可信回测主线复核。`report_id=14` 作为 JM V1-B fast-entry 15m 当前样本已通过只读 trust audit，`audit_status=passed`，所有 checks passed。

该结论只代表当前 `report_id=14` 样本通过 Stage 13 审计，不代表所有历史报告或所有策略完全可信；Stage 13 不是策略收益优化阶段。

已完成：

- Stage 1 RQData 权限与接口能力 PoC。
- Stage 2 JM 历史数据更新到最新可用交易日。
- Stage 2C：JM v2 raw / standard parquet 写入。
- Stage 2D：manifest / checksum / quality / DB 登记。
- Stage 2E：coverage audit，结论 `can_enter_stage3=true`。
- Stage 3A / 3B：active 数据过滤测试和 Web Data 页面 smoke。
- Stage 4A / 4B / 5：RQData live 1m 骨架和 live 多周期聚合。
- Stage 6A / 6B：Web Market 显式 live 查看和 live evaluator preview-only。
- Stage 7：通达信 XMA 风险审查。
- Stage 8：`signal_events` 信号事件化。
- Stage 8.5-0 到 8.5-9：数据主链路审查、口径冻结、schema 最小实现、JM2609 actual-contract 写入试点、Web / live / evaluator 只读收敛和 Stage 9 前 final Gate。
- Stage 8.6：全品种 active Gate 只读审计（90 products, active_passed=82, active_partial=8）。
- Stage 9-A：企业微信只读 preview / dry-run adapter。
- Stage 9-B1：受控发送 / 通知记录 / 失败重试框架。
- Stage 9-B2：单条历史回放 eligible event 生成 + observation-only 真实 smoke（HTTP 200, sent）。
- Stage 10-A / 10-B：Web Market 策略展示增强、signal marker 点击联动和 notification 只读状态展示。
- Stage 11-B / 11-C / 11-D：本地运行脚本增强、runtime health API 和 Web `/runtime` 只读 dashboard。
- Stage 13-A/B/D/F/G：只读 trust audit、report/trade/order lineage mapping、JM2609 trading parameter 受控修复和 `report_id=14` lineage mapping 修复。
- Web Market 品种研究面板：只读展示本地 PostgreSQL 中的 RQData 结构化元数据。
- 全品种下载已启动并出现一批 manifest / processed summary，当前仍需审计后才能进入 active 结论。

下一步：

1. `Stage 14`：Web 复盘闭环增强，基于 `report_id=14` 可信样本做只读展示和复盘链路增强。
2. `Stage 12`：阿里云 Web 托管设计与远程 health smoke，仍为 pending。
3. 全品种 active Gate 最终确认、盘后归档真实写入、企业微信 worker / scheduler / 批量重试仍需独立授权任务。

## 5. 当前 JM v2 数据

JM v2 数据版本为全窗口 `20230103_20260707_v2`。分钟 bar 最大自然时间为夜盘 `2026-07-06 23:00:00`，最大 `trading_day=2026-07-07`。

| timeframe | rows | min datetime | max datetime | data_version |
|---|---:|---|---|---|
| 1m | 289455 | 2023-01-03 09:01 | 2026-07-06 23:00 | `rqdata_jm_standard_1m_20230103_20260707_v2` |
| 5m | 57891 | 2023-01-03 09:05 | 2026-07-06 23:00 | `rqdata_jm_standard_5m_20230103_20260707_v2` |
| 15m | 19297 | 2023-01-03 09:15 | 2026-07-06 23:00 | `rqdata_jm_standard_15m_20230103_20260707_v2` |
| 30m | 10072 | 2023-01-03 09:30 | 2026-07-06 23:00 | `rqdata_jm_standard_30m_20230103_20260707_v2` |
| 60m | 5883 | 2023-01-03 10:00 | 2026-07-06 23:00 | `rqdata_jm_standard_60m_20230103_20260707_v2` |
| 1d | 847 | 2023-01-03 00:00 | 2026-07-06 00:00 | `rqdata_jm_standard_1d_20230103_20260707_v2` |

六周期均已登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。

关键证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

## 6. 当前目录结构

| 目录 | 作用 |
|---|---|
| `apps/quant-web/` | Vue Web 工作台 |
| `services/quant-api/` | FastAPI、ORM、任务、数据读取、回测、信号、复盘 API |
| `packages/quant-core/` | vn.py CtaTemplate 策略和共享配置 |
| `strategies/` | 策略说明目录 |
| `experiments/` | 隔离 PoC，不属于正式 V1 报告链路 |
| `data/` | 本地数据湖、manifest、质量报告 |
| `docs/` | 当前架构、数据、回测、策略和交接文档 |
| `tasks/` | Codex 任务管理 |
| `scripts/` | 启停、数据同步、审计、导出脚本 |

## 7. 当前核心模块

| 模块 | 关键代码 |
|---|---|
| API 入口 | `services/quant-api/app/main.py` |
| 数据中心 | `services/quant-api/app/api/data_center.py`、`app/data_sources/*`、`app/services/rqdata_ingest/*` |
| K线查询 | `services/quant-api/app/api/market.py`、`app/services/market_data_reader.py` |
| 研究面板 | `services/quant-api/app/api/futures_research.py`、`app/services/futures_research_reader.py` |
| 回测任务 | `services/quant-api/app/api/backtests.py`、`app/backtest/v1b_jm_tasks.py`、`app/tasks/backtests.py` |
| 回测可信审计 | `services/quant-api/app/backtest/trust_audit.py`、`scripts/backtest_trust_audit.py` |
| vn.py 适配 | `services/quant-api/app/vnpy_integration/*` |
| 信号扫描 | `services/quant-api/app/api/signals.py`、`app/signal/jm_v1b.py`、`app/services/signal_scanner.py` |
| 运行状态 | `services/quant-api/app/api/runtime.py`、`app/services/runtime_health.py`、`apps/quant-web/src/pages/runtime/index.vue` |
| 复盘中心 | `services/quant-api/app/api/reviews.py`、`app/review/backtest_trade.py` |
| Web 路由 | `apps/quant-web/src/app/router.ts` |
| K线组件 | `apps/quant-web/src/components/kline/KlineChart.vue` |

## 8. 已具备功能

- 数据中心、RQData ingest、JM v2 parquet / manifest / quality 登记。
- DuckDB 读取 standard parquet。
- Market K 线查询、指标和买卖点 marker。
- vn.py CTA 回测任务、JM V1-B 固定任务、报告、曲线、交易明细。
- 批量回测 watchlist 和 WebSocket 进度。
- JM V1-B 信号扫描，只提醒不下单。
- `signal_events` 信号事件化，支持 contract context 显式字段。
- Stage 9 企业微信：只读 preview / dry-run adapter、受控发送 / 通知记录 / 失败重试框架、单条历史回放 smoke 已通过。
- Stage 8.6 全品种 active Gate 只读审计。
- Stage 10-A / 10-B Web Market 策略展示增强和 notification 只读状态展示。
- Stage 11-B / 11-C / 11-D 只读 runtime health API 与 Web `/runtime` 运行状态面板。
- Stage 13 可信回测主线复核：只读 trust audit、lineage mapping、`report_id=14` 当前可信样本。
- 从回测成交创建复盘 note、标签和统计。
- FastAPI 健康检查和 Vue Web 工作台。
- Web Market 品种研究面板读取主力映射、复权因子、交易参数、仓单、展期收益、合约池、连续合约和会员排名。

## 9. 策略状态

| 策略 | 版本 | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | JM 15m / 5m 固定任务历史主线 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 日线方向 + 15m/5m 短持有研究 spec |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 独立研究版本，trusted 结果为负 |

历史策略和实验只作为研究资产，不作为自动交易依据。

## 10. 未完成能力

- 企业微信真实发送 worker / scheduler / 批量重试。
- 全品种下载结果审计、DB 登记核对和 active Gate 分层最终确认。
- 盘后归档真实写入、worker、scheduler 和长期运行控制面。
- 阿里云 Web 托管设计与远程 health smoke。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 旧报告 lineage backfill、rollover-safe / trusted metrics 复核和样本外验证。
- Stage 14 Web 复盘闭环增强。

## 11. 工作方式约束

- 单功能域拆分。
- 每轮有明确允许和禁止修改范围。
- 高风险任务默认 Plan 模式或先审查。
- 输出可复制给浏览器 GPT 的变更摘要和文件清单。
- 不依赖旧聊天作为当前事实。
- 不提交密钥，不自动下单。
