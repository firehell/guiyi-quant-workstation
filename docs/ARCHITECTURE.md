# 归一量化系统架构

> 版本：V1 重构版  
> 当前路线：米筐 RQData + vn.py CTA 回测 + 自定义 Vue Web  
> 阶段边界：V1 只做研究闭环，不做自动实盘。

---

## 1. 总体架构

归一量化 V1 架构：

```text
Vue 3 Web 工作台
        |
        | REST API / WebSocket
        v
FastAPI 应用层
        |
        | 任务编排 / 参数校验 / 结果查询
        v
Redis + RQ 任务队列
        |
        | 异步执行
        v
Quant Service Layer
        |
        | 数据读取 / 策略注册 / 回测适配 / 报告转换
        v
vn.py BacktestingEngine
        |
        | 使用标准化行情数据
        v
Parquet + DuckDB + PostgreSQL
        |
        | 数据下载与标准化
        v
RQData / Local Legacy Data
```

核心原则：

```text
外部数据源不直接给策略和 Web 使用
vn.py 不直接决定产品形态
归一量化保留数据仓、任务、报告、复盘、信号和 Web 工作台
```

---

## 2. 技术栈

### 前端

- Vue 3
- Vite
- TypeScript
- Naive UI
- Pinia
- Vue Router
- Axios / TanStack Query Vue
- TradingView Lightweight Charts
- Apache ECharts / vue-echarts
- WebSocket

### 后端

- Python 3.13
- FastAPI
- Pydantic / pydantic-settings
- SQLAlchemy 2
- Alembic
- Redis + RQ
- APScheduler / RQ Scheduler
- pandas / Polars
- DuckDB
- PyArrow
- pytest
- ruff
- mypy

### 数据

- RQData / 米筐：V1 主数据源。
- PostgreSQL：业务事实库。
- Parquet：历史行情和大体量数据。
- DuckDB：本地研究查询。
- Redis：任务队列和临时状态。

### 回测

- vn.py / VeighNa CTA BacktestingEngine。
- vn.py CtaTemplate。
- 归一量化自定义 `vnpy_integration` adapter。
- 归一量化统一 result converter。

### 后期候选

- vn.py CTP Gateway：V2 实盘候选。
- TqSdk / 天勤：V2 实盘候选。
- TuShare：后期辅助数据候选。

---

## 3. 业务分层

```text
数据中心 Data Center
→ 行情中心 Market Center
→ 策略中心 Strategy Center
→ 回测中心 Backtest Center
→ 信号中心 Signal Center
→ 风控中心 Risk Center
→ 复盘中心 Review Center
→ 交易辅助中心 Trade Assist Center
→ 执行中心 Execution Center
```

V1 实现到：

```text
数据
→ 行情
→ 策略
→ 回测
→ 报告
→ 信号
→ 复盘
```

V1 不实现：

```text
实盘下单
自动执行
实盘持仓管理
无人值守策略运行
```

---

## 4. 模块职责

### 4.1 数据中心

负责：

- RQData 下载。
- raw parquet 留底。
- standard parquet 标准化。
- 交易日历。
- 合约元数据。
- 主力映射。
- 交易参数。
- 手续费和保证金规则。
- 数据质量检查。
- 数据文件索引。

不负责：

- 生成交易信号。
- 直接回测。
- 实盘下单。

---

### 4.2 行情中心

负责：

- K线查询。
- 多周期查询。
- 指标数据准备。
- Web K线工作台数据服务。
- 回测买卖点定位数据。

数据来源：

```text
PostgreSQL market_data_files
→ DuckDB read_parquet
→ MarketDataReader
```

---

### 4.3 策略中心

负责：

- 策略注册。
- 策略版本。
- 参数模板。
- 策略说明。
- 策略适用范围。
- vn.py 策略类路径记录。

策略不直接下单。

V1 策略优先写为 vn.py `CtaTemplate`。

---

### 4.4 回测中心

负责：

- 创建回测任务。
- 校验参数。
- 写入 RQ 队列。
- 调用 vn.py adapter。
- 转换 vn.py 结果。
- 保存报告。
- 提供 Web 查询 API。

回测中心不代表实盘结果。

---

### 4.5 信号中心

负责：

- 定时或手动扫描。
- 生成信号快照。
- 记录信号状态。
- 展示信号解释。
- 供人工观察。

信号中心 V1 不下单。

---

### 4.6 风控中心

负责：

- 回测风控统计。
- 信号过滤。
- 单笔风险。
- 保证金占用。
- 最大回撤。
- 连续亏损。
- 品种黑名单。
- 策略暂停条件。

V2 才进入发单前拦截。

---

### 4.7 复盘中心

负责：

- 单笔交易复盘。
- 入场理由。
- 出场理由。
- 错误标签。
- 策略场景标签。
- 执行偏差。
- 亏损归因。

---

### 4.8 交易辅助中心

V1 只预留。

V1.5 支持：

```text
信号
→ 人工观察
→ 手动下单
→ 手工录入成交
```

V2 支持：

```text
信号
→ 风控检查
→ 人工确认
→ 发单
```

---

## 5. 数据流

### 5.1 RQData 下载流

```text
RQData API
→ RqDataClient
→ raw parquet
→ 字段标准化
→ standard parquet
→ market_data_files
→ data_quality_reports
→ DuckDB 查询
```

### 5.2 回测流

```text
Web 创建回测任务
→ FastAPI 参数校验
→ backtest_tasks
→ RQ 入队
→ VnpyBacktestAdapter
→ LocalParquetProvider 读取数据
→ vn.py BacktestingEngine
→ raw result
→ ResultConverter
→ backtest_reports / trades / orders / curves
→ Web 报告展示
```

### 5.3 信号流

```text
标准 K线
→ 策略信号逻辑
→ signal_snapshot
→ 风控过滤
→ signals 表
→ Web 信号列表
→ 人工观察
```

### 5.4 复盘流

```text
backtest_trade / manual_trade
→ K线定位
→ review_note
→ 标签
→ 归因
→ 策略迭代建议
```

---

## 6. 目录建议

```text
services/quant-api/app/
  api/
  core/
  db/
  models/
  schemas/
  data_sources/
    rqdata_provider.py
    local_parquet_provider.py
    legacy_data_provider.py
  vnpy_integration/
    settings.py
    symbol_mapper.py
    backtest_runner.py
    result_converter.py
    strategy_loader.py
  backtest/
    service.py
    task_runner.py
    schemas.py
  market/
  strategy/
  signal/
  review/
  risk/
  tasks/

packages/quant-core/
  guiyi_quant/
    strategies/
      su_bing_ema21/
        vnpy_strategy.py
        config_schema.py
        default_params.json
        review_tags.json
        README.md
      ma_breakout/
      n_structure/
    adapters/
    reports/
    risk/
```

---

## 7. 数据源角色

| 数据源 | V1 角色 |
|---|---|
| RQData | 主数据源 |
| Local Parquet | 正式本地数据湖 |
| 早期米筐数据 | 清洗后可并入正式数据 |
| 天勤旧数据 | validation source |
| 交易练习者数据 | legacy_reference |
| TuShare | V1 不使用 |
| TqSdk | V2 实盘候选 |

---

## 8. 安全边界

禁止：

1. 把 RQData 账号写入代码。
2. 把 TqSdk 账号写入代码。
3. 把 CTP 账号、密码、AuthCode 写入代码。
4. 把 `.env` 提交。
5. 在 V1 写实盘下单逻辑。
6. 在 V1 做自动执行。
7. 直接修改 vn.py 源码。
8. 把 legacy 数据混入正式回测。
9. 用主力连续合约当真实可成交合约直接成交回测。

---

## 9. 当前实现状态口径

当前阶段：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再作为当前目标。

已具备：

- FastAPI 基础服务。
- Vue 3 / Vite / TypeScript / Naive UI 前端骨架。
- PostgreSQL / Redis 基础依赖。
- Alembic 初始化。
- RQData 结构化数据下载主体。
- `market_data_files` / `data_quality_reports`。
- Parquet + DuckDB 读取基础。
- 初始策略目录。
- `vnpy_integration` adapter、strategy loader、symbol mapper、result converter。
- 回测任务 API、报告模型、交易明细和曲线表。
- Web K线、回测报告、信号扫描和复盘中心骨架。

V1-B 待收敛：

- JM 最近 3 年 1d / 15m / 5m 数据验收。
- 日线定方向、15m / 5m 独立入场、5-8 根 K线短持有和止损退出规则收敛。
- V1-B 正式回测报告入库。
- Web 展示 V1-B 报告、资金曲线、回撤曲线、交易明细和 K线买卖点。
- 单笔交易创建复盘 note。
- 信号扫描只提醒，不自动下单。

---

## 10. 设计原则

1. 数据先行。
2. 回测保守。
3. 策略可解释。
4. 报告可复盘。
5. 信号只提醒。
6. 风控默认开启。
7. 实盘后置。
8. AI 是研究助理，不是自动交易员。
