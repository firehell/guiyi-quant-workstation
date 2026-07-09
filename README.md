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
| 查看阿里云 Web 托管方案 | `docs/ALIYUN_WEB_HOSTING_PLAN.md` |
| 查看回测口径 | `docs/BACKTEST_ENGINE.md` |
| 查看策略状态 | `docs/STRATEGY_CURRENT_STATE.md` |
| 新 Codex 会话接手 | `docs/CODEX_HANDOFF.md` |
| 查看目录和功能清单 | `docs/PROJECT_INVENTORY.md` |
| 查看 Agent 规则 | `AGENTS.md` |

## 当前阶段

当前已完成到 Stage 13：可信回测主线复核。`report_id=14` 作为 JM V1-B fast-entry 15m 当前样本已通过 `scripts/backtest_trust_audit.py --report-id 14 --format markdown` 只读审计，`audit_status=passed`，所有 checks passed。

该结论只代表当前 `report_id=14` 样本通过 Stage 13 审计，不代表所有历史报告或所有策略完全可信；Stage 13 不是收益优化阶段。

近期已完成：

- JM v2 六周期 raw / standard parquet 已写入并完成质量登记。
- active 数据过滤测试和 Web Data 页面 smoke 已完成代码级闭环。
- RQData live 1m 最小入库、live 多周期聚合、Web Market 显式 live 查看已完成代码级闭环。
- JM V1-B live evaluator preview-only 接口已完成代码级闭环。
- 通达信 XMA PoC 已完成未来函数 / 重绘风险审查，原始 XMA 不进入正式信号链路。
- `signal_events` append-only 信号事件账本已完成代码级闭环。
- Stage 8.5 已完成 schema 最小实现、JM2609 actual-contract 写入试点、Web / live / evaluator 只读收敛和 Stage 9 前 final Gate。
- Stage 8.6 全品种下载结果 active Gate 只读审计已完成代码级闭环（90 products, active_passed=82, active_partial=8）。
- Stage 9-A 企业微信只读 preview / dry-run adapter 已完成。
- Stage 9-B1 受控发送 / 通知记录 / 失败重试框架已完成。
- Stage 9-B2 单条 JM V1-B 历史回放 eligible event 生成 + observation-only 真实 smoke 已完成（HTTP 200, sent）。
- Stage 10-A / 10-B Web Market 策略展示增强已完成：当前图信号过滤、策略侧栏、signal marker 点击联动、关联 `signal_events` 与企业微信 notification 只读状态展示。
- Stage 11-B 本地运行脚本增强已完成：新增只读 `dev-status` / `dev-healthcheck`，并保护 `dev-down` 不误杀非本项目进程。
- Stage 11-C runtime health API 已完成：`GET /api/runtime/health` 只读汇总 DB / Redis / RQ / worker / live checkpoint / notification retry 状态，不启动服务、不写 DB、不发送企业微信。
- Stage 11-D Web runtime dashboard 已完成：`/runtime` 只读展示 DB / Redis / RQ / worker / checkpoint / notification retry 状态，只提供手动刷新。
- Stage 13 已完成可信回测主线复核收口：只读 trust audit、report/trade/order lineage mapping、JM2609 price_tick 受控修复和 `report_id=14` lineage mapping 修复已完成。
- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 中的 RQData 结构化元数据，不改变 K 线 active 读取入口。
- 全品种 RQData 下载已出现一批 manifest / processed summary，但仍按"进行中 / 待审计"处理，不能直接等同于全部进入 active。
- Web 托管当前主线改为阿里云方案；Cloudflare Access 文档保留为历史备选，不再作为当前主线。

下一步：

1. Stage 14：Web 复盘闭环增强，基于 `report_id=14` 这个已通过 trust audit 的样本做只读展示和复盘链路增强。
2. Stage 12：阿里云 Web 托管设计与远程 health smoke，仍为 pending。
3. 全品种 active Gate 最终确认、盘后归档真实写入和企业微信 worker / scheduler / 批量重试仍需独立授权任务。

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
- 回测可信审计：Stage 13 只读 trust audit CLI、report/trade/order lineage mapping、`report_id=14` 当前可信样本。
- 批量回测：watchlist 和 WebSocket 进度能力。
- 信号扫描：JM V1-B 研究信号扫描，只提醒不下单。
- 信号事件账本：`signal_events` append-only 事件化，支持 contract context 显式字段。
- Stage 9 企业微信：只读 preview / dry-run adapter、受控发送 / 通知记录 / 失败重试框架、单条历史回放 smoke 已通过。
- Stage 8.6 全品种 active Gate：只读审计器，分层输出 active_passed / active_partial / audit_pending / failed。
- 复盘中心：从回测成交创建 note、标签和统计。
- 数据链路 Gate：主连研究背景、真实主力触发、live preview、盘后归档边界已冻结到文档。
- 运行状态：`/health`、`/api/health`、`/healthz`、`/api/runtime/health` 和 Web `/runtime` 只读运行状态页面。
- Web 工作台：Data、Market、Backtest、Signal、Runtime、Review 等页面。
- Web 研究面板：`/api/v1/market/research/*` 只读消费主力映射、复权因子、交易参数、仓单、展期收益、合约池、连续合约和会员排名。

## 未完成能力

- 企业微信真实发送 worker / scheduler / 批量重试。
- 全品种下载结果审计、DB 登记核对和 active Gate 分层最终确认。
- 盘后归档真实写入、worker、scheduler 和长期运行控制面。
- 阿里云 Web 托管方案设计与验收。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- Stage 14 Web 复盘闭环增强。

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
curl http://127.0.0.1:8000/api/runtime/health
docker exec guiyi-postgres pg_isready -U guiyi -d guiyi_quant
docker exec guiyi-redis redis-cli ping
```

运行状态检查：

```bash
./scripts/dev-status.sh
./scripts/dev-status.sh --json
./scripts/dev-healthcheck.sh --no-start
./scripts/dev-healthcheck.sh --json --no-start
```

`dev-status` 和 `dev-healthcheck` 都是只读脚本，不启动服务、不写数据库、不触发 RQData、不读取企业微信 webhook。`dev-healthcheck` 会检查 `/api/runtime/health`。`dev-down.sh` 停止 PID 前会校验 PID 命令行包含当前项目路径和对应服务标识，避免误杀非本项目进程。

## 安全边界

- 不提交 `.env`、账号、密码、API Key、webhook、token、license。
- 企业微信 webhook 只能从环境变量读取，例如 `QYWX_WEBHOOK_URL`。
- V1 不接实盘，不自动下单，不把信号直接变成交易指令。
- 旧 TqSdk / 天勤、交易练习者数据和 candidate / validation 数据不得进入 active 回测或信号输入。
