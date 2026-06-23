# 归一量化系统架构

> 全局总控：`docs/归一量化_Codex从零搭建总控文档_V1.md`
> 数据细节：`docs/DATA_CENTER.md`

## 技术栈

前端：

- Vue 3
- Vite
- TypeScript
- Naive UI
- Pinia
- Vue Router
- Axios
- TradingView Lightweight Charts
- ECharts / vue-echarts
- WebSocket

后端：

- FastAPI
- SQLAlchemy 2
- Alembic
- Pydantic / pydantic-settings
- pandas / Polars
- Redis + RQ
- APScheduler / RQ Scheduler
- pytest
- ruff + mypy

数据：

- TqSdk / 天勤专业版：核心目标数据源。
- RQData / Tushare / AKShare：补充适配或交叉校验。
- PostgreSQL：元数据、策略、任务、报告、信号、复盘、风控。
- Parquet：历史 K 线、tick、大体量行情文件。
- DuckDB：本地研究查询、批量统计、回测读取。

部署：

- 本地 Mac / 本地工作站。
- Docker Compose。
- 第一版不上云。

## 业务分层

```text
数据中心 Data Center
→ 行情中心 Market Center
→ 策略中心 Strategy Center
→ 信号中心 Signal Center
→ 风控中心 Risk Center
→ 回测中心 Backtest Center
→ 交易中心 Trade Center
→ 执行中心 Execution Center
→ 复盘中心 Review Center
```

核心约束：

- 数据中心只负责数据源、合约、交易日历、K线和质量检查，不生成交易信号。
- 策略中心只负责策略版本、参数模板和信号计算，不直接下单。
- 信号中心只记录信号快照、状态机和扫描结果，不绕过风控。
- 风控中心负责单笔风险、保证金、日亏损、连续亏损和持仓限制。
- 回测中心负责历史撮合、报告和交易卡片，不代表实盘结果。
- 执行中心必须保留人工确认，不允许无人值守实盘。

## 标准数据流

```text
外部数据源
→ Source Adapter
→ Raw Zone
→ Normalize Layer
→ Quality Check
→ PostgreSQL / Parquet / DuckDB
→ MarketDataReader
→ 策略信号
→ 回测成交
→ 回测报告
→ 信号扫描
→ 单笔复盘
```

交易辅助链路后置到 V1.5 / V2：

```text
signal_snapshot
→ trade_intent
→ risk_check
→ manual_confirmation
→ order
→ trade
→ position
→ review_note
```

## 当前实现状态

已具备：

- Docker Compose 的 PostgreSQL / Redis。
- FastAPI 最小服务和健康检查。
- Vue 3 / Vite / TypeScript / Naive UI 前端壳子。
- 路由页面、API client、Pinia store、sample K线组件、ECharts 包装、WebSocket client。
- Alembic 初始化。

尚未具备：

- 数据源适配器。
- 真实 K 线下载、Parquet 写入和 DuckDB 查询。
- SQLAlchemy 业务模型和 Alembic 业务迁移。
- 回测引擎、策略状态机、信号扫描、复盘和风控计算。
- 后端 WebSocket 和模拟交易链路。

## 安全边界

- TqSdk 账号、交易账号、API token、Webhook 只读环境变量。
- `tqsdk-python/` 只作为本地源码参考目录，不提交到项目仓库。
- V0/V1 不做全自动实盘。
- 回测默认检查未来函数、数据泄露、过拟合、交易成本、保证金和回撤。
