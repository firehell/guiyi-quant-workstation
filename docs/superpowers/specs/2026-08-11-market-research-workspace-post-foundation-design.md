# Market Research Workspace V2 — Post-Foundation Design

Final rebase：2026-08-12  
Review baseline：`develop@51e849888590872eab298a682a105ef904ca0426`（文档提交前代码头）

## 1. Purpose

本设计是归一量化在 Data Foundation 完整闭环后的 Market Research Workspace 最终 P0 设计基线。

当前目标不是继续建设数据底座，也不是把 RQData API 返回值搬到 Web，而是在已经可信的 60 品种历史行情、主力映射和 Runtime seam 之上，把 Market Web 收敛成两个高效研究入口：

```text
Market Radar
    -> 看全市场状态
    -> 找值得进一步研究的品种
    -> 点击品种
Product Workspace
    -> 第一屏完整看 K 线
    -> 再看趋势、量价、OI 和合约上下文
```

项目仍然是本地优先、单用户、个人开发维护的国内期货量化研究工作站。设计优先级固定为：

```text
研究效率
> 数据语义正确
> 响应速度
> 简单可维护
> 必要复用
> 商业终端式扩展能力
```

不复制 TradingView，不建设 SaaS、多用户平台，也不实现自动交易。

---

## 2. Final Rebase Baseline

### 2.1 Data Foundation 已满足

当前 `STATUS.md` 已确认：

```text
DFD-01 ～ DFD-07 全部完成并归档
active universe = 60
60/60 Canonical closure complete
fixed T0 = 2026-08-11
full audit = passed / 0 findings
```

因此旧文档中“等待 60/60 后再启用本设计”的前置条件已经满足。本文从现在起不再以 partial universe 为主要产品设计前提。

长期数据事实继续只认：

```text
RQData
-> temporary staging + six hard validations
-> Canonical Parquet
-> PostgreSQL eight-table Catalog/metadata
-> MarketDataService
-> consumers
```

### 2.2 active 与 operational 现在均为 60

当前：

```text
active_products.txt      = 60
operational_products.txt = same 60
```

这意味着：

- Historical Research Universe 为 60；
- Runtime Live/after-market 的**配置范围**也是这 60；
- 但 Live provider channels 仍必须按真实 MarketPhase 只订阅当前 `TRADING` 的品种，不能把“operational=60”误解为“任何时刻同时订阅 60 个 channel”。

60 品种的每日 17:00 + 最多一次 1h retry 历史更新已经属于现有 Market Runtime V1 的有界持续自动化能力，不再为 Market Radar 另建第二套 Daily Freshness scheduler。

### 2.3 当前仍有一个独立 Runtime 自然验收尾项

2026-08-12 的 60 品种 Runtime 已切换到 clean/detached `51e84988...`，并部署了下列根因修复：

```text
完整 operational-60 当日 rank1 snapshot
        !=
当前 TRADING provider channels
```

现场同时发现 56 个品种 `TradingSession.effective_to` 停在 2026-08-11。盘后 runner 已修复为先按
Calendar-only metadata day 判断交易日，再由 `HistoricalDataManager.update` 同步当天 Session，避免旧
Session 把真实交易日误判为 `NON_TRADING_DAY`。该修复只有部署到隔离 Runtime 后，才能形成 17:00
自然运行证据；部署和自然验收状态以 `STATUS.md` 为准。

这个尾项：

- **不否定 Data Foundation 60/60 完成事实；**
- **不阻塞 P0 纯代码开发；**
- 但在 P0 最终真实 Runtime 集成验收前必须读回 60 品种自然盘后状态与健康状态。

---

## 3. Frozen Boundaries

### 3.1 Historical Core

以下合同不在 P0 重构：

- Canonical Parquet 是唯一 active 历史 Bar 存储；
- PostgreSQL 不保存 K 线；
- `MarketDataService` 是历史 Bar 唯一正式读取入口；
- 物理 Dataset 只有 `continuous | contract`；
- `actual_dominant` 只在查询时按 `MainContractMap rank=1` 拼接；
- `continuous/MAIN` 保持当前未平滑连续语义；
- Consumer 不得 glob、自判主力、自选物理文件或跨频回退。

P0 Research Service 只能成为 `MarketDataService` 的只读消费者，不能绕过它。

### 3.2 Runtime / Live Core

继续冻结：

```text
Historical Canonical
    !=
Redis Live Observation
```

Product Workspace 必须复用当前已经存在并验收过的：

```text
MarketReadService
useMarketSeries
GET /api/v1/market/bars/page
GET /api/v1/market/state
WS  /api/v1/market/ws
Canonical/Live seam
after-market seam refresh
```

不新增第二套分页、WebSocket、reconnect、trading-day、phase 或 Historical/Live merge 逻辑。

### 3.3 Indicator Authority

唯一指标业务权威继续是：

```text
packages/quant-core/guiyi_quant/indicators/
```

当前 Registry 核心状态保持：

```text
EMA10 / EMA21 / EMA60 -> validated
MACD                  -> compatibility_validated
ATR                   -> compatibility_validated
HTDY original         -> observation_only
HTDY strict           -> strategy_candidate
```

Web `indicators.ts` / `mainIndicators.ts` 只用于浏览器观察镜像；发生口径冲突时必须以 Python Kernel + golden 为准。

### 3.4 Product taxonomy 已经存在

当前仓库已经有：

```text
data/universe/product_sectors.csv
services/quant-api/app/market_data/product_taxonomy.py
apps/quant-web/src/utils/productDirectory.ts
```

`product_sectors.csv` 精确覆盖 active 60，并提供展示名称和一级研究板块；后端 taxonomy 做严格一致性校验，`/market/dominants` 已返回 `product_name + sector`。

因此 P0 不再设计新的 sector 配置，不从 `Instrument.sector` 推断，也不让 Web 复制品种到板块映射。

---

## 4. Product Information Architecture

长期只保留两个核心页面：

```text
Market
├─ Market Radar
└─ Product Workspace
```

不新增：

```text
RQData API 中心
会员排名一级页
仓单一级页
展期收益一级页
交易参数一级页
```

以后 RQData Research Enrichment 仍然是 Product Workspace 的纵向研究模块，而不是 provider API 页面。

---

## 5. Market Research Read Model

### 5.1 Why

当前 Web 已经能正确读取 K 线和 Live seam，但 Radar、右侧研究摘要、下方量价/OI 如果各自在浏览器重复计算，会产生：

- 同一指标多个口径；
- 60 品种前端 N+1；
- 浏览器承担过多研究逻辑；
- 以后 P1 数据难以复用。

P0 新增一个**只读研究语义层**：

```text
MarketDataService
      ↓
research_metrics
      ↓
MarketResearchService / MarketRadarService
      ↓
ProductResearchSnapshot / RadarSnapshot
      ↓
Market Web
```

### 5.2 Responsibilities

Research 层只允许：

- 调用 `MarketDataService`；
- 读取 `MainContractMap`/dominants 已有摘要；
- 使用 `load_active_products()`；
- 使用 `load_product_taxonomy()`；
- 使用 `DatabaseCoverageSource.latest_complete_day()`；
- 调用 quant-core EMA/ATR 等权威函数；
- 计算研究统计并输出 DTO。

明确禁止：

- 调用 RQData provider；
- 写 PostgreSQL；
- 写 Canonical；
- 读写 Redis Live；
- 修改 `operational_products`；
- 承担 Runtime subscription 或 after-market 控制。

推荐只读 API：

```text
GET /api/v1/market/research/product
GET /api/v1/market/research/radar
```

---

## 6. Freshness Model

### 6.1 expected_as_of

Radar 的目标日期不能由浏览器自然日猜测。

固定使用现有交易日/session 事实：

```text
expected_as_of
= DatabaseCoverageSource.latest_complete_day(active 60)
```

这意味着：

- 交易日盘中：通常仍是上一完整交易日；
- 收盘并且 session 已完整结束：可以推进到当天；
- 周末/节假日：保持最近完整交易日；
- Calendar/Session 事实不足：fail-closed。

### 6.2 participant rule

Radar 每个 symbol 使用 `actual_dominant / 1d` 最新历史数据。

只有：

```text
latest trading_day == expected_as_of
```

才进入 participant 集合。

响应必须显式返回：

```text
status = ready | degraded
expected_as_of
active_count = 60
participant_count
stale[]
unavailable[]
```

正常状态：

```text
participant_count = 60
status = ready
```

任何品种没推进到 `expected_as_of`：

```text
status = degraded
```

Web 例如显示：

```text
数据日期 2026-08-20 · 参与 59/60 · 1 个品种待更新
```

禁止隐藏 stale 或继续写“全市场完整”。

### 6.3 Daily freshness 复用现有 Runtime

当前 `operational_products.txt` 已与 active 60 一致，现有 17:00 after-market updater 也读取同一份 60 品种配置并调用唯一正式 `HistoricalDataManager.update`。

因此 P0：

- **不新建 Daily Radar scheduler；**
- **不新增数据库任务表；**
- **不新增第二个历史写入口。**

如果盘后更新失败，Radar 只通过 freshness 诚实降级，不主动修复或触发写入。

---

## 7. Market Radar

### 7.1 First-screen questions

第一屏只回答：

1. 最近完整交易日整个市场有多活跃？
2. 价格与持仓变化集中在哪里？
3. 哪些品种值得打开 Product Workspace 继续看？
4. 哪些板块整体更强或更弱？

### 7.2 Layout

从上到下：

```text
Market Summary
Price Change × OI Change Scatter
值得关注 Attention
Sector Summary
Full Market Detail
```

页面允许纵向滚动，但前三块应在常见桌面第一屏/第一屏附近完成发现任务。

### 7.3 Summary Strip

最多 6 项：

```text
上涨品种
下跌品种
放量品种
明显增仓品种
高波动品种
expected_as_of / freshness
```

不增加“平均收益、总OI、综合分数”等仅因为能计算但不能明显降低研究成本的指标。

### 7.4 Price × OI Scatter

固定：

```text
X = price_change_1d
Y = oi_change_1d
bubble size = turnover/liquidity proxy
```

四象限只使用事实措辞：

```text
上涨 + 增仓
上涨 + 减仓
下跌 + 增仓
下跌 + 减仓
```

禁止使用“多头资金流入/空头资金流出”等由这些字段无法单独证明的因果描述。

Hover 只显示：

```text
品种/名称
1D涨跌
OI变化
量比
ATR分位
```

点击直接进入 Product Workspace，不增加中间详情弹窗。

### 7.5 Attention

统一命名：

```text
attention = 系统透明规则筛出的“值得关注”
watchlist = 用户本地手工自选
```

两者不共用字段名。

P0 固定规则：

```text
abs(price_change_1d) >= 2%
volume_ratio20        >= 1.50
oi_change_1d          >= 5%   -> oi_increase
oi_change_1d          <= -5%  -> oi_decrease
atr14_percentile252   >= 80%
position20            >= 90%  -> near_20d_high
position20            <= 10%  -> near_20d_low
EMA21 direction aligned with close
```

候选至少满足 2 个原因，不为了凑满 10 条降低阈值。

排序固定：

```text
reason_count DESC
abs(price_change_1d) DESC
turnover DESC (None last)
symbol ASC
```

Web 只翻译后端 reason code，不重新评分。

### 7.6 Sector Summary

直接使用现有 60 品种 taxonomy。

每个 sector 返回：

```text
sector
total_count
participant_count
up_count
down_count
median_price_change_1d
attention_count
```

使用**中位数**而不是成交额加权收益，避免不同品种合约规模直接参与跨品种收益权重。

Web 使用现有 `PRODUCT_SECTORS` 负责 sector label，不复制 symbol->sector 映射。

### 7.7 Full Market Detail

页面下方紧凑表：

```text
品种 | 板块 | 1D | 5D | 量比 | OI变化 | ATR分位 | 20日位置 | 状态
```

支持按板块和本地自选过滤；它是核对/排序工具，不是首页主视觉。

---

## 8. Shared Research Metrics

后端共享指标定义一次，供 Product Snapshot 与 Radar 共用。

固定 P0 语义：

```text
price_change_1d = close_T / close_T-1 - 1
price_change_5d = close_T / close_T-5 - 1

position20 =
(close_T - min(low,last20)) /
(max(high,last20) - min(low,last20))

volume_ratio20 =
volume_T / mean(previous 20 volume)
# current excluded

oi_change_1d =
OI_T / OI_T-1 - 1
# both finite and previous > 0

turnover_change_5d =
turnover_T / mean(previous 5 turnover) - 1
# all required values present
```

Trend：

```text
up      = close > EMA21 AND EMA21[T] > EMA21[T-1]
down    = close < EMA21 AND EMA21[T] < EMA21[T-1]
neutral = otherwise
unavailable = EMA not ready
```

EMA 必须调用 quant-core：

```text
ema_series(period=21, seed_policy=sma_window)
```

ATR 必须调用 quant-core：

```text
atr_series(period=14, smoothing_policy=wilder_sma_seed)
```

ATR percentile：latest ready ATR 相对其前最多 252 个 ready ATR 的经验分位；基准 ready 值少于 20 个返回 unavailable。

后端研究比例/价格衍生值继续使用 `Decimal`；仅在 Web HTTP 边界转成显示数值。

---

## 9. ProductResearchSnapshot

一个聚合响应同时服务右栏和 K 线下面的 P0 研究区，避免多个前端请求。

至少返回：

```text
symbol
product_name
sector
exchange
series_kind
contract
as_of
current_dominant
dominant_mapping_date

daily_trend
weekly_trend
position20
distance_to_20d_high
distance_to_20d_low
volume_ratio20
oi_change_1d
turnover_change_5d
atr14_percentile252

recent_daily[]
```

后端可以读取最多 300 根日线计算 ATR/历史分位，但 HTTP `recent_daily` 只返回最近 80 个点，足够下方 Price/Volume/OI 观察，减少无意义 payload。

Product Research 必须跟随当前图表 identity：

```text
actual_dominant
continuous
contract + exact contract
```

不在右栏偷偷切换另一种 series 口径。

---

## 10. Product Workspace

### 10.1 Core Principle

> **进入品种页后，K 线永远是第一视觉中心。**

辅助研究不能默认把主图挤成小窗。

### 10.2 Responsive Layout

```text
>= 1600px
Kline Workspace + 296px lightweight research sidebar

< 1600px
Kline full width + “研究” drawer
```

所有桌面尺寸支持 K 线全屏。

### 10.3 Toolbar

高频控件固定：

```text
品种
Series: 真实主力 | 主连
Period: 1m 5m 15m 30m 60m D W
主图指标
全屏
```

`contract` 保留为低频高级入口。

切换 Series/Period 立即沿用现有 `replaceSeries()`，不再保留“选择后点击读取最新页”的管理后台式主流程。

### 10.4 Kline Panels

固定三层：

```text
Pane 0: Candlestick + selected main overlays
Pane 1: Volume
Pane 2: MACD
```

默认比例约 6/2/2。

必须继续复用当前 Kline 已有能力：

```text
normalizeBarSeries
Shanghai time formatting
replaceBars
prependBars
updateBar
followLatest
left-edge pagination
viewport preservation
```

不因增加 pane/indicator 回退成全量重绘 + 无条件 `fitContent()`。

### 10.5 Main indicators

主图只展示当前 Registry/Web definition 已登记能力：

```text
EMA10
EMA21
EMA60
HTDY original observation
```

不新增 BOLL/RSI/KDJ/CCI。

### 10.6 Crosshair

优先实现跨 pane 十字线联动，而不是画线工具。

同一时刻显示：

```text
O H L C
Volume
OI
enabled EMA
MACD DIF / DEA / HIST
```

缺失字段显示 unavailable，不补 0。

### 10.7 HTDY original

HTDY 继续单独作为风险任务：

- 默认关闭；
- 开启时始终显示“未来引用 / 重绘风险 / 仅供人工观察”；
- 不改变 Registry capability；
- 不进入 Radar attention；
- observation marker 使用“买观察/卖观察/XG观察”，不称为正式买卖信号。

---

## 11. Lightweight Research Sidebar

只保留三块。

### Trend / Position

```text
日线方向
周线方向
20日位置
距20日高/低
ATR分位
```

### Volume / OI

```text
量比20
OI 1D
成交额相对5日
```

### Contract / Runtime Context

```text
当前 rank1 主力
映射交易日
当前 Live/Historical 状态
Market phase
```

Runtime state 仍来自现有 `MarketReadService/useMarketSeries`，不是 Research API 自行推断。

右栏不放大表、provider raw fields 或 P1 占位卡片。

---

## 12. Vertical Research Area

P0 只实现：

```text
Price / Volume / OI
```

使用 `ProductResearchSnapshot.recent_daily` 显示：

- normalized price trend；
- normalized OI trend；
- volume bars；
- 简短事实摘要。

P0 不提前实现：

```text
Term Structure
Dominant Migration
Roll Yield
Warehouse State
Member Position Structure
Trading Economics
```

这些属于 P1，必须在 P0 实际使用后重新排序优先级。

---

## 13. Local Interaction State

单用户本地 Web 直接使用 localStorage：

```text
last symbol
last series
last period
main indicators
research sidebar open/closed
watchlist
```

不建用户表、Preference API、账户体系或云同步。

损坏/版本不匹配时回退默认值，不能阻塞 Market 页面。

---

## 14. Error / Degradation Policy

### Kline Core

Canonical、Map、coverage、物理一致性问题继续显式失败；不得用 Research 数据掩盖。

### Product Research

Research API 失败时：

```text
Kline 仍可读 -> Kline 正常
Sidebar / lower research -> unavailable
```

不得用 Research 错误覆盖整个图表页。

### Radar

Radar 必须保留：

```text
ready/degraded
expected_as_of
participant_count/60
stale
unavailable
```

不能静默排除坏品种再显示 60 品种结论。

### Runtime

Live/Redis/phase 异常继续按当前 Runtime 合同降级；Research Service 不接管 Runtime 修复。

---

## 15. Performance

只做明显有效的控制：

- Kline 继续最新 1200 bars + cursor 左拖；
- Live append 保持增量 update；
- Radar 后端一次批量生成 snapshot，避免前端 60 × N；
- Product Research 一个响应满足 sidebar + lower panel；
- Radar/Research 可以使用简单进程内短缓存，但缓存 key 必须包含 identity / expected_as_of；
- P1 以后再按 viewport lazy load；
- 不建分布式缓存、任务平台或复杂 invalidation 系统。

---

## 16. Testing Strategy

### Backend

至少覆盖：

- shared research metric exact semantics；
- Decimal/null behavior；
- ProductResearchSnapshot identity 一致；
- `expected_as_of` 使用现有 complete-day 语义；
- 60/60 ready；
- 59/60 stale degraded；
- known `MarketDataError` 单品种隔离；
- unexpected exception 继续 fail-closed；
- attention reason / deterministic sort；
- sector summary 使用现有 taxonomy；
- Research 路径零 provider / 零 mutation。

### Frontend

至少覆盖：

- Radar summary/scatter/attention/sector/detail；
- attention 与 watchlist 区分；
- Product Workspace responsive；
- period/series switch；
- three-pane Kline；
- EMA + fixed Volume/MACD；
- crosshair；
- HTDY risk notice；
- left pagination / Shanghai time / viewport；
- current after-market seam 和 WebSocket regression；
- localStorage fallback；
- Research failure 不影响 Kline。

### Repository verification

实现期的真实命令始终以当时 `TESTING.md` 为准。当前基线使用：

```text
pytest / Ruff / Mypy
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
secret_scan.py
git diff --check
openspec validate --specs --strict --no-interactive
```

---

## 17. Delivery Order

最终 P0 顺序：

```text
P0-1 Shared Research Metrics + Product Research Service
P0-2 Product Workspace shell / local state
P0-3 Three-pane Kline Core
P0-4 Product Research Sidebar + Price/Volume/OI
P0-5 Full-universe Radar backend
P0-6 Market Radar Web
P0-7 HTDY original observation overlay
P0-8 Final integration review + real-use gate
```

这套顺序不再被 60/60 Data Foundation 阻塞。

若 `STATUS.md` 所列当前封板 commit（包含 Calendar-first 盘后修复）在 P0 开发开始时仍未部署：

- P0-1～P0-7 可以正常开发；
- P0-8 的真实 Runtime-integrated acceptance 前必须先完成独立 Runtime switch/readback；不得只因
  `51e84988...` 已部署就跳过本轮封板 commit。

---

## 18. P1 Direction

P0 真实使用一段时间后，再决定以下模块优先级：

```text
Term Structure
Dominant Migration
Roll Yield
Warehouse State
Member Position Structure
Trading Economics
```

P1 原则保持：

```text
RQData Research Adapter
       ↓
FuturesResearchService
       ↓
semantic DTO
       ↓
Product Workspace
```

不得把 provider API 塞进 `MarketDataService`，也不得建立 `/api/rqdata/*` passthrough。

---

## 19. Non-goals

P0 明确不做：

- 新的历史数据架构；
- 新 Daily scheduler；
- 扩大 operational universe（当前已经是 60）；
- Tick / 五档盘口；
- 自动交易、下单或交易建议；
- Backtest/Signal/Review/Strategy 应用面；
- RQData raw API browser；
- 商业 TradingView clone；
- 画线、斐波那契、自定义公式；
- 多用户/SaaS；
- Dashboard builder；
- Research Catalog/lineage 平台；
- P1 enrichment 提前实现。

---

## 20. Success Criteria

P0 成功标准：

1. Radar 正常日能显示 60/60 current，异常日能明确显示 degraded；
2. 打开 Radar 后约 10 秒内能知道数据日期、市场活跃度、主要板块和优先研究品种；
3. 点击品种后第一视觉中心始终是完整 Kline；
4. 真实主力/主连和七周期一键切换；
5. Volume + MACD 固定可见；
6. 十字线能读取同一时刻 OHLCV/OI/EMA/MACD；
7. 向左加载继续保持已经验收的历史分页体验；
8. Sidebar/Price-OI 区减少人工找数据的时间；
9. 60 品种 Runtime 状态和 Research 状态职责清晰，不互相冒充；
10. 新增复杂度都能直接换来个人研究效率。
