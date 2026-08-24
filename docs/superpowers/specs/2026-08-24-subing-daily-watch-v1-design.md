# 苏冰今日观察 V1 设计

更新时间：2026-08-24  
状态：用户已批准产品方案；本文件冻结产品、数据、存储、Runtime 与 Web 合同，授权后续按配套 Implementation Plan 实施。它不授权代码实现之外的真实扩展盘写入、Alert Scope 变更、真实通知、release、main/tag、Runtime switch/promotion、正式 DB/Redis/Canonical mutation 或订单能力。

本设计取代以下旧方向：

- `docs/superpowers/specs/2026-08-24-four-system-all-frequency-market-observation-design.md`
- `docs/superpowers/plans/2026-08-24-four-system-all-frequency-market-observation.md`

当前 `STATUS.md` 仍把旧“四体系 Active60 全周期 Observation”标记为可恢复，因此在旧文档退出 active surface、`STATUS.md` 完成收口前，任何代码实现都必须 fail-closed。旧文档和状态的关闭是配套 Implementation Plan 的 Task 0，不属于本次两份文档提交本身。

## 1. 背景与问题

归一量化是本地优先、单用户的国内期货研究工作站。项目的实际问题不是缺少更多策略或指标，而是：

1. 用户白天不能持续盯盘；
2. active60 品种过多，即使盯盘也无法稳定检查全部品种；
3. 当前收到苏冰信号后仍需要人工重新判断大周期方向、趋势与震荡背景；
4. N 字、日进斗金等研究资产尚未形成明确的国内期货生产用途，继续横向扩展会增加认知和维护负担。

用户已经确认新的产品收敛：

```text
生产核心
├── 火天大有 Watcher
└── 苏冰 Trading Assistant

研究辅助
└── N Structure：未来可能作为苏冰大周期结构背景，当前不接入

Research Shelf
└── 日进斗金：保留现有研究资产，当前不扩展
```

本阶段只建设 `苏冰今日观察 V1`，先解决“今天看什么”，再由既有 5m/15m 苏冰链解决“盘中什么时候值得检查”。

## 2. 产品目标

每天现有盘后更新成功后，对 active60 的 `actual_dominant + 1d + 60m` confirmed Canonical Bars 计算 EMA21 价格位置及 5/10 Bar EMA21 回归斜率，形成下一交易日固定观察池：

```text
active60
  ↓
D1 + 60m EMA21 趋势过滤
  ↓
多头观察 / 空头观察 / 趋势不明确 / 数据不可用
  ↓
扩展盘不可变历史 + current
  ↓
Market Web 首页“苏冰今日观察”
  ↓
候选点击后固定进入 actual_dominant + 15m + 苏冰
```

V1 的成功标准是：

- 每个交易日从 60 个品种中稳定筛出真正具有 D1/60m 同向趋势背景的品种；
- 震荡、方向冲突和数据不完整的品种不进入当天小周期观察对象；
- 首页直接展示完整候选规模和简化证据；
- 所有生成事实可按 target trading day 复盘；
- 不引入评分、排名、通用策略框架或新的运行组件。

## 3. 非目标

V1 明确不做：

- 不修改 `subing_entry_signal_v1` Formal Signal、Calibration、same-boundary resolver 或 Event identity；
- 不让观察池接管 production Alert Scope；
- 不新增 Alert Rule、通知、retry、replay、backfill、outbox、queue 或订单；
- 不加入 MACD、BOLL、成交量、持仓量、突破、N 字或日进斗金条件；
- 不生成综合分、趋势强度、Top N、胜率、PnL、推荐或“可交易”结论；
- 不提供历史浏览 API、历史日期选择器或跨日统计；
- 不删除 Trend Focus 后端代码；只从首页移除其产品入口；
- 不新增 PostgreSQL 表、Redis key、Canonical schema、worker、scheduler 或 launchd job；
- 不自动清理、压缩或归档历史；
- 不自动发布 main/tag，不自动切换 Runtime，不手工回填第一份真实观察池。

## 4. 产品工作流

### 4.1 盘后生成

```text
18:05 现有 after-market 自然运行
  ↓
RQData readiness
  ↓
HistoricalDataManager.update
  ↓
Canonical / Catalog / MainContractMap 更新
  ↓
正式 rank1 与 Live snapshot 核对
  ↓
Live 清理
  ↓
AfterMarketResult.status == passed
  ↓
SubingDailyWatchGenerator.run(source_trading_day)
```

触发依据只能是 `AfterMarketResult.status == passed`，不能由时间、进程已启动、部分文件存在或 `skipped` 推导。

### 4.2 下一交易日使用

```text
source_trading_day = 本次刚完成更新的交易日
target_trading_day = 所有 operational exchanges 的下一共同交易日
```

例如周五盘后：

```text
source_trading_day = 周五
target_trading_day = 下周一
```

生成后从目标交易日夜盘开始到目标交易日日盘结束，名单保持不变：

- 夜盘不重算；
- 日盘前不重算；
- 盘中新完成的 60m Bar 不改变名单；
- Web 刷新只读取已发布 current，不现场计算。

### 4.3 用户检查

候选卡点击后固定打开：

```text
series_kind = actual_dominant
frequency = 15m
overlay = subing
entry = subing-daily-watch
```

本次入口覆盖只作用于当前进入，不改写全局 `MainChartPreferences`。用户进入后可自行切换 5m 或其他 Overlay。

## 5. Universe 与产品元数据

### 5.1 唯一 Universe

观察池使用：

```text
data/universe/active_products.txt
```

输出顺序严格保持该文件顺序。不得按斜率、涨跌幅、成交量、名称或其他指标重新排序。

现有盘后 Runtime 使用 `operational_products.txt`。生成前必须验证：

```text
active_count == 60
set(active_products) == set(operational_products)
```

不相等时整次生成失败：

```text
ACTIVE_OPERATIONAL_SCOPE_MISMATCH
```

不能只生成 operational 子集后仍宣称覆盖 active60。

### 5.2 产品元数据

产品名称、板块、交易所、当前主力摘要继续来自现有 Catalog/`MarketDataService.list_latest_dominants()`。任一 active symbol 缺少唯一产品摘要时，该 symbol 记为：

```text
decision = unavailable
reason_code = PRODUCT_METADATA_UNAVAILABLE
```

但 Universe 配置本身无效或 active/operational 不一致是顶层失败，不生成部分账本。

## 6. 数据身份与因果边界

### 6.1 固定查询身份

每个品种固定读取：

```text
series_kind = actual_dominant
frequencies = 1d, 60m
since = source_trading_day   # probe 当前 rank1 segment
through = source_trading_day
confirmed Canonical only
```

所有 Historical 数据必须通过：

```text
MarketDataService
  → ActualDominantResearchSegmentLoader
```

消费者不得直接读 Parquet、glob、自判主力、跨频回退或重新聚合。

### 6.2 Rank1 segment

`ActualDominantResearchSegmentLoader` 先以 source day probe 当前 rank1 segment，再从真实 `segment.start_trading_day` 加载完整 D1/60m 上下文。

硬边界：

- D1 与 60m 必须恢复同一个 current rank1 physical contract segment；
- 不跨换月继承 EMA 或 slope memory；
- 不用 continuous 或前一物理合约补足 warm-up；
- probe/full segment identity 不一致时 fail-closed；
- 最新 D1 与 60m 事实的 `trading_day` 必须等于 `source_trading_day`；
- 最新事实的 physical contract 和 segment start 必须一致；
- source day 之后的 Bar 一律不可读。

主力切换初期历史不足是正常 typed unavailable，不得猜测。

## 7. EMA21 趋势事实

### 7.1 抽取独立 formula seam

现有 `subing_research.py` 的 Factor 同时计算 EMA、MACD 和量能。盘后准入只允许依赖 EMA21 趋势事实，因此新增独立纯函数模块：

```text
services/quant-api/app/market_data/subing_ema_trend.py
```

建议公开接口：

```python
class SubingEmaTrendStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"

@dataclass(frozen=True, slots=True)
class SubingEmaTrendSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal

@dataclass(frozen=True, slots=True)
class SubingEmaTrendResult:
    status: SubingEmaTrendStatus
    snapshot: SubingEmaTrendSnapshot | None

def calculate_subing_ema_trend_series(...) -> tuple[SubingEmaTrendResult, ...]: ...
def calculate_subing_ema_trend(...) -> SubingEmaTrendResult: ...
```

原有 SuBing Factor 改为复用该 seam，再附加 MACD、成交量和既有字段。必须通过 exact parity 测试，保证重构前后的以下字段完全一致：

```text
ema21
price_side
slope_5_raw
slope_10_raw
slope_5_bps_per_bar
slope_10_bps_per_bar
```

### 7.2 精确公式

```text
EMA period = 21
seed_policy = sma_window
```

对最后 5 个和 10 个 ready EMA21 值分别计算一元线性回归斜率：

```text
x = 0..n-1
slope = Σ((x - x̄)(y - ȳ)) / Σ((x - x̄)²)
```

标准化：

```text
slope_5_bps_per_bar = slope_5_raw / mean(last_5_ema21) × 10000
slope_10_bps_per_bar = slope_10_raw / mean(last_10_ema21) × 10000
```

所有计算使用 `Decimal`。V1 不设 `0.5bps`、`1bps` 等人工阈值；只判断正、负或零。

EMA21 或最近 10 个 EMA 值未 ready、均值为零、输入 identity 非法时返回 `insufficient_data` 或 typed identity error，不能回退到 SMA、前值或其他频率。

## 8. 准入分类

### 8.1 单周期方向

单周期 `long`：

```text
close > ema21
slope_5_bps_per_bar > 0
slope_10_bps_per_bar > 0
```

单周期 `short`：

```text
close < ema21
slope_5_bps_per_bar < 0
slope_10_bps_per_bar < 0
```

其余完整事实为 `neutral`，包括：

- `close == ema21`；
- 任一 slope 等于 0；
- 价格位置与 slope 方向冲突；
- 5 Bar 与 10 Bar slope 方向冲突。

### 8.2 双周期结果

| D1 | 60m | decision | reason code |
|---|---|---|---|
| long | long | `long_watch` | `D1_H1_LONG_ALIGNED` |
| short | short | `short_watch` | `D1_H1_SHORT_ALIGNED` |
| neutral | 任意 | `excluded` | `D1_TREND_NEUTRAL` |
| 任意非 neutral | neutral | `excluded` | `H1_TREND_NEUTRAL` |
| long | short | `excluded` | `D1_H1_DIRECTION_MISMATCH` |
| short | long | `excluded` | `D1_H1_DIRECTION_MISMATCH` |

### 8.3 Typed unavailable

品种级 reason code：

```text
D1_HISTORY_INSUFFICIENT
H1_HISTORY_INSUFFICIENT
SOURCE_TRADING_DAY_MISSING
DOMINANT_SEGMENT_UNAVAILABLE
DATA_IDENTITY_MISMATCH
PRODUCT_METADATA_UNAVAILABLE
```

顶层生成错误：

```text
ACTIVE_OPERATIONAL_SCOPE_MISMATCH
NEXT_TRADING_DAY_UNAVAILABLE
OBSERVATION_ROOT_UNCONFIGURED
OBSERVATION_ROOT_UNAVAILABLE
OBSERVATION_ROOT_NOT_WRITABLE
SNAPSHOT_INVALID
SNAPSHOT_IDENTITY_CONFLICT
CURRENT_TARGET_REGRESSION
OBSERVATION_ATOMIC_WRITE_FAILED
```

一个 symbol 在完整账本中只能有一个 decision；若有多个数据缺口，`unavailable_reasons` 可保留多个稳定 reason code。

## 9. 领域模型与完整账本

建议新增：

```text
services/quant-api/app/market_data/subing_daily_watch.py
```

核心类型：

```python
SubingDailyWatchDecision = Literal[
    "long_watch", "short_watch", "excluded", "unavailable"
]

@dataclass(frozen=True, slots=True)
class SubingDailyWatchItem:
    symbol: str
    product_name: str
    sector: str
    decision: SubingDailyWatchDecision
    reason_codes: tuple[str, ...]
    daily: SubingEmaTrendSnapshot | None
    hourly: SubingEmaTrendSnapshot | None
    unavailable_reasons: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SubingDailyWatchSnapshot:
    source_trading_day: date
    target_trading_day: date
    generated_at: datetime
    items: tuple[SubingDailyWatchItem, ...]
```

硬约束：

```text
items.length == 60
每个 active symbol 恰好出现一次
items 顺序等于 active_products.txt
long_watch + short_watch + excluded + unavailable == 60
四类 decision 互斥
long/short item 必须同时有 D1 与 60m facts
excluded item 必须有完整 D1 与 60m facts
unavailable item 不得伪造缺失 facts
```

## 10. 共同交易日解析

新增窄模块：

```text
services/quant-api/app/market_data/subing_daily_watch_calendar.py
```

提供两个职责明确的函数：

```python
def resolve_next_common_trading_day(
    session: Session,
    *,
    products: tuple[str, ...],
    source_trading_day: date,
) -> date: ...

def resolve_expected_daily_watch_day(
    session: Session,
    *,
    products: tuple[str, ...],
    now: datetime,
    cutover: time = time(18, 20),
) -> date: ...
```

解析规则：

1. 每个 product 必须有唯一 active `Instrument.exchange_code`；
2. 只使用现有 `TradingCalendar`；
3. 每个涉及 exchange 分别解析下一交易日；
4. 所有 exchange 必须得到同一个日期；
5. 缺行、不唯一或不同步时 fail-closed。

API 的 expected day 采用与盘后 health 一致的上海时间 18:20 cutover：

- 交易日 18:20 前，expected 为当前/最近共同交易日；
- 交易日 18:20 起，expected 为下一共同交易日；
- 周末和节假日，expected 为下一共同交易日；
- calendar 事实不完整时返回 typed unavailable。

这只用于判断 `current.json` 是否属于当前应显示的观察日，不触发生成。

## 11. 扩展盘持久化

### 11.1 唯一根目录

新增环境变量：

```text
GUIYI_SUBING_OBSERVATION_ROOT
```

正式本机示例：

```text
/Volumes/扩展盘/guiyi-quant-data/observations/subing-daily-v1
```

代码不得写死个人卷名，也不得提供仓库或系统盘 fallback。

### 11.2 Mount 安全

新增 store：

```text
services/quant-api/app/market_data/subing_daily_watch_store.py
```

生产 root resolver 必须验证：

1. 环境变量存在且非空；
2. 配置路径是绝对路径；
3. 路径结构为 `/Volumes/<volume>/...`；
4. `/Volumes/<volume>` 已存在且 `Path.is_mount()` 为真；
5. volume 和现存父目录不是 symlink；
6. 验证 mount 后才允许创建功能目录；
7. 根目录可写；
8. 临时文件和正式文件位于同一目录/同一文件系统。

测试通过注入 `MountInspector`/fake root 完成，不触碰真实 `/Volumes`。

扩展盘未挂载时禁止执行会在系统盘创建同名目录的 `mkdir('/Volumes/扩展盘/...')`。

### 11.3 目录结构

```text
$GUIYI_SUBING_OBSERVATION_ROOT/
├── history/
│   ├── 2026-08-25.json
│   ├── 2026-08-26.json
│   └── ...
├── current.json
└── generation-status.json
```

历史文件名使用 `target_trading_day`。

### 11.4 原子与不可变语义

```text
history/<target>.json 不存在
→ 写临时文件、fsync、os.replace

history/<target>.json 已存在且 canonical bytes 完全相同
→ idempotent success

history/<target>.json 已存在但内容不同
→ SNAPSHOT_IDENTITY_CONFLICT
→ 不覆盖历史、不更新 current
```

若现有 `current.target_trading_day` 晚于新 target：

```text
CURRENT_TARGET_REGRESSION
```

写入顺序：

```text
1. 构建并验证完整 snapshot
2. canonical JSON 序列化
3. 原子发布 history/<target>.json
4. 用同一 snapshot bytes 原子替换 current.json
5. 原子更新 generation-status.json
```

目录权限目标 `0700`，文件权限目标 `0600`。临时文件也在扩展盘目标目录。

### 11.5 保留周期

```text
永久保留
不自动删除
不压缩
不建立清理 job
```

公式变化必须使用新 projection version 和新根目录，不能改写 V1 历史。

## 12. JSON 合同

### 12.1 Snapshot 顶层

```json
{
  "schema_version": 1,
  "projection_version": "subing_daily_watch_v1",
  "formula_version": "subing_ema21_trend_v1",
  "source_trading_day": "2026-08-24",
  "target_trading_day": "2026-08-25",
  "generated_at": "2026-08-24T18:24:13+08:00",
  "series_kind": "actual_dominant",
  "frequencies": ["1d", "60m"],
  "ema_period": 21,
  "slope_windows": [5, 10],
  "counts": {
    "universe": 60,
    "long_watch": 12,
    "short_watch": 9,
    "excluded": 37,
    "unavailable": 2
  },
  "items": []
}
```

所有 `Decimal` 以十进制字符串写入 JSON，禁止 binary float。

### 12.2 Item

```json
{
  "symbol": "rb",
  "product_name": "螺纹钢",
  "sector": "黑色",
  "decision": "long_watch",
  "reason_codes": ["D1_H1_LONG_ALIGNED"],
  "daily": {
    "bar_end": "2026-08-24T15:00:00+08:00",
    "trading_day": "2026-08-24",
    "physical_contract": "RB2610",
    "segment_start_trading_day": "2026-07-20",
    "close": "3512",
    "ema21": "3478.2468",
    "price_side": "above",
    "slope_5_bps_per_bar": "8.6214",
    "slope_10_bps_per_bar": "5.9173"
  },
  "hourly": {
    "bar_end": "2026-08-24T15:00:00+08:00",
    "trading_day": "2026-08-24",
    "physical_contract": "RB2610",
    "segment_start_trading_day": "2026-07-20",
    "close": "3512",
    "ema21": "3498.1182",
    "price_side": "above",
    "slope_5_bps_per_bar": "3.1732",
    "slope_10_bps_per_bar": "2.1419"
  },
  "unavailable_reasons": []
}
```

### 12.3 Generation status

```json
{
  "schema_version": 1,
  "projection_version": "subing_daily_watch_v1",
  "last_run": {
    "source_trading_day": "2026-08-24",
    "target_trading_day": "2026-08-25",
    "started_at": "2026-08-24T18:24:00+08:00",
    "finished_at": "2026-08-24T18:24:13+08:00",
    "status": "passed",
    "error_code": null
  },
  "last_successful_target_trading_day": "2026-08-25"
}
```

若 root 本身不可用，无法写该状态文件；只记录固定 error code 的脱敏日志，API 通过实时 root 检查返回 unavailable。

## 13. 盘后 Runtime 集成

当前 `runtime_entry.run_after_market()` 负责现有盘后维护及独立的 Execution Review roll follow-up。V1 增加另一个隔离 follow-up：

```text
market_result = AfterMarketUpdater.run()

if market_result.status == passed:
    try:
        新 session → SubingDailyWatchGenerator.run(market_result.trading_day)
    except:
        固定 warning code；不改变 market_result

if market_result.status == passed and roll gate == enabled:
    独立 session → reconcile_open_episodes()
```

硬边界：

- 生成失败不回滚 Canonical；
- 不把 `AfterMarketResult.status` 从 passed 改为 failed；
- 不改变 `data.after-market` stdout payload 或进程成功码；
- 不阻断 Execution Review roll follow-up；
- 不发送 PushPlus；
- 不创建 AlertEvent；
- 不 retry、不 replay、不 backfill；
- `AfterMarketUpdater` 和 `HistoricalDataManager` 不依赖苏冰代码。

## 14. 只读 API

新增：

```text
GET /api/v1/market/research/subing-daily-watch/current
```

不增加历史 API。

### 14.1 Response

```python
class SubingDailyWatchCurrentResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    expected_target_trading_day: date | None
    latest_target_trading_day: date | None
    error_code: str | None
    snapshot: SubingDailyWatchWebSnapshotOut | None
```

正常不可用使用 HTTP 200 typed response，包括：

```text
SUBING_DAILY_WATCH_NOT_GENERATED
SUBING_DAILY_WATCH_STALE
SUBING_DAILY_WATCH_INVALID
SUBING_OBSERVATION_ROOT_UNAVAILABLE
SUBING_DAILY_WATCH_EXPECTED_DAY_UNAVAILABLE
```

Unexpected programming/infrastructure exceptions继续按现有 FastAPI 安全边界处理，不返回异常正文。

### 14.2 Web projection

API 不把完整 `excluded` 账本发送给浏览器，只投影：

```text
source_trading_day
target_trading_day
generated_at
counts
long_watch items
short_watch items
unavailable items
```

每个 long/short item 包含 D1/60m 简化方向事实和原始 Decimal 字段；V1 UI 只显示简化文字。完整 excluded facts 只保存在扩展盘历史/current 文件。

### 14.3 Current 校验

读取时必须：

1. 重新验证扩展盘 root；
2. 严格解析 `current.json` schema；
3. 重新校验 60-item ledger 和 counts；
4. 解析 `expected_target_trading_day`；
5. 要求 `current.target_trading_day == expected_target_trading_day`。

不一致时不返回旧候选列表。

## 15. Web 首页

### 15.1 页面结构

```text
期货市场发现

Runtime 状态
需要处理（Formal Signal / Execution Review）
苏冰今日观察
展开全市场研究（Radar）
```

V1 从首页移除：

```text
getMarketTrendFocus()
MarketFocusList
Trend Focus refresh/generation state
```

Trend Focus 后端、API 和测试暂不删除。

### 15.2 数据刷新

新增 `getSubingDailyWatchCurrent()`，使用现有 `useLatestResource` generation guard。

- mount/“全部刷新”：Formal + Runtime + Radar + Daily Watch；
- 页面重新 visible：Formal + Runtime + Daily Watch；
- Daily Watch 网络请求失败时不得展示 `useLatestResource` 保留的旧成功候选；显示 unavailable 卡片；
- typed unavailable 同样不回退 Trend Focus。

### 15.3 汇总与列表

顶部：

```text
目标交易日 2026-08-25 · 来源交易日 2026-08-24
多头观察 14｜空头观察 9｜趋势不明确 35｜数据不可用 2
```

多头、空头各默认展示 6 个，独立展开全部：

- 不分页；
- 展开状态只在当前组件内；
- 不写 localStorage；
- 按 active universe 固定顺序；
- “前 6 个”不表示优先级。

卡片：

```text
RB 螺纹钢                    多头观察
日线  价格在 EMA21 上方 · 5/10 斜率向上
60m   价格在 EMA21 上方 · 5/10 斜率向上
[检查 15m]
```

首页不直接展示 Close、EMA21 和 slope 数值。

### 15.4 Unavailable

默认收起，可展开全部：

```text
XX 品种
影响周期：60m
原因：60m 历史不足
```

规则：

- 显示 symbol、product name、影响周期和稳定中文原因；
- 不显示“检查”按钮；
- 不允许点击跳转；
- 不计入 excluded；
- 顶层 root/snapshot 错误显示整块 unavailable，不伪装成 60 个品种均不可用。

## 16. 图表一次性入口

新增纯函数工具：

```text
apps/quant-web/src/utils/marketChartEntry.ts
```

合法入口精确要求：

```text
entry=subing-daily-watch
overlay=subing
series_kind=actual_dominant
frequency=15m
symbol 为合法 product code
contract 为空
```

初始化：

```text
route entry override > local MainChartPreferences
```

但不调用 `saveMainChartPreferences()`。首次成功 canonical replace 后清理 `entry`/`overlay` 一次性 query，只保留标准 chart identity；用户之后手工切换 Overlay 或周期时按现有偏好逻辑处理。

非法或不完整入口忽略 override，继续使用普通 Market 初始化，不能部分强制 identity。

## 17. 错误与降级矩阵

| 场景 | 生成 | 历史/current | API | Web |
|---|---|---|---|---|
| after-market failed | 不运行 | 不变 | 旧 target 若已过期则 unavailable | unavailable |
| after-market skipped | 不运行 | 不变 | 按 expected day 校验 | 正常或 unavailable |
| active/operational 不一致 | 顶层失败 | 不更新 | unavailable | unavailable |
| 单品种 D1/60m 不足 | 继续 | item=unavailable | 返回该项 | 可展开，不可点击 |
| 扩展盘未挂载 | 失败 | 不写任何 fallback | root unavailable | 整块 unavailable |
| 同 target 重跑同内容 | 幂等成功 | 不改历史内容 | ready | 正常 |
| 同 target 内容冲突 | 失败 | 保留旧历史/current | invalid/unavailable | unavailable |
| current target 过期 | 不影响历史 | 保留供审计 | stale/unavailable，不返候选 | unavailable |
| Daily Watch follow-up 异常 | after-market 仍 passed | 尽可能写 failure status | unavailable | unavailable |
| Web 网络失败 | 无影响 | 无影响 | 无变化 | 隐藏旧候选，显示 unavailable |

## 18. 测试策略

### 18.1 公式

- EMA21 seed 与现有 Indicator Kernel 一致；
- 5/10 regression slope 确定性；
- positive/negative/zero 分类；
- insufficient warm-up；
- 原 SuBing Factor 六个 EMA/slope 字段 exact parity。

### 18.2 数据与因果

- source day probe → true segment start；
- D1/60m segment identity 一致；
- 主力切换不跨 segment；
- source day 之后 Bar 不可见；
- active60 全量、顺序和计数；
- typed unavailable 不静默丢弃。

### 18.3 Store

全部使用 temp root + fake `MountInspector`：

- 未配置、非绝对、非 `/Volumes`、未挂载、symlink、不可写；
- 原子 history/current/status；
- 同内容幂等；
- 不同内容冲突；
- current regression；
- 写入失败保留最后有效文件；
- 不触碰真实扩展盘。

### 18.4 Runtime

- after-market 非 passed 不调用；
- passed 精确调用一次；
- generator failure 不改变 public result；
- generator failure 不阻断 roll follow-up；
- runtime import 不加载 `app.research`；
- 不发送通知。

### 18.5 API/Web

- ready/current DTO；
- missing/stale/invalid/root unavailable typed response；
- excluded details 不进入 API；
- 首页替换 Trend Focus；
- 每侧默认 6 个与展开；
- unavailable 展开且不可点击；
- 网络失败不展示 stale candidates；
- chart route 强制 15m + subing 且不写全局 preference。

## 19. Canonical 与发布 Gate

实施顺序中的第一项必须关闭旧四体系 active 文档和 `STATUS.md` 冲突。代码完成后才能更新：

```text
PROJECT_SOURCE.md
DECISIONS.md
STATUS.md
.env.example
```

代码和测试完成只允许结论：

```text
允许集成 develop
```

不得据此宣称：

```text
已 release
Runtime Ready
扩展盘已配置
真实观察池已生成
Alert Scope 已切换
```

后续链路：

```text
develop
→ 独立 Review
→ release candidate
→ 用户批准 main/tag
→ 用户批准 Runtime promotion
→ 配置 GUIYI_SUBING_OBSERVATION_ROOT
→ 等待下一次自然 after-market
→ 验收 history/current/API/Web
```

release 批准和 Runtime promotion 是两个独立 Gate。首次真实观察池默认等待自然 after-market，不手工触发或回填。

## 20. 最终验收

V1 只有在下列事实全部成立时才可标记产品代码完成：

1. 旧四体系 active 方案已退出 canonical；
2. 原苏冰 5m/15m Factor exact parity；
3. active60 每个 symbol 在账本中恰好一次；
4. D1/60m 同向准入规则无额外阈值和条件；
5. rank1 segment-local、无 future Bar、无 cross-contract warm-up；
6. 全部 durable artifacts 只写受验证扩展盘 root；
7. 历史不可变，current 不回退；
8. API 不返回过期候选；
9. 首页不再展示 Trend Focus，两侧默认 6 个；
10. unavailable 可解释但不可进入图表；
11. 候选固定进入 actual_dominant + 15m + subing；
12. 本次入口不改写全局偏好；
13. after-market 成功语义不被下游失败污染；
14. Alert、DB、Redis、Canonical schema、订单边界均未变化；
15. 定向测试、完整受影响测试、Ruff、Mypy、Web test/build、Playwright、secret scan 全部通过。
