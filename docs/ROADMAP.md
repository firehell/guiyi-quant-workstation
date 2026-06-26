# ROADMAP.md — 归一量化产品路线图

> 版本：V1 重构版  
> 当前路线：米筐 RQData + vn.py CTA 回测 + 自定义 Vue Web  
> 当前阶段：Phase 1 / P0-001 文档统一

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
| Phase 5 | V1.5 模拟与提醒 | 人工观察、手工成交、企业微信提醒 |
| Phase 6 | V2 半自动实盘辅助 | CTP / 天勤评估、人工确认、风控拦截 |
| Phase 7 | V3 AI 策略迭代 | AI 总结、归因、版本对比、优化建议 |

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

任务：

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
- [ ] 外部审查文档一致性（ChatGPT）。

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

任务：

- [ ] 梳理现有 RQData ingest。
- [ ] 新增或整理 `data_sources/rqdata_provider.py`。
- [ ] 新增 `data_sources/local_parquet_provider.py`。
- [ ] 新增 `data_sources/legacy_data_provider.py`。
- [ ] 标准化 `data_role`。
- [ ] 完善 `market_data_files`。
- [ ] 完善 `data_quality_reports`。
- [ ] 明确 primary / validation / legacy_reference。
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

任务：

- [ ] 新增 `experiments/vnpy_rqdata_demo/`。
- [ ] 检测本机是否已有 vn.py；未安装时只提示，不在 P0/P1-001 自动安装或修改依赖。
- [ ] 验证最小 CTA 回测。
- [ ] 验证读取本地标准 K线。
- [ ] 新增 `vnpy_integration/`。
- [ ] 实现 `symbol_mapper.py`。
- [ ] 实现 `strategy_loader.py`。
- [ ] 实现 `backtest_runner.py`。
- [ ] 实现 `result_converter.py`。
- [ ] 新增 `VnpyBacktestAdapter`。
- [ ] 实现苏冰 EMA21 vn.py 策略草稿。
- [ ] 输出标准化回测 JSON。
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

任务：

- [ ] 数据中心页面接真实 API。
- [ ] K线工作台接 MarketDataReader。
- [ ] 策略中心接策略版本 API。
- [ ] 回测任务页面接任务 API。
- [ ] 回测报告页面接标准化结果。
- [ ] 交易明细表接 `backtest_trades`。
- [ ] K线图显示买卖点 marker。
- [ ] 信号扫描页面接 signals API。
- [ ] 复盘页面接 review_notes API。
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
P0-001 文档统一
P0-002 外部审查文档（ChatGPT）
P1-001 vn.py + RQData demo 实验目录
P1-002 data_sources 模块
P1-003 vnpy_integration adapter
P1-004 苏冰 EMA21 vn.py 策略
P1-005 回测任务 API
P1-006 Web 回测页面
P2-001 测试补齐
P2-002 依赖和迁移专项决策
P2-003 风控统计补齐
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
