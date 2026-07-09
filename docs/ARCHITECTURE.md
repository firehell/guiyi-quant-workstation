# 归一量化系统架构

生成时间：2026-07-09

## 1. 架构定位

归一量化是本地运行的国内期货量化研究工作站。V1 聚焦研究闭环，不做自动实盘。

当前主链路：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

## 2. 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic |
| 任务 | Redis、RQ |
| 数据 | RQData、Local Standard Parquet、DuckDB、PostgreSQL |
| 回测 | vn.py / VeighNa CTA BacktestingEngine、自定义 Adapter / Runner / ResultConverter |
| 部署 | 本地 Mac、Docker Compose；阿里云 Web 托管为当前远程访问设计主线；Cloudflare Access 保留为历史备选 |

## 3. 模块分层

```text
apps/quant-web
  Vue Web 工作台：Data / Market / Backtest / Signal / Runtime / Review
  Market 研究面板：只读展示 RQData 结构化元数据

services/quant-api
  FastAPI：REST API、WebSocket、任务创建、查询、复盘、runtime health
  RQ Worker：回测和后续异步任务
  SQLAlchemy / Alembic：业务事实库和结构化元数据
  DuckDB：读取 standard parquet

packages/quant-core
  vn.py CtaTemplate 策略、策略配置、review tags

data
  raw parquet、standard parquet、manifest、质量报告
```

## 4. 数据边界

active 数据入口只允许：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先使用 `quality_status=passed`。

禁止把以下数据作为正式回测、默认 Market API 或信号输入：

- validation
- legacy_reference
- candidate
- failed
- 旧 TqSdk / 天勤数据
- 交易练习者数据

Stage 8.5 新增数据主链路 Gate：

- `continuous_contract` 只用于研究背景、连续图、日线方向和回测上下文。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 盘后归档必须经过质量 Gate 后才能进入 historical active。
- Stage 9 企业微信前，`signal_events` 必须显式记录真实合约绑定和触发价来源。
- 全品种下载产物必须按 `进行中 -> 待审计 -> 可进入 active` 分层；出现 manifest 或 processed summary 不等于已经通过 active Gate。

## 5. 当前已具备能力

- RQData ingest。
- JM v2 raw / standard parquet。
- manifest、checksum、quality report。
- PostgreSQL `market_data_files` / `data_quality_reports` 登记。
- DuckDB 读取 standard parquet。
- Market K 线查询和 Web K 线工作台。
- vn.py CTA 回测任务、JM V1-B 固定任务。
- 回测报告、资金曲线、回撤曲线、交易明细。
- 批量回测 watchlist 和 WebSocket 进度。
- JM V1-B 信号扫描，只提醒不下单。
- `signal_events` append-only 信号事件账本。
- `strategy_signals` / `signal_events` contract context 显式字段与 API 过滤。
- RQData live 1m 独立表和 5m / 15m / 30m / 60m live 聚合表。
- Web Market 显式 historical / live 模式，默认仍为 historical。
- `live_signal_evaluator` 只读 preview，默认不写正式信号或事件。
- 从回测成交创建复盘 note。
- `/health`、`/api/health`、`/healthz`。
- Web Market 研究面板只读 API：`/api/v1/market/research/*`。
- 全品种下载脚本骨架：metadata、主连 historical、actual-contract roll、research enhancers、audit 分层执行。
- Stage 8.6 全品种 active Gate 只读审计：分层输出 active_passed / active_partial / audit_pending / failed / missing / stage9_blocked。
- Stage 9-A 企业微信只读 preview / dry-run adapter：Gate 通过时返回 markdown payload preview，不真实发送。
- Stage 9-B1 受控发送框架：Gate → 发送 → 通知记录 → 失败重试（最多 3 次），CLI 显式执行。
- Stage 9-B2 单条历史回放 eligible event 生成：已完成 observation-only 真实 smoke（HTTP 200, sent）。
- Stage 10-A / 10-B Web Market 策略展示增强：当前图信号过滤、右侧策略侧栏、signal marker 点击联动、notification 只读状态展示。
- Stage 11-B / 11-C / 11-D 本地运行可观测性：`dev-status`、`dev-healthcheck`、`dev-down`、`GET /api/runtime/health` 和 Web `/runtime` 只读 dashboard。
- Stage 13 可信回测主线复核：只读 trust audit CLI、report/trade/order lineage mapping、JM2609 trading parameter 受控修复和 `report_id=14` lineage mapping 修复。

## 6. 当前未完成能力

- 企业微信真实发送 worker / scheduler / 批量重试。
- 全品种下载结果审计、DB 登记核对和 active Gate 分层最终确认。
- 盘后归档真实写入、worker、scheduler 和长期运行控制面。
- 阿里云 Web 托管设计与远程 health smoke。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 旧报告 lineage backfill、rollover-safe / trusted metrics 复核和样本外验证。
- Stage 14 Web 复盘闭环增强。

## 7. 实盘边界

V1 不实现：

- 自动下单。
- 实盘委托。
- 无人值守交易。
- CTP / TqSdk trading gateway。

后续 V1.5 / V2 如评估交易辅助，必须遵守：

```text
信号 -> 风控检查 -> 人工确认 -> 发单 -> 成交回报 -> 日志归档
```
