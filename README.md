# 归一量化工作站

> 本地运行的国内期货量化研究、回测、复盘、信号扫描和后期人工确认交易辅助系统。当前重点是 V1 Web 研究闭环，不做自动实盘。

---

## 快速导航

| 我想做... | 去哪里 |
|---|---|
| 了解项目整体规范 | [`AGENTS.md`](AGENTS.md) |
| 新 Codex 账号接手项目 | [`docs/CODEX_HANDOFF.md`](docs/CODEX_HANDOFF.md) + [`tasks/current.md`](tasks/current.md) |
| 查看 Agent 协作流程 | [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md) |
| 查看 V1 重构总控 | [`docs/V1_REFACTOR_VNPY_RQDATA.md`](docs/V1_REFACTOR_VNPY_RQDATA.md) |
| 查看当前 V1-B 阶段完成记录 | [`docs/V1B_JM_3Y_FAST_ENTRY.md`](docs/V1B_JM_3Y_FAST_ENTRY.md) |
| 查看 V1-B 阶段范围 | [`docs/V1B_JM_3Y_SHORT_HOLD.md`](docs/V1B_JM_3Y_SHORT_HOLD.md) |
| 查看 V1 验收和运行清单 | [`docs/V1_ACCEPTANCE.md`](docs/V1_ACCEPTANCE.md) |
| 代码审查（ChatGPT 外部） | [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md) + [`prompts/code-review.md`](prompts/code-review.md) |
| 查看产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 查看系统架构 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 查看数据中心设计 | [`docs/DATA_CENTER.md`](docs/DATA_CENTER.md) |
| 查看回测设计 | [`docs/BACKTEST_ENGINE.md`](docs/BACKTEST_ENGINE.md) |
| 开发新策略 | [`strategies/`](strategies/) + [`docs/BACKTEST_ENGINE.md`](docs/BACKTEST_ENGINE.md) |
| 查看路线图 | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| 查看功能与目录说明 | [`docs/PROJECT_INVENTORY.md`](docs/PROJECT_INVENTORY.md) |
| 查看当前进度 | [`docs/PROJECT_PROGRESS.md`](docs/PROJECT_PROGRESS.md) |
| 报告 Bug | [`prompts/workbuddy-bugfix.md`](prompts/workbuddy-bugfix.md) |
| 创建新任务 | [`tasks/pending/`](tasks/pending/) + [`prompts/task-template.md`](prompts/task-template.md) |

---

## 项目结构

```
guiyi-quant-workstation/
├── AGENTS.md              AI Agent 协作规范（必读）
├── CLAUDE.md              兼容入口，指向 AGENTS.md 和交接文档
├── docker-compose.yml     启动 PostgreSQL / Redis 基础依赖
├── .env.example           环境变量模板
│
├── .cursor/rules/         Cursor IDE 规范（自动应用）
├── .agents/skills/        WorkBuddy 技能包
│
├── apps/quant-web/        自定义 Web 工作台（Vue 3 + Vite + TypeScript + Naive UI）
├── services/quant-api/    后端 API 与任务编排（FastAPI + Redis/RQ）
├── packages/quant-core/   V1 策略、指标、风控、结果格式共享库
│
├── strategies/            期货交易策略
│   ├── su_bing_ema21/    EMA21 趋势跟踪
│   ├── ma_breakout/      均线突破系统
│   └── n_structure/      N 结构形态策略
│
├── data/                  数据存储（RQData raw、standard parquet、validation、legacy_reference）
├── backtests/             回测结果与报告
├── docs/                  设计文档（含 CODEX_HANDOFF.md / AGENT_WORKFLOW.md）
├── prompts/               AI 提示模板（含 code-review.md）
├── tasks/                 任务管理（含 current.md 和 pending/running/review/done）
└── tqsdk-python/          天勤源码本地参考目录（V2 候选调研，不作为 V1 主依赖提交）
```

---

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
docker exec guiyi-postgres pg_isready -U guiyi -d guiyi_quant
docker exec guiyi-redis redis-cli ping
```

### V1 demo / 回测 / 报告

后端 demo：

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --check-env
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --sample
```

回测任务：

```text
POST /api/backtests/tasks
GET  /api/backtests/tasks
GET  /api/backtests/reports
GET  /api/backtests/reports/{report_id}
```

Web 查看：

```text
http://127.0.0.1:5173/backtest
```

完整 V1 验收清单见 [`docs/V1_ACCEPTANCE.md`](docs/V1_ACCEPTANCE.md)。

---

## 当前进展

见 [`docs/ROADMAP.md`](docs/ROADMAP.md) 和 [`docs/V1_REFACTOR_VNPY_RQDATA.md`](docs/V1_REFACTOR_VNPY_RQDATA.md)。

新 Codex 账号或新线程接手时，先读 [`docs/CODEX_HANDOFF.md`](docs/CODEX_HANDOFF.md)、[`tasks/current.md`](tasks/current.md) 和 [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md)，先总结理解和计划，不要直接改代码。

- ✅ Phase 0：工作站脚手架
- ✅ Phase 1：V1 重构统一（文档、数据源口径、vn.py adapter 设计）
- ✅ Phase 2-4：RQData 数据中心、vn.py 回测、Web 研究闭环骨架
- ✅ V1-B：焦煤 JM 3 年真实数据短持有策略闭环
- 🚧 V1-B.1：报告口径加固与验收收尾
- 📋 Phase 5：V1.5 模拟与提醒（仍不自动下单）
- 📋 Phase 6：V2 半自动实盘辅助候选

当前状态：以焦煤 JM 最近 3 年真实数据为样板，已跑通日线定方向、15m / 5m 独立入场、持有 5-8 根本周期 K线、止损退出、回测报告入库、Web 报告/K线复盘和信号扫描提醒闭环。旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再作为当前目标。

V1-B 关键结果：

| 项目 | 结果 |
|---|---|
| 数据范围 | 2023-01-03 至 2025-12-31 |
| 1d / 15m / 5m 行数 | 727 / 16569 / 49707 |
| 15m report_id | 3 |
| 5m report_id | 4 |
| 复盘 note 示例 | `review_id=1`，关联 `report_id=3` / `trade_id=5` |
| 信号扫描 | `POST /api/signals/v1b/jm/scan?run_inline=true`，当前 15m / 5m 均为 `no_signal` |
| 验证 | `pytest` 153 passed，`ruff` passed，`pnpm build` passed |

Web 查看：

```text
15m 报告：http://127.0.0.1:5173/backtest?report_id=3
5m 报告：http://127.0.0.1:5173/backtest?report_id=4
复盘 note：http://127.0.0.1:5173/review?review_id=1
信号扫描：http://127.0.0.1:5173/signal
```

当前未解决问题：浏览器截图级 UI smoke 尚未完成；年化收益、手续费、滑点、最大回撤百分比口径仍需在 V1-B.1 加固；前端 build 保留 `BaseChart` 501.85 kB chunk warning。

---

## 依赖边界

- `rqdatac`：V1 主数据源 SDK。
- `vnpy`：V1 CTA 回测底座。
- `tqsdk`：保留为历史数据验证工具和 V2 模拟 / 半自动实盘候选，不是 V1 默认主链路。
- `tushare`：保留为后期辅助数据候选，不是 V1 默认主链路。
- CTP：不属于 V1；后期如评估也必须走人工确认和风控拦截，不做无人值守自动下单。

当前暂不移动 `tqsdk` / `tushare` 到 optional dependency，以避免影响历史数据模块和测试；后续建议开单独依赖清理任务处理。

`.env.example` 中 TqSdk、TuShare、CTP 字段仅作为禁用占位和后期候选说明；V1 新环境只应按 RQData / Local Parquet 主链路准备数据凭据。

---

## 重要提醒

- 🔐 **密钥安全**：真实凭据只放本地环境变量或未提交配置；不得提交 `.env`、账号、密码、API Key、CTP 密码、米筐账号、天勤账号。
- 💰 **风控优先**：策略、回测、信号必须检查未来函数、数据泄露、过拟合、手续费、滑点、合约乘数、保证金、最大回撤和连续亏损。
- 📊 **数据安全**：V1 正式研究默认读取 `source=rqdata / local_parquet`、`data_role=primary`、`quality_status != failed` 的标准数据。
- 📚 **旧数据隔离**：旧天勤数据只作为 validation source；交易练习者数据只作为 legacy_reference；TuShare 从 V1 主链路移除，后期仅作辅助候选。
- 🧪 **阶段边界**：V1 使用 RQData + Parquet + DuckDB + vn.py CTA 回测 + 自定义 Vue Web；不安装或接入 VeighNa Studio，不从零自研完整回测引擎，不做 tick 高频和自动实盘。
