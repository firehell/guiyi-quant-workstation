# 项目长期记忆 — 归一量化工作站

## 项目基本信息
- **项目名**：归一量化工作站（guiyi-quant-workstation）
- **定位**：面向期货量化交易的全栈研发平台

## 技术栈
- 前端：Vue 3 + TypeScript + Vite + Naive UI + Pinia + Vue Router（K线用 lightweight-charts，图表用 ECharts）
- 后端：Python FastAPI + SQLAlchemy 2.0 + PostgreSQL 16 + Redis 7
- 数据存储：Apache Parquet
- 容器：Docker Compose

## 三个现有策略
1. `su_bing_ema21`：EMA21 均线趋势跟踪
2. `ma_breakout`：均线突破系统
3. `n_structure`：N 结构价格形态识别

## 重要规范
- 资金计算：必须用 `Decimal`，禁止浮点
- 密钥：统一从 `.env` 读取
- 数据：`data/raw/` 只追加不删除
- 颜色：涨红（`#ef4444`）跌绿（`#22c55e`）——A 股习惯

## AI 协作体系
- WorkBuddy 技能：`.agents/skills/`（6 个）
- Claude 评审 Agent：`.claude/agents/`（5 个）
- Cursor 规范：`.cursor/rules/`（5 个）

## 路线图阶段
- Phase 0：脚手架 ✅
- Phase 1：数据基础设施（当前目标）
- Phase 2：回测引擎
- Phase 3：前端看板
- Phase 4：实盘对接
