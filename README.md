# 归一量化工作站

> 本地运行的国内期货量化研究、回测、复盘、信号扫描和后期人工确认交易辅助系统。当前重点是 V1 Web 研究闭环，不做自动实盘。

---

## 快速导航

| 我想做... | 去哪里 |
|---|---|
| 了解项目整体规范 | [`AGENTS.md`](AGENTS.md) |
| 查看 V1 重构总控 | [`docs/V1_REFACTOR_VNPY_RQDATA.md`](docs/V1_REFACTOR_VNPY_RQDATA.md) |
| 开始开发（Claude Code 用户） | [`CLAUDE.md`](CLAUDE.md) |
| 查看产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 查看系统架构 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 查看数据中心设计 | [`docs/DATA_CENTER.md`](docs/DATA_CENTER.md) |
| 查看回测设计 | [`docs/BACKTEST_ENGINE.md`](docs/BACKTEST_ENGINE.md) |
| 开发新策略 | [`strategies/`](strategies/) + [`docs/BACKTEST_ENGINE.md`](docs/BACKTEST_ENGINE.md) |
| 查看路线图 | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| 报告 Bug | [`prompts/workbuddy-bugfix.md`](prompts/workbuddy-bugfix.md) |
| 创建新任务 | [`tasks/pending/`](tasks/pending/) + [`prompts/task-template.md`](prompts/task-template.md) |

---

## 项目结构

```
guiyi-quant-workstation/
├── AGENTS.md              AI Agent 协作规范（必读）
├── CLAUDE.md              Claude Code 专用指南
├── docker-compose.yml     启动 PostgreSQL / Redis 基础依赖
├── .env.example           环境变量模板
│
├── .cursor/rules/         Cursor IDE 规范（自动应用）
├── .agents/skills/        WorkBuddy 技能包
├── .claude/agents/        Claude 评审 Agent
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
├── docs/                  设计文档
├── prompts/               AI 提示模板
├── tasks/                 任务管理（pending/running/review/done）
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

---

## 当前进展

见 [`docs/ROADMAP.md`](docs/ROADMAP.md) 和 [`docs/V1_REFACTOR_VNPY_RQDATA.md`](docs/V1_REFACTOR_VNPY_RQDATA.md)。

- ✅ Phase 0：工作站脚手架
- 🚧 Phase 1：V1 重构统一（文档、数据源口径、vn.py adapter 设计）
- 📋 Phase 2：RQData 数据中心 V1
- 📋 Phase 3：vn.py 回测 V1
- 📋 Phase 4：Web 研究闭环 V1
- 📋 Phase 5：V1.5 模拟与提醒（仍不自动下单）
- 📋 Phase 6：V2 半自动实盘辅助候选

当前真实状态：脚手架可运行，RQData 结构化下载已有基础，前后端已有研究工作台壳子；下一步按单线程顺序推进文档统一、实验目录、data_sources、vnpy_integration、策略、API、Web。

---

## 重要提醒

- 🔐 **密钥安全**：真实凭据只放本地环境变量或未提交配置；不得提交 `.env`、账号、密码、API Key、CTP 密码、米筐账号、天勤账号。
- 💰 **风控优先**：策略、回测、信号必须检查未来函数、数据泄露、过拟合、手续费、滑点、合约乘数、保证金、最大回撤和连续亏损。
- 📊 **数据安全**：V1 正式研究默认读取 `source=rqdata / local_parquet`、`data_role=primary`、`quality_status != failed` 的标准数据。
- 📚 **旧数据隔离**：旧天勤数据只作为 validation source；交易练习者数据只作为 legacy_reference；TuShare 从 V1 主链路移除，后期仅作辅助候选。
- 🧪 **阶段边界**：V1 使用 RQData + Parquet + DuckDB + vn.py CTA 回测 + 自定义 Vue Web；不安装或接入 VeighNa Studio，不从零自研完整回测引擎，不做 tick 高频和自动实盘。
