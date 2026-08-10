# Market Research Workspace Design

## 1. Purpose

将当前 Market-only Web 从“主力映射表 + K 线查询页”收敛为适合个人研究的两级工作流：

```text
Market Radar
    -> 发现今天值得看的市场与品种
    -> 点击品种
Product Workspace
    -> 以完整 K 线为第一视觉中心
    -> 再向下查看量价/OI、期限结构、会员、仓单等研究解释
```

设计目标不是复制 TradingView 或商业期货终端，而是利用当前可信 Canonical、MainContractMap 与后续精选 RQData 研究数据，减少“自己找数据、自己拼接口结果、自己判断先看什么”的时间。

本项目是本地优先、单用户、个人开发维护的研究工作站。设计优先级依次为：研究效率、响应速度、可解释性、维护成本；不为 SaaS、多用户、团队协作、商业终端功能或无人值守交易增加复杂度。

## 2. Current Boundary

本设计以当前 active canonical 为约束：

- 当前产品面仍为 Market-only；不恢复已退役的 Signal/Review/Strategy/Backtest 应用面。
- 历史行情只能经 `MarketDataService` 读取 Canonical；Web 不自行 glob、不自行判断主力、不跨频回退。
- 当前物理序列仍只有 `continuous` 与 `contract`；`actual_dominant` 继续由 `MainContractMap rank=1` 查询时拼接。
- `continuous/MAIN` 继续保持当前未平滑主连语义，不用 `futures.get_dominant_price()` 或复权因子改写现有 Canonical。
- historical canonical 与 live observation 分离。本设计不恢复盘中 Live、WebSocket、实时 tick 或 Runtime promotion。
- 所有市场状态均为研究观察，不是交易指令；保持 `auto_order=false`。

当前 DFD-07 数据重建进度不因本设计改变。P0 必须能在 Canonical 未全域完成时对不可用品种 fail-closed/降级展示，而不是伪造完整全市场结论。

## 3. Product Information Architecture

一级导航长期保持简单。当前新增能力只围绕 Market 展开，不为每一种 RQData API 新建一级页面。

```text
Market
├─ Market Radar
└─ Product Workspace
```

未来 Research Enrichment 仍属于 `Product Workspace` 的纵向研究区：

```text
Product Workspace
├─ Kline Workspace
├─ Market State / Price-Volume-OI
├─ Term Structure / Dominant Migration
├─ Member Position Structure
├─ Warehouse State
└─ Trading Economics
```

“会员排名”“仓单库存”“展期收益”“交易参数”是数据来源或研究组件，不是页面单位。

## 4. Market Radar

### 4.1 Question

Market Radar 只回答两个问题：

1. 今天整个期货市场处于什么状态？
2. 哪 5～10 个品种值得进一步打开 Product Workspace？

页面允许纵向滚动，但第一屏必须完成主要发现任务。

### 4.2 First-screen Structure

第一屏固定四块：

1. **市场概览**：最多 6 个摘要指标；
2. **价格变化 × 持仓量变化散点图**：页面主视觉；
3. **今日值得关注**：5～10 个可解释候选；
4. **板块表现**：低密度摘要，不与散点主视觉竞争。

推荐概览指标固定为：

- 上涨品种数；
- 下跌品种数；
- 放量品种数；
- 明显增仓品种数；
- 高波动品种数；
- 数据对应的最新完整交易日。

不持续增加“市场平均收益、平均 ATR、总持仓”等只是因为能计算却不能明显提高决策效率的指标。

### 4.3 Price × Open Interest Map

散点图定义：

- X 轴：品种 1D 价格变化；
- Y 轴：同口径 OI 变化；
- 气泡大小：成交额或统一流动性代理；
- 颜色：价格上涨/下跌；
- 点击：直接进入该品种 Product Workspace；
- Hover：只显示品种、1D 涨跌、OI 变化、量比、ATR 分位等 4～5 个核心值。

四象限只表达结构状态：

```text
上涨 + 增仓
上涨 + 减仓
下跌 + 增仓
下跌 + 减仓
```

禁止把 OI 变化直接命名为“多头资金流入/空头资金流出”等无法由这些事实单独证明的因果结论。

### 4.4 Today Watchlist

“今日值得关注”使用可解释规则，而不是黑盒综合评分。

P0 可使用的候选条件来自 Canonical 与 Indicator Kernel，例如：

- 价格上涨/下跌达到相对阈值；
- OI 明显增加/减少；
- 成交量相对近期基线放大；
- ATR/实现波动处于历史高分位；
- 接近或突破近期高低点；
- EMA21 方向/斜率与价格位置一致；
- 多条件同时出现。

结果显示“关注原因 4/5”或直接标签：

```text
放量 / 增仓 / 接近20日高 / EMA21向上
```

不生成“综合评分 82.43”“强烈做多”等伪精确或交易指令式文本。

排序可以按满足条件数量、变化幅度和流动性做稳定的确定性排序，但排序逻辑必须可读、可测试。

### 4.5 Full Market Detail

第一屏以下可保留全市场紧凑表，供人工核对：

```text
品种 | 1D | 5D | 量比 | OI变化 | ATR分位 | 20日位置 | 状态标签
```

表格是下钻工具，不是首页主视觉。

## 5. Product Workspace

### 5.1 Core Principle

进入品种页后，**K 线优先级永久高于所有辅助研究信息**。

任何后续研究功能不得默认把 K 线主体压缩成小窗口。页面纵向空间承担扩展，横向空间只用于轻量研究摘要。

### 5.2 Responsive Layout

采用已确认的方案 C：

- 桌面大屏 `>= 1600px`：K 线主体 + 约 280～300px 常驻轻量研究栏；
- `< 1600px`：右栏自动折叠为入口按钮/抽屉，K 线全宽；
- 所有桌面尺寸均允许一键 K 线全屏；
- 不为移动端或商业终端做独立复杂布局。

右栏展开/折叠属于 UI 偏好，可以仅保存在浏览器本地。

### 5.3 Kline Workspace

Kline Workspace 接近 TradingView 的“看图效率”，但明确不复制其绘图、布局和插件系统。

顶部只保留高频研究操作：

```text
品种/当前合约
Series: 真实主力 | 主连
周期: 1m | 5m | 15m | 30m | 60m | D | W
主图指标: 无 | EMA | BOLL [未来可按正式 Indicator Kernel 增加少量已批准指标]
全屏
```

`contract` 指定真实合约继续由现有查询合同支持，但作为低频研究入口，不与“真实主力/主连”并列抢占常用工具栏。

明确不实现：

- 趋势线、水平线、斐波那契、文本、测距等画线工具；
- indicator marketplace；
- 自定义公式编辑器；
- 任意多副图、拖拽排序或可配置布局；
- 多图分屏或多窗口联动。

### 5.4 Chart Panels

图表面板固定三层：

1. **主图**：Candlestick + 当前选择的主图指标；
2. **副图 1**：Volume，固定存在；
3. **副图 2**：MACD，固定存在。

主图第一版重点支持 EMA 组合；BOLL 是否进入同一 P0 任务由实施计划按当前 Indicator Kernel 能力决定，不允许在 Web TypeScript 重新定义指标权威。

副图不增加 RSI/KDJ/CCI 等额外管理系统。

### 5.5 Viewport and History Loading

保留当前 `lightweight-charts` 与向左自动加载历史的方式：

- 页面首次只读取适合当前周期的最近窗口；
- 用户向左拖到边界时自动请求更早 Canonical；
- prepend 后保持原视觉位置，不跳回最新；
- 用户回到最右端时恢复 follow-latest 状态；
- 不一次性加载 2023 至今所有分钟 Bar；
- 无交易时段/周末仍显示最近可用历史，不要求存在“今天”的 Bar。

不同周期可以有不同默认窗口，但这是性能策略，不改变数据语义。

### 5.6 Crosshair Synchronization

K 线体验优化的优先级高于画线工具。

十字光标移动到某个时间点时，主图、Volume、MACD 使用同一个时间位置，并在顶部/面板标签显示该时刻可得数据：

```text
O/H/L/C
Volume
Open Interest
EMA fields (when enabled)
MACD DIF/DEA/HIST
```

仅显示当前可得字段；不为缺失字段静默填充。

历史十字线未来可以与 Research Snapshot 对齐，但 P0 不因此提前引入 Research Canonical。

## 6. Lightweight Research Sidebar

常驻右栏不是第二个 Dashboard，只是“不离开 K 线即可看到的上下文”。

第一版只保留三块：

### 6.1 Trend / Position

- 日线方向；
- 周线方向；
- 20 日价格位置；
- 距近期高/低点距离。

### 6.2 Volume / OI

- 量比；
- OI 变化；
- 成交额变化；
- 必要时 ATR 分位。

### 6.3 Contract Context

P0：

- 当前 rank1 真实主力；
- 主力映射交易日。

P1 才允许增加：

- 近月/主力/次主力价差；
- Roll Yield；
- 换月状态。

右栏避免大表、排名明细和原始 API 字段。

## 7. Vertical Research Area

K 线第一屏以下按研究问题纵向展开。模块到达视口附近再 lazy load；不能因为页面存在就立即请求全部外部研究 API。

推荐顺序：

### 7.1 P0: Price / Volume / OI

使用当前 Canonical 直接计算：

- price + OI 同轴/双轴趋势；
- volume / turnover 变化；
- 趋势、波动和位置摘要。

该模块回答“当前价格变化是否伴随成交与持仓结构变化”。

### 7.2 P1: Term Structure

组合精选 RQData 研究输入，不展示 provider 原始返回：

- 可交易合约列表；
- 合约价格/结算价；
- 到期月份；
- 主力/次主力关系；
- Roll Yield。

输出期限结构曲线、Contango/Backwardation 状态、关键价差与历史分位。

### 7.3 P1: Dominant Migration

结合真实合约 Canonical、MainContractMap、Volume/OI：

- 当前主力与前/次主力；
- 主力与次主力 OI/Volume 相对变化；
- 换月区域和迁移速度；
- 近几次主力切换时间线。

禁止创建第二套主力定义。

### 7.4 P1: Member Position Structure

`futures.get_member_rank` 只作为 Research Adapter 输入。Web 展示二次统计：

- Top5/Top20 long/short；
- 多空净差；
- 集中度及变化；
- 连续上榜/持续增加等稳定性信息。

原始龙虎榜仅作为按需“查看明细”，不是主页面。

### 7.5 P1: Warehouse State

`futures.get_warehouse_stocks` 作为研究输入，主要输出：

- 当前仓单；
- 1D/5D/20D 变化；
- 历史分位；
- 同期价格变化；
- 库存趋势小图。

模块描述“低库存/持续去库/累库”等事实状态，不把库存变化单独解释成交易方向。

### 7.6 P1: Trading Economics

结合交易参数、contract multiplier、tick size 与当前价格，计算并清晰标记“交易所口径”：

- 一手名义价值；
- 一跳盈亏；
- 交易所保证金估算；
- 开仓/平今手续费估算；
- 合约到期日。

期货公司实际保证金和佣金不由此推断。

## 8. Research Data Architecture

P0 不改变当前 Canonical 数据架构。

```text
Canonical / MainContractMap / Indicator Kernel
        -> Market research calculations
        -> Market Radar / Product Workspace
```

P1 新增研究能力时，不把外部研究 API 塞入 `MarketDataService`。保持两层可用性：

```text
Trusted Historical Core
MarketDataService
        -> Kline / Trend / Price-Volume-OI

Research Enrichment
RQData Research Adapter
        -> FuturesResearchService
        -> TermStructure / Member / Warehouse / TradingEconomics
```

Web 访问研究语义 DTO/endpoint，不允许建立 `/api/rqdata/*` 形式的 provider passthrough。

RQData Research API 临时失败、额度耗尽或字段缺失时，只影响对应 enrichment 模块；不能导致 Canonical K 线和 P0 研究摘要不可用。

是否需要长期保存 member/warehouse/term-structure 历史快照属于后续独立 Research Canonical 决策。P1 默认先按需读取/计算，不提前设计通用 lineage、版本平台或第二套 Catalog。

## 9. Local-only Interaction State

利用单用户本地 Web 的优势，简单 UI 偏好可存浏览器 localStorage，不建立账户、Preference API 或用户配置表。

第一版可记忆：

- 上次品种；
- 上次周期；
- 上次 series（真实主力/主连）；
- 主图指标选择；
- 研究侧栏展开状态；
- 自选品种列表。

Market Radar 支持“全部 / 自选”切换；品种页用简单星标加入/移除自选。

本地状态损坏时回退默认值即可，不建立同步、迁移或多设备兼容层。

## 10. Error and Degradation Policy

### Core

以下问题必须显式失败/空状态，不伪造结果：

- Canonical dataset/partition/coverage 不完整；
- MainContractMap 缺失；
- 指标输入不足；
- 当前 DFD-07 未闭环品种不可安全计算全量统计。

Market Radar 必须显示本轮“可参与计算品种数”，避免把部分宇宙结果误写成完整 60 品种结论。

### Enrichment

每个 P1 模块独立失败：

```text
期限结构 暂无研究数据
会员持仓 暂无研究数据
仓单库存 暂无研究数据
```

不要用全局错误页覆盖正常 K 线。

## 11. Performance

个人本地应用优先做简单、明显有效的性能控制：

- K 线按周期使用合理默认窗口；
- 向左拖动再加载更早数据；
- Market Radar 的 P0 指标由后端批量计算或一次聚合响应，避免 60 品种 × 多接口前端 N+1；
- 下方 P1 模块 IntersectionObserver/lazy load；
- 相同品种同交易日的短期研究结果允许简单内存/浏览器缓存；
- 不为此建设分布式缓存、任务平台或复杂 invalidation 系统。

## 12. Testing

### P0 backend

测试应覆盖：

- Market Radar 指标窗口与统一交易日口径；
- price/OI 四象限分类；
- 关注规则标签和确定性排序；
- Canonical/Map 缺失时的部分宇宙与 fail-closed 行为；
- 指标计算使用 quant-core Kernel 权威实现。

### P0 frontend

测试应覆盖：

- Radar 首屏结构、scatter hover/click；
- Product Workspace 路由和上下文保持；
- `>=1600px` 右栏常驻、窄屏折叠；
- 周期/series/主图指标切换；
- Volume + MACD 固定副图；
- 向左加载并保持 viewport；
- localStorage 默认值/损坏值回退；
- Canonical 失败时明确空/错误状态。

### P1

每个 Research Enrichment 模块独立测试 provider normalization、二次统计、失败降级和 Web 展示。不得用真实 provider 调用作为普通单元测试前置。

## 13. Delivery Order

设计基线的推荐实现顺序：

```text
P0-1 Market Radar 数据合同与基础指标
P0-2 Price × OI scatter
P0-3 今日值得关注
P0-4 Product Workspace 页面重排
P0-5 轻量 TradingView-like Kline UX
P0-6 EMA + fixed Volume/MACD
P0-7 轻量研究侧栏
P0-8 自选 + 本地状态记忆

--- 真实使用几天后再决定 P1 ---

P1-1 Term Structure
P1-2 Dominant Migration
P1-3 Roll Yield
P1-4 Warehouse State
P1-5 Member Position Structure
P1-6 Trading Economics
```

P0 完成后先真实使用并观察信息密度、首屏响应和使用频率，再决定 P1 的具体优先级。不得因为 RQData 提供某接口就自动把它产品化。

## 14. Non-goals

本设计明确不做：

- 自动交易、下单或交易建议；
- Live/WebSocket/tick 盘中路径；
- 恢复旧 Backtest/Signal/Review/Strategy 应用面；
- 商业 TradingView 克隆；
- 绘图工具和复杂自定义指标系统；
- 多用户、权限、SaaS、云同步；
- Dashboard builder；
- 多窗口、多图分屏；
- RQData 原始 API 浏览器；
- 为 P1 提前创建通用 Research Catalog/lineage 平台。

## 15. Success Criteria

设计实现成功的标准不是“页面显示更多数据”，而是：

1. 打开 Market Radar 后约十秒内能确定当前市场活跃度和优先研究品种；
2. 点击品种后第一屏以完整 K 线为视觉中心，不需要先处理表单或大量研究卡片；
3. 常用周期、真实主力/主连和少量主图指标可以一键切换；
4. Volume 与 MACD 始终可见，十字线可以联动读取同一时刻的数据；
5. 需要更多解释时向下滚动即可，不需要在多个 API 页面间跳转；
6. 外部 Research API 失败不会破坏可信 Canonical K 线；
7. 新功能保持个人项目的简单性，任何复杂度都必须能直接换来研究效率。
