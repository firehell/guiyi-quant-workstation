# 归一量化工作站

本仓库是本地运行的国内期货量化研究工作站，当前重点是 V1 / V1-B 研究闭环：数据更新、质量检查、K 线查看、策略回测、报告、信号提醒、复盘和人工观察。

项目不是 SaaS，不做无人值守自动实盘，不把信号直接当成实盘交易指令。

## 快速导航

| 我想做... | 文件 |
|---|---|
| 查看当前任务 | `tasks/current.md` |
| 给浏览器 GPT 同步当前状态 | `docs/gpt/CURRENT_STATE.md` |
| 给浏览器 GPT 同步长期项目快照 | `docs/gpt/PROJECT_SNAPSHOT.md` |
| 查看下一步阶段 | `docs/gpt/NEXT_STEPS.md` |
| 查看系统架构 | `docs/ARCHITECTURE.md` |
| 查看数据中心口径 | `docs/DATA_CENTER.md` |
| 查看回测口径 | `docs/BACKTEST_ENGINE.md` |
| 查看策略状态 | `docs/STRATEGY_CURRENT_STATE.md` |
| 新 Codex 会话接手 | `docs/CODEX_HANDOFF.md` |
| 查看目录和功能清单 | `docs/PROJECT_INVENTORY.md` |
| 查看 Agent 规则 | `AGENTS.md` |

## 当前阶段

当前处于 Stage 3 前置状态。

Stage 2C / 2D / 2E 已完成：

- JM v2 六周期 raw / standard parquet 已写入。
- manifest、checksum、quality report 已生成。
- PostgreSQL `market_data_files` / `data_quality_reports` 已登记。
- coverage audit 结论为 `can_enter_stage3=true`。

下一步：

1. `DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS`
2. `WEB-DATA-3B-DATA-PAGE-SMOKE`

## 当前主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

active 数据入口硬约束：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先使用 `quality_status=passed`。

## JM v2 数据状态

JM v2 正式研究数据已更新到最新可用交易日 `2026-07-07`。分钟 bar 最大自然时间为夜盘 `2026-07-06 23:00:00`，对应最大 `trading_day=2026-07-07`。

| timeframe | rows | range | data_version | quality |
|---|---:|---|---|---|
| 1m | 289455 | 2023-01-03 09:01 -> 2026-07-06 23:00 | `rqdata_jm_standard_1m_20230103_20260707_v2` | passed |
| 5m | 57891 | 2023-01-03 09:05 -> 2026-07-06 23:00 | `rqdata_jm_standard_5m_20230103_20260707_v2` | passed |
| 15m | 19297 | 2023-01-03 09:15 -> 2026-07-06 23:00 | `rqdata_jm_standard_15m_20230103_20260707_v2` | passed |
| 30m | 10072 | 2023-01-03 09:30 -> 2026-07-06 23:00 | `rqdata_jm_standard_30m_20230103_20260707_v2` | passed |
| 60m | 5883 | 2023-01-03 10:00 -> 2026-07-06 23:00 | `rqdata_jm_standard_60m_20230103_20260707_v2` | passed |
| 1d | 847 | 2023-01-03 -> 2026-07-06 | `rqdata_jm_standard_1d_20230103_20260707_v2` | passed |

关键证据：

- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

## 当前架构

```text
apps/quant-web/        Vue 3 + Vite + TypeScript + Naive UI Web 工作台
services/quant-api/    FastAPI + SQLAlchemy + Redis/RQ + vn.py 后端
packages/quant-core/   vn.py CtaTemplate 策略和共享策略配置
data/                  raw / standard parquet、manifest、质量报告
docs/                  当前架构、数据、回测、策略和交接文档
scripts/               启停、RQData、审计、导出脚本
tasks/                 当前任务和任务队列
experiments/           隔离 PoC，不属于正式 V1 报告链路
```

## 已具备功能

- 数据中心：RQData ingest、JM v2 parquet、manifest、quality report、DB 登记。
- 数据读取：DuckDB 读取 standard parquet，按 active 入口约束供 Market / Backtest / Signal 使用。
- K 线工作台：多周期 K 线、指标、回测买卖点 marker。
- 回测中心：vn.py CTA 任务、JM V1-B 固定任务、报告、曲线、交易明细。
- 批量回测：watchlist 和 WebSocket 进度能力。
- 信号扫描：JM V1-B 研究信号扫描，只提醒不下单。
- 复盘中心：从回测成交创建 note、标签和统计。
- 健康检查：`/health`、`/api/health`、`/healthz`。
- Web 工作台：Data、Market、Backtest、Signal、Review 等页面。

## 未完成能力

- RQData 实时 1m 入库。
- 1m 聚合 5m / 15m / 30m / 1h / 1d / 1w。
- `signal_events` 信号事件化。
- 企业微信只读提醒。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 本地长期运行、worker、scheduler、health check 完整验收。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 本地启动

```bash
cp .env.example .env
./scripts/dev-up.sh
```

访问：

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000
API docs: http://127.0.0.1:8000/docs
```

基础验收：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/healthz
docker exec guiyi-postgres pg_isready -U guiyi -d guiyi_quant
docker exec guiyi-redis redis-cli ping
```

## 安全边界

- 不提交 `.env`、账号、密码、API Key、webhook、token、license。
- 企业微信 webhook 只能从环境变量读取，例如 `QYWX_WEBHOOK_URL`。
- V1 不接实盘，不自动下单，不把信号直接变成交易指令。
- 旧 TqSdk / 天勤、交易练习者数据和 candidate / validation 数据不得进入 active 回测或信号输入。
