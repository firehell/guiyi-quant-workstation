# 归一量化工作站

> 本地运行的国内期货量化研究、回测、复盘、信号扫描和后期人工确认交易辅助系统。当前重点是 V1 Web 研究闭环，不做自动实盘。

## 快速导航

| 我想做... | 去哪里 |
|---|---|
| 了解项目整体规范 | [`AGENTS.md`](AGENTS.md) |
| 查看当前状态速览 | [`CURRENT_STATE.md`](CURRENT_STATE.md) |
| 给浏览器 GPT 同步完整项目上下文 | [`PROJECT_SNAPSHOT.md`](PROJECT_SNAPSHOT.md) + [`docs/CODEX_HANDOFF_FOR_CHATGPT.md`](docs/CODEX_HANDOFF_FOR_CHATGPT.md) |
| 新 Codex 账号接手项目 | [`docs/CODEX_HANDOFF.md`](docs/CODEX_HANDOFF.md) + [`tasks/current.md`](tasks/current.md) |
| 查看下一步任务顺序 | [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md) |
| 查看 Agent 协作流程 | [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md) + [`docs/AI_DEVELOPMENT_WORKFLOW.md`](docs/AI_DEVELOPMENT_WORKFLOW.md) |
| 查看产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 查看系统架构 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 查看数据中心设计 | [`docs/DATA_CENTER.md`](docs/DATA_CENTER.md) |
| 查看回测设计 | [`docs/BACKTEST_ENGINE.md`](docs/BACKTEST_ENGINE.md) |
| 查看策略研究状态 | [`docs/STRATEGY_CURRENT_STATE.md`](docs/STRATEGY_CURRENT_STATE.md) |
| 查看功能与目录说明 | [`docs/PROJECT_INVENTORY.md`](docs/PROJECT_INVENTORY.md) |
| 查看远程浏览器访问口径 | [`docs/CLOUDFLARE_WORKSTATION_ACCESS.md`](docs/CLOUDFLARE_WORKSTATION_ACCESS.md) |
| 代码审查（ChatGPT 外部） | [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md) + [`prompts/code-review.md`](prompts/code-review.md) |

## 项目结构

```text
guiyi-quant-workstation/
├── AGENTS.md              AI Agent 协作规范（必读）
├── CLAUDE.md              兼容入口，指向 AGENTS.md 和交接文档
├── CURRENT_STATE.md       当前状态速览（给 GPT / Codex）
├── PROJECT_SNAPSHOT.md    长期项目上下文（给 GPT）
├── docker-compose.yml     启动 PostgreSQL / Redis 基础依赖
├── .env.example           环境变量模板
│
├── apps/quant-web/        自定义 Web 工作台（Vue 3 + Vite + TypeScript + Naive UI）
├── services/quant-api/    后端 API 与任务编排（FastAPI + Redis/RQ）
├── packages/quant-core/   V1 策略、指标、风控、结果格式共享库
├── strategies/            策略说明目录
├── experiments/           隔离 PoC（RQAlpha / XMA 等，不属于正式 V1 报告链路）
├── data/                  数据存储（RQData raw、standard parquet、manifest、质量报告）
├── backtests/             回测结果与报告
├── docs/                  设计文档（含交接、路线、远程访问文档）
├── prompts/               AI 提示模板
├── tasks/                 任务管理（含 current.md 和 pending/running/review/done）
└── scripts/               开发启停、数据同步、审计、导出脚本
```

## 当前状态

当前主链路：

```text
RQData / Local Standard Parquet
-> DuckDB
-> vn.py CTA BacktestingEngine
-> ResultConverter
-> PostgreSQL
-> FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察 / 交易复盘
```

当前关键事实：

| 项目 | 当前状态 |
|---|---|
| active 数据入口 | `rqdata` / `local_parquet` + `primary` + `quality_status != failed` |
| 旧 TqSdk / 交易练习者 active 数据 | 已移除 |
| JM 数据窗口 | 2023-01-03 至 2025-12-31 |
| 主回测底座 | vn.py / VeighNa CTA BacktestingEngine |
| Web 工作台 | Vue 3 + Vite + TypeScript + Naive UI |
| 本地健康检查 | `/health`、`/api/health`、`/healthz` |
| 远程访问 | Cloudflare Tunnel + Access，仅 Web/API，不暴露 shell |
| 下一步 | RQData 权限与接口能力 PoC |

详见 [`CURRENT_STATE.md`](CURRENT_STATE.md) 和 [`PROJECT_SNAPSHOT.md`](PROJECT_SNAPSHOT.md)。

## 本地启动

### 一键启动（推荐）

```bash
# 首次：配置环境变量（脚本也会自动从 .env.example 复制）
cp .env.example .env

# 启动 Docker + 后端 API + RQ Worker + 前端（后台运行）
./scripts/dev-up.sh

# 查看 API 日志
tail -f .run/logs/api.log

# 停止全部服务
./scripts/dev-down.sh

# 仅停应用进程，保留 PostgreSQL / Redis
./scripts/dev-down.sh --keep-docker
```

### 手动分步启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实配置

# 2. 启动基础依赖
docker compose up -d

# 3. 启动后端 API
cd services/quant-api
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 4. 另开终端启动前端
cd apps/quant-web
pnpm dev --host 127.0.0.1 --port 5173
```

访问地址：

```text
前端：http://127.0.0.1:5173
API：http://127.0.0.1:8000
API 文档：http://127.0.0.1:8000/docs
```

基础运行验收：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:5173/healthz
docker exec guiyi-postgres pg_isready -U guiyi -d guiyi_quant
docker exec guiyi-redis redis-cli ping
```

远程浏览器访问使用 Cloudflare Tunnel + Access，配置口径见 [`docs/CLOUDFLARE_WORKSTATION_ACCESS.md`](docs/CLOUDFLARE_WORKSTATION_ACCESS.md)。

## 关键页面和 API

关键页面：

```text
http://127.0.0.1:5173/data
http://127.0.0.1:5173/market
http://127.0.0.1:5173/backtest
http://127.0.0.1:5173/signal
http://127.0.0.1:5173/review
```

关键 API：

- `POST /api/backtests/tasks`
- `POST /api/backtests/v1b/jm/15m/tasks`
- `POST /api/backtests/v1b/jm/5m/tasks`
- `POST /api/backtests/v1b/jm/daily-ema21-macd-volume/tasks`
- `POST /api/backtests/v1b/jm/daily-score2of4/tasks`
- `GET /api/backtests/reports`
- `GET /api/backtests/reports/{report_id}/trades`
- `POST /api/signals/v1b/jm/scan?run_inline=true`
- `POST /api/reviews/from-backtest-trade/{trade_id}`

## 当前策略状态

主要策略版本：

| 策略 | 版本 | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | JM 15m / 5m 固定任务主线 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 日线方向 + 15m/5m 短持有研究 spec |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 日线 2/4 条件研究版本，trusted 结果为负 |

策略研究状态详见 [`docs/STRATEGY_CURRENT_STATE.md`](docs/STRATEGY_CURRENT_STATE.md)。

## 实验目录说明

`experiments/` 下有独立 PoC：

- `experiments/rqalpha_su_bing_jm_daily/`：RQAlpha Plus 上的苏冰 JM 日线规则实验。
- `experiments/rqalpha_tdx_xma_bands/`：通达信 XMA 通道策略实验，明确存在未来函数 / 重绘风险。

这些实验不入 PostgreSQL，不走 vn.py 主链路，不等同于正式可信回测报告。

## 依赖边界

- `rqdatac`：V1 主数据源 SDK。
- `vnpy`：V1 CTA 回测底座。
- `tqsdk`：已从当前 V1 active 数据链路和依赖中移除；后续仅可作为 future backup 单独评估。
- `tushare`：保留为后期辅助数据候选，不是 V1 默认主链路。
- CTP：不属于 V1；后期如评估也必须走人工确认和风控拦截，不做无人值守自动下单。

`.env.example` 中 TqSdk、TuShare、CTP 字段仅作为禁用占位和后期候选说明；V1 新环境只应按 RQData / Local Parquet 主链路准备数据凭据。

## 重要提醒

- 密钥安全：真实凭据只放本地环境变量或未提交配置；不得提交 `.env`、账号、密码、API Key、CTP 密码、米筐账号、天勤账号。
- 风控优先：策略、回测、信号必须检查未来函数、数据泄露、过拟合、手续费、滑点、合约乘数、保证金、最大回撤和连续亏损。
- 数据安全：V1 正式研究默认读取 `source=rqdata / local_parquet`、`data_role=primary`、`quality_status != failed` 的标准数据。
- 旧数据移除：旧天勤数据、交易练习者数据和 TqSdk 临时下载文件已从当前 active 数据体系移除。
- 阶段边界：V1 使用 RQData + Parquet + DuckDB + vn.py CTA 回测 + 自定义 Vue Web；不安装或接入 VeighNa Studio，不从零自研完整回测引擎，不做 tick 高频和自动实盘。
