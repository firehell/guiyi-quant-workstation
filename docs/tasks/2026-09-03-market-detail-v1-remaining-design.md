# Market 统一详情页 V1 剩余部分 Design Spec

日期：2026-09-03
状态：`DESIGN_REVIEWED / READY_FOR_IMPLEMENTATION`
文档类型：V1 剩余产品与工程设计权威
规划基线：`develop@1cc757e4519dabe06240635304cdccfe644cedc5`
进行中依赖：PR `#327`，`feature/market-detail-free@3f0ccab8b415d15faf25f6baf27c37506d7ff629`
任务车道：Lane 2（只读 Market Web；不修改策略公式、生产状态或真实写入）

> 本文替代并删除：
>
> - `docs/tasks/2026-09-02-market-detail-niuwah-unified-spec.md`
> - `docs/tasks/2026-09-02-market-detail-niuwah-unified-implementation-plan.md`
>
> 本文只冻结统一 Market 详情页 **V1 剩余部分**。已经进入 `develop` 的 Slice A 不重做；PR #327 的 Slice B1 以其 exact-head 实现和验收为准，合入后才开始后续 Slice。

---

## 1. 规范性边界

### 1.1 事实源优先级

发生冲突时依次服从：

1. `STATUS.md`：当前 release、production Runtime、Scope、自然 evidence 与 Gate；
2. `AGENTS.md`：执行授权、安全边界与不可破坏规则；
3. `docs/DEVELOPMENT.md`：日常开发与验证流程；
4. `PROJECT_SOURCE.md`：当前稳定产品面；
5. `DECISIONS.md` 与 accepted OpenSpec：长期决策与 active contract；
6. 本文与配套 Implementation Plan：未来 V1 剩余 Web 交付；
7. 具体 Issue、PR、代码和测试：实际实现事实。

本文不能将规划写成已发布、已运行或已通过生产 Gate 的事实。

### 1.2 与 Newow 专用文档的关系

`openspec/specs/newow-product-reference-trading/spec.md` 自 2026-09-05 起接管 Newow 新产品能力。
本节下列固定 Trend D1 条款只约束既有 `view=trend` 与
`GET /api/v1/market/newow/trend-detail` 兼容入口，不再限制 `view=newow` 的三策略 × 三周期、
ReferenceTrade、Hint、解释和明确统计窗口。两类入口必须复用同一公式 authority，不能形成第二套算法。

以下 Newow 专用合同继续有效，并且仍由 Newow 文档、Kernel、Engine、只读 API 与测试负责：

```text
strategy_code = newow_trend_v1
profile_id = newow_trend_d1_v1
series_kind = actual_dominant
frequency = 1d
bar_policy = completed_only

newow_trend_band_cleanroom_v1
newow_escape_d123_v1
newow_cup_handle_v1
same-physical-contract isolation
rollover reset / rollover seam
causality / strict-before / prefix invariance / restore parity / fail-closed
```

本文只取代 Newow 专用文档中的旧 Web 交付形态：

```text
CurrentDetailView / NewowTrendDetailView 双外壳
“当前版本 / 牛哇版本”切换
独立 Newow 详情 route 或第二套详情 Shell
```

Newow Web 必须作为统一 `/market/chart` 下的 Workspace 交付，不得在浏览器复制或改写 Newow 公式。

### 1.3 本文不重新定义的内容

本文不重新定义：

- HTDY Kernel、重绘窗口或 first-seen Event 语义；
- SuBing `subing_ths_alert_15m_v1 / subing_ths_15m_v3` 公式；
- Alert Rule、Scope、audience、transport、migration 或 Runtime；
- MarketDataService、Canonical、MainContractMap 或 session 锚点；
- Newow 趋势带、D1/D2/D3、杯柄公式；
- production 0045、G10、G9 或 Runtime promotion。

---

## 2. 产品目标

统一详情页 V1 只完成一个人工盯盘闭环：

```text
Market 首页发现值得复核的品种或 Event
→ 打开统一详情页
→ 选择一个分析视角
→ 先读取当前事实、数据状态和风险说明
→ 在图表、历史与来源详情中复核
→ 用户自行决定是否交易
```

页面只回答：

```text
现在发生了什么
这些事实来自哪里
图表和历史怎样复核
当前哪些数据不可用或存在风险
```

页面不回答：

```text
应该开几手
应该做多或做空
目标价和止损价是多少
多个策略投票后的综合结论
账户应当持有什么仓位
```

---

## 3. V1、V1.1 与 V2 边界

### 3.1 V1 必须交付

```text
现有 Market 首页
统一 /market/chart Shell
Newow / HTDY / SuBing / Free 四个只读 Workspace，另保留 `view=trend` D1 兼容入口
普通品种入口与 Event 精确深链
共享行情头、单一身份控制、渐进式披露和详情抽屉
四视角 Marker、历史、数据和错误边界隔离
最终默认 Newow 趋势日线
旧详情页与 active legacy reference 删除
桌面、移动端、键盘、无障碍与视觉验收
active OpenSpec 与稳定产品文档更新
```

V1 不提供任何 Alert Scope 写控制。

### 3.2 V1.1 候选

V1.1 不阻塞 V1，候选范围只有：

1. 首页“日、周、同向”收敛为更清楚的周期结构表达；
2. 首页移动端摘要、Focus Rail 文案和原生链接语义优化；
3. 条件性的 Alert Scope 控制。

Alert Scope 控制只有在以下条件全部满足并且用户确认存在高频管理需求后，才单独建立 Lane 3 Spec：

```text
production 0045 已完成
v1.9.14 exact-tag Runtime 已 promotion 并 readback
新 G10 已通过
G9 已获得独立授权并完成
自然 Event、provider acceptance 与用户实际送达已验证
```

若单用户日常不需要频繁调整 Scope，则长期保留 CLI/专用 activation seam，不做 Web 写控制。

### 3.3 后续候选与 Newow 合同接管

原列为 V2 候选的 Newow Marker 复盘/统计、期货化震荡、多周期解释、4/7/11 与 J 等提示，
已由 `newow-product-reference-trading` OpenSpec 以新身份接管，不再受本文旧 V1 禁止条款约束。
这些能力仍是只读策略与参考交易，不得恢复退役实现。候选版本、OOS、Walk-forward、Shadow、
风险/组合/账户、执行和人工批准晋升继续属于后续独立合同。

现有 `Range Detector` 不能改名或升级为正式震荡策略；单纯 OI 变化不能称为“主力吸筹、洗盘、控盘或出货”。

---

## 4. 已有基线与剩余顺序

### 4.1 已有事实

```text
Slice A
  已进入 develop
  已有 route/identity、preferences、shared shell、shared components

Slice B1
  PR #327 exact head 已完成 Free Workspace 与共享 Kline Stage 修正
  尚处于 owner visual/integration Gate
  未进入 develop

Newow A/B/C
  Kernel、Engine、actual-dominant D1 service 和只读 API 已进入 develop
  GET /api/v1/market/newow/trend-detail 已存在
```

### 4.2 V1 严格顺序

```text
B1 owner visual review
→ B1 合入 develop
→ B2 HTDY Workspace
→ D Trend Workspace
→ C SuBing Workspace
→ E Final Cutover
```

每个源码 Slice 必须：

```text
从执行时最新 clean develop 创建独立 task branch/worktree
→ Draft PR
→ 定向测试与完整受影响验证
→ exact-head 独立 Review
→ 用户明确“允许集成 develop”
→ 合入 develop
→ 确认后清理 task worktree/branch
```

不得从 PR #327 分支继续开发 B2，也不得并行修改共享 Shell、`MarketDetailPage.vue`、`KlineChart.vue` 或同一 E2E 文件。

---

## 5. 总体架构

```text
/market/chart
└── MarketDetailPage
    ├── MarketDetailTopBar
    ├── MarketDetailQuoteHeader
    │   └── MarketFactsDisclosure
    ├── MarketDetailViewNav
    ├── MarketDetailViewHost
    │   ├── NewowDetailWorkspace
    │   ├── TrendDetailWorkspace（D1 兼容入口）
    │   ├── HtdyDetailWorkspace
    │   ├── SubingDetailWorkspace
    │   └── FreeChartWorkspace
    └── MarketDetailDrawer
```

共享层只负责：

- route 和 identity；
- 品种、序列、合约、周期的单一控制权威；
- generic Market bars、行情头和分页；
- generation/cancellation；
- Workspace 挂载；
- 共享渐进式披露、抽屉和错误状态；
- 一次性 `focus_bar_end` 定位。

共享层不得：

- 计算 Newow、HTDY、SuBing 正式结论；
- 合并四个视角形成总分；
- 把 Event 空列表解释为 Runtime 正常；
- 把 Runtime heartbeat 解释为策略已经评估当前 Bar；
- 根据基础 K 线猜测缺失的正式结果。

每个 Workspace 独立拥有：

- 允许的数据身份；
- 图层白名单；
- 三项直接事实；
- 语义提示；
- disclosure 内容；
- Marker 与历史白名单；
- unavailable/stale/warming 状态。

---

## 6. 路由与身份合同

### 6.1 唯一路由

```text
/market/chart
```

规范参数：

```text
symbol
view = newow | trend | htdy | subing | free
series_kind = actual_dominant | continuous | contract
contract
frequency = 1m | 5m | 15m | 30m | 60m | 1d | 1w
focus_bar_end
```

### 6.2 能力矩阵

| View | 序列 | 周期 | 正式 Marker | 身份可改 |
|---|---|---|---|---|
| Newow | `actual_dominant` | `1w / 1d / 60m` | 当前策略 typed BUILD/CLEAR 与 Hint | 策略、周期可改 |
| Trend 兼容 | `actual_dominant` | `1d` | Newow 趋势 typed Marker | 否 |
| HTDY | `actual_dominant / continuous / contract` | 七周期 | raw HTDY；仅 `actual_dominant` 可叠加 HTDY Event | 是 |
| SuBing | `actual_dominant` | `15m` | 仅 SuBing `AlertEvent` | 否 |
| Free | `actual_dominant / continuous / contract` | 七周期 | 无策略/Event Marker | 是 |

### 6.3 默认与切换

普通品种入口：

```text
view=newow
series_kind=actual_dominant
frequency=1d
strategy=trend
```

既有 `view=trend` 深链继续解析为固定 `actual_dominant + 1d + trend` 兼容入口。

HTDY Event 入口：

```text
view=htdy
series_kind=actual_dominant
frequency=event.frequency
focus_bar_end=event.bar_end
```

SuBing Event 入口：

```text
view=subing
series_kind=actual_dominant
frequency=15m
focus_bar_end=event.bar_end
```

视角切换：

- Newow 固定 `actual_dominant`，允许 `trend | oscillation | main_rise` 与 `1w | 1d | 60m`；
- Trend 兼容入口强制 `actual_dominant + 1d + trend`；
- SuBing 强制 `actual_dominant + 15m`；
- HTDY 与 Free 恢复各自最近一次安全的 `actual_dominant | continuous + frequency`；`contract` 仅存在于当前 route，不写入持久偏好；
- `contract` 只在当前品种内有效，切换品种必须清除并回到 `actual_dominant`；
- 切换 View、symbol、series、contract 或 frequency 时清空旧 viewport、Marker selection、history selection、disclosure transient state 和未完成请求。

### 6.4 非法 URL

非法组合不得静默修正：

```text
view=trend&frequency=15m
view=newow&series_kind=continuous
view=newow&frequency=15m
view=subing&series_kind=continuous
series_kind=contract 但 contract 缺失
未知 view/series/frequency
非法 symbol 或 focus_bar_end
```

页面显示明确错误和一个由 route parser 生成的规范化恢复动作；只有用户点击后才修改 URL。

---

## 7. 单一身份控制

一个页面只能存在一套 route identity 控制：

```text
品种
序列
指定合约
周期
```

`MarketDetailViewNav` 是 V1 的唯一可编辑 identity surface。Workspace 不得复制品种、序列、合约或周期控件。

固定 View：

- Trend 兼容入口只显示“固定日K”；
- SuBing 只显示“固定15m”。

灵活 View：

- Newow 使用共享品种/周期 identity 控制，并增加唯一策略选择；Workspace 不得再复制一套品种或周期控件；
- HTDY 与 Free 显示同一套序列/周期控件；
- contract 输入和按钮必须由共享 ViewNav 承担；
- Workspace 只显示本视角指标、解释和数据。

最终 Slice E 可以把品种输入升级为轻量选择器，但不得建立第二套控制。

---

## 8. 共享行情与数据读取

### 8.1 通用行情

共享行情头只消费当前 identity 的 generic Market 事实：

- latest completed/accepted Bar；
- previous Bar；
- OHLC；
- change/pct；
- volume；
- turnover；
- OI；
- physical contract；
- Market state；
- Canonical coverage；
- freshness。

`actual_dominant` 的头部合约必须来自最新 Bar 的 `physicalContract`；缺失或与 metadata 冲突时 fail-closed，不回退使用另一个合约。

### 8.2 请求隔离

每次 identity 或 visible-range 变化必须递增 generation。旧 generation 的：

- bars；
- research；
- Alert Event；
- Rule/Runtime；
- Newow detail；

均不得进入当前页面。

各 read authority 独立维护：

```text
generic Market
HTDY raw display
Alert Event
Alert Rule/Runtime
Newow detail
generic indicator
```

一个 authority 失败不得改写另一个 authority 的事实。

### 8.3 最后成功快照

V1 只在同一 identity 内允许保留最后成功快照，并必须明确标记 stale。切换 identity 后不得跨品种、跨周期或跨 View 复用旧快照。

首次加载失败且没有同 identity 快照时显示 unavailable。

---

## 9. Workspace 设计

### 9.1 Free

PR #327 是 Free 的实现基线。V1 继续冻结：

```text
三事实：当前序列 / 当前周期 / 数据状态
指标：EMA10 / EMA21 / EMA60 / Range Detector / Volume / MACD
Marker：始终为空
历史：无
```

Range Detector：

- 只读通用指标；
- 明确显示 warming/insufficient/error；
- 不使用“震荡策略、吸筹、目标价、建仓、清仓”等文案；
- 不进入 Alert 或其他 Workspace。

### 9.2 HTDY

#### 数据权威

```text
raw HTDY
  当前 bars 的浏览器展示镜像
  observation-only
  可能重绘
  不等于持久 Event

HTDY AlertEvent
  rule_code = htdy_original_15m
  forward-only first-seen
  创建后不可变
  来自 Alert API
```

两种事实必须并列，不得互相覆盖。

#### 三项直接事实

```text
当前原始观察
最近已保存事件
运行状态
```

“运行状态”只陈述 Rule/Scope/Runtime readback，不推导静默正常。

#### 图层

```text
Kline
HTDY ZK1 / ZD1 / ZD2
raw buy/sell observation markers
HTDY AlertEvent markers（仅 actual_dominant）
可选 EMA
可选 Range Detector
Volume
MACD
```

HTDY View 必须排除 SuBing Event 与 Newow Marker。

#### 历史与降级

- Event 列表与 Event Marker 必须来自同一内部 Event Map；
- raw 可用、Alert API 失败：保留 raw，Event 区显示不可用；
- raw 失败、Event 可用：保留 Event，raw 区显示不可用；
- Runtime degraded：保留既有事实并明确提示；
- 无 Event：显示“暂无已保存事件”，不能显示“中性”或“运行正常”。

### 9.3 Newow 与 Trend 兼容入口

本节以下固定 D1 读取、三事实、图层和降级合同只描述既有 `view=trend` 兼容入口。
`view=newow` 的三策略 × 三周期、Action/Hint、ReferenceTrade、乐观摘要、as-of、证据与重绘隔离，
以 `openspec/specs/newow-product-reference-trading/spec.md` 为准。兼容入口可由薄适配复用新服务，
但其公开 D1 请求与响应语义不得被删除或静默放宽。

#### 数据权威

唯一正式接口：

```text
GET /api/v1/market/newow/trend-detail
```

固定：

```text
product=current symbol
series_kind=actual_dominant
frequency=1d
from=当前已加载可见窗口最早 trading_day
through=当前已加载窗口最晚 trading_day
```

Web 必须严格验证：

```text
strategy_code
profile_id
series_kind
frequency
bar_policy
symbol/product
有序、唯一、timezone-aware bar_end
trading_day
physical_contract
OHLCV/OI
marker type
rollover seam
```

Newow bars 与 generic Market bars 在共同可见窗口内必须逐 Bar 对齐：

```text
bar_end
trading_day
physical contract
OHLCV
open_interest
```

不一致时隐藏全部 Newow 图层并显示 `NEWOW_DATA_IDENTITY_INVALID`，不能只绘制看似匹配的一部分。

向左加载扩展窗口时：

1. 先保留 generic bars；
2. 将旧 Newow overlay 标记为 loading，不把旧结果覆盖新窗口；
3. 请求新的完整可见窗口；
4. strict parity 通过后原子替换 overlay。

#### 三项直接事实

```text
周线背景
日线趋势
当前风险
```

- 周线背景来自 generic completed W1，只作人工 context，不进入 Newow Gate；
- 日线趋势来自 Newow 最新 trend band；
- 当前风险来自最新有效 D1/D2/D3；无风险时明确写“暂无 D1/D2/D3”。

杯柄不占首屏三事实，放在 disclosure、图层和历史中。

#### 图层

```text
Newow bars / Kline
黄蓝趋势带
BUILD / CLEAR
D1 / D2 / D3
杯柄 overlay 与 typed lifecycle marker
rollover seam
Volume
```

不得将 Newow 加入通用 `ResearchOverlayId`，不得用前端 EMA/Range 重算或补全。

#### 语义

用户文案优先使用：

```text
趋势建立观察
趋势延续
趋势转弱观察
暂无多头趋势
```

原始 `BUILD / HOLD / CLEAR / EMPTY` 在详情中保留。

蓝色带只表示“暂无多头趋势/风险阶段”，不表示建立期货空单。所有状态均为研究观察，不是账户持仓。

#### 降级

Newow API 失败或 identity mismatch 时：

- generic D1 Kline 可以继续显示；
- 黄蓝带、Newow Marker、杯柄和 Newow 历史全部隐藏；
- 不根据基础 Kline 猜趋势；
- 同 identity 最后成功快照可标 stale，但窗口扩大后不能伪装为覆盖新窗口。

### 9.4 SuBing

#### 固定身份

```text
rule_code = subing_ths_alert_15m_v1
formula_version = subing_ths_15m_v3
series_kind = actual_dominant
frequency = 15m
completed_only = true
```

#### 数据权威

正式方向只来自 SuBing `AlertEvent`：

```text
S↑ = Event result buy
S↓ = Event result sell
```

EMA21、MACD 和 Kline 只用于复核，浏览器不得从它们生成正式 Marker。

#### 三项直接事实

```text
最近预警
Rule 范围
Runtime 评估
```

Rule 范围必须分别表达：

- Rule 是否 enabled；
- 当前 symbol×15m 是否在 Scope；
- disabled + empty scope；
- API unavailable。

Runtime 评估必须使用 `rule_status[subing_ths_alert_15m_v1]` 的：

```text
last_evaluated_bar_at
last_event_at
last_failure_at
error_type
```

不能用全局 Alert heartbeat 冒充 SuBing 已评估。

#### 图层

```text
15m Kline
EMA21
SuBing Event-backed S↑ / S↓
Volume
MACD
```

排除 HTDY、Range、EMA10/60、Newow 和本地 synthetic signal。

#### 空状态与生产 Gate

- 无 Event：显示“暂无已保存预警”，不显示“中性”；
- Rule disabled、empty scope、Runtime unavailable 必须分别显示；
- 页面代码完成不表示 G10、G9、Runtime 或微信送达完成；
- V1 不渲染 Scope 写按钮。

---

## 10. Marker、历史与详情

### 10.1 Marker 白名单

```text
Free
  []

HTDY
  raw HTDY markers
  + HTDY AlertEvent markers

Trend
  Newow typed markers only

Newow
  当前策略 typed BUILD / CLEAR
  + 当前策略 Hint（与主动作分型）

SuBing
  SuBing AlertEvent markers only
```

Marker 不允许跨 View 残留。

### 10.2 稳定 identity

详情选择只能使用当前已渲染集合中的稳定 ID：

```text
Alert: alertEventIdentityKey
Newow: marker_id / candidate_id / rollover seam identity
raw HTDY: observation type + bar time
```

禁止解析 tooltip 文案恢复 identity。未知、过期、其他 View 的 ID 必须拒绝。

### 10.3 同源历史

同一 View 的图上 Marker、历史列表和详情抽屉必须来自同一个 normalized projection，不能分别请求后再靠文案关联。

### 10.4 focus

`focus_bar_end` 是一次性 route intent：

1. 当前 identity 和目标时间验证通过；
2. 必要时分页向左加载；
3. 图表 `revealTime()` 成功后移除 query；
4. 定位后退出 follow-latest；
5. 定位失败保留 intent，并在下一次 bars 扩展后重试；
6. identity 改变时清除旧 intent。

D1/W1 使用 trading day 定位，日内使用 exact timestamp 定位。

---

## 11. 页面信息顺序

桌面与移动端保持相同语义顺序：

```text
Top Bar
Quote Header
View Tabs
Identity Controls
Semantic Banner
Three Direct Facts
Insight / Evidence Disclosures
Main Chart
History / Indicator Explanation / Data Details
```

要求：

- 一个 View 首屏只出现该 View 的事实；
- 设置项不能压过语义提示和三事实；
- 第一块关键 disclosure 默认展开，其余按当前共享组件合同；
- 桌面允许多开，移动端单开；
- 错误、stale、warming 在折叠标题可见；
- 不恢复常驻右侧工程检查栏。

---

## 12. 响应式与无障碍

最低要求：

- 390px、1280×800、1440×900、1920 宽度均可用；
- 视角和周期可横向滚动；
- 交互目标不小于 44×44 CSS px；
- icon-only 按钮具有中文 `aria-label`；
- 状态不能只依赖颜色；
- 中国期货红涨绿跌，同时配文字/箭头/形状；
- Tab 使用 `role=tab`、`aria-selected` 和键盘操作；
- Disclosure 使用 `aria-expanded`、`aria-controls`、Enter/Space；
- Drawer 有 focus trap、Esc 关闭和关闭后焦点恢复；
- 支持 `prefers-reduced-motion`；
- 图表可通过旁边的文字事实和历史访问关键含义。

牛哇页面只作为信息节奏参考；SVG、CSS、Logo、截图切片和品牌资产不得复制。

---

## 13. Final Cutover

Slice E 只有在 B2、D、C 全部进入 `develop` 后启动。

必须完成：

1. 普通首页品种入口默认进入 Newow 趋势日线；既有 `view=trend` 深链继续进入 D1 兼容入口；
2. HTDY/SuBing Event 深链进入对应 View 和 Bar；
3. 品种选择不再返回 Legacy；
4. 删除 `LegacyMarketChart.vue` 及 active references；
5. 删除“返回旧版详情”等临时入口；
6. 四个 View 都是真实 Workspace，不保留空 Tab；
7. 更新 active OpenSpec；
8. 更新 `PROJECT_SOURCE.md` 与 `DECISIONS.md` 的稳定产品面；
9. `STATUS.md` 只在真实 release/Runtime/Scope/evidence 发生变化时另行更新，本 Slice 不提前修改；
10. 完整视觉、键盘、无障碍、typed contract 和 fail-closed 验收。

---

## 14. 禁止范围

V1 剩余实现禁止：

- 自动交易、订单、账户、持仓、保证金或 PnL；
- 模糊的全历史策略效果、账户收益、复利净值、年化、组合收益或将 ReferenceTrade 称为成交/持仓；
- 在 Newow accepted contract 之外新增综合分、胜率、置信度、策略投票、建议仓位、目标价、吸筹价或系统止损价；
- 在 Newow accepted contract 之外恢复震荡策略、主升浪、主力照妖镜或 AI 分析假入口；
- 将 OI 解释为主力身份；
- 将蓝色趋势带解释为期货空单；
- 新增 Newow Alert/Runtime；
- 修改 SuBing、HTDY 或 Newow 公式；
- 在 Web 复制正式公式；
- 新 DB 表、migration、Redis key、queue、worker；
- Scope mutation；
- production RQData、Canonical、PostgreSQL、Redis、Runtime 或通知；
- `main`、tag、Release；
- 恢复已退役 Attention、Trend Focus、Main Force Mirror、N Structure 或旧苏冰策略。

---

## 15. 验收合同

V1 `CODE_COMPLETE` 至少要求：

1. Free、HTDY、Newow、SuBing 四个 Workspace 全部真实挂载，`view=trend` D1 兼容入口仍可用；
2. 只有一套 identity 控制；
3. Free Marker 恒为 0；
4. HTDY raw 与 immutable Event 并列且同源历史；
5. `view=trend` 固定 D1 兼容入口继续只消费 Newow API，strict parity 失败时不绘制；
6. `view=newow` 的三策略 × 三周期只消费 typed Newow API，Action、Hint、ReferenceTrade、统计与证据状态不串身份；
7. SuBing Marker 只来自 Event；
8. Rule、Scope、Runtime、Event 空状态分别呈现；
9. Event 深链定位准确并一次性消费；
10. contract 不跨品种延续；
11. Workspace 切换不串 Marker、viewport、history 或 disclosure；
12. Legacy 与 active references 删除；
13. unit、Playwright、build、OpenSpec、canonical consistency、secret scan 和 diff check 通过；
14. exact-head 独立 Review 无 Critical/Important finding；
15. 用户完成关键桌面与移动端视觉审查。

必须分别声明：

```text
CODE_COMPLETE
TEST_COMPLETE
EXTERNAL_GATE_PENDING
RELEASED
RUNTIME_READY
```

任何一项不得由另一项替代。

---

## 16. 冻结决策摘要

```text
V1 顺序 = B1 → B2 → D → C → E
B3 Alert Scope Control 不属于 V1
Trend 兼容入口先于 SuBing，因为既有 Newow D1 API 已就绪且完全只读
Newow 新产品由 accepted OpenSpec 接管三策略 × 三周期、参考交易与解释
四视角共享 Shell，但不共享公式权威
周线背景只作 Trend context，不成为隐藏 Gate
杯柄不占 Trend 首屏三事实
HTDY Event 只在 actual_dominant 展示
SuBing 始终 Event-only
Free 始终无策略/Event Marker
Final Cutover 前不删除 Legacy
V1.1/V2 必须另开独立 Spec，不从本设计直接扩展
```
