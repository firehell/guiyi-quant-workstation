# 归一量化 Codex 从零搭建总控文档 V1

> 用途：把本文件直接交给 Codex，作为从空仓库开始搭建“归一量化”项目的总控说明。
> 项目定位：本地运行的国内期货量化研究、回测、策略盯盘、复盘、信号扫描、模拟交易和后期半自动实盘辅助系统。
> 第一版目标：先打通研究闭环，不做无人值守实盘。

---

## 0. 给 Codex 的总指令

你现在是“归一量化”项目的主力开发 Agent。请严格按照本文档从零搭建项目。

### 0.1 必须遵守

1. 不要一次性实现全部功能，按任务编号逐步开发。
2. 每次修改前先输出计划，每次修改后说明改了哪些文件、如何运行、如何测试。
3. 每个阶段必须能本地启动、能跑测试、能看到页面或接口结果。
4. 不允许提交任何 API Key、天勤账号、交易账号、交易密码、CTP 密码。
5. 默认 `ENABLE_LIVE_TRADING=false`，第一版不做实盘自动下单。
6. 回测、策略、信号扫描必须避免未来函数、数据泄露和过拟合。
7. 行情、信号、交易、风控必须拆分，不允许策略模块直接下单。
8. 先用 mock/sample 数据跑通，再接米筐试用、天勤专业版、Tushare。
9. 前端只通过 FastAPI REST/WebSocket 调用后端，不直接连接数据库或数据文件。
10. 大改前提醒用户做 Git checkpoint。

### 0.2 固定技术栈

不要重新发散选型。

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + TypeScript |
| UI | Naive UI |
| 状态管理 | Pinia |
| 路由 | Vue Router |
| HTTP | Axios |
| K线 | TradingView Lightweight Charts |
| 统计图 | Apache ECharts / vue-echarts |
| 后端 | Python 3.12 + FastAPI |
| ORM | SQLAlchemy 2 |
| 迁移 | Alembic |
| 校验 | Pydantic v2 / pydantic-settings |
| 元数据库 | PostgreSQL |
| 行情存储 | Parquet |
| 研究查询 | DuckDB |
| 任务队列 | Redis + RQ |
| 定时任务 | APScheduler / RQ Scheduler |
| 测试 | pytest |
| 代码质量 | ruff + mypy |
| 本地部署 | Docker Compose |

### 0.3 第一版不做

- 不做全自动实盘。
- 不做 tick 级高频回测。
- 不做复杂盘口队列撮合。
- 不做多用户权限系统。
- 不做手机 App。
- 不做策略商城。
- 不做 Web 策略代码编辑器。
- 不做 AI 自动生成策略并直接上线。

---

## 1. 项目总定位

“归一量化”不是普通网站，也不是公开 SaaS，而是本地期货交易研究工作台。

核心闭环：

```text
数据下载
→ 数据清洗
→ 行情状态识别
→ 策略参数配置
→ 回测验证
→ 回测报告
→ K线买卖点标记
→ 单笔复盘
→ 信号扫描
→ 模拟交易
→ 风控监控
→ 策略迭代
```

第一版的核心是：

```text
数据中心 + K线工作台 + 苏冰策略 V1 + 批量回测 + 信号扫描 + 复盘中心
```

后期才接：

```text
天勤模拟账户 → 人工确认下单 → 风控拦截 → 半自动实盘
```

---

## 2. 业务分层：行情与交易必须拆分

### 2.1 拆分原则

行情负责“看见市场”，交易负责“处理账户与订单”。策略只生成信号和交易意图，不直接成交。

```text
行情中心 Market Center
→ 策略中心 Strategy Center
→ 信号中心 Signal Center
→ 风控中心 Risk Center
→ 交易中心 Trade Center
→ 执行中心 Execution Center
→ 复盘中心 Review Center
```

### 2.2 各中心职责

| 中心 | 负责 | 不负责 |
|---|---|---|
| 数据中心 | 数据源、合约、交易日历、K线、质量检查 | 不生成交易信号 |
| 行情中心 | 历史行情、实时行情、指标、行情状态 | 不处理账户订单 |
| 策略中心 | 策略版本、参数模板、信号计算 | 不直接下单 |
| 信号中心 | 信号快照、信号状态机、扫描结果 | 不绕过风控 |
| 风控中心 | 单笔风险、保证金、日亏损、连续亏损、持仓限制 | 不生成交易逻辑 |
| 回测中心 | 历史撮合、成交模拟、报告、交易卡片 | 不代表实盘结果 |
| 交易中心 | 模拟持仓、委托、成交、资金、保证金 | 不重新计算策略 |
| 执行中心 | 人工确认、模拟下单、后期实盘接口 | 不允许无人值守实盘 |
| 复盘中心 | 单笔复盘、错误标签、策略归因 | 不改变历史数据 |

### 2.3 标准链路

```text
bar/tick 数据
→ 指标计算
→ strategy_signal
→ signal_snapshot
→ trade_intent
→ risk_check
→ manual_confirmation
→ order
→ trade
→ position
→ review_note
```

V1 实现到：

```text
行情数据 → 策略信号 → 回测成交 → 信号扫描 → 复盘记录
```

V1.5 实现到：

```text
模拟账户 → 模拟持仓 → 模拟订单 → 企业微信提醒
```

V2 才实现：

```text
人工确认 → 半自动实盘 → 风控拦截
```

---

## 3. 数据源与统一数据层

### 3.1 数据源分工

| 数据源 | 第一阶段角色 | 后期角色 | 备注 |
|---|---|---|---|
| 米筐试用 | 早期验证、对比数据体验 | 可作为补充 | 不是长期唯一数据源 |
| 天勤专业版 / TqSdk | 后期主数据源 | 主行情源 + 模拟/实盘接口 | 核心数据源 |
| Tushare | 交易日历、合约、主力映射、日线补充 | 元数据补充 | 新浪不能平替 |
| 新浪财经 / AKShare | 低优先级辅助校验 | 临时参考 | 不作为正式回测主源 |

### 3.2 统一数据层

多源数据不能直接给策略和回测使用，必须经过标准化。

```text
Source Adapter 数据源适配层
  ├── RiceQuantAdapter
  ├── TqSdkAdapter
  ├── TushareAdapter
  ├── SinaAdapter
  └── AkShareAdapter

Raw Zone 原始数据区
  ├── 原始字段
  ├── 原始代码
  ├── 原始时间戳
  └── 原始下载批次

Normalize Layer 标准化层
  ├── 合约代码统一
  ├── 交易所代码统一
  ├── 时间戳统一
  ├── 交易日归属统一
  ├── 夜盘归属统一
  ├── OHLCV 字段统一
  ├── 成交量/持仓量单位统一
  ├── 主力合约映射统一
  ├── 手续费规则统一
  └── 保证金规则统一

Quality Check 质量检查层
  ├── 缺失 K线
  ├── 重复 K线
  ├── OHLC 异常
  ├── 成交量异常
  ├── 持仓量异常
  ├── 夜盘断点
  ├── 主力切换异常
  └── 多源交叉校验

Canonical Store 标准数据仓
  ├── PostgreSQL：元数据、策略、任务、报告、信号、复盘
  ├── Parquet：历史 K线、tick、大体量行情
  └── DuckDB：研究查询、批量统计、回测读取
```

### 3.3 数据目录规范

```text
data/
├── raw/
│   ├── ricequant/
│   ├── tqsdk/
│   ├── tushare/
│   └── sina/
├── normalized/
│   ├── bars/
│   ├── ticks/
│   └── metadata/
├── parquet/
│   └── futures/
│       └── exchange=SHFE/
│           └── instrument=rb/
│               └── timeframe=2h/
├── sample/
└── quality_reports/
```

### 3.4 标准 K 线字段

```text
symbol              # 品种，如 rb
contract_code       # 合约，如 rb2410
exchange            # 交易所
trading_day         # 交易日
natural_date        # 自然日
datetime            # K线结束时间，统一时区
open
high
low
close
volume
open_interest
turnover
source
source_batch_id
is_night_session
is_main_contract
created_at
```

---

## 4. 项目工程结构

从空目录开始创建：

```text
guiyi-quant-workstation/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── pyproject.toml                  # 可选：根工作区配置
│
├── apps/
│   └── quant-web/                  # Vue 前端
│
├── services/
│   └── quant-api/                  # FastAPI 后端
│       ├── app/
│       │   ├── main.py
│       │   ├── api/
│       │   ├── core/
│       │   ├── db/
│       │   ├── models/
│       │   ├── schemas/
│       │   ├── services/
│       │   ├── tasks/
│       │   ├── data/
│       │   ├── market/
│       │   ├── strategy/
│       │   ├── signal/
│       │   ├── backtest/
│       │   ├── risk/
│       │   ├── trade/
│       │   ├── execution/
│       │   ├── review/
│       │   └── ai/
│       ├── alembic/
│       ├── tests/
│       └── pyproject.toml
│
├── packages/
│   └── quant-core/                 # 可复用量化核心，后期抽包
│       ├── indicators/
│       ├── strategies/
│       ├── backtest/
│       ├── risk/
│       └── tests/
│
├── strategies/
│   └── su_bing_ema21/
│       ├── README.md
│       ├── params/
│       └── research_notes.md
│
├── data/
│   ├── raw/
│   ├── normalized/
│   ├── parquet/
│   └── sample/
│
├── tqsdk-python/                  # 本地天勤源码参考目录，不作为项目代码提交
│
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── DATA_CENTER.md
│   ├── STRATEGY_SU_BING.md
│   ├── BACKTEST_ENGINE.md
│   ├── API_SPEC.md
│   ├── FRONTEND_SPEC.md
│   ├── DATABASE_SCHEMA.md
│   ├── RISK_CONTROL.md
│   ├── AGENT_WORKFLOW.md
│   └── ROADMAP.md
│
├── prompts/
│   ├── codex-start.md
│   ├── codex-feature.md
│   ├── claude-review.md
│   └── workbuddy-ui-fix.md
│
└── tasks/
    ├── pending/
    ├── running/
    ├── review/
    └── done/
```

---

## 5. 环境变量

创建 `.env.example`：

```env
GUIYI_ENV=development
GUIYI_PROJECT_NAME=guiyi-quant

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=guiyi
POSTGRES_PASSWORD=guiyi_dev_password
POSTGRES_DB=guiyi_quant
DATABASE_URL=postgresql+psycopg://guiyi:guiyi_dev_password@localhost:5432/guiyi_quant

REDIS_URL=redis://localhost:6379/0

DATA_ROOT=./data
PARQUET_ROOT=./data/parquet

TQSDK_USERNAME=
TQSDK_PASSWORD=
TUSHARE_TOKEN=

ENABLE_LIVE_TRADING=false
ENABLE_PAPER_TRADING=false
ENABLE_AI_STRATEGY_GENERATION=false
```

创建 `.gitignore`：

```gitignore
.DS_Store
.env
.env.*
!.env.example
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
node_modules/
dist/
build/
.vite/
data/raw/
data/normalized/
data/parquet/
*.parquet
*.duckdb
*.db
*.sqlite
tqsdk-python/
logs/
*.log
secrets/
*.key
*.pem
backtests/results/
backtests/reports/
.idea/
.vscode/
```

---

## 6. Docker Compose

创建 `docker-compose.yml`：

```yaml
services:
  postgres:
    image: postgres:16
    container_name: guiyi-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: guiyi
      POSTGRES_PASSWORD: guiyi_dev_password
      POSTGRES_DB: guiyi_quant
    ports:
      - "5432:5432"
    volumes:
      - guiyi_postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    container_name: guiyi-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - guiyi_redis_data:/data

volumes:
  guiyi_postgres_data:
  guiyi_redis_data:
```

验收：

```bash
docker compose up -d
docker ps
docker exec -it guiyi-redis redis-cli ping
```

---

## 7. 后端模块设计

### 7.1 后端目录

```text
services/quant-api/app/
├── main.py
├── core/
│   ├── config.py
│   ├── logging.py
│   ├── security.py
│   └── errors.py
├── db/
│   ├── session.py
│   ├── base.py
│   └── init_db.py
├── models/
├── schemas/
├── api/
│   ├── routes_health.py
│   ├── routes_data.py
│   ├── routes_market.py
│   ├── routes_strategy.py
│   ├── routes_signal.py
│   ├── routes_backtest.py
│   ├── routes_risk.py
│   ├── routes_trade.py
│   └── routes_review.py
├── services/
├── tasks/
├── data/
├── market/
├── strategy/
├── signal/
├── backtest/
├── risk/
├── trade/
├── execution/
├── review/
└── ai/
```

### 7.2 FastAPI 基础接口

V0 先实现：

```text
GET /api/health
GET /api/dashboard/summary
GET /api/contracts
GET /api/watchlists
GET /api/strategies
GET /api/backtests/tasks
```

### 7.3 任务队列

耗时任务必须进入 RQ：

```text
data_download
quality_check
backtest_single
backtest_batch
signal_scan
report_build
ai_analysis
```

任务表与 RQ 任务需要关联：

```text
job_id
status: pending/running/success/failed/canceled
progress
message
started_at
finished_at
error_message
```

---

## 8. 数据库设计

### 8.1 基础元数据

#### instruments

```sql
id
symbol                  -- rb, hc, i, j, TA, MA
name
sector                  -- 黑色/化工/能源/农产品/有色
exchange
price_tick
volume_multiple
default_margin_ratio
min_lot
enabled
created_at
updated_at
```

#### contracts

```sql
id
instrument_id
contract_code           -- rb2410
exchange
list_date
expire_date
last_trade_date
delivery_month
is_active
created_at
updated_at
```

#### trading_sessions

```sql
id
instrument_id
exchange
session_type            -- day/night
start_time
end_time
trading_day_rule        -- night_belongs_next_day 等
enabled
```

#### trading_calendars

```sql
id
exchange
trading_day
is_trading_day
has_night_session
remark
```

#### fee_margin_rules

```sql
id
instrument_id
contract_id nullable
start_date
end_date
open_fee_type           -- by_volume/by_turnover
open_fee
close_fee
close_today_fee
margin_ratio_long
margin_ratio_short
source
```

### 8.2 数据任务与质量

#### data_sources

```sql
id
name                    -- ricequant/tqsdk/tushare/sina/akshare
source_type             -- market/metadata/auxiliary
priority
enabled
auth_required
status
last_check_time
remark
```

#### data_ingest_batches

```sql
id
source_id
data_type               -- bar/tick/contract/calendar/fee_margin
started_at
finished_at
status
row_count
checksum
version
message
```

#### data_download_tasks

```sql
id
source_id
instrument_id
contract_id nullable
timeframe
start_time
end_time
status
progress
job_id
error_message
created_at
updated_at
```

#### data_quality_reports

```sql
id
batch_id
instrument_id
contract_id nullable
timeframe
check_type              -- missing/duplicate/ohlc_error/outlier/gap
severity                -- info/warning/error
start_time
end_time
details_json
fixed_status
created_at
```

### 8.3 主力映射与换月

#### contract_roll_maps

```sql
id
instrument_id
trade_date
main_contract_id
next_contract_id
source_id
roll_reason             -- volume/open_interest/fixed_days_before_delivery
roll_confirmed
created_at
```

### 8.4 策略与参数

#### strategies

```sql
id
code                    -- su_bing_ema21
name
category                -- trend/swing/breakout
status
description
created_at
updated_at
```

#### strategy_versions

```sql
id
strategy_id
version                 -- v1.0.0
logic_hash
code_path
changelog
is_active
created_at
```

#### strategy_param_profiles

```sql
id
strategy_version_id
name                    -- 黑色2H模板/化工2H模板/能源4H模板
instrument_group
timeframe
params_json
risk_json
enabled
created_at
```

#### strategy_instrument_overrides

```sql
id
param_profile_id
instrument_id
override_params_json
reason
created_at
```

### 8.5 信号、交易意图、风控

#### signal_snapshots

```sql
id
strategy_version_id
instrument_id
contract_id
timeframe
direction               -- long/short/neutral
signal_level            -- 51/60/70/80
state                   -- watch/momentum/volume_breakout/trial/hold/add/reduce/exit
entry_price
stop_price
target_price
volume_ratio
risk_amount
margin_required
reason_json
created_at
```

#### signal_state_transitions

```sql
id
signal_snapshot_id
from_state
to_state
trigger_reason
price
created_at
```

#### trade_intents

```sql
id
source_signal_id
action                  -- open/add/reduce/close/roll
side                    -- long/short
suggested_lots
price_type              -- market/limit/stop
limit_price nullable
stop_price nullable
risk_check_status       -- pending/passed/rejected
manual_confirm_required
status                  -- draft/approved/rejected/executed/canceled
created_at
```

#### risk_checks

```sql
id
trade_intent_id
single_trade_risk
margin_usage_after
daily_loss_after
max_position_after
result                  -- pass/reject/warn
reject_reason
created_at
```

### 8.6 回测

#### backtest_tasks

```sql
id
name
strategy_version_id
param_profile_id
mode                    -- single/batch/grid
status
job_id
progress
config_json
started_at
finished_at
created_at
```

#### backtest_reports

```sql
id
backtest_task_id
strategy_version_id
instrument_id nullable
summary_json
equity_curve_path
drawdown_curve_path
trades_path
created_at
```

#### backtest_trades

```sql
id
backtest_report_id
instrument_id
contract_id
timeframe
side
entry_time
entry_price
exit_time
exit_price
lots
pnl
pnl_pct
fee
slippage
margin_used
max_floating_loss
max_floating_profit
entry_reason
exit_reason
created_at
```

#### backtest_trade_cards

```sql
id
backtest_report_id
trade_id
title
card_json
created_at
```

### 8.7 K线标记与复盘

#### chart_markers

```sql
id
instrument_id
contract_id
timeframe
marker_type             -- A/B/J/X/SL/ROLL/signal
side
price
time
label
source_type             -- backtest/scan/manual/live
source_id
created_at
```

#### review_notes

```sql
id
source_type             -- backtest_trade/live_trade/manual
source_id
instrument_id
contract_id
timeframe
entry_reason
exit_reason
mistake_tags_json
emotion_tags_json
lesson
screenshot_path nullable
created_at
updated_at
```

### 8.8 盯盘和推送

#### watchlists

```sql
id
name
description
enabled
created_at
```

#### watchlist_items

```sql
id
watchlist_id
instrument_id
contract_id nullable
sort_order
enabled
created_at
```

#### notification_rules

```sql
id
rule_type               -- price_alert/signal_change/risk_alert/task_done
instrument_id nullable
strategy_id nullable
threshold_json
channel                 -- web/wechat/email
webhook_url_encrypted nullable
enabled
created_at
```

---

## 9. 前端页面设计

### 9.1 前端目录

```text
apps/quant-web/src/
├── app/
│   ├── router.ts
│   └── pinia.ts
├── layouts/
│   └── MainLayout.vue
├── pages/
│   ├── dashboard/
│   ├── data/
│   ├── watchlist/
│   ├── market/
│   ├── strategy/
│   ├── signal/
│   ├── backtest/
│   ├── risk/
│   ├── trade/
│   ├── review/
│   └── settings/
├── components/
│   ├── kline/
│   ├── charts/
│   ├── signal/
│   ├── backtest/
│   ├── risk/
│   ├── tables/
│   └── common/
├── api/
├── stores/
├── types/
├── utils/
└── websocket/
```

### 9.2 页面清单

| 页面 | 路由 | V1 目标 |
|---|---|---|
| Dashboard | `/` | 数据状态、任务、信号、策略、风险摘要 |
| 数据中心 | `/data` | 数据源、下载任务、质量检查 |
| 品种池/盯盘 | `/watchlist` | 黑色/化工/能源信号看板 |
| 品种详情 | `/market/:instrumentId` | 行情、K线、策略状态、回测交易卡片 |
| 策略中心 | `/strategies` | 苏冰策略、版本、参数模板 |
| 信号扫描 | `/signals` | 全品种/品种池扫描，结果筛选 |
| 回测任务 | `/backtests` | 创建单品种/批量回测任务 |
| 回测报告 | `/backtests/:id` | 报告、交易明细、资金曲线、K线标记 |
| 风控中心 | `/risk` | 风险预算、保证金、单笔风险 |
| 复盘中心 | `/reviews` | 单笔复盘、错误标签、策略归因 |
| 系统设置 | `/settings` | 数据路径、推送、刷新间隔、开关 |

### 9.3 盯盘首页设计

参考牛哇“买入/持有/卖出/空仓”的可视化方式，但期货版使用：

| 状态 | 图标建议 | 含义 |
|---|---|---|
| 观察 | 灰色圆点 | 趋势还不明确 |
| 试单 A | 红色 A | 带量突破轻仓试单 |
| 持仓 | 黄色对勾 | 趋势仍在，持仓观察 |
| 加仓 B | 橙色 B | 回调不破后二次突破 |
| 减仓 J | 绿色 J | 标准减仓点 |
| 清仓 X | 蓝色 X | 趋势失效或风险过高 |

列表字段：

```text
品种 / 主力合约
最新价 / 涨跌幅
方向：多头/空头/震荡
信号优势：51/60/70/80
状态：观察/试单/持仓/加仓/减仓/清仓
入场价
止损价
目标价
可开手数
预计保证金
单笔风险
信号时间
```

### 9.4 品种详情页设计

模块顺序：

```text
顶部行情区
→ 多周期状态卡
→ 苏冰信号解释卡
→ K线图 + 标记
→ 指标面板
→ 回测操盘提醒
→ 策略收益曲线
→ 风控卡
→ 复盘记录
```

顶部行情字段：

```text
主力合约、最新价、涨跌幅、最高、最低、开盘、成交量、持仓量、增仓/减仓、结算价、合约乘数、保证金率、手续费、最后交易日、强制换月日
```

### 9.5 K线标记

| 标记 | 程序含义 |
|---|---|
| A | 带量突破轻仓试单 |
| B | 回调不破后二次加仓 |
| J | 减仓点 |
| X | 清仓点 |
| SL | 止损点 |
| TP | 目标/止盈观察点 |
| ROLL | 移仓换月 |

---

## 10. 苏冰策略 V1.3 程序化设计

### 10.1 策略本质

苏冰系统不能简化成 EMA21 + MACD。它是：

```text
均线方向过滤
+ MACD 零轴附近动能确认
+ 成交量放大验证突破力度
+ 多周期共振提高信号质量
+ 带量突破轻仓试单
+ 回调不破后二次加仓
+ 盈利单分段减仓
+ 亏损/假突破快速退出
```

### 10.2 信号优势等级

注意：51/60/70/80 是“经验优势等级”，不是承诺胜率。系统必须同时显示“经验优势等级”和“回测真实胜率”。

| 等级 | 条件 | 展示文案 | 系统动作 |
|---|---|---|---|
| 51 | 价格在均线方向一侧 | 趋势顺风 | 只观察，不直接开仓 |
| 60 | 增加 MACD 零轴附近金叉/死叉 | 动能确认 | 进入重点观察 |
| 70 | 增加成交量放大 | 带量突破 | 可轻仓试单 |
| 80 | 增加多周期共振 | 共振信号 | 重点盯盘，可按风控计划交易 |

文案示例：

```text
信号优势 70：带量突破
趋势方向、MACD 动能和短周期放量已同向，允许轻仓试单；若突破失败，按小周期止损退出。
```

```text
信号优势 80：多周期共振
日线方向与 30M/15M 入场信号共振，属于高质量观察信号；仍需按单笔风险和保证金约束执行。
```

### 10.3 均线规则

默认：

```text
核心均线：EMA21
趋势均线：MA/EMA60 可选
短线辅助：MA10 可选
```

多头：

```text
close > EMA21
EMA21 slope > 0
价格不围绕 EMA21 反复穿越
```

空头：

```text
close < EMA21
EMA21 slope < 0
价格不围绕 EMA21 反复穿越
```

震荡过滤：

```text
lookback=N 根 K 线内，价格穿越 EMA21 次数 >= threshold，则标记为震荡，不开趋势单。
```

### 10.4 MACD 零轴附近规则

多头：

```text
DIFF 上穿 DEA
DIFF 和 DEA 接近 0 轴
MACD 柱由弱转强或红柱放大
```

空头：

```text
DIFF 下穿 DEA
DIFF 和 DEA 接近 0 轴
MACD 柱由弱转弱或绿柱放大
```

零轴附近不能写死，使用 ATR 标准化：

```text
near_zero = abs(diff) <= atr * diff_zero_threshold_atr
         and abs(dea) <= atr * dea_zero_threshold_atr
```

### 10.5 成交量放大规则

成交量比较对象默认是前一根 K 线，不先引入复杂均量。

| 周期 | 成交量规则 | 用途 |
|---|---|---|
| 5 分钟 | 当前量 >= 前一根 3 倍 | 日内突破试单 |
| 15 分钟 | 当前量 >= 前一根 3 倍 | 关键突破确认 |
| 30 分钟 | 当前量 >= 前一根 3 倍 | 短波段确认 |
| 日线 | 当前量 > 前一日 | 趋势延续参考 |
| 周线 | 当前量 > 前一周 | 背景参考 |

程序字段：

```text
volume_ratio = current_volume / previous_volume
volume_breakout = volume_ratio >= 3.0   # 5/15/30m
volume_breakout = volume_ratio > 1.0    # 1d/1w
```

### 10.6 带量突破轻仓试单 A 点

不是必须等 3 根 K 确认真突破后再入场。苏冰系统允许在带量突破时轻仓跟随，失败后快速平掉。

A 点条件：

```text
1. 均线方向一致
2. MACD 零轴附近动能确认
3. 5/15/30 分钟成交量 >= 前一根 3 倍，或日线成交量 > 前一日
4. 突破震荡区间高点/低点或关键前高/前低
5. 不处于快速反向行情
```

A 点动作：

```text
trade_intent.action = open
trade_intent.label = A
position_type = trial
lots = 计划仓位的 20%-30%，或 0.5R 风险
stop = 突破 K 起涨点 / 区间边界 / 小周期 EMA21
```

失败处理：

```text
突破后 1-3 根 K 重新回到区间内，或跌破试单止损，立即 X 清仓。
```

### 10.7 二次确认加仓 B 点

B 点不是第一入场，而是“已有底仓浮盈后的确认加仓”。

B 点条件：

```text
1. A 点已有浮盈
2. 回调不破起涨点/不破 EMA21/不回原震荡区间
3. 再次突破前高/前低
4. 成交量再次放大
5. 持仓量增加更优
6. 加仓后总风险仍在风控上限内
```

B 点动作：

```text
trade_intent.action = add
trade_intent.label = B
add_lots <= current_lots
stop_new = B 点前低/前高
stop_old = A 点原止损可跟踪上移，但不能让总风险扩大
```

### 10.8 减仓 J 点

苏冰减仓点必须程序化，不能只做一个平仓。

| 减仓类型 | 触发 | 动作 |
|---|---|---|
| 快速大幅盈利 | 短时间浮盈 >= 2R/3R 或保证金收益 >= 30% | 减 20%-30%，留底仓 |
| 上一根 K 高低点 | 多单跌破上一根 K 低点；空单突破上一根 K 高点 | 减仓或跟踪止盈 |
| MACD 背离 | 多单高位背离/死叉；空单低位背离/金叉 | 减仓，不反手 |
| 走势不及预期 | 入场后 3-5 根 K 不盈利，或反复穿均线 | 减仓/清仓 |
| 假突破 | 突破后快速回原区间 | 试单直接退出 |
| 盈利不能变亏 | 浮盈后回到成本附近 | 保护性减仓或清仓 |

### 10.9 清仓 X 点

清仓条件：

```text
1. 触发硬止损
2. 趋势失效，价格破核心均线
3. 频繁穿越均线，进入震荡
4. 假突破确认
5. 走势不及预期且时间止损触发
6. 临近换月需要平旧合约
7. 风控触发：日亏损、保证金、连续亏损、最大回撤
```

### 10.10 状态机

```text
EMPTY 空仓
→ WATCH 趋势观察
→ MOMENTUM 动能确认
→ BREAKOUT 带量突破
→ TRIAL A点试单
→ HOLD 持仓观察
→ ADD_READY B点准备加仓
→ ADD 加仓
→ TREND_HOLD 趋势持有
→ REDUCE J点减仓
→ EXIT X点清仓
→ REVIEW 复盘
```

多空对称：

```text
多头：均线上方 → 零轴金叉 → 放量上破 → A 试单 → 回调不破 → B 加仓 → J 减仓 → X 清仓
空头：均线下方 → 零轴死叉 → 放量下破 → A 试单 → 回抽不过 → B 加仓 → J 减仓 → X 清仓
```

---

## 11. 风控设计

### 11.1 账户默认

按 10 万级别中小资金账户设计。

默认风险参数：

```text
account_equity = 100000
risk_per_trade_pct = 0.5% ~ 1.0%
max_daily_loss_pct = 2%
max_total_drawdown_pct = 10% ~ 15%
max_margin_usage_pct = 35%
max_single_instrument_margin_pct = 20% ~ 30%
max_open_positions = 3
```

### 11.2 以损定量

```text
每手风险 = abs(entry_price - stop_price) * volume_multiple
允许亏损 = account_equity * risk_per_trade_pct
可开手数 = floor(允许亏损 / 每手风险)
```

还必须受保证金约束：

```text
每手保证金 = entry_price * volume_multiple * margin_ratio
保证金允许手数 = floor(可用保证金上限 / 每手保证金)
最终手数 = min(风险手数, 保证金手数, 品种上限手数)
```

### 11.3 风控拦截

任何 trade_intent 进入执行前必须检查：

```text
单笔风险
保证金占用
日亏损
连续亏损
最大持仓数
同品种持仓上限
临近换月
数据质量状态
是否处于禁交易时间
```

V1 只做检查和报告，不下实盘单。

---

## 12. 回测引擎设计

### 12.1 核心对象

```text
BacktestEngine
├── DataFeed
├── TradingCalendar
├── RollManager
├── StrategyRunner
├── SignalEngine
├── BrokerSimulator
├── FeeModel
├── SlippageModel
├── MarginModel
├── PositionManager
├── RiskManager
├── Portfolio
├── ReportBuilder
└── AuditLogger
```

### 12.2 回测原则

1. 信号在当前 K 收盘后确认。
2. 市价单默认下一根 K 开盘成交。
3. 限价单必须 high/low 触达才成交。
4. 止损遇跳空，按可成交开盘价处理，不按理想止损价美化。
5. 手续费、滑点、合约乘数、保证金必须计入。
6. 主力换月、交割月前退出必须计入。
7. 多品种可并行，但组合账户风险统一聚合。
8. 回测必须输出交易明细和 K线标记。
9. 回测结果不等于实盘结果。

### 12.3 撮合规则

```text
市价开仓：signal bar close 确认 → next bar open + slippage 成交
限价开仓：next bars 触达 limit_price 才成交
止损：触发价可成交则按 stop_price + slippage；跳空穿越则按 next open
止盈：触达目标价才成交
减仓：按规则生成 reduce intent，下一根 K 成交
加仓：只在已有浮盈且风控通过时执行
换月：强制换月日平旧开新，手续费和滑点计入
```

### 12.4 报告指标

```text
总收益
年化收益
最大回撤
最大回撤持续时间
胜率
盈亏比
期望值
平均盈利
平均亏损
最大连续亏损
单笔最大亏损
平均持仓周期
手续费总额
滑点总额
换月成本
最大保证金占用
平均保证金占用
品种贡献
月度收益
交易明细
K线标记
样本内/样本外表现
```

---

## 13. API 设计

### 13.1 Health

```text
GET /api/health
GET /api/dashboard/summary
```

### 13.2 Data

```text
GET  /api/data/sources
POST /api/data/sources/test
GET  /api/contracts
GET  /api/instruments
GET  /api/trading-calendars
POST /api/data/download-tasks
GET  /api/data/download-tasks
GET  /api/data/quality-reports
```

### 13.3 Market

```text
GET /api/market/bars
GET /api/market/overview/{instrument_id}
GET /api/market/markers
GET /api/market/multi-timeframe-state
```

### 13.4 Watchlist

```text
GET  /api/watchlists
POST /api/watchlists
GET  /api/watchlists/{id}/items
POST /api/watchlists/{id}/items
GET  /api/watchlists/{id}/signal-summary
```

### 13.5 Strategy

```text
GET  /api/strategies
GET  /api/strategies/{id}
GET  /api/strategies/{id}/versions
GET  /api/strategy-param-profiles
POST /api/strategy-param-profiles
PUT  /api/strategy-param-profiles/{id}
```

### 13.6 Signal

```text
POST /api/signals/scan
GET  /api/signals/tasks
GET  /api/signals/results
GET  /api/signals/snapshots
GET  /api/signals/snapshots/{id}
```

### 13.7 Backtest

```text
POST /api/backtests/run
POST /api/backtests/run-batch
GET  /api/backtests/tasks
GET  /api/backtests/reports/{id}
GET  /api/backtests/reports/{id}/trades
GET  /api/backtests/reports/{id}/equity-curve
GET  /api/backtests/reports/{id}/drawdown-curve
```

### 13.8 Risk

```text
POST /api/risk/check-intent
GET  /api/risk/profiles
PUT  /api/risk/profiles/{id}
GET  /api/risk/dashboard
```

### 13.9 Review

```text
GET  /api/reviews
POST /api/reviews
GET  /api/reviews/{id}
PUT  /api/reviews/{id}
```

### 13.10 WebSocket

```text
WS /ws/tasks
WS /ws/signals
```

---

## 14. V0 / V1 开发任务清单

### T-000：初始化仓库

目标：创建目录、Git、基础文档、`.env.example`、`.gitignore`。

验收：

```bash
git status
ls
```

### T-001：Docker 基础服务

目标：PostgreSQL + Redis。

验收：

```bash
docker compose up -d
docker exec -it guiyi-redis redis-cli ping
```

### T-002：FastAPI 后端壳子

目标：创建 `services/quant-api`，实现 `/api/health` 和 `/api/dashboard/summary`。

验收：

```bash
cd services/quant-api
uv run uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/api/health
```

### T-003：Vue 前端壳子

目标：创建 `apps/quant-web`，实现主布局、路由、Naive UI、暗色主题。

验收：

```bash
cd apps/quant-web
pnpm dev --host 0.0.0.0 --port 5173
```

### T-004：数据库模型与 Alembic

目标：实现基础元数据表、策略表、任务表。

最小表：

```text
instruments
contracts
data_sources
strategies
strategy_versions
strategy_param_profiles
backtest_tasks
signal_snapshots
watchlists
```

验收：

```bash
uv run alembic revision --autogenerate -m "init schema"
uv run alembic upgrade head
```

### T-005：数据中心 V0

目标：mock 数据源、合约列表、下载任务页面。

后端：

```text
GET /api/data/sources
GET /api/instruments
GET /api/contracts
GET /api/data/download-tasks
```

前端页面：`/data`

### T-006：样本 K 线与 Market API

目标：用 sample CSV/Parquet 返回 K线。

后端：

```text
GET /api/market/bars?instrument=rb&timeframe=2h
```

前端：K线工作台能显示 K线。

### T-007：指标计算 V0

目标：实现 EMA21、MACD、ATR、成交量放大比率。

测试：

```text
输入固定 K线，输出指标不得使用未来数据。
```

### T-008：苏冰策略 V1.3

目标：实现信号等级 51/60/70/80、A/B/J/X 状态机。

核心输出：

```text
signal_snapshot
chart_markers
trade_intent_draft
```

不下单。

### T-009：信号扫描中心

目标：品种池批量扫描。

后端：

```text
POST /api/signals/scan
GET /api/signals/results
```

前端页面：`/signals`

### T-010：回测引擎 V0

目标：bar 级事件驱动回测，支持单品种、手续费、滑点、保证金、交易明细。

不做：tick 级撮合。

### T-011：苏冰策略回测接入

目标：苏冰策略产生的 A/B/J/X 信号进入回测。

输出：

```text
交易明细
资金曲线
回撤曲线
K线标记
交易卡片
```

### T-012：批量回测

目标：黑色/化工/能源品种池批量回测。

实现：RQ 子任务 + 汇总报告。

### T-013：回测报告页面

目标：资金曲线、回撤曲线、交易明细、交易卡片、指标摘要。

前端页面：`/backtests/:id`

### T-014：品种详情页

目标：行情顶部、策略状态卡、K线标记、近期回测交易卡片。

页面：`/market/:instrumentId`

### T-015：盯盘首页

目标：参考牛哇盯盘风格，但期货化。

字段：品种、价格、涨跌、信号等级、A/B/J/X、风险、目标价、止损价。

### T-016：复盘中心

目标：单笔交易复盘卡，记录入场依据、出场原因、错误标签。

### T-017：风控中心 V0

目标：单笔风险、保证金占用、最大回撤、连续亏损。

### T-018：企业微信推送预留

目标：只做配置和测试接口，不强制接入。

### T-019：文档与测试整理

目标：补 README、API_SPEC、测试说明、运行说明。

---

## 15. 测试要求

### 15.1 单元测试

必须覆盖：

```text
EMA/MACD/ATR 指标
成交量放大规则
震荡过滤规则
信号等级计算
A/B/J/X 状态机
以损定量
手续费计算
保证金计算
最大回撤计算
撮合成交规则
```

### 15.2 未来函数检查

必须测试：

```text
第 N 根 K 线信号，只能使用 <= N 的数据。
第 N 根收盘确认信号，成交不能在第 N 根收盘价默认成交。
多周期数据对齐时，小周期不能提前看到未收盘的大周期 K 线。
```

### 15.3 回测回归样例

准备一份小型 sample 数据，固定输出，避免后续改动破坏结果。

---

## 16. Codex 标准工作流

每个任务开始时先输出：

```text
1. 我将修改哪些文件
2. 我不会修改哪些文件
3. 实现步骤
4. 风险点
5. 验收命令
```

每个任务完成后输出：

```text
1. 已修改文件列表
2. 新增接口/页面/模型
3. 如何运行
4. 如何测试
5. 已知限制
6. 下一步建议
```

---

## 17. 第一条 Codex Prompt

把下面这段直接复制给 Codex：

```text
你现在是“归一量化”项目的主力开发 Agent。

请先阅读当前文档《归一量化 Codex 从零搭建总控文档 V1》。

项目定位：本地运行的国内期货量化研究、回测、策略盯盘、复盘、信号扫描和后期半自动实盘辅助系统。

固定技术栈：
前端 Vue 3 + Vite + TypeScript + Naive UI。
后端 Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic。
数据 PostgreSQL + Parquet + DuckDB。
任务 Redis + RQ。

当前任务：从空目录初始化项目骨架，只完成 T-000 和 T-001。

要求：
1. 先输出你的理解和实施计划。
2. 不要一次性实现所有模块。
3. 创建目录、.gitignore、.env.example、docker-compose.yml、基础 README。
4. 不要写入任何真实账号或密钥。
5. 完成后说明如何启动 PostgreSQL 和 Redis，如何验收。
```

---

## 18. 第二条 Codex Prompt

```text
继续归一量化项目，现在执行 T-002：FastAPI 后端壳子。

要求：
1. 在 services/quant-api 创建 Python 3.12 + FastAPI 项目。
2. 使用 uv 管理依赖。
3. 实现 /api/health 和 /api/dashboard/summary。
4. 配置 pydantic-settings 读取 .env。
5. 配置 CORS，允许 http://localhost:5173。
6. 不连接真实数据源。
7. 写 README 说明启动命令。
8. 给出测试命令。
```

---

## 19. 第三条 Codex Prompt

```text
继续归一量化项目，现在执行 T-003：Vue 前端壳子。

要求：
1. 在 apps/quant-web 创建 Vue 3 + Vite + TypeScript 项目。
2. 安装 Naive UI、Pinia、Vue Router、Axios、ECharts、Lightweight Charts。
3. 创建暗色主布局 MainLayout。
4. 创建页面路由：Dashboard、数据中心、盯盘、品种详情、策略中心、信号扫描、回测、复盘、风控、设置。
5. Dashboard 调用后端 /api/health。
6. 不做登录。
7. 不直接连接数据库。
8. 完成后说明运行命令和页面地址。
```

---

## 20. 关键验收标准

项目从零搭建到 V1 的最低验收标准：

```text
[ ] Docker PostgreSQL 正常运行
[ ] Docker Redis 正常运行
[ ] FastAPI /api/health 正常
[ ] Vue 前端可启动
[ ] 前端可调用后端 health
[ ] 数据中心页面有骨架
[ ] K线工作台能显示 sample K线
[ ] 苏冰策略能输出 51/60/70/80 信号等级
[ ] 苏冰策略能标记 A/B/J/X
[ ] 单品种回测能输出交易明细
[ ] 批量回测能跑品种池
[ ] 回测报告有资金曲线和回撤曲线
[ ] K线图能显示买卖点/加仓点/减仓点
[ ] 复盘中心能记录单笔交易
[ ] 风控中心能计算单笔风险和保证金占用
[ ] 测试覆盖核心指标和回测逻辑
[ ] README 能让新开发者本地跑起来
```

---

## 21. 安全边界

1. 第一版只做研究、回测、盯盘、复盘、信号扫描。
2. 不做无人值守自动实盘。
3. 任何实盘接口必须经过：信号扫描 → 人工观察 → 模拟交易 → 小资金实盘 → 人工确认下单 → 半自动执行。
4. AI 只能做研究助理、复盘助理、代码助手，不是自动交易员。
5. 回测结果不等于实盘结果。
6. 每次策略优化必须防止未来函数、数据泄露、过拟合。
7. 数据源异常、数据质量异常时，策略信号必须降级或禁用。

---

## 22. 当前最优开发顺序

```text
Day 1：项目骨架 + Docker
Day 2：FastAPI 后端壳子 + Vue 前端壳子
Day 3：数据库模型 + Alembic
Day 4：数据中心 V0 + sample K线
Day 5：K线工作台 + 指标计算
Day 6：苏冰策略 V1.3 信号状态机
Day 7：单品种回测 + 报告
Day 8：批量回测 + 盯盘首页
Day 9：品种详情页 + K线标记
Day 10：复盘中心 + 风控中心
```

---

## 23. 最终说明

本文件是 Codex 从零搭建归一量化的总控文档。Codex 应按任务编号逐步实现，而不是一次性生成一个无法维护的大项目。

第一阶段目标不是页面炫酷，而是让系统真正形成：

```text
数据可信
→ 信号可解释
→ 回测可复现
→ 风险可计算
→ 交易可复盘
→ 策略可迭代
```
