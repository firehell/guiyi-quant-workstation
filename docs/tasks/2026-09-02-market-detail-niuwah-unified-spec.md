# Market 统一牛哇式详情页 V1 Spec

日期：2026-09-02  
状态：`SPEC_INTERNAL_REVIEW_PASSED / USER_REVIEW_PENDING / IMPLEMENTATION_NOT_STARTED`  
规划基线：`develop@765ee9e75c81d0e9086eeee1cf79775a951a8a5d`  
任务车道：Lane 2（产品与 Web 设计；本文件不实现公式、Runtime 或生产写入）

> 本文冻结 `/market/chart` 下一版的产品、信息架构、交互、视觉语法、数据权威和验收合同。  
> 用户已确认采用“统一牛哇式详情页外壳 + 趋势策略 / 火天大有 / 新苏冰 / 自由看盘四个互斥分析视角”，替代此前“当前版本 / 牛哇版本”双页面结构。

## 1. 规范性边界与文档关系

### 1.1 本文负责什么

本文只负责未来 Market 详情页：

```text
/market/chart
→ 统一详情页外壳
→ 四个互斥分析视角
→ 顶部渐进式信息披露
→ 视角内图表、解读、历史与数据详情
```

本文不重新定义任何公式、Event、Scope、Runtime、迁移或生产事实。

### 1.2 与既有 Newow 文档的关系

本文一经用户批准，仅替代下列 Newow 旧设计内容：

```text
“当前版本 / 牛哇版本”双页面入口
CurrentDetailView / NewowTrendDetailView 双外壳
详情页版本切换控件
Newow Web 的顶部信息架构和页面布局
```

以下 Newow 合同继续有效，不受本文修改：

```text
strategy_code = newow_trend_v1
series_kind = actual_dominant
frequency = 1d
completed_only
黄蓝趋势带
建仓 / 清仓
D1 / D2 / D3
杯柄生命周期
同一物理合约段隔离
因果、prefix invariance 与 fail-closed
```

`docs/tasks/2026-09-01-newow-trend-v1-design.md` 与本文发生页面架构冲突时，以本文为未来 Web 设计权威；公式、数据和 Kernel 仍以 Newow 专用 Spec 为准。

### 1.3 与 SuBing、HTDY 和稳定 canonical 的关系

- 新苏冰只认 `subing_ths_alert_15m_v1` / `subing_ths_15m_v2`，正式 Marker 只来自 `AlertEvent`。
- 火天大有继续保留“原始观察可重绘、首次识别 Event 不可变”的双事实语义。
- 通用 EMA、MACD、成交量和 Range Detector 只用于研究展示，不拥有交易、Alert 或持仓语义。
- 当前 `PROJECT_SOURCE.md`、`STATUS.md` 和生产 Runtime 事实不因本设计自动改变。
- 本文不授权修改 `main`、tag、Release、Runtime、production DB/Redis/Scope、真实通知或任何真实数据写入。

---

## 2. 产品定义

### 2.1 最终产品形态

归一量化详情页不再拆成“当前版本”和“牛哇版本”，而是一个统一外壳：

```text
MarketDetailShell
├── 趋势策略 Trend
├── 火天大有 HTDY
├── 新苏冰 SuBing
└── 自由看盘 Free
```

四个视角共享品种身份、返回入口、行情头、视觉系统和基础交互，但各自拥有独立的数据身份、公式权威、图层、解释和历史口径。

### 2.2 用户价值

详情页只解决三件事：

```text
现在发生了什么
→ 为什么会显示成这样
→ 去图表和历史中复核
```

页面不替用户下单，也不输出跨视角综合买卖结论。

### 2.3 默认进入规则

普通品种入口默认进入：

```text
view = trend
series_kind = actual_dominant
frequency = 1d
```

原因：

- 用户已确定牛哇趋势策略是详情页的核心参考形态；
- 牛哇参考页默认突出“趋势策略”；
- 普通入口应先提供稳定、低频、易读的整体趋势，再由用户切换到预警或自由图表。

事件入口不走默认规则，而是精确进入事件所属视角和 Bar。

---

## 3. 设计目标

V1 必须同时满足：

1. 视觉、留白、卡片、标签、折叠、图标和信息节奏参考牛哇详情页。
2. 主图之前先显示当前视角的核心事实和解释，图表用于复核。
3. 不再使用常驻右侧“检查栏”。
4. 顶部只直出高频行情字段，次级字段通过“更多行情数据”展开。
5. 四个视角同时存在，但任一时刻只有一个视角控制主图。
6. 不同视角的数据身份、周期、Marker 和解读不得串用。
7. 保留现有 K 线、成交量、MACD、EMA、Range、HTDY 和 SuBing 能力。
8. Newow 趋势视角仍使用独立计算与图表组合，不退化为现有 Overlay 条件堆叠。
9. 桌面和移动端保持相同的信息顺序。
10. 数据缺失、身份冲突、Runtime degraded 或 API 失败时 fail-closed。

---

## 4. 牛哇参考页的采用与拒绝

用户提供的牛哇截图体现了以下页面节奏：

```text
品种与价格
→ 策略切换
→ 综合信息区
→ 警示和摘要
→ 若干可展开判断块
→ 主图
```

归一量化采用其“信息组织语法”，不复制其品牌资产、私有源码或无权威算法。

| 牛哇参考模式 | 归一量化采用方式 | 明确拒绝 |
|---|---|---|
| 顶部品种、价格、涨跌、OHLCV | 适配为期货品种、主力合约、OHLC、成交量、持仓量 | 股票市值、市盈率、换手率等股票字段 |
| 策略 Tab | 四个互斥分析视角 | 震荡策略、主升浪、AI 分析假入口 |
| 主图前先给结论 | “当前视角摘要”置于主图上方 | 先看图再自己拼装全部事实 |
| 横向摘要和浅底卡片 | 三项直接事实 + 语义提示 + 展开块 | 常驻右侧工程检查栏 |
| 综合分数 | 不使用；改为三个直接事实 | 综合买卖分、胜率、信号强度分 |
| 仓位与行动建议 | 不使用 | 建议仓位、减仓观望、建仓比例 |
| 目标价、吸筹价、止损线 | 不使用 | 无权威目标价、系统止盈止损 |
| 点击展开 | 行情详情、视角证据和运行信息渐进披露 | 首屏平铺全部字段 |
| 大幅宽屏主图 | 详情页全宽图表 | BI 式左右分栏主布局 |

---

## 5. V1 范围

### 5.1 包含

```text
统一 Market 详情页外壳
四个互斥分析视角
普通品种与事件深链
期货化品种行情头
更多行情数据展开区
视角摘要区
模式专属事实条和折叠解释
模式专属周期与序列控制
主图、成交量和适用副图
指标解读
模式专属历史记录
行情与数据可信详情
桌面、平板、移动端响应式
键盘与无障碍
加载、旧快照、降级和错误状态
视觉截图和 E2E 验收
```

### 5.2 不包含

```text
自动交易或订单
账户、委托、实际持仓、保证金、PnL
仓位建议、止盈止损建议
目标价、吸筹价、收益率曲线
跨视角综合结论或综合评分
AI 自动分析
新增震荡策略或主升浪策略
Newow Alert / PushPlus / Runtime
SuBing 新公式或隐藏过滤
HTDY 公式修订
Range Detector 策略化
新闻、基本面、外盘或宏观数据
新的 PostgreSQL 表、Redis key、队列或 Worker
```

---

## 6. 页面总架构

```text
MarketDetailPage
├── MarketDetailTopBar
├── MarketDetailQuoteHeader
│   └── MarketFactsDisclosure
├── MarketDetailViewNav
├── MarketDetailViewHost
│   ├── TrendDetailWorkspace
│   ├── HtdyDetailWorkspace
│   ├── SubingDetailWorkspace
│   └── FreeChartWorkspace
└── SharedDetailDrawer
```

每个 Workspace 内部顺序固定：

```text
视角控制
→ 当前视角摘要
→ 主图
→ 适用副图
→ 指标解读 / 历史记录 / 行情数据
```

禁止恢复以下主布局：

```text
主图 | 常驻右侧检查栏
```

宽屏下也以纵向阅读为主，主图使用可用宽度。

---

## 7. 路由与身份合同

### 7.1 路由

继续使用唯一详情路由：

```text
/market/chart
```

新增规范化查询参数：

```text
view = trend | htdy | subing | free
```

示例：

```text
/market/chart?symbol=jm&view=trend
/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m
/market/chart?symbol=jm&view=subing&focus_bar_end=...
/market/chart?symbol=jm&view=free&series_kind=continuous&frequency=60m
```

### 7.2 四视角能力矩阵

| 视角 | `series_kind` | 周期 | 默认图层 | 身份是否可改 |
|---|---|---|---|---|
| 趋势策略 | `actual_dominant` | `1d` | Newow 趋势图层 + 成交量 | 不可改 |
| 火天大有 | `continuous / actual_dominant / contract` | `1m/5m/15m/30m/60m/1d/1w` | HTDY + 成交量 + MACD | 可改 |
| 新苏冰 | `actual_dominant` | `15m` | EMA21 + 成交量 + MACD + Event Marker | 不可改 |
| 自由看盘 | `continuous / actual_dominant / contract` | `1m/5m/15m/30m/60m/1d/1w` | 通用指标 | 可改 |

### 7.3 明确切换与非法 URL

用户点击视角 Tab 属于明确操作：

- 点击“趋势策略”时，URL 更新为 `actual_dominant + 1d`。
- 点击“新苏冰”时，URL 更新为 `actual_dominant + 15m`。
- 点击“火天大有”或“自由看盘”时，恢复该视角最近一次合法设置；无历史设置时使用 `actual_dominant + 15m`。

直接输入或打开不合法 URL 时不得静默修正：

```text
view=trend&frequency=15m
view=subing&series_kind=continuous
view=unknown
contract 序列但 contract 缺失
```

页面显示明确不可用状态和“按该视角要求打开”按钮。只有用户点击后才规范化 URL。

### 7.4 入口规则

普通首页行：

```text
symbol
→ view=trend
→ actual_dominant
→ 1d
```

HTDY Event：

```text
symbol
→ view=htdy
→ actual_dominant
→ event.frequency
→ focus_bar_end=event.bar_end
```

SuBing Event：

```text
symbol
→ view=subing
→ actual_dominant
→ 15m
→ focus_bar_end=event.bar_end
```

`focus_bar_end` 继续使用已有的一次性消费语义。趋势策略的历史标记定位在 V1 内通过当前图表实例完成，不新增公开深链参数。

### 7.5 产品切换

- 趋势策略和新苏冰：切换品种后自动解析新品种的当前 `actual_dominant`。
- 火天大有和自由看盘：保留合法的 `series_kind + frequency`。
- 若当前是 `contract` 且切换品种，指定合约不得跨品种沿用；页面回到 `actual_dominant` 并显示一次明确提示。
- 任何视角切换都不得继承另一个视角的指标、Marker、展开内容或 viewport。

---

## 8. 顶部导航

### 8.1 桌面结构

```text
← 行情看板
品种中文名  当前主力合约 ▾
[历史] [预警] [更多]
```

### 8.2 操作显示规则

- 返回：优先返回来源页；没有合法来源时回 `/market`。
- 品种：打开可搜索品种抽屉或下拉。
- 历史：只在当前视角存在合法历史内容时显示。
- 预警：只在 HTDY / SuBing 且当前 Rule 与频率可控制时显示。
- 预警抽屉必须明确展示 `rule_code + symbol + frequency + 当前服务端状态`；用户切换只提交这一项精确 Scope，不做批量或隐式变更。请求失败时读回服务端状态，不用乐观 UI 冒充成功。
- 更多：承载图表全屏、数据说明和适用设置。
- V1 不新增收藏能力，因此不显示空心星或不可用收藏按钮。

### 8.3 吸附态

页面滚动越过完整行情头后，顶部收敛为：

```text
←  焦煤 JM2601   1286.5  +1.42%   [当前视角]
```

吸附态不重复展示 OHLCV，不遮挡视角 Tab。

---

## 9. 品种行情头

### 9.1 默认可见字段

```text
品种中文名
品种代码
当前显示合约
最新已完成 Bar 的 close
涨跌值
涨跌幅
open
high
low
volume
open_interest（可用时）
数据截至时间
```

状态标签：

```text
真实主力 / 主连 / 指定合约
交易所
交易中 / 盘中休市 / 已收盘 / 状态未知
Live / Historical / 收盘快照
```

### 9.2 价格时间口径

顶部价格始终来自当前视角所显示序列的最新已完成 Bar：

- 趋势策略：completed D1。
- 新苏冰：completed 15m。
- HTDY / 自由看盘：当前所选周期的 completed Bar。
- 未完成 Preview 或 tick 不得冒充顶部价格。
- 页面必须显示“截至”时间，防止用户把日线收盘值误认为实时价格。

### 9.3 “更多行情数据”展开

默认折叠，点击后在行情头内部展开三组信息。

#### 行情扩展

```text
turnover（有则显示）
price_change_5d
volume_ratio20
oi_change_1d
position20
distance_to_20d_high
distance_to_20d_low
atr14_percentile252
```

#### 主力身份

```text
series_kind
current dominant contract
dominant mapping date
resolved physical contract segment
trading_day
exchange
sector
```

#### 数据可信

```text
canonical coverage
has_more_before
overlay source
market phase
live eligible
live available
last successful update / stale status
```

缺失的可选字段显示 `—`；关键身份不可证明时显示错误，不以旧品种或旧合约补齐。

### 9.4 展开交互

- 默认折叠。
- 点击标题、箭头或键盘 Enter/Space 均可切换。
- 桌面在原位展开；移动端同样原位展开，不跳转独立页面。
- 展开状态不跨品种持久化，避免用户误以为旧信息仍属于新对象。

---

## 10. 分析视角导航

显示顺序固定：

```text
[趋势策略] [火天大有] [新苏冰] [自由看盘]
```

规则：

- 使用牛哇式横向胶囊 Tab。
- 当前项为橙色实底，其他项为浅灰或白底。
- 每个 Tab 必须有可读文字，不只依赖颜色。
- 移动端横向滚动，不压缩成难以点击的小字。
- 不显示“AI 分析”“震荡策略”“主升浪”等未实现入口。

周期与序列控件位于 Tab 下方：

- 只有一个周期时显示固定胶囊，例如 `日K` 或 `15m`。
- 有多个周期时显示横向周期 Chip。
- `series_kind` 只有 HTDY / 自由看盘可见。
- 不支持的周期或序列直接不渲染，不渲染灰色假按钮。

---

## 11. 当前视角摘要区

### 11.1 位置与目的

摘要区位于视角控件与主图之间，是页面最重要的信息层：

```text
视角标题 + 数据截至
→ 语义提示
→ 三项直接事实
→ 主摘要卡
→ 可展开证据块
```

用户应在查看 K 线前理解当前视角“显示了什么、依据是什么、数据是否可信”。

### 11.2 禁止“综合决策”

摘要区不得输出：

```text
综合分数
买卖总分
置信度
胜率
方向投票
四视角共振
建议仓位
行动建议
```

每一项只能显示所属视角的直接事实。

### 11.3 语义提示

每个视角固定一条短提示：

- 趋势策略：`建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。`
- 火天大有：`原始观察可能随未来 K 线重绘；已保存首次识别事件不会被改写。`
- 新苏冰：`正式 S↑ / S↓ 只来自 AlertEvent；图上的 EMA21 与 MACD 仅用于人工复核。`
- 自由看盘：`通用指标只用于研究展示，不构成交易或预警结论。`

### 11.4 三项直接事实

采用牛哇顶部三栏摘要的视觉节奏，但内容为直接事实。

| 视角 | 事实 1 | 事实 2 | 事实 3 |
|---|---|---|---|
| 趋势策略 | 当前趋势状态 | 当前 D1/D2/D3 风险 | 当前杯柄状态 |
| 火天大有 | 当前原始观察 | 最新已保存事件 | 当前预警可用状态 |
| 新苏冰 | 最新已保存预警 | 信号 K 线时间 | 当前 Rule / Runtime 状态 |
| 自由看盘 | 当前序列 | 当前周期 | 当前数据状态 |

任何字段不可用时写明 `不可用` 或 `暂无`，不能改写成“中性”。

### 11.5 折叠块

- 第一块默认展开。
- 其他块默认折叠。
- 桌面允许独立展开多个；移动端采用单开 Accordion。
- 每块标题行包含摘要、更新时间和展开箭头。
- 展开正文最多分为“事实、依据、说明”三层，不出现长篇工程日志。
- 错误和 stale 信息不得隐藏在折叠正文中，必须在标题或事实条可见。

---

## 12. 趋势策略视角

### 12.1 固定身份

```text
view = trend
strategy_code = newow_trend_v1
series_kind = actual_dominant
frequency = 1d
completed_only = true
alert_capable = false
auto_order = false
```

### 12.2 摘要区

三项直接事实：

```text
趋势状态：建仓 / 持有 / 清仓 / 空仓
风险标记：D1 / D2 / D3 / 无
杯柄状态：形成 / 就绪 / 突破 / 走弱 / 失效 / 过期 / 无
```

主摘要标题：

```text
趋势判断
```

默认展开内容：

```text
当前黄带 / 蓝带状态
最近一次 BUILD / CLEAR 转换
状态发生日期
当前物理合约
分析截至 completed D1
```

第二块：

```text
风险与形态
```

内容：

```text
最近 D1 / D2 / D3
杯柄方向
杯柄生命周期
关键锚点和确认时间
成交量事实
```

第三块：

```text
主力与数据
```

内容：

```text
当前 actual dominant
主力映射日
物理合约段
是否发生 rollover reset
数据覆盖与可用状态
```

### 12.3 状态文案

用户可见状态只使用：

```text
建仓
持有
清仓
空仓
```

固定提示：

```text
策略状态，不是实际账户持仓。
```

蓝色只表示 Newow 的空仓或风险阶段，不表示建立期货空单。

### 12.4 主图

层级从底到顶：

```text
K 线与网格
黄蓝趋势带
杯柄轮廓和柄部区间
BUILD / CLEAR Marker
D1 / D2 / D3 Marker
十字线与选中态
主力换月分界
```

副图：

```text
成交量
```

不显示：

```text
MACD
Range Detector
HTDY
SuBing Marker
目标价
吸筹价
收益率曲线
```

### 12.5 历史与解读

指标解读：

```text
趋势策略
D1 / D2 / D3
杯柄形态
```

历史记录：

```text
BUILD
CLEAR
D1
D2
D3
CUP_READY
CUP_BREAKOUT
CUP_WEAKENED
CUP_INVALIDATED
CUP_EXPIRED
```

历史列表来自 Newow 只读结果，不称为 AlertEvent，不声明通知或送达。

### 12.6 不可用

Newow 结果不可用时：

- 可以保留基础 completed D1 K 线；
- 不渲染黄蓝、Marker、杯柄或趋势状态；
- 摘要显示 `趋势策略数据不可用`；
- Web 不允许重新实现 Newow 公式作为 fallback。

---

## 13. 火天大有视角

### 13.1 能力

```text
view = htdy
series_kind = continuous | actual_dominant | contract
frequency = 1m | 5m | 15m | 30m | 60m | 1d | 1w
```

### 13.2 双事实语义

必须并列显示：

```text
原始观察
可能重绘，来自当前图表 Bar 的 retrospective / current display

已保存首次识别事件
来自 AlertEvent，创建后不可变
```

原始观察不得覆盖、替换或删除已保存 Event；已保存 Event 也不能被描述为当前仍然成立的原始观察。

### 13.3 摘要区

三项直接事实：

```text
当前原始观察：买观察 / 卖观察 / 双向观察 / 暂无
最新已保存事件：类型 + 观察时间 + 首次识别时间 / 暂无
预警状态：已启用 / 未启用 / 不支持当前身份 / Runtime 不可用
```

默认展开：

```text
当前观察
```

内容：

```text
当前观察标签
观察 Bar
ZK1 / ZD1 / ZD2 可见状态
可能重绘提示
```

第二块：

```text
首次识别事件
```

内容：

```text
Event 方向
观察 Bar 时间
detected_at
physical contract
持久事件身份
```

第三块：

```text
预警与运行
```

内容：

```text
当前 Rule
当前产品 × 周期 Scope
Runtime heartbeat / per-rule status
notification_attempted_at
provider accepted 不等于微信送达
```

### 13.4 主图

```text
K 线
ZK1
ZD1
ZD2
原始观察 Marker
持久 AlertEvent Marker
可选 EMA10 / EMA21 / EMA60
可选 Range Detector
成交量
MACD
```

通用 EMA 和 Range 只作为独立研究图层，默认关闭，也不得进入 HTDY 摘要、Event 或预警判断。

不显示：

```text
Newow 趋势图层
SuBing Marker
```

### 13.5 Marker 区分

- 原始观察：轻量、小尺寸、普通观察标签。
- 已保存 Event：实心方形或明确事件徽标。
- 两者必须使用不同形状和 Tooltip 标题，不能只靠颜色区分。

### 13.6 降级

- Alert API 不可用但行情 Bar 可用：保留原始 HTDY 展示，持久事件区域显示不可用。
- HTDY 图表计算不可用：不显示原始观察，已保存 Event 仍可显示。
- Runtime degraded：不得隐藏，预警状态明确显示 degraded，但不影响既有 Event 的只读查看。

---

## 14. 新苏冰视角

### 14.1 固定身份

```text
view = subing
rule_code = subing_ths_alert_15m_v1
formula_version = subing_ths_15m_v2
series_kind = actual_dominant
frequency = 15m
completed_only = true
auto_order = false
```

### 14.2 唯一正式事实

正式方向 Marker 只来自：

```text
AlertEvent
```

Web 不根据 EMA21、MACD 或最新 Bar 自己生成 S↑ / S↓。

当当前窗口没有 Event 时，显示：

```text
当前窗口暂无已保存苏冰预警
```

不得显示“中性”“无信号偏多/偏空”或根据本地计算补一个当前方向。

### 14.3 摘要区

三项直接事实：

```text
最新预警：S↑ 多头预警 / S↓ 空头预警 / 暂无
信号 K 线：bar_end + physical contract
预警状态：Rule + Scope + Runtime 可用状态
```

默认展开：

```text
最新预警
```

内容：

```text
Event 方向
信号 K 线时间
detected_at
physical contract
notification_attempted_at
```

第二块：

```text
触发规则
```

固定说明：

```text
S↑：MACD 金叉且 Close > EMA21
S↓：MACD 死叉且 Close < EMA21
```

不增加：

```text
零轴过滤
量能 / OI
Range
ATR
周期共振
评分
三根 K 确认
```

第三块：

```text
运行与通知
```

内容：

```text
Rule enabled
当前产品 15m Scope
per-rule last evaluated Bar
last event
last failure
provider accepted 不等于微信送达
```

### 14.4 主图

```text
15m K 线
EMA21
S↑ / S↓ AlertEvent Marker
成交量
MACD
```

EMA21 和 MACD 是通用可视化复核，不是第二套 Candidate authority。

不显示：

```text
Newow
HTDY
Range Detector
EMA10 / EMA60
本地推导正式 Marker
```

### 14.5 Marker

```text
S↑：上箭头，位于 Bar 下方，配“多头预警”
S↓：下箭头，位于 Bar 上方，配“空头预警”
```

使用中国市场惯例：

```text
上涨 / 多头观察使用红色
下跌 / 空头观察使用绿色
```

仍必须同时使用文字和箭头方向，不能只靠颜色。

### 14.6 历史

历史记录只显示真实 SuBing AlertEvent。点击后：

```text
切换到 view=subing
定位 focus_bar_end
打开 Event 详情抽屉
```

---

## 15. 自由看盘视角

### 15.1 能力

```text
view = free
series_kind = continuous | actual_dominant | contract
frequency = 1m | 5m | 15m | 30m | 60m | 1d | 1w
```

### 15.2 产品定位

自由看盘是通用研究工具，不给“当前策略结论”。

三项直接事实：

```text
当前序列
当前周期
当前数据状态
```

默认展开：

```text
指标设置
```

内容：

```text
EMA10
EMA21
EMA60
Range Detector
```

第二块：

```text
市场背景
```

内容：

```text
周线趋势
日线趋势
20 日位置
量比 20
OI 1D
ATR 分位
```

第三块：

```text
数据详情
```

内容：

```text
series identity
physical contract
mapping date
Live / Historical
Canonical coverage
历史边界
```

### 15.3 主图

```text
K 线
用户选择的 EMA10 / EMA21 / EMA60
可选 Range Detector
成交量
MACD
```

不显示任何 Newow、HTDY 或 SuBing Marker。

Range Detector 固定提示：

```text
只读回画展示；确认前不可用于策略判断。
```

### 15.4 历史入口

自由看盘没有策略历史，因此不显示“历史记录”空入口。底部只显示：

```text
指标解读
行情数据
```

---

## 16. 图表通用交互

所有视角保留：

```text
缩放
平移
十字线
向左加载
回到最新
全屏
Marker 点击
```

规则：

- 用户离开最新位置时显示“回到最新”。
- 向左加载保持 viewport，不跳到起点。
- 模式、品种、序列或周期改变时取消旧请求并拒绝过期结果。
- 全屏只放大当前图表和必要控制，不显示顶部摘要和历史抽屉。
- `focus_bar_end` 定位成功后停止自动跟随，避免立即跳回最新。
- 不同视角的 viewport 独立保存于当前会话，不跨视角硬套时间范围。

---

## 17. Marker 与换月语义

### 17.1 视角隔离

任一主图只渲染当前视角的 Marker：

```text
Trend → Newow Marker
HTDY → HTDY 原始观察 + HTDY Event
SuBing → SuBing Event
Free → 无策略 Marker
```

禁止把 HTDY、SuBing 和 Newow 同时叠到一张图上。

### 17.2 点击行为

点击 Marker 打开统一详情抽屉，固定结构：

```text
标记名称
所属视角
Bar 时间
physical contract
直接事实
事实来源
公式 / 规则版本（适用时）
风险或重绘说明
```

不显示账户仓位、收益或交易动作。

### 17.3 主力换月

在 `actual_dominant` 图表中显示低干扰垂直分界：

```text
JM2509 → JM2601
主力切换
```

- 分界只表达 physical contract ownership。
- 不暗示价格跳空是交易机会。
- Newow 和 SuBing 的计算状态仍按各自 same-contract / rollover 合同处理。
- `continuous` 不伪装成 actual dominant。

---

## 18. 底部信息区与抽屉

Shell 提供三个能力槽位：

```text
指标解读
历史记录
行情数据
```

当前视角没有内容时不渲染对应入口。

### 18.1 桌面

主图下方显示 Tab 条。选择后在图表下原位展开内容，也可由顶部快捷入口滚动到该区域。

### 18.2 移动端

选择后使用底部抽屉：

```text
半透明遮罩
白色大圆角卡片
明确标题
可滚动正文
底部关闭按钮
```

### 18.3 数据复用

顶部“历史”与底部“历史记录”必须消费同一个 ViewModel 和数据源，不允许实现两套历史列表。

---

## 19. 数据权威矩阵

| 页面事实 | 唯一权威 | Web 允许做什么 | Web 禁止做什么 |
|---|---|---|---|
| 品种、交易所、主力合约 | Market metadata / MainContractMap 投影 | 格式化和展示 | 自判主力 |
| K 线 | Market API / `useMarketSeries` | 排序、映射到图表 | glob、跨频回退 |
| 周日趋势与研究指标 | `getProductResearch` | 直接展示 | 重新定义趋势 |
| Newow 趋势 | Newow 专用只读 API / Engine | 映射到专用图表 | 浏览器重算正式 Newow |
| HTDY 原始观察 | 现有 HTDY Web display kernel | retrospective 展示 | 冒充不可变 Event |
| HTDY 已保存事件 | Alert API | Marker、历史和详情 | 因重绘改写 Event |
| SuBing 预警 | Alert API | Marker、历史和详情 | 本地计算正式 Marker |
| EMA / MACD / Range | 通用前端指标实现 | 可视化复核 | 获得 Alert/交易语义 |
| Rule / Scope | Alert API | 明确用户操作后修改 | 批量或隐式变更 |
| Runtime 状态 | Runtime health | 展示 | 推断微信实际送达 |

### 19.1 共享头部 ViewModel

```text
MarketDetailHeaderModel
├── symbol
├── product_name
├── exchange
├── sector
├── series_kind
├── contract
├── as_of
├── open / high / low / close
├── change / pct
├── volume / turnover / open_interest
├── phase
├── display_source
├── freshness
└── extended facts
```

这可以由当前单品种 bars、dominants 和 research 组合成 Web 展示模型；它不是新策略 authority。

### 19.2 视角 ViewModel

```text
DetailViewModel
├── view
├── identity
├── as_of
├── semantic_banner
├── facts[3]
├── disclosure_sections[]
├── chart_payload
├── history
├── data_status
└── actions
```

每个事实必须标记来源类别：

```text
market
newow
htdy_display
alert_event
runtime
generic_indicator
```

不同来源不得在 ViewModel 中合成为一个方向或分数。

---

## 20. 数据加载与刷新

### 20.1 初始加载

按依赖分层：

```text
先加载 metadata + bars
→ 可渲染行情头和基础图
→ 并行加载当前视角摘要、Alert、research、Runtime
→ 分块更新
```

不要求所有资源成功后才显示整页。

### 20.2 请求边界

单个详情页只能执行常数级单品种请求：

```text
不得按 Bar 请求
不得按 60 个品种请求
不得因折叠块展开重复计算整套历史
```

展开区默认使用已加载 ViewModel；只有明确尚未请求且内容成本较高时才 lazy-load。

### 20.3 刷新

- Live / Bar 更新只更新当前身份。
- 切换视角时旧 generation 的响应必须丢弃。
- 切换到 Trend 或 SuBing 时先验证固定身份。
- 30 秒 Alert 刷新继续只更新 Event 展示，不重置用户 viewport。
- 手动刷新只刷新当前品种和当前视角，不触发全市场刷新。

---

## 21. Loading、stale 与错误

### 21.1 原则

```text
能显示什么就显示什么
但绝不把缺失事实猜成中性、正常或无信号
```

### 21.2 同身份旧快照

只有完全相同的：

```text
symbol + view + series_kind + contract + frequency
```

才允许保留上一份成功视图，并显示：

```text
正在展示上一份成功快照
```

不得把旧品种、旧周期或旧合约数据沿用到新身份。

### 21.3 错误矩阵

| 失败 | 页面行为 |
|---|---|
| metadata 失败 | 阻塞身份相关内容，显示“品种元数据不可用” |
| bars 失败 | 图表不可用；不渲染任何派生图层 |
| research 失败 | 基础图保留；市场背景显示不可用 |
| Newow 失败 | D1 基础图可保留；趋势图层和摘要不可用 |
| HTDY display 失败 | 持久 Event 仍可见；原始观察不可用 |
| Alert API 失败 | 不显示持久 HTDY / SuBing Event；不本地补算 |
| Runtime health 失败 | 显示“运行状态不可用”；不推断 Rule 正常 |
| Range warm-up 不足 | Range 不显示，并保留明确原因 |
| 非法 URL 身份 | fail-closed，不自动换周期或序列 |

### 21.4 Runtime 与数据分离

以下状态必须分别展示：

```text
行情数据可读
Alert Runtime degraded
Rule disabled
Rule 无 Scope
provider attempted
provider accepted
微信实际送达未知
```

不得压缩成一个“正常 / 异常”标签。

---

## 22. 视觉系统

### 22.1 总体风格

```text
全宽浅色页面
白色主体
浅灰区块
细分隔线
小圆角信息条
中圆角内容卡
胶囊式 Tab
低强度阴影
高密度但不拥挤
```

不恢复深色应用顶部或左侧应用导航；`/market` 与 `/market/chart` 继续作为全视口 Market 工作区。

### 22.2 色彩

沿用 Market Home 已冻结的中国市场语义和现有 token：

```text
上涨 / 多头观察：#E63935
下跌 / 空头观察：#35C759
当前选中视角：#FF9601
中性控制：#017AFF 或中性灰
数据不足：#98A2B3
```

实现优先复用 `--gy-*` token，不在局部组件重新定义第二套方向色。

Newow 黄蓝带使用其专属颜色，不与首页中性蓝或 HTDY 颜色混用。

### 22.3 信息层级

从强到弱：

```text
价格与当前状态
视角事实
风险 / 不可用
证据摘要
工程数据详情
```

Canonical coverage、mapping date 和 bars 数量不进入首屏主视觉，只在更多行情或行情数据中展示。

### 22.4 参考页视觉验收

实现阶段必须在真实浏览器并列对照：

```text
牛哇参考详情页
归一量化趋势策略
归一量化 HTDY
归一量化 SuBing
归一量化自由看盘
```

对照重点：

```text
首屏留白
策略 Tab
摘要区密度
折叠块层级
警示条
主图起始位置
卡片圆角
字号和行高
颜色和图标语义
```

不得声称复制牛哇私有 CSS 或品牌一致性。

当本文未写明某个纯视觉细节时，实施者按以下顺序收敛：

```text
用户提供的牛哇真实截图 / 可访问页面
→ 已实现的牛哇式 Market Home token 与图标节奏
→ 本文的信息层级和无障碍合同
→ 无证据则省略，不自由发挥
```

若参考视觉与数据权威、风险提示或无障碍冲突，以归一量化合同为先。

---

## 23. 响应式

### 23.1 1920 × 1080 / 1440 × 900

- 页面使用几乎全部可用宽度。
- 无常驻右侧栏。
- 行情头、视角 Tab、摘要区均在主图上方。
- 默认只展开第一块，主图顶部在首屏或首次小幅滚动后可见。
- 图表最小高度 560px。

### 23.2 1280 × 800

- 行情字段允许换行。
- 三项事实保持三栏或紧凑三列。
- 摘要展开正文不与图表并排。
- 图表最小高度 500px。

### 23.3 390 × 844

- 顶部吸附。
- 视角和周期横向滚动。
- 三项事实可横向滑动或变为三行紧凑卡。
- Accordion 单开。
- 图表最小高度 420px。
- 解读、历史和数据使用底部抽屉。
- 不显示桌面专用 Hover 才能获得的关键事实。

---

## 24. 无障碍

- 所有 Tab、Accordion、Drawer 和 Marker 详情可用键盘操作。
- 视角 Tab 使用 `role=tablist` / `role=tab` 或等价语义。
- Accordion 标题暴露 `aria-expanded` 和控制目标。
- 红绿状态必须同时有文本、形状或箭头。
- 图表 Marker 有中文 aria 描述和可访问历史列表替代。
- 焦点不得被 Drawer 吞失；关闭后回到触发元素。
- 动效尊重 `prefers-reduced-motion`。
- 移动端触控目标不小于 44 × 44 CSS px。

---

## 25. 本地偏好与状态隔离

新增版本化偏好：

```text
guiyi.market.detail.preferences.v1
```

只保存：

```text
last_view
htdy.series_kind
htdy.frequency
htdy.optional_ema_indicators
htdy.show_range_detector
free.series_kind
free.frequency
free.optional_ema_indicators
free.show_range_detector
```

不保存：

```text
focus_bar_end
当前品种的临时错误
旧快照
Accordion 展开正文
Rule / Scope
Runtime 状态
```

迁移规则：

- 现有 `guiyi.market.chart.preferences.v9` 的通用 EMA、Range、周期只迁移到 `free`。
- 旧 `selectedOverlay=htdy` 不能让普通品种入口跳过新默认 Trend。
- 存储损坏时返回安全默认值。
- HTDY、SuBing、Trend 和 Free 的设置不得互相覆盖。

---

## 26. 组件与代码边界

### 26.1 推荐组件树

```text
src/pages/market/chart.vue                 # 未来收敛为 Shell / route orchestrator
src/components/market/detail/
├── MarketDetailTopBar.vue
├── MarketDetailQuoteHeader.vue
├── MarketFactsDisclosure.vue
├── MarketDetailViewNav.vue
├── MarketDetailInsightDeck.vue
├── MarketDetailFactStrip.vue
├── MarketDetailDisclosure.vue
├── MarketDetailSectionTabs.vue
├── MarketDetailDrawer.vue
├── TrendDetailWorkspace.vue
├── HtdyDetailWorkspace.vue
├── SubingDetailWorkspace.vue
└── FreeChartWorkspace.vue
```

图表：

```text
NewowTrendChartStage        # 独立组合
HtdyChartStage              # 可适配现有 KlineChart
SubingChartStage            # 可适配现有 KlineChart
FreeChartStage              # 可适配现有 KlineChart
```

### 26.2 不建设巨型条件组件

禁止继续把以下全部塞进一个模板：

```text
if trend ...
if htdy ...
if subing ...
if free ...
```

Shell 只负责：

```text
route
identity
shared header
view selection
error boundary
workspace mounting
```

各 Workspace 自己负责摘要、图层、历史和视角控制。

### 26.3 现有组件处置

当前：

```text
ProductWorkspaceToolbar
ProductCheckSidebar
product-status-strip
```

在新页面完成并通过回归后退出 active 页面。删除前必须关闭所有 active references；不保留 legacy copy。

现有 `KlineChart.vue` 可继续服务 HTDY、SuBing 和 Free，但不得承担 Newow 正式公式，也不得因本任务复制 SuBing Candidate。

### 26.4 后端影响

本设计不要求新的通用详情数据库或缓存。

允许的未来只读接口：

- 复用现有 Market、Research、Runtime 和 Alert API。
- Newow 仅接其既定 Slice C 专用只读 API。
- 若实现发现共享行情头缺少一个关键字段，优先扩展已有单品种只读 DTO，不新增第二套 Market Domain。

---

## 27. 关键用户流程

### 27.1 普通品种

```text
首页点击焦煤
→ Trend
→ 查看趋势状态 / D 风险 / 杯柄
→ 展开趋势判断
→ 图表复核
→ 切换 SuBing 查看 15m 预警
```

### 27.2 HTDY Event

```text
首页点击 HTDY Event
→ Htdy
→ exact frequency
→ 定位 observation Bar
→ 打开 Event 详情
→ 原始观察与持久事件分开显示
```

### 27.3 SuBing Event

```text
首页点击 S↑ / S↓
→ SuBing
→ actual_dominant 15m
→ 定位信号 Bar
→ 打开 Event 详情
→ EMA21 / MACD 图上复核
```

### 27.4 自由复核

```text
切换 Free
→ 选择主连 / 真实主力 / 指定合约
→ 选择周期
→ 打开 EMA / Range
→ 查看市场背景和数据详情
```

### 27.5 数据失败

```text
Alert API 失败
→ 图表基础行情保留
→ Event 区显示不可用
→ 不本地生成正式 Event
```

---

## 28. 验收标准

### 28.1 产品

1. 只有一个详情页外壳。
2. 四个视角互斥。
3. 普通入口默认 Trend。
4. Event 入口精确进入所属视角。
5. 主图前有牛哇式摘要和展开块。
6. 无常驻右侧检查栏。
7. 不输出综合评分、仓位或目标价。

### 28.2 身份

1. Trend 始终 `actual_dominant + 1d`。
2. SuBing 始终 `actual_dominant + 15m`。
3. HTDY / Free 支持其合法序列和七周期。
4. 非法 URL fail-closed。
5. product / view / series / frequency 切换不显示旧身份数据。
6. actual dominant 换月可见且不跨合约污染正式状态。

### 28.3 事实

1. SuBing Marker 只来自 AlertEvent。
2. HTDY 原始观察与持久 Event 分开。
3. Newow 正式结果只来自 Newow Engine/API。
4. Free 不显示策略 Marker。
5. Runtime、Rule、Scope、Event、provider acceptance 和微信送达不混淆。

### 28.4 交互

1. 更多行情默认折叠。
2. 第一证据块默认展开。
3. 桌面多开、移动端单开。
4. 顶部和底部历史入口复用同一数据。
5. Marker 点击打开可访问详情。
6. focus 后不立即回到最新。
7. 视角切换保持各自设置但不泄漏图层。

### 28.5 视觉

必须有以下快照：

```text
1920×1080 Trend ready
1440×900 Htdy ready
1440×900 SuBing event
1280×800 Free with Range
390×844 Trend
390×844 SuBing history drawer
非法身份
视角数据 unavailable
Alert API unavailable
Runtime degraded
```

每张快照必须同时验证：

```text
无右侧栏
顶部行情层级
视角 Tab
事实条
展开块
主图位置
红绿橙灰语义
```

### 28.6 单元和 E2E

至少覆盖：

```text
route parser / serializer
default Trend entry
event deep links
fixed identity rules
invalid URL fail-closed
per-view preference isolation
legacy preference migration to Free only
view generation cancellation
header ViewModel
fact strip no synthetic score
accordion behavior
marker isolation
SuBing Event-only authority
HTDY dual-fact display
Newow unavailable no Web fallback
data stale identity match
product switch from contract
keyboard navigation
drawer focus restoration
responsive screenshots
build
```

---

## 29. 实施依赖与切片边界

本文批准后才能编写 Implementation Plan。

后续计划应拆成独立可审查 Slice：

```text
Slice A — Shell、route、header、视角导航、渐进披露、偏好
Slice B — Free + HTDY 迁移，关闭旧 toolbar/sidebar
Slice C — SuBing 专用视角与 Event 深链
Slice D — Newow 只读 API 已完成后接入 Trend
Slice E — E2E、视觉对照、可访问性与最终 Review
```

V1 路由替换不得在 Trend 尚无可用只读数据时提前启用。部分 Slice 可以进入 `develop`，但在全部四个 Workspace 达到验收前，现有 `/market/chart` 必须保持可用，不能发布一个默认进入空 Trend 的半成品页面。

依赖规则：

- Newow Trend 接入不得抢跑其现有 Slice C 只读 API。
- Shell / Free / HTDY / SuBing 的 Web 呈现属于 Lane 2。
- Newow 公式、数据服务或任何 Alert/Scope 语义变化仍按对应 Lane 3 合同执行。
- 各 Slice 不自动合入 `develop`，必须按其风险完成测试和独立 Review。
- 任何 `main`、tag、Release、Runtime promotion 或 production mutation 都不在本任务授权内。

---

## 30. 风险与禁止范围

### 30.1 最大产品风险

```text
为了“像牛哇”而恢复综合买卖建议
为了统一页面而混合四个 authority
为了展示当前方向而在 Web 本地重算 SuBing
为了复用 KlineChart 而把 Newow 塞进 Overlay
为了省请求而沿用错误品种或周期的旧快照
```

上述情况均阻塞实现或集成。

### 30.2 复杂度控制

V1 不做：

```text
通用策略插件平台
通用 Dashboard schema builder
通用 workflow
通用历史事件仓库
服务器端用户偏好
跨设备同步
多用户权限
```

四个固定视角使用显式组件和 typed mapping，适合单用户本地项目维护。

---

## 31. 已冻结决策

```text
统一外壳，取消双页面
四视角互斥
普通入口默认趋势策略
顶部摘要优先于图表
更多行情点击展开
无常驻右侧栏
无综合决策分
无建议仓位
无目标价 / 止损价
Trend 固定 actual_dominant D1
SuBing 固定 actual_dominant 15m
HTDY 保留七周期
Free 承接通用指标
Newow 使用独立 Workspace
SuBing Marker 只来自 AlertEvent
HTDY 原始观察与 Event 分离
桌面和移动端保持同一信息顺序
```

本 Spec 没有未决产品问题；实现阶段只能在不改变上述决策的前提下做像素级校准。

---

## 32. Spec 自审记录

自审已检查：

```text
待办占位符：0
未定义视角：0
非法跨视角合成：0
未授权生产操作：0
股票专属字段残留：0
假按钮：0
双页面入口残留：0
右侧栏残留：0
SuBing Web 公式 authority 重复：0
Newow Overlay 化：0
```

当前 Gate：

```text
SPEC_INTERNAL_REVIEW_PASSED
USER_REVIEW_PENDING
IMPLEMENTATION_BLOCKED
```

用户批准本文后，下一步仅允许编写 Implementation Plan；本文本身不授权源码实现。
