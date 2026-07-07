# 归一量化系统架构

生成时间：2026-07-07

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
| 部署 | 本地 Mac、Docker Compose；Cloudflare Access 为后续验收项 |

## 3. 模块分层

```text
apps/quant-web
  Vue Web 工作台：Data / Market / Backtest / Signal / Review

services/quant-api
  FastAPI：REST API、WebSocket、任务创建、查询、复盘
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
- 从回测成交创建复盘 note。
- `/health`、`/api/health`、`/healthz`。

## 6. 当前未完成能力

- RQData 实时 1m 入库。
- 1m 聚合多周期。
- `signal_events` 信号事件化。
- 企业微信只读提醒。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 本地长期运行、worker、scheduler、health check 完整验收。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

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
