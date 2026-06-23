# DATA_CENTER.md — 归一量化底层数据底座最终设计

> 版本：v1.1
> 状态：最终设计稿
> 更新日期：2026-06-23
> 权威性：全局项目口径以 `docs/归一量化_Codex从零搭建总控文档_V1.md` 为准；本文是底层数据实现细节的权威设计文档
> 原始参考：`docs/guiyi_quant_database_design.md` 保留为设计草稿，不作为实现依据
> 阶段边界：V0 命令行原型 + V1 Web 研究闭环
> 当前数据源策略：sample/mock 先跑通本地闭环，TqSdk / 天勤专业版作为核心目标数据源，RQData / Tushare / AKShare 作为补充适配或交叉校验

## 1. 项目定位和数据闭环

数据中心不是单纯存 K 线的模块，而是归一量化系统的底层资产层。它需要服务完整研究闭环：

```text
数据源配置
→ 合约与品种管理
→ 历史数据下载
→ 数据清洗与质量检查
→ 本地标准化数据仓
→ 策略参数与版本管理
→ 回测任务与报告归档
→ 信号扫描记录
→ 单笔交易复盘
→ 风控统计
→ 后续模拟 / 半自动实盘扩展
→ 策略迭代
```

第一版目标不是机构级大数据平台，而是做到：

1. 数据可追溯。
2. 回测可复现。
3. 策略版本可对比。
4. 信号和交易可复盘。
5. 后期能平滑接入模拟和半自动实盘。
6. 不把大体量行情数据塞进 PostgreSQL。
7. 不被任一数据供应商字段结构绑定。

## 2. 存储分层与职责边界

底层数据架构固定为：

```text
PostgreSQL + Parquet + DuckDB + Redis
```

| 组件 | 职责 | V1 是否使用 | 边界 |
|---|---|---:|---|
| PostgreSQL | 业务事实、元数据、任务、报告、交易明细、信号、复盘、风控配置 | 必须 | 不存分钟线 / tick 全量 |
| Parquet | 历史 K 线、tick、资金曲线、回撤曲线、参数搜索结果等大体量文件 | 必须 | 不存账号、密码、任务状态 |
| DuckDB | 本地研究查询、读取 Parquet、批量统计、回测取数 | 必须 | 不作为权威业务库 |
| Redis | RQ 队列、任务进度、临时状态缓存 | 必须 | 不作为长期数据库 |
| ClickHouse | 大规模 tick / 多年分钟线高并发查询 | 后期 | V1 不引入 |
| TimescaleDB | 时间序列扩展能力 | 暂不做 | V1 不引入 |

核心原则：

```text
PostgreSQL 管业务事实
Parquet 管历史行情
DuckDB 管研究查询
Redis 管临时状态
```

禁止：

- 把分钟线、tick 全量写入 PostgreSQL。
- 回测引擎直接调用米筐或天勤 SDK。
- 回测引擎直接拼 Parquet 路径。
- 没有质量报告就让数据进入默认回测。
- 把主力连续合约当成真实可交易合约直接成交回测。
- 把账号、license、token、交易密码写入代码库或文档。

## 3. 数据源适配设计

### 3.1 数据源优先级

| 优先级 | 数据源 | 当前用途 | 阶段 |
|---:|---|---|---|
| 1 | sample/mock | 先跑通 V0/V1 本地闭环、API 和文件规范 | V0 |
| 2 | TqSdk / 天勤专业版 | 核心目标数据源，负责行情源并为后续模拟/实盘辅助预留接口 | V1 |
| 3 | RQData / Tushare / AKShare 等 | 补充适配、元数据补充或交叉校验 | Backlog |

外部数据源只存在于采集适配层。清洗后必须进入本地标准化数据仓，后续 K 线、回测、信号、复盘统一读取本地数据。

### 3.2 数据源适配接口

后端固定定义统一 `DataSource` 接口。各供应商只实现适配器，不向回测和前端暴露 SDK 细节。

```python
class DataSource:
    provider: str

    def list_instruments(self) -> list[InstrumentDTO]: ...
    def list_contracts(self, instrument_symbol: str, start: date | None = None, end: date | None = None) -> list[ContractDTO]: ...
    def get_trading_calendar(self, exchange: str, start: date, end: date) -> CalendarDTO: ...
    def get_trading_sessions(self, exchange: str, instrument_symbol: str | None = None) -> list[TradingSessionDTO]: ...
    def get_bars(self, request: BarRequest) -> DataFrame: ...
    def get_main_contract_map(self, instrument_symbol: str, start: date, end: date) -> DataFrame: ...
```

V0 最小实现：

- `SampleDataSource.get_bars`
- `SampleDataSource.list_instruments`
- `SampleDataSource.list_contracts`
- `TqSdkDataSource` 同名接口框架
- `TqSdkDataSource.get_bars` 最小行情下载

RQData / Tushare / AKShare 适配器作为后续补充，不能影响标准数据层和回测读取方式。

### 3.3 数据流

历史数据下载：

```text
创建 data_download_tasks
→ 读取 data_sources 和环境变量
→ 调用 DataSource 适配器
→ 保存 raw 快照
→ 标准化字段
→ 写入 Parquet
→ 写入 market_data_files 文件索引
→ 运行数据质量检查
→ 写入 data_quality_reports
→ 更新任务状态
```

回测取数：

```text
backtest_tasks 指定策略、参数、品种、合约、周期、时间范围
→ 查询 contracts、market_data_files、data_quality_reports
→ 校验数据版本和质量状态
→ MarketDataReader 调用 DuckDB 读取 Parquet
→ 回测引擎运行
→ 结果写 PostgreSQL，曲线类大文件写 Parquet
```

Web 查询：

```text
Vue 数据中心 / K线 / 回测
→ FastAPI /api/v1/data/* 或 /api/v1/market/*
→ PostgreSQL 查询任务、覆盖范围、质量报告
→ DuckDB 查询 K 线摘要或分页数据
→ 前端展示
```

## 4. PostgreSQL 表组设计

本节为“设计 schema”。真实落地必须通过 SQLAlchemy 2 模型和 Alembic migration，不允许手工改库。

### 4.1 V1 必做表组

| 表 | 模块 | 用途 |
|---|---|---|
| `data_sources` | 数据源 | 记录米筐、天勤等数据源元信息，不保存敏感凭据 |
| `system_settings` | 系统配置 | 保存非敏感系统默认配置 |
| `instruments` | 品种 | 品种层级，如 rb、i、TA、SC |
| `contracts` | 合约 | 真实可交易合约，如 rb2510 |
| `main_contract_map` | 主力映射 | 每个交易日的主力 / 次主力合约 |
| `trading_calendars` | 交易日历 | 交易日、节假日、夜盘标识 |
| `trading_sessions` | 交易时段 | 日盘、夜盘、跨日规则 |
| `watchlists` | 品种池 | 研究池、回测池、扫描池 |
| `watchlist_items` | 品种池明细 | 品种池内品种 |
| `data_download_tasks` | 数据任务 | 下载任务、进度、失败原因 |
| `market_data_files` | 行情文件索引 | Parquet 文件路径、范围、版本、checksum |
| `data_quality_reports` | 数据质量 | 缺失、重复、异常、跨源差异 |
| `strategies` | 策略 | 策略基础信息 |
| `strategy_versions` | 策略版本 | 策略逻辑版本和代码路径 |
| `strategy_parameter_sets` | 策略参数 | 参数模板和 JSON 快照 |
| `backtest_tasks` | 回测任务 | 回测输入、数据版本、成本模型 |
| `backtest_reports` | 回测报告 | 指标、报告摘要、曲线路径 |
| `backtest_trades` | 回测交易明细 | 每笔交易、手续费、滑点、盈亏 |
| `signal_scan_tasks` | 信号扫描任务 | 扫描范围、策略、周期 |
| `signals` | 信号 | 触发条件、方向、状态 |
| `review_notes` | 复盘 | 单笔交易或信号复盘 |
| `risk_profiles` | 风控模板 | 单笔风险、回撤、持仓限制 |

### 4.2 V1 可选表

| 表 | 用途 | 默认处理 |
|---|---|---|
| `backtest_equity_points` | 资金曲线点 | 单次回测点数少可入库；批量回测优先写 Parquet |

### 4.3 V1.5 / V2 后置表

模拟和实盘相关表不作为 V1 必做，不启用自动实盘。

| 表 | 阶段 | 用途 |
|---|---|---|
| `trading_accounts` | V1.5 / V2 | 模拟 / 实盘账户元信息，不保存明文密码 |
| `orders` | V1.5 / V2 | 人工确认后的委托 |
| `trades` | V1.5 / V2 | 模拟 / 实盘成交 |
| `positions` | V1.5 / V2 | 持仓快照 |

### 4.4 V3 后置表

V3 再考虑 AI 总结、亏损归因、策略迭代辅助记录表。V1 不建。

## 5. 设计 schema 草案

### 5.1 数据源与系统配置

```sql
CREATE TABLE data_sources (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'disabled',
    priority INT NOT NULL DEFAULT 100,
    config JSONB NOT NULL DEFAULT '{}',
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE system_settings (
    id BIGSERIAL PRIMARY KEY,
    setting_key VARCHAR(128) NOT NULL UNIQUE,
    setting_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`data_sources.config` 只允许保存非敏感配置，例如缓存路径、接口模式、启停开关。真实 license、账号、密码只读环境变量。

### 5.2 品种、合约与交易日历

```sql
CREATE TABLE instruments (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(64) NOT NULL,
    exchange VARCHAR(16) NOT NULL,
    sector VARCHAR(32),
    category VARCHAR(32),
    is_active BOOLEAN NOT NULL DEFAULT true,
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contracts (
    id BIGSERIAL PRIMARY KEY,
    contract_code VARCHAR(64) NOT NULL UNIQUE,
    instrument_symbol VARCHAR(32) NOT NULL,
    exchange VARCHAR(16) NOT NULL,
    name VARCHAR(64),
    contract_month VARCHAR(16),
    price_tick NUMERIC(18, 6),
    volume_multiple INT,
    margin_rate NUMERIC(10, 6),
    open_fee NUMERIC(18, 6),
    close_fee NUMERIC(18, 6),
    close_today_fee NUMERIC(18, 6),
    listed_date DATE,
    expired_date DATE,
    status VARCHAR(32) DEFAULT 'active',
    raw_symbol VARCHAR(64),
    provider VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE main_contract_map (
    id BIGSERIAL PRIMARY KEY,
    instrument_symbol VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    main_contract VARCHAR(64) NOT NULL,
    secondary_contract VARCHAR(64),
    rule VARCHAR(64) NOT NULL DEFAULT 'volume_open_interest',
    provider VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_symbol, trade_date, provider)
);

CREATE TABLE trading_calendars (
    id BIGSERIAL PRIMARY KEY,
    exchange VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    has_night_session BOOLEAN DEFAULT false,
    remark TEXT,
    UNIQUE (exchange, trade_date)
);

CREATE TABLE trading_sessions (
    id BIGSERIAL PRIMARY KEY,
    exchange VARCHAR(16) NOT NULL,
    instrument_symbol VARCHAR(32),
    session_name VARCHAR(32) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    crosses_midnight BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

要求：

- `contracts.volume_multiple`、`price_tick`、手续费、保证金字段必须维护，因为回测盈亏、滑点、保证金都依赖这些字段。
- `main_contract_map` 用于选约和复现主力切换，不直接等同于可交易连续合约。
- 夜盘跨自然日时必须以 `trade_date` / `trading_day` 表示期货交易日归属。

### 5.3 品种池

```sql
CREATE TABLE watchlists (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    type VARCHAR(32) NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE watchlist_items (
    id BIGSERIAL PRIMARY KEY,
    watchlist_id BIGINT NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    instrument_symbol VARCHAR(32) NOT NULL,
    priority INT NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT true,
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (watchlist_id, instrument_symbol)
);
```

`watchlists.type` 固定候选：

```text
research
backtest
signal_scan
simulation
live_watch
```

V1 只启用 `research`、`backtest`、`signal_scan`。

### 5.4 数据任务、文件索引与质量报告

```sql
CREATE TABLE data_download_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_no VARCHAR(64) NOT NULL UNIQUE,
    provider VARCHAR(32) NOT NULL,
    instrument_symbol VARCHAR(32),
    contract_code VARCHAR(64),
    period VARCHAR(16) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    progress NUMERIC(5, 2) NOT NULL DEFAULT 0,
    error_message TEXT,
    result JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE market_data_files (
    id BIGSERIAL PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    data_type VARCHAR(32) NOT NULL,
    instrument_symbol VARCHAR(32),
    contract_code VARCHAR(64),
    period VARCHAR(16),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    file_path TEXT NOT NULL,
    row_count BIGINT,
    file_size_bytes BIGINT,
    checksum VARCHAR(128),
    data_version VARCHAR(64),
    quality_status VARCHAR(32) DEFAULT 'unchecked',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, data_type, contract_code, period, start_time, end_time, data_version)
);

CREATE TABLE data_quality_reports (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT REFERENCES market_data_files(id) ON DELETE SET NULL,
    provider VARCHAR(32) NOT NULL,
    contract_code VARCHAR(64),
    period VARCHAR(16),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL,
    missing_bars INT DEFAULT 0,
    duplicated_bars INT DEFAULT 0,
    abnormal_price_count INT DEFAULT 0,
    abnormal_volume_count INT DEFAULT 0,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`data_download_tasks.status`：

```text
pending
running
success
failed
cancelled
```

`market_data_files.data_type`：

```text
kline
tick
daily
main_contract
backtest_equity
backtest_drawdown
parameter_search
report_chart
```

`quality_status` / `data_quality_reports.status`：

```text
unchecked
passed
warning
failed
```

### 5.5 策略、回测、信号、复盘、风控

```sql
CREATE TABLE strategies (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(32),
    style VARCHAR(32),
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE strategy_versions (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    logic_hash VARCHAR(128),
    code_path TEXT,
    config_schema JSONB NOT NULL DEFAULT '{}',
    change_log TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (strategy_id, version)
);

CREATE TABLE strategy_parameter_sets (
    id BIGSERIAL PRIMARY KEY,
    strategy_version_id BIGINT NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    params JSONB NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE backtest_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_no VARCHAR(64) NOT NULL UNIQUE,
    strategy_version_id BIGINT NOT NULL REFERENCES strategy_versions(id),
    parameter_set_id BIGINT REFERENCES strategy_parameter_sets(id),
    watchlist_id BIGINT REFERENCES watchlists(id),
    contract_code VARCHAR(64),
    instrument_symbol VARCHAR(32),
    period VARCHAR(16) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    initial_capital NUMERIC(18, 2) NOT NULL,
    commission_model JSONB NOT NULL DEFAULT '{}',
    slippage_model JSONB NOT NULL DEFAULT '{}',
    risk_config JSONB NOT NULL DEFAULT '{}',
    data_version VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    progress NUMERIC(5, 2) NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE backtest_reports (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES backtest_tasks(id) ON DELETE CASCADE,
    total_return NUMERIC(18, 6),
    annual_return NUMERIC(18, 6),
    max_drawdown NUMERIC(18, 6),
    sharpe_ratio NUMERIC(18, 6),
    win_rate NUMERIC(18, 6),
    profit_loss_ratio NUMERIC(18, 6),
    expectancy NUMERIC(18, 6),
    trade_count INT,
    win_count INT,
    loss_count INT,
    max_consecutive_losses INT,
    avg_profit NUMERIC(18, 6),
    avg_loss NUMERIC(18, 6),
    equity_curve_path TEXT,
    drawdown_curve_path TEXT,
    monthly_stats JSONB NOT NULL DEFAULT '{}',
    instrument_stats JSONB NOT NULL DEFAULT '{}',
    summary JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE backtest_trades (
    id BIGSERIAL PRIMARY KEY,
    report_id BIGINT NOT NULL REFERENCES backtest_reports(id) ON DELETE CASCADE,
    trade_no VARCHAR(64) NOT NULL,
    instrument_symbol VARCHAR(32) NOT NULL,
    contract_code VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    open_price NUMERIC(18, 6) NOT NULL,
    close_time TIMESTAMPTZ,
    close_price NUMERIC(18, 6),
    volume INT NOT NULL,
    turnover NUMERIC(18, 2),
    commission NUMERIC(18, 2) DEFAULT 0,
    slippage NUMERIC(18, 2) DEFAULT 0,
    gross_pnl NUMERIC(18, 2),
    net_pnl NUMERIC(18, 2),
    return_pct NUMERIC(18, 6),
    holding_bars INT,
    entry_signal_id VARCHAR(128),
    exit_signal_id VARCHAR(128),
    entry_reason TEXT,
    exit_reason TEXT,
    stop_loss_price NUMERIC(18, 6),
    take_profit_price NUMERIC(18, 6),
    tags JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE signal_scan_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_no VARCHAR(64) NOT NULL UNIQUE,
    watchlist_id BIGINT REFERENCES watchlists(id),
    strategy_version_id BIGINT REFERENCES strategy_versions(id),
    period VARCHAR(16) NOT NULL,
    scan_time TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    result JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE signals (
    id BIGSERIAL PRIMARY KEY,
    scan_task_id BIGINT REFERENCES signal_scan_tasks(id) ON DELETE SET NULL,
    strategy_version_id BIGINT NOT NULL REFERENCES strategy_versions(id),
    instrument_symbol VARCHAR(32) NOT NULL,
    contract_code VARCHAR(64) NOT NULL,
    period VARCHAR(16) NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    signal_type VARCHAR(32) NOT NULL,
    direction VARCHAR(16),
    price NUMERIC(18, 6),
    strength NUMERIC(10, 4),
    reason TEXT,
    features JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE review_notes (
    id BIGSERIAL PRIMARY KEY,
    source_type VARCHAR(32) NOT NULL,
    source_id BIGINT,
    instrument_symbol VARCHAR(32),
    contract_code VARCHAR(64),
    strategy_version_id BIGINT REFERENCES strategy_versions(id),
    review_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    title VARCHAR(128),
    market_context TEXT,
    entry_reason TEXT,
    exit_reason TEXT,
    mistake_tags JSONB NOT NULL DEFAULT '[]',
    lesson TEXT,
    screenshot_paths JSONB NOT NULL DEFAULT '[]',
    score INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_profiles (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    account_size NUMERIC(18, 2) NOT NULL,
    max_risk_per_trade_pct NUMERIC(10, 6) NOT NULL,
    max_daily_loss_pct NUMERIC(10, 6),
    max_total_drawdown_pct NUMERIC(10, 6),
    max_positions INT,
    max_margin_usage_pct NUMERIC(10, 6),
    max_consecutive_losses INT,
    config JSONB NOT NULL DEFAULT '{}',
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

回测要求：

- `backtest_tasks` 必须绑定 `strategy_version_id`。
- `backtest_tasks` 必须记录 `data_version`、手续费模型、滑点模型、风控配置、初始资金、回测区间。
- `backtest_reports` 不能只保存收益数字，必须能追踪交易明细和曲线路径。
- `backtest_trades` 必须保留手续费、滑点、毛盈亏、净盈亏和入场/出场理由。

### 5.6 V1 可选：资金曲线点

```sql
CREATE TABLE backtest_equity_points (
    id BIGSERIAL PRIMARY KEY,
    report_id BIGINT NOT NULL REFERENCES backtest_reports(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    equity NUMERIC(18, 2) NOT NULL,
    drawdown NUMERIC(18, 6),
    position_value NUMERIC(18, 2),
    cash NUMERIC(18, 2)
);
```

默认建议：单次回测点数少时可入 PostgreSQL；批量回测或高频曲线保存为 Parquet，`backtest_reports` 只记录路径。

### 5.7 V1.5 / V2 后置：模拟与实盘表

以下表只作为后续扩展设计。V1 不启用自动实盘，不保存明文交易密码。

```sql
CREATE TABLE trading_accounts (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    broker VARCHAR(64),
    account_type VARCHAR(32) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'disabled',
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT REFERENCES trading_accounts(id),
    strategy_version_id BIGINT REFERENCES strategy_versions(id),
    signal_id BIGINT REFERENCES signals(id),
    order_ref VARCHAR(128),
    contract_code VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    offset VARCHAR(16) NOT NULL,
    price NUMERIC(18, 6),
    volume INT NOT NULL,
    order_type VARCHAR(32),
    status VARCHAR(32) NOT NULL,
    submitted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE trades (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT REFERENCES trading_accounts(id),
    order_id BIGINT REFERENCES orders(id),
    strategy_version_id BIGINT REFERENCES strategy_versions(id),
    contract_code VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    offset VARCHAR(16) NOT NULL,
    price NUMERIC(18, 6) NOT NULL,
    volume INT NOT NULL,
    trade_time TIMESTAMPTZ NOT NULL,
    commission NUMERIC(18, 2),
    raw JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE positions (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT REFERENCES trading_accounts(id),
    contract_code VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    volume INT NOT NULL,
    available_volume INT,
    avg_price NUMERIC(18, 6),
    margin NUMERIC(18, 2),
    floating_pnl NUMERIC(18, 2),
    snapshot_time TIMESTAMPTZ NOT NULL,
    raw JSONB NOT NULL DEFAULT '{}'
);
```

## 6. 命名规范

统一命名口径：

| 概念 | 固定命名 |
|---|---|
| 品种表 | `instruments` |
| 品种字段 | `instrument_symbol` |
| 合约字段 | `contract_code` |
| 数据源字段 | `provider` |
| 周期字段 | `period` |
| 交易日字段 | `trading_day` 或 `trade_date` |
| 文件索引表 | `market_data_files` |
| 数据版本字段 | `data_version` |

不要再混用：

- `products`
- `symbol` 表示品种和合约两种含义
- `source` / `source_provider` / `provider` 三套数据源字段
- `interval` / `timeframe` / `period` 三套周期字段
- `data_versions` 替代文件索引职责

## 7. Parquet 目录与字段规范

### 7.1 目录结构

```text
data/
├── raw/
│   ├── rqdata/
│   │   ├── kline/
│   │   ├── contracts/
│   │   └── main_contract/
│   └── tqsdk/
│       ├── kline/
│       ├── contracts/
│       └── main_contract/
│
├── parquet/
│   ├── market/
│   │   └── provider=rqdata/
│   │       └── data_type=kline/
│   │           └── period=1m/
│   │               └── exchange=SHFE/
│   │                   └── instrument=rb/
│   │                       └── year=2025/
│   │                           └── rb2510_2025_1m.parquet
│   │
│   │   └── provider=tqsdk/
│   │       └── data_type=tick/
│   │           └── exchange=SHFE/
│   │               └── instrument=rb/
│   │                   └── year=2025/
│   │                       └── month=01/
│   │                           └── rb2510_2025_01_tick.parquet
│   │
│   ├── backtest/
│   │   ├── equity/
│   │   ├── drawdown/
│   │   └── parameter_search/
│   │
│   └── reports/
│       └── charts/
│
├── processed/
│   ├── research/
│   └── features/
│
├── sample/
└── quality/
    └── reports/
```

规则：

- `data/raw/` 只追加，不覆盖，保存供应商原始字段。
- `data/parquet/market/` 是回测和 K 线工作台的标准行情源。
- `data/parquet/backtest/` 保存资金曲线、回撤曲线、参数搜索结果等大文件。
- `data/parquet/reports/` 可保存报告图表；后续也可迁移到 `backtests/reports/`。
- tick 目录只做后期预留，不参与 V1 回测。

### 7.2 K 线 Parquet 标准字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `datetime` | timestamp | 是 | K 线开始时间或供应商原始时间，必须在元数据中固定语义 |
| `trading_day` | date | 是 | 期货交易日，夜盘按交易日归属 |
| `exchange` | string | 是 | 交易所 |
| `instrument_symbol` | string | 是 | 品种，如 rb |
| `contract_code` | string | 是 | 真实合约，如 rb2510 |
| `period` | string | 是 | 1m、5m、15m、30m、1h、2h、4h、1d |
| `open` | double | 是 | 开盘价 |
| `high` | double | 是 | 最高价 |
| `low` | double | 是 | 最低价 |
| `close` | double | 是 | 收盘价 |
| `volume` | int64 | 是 | 成交量 |
| `open_interest` | double/int64 | 否 | 持仓量 |
| `turnover` | double | 否 | 成交额 |
| `provider` | string | 是 | rqdata、tqsdk |
| `data_version` | string | 是 | 数据版本 |
| `created_at` | timestamp | 是 | 写入时间 |

### 7.3 tick Parquet 字段，后期

| 字段 | 类型 | 说明 |
|---|---|---|
| `datetime` | timestamp | 时间戳 |
| `trading_day` | date | 交易日 |
| `exchange` | string | 交易所 |
| `instrument_symbol` | string | 品种 |
| `contract_code` | string | 合约 |
| `last_price` | double | 最新价 |
| `volume` | int64 | 成交量 |
| `turnover` | double | 成交额 |
| `open_interest` | double | 持仓量 |
| `bid_price1` | double | 买一价 |
| `bid_volume1` | int64 | 买一量 |
| `ask_price1` | double | 卖一价 |
| `ask_volume1` | int64 | 卖一量 |
| `provider` | string | 数据源 |
| `data_version` | string | 数据版本 |

V1 不做 tick 级高频回测，不建设复杂 tick 撮合库。

## 8. DuckDB 查询与回测取数

DuckDB 只负责读取 Parquet，不保存权威状态。

典型查询：

```sql
SELECT
    datetime,
    trading_day,
    open,
    high,
    low,
    close,
    volume,
    open_interest
FROM read_parquet('data/parquet/market/provider=rqdata/data_type=kline/period=30m/exchange=SHFE/instrument=rb/year=2025/*.parquet')
WHERE contract_code = 'rb2510'
  AND datetime >= timestamp '2025-01-01 00:00:00'
  AND datetime < timestamp '2025-12-31 00:00:00'
ORDER BY datetime;
```

后端必须封装 `MarketDataReader`：

```python
class MarketDataReader:
    def load_bars(self, contract_code: str, period: str, start: datetime, end: datetime, provider: str | None = None, data_version: str | None = None) -> DataFrame: ...
    def load_main_contract_map(self, instrument_symbol: str, start: date, end: date, provider: str | None = None) -> DataFrame: ...
    def get_coverage(self, instrument_symbol: str | None, contract_code: str | None, period: str) -> CoverageDTO: ...
    def get_quality_status(self, contract_code: str, period: str, start: datetime, end: datetime, data_version: str | None = None) -> QualityStatusDTO: ...
```

约束：

- 回测引擎只能调用 `MarketDataReader`。
- `MarketDataReader` 先查 PostgreSQL 的 `market_data_files` 和 `data_quality_reports`，再用 DuckDB 读 Parquet。
- 质量状态为 `failed` 的数据不允许默认进入回测。
- 质量状态为 `warning` 的数据必须在任务记录里留下人工确认或显式参数。

## 9. 数据版本与可复现规则

回测报告必须可复现。每次回测至少保存：

| 项目 | 存放位置 |
|---|---|
| 策略版本 | `backtest_tasks.strategy_version_id` |
| 参数模板 | `backtest_tasks.parameter_set_id` |
| 参数快照 | `backtest_tasks` 或报告 `summary` 中保存 JSON 快照 |
| 数据版本 | `backtest_tasks.data_version` |
| 手续费模型 | `backtest_tasks.commission_model` |
| 滑点模型 | `backtest_tasks.slippage_model` |
| 风控配置 | `backtest_tasks.risk_config` |
| 初始资金 | `backtest_tasks.initial_capital` |
| 回测区间 | `backtest_tasks.start_time` / `end_time` |
| Parquet 文件索引 | `market_data_files.id` 或文件路径集合 |
| 交易明细 | `backtest_trades` |

`data_version` 建议格式：

```text
sample_20260623_v1
sample_20260623_cleaned_v1
tqsdk_20260623_v1
tqsdk_20260623_cleaned_v1
```

同一数据源、合约、周期、时间范围重复下载时，不直接覆盖旧文件；新数据写入新版本，旧版本保留到手工清理或归档。

## 10. 数据质量规则

每次下载后必须生成质量报告。

| 检查项 | 说明 | 默认处理 |
|---|---|---|
| 时间连续性 | 交易时段内 K 线是否缺失 | 记录缺口；严重时 failed |
| 重复时间戳 | 同一合约、周期、时间是否重复 | 记录重复；去重策略必须留痕 |
| OHLC 合法性 | `high >= open/close/low` 且 `low <= open/close/high` | failed |
| 成交量合法性 | `volume >= 0` | failed |
| 持仓量合法性 | `open_interest >= 0` | warning 或 failed |
| 异常跳动 | 单根 K 线涨跌幅超阈值 | warning，必要时人工确认 |
| 夜盘归属 | 夜盘是否归属正确交易日 | failed |
| 主力换月 | 主力合约切换是否断档 | warning 或 failed |
| 到期后数据 | 合约到期后仍有行情 | failed |
| 文件校验 | checksum 是否变化 | warning 或 failed |
| 数据源差异 | 后期天勤和米筐同 K 线对照 | 记录差异，不自动覆盖 |

质量状态：

```text
unchecked
passed
warning
failed
```

禁止绕过质量报告直接回测。

## 11. 索引设计

V1 必要索引：

```sql
CREATE INDEX idx_contracts_instrument ON contracts(instrument_symbol);
CREATE INDEX idx_main_contract_map_instrument_date ON main_contract_map(instrument_symbol, trade_date);
CREATE INDEX idx_market_data_files_query ON market_data_files(contract_code, period, start_time, end_time);
CREATE INDEX idx_market_data_files_provider_version ON market_data_files(provider, data_version);
CREATE INDEX idx_download_tasks_status ON data_download_tasks(status, created_at);
CREATE INDEX idx_backtest_tasks_status ON backtest_tasks(status, created_at);
CREATE INDEX idx_backtest_reports_task ON backtest_reports(task_id);
CREATE INDEX idx_backtest_trades_report ON backtest_trades(report_id);
CREATE INDEX idx_signals_time ON signals(signal_time);
CREATE INDEX idx_signals_contract_period ON signals(contract_code, period, signal_time);
CREATE INDEX idx_review_notes_source ON review_notes(source_type, source_id);
```

不建议第一版盲目添加大量复合索引。先按真实查询路径和慢查询再补，避免增加写入成本。

## 12. Alembic / SQLAlchemy 开发规范

所有 PostgreSQL 表结构变更必须通过 Alembic migration，不要手工改库。

建议模块结构：

```text
services/quant-api/app/
  db/
    session.py
    base.py

  models/
    data_source.py
    instrument.py
    contract.py
    calendar.py
    watchlist.py
    data_task.py
    market_file.py
    data_quality.py
    strategy.py
    backtest.py
    signal.py
    review.py
    risk.py

  repositories/
    contract_repo.py
    market_file_repo.py
    strategy_repo.py
    backtest_repo.py
    signal_repo.py

  services/
    data_catalog_service.py
    market_data_service.py
    data_quality_service.py
    backtest_report_service.py
```

分层原则：

```text
models：只定义表结构
repositories：只做数据库读写
services：做业务流程
tasks：做异步任务
api：只做接口层
```

命名规范：

| 类型 | 命名 |
|---|---|
| 表名 | 小写复数，下划线，例如 `backtest_tasks` |
| 字段名 | 小写下划线，例如 `strategy_version_id` |
| 主键 | `id` |
| 时间字段 | `created_at`、`updated_at`、`started_at`、`finished_at` |
| 状态字段 | `status` |
| JSON 字段 | `config`、`params`、`summary`、`raw`、`details` |

时间规范：

- 数据库时间字段使用 `TIMESTAMPTZ`。
- 行情中必须明确 `trading_day` / `trade_date`。
- 夜盘不能按自然日粗暴切分。
- 前端展示按中国期货交易时间语义展示。

## 13. V1 数据 API 草案

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/data/sources` | 查看数据源状态 |
| GET | `/api/v1/data/instruments` | 查看品种列表 |
| GET | `/api/v1/data/contracts` | 查看合约列表 |
| POST | `/api/v1/data/download-tasks` | 创建下载任务 |
| GET | `/api/v1/data/download-tasks` | 查询下载任务 |
| GET | `/api/v1/data/download-tasks/{id}` | 查看任务详情 |
| GET | `/api/v1/data/quality-reports` | 查看质量报告 |
| GET | `/api/v1/data/coverage` | 查看数据覆盖范围 |
| GET | `/api/v1/market/bars` | 查询 K 线 |
| GET | `/api/v1/market/main-contracts` | 查询主力合约映射 |

API 不直接暴露外部数据源 SDK；所有响应来自 PostgreSQL、Parquet、DuckDB 的本地数据仓。

## 14. 备份与恢复

第一版本地部署必须有备份，不需要上云。

### 14.1 必备备份对象

| 对象 | 是否必须备份 | 说明 |
|---|---:|---|
| PostgreSQL | 必须 | 业务事实、任务、报告、复盘、信号 |
| Parquet 历史行情 | 必须 | 回测和研究基础 |
| 策略代码 | 必须 | Git 管理 |
| 回测报告 | 必须 | Markdown、JSON、图表、曲线 |
| 复盘记录 | 必须 | PostgreSQL + 截图路径 |
| `.env` / `.env.local` | 必须但单独安全备份 | 不进 Git |
| logs | 可选 | 排错用 |

### 14.2 PostgreSQL 备份

```bash
pg_dump -h localhost -U guiyi -d guiyi_quant > backups/postgres/guiyi_quant_$(date +%Y%m%d).sql
```

### 14.3 Parquet 备份

```text
data/parquet/
→ 外置 SSD
→ 每周全量备份
→ 每日增量备份
```

## 15. 第一阶段开发顺序

### Step 1：基础库

```text
PostgreSQL Docker
Redis Docker
SQLAlchemy 连接
Alembic 初始化
基础 health check
```

### Step 2：元数据表

```text
data_sources
system_settings
instruments
contracts
main_contract_map
trading_calendars
trading_sessions
watchlists
watchlist_items
```

### Step 3：数据任务与文件索引

```text
data_download_tasks
market_data_files
data_quality_reports
Parquet 目录规范
DuckDB 查询工具
```

### Step 4：策略与回测表

```text
strategies
strategy_versions
strategy_parameter_sets
backtest_tasks
backtest_reports
backtest_trades
```

### Step 5：信号、复盘和风控

```text
signal_scan_tasks
signals
review_notes
risk_profiles
```

### Step 6：数据源适配和最小下载链路

```text
RicequantDataSource
TqSdkDataSource 接口占位
SampleDataSource
TqSdkDataSource
下载或导入 rb / i / TA / SC 等少量样本
生成 Parquet
写入 market_data_files
生成 data_quality_reports
DuckDB 读取验证
```

### Step 7：备份脚本和恢复说明

```text
PostgreSQL dump
Parquet 目录备份
恢复流程说明
```

## 16. V0 / V1 验收标准

V0 验收：

- 能导入 sample/mock K 线或从 TqSdk 下载一个期货品种的历史 K 线。
- 能生成标准 Parquet。
- 能写入 `market_data_files`。
- 能生成 `data_quality_reports`。
- 能用 DuckDB 读取 Parquet 并输出行数和时间范围。
- 能在 PostgreSQL 中查询到品种、合约、任务、文件索引、质量报告。

V1 验收：

- Web 数据中心能展示数据源、下载任务、覆盖范围和质量报告。
- K 线页面能读取本地标准行情。
- 回测任务只读取本地标准化数据。
- 回测报告绑定策略版本、参数、数据版本、手续费、滑点、风控配置和交易明细。
- 质量状态为 `failed` 的数据不能默认进入回测。
- 接入或完善 TqSdk 时，只新增或完善适配器，不重写回测和前端。

## 17. 阶段边界

### 17.1 V1 必做

```text
1. PostgreSQL V1 必做表
2. Parquet 行情存储目录
3. DuckDB 查询工具
4. 合约和品种管理
5. 主力映射
6. 交易日历和交易时段
7. 品种池
8. 数据下载任务
9. 行情文件索引
10. 数据质量报告
11. 策略版本
12. 策略参数
13. 回测任务
14. 回测报告
15. 回测交易明细
16. 信号扫描任务和信号记录
17. 复盘记录
18. 风控模板
19. Alembic 迁移
20. 基础备份脚本
```

### 17.2 V1 可选

```text
1. backtest_equity_points
2. 月度统计 JSON
3. 品种维度统计 JSON
4. 数据质量评分
5. 参数搜索结果 Parquet
```

### 17.3 V1.5 / V2 后期再做

```text
1. 模拟 / 实盘账户表
2. 委托表
3. 成交表
4. 持仓快照表
5. tick 数据落库和索引
6. 企业微信提醒
7. 人工确认下单
8. 风控拦截
9. 多数据源自动对账
```

### 17.4 V3 后期再做

```text
1. AI 分析记录表
2. AI 亏损归因
3. AI 策略版本对比
4. AI 策略迭代建议
5. 策略组合层表
```

### 17.5 V1 不做

```text
1. 全自动实盘
2. tick 级高频回测
3. ClickHouse
4. TimescaleDB
5. 云数据库
6. 多用户权限
7. 多账户资金管理
8. 复杂组合保证金
9. 数据售卖 / 分发权限系统
10. 把分钟线或 tick 全量写入 PostgreSQL
```

## 18. 最终结论

归一量化底层数据部分的核心不是选一个数据库塞所有数据，而是建立本地数据仓体系：

```text
PostgreSQL：业务元数据和结果
Parquet：历史行情和大体量研究文件
DuckDB：研究查询和回测取数
Redis：任务状态和临时缓存
```

第一版只要把以下内容做好，就足够支撑 Web、回测、信号扫描和复盘：

```text
合约与品种
交易日历与交易时段
主力映射
品种池
数据下载任务
行情文件索引
数据质量报告
策略版本
策略参数
回测任务
回测报告
交易明细
信号记录
复盘记录
风控配置
```

后续接入天勤专业版、模拟账户、半自动实盘和 AI 策略迭代时，不推翻这套结构，只新增适配器、迁移和后置扩展表。
