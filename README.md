# 归一量化工作站

> 本地运行的国内期货量化研究、回测、复盘、信号扫描、模拟交易和后期半自动实盘辅助系统。

---

## 快速导航

| 我想做... | 去哪里 |
|---|---|
| 了解项目整体规范 | [`AGENTS.md`](AGENTS.md) |
| 查看新版项目总控 | [`docs/归一量化_Codex从零搭建总控文档_V1.md`](docs/归一量化_Codex从零搭建总控文档_V1.md) |
| 查看项目大纲 | [`docs/PROJECT_BOOK.md`](docs/PROJECT_BOOK.md) |
| 查看当前进度 | [`docs/PROJECT_PROGRESS.md`](docs/PROJECT_PROGRESS.md) |
| 开始开发（Claude Code 用户） | [`CLAUDE.md`](CLAUDE.md) |
| 查看产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 查看系统架构 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
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
├── apps/quant-web/        前端看板（Vue 3 + Vite）
├── services/quant-api/    后端 API（Python FastAPI）
├── packages/quant-core/   共享量化核心库
│
├── strategies/            期货交易策略
│   ├── su_bing_ema21/    EMA21 趋势跟踪
│   ├── ma_breakout/      均线突破系统
│   └── n_structure/      N 结构形态策略
│
├── data/                  数据存储（raw/processed/parquet/sample）
├── backtests/             回测结果与报告
├── docs/                  设计文档
├── prompts/               AI 提示模板
├── tasks/                 任务管理（pending/running/review/done）
└── tqsdk-python/          天勤源码本地参考目录（不提交）
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

见 [`docs/PROJECT_PROGRESS.md`](docs/PROJECT_PROGRESS.md) 和 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

- ✅ Phase 0：工作站脚手架
- 🚧 Phase 1：数据中心 V0
- 📋 Phase 2：策略与回测 V0
- 📋 Phase 3：Web 研究闭环
- 📋 Phase 4：模拟与提醒，V1.5
- 📋 Phase 5：半自动实盘辅助，V2

当前真实状态：脚手架可运行，文档体系较完整，后端和前端仍以最小接口与页面壳子为主，业务闭环待实现。

---

## 重要提醒

- 🔐 **密钥安全**：复制 `.env.example` 为 `.env` 后填入真实凭据；`.env` 已加入 `.gitignore`，`.env.example` 仅含占位符
- 💰 **风控优先**：涉及交易的代码必须经过风控校验，详见 [`docs/RISK_CONTROL.md`](docs/RISK_CONTROL.md)
- 📊 **数据安全**：`data/raw/` 只追加不删除
- 📚 **TqSdk 源码参考**：`tqsdk-python/` 只用于本地查阅天勤源码、函数和示例，不作为项目代码提交
- 🧪 **阶段边界**：V0/V1 只做研究闭环，不做全自动实盘
