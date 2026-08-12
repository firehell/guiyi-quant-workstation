# Market Research Workspace V2 — Post-Foundation Design

## 1. Purpose

本设计是归一量化 Market Research Workspace 的新开发基线，供 **Market Runtime MR-08 已完成验收、active universe 60/60 历史 Canonical 已全部闭环** 后启动开发使用。

目标不是把 RQData API 或大量原始字段搬到 Web，而是把可信市场数据压缩成两级个人研究工作流：

```text
Market Radar
    -> 快速理解全市场状态
    -> 找到值得进一步研究的品种
    -> 点击品种
Product Workspace
    -> 第一屏完整看 K 线
    -> 再向下看趋势、量价、OI 与后续期货研究增强
```

项目仍然是本地优先、单用户、个人开发维护的国内期货研究工作站。设计优先级固定为：

```text
研究效率
> 数据语义正确
> 响应速度
> 简单可维护
> 可复用
> 商业终端式扩展能力
```

本设计不复制 TradingView，不建设 SaaS、多用户平台或自动交易系统。

---

## 2. Activation Gate

### 2.1 本文是未来基线文档

本文生成时仓库仍处于 60 品种逐步闭环过程中；**不得因为本文存在就把 60/60 写成当前已完成事实**。

真正开始执行本文前，只认 `STATUS.md` 的最新事实。至少必须满足：

```text
A. Market Runtime MR-08 最终验收已完成
B. active universe = 60
C. 60/60 品种历史 Canonical 全部完成闭环
D. 60/60 audit passed
E. 60/60 fixed-through/fixed-T0 口径达到仓库当时规定的 NOOP 验收
F. MarketDataService 对当前要求的查询模式/周期完成全域只读验收
```

若未来 Data Foundation 的任务编号发生变化，以 `STATUS.md`、`docs/DATA_CENTER.md` 和 active task contract 的事实为准，不依赖本文中的旧阶段编号。

### 2.2 Runtime 与 60/60 Data Foundation 是两个不同维度

即使 60/60 历史数据全部闭环，也不能自动推出：

```text
60 品种全部启用 Live
60 品种全部进入 operational_products
60 品种全部自动盘后更新已获授权
```

当前 Runtime 的有界持续自动化只由 `operational_products.txt` 控制。若届时仍为 `j/jm/ap/ag`，则保持：

```text
Historical Research Universe = active 60
Live Observation Universe     = operational subset
```

任何扩大 Live 或自动真实写入范围的动作都属于独立 Runtime/Data Gate。

---

## 3. Frozen Project Boundaries

### 3.1 Historical Core

继续冻结：

```text
RQData
-> temporary staging
-> six hard validations
-> Canonical Parquet
-> PostgreSQL eight-table metadata/catalog
-> MarketDataService
-> consumers
```

- Canonical Parquet 是唯一 active 历史 Bar 存储。
- PostgreSQL 不保存 K 线。
- `MarketDataService` 是正式历史 Bar 唯一读取入口。
- Web、Research Service、Indicator consumer 均不得 glob Parquet、自选文件、自判主力或跨频回退。
- 物理 Dataset 只有 `continuous | contract`。
- `actual_dominant` 继续由 `MainContractMap rank=1` 查询时拼接。
- `continuous/MAIN` 继续保持当前未平滑连续语义，不引入 `get_dominant_price` 或复权连续序列替代。

### 3.2 Live Core

继续冻结 historical / live 分层：

```text
Historical Canonical
    !=
Redis Live Observation
```

P0 Market Research Workspace 必须复用已经验收的：

```text
MarketReadService
useMarketSeries
/bars/page
/market/state
/market/ws
Canonical/Live seam
```

不重建第二套分页、WebSocket、Live merge 或 trading-day 逻辑。

### 3.3 Indicator Authority

指标权威继续是：

```text
packages/quant-core/guiyi_quant/indicators/
```

Web TypeScript 只允许作为已登记指标的观察镜像。

当前主图可用集合按仓库实际 Registry/`MAIN_INDICATOR_DEFINITIONS` 读取；设计基线按目前事实为：

```text
EMA10
EMA21
EMA60
HTDY original observation（默认关闭，明确重绘/未来引用风险）
```

Volume 与 MACD 固定为副图观察面，不因此修改 MACD formal capability。

---

## 4. Product Information Architecture

长期只保留两个核心页面：

```text
Market
├─ Market Radar
└─ Product Workspace
```

不创建：

```text
RQData API 中心
会员排名一级页
仓单一级页
展期收益一级页
交易参数一级页
```

未来 RQData Research Enrichment 全部是 Product Workspace 的研究模块，不是 provider API 页面。

---

## 5. Data Freshness Model

这是 V2 相对旧设计新增的核心约束。

### 5.1 60/60 闭环只证明历史资产完整，不证明每天都已更新

Market Radar 每次响应必须显式返回：

```text
expected_as_of
participant_count
active_count
stale/unavailable products
```

`expected_as_of` 由可信 TradingCalendar/完整交易日语义确定，不由浏览器自然日猜测。

一个品种只有在：

```text
latest actual_dominant/1d trading_day == expected_as_of
```

时才进入该次 Radar 统计。

因此正常全域状态是：

```text
participant_count = 60
active_count      = 60
```

若某品种日线没有推进到 expected_as_of，则 Radar 返回 `partial/degraded`，Web 显示例如：

```text
数据日期 2026-08-20 · 参与 59/60 · 1 个品种待更新
```

禁止继续显示“全市场完整”。

### 5.2 Daily Ready Gate

为了让 Market Radar 成为每天可用的研究入口，最终还需要一个独立 Daily Freshness Gate：

```text
60/60 latest complete trading day current
```

最简单的长期方案是复用现有 `HistoricalDataManager.update` / `guiyi data update --universe active`，实现一个**仅历史日终更新 active 60** 的轻量自动化，同时保持 Live universe 不变。

推荐长期关系：

```text
active_products.txt       = 60 historical research universe
operational_products.txt  = Live observation subset
```

不要为了更新 60 品种历史数据而把 Live subscription 扩成 60。

真正启用 60 品种自动日终写入属于独立 Lane 3 / Runtime + formal data write Gate；P0 Web 代码可以先完成，但在该 Gate 通过前只能诚实显示 `as_of` 与 freshness 状态。

---

## 6. Market Radar

### 6.1 Research Questions

Market Radar 第一屏只回答：

1. 最近完整交易日的市场整体活跃度如何？
2. 价格与持仓结构在哪些品种上出现明显变化？
3. 哪些品种值得打开 Product Workspace 继续研究？

### 6.2 First-screen Layout

从上到下：

```text
Market Summary
Price Change × OI Change Scatter
值得关注
板块表现（有可信分类时）
```

页面可继续向下滚动查看全市场明细。

### 6.3 Summary Strip

最多 6 项：

```text
上涨品种
下跌品种
放量品种
明显增仓品种
高波动品种
数据日期 / freshness
```

不增加只是“能算”但不明显改善研究效率的卡片。

### 6.4 Price × OI Scatter

固定定义：

```text
X = 1D price change
Y = 1D open-interest change
Bubble size = turnover/liquidity proxy
```

四象限只表达事实结构：

```text
上涨 + 增仓
上涨 + 减仓
下跌 + 增仓
下跌 + 减仓
```

禁止把 OI 变化直接解释成“多头资金流入”“空头资金流出”。

Hover 只显示 4～5 个核心值；点击直接进入 Product Workspace，不增加中间详情弹窗。

### 6.5 Attention Candidates

统一名称使用：

```text
attention = 系统规则筛出的“值得关注”
watchlist = 用户本地自选
```

二者不得混用。

P0 使用透明规则标签而不是综合黑盒分数。基线规则可冻结为：

```text
abs(1D price change) >= 2%
volume ratio 20      >= 1.50
OI 1D increase       >= 5%
OI 1D decrease       <= -5%
ATR14 percentile     >= 80%
position20           >= 90%  -> near 20d high
position20           <= 10%  -> near 20d low
EMA21 direction aligned with close
```

候选至少满足 2 个原因；不足 10 个就少显示，不降低标准凑数量。

排序：

```text
reason_count DESC
abs(price_change_1d) DESC
turnover DESC
symbol ASC
```

Web 只翻译后端 reason code，不重新评分。

### 6.6 Sector Summary

旧设计因为数据库 `Instrument.sector` 未必完整而选择隐藏板块；V2 在 60/60 基线后建议使用一个非常轻量、版本化的仓库配置：

```text
data/universe/product_sectors.csv
```

要求：

- 恰好覆盖 active 60；
- 每个品种只属于一个一级研究板块；
- 与 `active_products.txt` 一致性测试；
- 不进 PostgreSQL，不做 taxonomy 平台。

建议一级板块保持少量稳定分类，例如黑色、有色、贵金属、能源、化工、农产品等；具体 60 品种映射在该任务设计/Review 时一次性冻结。

如果用户不希望维护这份静态映射，则 sector 模块整体隐藏，不能从 symbol 名称猜测。

### 6.7 Full Market Detail

Radar 下半部分保留紧凑表：

```text
品种 | 1D | 5D | 量比 | OI变化 | ATR分位 | 20日位置 | 状态
```

表格用于核对和快速排序，不是第一视觉中心。

---

## 7. Market Research Service

V2 不再让前端为 Product Sidebar 和 Radar 各自重复计算研究指标。

新增只读研究语义层：

```text
MarketDataService
      ↓
MarketResearchService
      ↓
RadarSnapshot / ProductResearchSnapshot
      ↓
Market Web
```

职责：

- 读取 Canonical / MainContractMap / Instrument metadata；
- 调用 quant-core EMA/ATR 等权威函数；
- 计算 Radar 和 Product Research 的二次统计；
- 输出研究 DTO；
- 不写 DB/Parquet；
- 不调用 RQData provider；
- 不负责 Live subscription。

推荐只读 API：

```text
GET /api/v1/market/research/radar
GET /api/v1/market/research/product?symbol=...&series_kind=...
```

API 是研究语义，不是 `/api/rqdata/*` provider passthrough。

### 7.1 ProductResearchSnapshot

至少返回：

```text
symbol / name / exchange
current dominant / mapping date
daily trend
weekly trend
20d position
20d high/low distance
volume ratio20
OI change1d
turnover change5d
ATR percentile
recent daily price/OI/volume series
```

一个响应满足轻量右栏和 K 线以下 P0 Price/Volume/OI 区，避免 Web N+1 请求。

---

## 8. Product Workspace

### 8.1 Core Principle

进入品种页以后：

> **K 线永远是第一视觉中心。**

辅助研究不能默认把 K 线压成小窗。

### 8.2 Responsive Layout

```text
>= 1600px
Kline Workspace + 296px lightweight research sidebar

< 1600px
Kline full width + “研究” drawer entry
```

所有桌面尺寸支持 K 线全屏。

不专门建设移动端交易终端布局。

### 8.3 Toolbar

高频控件固定为：

```text
品种
Series: 真实主力 | 主连
Period: 1m 5m 15m 30m 60m D W
主图指标
全屏
```

`contract` 指定真实合约保留为低频高级入口。

切换 Series/Period 直接加载，不保留“选择参数 -> 点击读取”的管理后台式流程。

### 8.4 Kline Panels

固定三层：

```text
Pane 0: Candlestick + selected main overlays
Pane 1: Volume
Pane 2: MACD
```

主图 overlay 只允许当前 Registry 已登记、Web 允许显示的项目。

明确不做：

- 画线；
- 斐波那契；
- 文本标注；
- 自定义公式；
- 任意 pane 管理；
- RSI/KDJ/CCI 等指标市场；
- 多图分屏；
- Dashboard builder。

### 8.5 Historical Pagination / Live Seam

完全复用当前验收通过的行为：

```text
initial latest page
left drag -> load earlier
prepend keeps viewport
followLatest only when user is at right edge
Canonical always wins
Live only after canonical_end
```

P0 不改这一业务语义，只允许为了三 pane/overlay 做最小图表组件扩展。

### 8.6 Crosshair

优先实现跨 pane 十字线联动，而不是画线工具。

同一时刻显示：

```text
O H L C
Volume
OI
visible EMA
MACD DIF / DEA / HIST
```

不存在的字段显示 unavailable，不补 0。

### 8.7 HTDY Original

HTDY original 继续独立于核心 EMA/MACD Kline 任务：

- 默认关闭；
- 开启时持续显示“未来引用/重绘风险/仅供人工观察”；
- 不改变 Indicator Registry capability；
- 不进入 Radar attention 规则；
- 不把 observation 标记命名为正式“买入/卖出信号”。

---

## 9. Lightweight Research Sidebar

大屏常驻右栏只保留三个块：

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

### Contract Context

P0：

```text
当前 rank1 主力
MainContractMap 映射日
Live 状态（仅 operational 品种适用）
```

右栏不放大表和 provider raw fields。

---

## 10. Vertical Research Area

第一屏下面只先实现 P0：

```text
Price / Volume / OI
```

使用 `ProductResearchSnapshot.recent_daily_series` 显示：

- price trend；
- OI trend；
- volume/turnover；
- 简短事实摘要。

P0 完成后先真实使用，再决定 P1。

P1 候选保持：

```text
Term Structure
Dominant Migration
Roll Yield
Warehouse State
Member Position Structure
Trading Economics
```

这些模块后续通过 `FuturesResearchService + RQData Research Adapter` 单独设计，不能塞进 `MarketDataService`。

---

## 11. Local Interaction State

单用户本地应用直接使用 localStorage 保存 UI 偏好：

```text
last symbol
last series
last period
main indicators
research sidebar open/closed
watchlist
```

不建用户表、Preference API、账户系统或云同步。

损坏时回退默认值即可。

---

## 12. Error / Degradation Policy

### 12.1 Core Kline

Canonical/Map/coverage/physical integrity 错误继续 fail-closed。

### 12.2 Research Snapshot

单品种 Research 计算失败只让右栏/下方研究区显示 unavailable；如果 Kline 本身仍可读，不允许研究摘要错误覆盖整个 Kline 页面。

### 12.3 Radar

Radar 返回完整 freshness metadata：

```text
expected_as_of
participant_count
active_count
unavailable/stale
```

只要不是 60/60 current，就显式 degraded。

### 12.4 P1 Enrichment

以后 warehouse/member/roll provider 失败只影响对应模块，绝不能破坏 Historical Core。

---

## 13. Performance

只做明显有效的优化：

- Kline 默认最近 1200 bars，继续 cursor 左拖；
- Kline Live append 使用现有增量 update；
- Radar 后端批量生成一次 snapshot，避免前端 60 × N 请求；
- Product Research 一个聚合响应满足 sidebar + 下方 P0；
- P1 后续 IntersectionObserver lazy load；
- localStorage / 简单进程内短缓存可用；
- 不建分布式缓存、任务平台、通用 invalidation 系统。

---

## 14. Testing Strategy

### Backend

重点验证：

- expected_as_of；
- 60/60 current 与 degraded freshness；
- price/OI/volume/ATR/EMA 公式；
- transparent reason codes；
- deterministic attention sorting；
- ProductResearchSnapshot；
- sector config 与 active 60 精确一致；
- `MarketDataService` 仍是唯一 historical reader。

### Frontend

重点验证：

- Market Radar 第一屏信息层级；
- scatter hover/click；
- attention 与 watchlist 区分；
- Product Workspace responsive layout；
- period/series switch；
- three-pane Kline；
- EMA + Volume + MACD；
- crosshair；
- HTDY risk notice；
- left pagination / viewport / Runtime seam 回归；
- localStorage fallback。

### Runtime/Data Regression

P0 Web/Research Service 不能让已经通过 MR-08 的：

```text
BREAK/CLOSED
night trading_day
Historical-only continuous
actual_dominant Live
Canonical/Live seam
after-market canonical advance
```

发生回归。

---

## 15. Non-goals

本阶段明确不做：

- 自动交易或下单；
- 交易建议；
- 扩大 Live universe；
- Tick/五档盘口；
- 新 Backtest/Signal/Review/Strategy 应用面；
- RQData raw API browser；
- 商业 TradingView clone；
- 绘图工具；
- 多用户/SaaS；
- Research Catalog/lineage 平台；
- P1 provider research modules 的提前实现。

---

## 16. Success Criteria

只有同时满足以下体验目标，P0 才算成功：

1. 打开 Market Radar 后约 10 秒内能知道数据日期、市场活跃度和优先研究品种；
2. 正常 Daily Ready 状态为 60/60 current，任何 stale product 都明确暴露；
3. 点击品种进入 Product Workspace 后，第一视觉中心始终是完整 Kline；
4. 周期、真实主力/主连、少量主图指标可以一键切换；
5. Volume 与 MACD 始终固定可见；
6. 十字线能同步查看同一时刻 OHLCV/OI/EMA/MACD；
7. 向左可以持续浏览更早历史且视口不跳回；
8. 研究摘要减少人工找数据时间，而不是增加卡片数量；
9. Live 仅影响 operational subset，60 品种历史 Radar 不依赖 60 路 Live；
10. 所有复杂度都能直接换来个人研究效率。

---

## 17. Supersession

当 Activation Gate 满足并正式开始 Market Research Workspace 开发后，本文件替代以下旧开发基线：

```text
docs/superpowers/specs/2026-08-10-market-research-workspace-design.md
```

旧文档保留为设计演进历史，不再作为 Codex 实施入口。
