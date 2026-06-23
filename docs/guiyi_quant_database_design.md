# 归一量化数据库部分功能与设计方案

> 适用范围：本文件只讨论“数据库 / 数据仓 / 本地数据管理”部分，不展开 Web 页面、策略逻辑、AI Agent、实盘交易界面。  
> 当前项目默认技术路线：**PostgreSQL + Parquet + DuckDB**。  
> 数据源第一阶段默认：**sample/mock 先跑通本地闭环，TqSdk / 天勤专业版作为核心目标数据源，RQData / Tushare / AKShare 作为补充适配或交叉校验**。

---

## 1. 数据库部分在系统里的定位

数据库不是单纯“存 K 线”的地方，而是整个归一量化系统的底层资产。

它要服务这条闭环：

```text
数据源配置
→ 合约与品种管理
→ 历史数据下载
→ 数据清洗与质量检查
→ 策略参数与版本管理
→ 回测任务与报告归档
→ 信号扫描记录
→ 单笔交易复盘
→ 模拟 / 实盘交易记录
→ 风控统计
→ 策略迭代
```

第一版数据库目标不是追求机构级大数据架构，而是要做到：

1. 数据可追溯。
2. 回测可复现。
3. 策略版本可对比。
4. 信号和交易可复盘。
5. 后期能平滑接入模拟和实盘。
6. 不把大体量行情数据全部塞进 PostgreSQL。
7. 不被某一家数据供应商字段结构绑定。

---

## 2. 总体数据库架构

### 2.1 三层存储结构

```text
┌──────────────────────────────────────┐
│ PostgreSQL                           │
│ 存元数据、配置、任务、报告、交易记录  │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ Parquet                              │
│ 存历史 K 线、tick、大体量行情数据      │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ DuckDB                               │
│ 查询 Parquet、做研究统计、回测取数     │
└──────────────────────────────────────┘
```

### 2.2 各组件分工

| 组件 | 主要职责 | 是否第一版使用 |
|---|---|---|
| PostgreSQL | 合约、品种池、任务、策略、回测报告、交易明细、信号、复盘、风控配置 | 必须 |
| Parquet | 1m/5m/15m/30m/1h/2h/4h/日线 K 线，后期 tick 数据 | 必须 |
| DuckDB | 本地研究查询、读取 Parquet、批量回测前取数、统计分析 | 必须 |
| Redis | 任务队列和实时状态缓存，不作为长期数据库 | 必须 |
| ClickHouse | 大规模 tick / 多年分钟线高并发查询，后期再考虑 | 后期 |
| TimescaleDB | 可选，不作为第一版必选 | 暂不做 |

### 2.3 核心原则

```text
PostgreSQL 管“业务事实”
Parquet 管“历史行情”
DuckDB 管“研究查询”
Redis 管“临时状态”
```

不要把所有 K 线全部塞入 PostgreSQL。否则数据量上来后，备份、迁移、查询和维护都会变重。

---

## 3. 数据库功能模块清单

数据库部分第一版需要支持以下功能。

| 模块 | 功能 | 第一版是否必须 |
|---|---|---|
| 数据源管理 | 天勤账号配置、供应商、权限、同步状态 | 必须 |
| 品种管理 | 黑色、化工、能源等品种分类 | 必须 |
| 合约管理 | 交易所、合约、乘数、最小变动价位、状态 | 必须 |
| 主力映射 | 主力合约切换、连续合约映射 | 必须 |
| 交易日历 | 交易日、夜盘、节假日、交易时段 | 必须 |
| 品种池 | 回测池、扫描池、实盘观察池 | 必须 |
| 数据下载任务 | 下载任务、进度、失败重试、日志 | 必须 |
| 数据质量检查 | 缺失、重复、异常价格、成交量异常 | 必须 |
| 行情文件索引 | Parquet 文件路径、周期、时间范围、版本 | 必须 |
| 策略管理 | 策略基础信息、标签、状态 | 必须 |
| 策略版本 | 每次策略逻辑或参数模板变更留版本 | 必须 |
| 策略参数 | 参数模板、回测参数、扫描参数 | 必须 |
| 回测任务 | 任务状态、品种、周期、策略、参数 | 必须 |
| 回测报告 | 绩效指标、资金曲线路径、报告摘要 | 必须 |
| 回测交易明细 | 每笔入场、出场、盈亏、手续费、滑点 | 必须 |
| 信号记录 | 扫描信号、触发条件、确认状态 | 必须 |
| 复盘记录 | 单笔交易复盘、错误标签、截图路径 | 必须 |
| 风控配置 | 单笔风险、最大回撤、最大持仓、连亏限制 | 必须 |
| 实盘记录 | 账户、委托、成交、持仓 | V1.5/V2 |
| AI 分析记录 | AI 总结、归因、优化建议 | V3 |

---

## 4. PostgreSQL 表结构设计

以下是第一版建议表结构。字段以 MVP 为主，后续可扩展。

---

# 4.1 数据源与系统配置

## 4.1.1 data_sources：数据源配置表

用于记录天勤、米筐等数据源配置，不保存明文密码。

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
```

字段说明：

| 字段 | 说明 |
|---|---|
| provider | tq、rqdata、tushare、ifind 等 |
| status | enabled、disabled、error |
| priority | 多数据源时的优先级 |
| config | 保存非敏感配置，例如本地缓存路径、接口模式 |
| 密码 | 不入库，写入 `.env` 或本地安全配置 |

---

## 4.1.2 system_settings：系统设置表

```sql
CREATE TABLE system_settings (
    id BIGSERIAL PRIMARY KEY,
    setting_key VARCHAR(128) NOT NULL UNIQUE,
    setting_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

适合保存：

```text
默认数据目录
默认回测手续费模型
默认滑点模型
默认品种池
默认扫描周期
系统运行模式：research / simulation / live_guarded
```

---

# 4.2 品种、合约与交易日历

## 4.2.1 instruments：品种表

记录品种层级，例如螺纹钢、铁矿石、PTA、甲醇、原油。

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
```

示例：

| symbol | name | exchange | sector | category |
|---|---|---|---|---|
| rb | 螺纹钢 | SHFE | 黑色 | 建材 |
| i | 铁矿石 | DCE | 黑色 | 原料 |
| TA | PTA | CZCE | 化工 | 聚酯 |
| SC | 原油 | INE | 能源 | 原油 |

---

## 4.2.2 contracts：合约表

记录具体合约，例如 rb2510、TA509。

```sql
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
    source_provider VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

重点字段：

| 字段 | 说明 |
|---|---|
| contract_code | 系统内部统一代码 |
| raw_symbol | 天勤或其他数据源原始代码 |
| volume_multiple | 合约乘数，计算盈亏必须用 |
| price_tick | 最小变动价位 |
| margin_rate | 保证金率，可后续每日更新 |
| open_fee / close_fee | 手续费模型基础值 |

---

## 4.2.3 main_contract_map：主力合约映射表

用于记录某品种在某交易日对应的主力合约。

```sql
CREATE TABLE main_contract_map (
    id BIGSERIAL PRIMARY KEY,
    instrument_symbol VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    main_contract VARCHAR(64) NOT NULL,
    secondary_contract VARCHAR(64),
    rule VARCHAR(64) NOT NULL DEFAULT 'volume_open_interest',
    source_provider VARCHAR(32) NOT NULL DEFAULT 'tq',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_symbol, trade_date, source_provider)
);
```

作用：

1. 回测主连时避免随意换月。
2. 复现某天实际使用的主力合约。
3. 后期接米筐时可对比主力规则差异。

---

## 4.2.4 trading_calendars：交易日历表

```sql
CREATE TABLE trading_calendars (
    id BIGSERIAL PRIMARY KEY,
    exchange VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    has_night_session BOOLEAN DEFAULT false,
    remark TEXT,
    UNIQUE (exchange, trade_date)
);
```

---

## 4.2.5 trading_sessions：交易时段表

用于记录每个交易所或品种的日盘、夜盘时段。

```sql
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

注意：

夜盘跨自然日，但归属交易日要按期货交易日处理，不能简单按自然日切分。

---

# 4.3 品种池与观察列表

## 4.3.1 watchlists：品种池表

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
```

type 示例：

```text
research       研究池
backtest       回测池
signal_scan    信号扫描池
simulation     模拟观察池
live_watch     实盘观察池
```

---

## 4.3.2 watchlist_items：品种池明细表

```sql
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

---

# 4.4 数据下载与数据质量

## 4.4.1 data_download_tasks：数据下载任务表

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
```

status：

```text
pending
running
success
failed
cancelled
```

---

## 4.4.2 market_data_files：行情文件索引表

实际 K 线数据存在 Parquet 文件里，本表只记录文件索引。

```sql
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
```

data_type：

```text
kline
tick
daily
main_contract
```

---

## 4.4.3 data_quality_reports：数据质量报告表

```sql
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

必须检查：

1. 时间戳重复。
2. K 线缺失。
3. high < low。
4. open/high/low/close 关系异常。
5. 成交量为负。
6. 夜盘归属错误。
7. 主力换月断档。
8. 不同数据源对照差异。

---

# 4.5 策略管理

## 4.5.1 strategies：策略基础表

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
```

示例策略：

```text
su_bing_ema21
n_structure_fractal
ma_breakout_trend_filter
```

---

## 4.5.2 strategy_versions：策略版本表

```sql
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
```

作用：

1. 防止策略逻辑改了但回测报告无法复现。
2. 回测报告必须绑定 strategy_version_id。
3. 后期 AI 对比策略版本时必须使用。

---

## 4.5.3 strategy_parameter_sets：策略参数模板表

```sql
CREATE TABLE strategy_parameter_sets (
    id BIGSERIAL PRIMARY KEY,
    strategy_version_id BIGINT NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    params JSONB NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

params 示例：

```json
{
  "period": "2h",
  "ema_period": 21,
  "atr_period": 14,
  "stop_loss_atr": 2.0,
  "trend_filter": true,
  "allow_long": true,
  "allow_short": true
}
```

---

# 4.6 回测任务与报告

## 4.6.1 backtest_tasks：回测任务表

```sql
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
```

关键要求：

1. 回测任务必须记录数据版本。
2. 必须记录手续费模型。
3. 必须记录滑点模型。
4. 必须记录初始资金。
5. 必须绑定策略版本。
6. 不允许只保存最终收益，不保存交易明细。

---

## 4.6.2 backtest_reports：回测报告表

```sql
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
```

---

## 4.6.3 backtest_trades：回测交易明细表

```sql
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
```

direction：

```text
long
short
```

---

## 4.6.4 backtest_equity_points：资金曲线点表，可选

如果资金曲线不大，可以入库；如果很大，建议保存为 Parquet，只在报告表记录路径。

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

第一版建议：

```text
资金曲线点数少：可入 PostgreSQL
批量回测很多：保存 Parquet，PostgreSQL 只存路径
```

---

# 4.7 信号扫描

## 4.7.1 signal_scan_tasks：信号扫描任务表

```sql
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
```

---

## 4.7.2 signals：策略信号表

```sql
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
```

signal_type 示例：

```text
entry
exit
warning
trend_change
breakout
pullback
stop_loss
take_profit
```

status 示例：

```text
new
viewed
ignored
watching
confirmed
converted_to_trade
```

---

# 4.8 复盘中心

## 4.8.1 review_notes：复盘记录表

```sql
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
```

source_type：

```text
backtest_trade
signal
manual_trade
live_trade
```

mistake_tags 示例：

```text
追价
震荡区入场
逆势
止损过大
过早出场
信号不完整
忽略大周期
```

---

# 4.9 风控配置

## 4.9.1 risk_profiles：风控模板表

```sql
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

针对你当前阶段，默认风控模板可按 10 万资金设计：

```json
{
  "account_size": 100000,
  "max_risk_per_trade_pct": 0.01,
  "max_margin_usage_pct": 0.4,
  "max_positions": 3,
  "max_consecutive_losses": 5
}
```

---

# 4.10 模拟与实盘，后期

第一版可以先建表但不启用，或者 V1.5 再建。

## 4.10.1 trading_accounts：交易账户表

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
```

account_type：

```text
simulation
live
```

注意：不保存明文交易密码。

---

## 4.10.2 orders：委托表

```sql
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
```

---

## 4.10.3 trades：实盘 / 模拟成交表

```sql
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
```

---

## 4.10.4 positions：持仓快照表

```sql
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

---

# 5. Parquet 行情数据设计

## 5.1 目录结构

建议目录：

```text
data/parquet/
  market/
    provider=tq/
      data_type=kline/
        period=1m/
          exchange=SHFE/
            instrument=rb/
              year=2025/
                rb2510_2025_1m.parquet

        period=30m/
          exchange=SHFE/
            instrument=rb/
              year=2025/
                rb2510_2025_30m.parquet

      data_type=tick/
        exchange=SHFE/
          instrument=rb/
            year=2025/
              month=01/
                rb2510_2025_01_tick.parquet

  backtest/
    equity/
    drawdown/
    parameter_search/

  reports/
    charts/
```

## 5.2 K 线 Parquet 字段

标准 K 线字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| datetime | timestamp | K 线开始时间 |
| trading_day | date | 交易日 |
| exchange | string | 交易所 |
| instrument_symbol | string | 品种 |
| contract_code | string | 合约 |
| period | string | 周期 |
| open | decimal/double | 开盘价 |
| high | decimal/double | 最高价 |
| low | decimal/double | 最低价 |
| close | decimal/double | 收盘价 |
| volume | int64 | 成交量 |
| open_interest | double/int64 | 持仓量 |
| turnover | double | 成交额 |
| source_provider | string | 数据源 |
| data_version | string | 数据版本 |
| created_at | timestamp | 写入时间 |

## 5.3 tick Parquet 字段，后期

| 字段 | 类型 | 说明 |
|---|---|---|
| datetime | timestamp | 时间戳 |
| trading_day | date | 交易日 |
| exchange | string | 交易所 |
| instrument_symbol | string | 品种 |
| contract_code | string | 合约 |
| last_price | double | 最新价 |
| volume | int64 | 成交量 |
| turnover | double | 成交额 |
| open_interest | double | 持仓量 |
| bid_price1 | double | 买一价 |
| bid_volume1 | int64 | 买一量 |
| ask_price1 | double | 卖一价 |
| ask_volume1 | int64 | 卖一量 |
| source_provider | string | 数据源 |
| data_version | string | 数据版本 |

第一版不建议做 tick 级回测，但可以预留字段。

---

# 6. DuckDB 查询设计

DuckDB 不需要长期作为业务库，主要用于读取 Parquet。

## 6.1 典型查询

```sql
SELECT
    datetime,
    open,
    high,
    low,
    close,
    volume,
    open_interest
FROM read_parquet('data/parquet/market/provider=tq/data_type=kline/period=30m/exchange=SHFE/instrument=rb/year=2025/*.parquet')
WHERE contract_code = 'rb2510'
  AND datetime >= '2025-01-01'
  AND datetime < '2025-12-31'
ORDER BY datetime;
```

## 6.2 回测取数流程

```text
回测任务读取 PostgreSQL
→ 找到策略、参数、合约、周期、时间范围
→ 查询 market_data_files 找到 Parquet 文件
→ DuckDB 读取 Parquet
→ 回测引擎运行
→ 结果写 PostgreSQL + Parquet
```

---

# 7. 数据版本与可复现设计

回测报告必须可复现，因此每次回测至少保存：

| 项目 | 存放位置 |
|---|---|
| 策略版本 | backtest_tasks.strategy_version_id |
| 参数 | backtest_tasks.parameter_set_id / JSON 快照 |
| 数据版本 | backtest_tasks.data_version |
| 手续费模型 | backtest_tasks.commission_model |
| 滑点模型 | backtest_tasks.slippage_model |
| 风控配置 | backtest_tasks.risk_config |
| 初始资金 | backtest_tasks.initial_capital |
| 回测区间 | backtest_tasks.start_time / end_time |

建议 data_version 格式：

```text
tq_20260623_v1
tq_20260623_cleaned_v1
rqdata_20260623_v1
```

---

# 8. 索引设计

## 8.1 PostgreSQL 必要索引

```sql
CREATE INDEX idx_contracts_instrument ON contracts(instrument_symbol);
CREATE INDEX idx_main_contract_map_instrument_date ON main_contract_map(instrument_symbol, trade_date);
CREATE INDEX idx_market_data_files_query ON market_data_files(contract_code, period, start_time, end_time);
CREATE INDEX idx_download_tasks_status ON data_download_tasks(status, created_at);
CREATE INDEX idx_backtest_tasks_status ON backtest_tasks(status, created_at);
CREATE INDEX idx_backtest_reports_task ON backtest_reports(task_id);
CREATE INDEX idx_backtest_trades_report ON backtest_trades(report_id);
CREATE INDEX idx_signals_time ON signals(signal_time);
CREATE INDEX idx_signals_contract_period ON signals(contract_code, period, signal_time);
CREATE INDEX idx_review_notes_source ON review_notes(source_type, source_id);
```

## 8.2 不建议第一版做的索引

第一版不要盲目加太多复合索引。先按实际查询慢点再补，否则会增加写入成本和维护复杂度。

---

# 9. 数据质量规则

数据质量检查至少包括：

| 检查项 | 说明 |
|---|---|
| 时间连续性 | 交易时段内 K 线是否缺失 |
| 重复时间戳 | 同一合约、周期、时间是否重复 |
| OHLC 合法性 | high >= open/close/low，low <= open/close/high |
| 成交量合法性 | volume >= 0 |
| 持仓量合法性 | open_interest >= 0 |
| 异常跳动 | 单根 K 线涨跌幅超阈值 |
| 夜盘归属 | 夜盘是否归属正确交易日 |
| 主力换月 | 主力合约切换是否断档 |
| 数据源差异 | 后期天勤和米筐对照 |
| 文件校验 | checksum 是否变化 |

质量状态：

```text
unchecked
passed
warning
failed
```

---

# 10. 数据库迁移与开发规范

## 10.1 使用 Alembic 管理表结构

所有 PostgreSQL 表结构变更必须通过 Alembic migration，不要直接手工改库。

目录建议：

```text
services/quant-api/
  alembic/
  alembic.ini
  app/models/
```

## 10.2 命名规范

| 类型 | 命名 |
|---|---|
| 表名 | 小写复数，下划线，例如 backtest_tasks |
| 字段名 | 小写下划线，例如 strategy_version_id |
| 主键 | id |
| 时间字段 | created_at、updated_at、started_at、finished_at |
| 状态字段 | status |
| JSON 字段 | config、params、summary、raw、details |

## 10.3 时间规范

统一使用：

```text
数据库时间：TIMESTAMPTZ
交易时间：保存交易所本地时间语义，同时明确 trading_day
前端展示：按中国期货交易时间展示
```

不要只按自然日处理夜盘。

---

# 11. 备份与恢复设计

第一版本地部署必须做备份，不需要上云。

## 11.1 PostgreSQL 备份

```bash
pg_dump -h localhost -U guiyi -d guiyi_quant > backups/postgres/guiyi_quant_$(date +%Y%m%d).sql
```

## 11.2 Parquet 备份

```text
data/parquet/
→ 外置 SSD
→ 每周全量备份
→ 每日增量备份
```

## 11.3 必备备份对象

| 对象 | 是否必须备份 |
|---|---|
| PostgreSQL | 必须 |
| Parquet 历史行情 | 必须 |
| 策略代码 | 必须，Git |
| 回测报告 | 必须 |
| 复盘记录 | 必须 |
| .env | 单独安全备份，不进 Git |
| logs | 可选 |

---

# 12. 第一版必须做 / 可以做 / 后期再做 / 不建议做

## 12.1 第一版必须做

```text
1. PostgreSQL 基础表
2. Parquet 行情存储目录
3. DuckDB 查询工具
4. 合约表
5. 品种表
6. 主力映射表
7. 交易日历表
8. 品种池表
9. 数据下载任务表
10. 行情文件索引表
11. 数据质量报告表
12. 策略表
13. 策略版本表
14. 策略参数表
15. 回测任务表
16. 回测报告表
17. 回测交易明细表
18. 信号表
19. 复盘记录表
20. 风控模板表
21. Alembic 迁移
22. 基础备份脚本
```

## 12.2 第一版可以做

```text
1. 资金曲线点表
2. 月度统计 JSON
3. 品种维度统计 JSON
4. 数据源对照字段
5. 数据质量评分
6. 回测参数搜索结果表
```

## 12.3 后期再做

```text
1. 实盘账户表
2. 委托表
3. 成交表
4. 持仓快照表
5. tick 数据落库和索引
6. ClickHouse
7. 多账户资金管理
8. 多数据源自动对账
9. AI 分析记录表
10. 策略组合层表
```

## 12.4 不建议第一版做

```text
1. 把全部 K 线存进 PostgreSQL
2. 一开始上 ClickHouse
3. 一开始做复杂 tick 级撮合库
4. 一开始做云数据库
5. 一开始做多用户权限
6. 一开始做复杂组合保证金
7. 一开始做数据售卖 / 分发权限系统
```

---

# 13. 推荐后端数据库模块结构

```text
services/quant-api/app/
  db/
    session.py
    base.py
    migrations.md

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
    trading.py

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

---

# 14. 第一阶段开发顺序

## Step 1：建基础库

```text
PostgreSQL Docker
SQLAlchemy 连接
Alembic 初始化
基础 health check
```

## Step 2：建元数据表

```text
instruments
contracts
trading_calendars
trading_sessions
watchlists
watchlist_items
```

## Step 3：建数据任务表

```text
data_sources
data_download_tasks
market_data_files
data_quality_reports
```

## Step 4：建策略与回测表

```text
strategies
strategy_versions
strategy_parameter_sets
backtest_tasks
backtest_reports
backtest_trades
```

## Step 5：建信号与复盘表

```text
signal_scan_tasks
signals
review_notes
risk_profiles
```

## Step 6：设计 Parquet 与 DuckDB

```text
目录结构
K线字段
文件索引
读取工具
数据质量检查工具
```

## Step 7：备份脚本

```text
PostgreSQL dump
Parquet 目录备份
恢复说明
```

---

# 15. 最终结论

归一量化数据库部分的核心不是“选一个数据库塞所有数据”，而是建立一个本地数据仓体系：

```text
PostgreSQL：业务元数据和结果
Parquet：历史行情主存储
DuckDB：研究查询和批量分析
Redis：任务状态和临时缓存
```

第一版只要把以下内容做好，就足够支撑后面的 Web、回测、信号扫描和复盘：

```text
合约与品种
数据下载任务
行情文件索引
数据质量报告
策略版本
回测任务
回测报告
交易明细
信号记录
复盘记录
风控配置
```

后期接天勤实盘、米筐数据、AI 策略迭代时，都不要推翻这套结构，只需要新增适配器和扩展表即可。
