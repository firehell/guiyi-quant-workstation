# 归一量化工作站

> 一套面向期货量化交易的全栈研发平台

---

## 快速导航

| 我想做... | 去哪里 |
|---|---|
| 了解项目整体规范 | [`AGENTS.md`](AGENTS.md) |
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
├── docker-compose.yml     一键启动全栈环境
├── .env.example           环境变量模板
│
├── .cursor/rules/         Cursor IDE 规范（自动应用）
├── .agents/skills/        WorkBuddy 技能包
├── .claude/agents/        Claude 评审 Agent
│
├── apps/quant-web/        前端看板（React + Vite）
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
└── tasks/                 任务管理（pending/running/review/done）
```

---

## 一键启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实配置

# 2. 启动全栈服务
docker-compose up -d

# 3. 访问
# 前端：http://localhost:5173
# API：http://localhost:8000
# API 文档：http://localhost:8000/docs
```

---

## 当前进展

见 [`docs/ROADMAP.md`](docs/ROADMAP.md)

- ✅ Phase 0：项目脚手架
- 🚧 Phase 1：数据基础设施
- 📋 Phase 2：回测引擎
- 📋 Phase 3：前端看板
- 📋 Phase 4：实盘对接

---

## 重要提醒

- 🔐 **密钥安全**：所有凭据从 `.env` 读取，`.env` 已加入 `.gitignore`
- 💰 **风控优先**：涉及交易的代码必须经过风控校验，详见 [`docs/RISK_CONTROL.md`](docs/RISK_CONTROL.md)
- 📊 **数据安全**：`data/raw/` 只追加不删除
