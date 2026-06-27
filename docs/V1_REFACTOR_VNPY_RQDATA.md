# V1_REFACTOR_VNPY_RQDATA.md

> 归一量化 V1 重构总控文档  
> 当前路线：米筐 RQData + vn.py CTA 回测 + 自定义 Vue Web  
> 本文用于指导 Codex 单线程执行重构。

---

## 0. 当前执行阶段更新

当前阶段：

```text
V1 真实回测闭环打通阶段
```

当前真实状态：

- Web / API / 信号 / 复盘 / 回测报告页面已有骨架。
- `data_role` 隔离已存在，正式研究默认使用 `primary`。
- `vnpy_integration` adapter、strategy loader、symbol mapper、result converter 已存在。
- 苏冰 EMA21 vn.py 策略草稿已存在。
- 真实 vn.py `BacktestingEngine` 尚未执行。
- 当前 `VnpyBacktestRunner.run()` 仍是 `prepared/executed=false` 的准备态返回。
- 本地 DB migration 未对齐，已观察到 `backtest_tasks.engine_type` 缺列风险。
- Python 版本口径已统一为 Python 3.13；后续新环境按 3.13 准备。

当前阶段目标：

```text
标准 Parquet 样本数据
→ MarketDataReader / LocalParquetProvider 读取
→ vn.py BacktestingEngine 真实执行
→ 苏冰 EMA21 策略真实跑回测
→ result_converter 转归一量化标准结果
→ 写入 PostgreSQL reports / trades / equity_curve / drawdown_curve
→ FastAPI 查询
→ Vue Web 展示真实报告
→ K线显示真实买卖点 marker
```

当前阶段不做：

```text
新策略
参数优化
多品种批量回测
AI 策略生成
天勤实盘
CTP
自动下单
Web 大屏扩展
```

当前阶段单线程顺序：

```text
P1R-001 更新任务状态和路线图
P1R-002 只读检查 Alembic head 与本地 DB 状态，形成 migration 对齐方案
P1R-003 准备标准 Parquet 样本数据 fixture，不触碰真实 data/
P1R-004 接真实 vn.py BacktestingEngine 执行
P1R-005 打通 normalized result 到 reports / trades / equity_curve / drawdown_curve 持久化
P1R-006 FastAPI 查询真实报告与交易明细
P1R-007 Vue Web 展示真实报告、资金曲线、回撤曲线
P1R-008 K线显示真实 backtest trades 买卖点 marker
P1R-009 回测严谨性审查
```

P1R-003 标准 Parquet fixture：

- 路径：`services/quant-api/tests/fixtures/standard_parquet/canonical/bars/provider=local_parquet/interval=60m/exchange=SHFE/symbol=rb/contract=rb2405/rb2405_60m.parquet`
- 生成脚本：`experiments/vnpy_rqdata_demo/generate_standard_fixture.py`
- 合约：`rb2405.SHFE`
- 周期：`60m`
- 行数：96 根 bar，满足 EMA21 / MACD / ATR 的基础预热窗口。
- 字段：`symbol`、`contract`、`exchange`、`vt_symbol`、`datetime`、`trading_day`、`interval`、`period`、`open`、`high`、`low`、`close`、`volume`、`turnover`、`open_interest`、`source`、`provider`、`data_role`、`quality_status`、`data_version`。
- 固定标记：`source=sample`、`provider=local_parquet`、`data_role=primary`、`quality_status=passed`。
- 用途：验证 DuckDB、`MarketDataReader`、`LocalParquetProvider` 与后续真实 vn.py runner 的最小标准数据入口。
- 边界：该 fixture 是合成研究样本，不读取 RQData 账号，不调用外部下载，不写入正式 `data/`，不代表真实行情或正式回测结论。

---

## 1. 重构目的

本次重构不是推翻归一量化，而是调整 V1 开发边界。

重构目标：

```text
精简数据源
降低回测底层开发成本
利用 vn.py 成熟 CTA 回测能力
保留归一量化自己的研究闭环
推迟实盘接入
```

历史方案（已废弃，不作为当前 V1 口径）：

```text
天勤专业版作为 V1 主数据源
自研完整 bar 级回测引擎
后期接天勤实盘
```

新路线：

```text
米筐 RQData 作为 V1 主数据源
vn.py 作为 V1 CTA 回测底座
Parquet + DuckDB + PostgreSQL 继续保留
Vue Web 继续自定义
V1 不接实盘
V2 再评估 vn.py CTP 和天勤
```

---

## 2. 最终 V1 主链路

```text
米筐 RQData
→ raw parquet
→ standard parquet
→ market_data_files
→ data_quality_reports
→ DuckDB / MarketDataReader
→ vn.py BacktestingEngine
→ raw backtest result
→ ResultConverter
→ PostgreSQL 回测报告
→ Vue Web 展示
→ K线买卖点复盘
→ 信号扫描
→ 人工观察
```

---

## 3. 核心角色划分

| 组件 | 角色 |
|---|---|
| RQData / 米筐 | V1 主数据源 |
| Parquet | 本地历史行情数据湖 |
| DuckDB | 本地研究查询 |
| PostgreSQL | 业务事实库 |
| vn.py | CTA 回测底座，V2 实盘候选 |
| FastAPI | 后端 API 和任务编排 |
| Redis + RQ | 异步任务队列 |
| Vue 3 Web | 自定义研究工作台 |
| Codex | 主力开发 Agent |
| ChatGPT（外部） | 审查员 |
| Cursor | 人工控制和小修 |
| WorkBuddy | UI bug 修复 |

---

## 4. V1 数据源决策

### 4.1 RQData

V1 主用。

用途：

- 历史分钟数据。
- 合约信息。
- 主力映射。
- 复权因子。
- 交易参数。
- 费用和保证金。
- 日线基准。
- 研究增强数据。

### 4.2 天勤

V1 不主用。

状态：

```text
V2 模拟 / 半自动实盘候选
```

旧天勤数据：

```text
source = tq_old
data_role = validation
```

### 4.3 TuShare

V1 移除。

状态：

```text
后期宏观 / 股票 / 辅助数据候选
```

### 4.4 交易练习者数据

不用于正式回测。

状态：

```text
source = trader_trainer
data_role = legacy_reference
```

用途：

- 页面测试。
- 对照校验。
- 历史参考。

---

## 5. V1 回测决策

V1 不从零自研完整撮合引擎。

采用：

```text
vn.py CTA BacktestingEngine
```

归一量化负责：

- 回测任务。
- 参数配置。
- 数据准备。
- vn.py adapter。
- 结果转换。
- 报告入库。
- Web 展示。
- K线复盘。
- 风控统计。

vn.py 负责：

- CtaTemplate。
- bar 级回测。
- 委托、成交、持仓等底层逻辑。

---

## 6. V1 Web 决策

继续使用：

```text
Vue 3 + Vite + TypeScript + Naive UI
```

不用：

- vn.py Studio 作为主界面。
- vn.py 自带 Web 作为最终产品。
- Next.js。
- 云端 SaaS。
- 多用户权限。

---

## 7. 旧数据隔离规则

`market_data_files` 必须支持：

```text
source
data_role
quality_status
data_version
```

`data_role` 枚举：

```text
primary
validation
legacy_reference
candidate
```

默认正式回测只允许：

```text
data_role = primary
quality_status != failed
```

validation 和 legacy_reference 必须手动选择，且报告标记为：

```text
research_only = true
```

---

## 8. 目录调整建议

### 8.1 后端新增

```text
services/quant-api/app/data_sources/
  __init__.py
  rqdata_provider.py
  local_parquet_provider.py
  legacy_data_provider.py

services/quant-api/app/vnpy_integration/
  __init__.py
  settings.py
  symbol_mapper.py
  strategy_loader.py
  backtest_runner.py
  result_converter.py
  errors.py
```

### 8.2 quant-core 新增

```text
packages/quant-core/guiyi_quant/strategies/su_bing_ema21/
  vnpy_strategy.py
  config_schema.py
  default_params.json
  review_tags.json
  README.md
```

### 8.3 实验目录

```text
experiments/vnpy_rqdata_demo/
  README.md
  run_demo.py
  sample_config.json
```

---

## 9. 数据库调整

建议保留 / 新增：

```text
contracts
instruments
watchlists
data_download_tasks
market_data_files
data_quality_reports

strategies
strategy_versions
strategy_parameters

backtest_tasks
backtest_reports
backtest_trades
backtest_orders
backtest_daily_results
backtest_equity_curve
backtest_drawdown_curve

signals
review_notes
risk_profiles
system_settings
```

### 9.1 `backtest_tasks` 新字段

```text
engine_type
vnpy_strategy_class
vnpy_setting_json
data_source
data_role
data_version
raw_result_path
normalized_result_path
status
error_type
error_message
traceback
started_at
finished_at
```

### 9.2 `strategies` 新字段

```text
strategy_framework
strategy_class_path
default_engine_type
supported_intervals
supported_markets
is_live_enabled
```

### 9.3 `market_data_files` 新字段

```text
source
data_role
quality_status
data_version
row_count
checksum
```

---

## 10. API 调整

### 数据中心

```text
GET  /api/contracts
GET  /api/instruments
GET  /api/watchlists
POST /api/data/download-tasks
GET  /api/data/download-tasks
GET  /api/data/files
GET  /api/data/quality-reports
GET  /api/market/bars
```

### 策略

```text
GET  /api/strategies
GET  /api/strategies/{strategy_id}
GET  /api/strategies/{strategy_id}/versions
POST /api/strategies/{strategy_id}/versions
GET  /api/strategies/{strategy_id}/params-schema
```

### 回测

```text
POST /api/backtests/tasks
GET  /api/backtests/tasks
GET  /api/backtests/tasks/{task_id}
GET  /api/backtests/reports
GET  /api/backtests/reports/{report_id}
GET  /api/backtests/reports/{report_id}/trades
GET  /api/backtests/reports/{report_id}/orders
GET  /api/backtests/reports/{report_id}/daily-results
GET  /api/backtests/reports/{report_id}/equity-curve
GET  /api/backtests/reports/{report_id}/drawdown-curve
```

### 信号

```text
POST /api/signals/scan-tasks
GET  /api/signals
GET  /api/signals/{signal_id}
POST /api/signals/{signal_id}/mark-reviewed
POST /api/signals/{signal_id}/ignore
POST /api/signals/{signal_id}/add-to-watch
```

### 复盘

```text
POST /api/reviews/trade-notes
GET  /api/reviews/trade-notes
GET  /api/reviews/trade-notes/{note_id}
PATCH /api/reviews/trade-notes/{note_id}
DELETE /api/reviews/trade-notes/{note_id}
```

---

## 11. Codex 历史执行顺序

以下 P0 / P1 / P2 列表是 V1 重构早期的历史执行记录和基础路线，不再代表当前下一步。当前下一步以本文第 0 节“当前执行阶段更新”和 `tasks/current.md` 为准。

### P0-001：文档统一

允许修改：

```text
AGENTS.md
docs/CODE_REVIEW.md
docs/PRD.md
docs/ARCHITECTURE.md
docs/DATA_CENTER.md
docs/BACKTEST_ENGINE.md
docs/ROADMAP.md
docs/V1_REFACTOR_VNPY_RQDATA.md
```

禁止修改：

```text
代码文件
依赖文件
数据库迁移
.env
data/
```

目标：

```text
统一全项目文档到 RQData + vn.py 新路线
```

---

### P0-002：外部审查文档一致性（ChatGPT）

只审查，不修改。

审查：

```text
是否仍残留天勤 V1 主数据源
是否仍残留自研完整回测引擎
是否明确旧数据隔离
是否明确 V1 不做实盘
```

---

### P1-001：vn.py + RQData demo 实验目录

允许修改：

```text
experiments/vnpy_rqdata_demo/
```

禁止修改：

```text
正式业务模块
数据库迁移
Web 前端
后端依赖文件
pyproject.toml
uv.lock
package.json
pnpm-lock.yaml
```

目标：

```text
检测本机是否已有 vn.py，未安装时只给出明确提示
验证最小 CTA 回测可跑
验证输出 statistics / trades JSON
```

P1-008 后端端到端 demo 补充：

```text
experiments/vnpy_rqdata_demo/run_demo.py --check-env
→ 输出 environment_check.json

experiments/vnpy_rqdata_demo/run_demo.py --sample
→ sample config
→ sample data provider
→ BacktestService task
→ BacktestTaskRunner
→ fake vn.py adapter
→ result converter
→ sample_standard_result.json
```

说明：

- demo 输出目录为 `experiments/vnpy_rqdata_demo/output/`。
- `output/` 只提交 `.gitignore`，不提交生成 JSON。
- sample 模式不需要真实 RQData 账号，不读取真实 `data/`。
- sample 模式使用内置样例 K线和 fake adapter，只验证后端链路形状。
- demo 是研究验证，不是正式回测结论。
- demo 不调用 CTP、TqSdk 实盘、vn.py gateway 或任何交易接口。

---

### P1-002：data_sources 模块

允许修改：

```text
services/quant-api/app/data_sources/
```

目标：

```text
RQDataProvider
LocalParquetProvider
LegacyDataProvider
```

---

### P1-003：vnpy_integration 模块

允许修改：

```text
services/quant-api/app/vnpy_integration/
```

目标：

```text
symbol_mapper
strategy_loader
backtest_runner
result_converter
```

---

### P1-004：苏冰 EMA21 vn.py 策略

允许修改：

```text
packages/quant-core/guiyi_quant/strategies/su_bing_ema21/
```

目标：

```text
实现 vn.py CtaTemplate 策略草稿
```

要求：

```text
不使用未来数据
参数可配置
输出交易理由或 signal reason
```

---

### P1-005：回测任务 API

允许修改：

```text
services/quant-api/app/backtest/
services/quant-api/app/api/
services/quant-api/app/models/
services/quant-api/app/schemas/
```

目标：

```text
创建回测任务
进入 RQ 队列
调用 vn.py adapter
结果入库
```

---

### P1-006：Web 回测页面

允许修改：

```text
apps/quant-web/src/pages/backtest/
apps/quant-web/src/api/
apps/quant-web/src/types/
```

目标：

```text
创建回测任务
查看任务状态
查看回测报告
```

---

### P2-001：测试补齐

目标：

```text
pytest
ruff
mypy
前端 typecheck
```

---

## 12. Codex 主 Prompt

```text
你现在是归一量化项目的主力开发 Agent。

请先阅读：

1. AGENTS.md
2. docs/CODE_REVIEW.md
3. docs/PRD.md
4. docs/ARCHITECTURE.md
5. docs/DATA_CENTER.md
6. docs/BACKTEST_ENGINE.md
7. docs/ROADMAP.md
8. docs/V1_REFACTOR_VNPY_RQDATA.md

本次项目进行 V1 重构。

新路线：

- V1 主数据源：米筐 RQData
- V1 回测底座：vn.py / VeighNa CTA 回测
- V1 不使用 VeighNa Studio 作为项目依赖
- 数据仓：PostgreSQL + Parquet + DuckDB
- 后端：FastAPI + Redis/RQ
- 前端：Vue 3 + Vite + TypeScript + Naive UI
- Web：归一量化自定义，不使用 vn.py 自带界面
- 天勤：V2 实盘阶段候选，不作为 V1 必需依赖
- TuShare：从 V1 移除，后期作为辅助数据候选
- 旧天勤数据：只作为 validation source
- 交易练习者数据：只作为 legacy_reference
- V1 不做自动实盘

请先不要大改代码。

第一步任务：
只统一项目文档，不改代码、不安装依赖、不运行数据库迁移。

输出：
1. 你理解的新架构
2. 准备修改的文件列表
3. 每个文件准备改什么
4. 修改完成后说明实际改了哪些文件
5. 给出下一步建议
```

---

## 13. 外部审查 Prompt（ChatGPT）

```text
请作为归一量化项目的架构审查员，只审查，不要修改文件。

本次项目路线调整为：

- V1 主数据源：米筐 RQData
- V1 回测底座：vn.py CTA 回测
- V1 不使用 VeighNa Studio 作为项目依赖
- 数据仓：PostgreSQL + Parquet + DuckDB
- 后端：FastAPI + Redis/RQ
- 前端：Vue 3 + Vite + TypeScript + Naive UI
- Web：归一量化自定义，不使用 vn.py 自带界面
- 天勤：V2 实盘候选
- TuShare：V1 移除
- 旧天勤数据：validation source
- 交易练习者数据：legacy_reference
- V1 不做实盘

请审查：

1. 文档是否统一到新路线
2. 是否仍有“天勤第一阶段主数据源”的旧描述
3. 是否仍有“必须自研完整回测引擎”的旧描述
4. 是否清楚说明 vn.py 的角色
5. 是否清楚说明米筐 RQData 的角色
6. 是否清楚说明旧数据处理策略
7. 是否保留归一量化自己的数据仓和 Web 工作台定位
8. 是否明确避免未来函数、数据泄露、过拟合
9. 是否明确 V1 不做自动实盘
10. 是否存在过度工程化

请按 P0 / P1 / P2 输出问题清单。
```

---

## 14. 重构验收标准

当前收尾验收清单见：

```text
docs/V1_ACCEPTANCE.md
```

`docs/V1_ACCEPTANCE.md` 记录 demo 运行方式、回测任务 API、报告查看方式、依赖清理结论、敏感词扫描口径和最终 V1 验收状态。

### 文档层

```text
[ ] AGENTS.md 已更新
[ ] docs/CODE_REVIEW.md 已新增
[ ] PRD.md 已更新
[ ] ARCHITECTURE.md 已更新
[ ] DATA_CENTER.md 已更新
[ ] BACKTEST_ENGINE.md 已更新
[ ] ROADMAP.md 已更新
[ ] V1_REFACTOR_VNPY_RQDATA.md 已新增或更新
[ ] 不再把天勤写成 V1 主数据源
[ ] 不再把自研完整回测引擎写成 V1 主路径
```

### 代码层

```text
[ ] experiments/vnpy_rqdata_demo 可运行
[ ] data_sources 模块存在
[ ] vnpy_integration 模块存在
[ ] 苏冰 EMA21 vn.py 策略草稿存在
[ ] 回测任务 API 存在
[ ] Web 回测页面能提交任务
[ ] vn.py 依赖和数据库迁移经过独立专项决策，不混入 P0/P1-001
```

### 安全层

```text
[ ] 没有账号密码入库
[ ] 没有 .env 提交
[ ] 没有自动实盘逻辑
[ ] 没有未来函数
[ ] 没有数据泄露
[ ] 旧数据不会默认进入正式回测
```

---

## 15. 风险点

1. vn.py 回测结果字段与归一量化报告字段不一致。
2. 主力连续合约不能直接当真实合约成交。
3. 2H / 4H 周期合成需处理夜盘。
4. 旧数据可能污染正式回测。
5. Codex 可能误删旧模块。
6. Codex 可能过早安装并改依赖。
7. Codex 可能误做实盘接口。
8. 米筐流量和线程限制需要下载任务控制。
9. 回测参数优化可能过拟合。
10. 回测结果不等于实盘结果。

---

## 16. 最终原则

```text
先统一文档
再做实验
再做 adapter
再接 API
再接 Web
最后补测试和审查
```

不要一次性大改。

每一步完成后：

```text
git diff
→ 本地测试
→ 外部审查（ChatGPT）
→ git commit
```
