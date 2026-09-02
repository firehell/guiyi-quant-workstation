# Market 首页牛哇式全景盯盘重构 Spec

状态：`SPEC_APPROVED_VISUAL / FACTUAL_REVISION_APPROVED`

日期：2026-09-02

Issue：`#300`、`#302`

原设计 PR：`#301`

事实修订基线：`develop@8f39539d07ccea6577d1bcc2244dce0ad715f37e`

设计 ID：`market_home_niuwah_reference_v2`

任务车道：`Lane 2 / Product-and-read-model design`

## 1. 文档职责

本文件冻结归一量化 `/market` 首页下一版产品、交互、视觉与只读数据合同。用户已经批准整体视觉，并进一步明确：图标部分必须高保真参考牛哇首页及牛哇手册中的视觉效果。

最终闭环固定为：

```text
打开首页
→ 先确认 Runtime 与市场快照是否可信
→ 用牛哇式有限图标快速浏览 completed D1/W1 与周期同向状态
→ 查看当前 HTDY 正式观察 Event
→ 点击品种进入 /market/chart
→ 用户人工判断
```

首页是研究工作站，不是下单面；所有图标、数值与 Event 只陈述已有事实，`auto_order=false`。

## 2. 事实修订

原 Spec 规划时仍存在 SuBing Daily Watch、Strategy Action、旧 Market Radar Web 面等能力。该 Spec 合入后，`develop` 已完成新的产品收敛：

- `/market` 当前只展示 Runtime；
- active 通用能力只有 EMA、MACD、ATR、Range Detector；
- active 研究观察和 Alert 产品只有 HTDY；
- 既有策略域、Daily Watch、Strategy Action、Episode、Performance、旧策略 Runtime/API/Web/cache 均退出 active 产品面；
- 未来不得直接恢复旧模块或旧身份。

因此，下列旧设计内容失效：

```text
默认苏冰观察图层
Daily Watch 多头/空头/趋势不明确
SuBing Formal Event
Strategy Action 焦点流
旧 Market Radar 组件直接复活
Issue #286 boundary ledger 作为首页依赖
```

实现者不得从 Git history 复制这些退役模块。首页必须基于当前 active generic Market facts、HTDY Event 与 Runtime 建立最小只读投影。

## 3. 当前 active 产品边界

稳定 Web route 只有：

```text
/market
/market/chart
```

首页允许消费：

1. `active_products.txt` 定义的研究 universe；
2. `MarketDataService` 读取的 `actual_dominant + completed D1/W1`；
3. `ResearchMetrics` 已有通用字段；
4. Runtime health 只读响应；
5. HTDY immutable `AlertEvent` 只读响应；
6. 品种 taxonomy、主力映射和现有图表 route。

首页不得消费或创建：退役策略能力、账户/订单/真实仓位、目标价/止损价、AI 综合分、自动交易路径、浏览器端指标重算或每品种一个 HTTP 请求的 N+1 页面。

## 4. 产品目标

首页必须在十秒内回答：

```text
一、Runtime 和数据快照是否可信？
二、哪些板块整体偏强或偏弱？
三、每个品种最近完整交易日的日线、周线状态是什么？
四、日线与周线是否同向？
五、当前是否出现需要打开图表复核的 HTDY 正式 Event？
```

量化目标：

- 当前约 60 个 active 品种全部可达，无分页；
- 59/60/61/90 个品种均能正确布局，60 不是永久常量；
- 桌面默认牛哇式紧凑表格；
- 任一品种一次点击进入 `/market/chart`；
- 浏览器全页请求数量为常数，不随品种数增长；
- stale/partial/unavailable/degraded 显式；
- 日线、周线状态不翻译为买入、持有、卖出或空仓；
- 无 HTDY Event 只表示“暂无正式观察 Event”，不证明 Runtime 正常静默。

## 5. 牛哇视觉参考边界

必须高保真参考：

- 顶部横向板块涨跌胶囊；
- “简单看图标”帮助条；
- 四个高识别度圆形状态图标；
- 价格、涨跌幅、日、周、趋势的固定列节奏；
- 极浅行分隔线、浅色数值胶囊、紧凑连续大列表；
- 非交易时段/数据时点灰色状态条；
- 小型趋势箭头；
- 表头与行内容稳定对齐。

不得复制牛哇 Logo、名称、版权图片、私有 CSS/源码、“买入/持股/卖出/空仓”业务结论、私有目标价、股票行业 taxonomy 或私有策略公式。实现使用本项目自己的 inline SVG 与 CSS。

## 6. 牛哇式图标视觉合同

### 6.1 颜色

```css
--gy-market-icon-up: #E63935;
--gy-market-icon-aligned: #FF9601;
--gy-market-icon-down: #35C759;
--gy-market-icon-neutral: #017AFF;
--gy-market-icon-unavailable: #98A2B3;

--gy-market-pill-up-soft: #FFE9E6;
--gy-market-pill-down-soft: #E9F9EB;
--gy-market-pill-aligned-soft: #FFF2E5;
--gy-market-pill-neutral-soft: #EAF1FF;
```

这些 token 只服务 Market 首页，不修改图表和全局方向色。

### 6.2 尺寸

| 使用位置 | 外圆直径 | SVG viewBox | 主 glyph |
|---|---:|---|---:|
| 图例 | 40px | `0 0 24 24` | 14–16px |
| 表格日/周/同向 | 28px | `0 0 24 24` | 11–13px |
| 趋势/HTDY 微图标 | 24px | `0 0 24 24` | 10–12px |

共同规则：完整圆、无阴影、glyph 纯白、勾/叉圆角端点、图标视觉居中，表格图标间距 10–12px，图例间距 14–16px。

### 6.3 SVG 几何

统一由 `MarketStateIcon.vue` inline 绘制。

上行：

```svg
<path d="M12 6.5 19 17.5H5Z" fill="currentColor" />
```

周期同向：

```svg
<path d="M6.5 12.3 10.2 16 17.8 8.3" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
```

下行：

```svg
<path d="M5 6.5h14L12 17.5Z" fill="currentColor" />
```

中性：

```svg
<path d="m7.2 7.2 9.6 9.6m0-9.6-9.6 9.6" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
```

数据不足：

```svg
<circle cx="12" cy="12" r="2.2" fill="currentColor" />
```

### 6.4 小趋势图标

24px 浅色圆底：

```svg
<path d="M6 15.5 10 11.5 13 13.5 18 8.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
<path d="M14.5 8.5H18v3.5" fill="none" stroke="currentColor" stroke-width="2" />
```

下行垂直镜像。上涨红线 + `#FFE9E6`，下跌绿线 + `#E9F9EB`。

### 6.5 事实语义

| 视觉 | 页面名称 | 唯一输入事实 | 禁止解释 |
|---|---|---|---|
| 红色上三角 | 上行 | D1/W1 trend = up | 买入、开多 |
| 橙色勾 | 周期同向 | D1 与 W1 同为 up 或同为 down | 持股、持仓 |
| 绿色下三角 | 下行 | D1/W1 trend = down | 卖出、开空 |
| 蓝色叉 | 中性 | D1/W1 trend = neutral | 空仓 |
| 灰色圆点 | 数据不足 | unavailable/stale | 无机会 |
| 红/绿趋势线 | 同向方向 | D1/W1 同向方向 | 趋势将持续 |

帮助条标题固定：`周期状态 · 简单看图标`。

副文案固定：`红色上行、橙色同向、绿色下行、蓝色中性；仅表示已完成周期事实。`

## 7. 首页信息架构

```text
A. 页面标题与刷新
B. 板块涨跌 ticker
C. 周期状态图例
D. 可信状态条
E. 四项摘要
F. 筛选和排序工具条
G. 牛哇式全市场表格
H. HTDY 焦点 Event 栏
I. 板块宽度与涨跌/OI 排行
```

不新增第二个首页 route，不建立 Dashboard Builder。

## 8. 响应式布局

1440px+：主表 + 288–320px 焦点栏，表头 sticky，日/周/同向/HTDY 必须可见。

1200–1439px：焦点栏 270–288px，可隐藏 5D/ATR 非核心列。

768–1199px：焦点栏移到表格上方，表格自身横向滚动，首列品种 sticky。

<768px：顺序固定为可信状态 → HTDY Event → 搜索筛选 → 品种卡列表；卡片保留价格、1D、日、周、同向、HTDY；图标仍为 28px。

## 9. 板块 ticker

使用 sector summary 的 `median_price_change_1d`：正值红字、负值绿字、null 为 `—`；点击只改变本地筛选。顺序来自 response，不在 Web 另建 taxonomy。

## 10. 可信状态条

必须分别表达：`target_as_of/data_as_of`、`participant_count/active_count`、stale/unavailable 数量、Runtime health、HTDY Event endpoint ready/unavailable/stale、是否为上一次成功快照。

固定关键文案：

```text
非实时行情 · 最近完整交易日收盘快照截至 YYYY-MM-DD
```

禁止把 D1 close 写为实时价格、失败后置零、Runtime degraded 显示正常、Event empty 写成系统已完整评估无信号。

## 11. 四项摘要

1. 上涨/下跌/平盘；
2. 日线上行/下行/中性/数据不足；
3. 日周同向偏多/偏空；
4. 当前 HTDY Event 数与最新时间。

摘要点击只改变本地筛选，不改变 Scope。

## 12. 主表格合同

桌面默认列：

```text
品种 | 板块 | 收盘 | 1D | 5D | 量比 | OI | 日 | 周 | 同向 | HTDY | 数据
```

`收盘` 是 latest completed D1 close，不称实时价；目标价列永久不存在，直到未来有 accepted authority。

## 13. 周期同向规则

复用已有通用展示语义：

```text
D1 up + W1 up           → 同向偏多
D1 down + W1 down       → 同向偏空
D1 neutral + W1 neutral → 中性
任一 unavailable        → 数据不足
其他组合                → 未同向
```

同向偏多：橙勾 + 红趋势微图标；同向偏空：橙勾 + 绿趋势微图标；中性：蓝叉；未同向：描边或文字，不使用实心橙勾；数据不足：灰点。

该规则只做 Web 展示组合，不是策略、Alert 或正式指标，不保存、不产生 Event、不影响 Scope。

## 14. HTDY 表达

首页只认当前交易日 persisted HTDY `AlertEvent`。显示 exact rule code、symbol、frequency、result、bar_end、detected_at、notification attempted time。Retrospective repaint arrow 不进入首页 current Event 列。

- buy：浅红底 + 红上行微图标，`HTDY 买观察`；
- sell：浅绿底 + 绿下行微图标，`HTDY 卖观察`；
- 双向：`HTDY 双向观察`，不得替用户决定方向；
- 无 Event：`—`；
- endpoint unavailable：灰点 + `Event 不可用`。

不得写建仓、清仓、持仓、应买、应卖、已送达。`notification_attempted_at` 只表示 transport 已尝试。

## 15. Market Home bulk 只读合同

新增：

```text
GET /api/v1/market/research/home-overview
```

Response 必须包含：status、target/data as-of、freshness、active/participant、stale/unavailable、summary、items、sector summary。Item 包含 symbol/name/sector/exchange/actual contract/dominant mapping date/data_as_of/close/1D/5D/volume ratio/OI change/ATR percentile/daily trend/weekly trend/reason codes。

Authority 固定：

- universe：`load_active_products()`；
- taxonomy：`load_product_taxonomy()`；
- target date：`DatabaseCoverageSource.latest_complete_day(active_products)`；
- Bars：`MarketDataService`；
- series：`actual_dominant`；
- frequency：D1 + W1；
- metrics：`calculate_research_metrics`；
- dominant identity：`list_latest_dominants()`。

一致性：同一 response 统一 `data_as_of`；D1 缺失/未到 data_as_of 不伪造 item；weekly 不足允许 item 但 weekly trend unavailable；participant 等于 items 数；symbol 不重复；taxonomy mismatch fail-closed；null 不变成 0；response 不含策略状态。

浏览器只调用一次 bulk endpoint。后端每品种最多一次 D1 + 一次 W1 query，只调用一次 dominants；不连接 provider、Redis，不写 cache/DB。开发机 warm filesystem 目标 `<1.5s`，cold `<3s`。

## 16. HTDY 全局 current Event 合同

新增：

```text
GET /api/alerts/current-events?limit=30
```

规则：current trading day 仍由现有 resolver；只查询 active HTDY Rule；只返回精确 trading day Event；排序 `detected_at DESC, bar_end DESC, id DESC`；limit 1..100；unavailable 返回 typed unavailable，不伪空 ready；不修改 Event 写入、Rule、Scope、transport，不增加 Alert 表。

## 17. Web ViewModel

只做 exact symbol join 和展示组合：daily/weekly/alignment/latest HTDY/row health。Duplicate symbol 或 Event identity 冲突 fail-closed；stale/unavailable 优先于彩色状态；不计算 EMA/MACD/HTDY，不根据 Event 推断 D1/W1，不根据 Scope 推断 Event，不根据无 Event 推断 normal silence。

## 18. 网络与刷新

页面常量请求：

```text
1 × home overview
1 × runtime health
1 × current HTDY events
```

首次并行；overview 手动/页面重新可见刷新；Runtime + Event 页面可见时每 60 秒刷新；隐藏时停止 timer；每个资源保留上一成功快照并单独标 stale；同资源不得并发重复请求；不新增 WebSocket，不做 per-row polling。

## 19. 搜索、筛选和排序

浏览器本地完成。搜索支持 symbol 和中文名；不新增拼音库。筛选 sector、日线、周线、同向、有无 HTDY、数据异常。排序 canonical 默认、1D 涨/跌、量比、OI、最新 Event。筛选不得改变任何 authority 或 Scope。

## 20. Deep link

品种点击沿用 `/market/chart`，`series_kind=actual_dominant`。HTDY Event 进入相同 chart + event frequency + `overlay=htdy`；若 chart 暂不支持 event 精确定位，只允许增加只读 route intent，不修改 HTDY 公式或 Event。

## 21. Loading、partial、错误

首次加载使用分区 skeleton，不全屏 spinner。Overview degraded 保留异常行，摘要写清参与数；overview failure 保留旧快照并标失败，无旧快照显示 typed error，不显示全 0。Runtime degraded 不阻断历史表但必须显著。Event empty：`当前交易日暂无 HTDY 正式观察 Event`。Event unavailable：`HTDY 当前 Event 暂不可用；不能据此判断本时段无观察。`

## 22. 本地偏好

版本化 key：`guiyi.market-home.preferences.v1`。只保存 sector filter、sort、compact density、详情默认 frequency、focus rail collapsed。解析失败回默认，不写生产 DB。

## 23. 无障碍

每图标有中文 aria-label 与 sr-only 文本；不以颜色为唯一信息；键盘可聚焦行，Enter 打开详情；focus ring 使用现有 token；低动态关闭 hover 位移；表格有 caption/scope/column header。

## 24. 测试合同

后端必须覆盖：59/60/61、统一 data_as_of、D1 stale/unavailable、W1 不足、taxonomy/dominant identity、null、summary、sector median、HTDY current sorting/limit/unavailable、退役 Rule 排除。

Web 必须覆盖：icon state→color/glyph/label、精确 palette、D1/W1 alignment、duplicate fail-closed、stale/unavailable priority、HTDY join、empty vs unavailable、search/filter/sort、route、preference、59/60/61、null formatting。

E2E 视口：1920×1080、1440×900、1280×800、390×844；覆盖 all ready、overview degraded、Runtime degraded、Event empty/unavailable、cached stale、筛选、deep link、keyboard、mobile order、无 page overflow、request count constant。

视觉 snapshot 必须包含：40px 图例、28px 五状态、24px 趋势图标、1440 全页、390 手机。允许差异仅限字体抗锯齿；图标背景色、尺寸、圆度、glyph path 必须稳定。

## 25. 实施范围

允许修改 Market Home 相关只读后端、API/schema、Web 首页组件/API/types/utils/tests/E2E，以及对应 OpenSpec 与 active canonical。禁止修改 quant-core 公式、HTDY kernel/evaluator/Event creation、Rule/Scope/audience/transport、Alembic、生产 PostgreSQL/Redis、Canonical、RQData、main/tag/Release/Runtime、退役策略文件；`/market/chart` 仅允许必要的只读 route intent。

## 26. Gate

Plan 批准后允许创建源码 task branch/worktree。源码完成必须经过：

```text
CODE_COMPLETE
→ TEST_COMPLETE
→ 独立 Review
→ 用户批准集成 develop
```

合入 `develop` 不等于 main/tag、Release、Runtime promotion 或任何真实写入授权。

## 27. Review 修正记录

已关闭：旧 SuBing/Daily Watch/Strategy Action/#286 ledger 依赖、旧 Radar 直接复活、图标交易语义越权、目标价、D1 冒充实时、HTDY empty/unavailable 混淆、active/operational 混淆、浏览器 N+1、60 硬编码、全局图表色污染、Web 指标重算、过度 Dashboard 架构，以及提前修改 STATUS。

## 28. 冻结结论

首页采用：

```text
板块 ticker
→ 简单看图标
→ 可信状态条
→ 紧凑全市场表
→ HTDY 焦点 Event
```

四个核心图标在几何、颜色、尺寸与排列上高保真参考用户提供的牛哇视觉；业务语义严格映射为上行、周期同向、下行、中性，并增加 fail-closed 的数据不足状态。首页事实只来自 current active generic Market、HTDY 与 Runtime，不恢复任何退役策略，不产生交易建议，最终决定始终由用户完成。
