# ROADMAP.md — 归一量化产品路线图

> 版本：V1 重构版  
> 当前路线：米筐 RQData + vn.py CTA 回测 + 自定义 Vue Web  
> 当前阶段：V1 真实回测闭环打通阶段

---

## 1. 当前总路线

归一量化 V1 主链路：

```text
米筐 RQData
→ 标准 Parquet 数据湖
→ DuckDB 查询 / 周期合成
→ vn.py CTA 回测
→ 回测结果标准化
→ PostgreSQL 归档
→ Vue Web 报告
→ K线复盘
→ 信号扫描
→ 人工观察
```

V1 不做：

```text
自动实盘
tick 级高频回测
复杂盘口撮合
AI 自动下单
多账户管理
云端 SaaS
手机 App
```

V2 再评估：

```text
vn.py CTP Gateway
天勤 TqSdk
人工确认下单
小资金实盘验证
```

---

## 2. 阶段总览

| 阶段 | 名称 | 目标 |
|---|---|---|
| Phase 0 | 工作站脚手架 | 前后端基础工程、Docker、文档、Agent 协作 |
| Phase 1 | V1 重构统一 | 文档、数据源口径、vn.py adapter 设计统一 |
| Phase 2 | RQData 数据中心 V1 | 米筐数据下载、Parquet、DuckDB、质量检查 |
| Phase 3 | vn.py 回测 V1 | vn.py demo、adapter、苏冰策略、回测任务 |
| Phase 4 | Web 研究闭环 V1 | K线、策略、回测报告、信号、复盘 |
| Phase 4R | V1 真实回测闭环打通 | 标准 Parquet 样本、真实 vn.py 执行、结果入库、Web 真实报告 |
| Phase 5 | V1.5 模拟与提醒 | 人工观察、手工成交、企业微信提醒 |
| Phase 6 | V2 半自动实盘辅助 | CTP / 天勤评估、人工确认、风控拦截 |
| Phase 7 | V3 AI 策略迭代 | AI 总结、归因、版本对比、优化建议 |

---

## 2.1 当前真实状态

当前阶段：

```text
V1 真实回测闭环打通阶段
```

已完成或已有骨架：

- V1 路线已统一为 RQData + Parquet + DuckDB + PostgreSQL + vn.py + FastAPI + Vue Web。
- 数据源抽象、`data_role` 隔离、MarketDataReader / LocalParquetProvider 已存在。
- vn.py adapter、strategy loader、symbol mapper、result converter 已存在。
- 苏冰 EMA21 vn.py 策略草稿已存在。
- 回测任务 API、RQ worker 函数、Web 回测任务页和报告页已有骨架。
- 信号扫描、复盘中心、K线 marker 展示路径已有骨架。

尚未完成：

- 真实 vn.py `BacktestingEngine` 尚未执行，当前 runner 仍是 `prepared/executed=false`。
- 标准 Parquet 样本数据到真实 vn.py 回测的最小链路尚未打通。
- vn.py raw result 到 `backtest_reports`、`backtest_trades`、`equity_curve`、`drawdown_curve` 的持久化尚未闭环。
- 本地 DB migration 未对齐，已观察到 `backtest_tasks.engine_type` 缺列风险。
- Python 版本口径已统一为 Python 3.13；后续新环境按 3.13 准备。

本阶段仍然不做：

```text
自动实盘
自动下单
CTP / TqSdk 交易接口
新策略
参数优化
多品种批量回测
AI 策略生成
Web 大屏扩展
```

---

## 3. Phase 0 — 工作站脚手架

状态：基本完成。

已具备：

- 项目目录。
- FastAPI 基础服务。
- Vue 3 / Vite / TypeScript / Naive UI 前端壳子。
- Docker Compose PostgreSQL / Redis。
- Alembic 初始化。
- 基础页面路由。
- API client。
- Pinia store。
- sample K线组件。
- ECharts 包装。
- WebSocket client。
- 初始策略目录。
- Agent 协作规则。

待补：

- P0-001 文档统一收尾。
- P0-002 外部审查文档一致性（ChatGPT）。

---

## 4. Phase 1 — V1 重构统一

目标：

```text
先统一文档和架构边界，不急着大改代码
```

状态：已推进到代码骨架阶段，仍需外部审查和状态对齐。

已完成：

- [x] 更新 `AGENTS.md`。
- [x] 移除 `CLAUDE.md`，新增 `docs/CODE_REVIEW.md`。
- [x] 更新 `README.md`。
- [x] 更新 `packages/quant-core/README.md`。
- [x] 更新 `docs/PRD.md`。
- [x] 更新 `docs/ARCHITECTURE.md`。
- [x] 更新 `docs/DATA_CENTER.md`。
- [x] 更新 `docs/BACKTEST_ENGINE.md`。
- [x] 更新 `docs/ROADMAP.md`。
- [x] 更新 `docs/V1_REFACTOR_VNPY_RQDATA.md`。
- [x] 明确 RQData 是 V1 主数据源。
- [x] 明确 vn.py 是 V1 回测底座。
- [x] 明确天勤是 V2 实盘候选。
- [x] 明确 TuShare 从 V1 移除。
- [x] 明确旧数据处理策略。
- [x] 明确 V1 不做实盘。

待补：

- [ ] 外部审查文档一致性（ChatGPT）。
- [ ] `tasks/current.md`、`docs/ROADMAP.md`、`docs/V1_REFACTOR_VNPY_RQDATA.md` 与当前真实回测闭环阶段保持同步。

验收：

```text
[ ] 全部文档路线一致
[ ] 不再把天勤写成 V1 主数据源
[ ] 不再把自研完整回测引擎写成 V1 主路径
[ ] 明确不依赖 VeighNa Studio
[ ] 明确旧数据隔离
```

---

## 5. Phase 2 — RQData 数据中心 V1

目标：

```text
把米筐数据变成 V1 正式本地数据资产
```

状态：已有数据源抽象和读取骨架，真实 RQData 资产仍需样本链路验证。

已完成或已有骨架：

- [x] 梳理现有 RQData ingest。
- [x] 新增或整理 `data_sources/rqdata_provider.py`。
- [x] 新增 `data_sources/local_parquet_provider.py`。
- [x] 新增 `data_sources/legacy_data_provider.py`。
- [x] 标准化 `data_role`。
- [x] `MarketDataReader` 支持 Parquet / DuckDB 查询路径。
- [x] 明确 primary / validation / legacy_reference。

待补：

- [ ] 用标准 Parquet 样本验证正式回测读取链路。
- [ ] 对齐本地 DB migration，避免模型字段与数据库缺列。
- [ ] 完善 `market_data_files` 与 `data_quality_reports` 的真实样本验收。
- [ ] 早期米筐数据清洗并入标准数据湖。
- [ ] 天勤旧数据标记为 validation。
- [ ] 交易练习者数据标记为 legacy_reference。
- [ ] 完成 1m → 多周期合成规则设计。
- [ ] DuckDB 查询封装。
- [ ] 数据中心 Web 展示数据覆盖情况。

验收：

```text
[ ] RQData 数据能落 raw parquet
[ ] standard parquet 可查询
[ ] market_data_files 有索引
[ ] data_quality_reports 有报告
[ ] 正式回测默认只读 primary 数据
[ ] legacy 数据不会混入正式回测
```

---

## 6. Phase 3 — vn.py 回测 V1

目标：

```text
用 vn.py 跑通第一条策略回测链路
```

状态：adapter 和 demo 骨架已完成，真实 `BacktestingEngine` 执行尚未打通。

已完成或已有骨架：

- [x] 新增 `experiments/vnpy_rqdata_demo/`。
- [x] 检测本机是否已有 vn.py；未安装时只提示。
- [x] 新增 `vnpy_integration/`。
- [x] 实现 `symbol_mapper.py`。
- [x] 实现 `strategy_loader.py`。
- [x] 实现 `backtest_runner.py` 当前准备 vn.py setting，但仍返回 `prepared/executed=false`。
- [x] 实现 `result_converter.py`。
- [x] 实现苏冰 EMA21 vn.py 策略草稿。
- [x] demo 样例模式可输出标准化 JSON。

待补：

- [ ] 验证读取本地标准 Parquet 样本 K线。
- [ ] 接真实 vn.py `BacktestingEngine` 执行。
- [ ] 执行一次单品种、单周期、苏冰 EMA21 真实回测。
- [ ] 输出真实 trades / statistics / equity_curve / drawdown_curve。
- [ ] 将真实回测结果转换为归一量化统一 JSON。
- [ ] 外部审查未来函数和成交撮合（ChatGPT）。

验收：

```text
[ ] vn.py demo 可运行
[ ] 能读取 standard parquet
[ ] 能执行一次单品种单周期回测
[ ] 能输出 trades
[ ] 能输出 statistics
[ ] 能转换为归一量化统一 JSON
[ ] 没有自动实盘逻辑
```

---

## 7. Phase 4 — Web 研究闭环 V1

目标：

```text
通过 Vue Web 完成数据、K线、策略、回测、报告、信号、复盘闭环
```

状态：Web/API/信号/复盘/报告页面已有骨架，真实报告数据链路尚未完全闭环。

已完成或已有骨架：

- [x] 数据中心页面接 API 骨架。
- [x] K线工作台接 MarketDataReader 路径。
- [x] 回测任务页面接任务 API。
- [x] 回测报告页面可展示标准化结果结构。
- [x] 交易明细表接 `backtest_trades` 结构。
- [x] K线图显示买卖点 marker 结构。
- [x] 信号扫描页面接 signals API。
- [x] 复盘页面接 review_notes API。

待补：

- [ ] 策略中心接正式策略版本 API。
- [ ] 回测报告页面展示真实 vn.py 回测入库结果。
- [ ] K线 marker 显示真实 backtest trades 买卖点。
- [ ] 风控统计展示最大回撤、连亏、保证金占用。

验收：

```text
[ ] Web 能创建回测任务
[ ] Web 能查看任务状态
[ ] Web 能查看回测报告
[ ] Web 能查看资金曲线
[ ] Web 能查看回撤曲线
[ ] Web 能查看交易明细
[ ] K线能显示买卖点
[ ] 信号列表可查询
[ ] 单笔复盘可记录
```

---

## 8. Phase 5 — V1.5 模拟与提醒

目标：

```text
从研究进入执行前验证，但仍不自动下单
```

任务：

- [ ] 信号扫描定时任务。
- [ ] 企业微信提醒候选。
- [ ] 人工观察状态。
- [ ] 手工录入实际成交。
- [ ] 理论成交 vs 实际成交对比。
- [ ] 执行偏差统计。
- [ ] 模拟盘接口调研。

不做：

- 自动实盘。
- 无人值守交易。
- 实盘账户下单。

---

## 9. Phase 6 — V2 半自动实盘辅助

目标：

```text
在策略经过回测、模拟和小资金验证后，再评估半自动实盘
```

候选方案：

```text
方案 A：vn.py CTP Gateway
方案 B：天勤 TqSdk
方案 C：继续人工下单
```

V2 优先路径：

```text
信号
→ 风控检查
→ 人工确认
→ 发单
→ 成交回报
→ 日志归档
```

任务：

- [ ] vn.py CTP Gateway 调研。
- [ ] 天勤 TqSdk 实盘接入调研。
- [ ] BrokerAdapter 抽象。
- [ ] ManualBrokerAdapter。
- [ ] 风控拦截。
- [ ] 人工确认页面。
- [ ] 小资金实盘验证流程。

---

## 10. Phase 7 — V3 AI 策略迭代

目标：

```text
AI 作为研究助理、复盘助理、代码助理，不作为自动交易员
```

任务：

- [ ] AI 总结回测报告。
- [ ] AI 归因亏损交易。
- [ ] AI 对比策略版本。
- [ ] AI 生成优化建议。
- [ ] AI 辅助生成测试用例。
- [ ] AI 辅助生成文档。

禁止：

- AI 自动下单。
- AI 自动上线策略。
- AI 绕过回测和模拟验证。

---

## 11. 当前最近执行顺序

当前建议 Codex 单线程执行：

```text
P1R-001 更新任务状态和路线图
P1R-002 只读检查 Alembic head 与本地 DB 状态，形成 migration 对齐方案
P1R-003 准备标准 Parquet 样本数据 fixture，不触碰真实 data/
P1R-004 接真实 vn.py BacktestingEngine 执行
P1R-005 打通 normalized result 到 reports / trades / equity_curve / drawdown_curve 持久化
P1R-006 FastAPI 查询真实报告与交易明细
P1R-007 Vue Web 展示真实报告、资金曲线、回撤曲线
P1R-008 K线显示真实 backtest trades 买卖点 marker
P1R-009 回测严谨性审查：未来函数、成交时点、手续费、滑点、合约乘数、保证金、回撤和连亏
```

每一步仍然必须保持 V1 边界：

```text
不接实盘
不接 CTP / TqSdk 交易接口
不自动下单
不新增策略
不做参数优化
不做多品种批量回测
```

---

## 12. Backlog

- 多品种批量回测。
- 参数优化。
- 样本内 / 样本外拆分。
- 策略版本对比。
- 品种适配评分。
- 企业微信提醒。
- 模拟账户接入。
- vn.py CTP 接入。
- 天勤 TqSdk 接入评估。
- AI 回测总结。
- AI 亏损归因。
