# CODEX_HANDOFF.md — Codex 接手交接

> 本文用于账号切换、线程切换或新的 Codex Agent 接手项目时快速建立上下文。新账号必须先读本文和本文列出的必读文档，先输出理解与计划，再开始修改文件。

---

## 1. 项目定位

归一量化是本地运行的国内期货量化研究、回测、复盘、信号扫描、模拟观察和后期半自动实盘辅助系统。

当前重点是 V1 Web 研究闭环：

```text
数据下载
→ 数据清洗
→ 策略配置
→ 回测验证
→ 回测报告
→ 单笔复盘
→ 信号扫描
→ 人工观察
→ 风控监控
→ 策略迭代
```

V1 不做无人值守自动实盘，不把信号直接变成实盘下单。

---

## 2. 当前 V1 路线

V1 固定路线：

- 主数据源：米筐 RQData。
- 本地数据仓：PostgreSQL + Parquet + DuckDB。
- 回测底座：vn.py / VeighNa CTA BacktestingEngine。
- 后端：FastAPI + SQLAlchemy 2 + Alembic + Redis/RQ。
- 前端：Vue 3 + Vite + TypeScript + Naive UI。
- 图表：TradingView Lightweight Charts + ECharts。
- Web：归一量化自定义 Web 工作台，不使用 VeighNa Studio 作为主产品。
- 天勤 TqSdk：V2 模拟 / 半自动实盘候选，不是 V1 必需主链路。
- TuShare / AKShare：V1 不作为主链路，仅作为后期辅助候选。

V1 主链路：

```text
RQData
→ raw parquet
→ standard parquet
→ market_data_files / data_quality_reports
→ DuckDB / MarketDataReader
→ vn.py CTA 回测
→ ResultConverter
→ PostgreSQL 回测报告
→ Vue Web 展示
→ K线复盘 / 信号扫描 / 人工观察
```

---

## 3. 新 Codex 接手必读

新账号或新线程接手时，按顺序阅读：

1. `AGENTS.md`
2. `docs/CODEX_HANDOFF.md`
3. `tasks/current.md`
4. `docs/ROADMAP.md`
5. `docs/V1_REFACTOR_VNPY_RQDATA.md`
6. `docs/ARCHITECTURE.md`
7. `docs/DATA_CENTER.md`
8. `docs/BACKTEST_ENGINE.md`
9. `docs/AGENT_WORKFLOW.md`
10. `README.md`

如果其中某个文件缺失，先报告缺失项，不要擅自大改。

---

## 4. 账号切换流程

旧账号交接前：

1. 运行 `git status --short`，确认当前工作区状态。
2. 如本次任务已经完成，先做 git checkpoint，由用户或 Cursor 管理提交。
3. 更新 `docs/CODEX_HANDOFF.md`，写明当前路线、状态、风险和下一步。
4. 更新 `tasks/current.md`，写明当前任务、允许修改文件、禁止修改文件、验收标准。
5. 在最终回复中说明修改文件、运行命令、测试命令、风险点和下一步。

新账号接手后：

1. 先读必读文档。
2. 先输出项目理解和接手计划。
3. 明确准备修改哪些文件，以及每个文件准备怎么改。
4. 未经用户确认，不直接改代码。
5. 不依赖历史聊天记忆，以仓库文档和代码为准。

---

## 5. 每次 Codex 任务完成后的交付格式

每次任务完成后必须说明：

1. 实际修改了哪些文件。
2. 为什么这么改。
3. 运行命令。
4. 测试命令。
5. 风险点。
6. 遗留问题。
7. 下一步建议。

如果没有运行某项测试，必须明确说明原因。

---

## 6. 禁止事项

任何 Codex 账号都不得：

1. 把账号、密码、token、license、API Key、CTP 密码、米筐账号、天勤账号写入仓库。
2. 修改或提交 `.env`。
3. 擅自触碰真实数据目录，尤其是 `data/raw/`、`data/parquet/`、`data/processed/`。
4. 做无人值守自动实盘、AI 自动下单或信号直接实盘下单。
5. 大范围重写前端、后端、数据和回测模块。
6. 直接修改 vn.py 源码。
7. 把旧天勤数据或交易练习者数据混入正式回测。
8. 删除旧代码、旧文档或历史数据，除非用户明确要求。

---

## 7. 当前建议下一步

当前优先级仍是单线程推进 V1 研究闭环。新任务开始前应先确认：

- 本次任务属于数据中心、K线、策略、回测、报告、信号、复盘、风控还是系统设置。
- 是否只改一个功能域。
- 是否能本地验证。
- 是否涉及策略/回测/信号风控审查。
- 是否会触碰凭据、真实数据或实盘边界。

默认下一步应围绕 `tasks/current.md` 执行，而不是临时扩展范围。
