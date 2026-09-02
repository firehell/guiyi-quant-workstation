# Market 首页牛哇式全景盯盘重构 Spec

状态：`SPEC_READY_FOR_USER_REVIEW`

日期：2026-09-01

Issue：`#300`

规划基线：`develop@8ff992100dba7b2a6ad1007ab0d782d03da5b424`

设计 ID：`market_home_niuwah_reference_v1`

任务车道：`Lane 2 / Design-only`

## 1. 文档职责

本文件冻结归一量化 `/market` 首页的下一版产品、交互、视觉和只读数据合同。

这不是给现有页面换皮，而是把首页重构为真正用于个人日常盯盘的全景工作台：

```text
打开首页
→ 先确认系统和数据是否可信
→ 立即看到是否有正式事件
→ 一眼扫完今天的苏冰观察方向
→ 一眼扫完 60 个品种的日线价格 / OI 结构
→ 点击品种进入图表，由用户决定是否行动
```

本 Spec 只定义设计，不实现页面，不修改 active canonical，不授权 `main`、tag、Release、Runtime、生产数据库、Scope、真实通知或数据写入。

## 2. 事实来源与参考置信度

设计按以下顺序取事实：

1. `STATUS.md`：当前 release、Runtime、Scope 与 pending Gate；
2. `AGENTS.md`：工程授权和不可破坏边界；
3. `PROJECT_SOURCE.md`：稳定产品面；
4. 当前 `develop` 的 `/market`、组件、类型与 HTTP client；
5. Issue #286 已批准的 Alert 可靠性与苏冰盯盘合同；
6. 用户指定的当前归一首页与牛哇首页；
7. 《牛哇财经操盘手册 2026》公开可见页面。

本次执行环境无法直接连接两个裸 IP 页面，因此不能声称已完成像素级在线测量。设计以仓库真实实现、手册中的首页语言和用户明确要求为依据；实施验收必须在可访问真实页面的浏览器中补做并列截图和尺寸对照。该限制不允许实现者凭印象改变本 Spec 的产品边界。

“完全参考牛哇首页”在本任务中定义为：

- 高保真参考其简单看盘、状态先行、全列表扫描、黄蓝状态、提醒优先和单击复核的产品语法；
- 不复制牛哇 Logo、吉祥物、图片、文案资产、私有 CSS、目标价算法或专有策略公式；
- 不把牛哇的买卖、仓位和目标价结论冒充归一量化事实。

## 3. 当前事实基线

归一量化是本地、单用户的国内期货研究工作站，稳定闭环为：

```text
可信行情 → Market Web → 研究观察 → Alert → 人工判断
```

所有页面、信号和通知均为研究观察，`auto_order=false`。稳定 Web route 仍只有：

```text
/market
/market/chart
```

规划时的当前事实：

- Market Radar 研究 universe 来自 `active_products.txt`，当前 60 个品种；
- Market Runtime universe 来自 `operational_products.txt`，当前也是 60 个品种；
- 两者当前内容相同，但 authority 永久不同，不得合并；
- 当前 Runtime 为 degraded，不能显示为 `RUNTIME_READY`；
- HTDY 与 SuBing 的 Rule、Scope、Event 和 audience authority 分离；
- Alert reliability / `subing_watch_15m_v1` 由 Issue #286 负责，本设计不得复制其公式或账本。

当前 `/market` 已有：

- `MarketRuntimeStatus`；
- `SubingWorkbench`；
- `MarketSummaryStrip`；
- `MarketScatter`；
- `MarketDetailTable`；
- 正确的 `/market/chart` deep link。

## 4. 当前首页的问题

当前页面以纵向卡片堆叠为主：

```text
标题
→ Runtime 四卡
→ 苏冰大工作台
→ 默认折叠的全市场研究
```

由此产生五个直接问题：

1. 首屏先看到组件，不是“现在要不要处理”；
2. 60 个品种不能一次形成视觉全貌；
3. Runtime、Daily Watch、Formal Event 与 Radar 缺少统一入口，但又不能混成一个总分；
4. 全市场研究默认折叠，违背首页作为盯盘入口的职责；
5. 移动端需要滚过多个大卡片后才能进入核心内容。

## 5. 设计目标

首页必须在十秒内回答四个问题：

```text
一、系统现在可信吗？
二、现在有必须打开图表复核的正式事件吗？
三、今天哪些品种属于多头观察、空头观察或趋势不明确？
四、全市场价格、持仓量、成交量和板块结构是什么样？
```

量化目标：

- 60 个 active 品种无分页完整可达；
- 任一品种最多一次点击进入图表；
- 首屏可见正式事件数量、Daily Watch 方向数量和 Radar 完整度；
- 不制造综合评分、仓位建议或目标价；
- 任何 stale、partial、unavailable、degraded 均显式可见；
- 1440×900 桌面宽度下，核心矩阵在一次短滚动内完整扫完；
- 390px 移动宽度下，正式事件优先于全市场矩阵。

## 6. 非目标与禁止范围

本设计明确不做：

- 自动交易、订单、账户、真实持仓、资金或仓位管理；
- AI 预测、综合买卖分、目标价、止损价或收益承诺；
- 修改苏冰、HTDY、Newow 或任何策略/指标公式；
- 在 TypeScript 中重算 EMA、MACD、Daily Watch、Alert 或 Radar 规则；
- 新建第二套 Market 数据源、第二个首页 route 或通用 Dashboard 框架；
- 每个品种单独发起 HTTP 请求；
- 修改 Alert Rule、Scope、audience、PushPlus、production PostgreSQL/Redis；
- 修改 `STATUS.md` 声称 release、Runtime 或自然 evidence 已完成；
- 因页面设计触碰 `main`、tag、Release 或 Runtime。

## 7. 从牛哇首页提取的设计语法

采用以下产品语法：

1. **简单看盘、一目了然**：核心状态直接铺开，不藏在二级页面；
2. **有限状态降低理解成本**：黄、蓝、灰、异常四类状态必须同时配文字；
3. **大列表可连续扫描**：品种名、状态和核心数值位置固定；
4. **提醒代替持续盯盘**：事件列表独立、时间清楚、点击直达图表；
5. **多周期背景可见**：归一量化映射为 Daily Watch 的 D1 / 60m 背景，不把 60m 写成周线；
6. **状态变化比解释文本更突出**：颜色、图标、方向和更新时间优先，技术详情后置。

不采用：

- 牛哇的“买入、持有、卖出、空仓”作为归一首页结论；
- 大盘与个股共振后的仓位百分比；
- 私有目标价；
- 自动交易入口；
- 未公开公式形成的趋势阶段或买卖点。

期货不存在本项目已冻结的单一“大盘指数” authority，因此牛哇的“大盘 + 个股”结构在归一量化中改写为：

```text
全市场宽度 / 板块结构
+
单品种观察状态
```

不合成“全市场买入”或“全市场空仓”。

## 8. 首页产品结构

首页固定为五层：

```text
A. 页面工具栏
B. 可信状态条
C. 四项摘要
D. 60 品种全景矩阵 + 焦点事件栏
E. 全市场结构与明细
```

页面不再使用“展开全市场研究”的默认折叠。Scatter、排行榜、板块和明细仍在首页，但位于主矩阵之后。

## 9. 四个事实图层

全景矩阵提供四个可切换图层：

```text
行情涨跌 · 日线快照
苏冰观察
正式事件
数据状态
```

同一时刻只允许一个图层控制品种卡片的主背景、主标签和排序。其他事实只能作为小徽标存在，不能混合生成“综合状态”。

默认图层：`苏冰观察`。用户选择保存到本地 preference；来源不可用时仍停留在该图层并显示不可用，不静默回退到其他事实。

## 10. Authority 分离合同

| 页面事实 | 唯一 authority | universe / 分母 | 允许展示 | 禁止推导 |
|---|---|---|---|---|
| 行情涨跌 | Market Radar | `active_products.txt` | 最近完整交易日日涨跌、5日变化、量/OI/ATR事实 | 实时行情、买卖方向 |
| 苏冰观察 | Daily Watch published snapshot | snapshot `counts.universe` | 多头观察、空头观察、趋势不明确、不可用 | 正式 Event、下单建议 |
| 正式事件 | AlertEvent 只读投影 | Rule / Scope / current trading day | exact Rule、result、bar_end、detected_at | Candidate、送达、持仓 |
| 数据状态 | Radar freshness + Runtime health | 各自 authority 的 expected set | current/stale/unavailable/degraded | “无信号”等于“系统正常” |
| Alert 边界完整性 | Issue #286 boundary ledger | Session-aware expected set | expected/evaluated/no-signal/candidate/failure | 固定 60/60 |
| Alert Scope | Rule Scope | product 或 product×frequency | 是否在通知授权范围 | Runtime 是否已评估 |

硬规则：

- active 60、operational 60、Daily Watch universe、boundary expected set 和 Alert Scope 即使数字相同，也必须带名称展示；
- `participant_count < active_count` 只表示 Radar 部分参与，不允许把缺失品种当作涨跌 0；
- Event 列表为空只能写“暂无正式事件”；
- 只有 #286 的 finalized boundary 满足严格合同，才允许写“本边界正常静默”；
- provider accepted 不等于微信送达。

## 11. 桌面端线框

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 期货盯盘  [苏冰观察][行情日线][正式事件][数据状态]  搜索  板块  刷新      │
├──────────────────────────────────────────────────────────────────────────┤
│ 数据截至 08-31 │ Radar 60/60 │ Market Runtime 降级 │ Alert 边界状态      │
├──────────────────────────────────────────────────────────────────────────┤
│ 正式事件 2 │ 多头观察 9 │ 空头观察 7 │ 数据完整 60/60                 │
├──────────────────────────────────────────────┬───────────────────────────┤
│                                              │ 焦点栏                    │
│  60 品种紧凑矩阵                             │ 1. 最新正式事件           │
│  8~10 列，自适应，无分页                     │ 2. 数据/Runtime 异常       │
│  点击任一卡片进入图表                        │ 3. 今日观察摘要            │
│                                              │ 固定宽度、随主区滚动       │
├──────────────────────────────────────────────┴───────────────────────────┤
│ 价格×OI 四象限 │ 涨跌/放量/增仓排行榜 │ 板块宽度                         │
├──────────────────────────────────────────────────────────────────────────┤
│ 全市场明细表                                                             │
└──────────────────────────────────────────────────────────────────────────┘
```

1920px：主矩阵 10 列，焦点栏约 320px。
1440px：主矩阵 8 列，焦点栏约 288px。
1200px 以下：焦点栏移到矩阵上方，不压缩卡片至不可读。

## 12. 页面工具栏

固定内容：

- 标题：`期货盯盘`；
- 副标题：`60 品种全景 · 研究观察 · 人工判断`，其中 60 来自响应，不硬编码；
- 四图层 segmented control；
- 品种搜索；
- 板块筛选；
- `全部刷新`；
- 数据时点与“研究观察，不自动下单”边界。

搜索与板块筛选只影响矩阵和明细表，不修改 Scope，不触发服务端写入。清空筛选恢复完整 active universe。

## 13. 可信状态条

状态条是单行紧凑 strip，不再使用四个同权大卡片。固定展示：

1. Radar `data_as_of` 与 freshness；
2. `participant_count / active_count`；
3. Market Runtime 总状态；
4. Alert Runtime / boundary 状态；
5. 最近刷新时间。

优先级：

```text
error / unavailable > degraded / stale > warming / pending > ready
```

状态颜色使用语义色，不使用涨跌红绿。任何 degraded 必须有简短原因和“查看详情”入口；详情复用现有只读 Runtime 信息，不创建修复按钮。

## 14. 四项摘要

摘要固定为：

- `正式事件`：当前只读 Event 数；
- `多头观察`：Daily Watch `long_watch`；
- `空头观察`：Daily Watch `short_watch`；
- `数据完整`：Radar `participant_count / active_count`。

摘要卡可点击切换对应图层或过滤矩阵，但不能改变 Scope。无数据时显示 `—` 和状态原因，不显示 0 伪装正常。

## 15. 60 品种全景矩阵

### 15.1 容量策略

当前只有 60 个品种，因此首页直接铺满全部 active universe：

- 无分页；
- 无虚拟的“热门前十”替代；
- CSS Grid 使用 `repeat(auto-fit, minmax(104px, 1fr))`；
- 卡片高度 68~78px；
- 默认按 `sector_order → symbol` 稳定排序；
- 搜索、板块、状态和异常可组合过滤；
- 切图层不改变同一品种的稳定位置，除非用户显式选择“按当前状态排序”。

`60` 只是当前事实，不是接口常量。59、61 或其他合法数量必须正常布局。

### 15.2 卡片永久内容

每张卡固定保留：

- 中文名；
- symbol；
- 当前主力合约（已有可信全局投影时显示，否则不为卡片单独请求）；
- 板块短标签；
- 数据异常小徽标；
- 正式 Event 小徽标。

主区域随图层变化。所有颜色必须配文字或图标，不能只靠色差表达。

## 16. 各图层卡片合同

### 16.1 行情涨跌 · 日线快照

主区域：

```text
日涨跌幅
5 日涨跌幅（次要）
量比 / OI 变化二选一的上下文徽标
```

红涨绿跌遵循国内期货约定；null 显示 `—`，不按 0 处理。顶部持续显示 `data_as_of`，明确这是最近完整交易日快照，不是实时价格。

### 16.2 苏冰观察

状态固定为：

```text
黄色：多头观察
蓝色：空头观察
灰色：趋势不明确 / 未进入观察池
斜纹警示：数据不可用
```

黄色和蓝色只表示 Daily Watch 研究观察，卡片必须写出“多头观察”或“空头观察”，不得写“买入/卖出”。

当前 Web snapshot 公开 `long_watch[] / short_watch[] / unavailable[]`，但没有逐品种 `excluded[]`。V1 采用最小合同：

- 当 `counts.universe`、三类公开列表、`counts.excluded` 与 Radar active identity 可严格对账时，集合补集显示为“趋势不明确”；
- 补集只显示中性结论，不伪造 D1/60m 价格侧、斜率或 reason；
- 任一计数、交易日、symbol 或 universe 不一致时，图层标记 `partial`，不得推断；
- 若未来必须显示全部 excluded 的 D1/60m 细节，另开最小只读 projection 任务，不在前端重算。

### 16.3 正式事件

主区域显示当前品种最近一条当前交易日 Event：

- exact Rule display name；
- exact result / action；
- frequency；
- `bar_end`；
- Event 数量徽标。

同品种多条 Event 时显示最近一条并标 `+N`。点击卡片以 Event identity 进入图表。没有 Event 显示“暂无正式事件”，不显示“无信号”或“正常静默”。

Candidate、Event、transport attempt、provider acceptance 和微信送达不得合并成一个“已提醒”。

### 16.4 数据状态

状态固定为：

```text
当前完整
盘后待更新
部分参与
stale
unavailable
Runtime degraded
```

Radar 的全局 degraded 不得无条件把所有品种染成红色；只有 response 提供的 per-product stale/unavailable identity 才标到具体卡片。全局错误放在可信状态条。

## 17. 焦点栏

焦点栏用于“现在需要处理什么”，优先级固定：

1. 最新正式 Event；
2. 数据 / Runtime 明确异常；
3. 今日苏冰观察摘要；
4. 没有以上内容时显示边界清楚的空态。

每条 Event 显示：

```text
品种 + 合约
Rule + result
bar_end / detected_at
打开图表
```

不提供“已读、忽略、下单、自动执行”按钮。V1 不新建用户处理状态域。

## 18. 全市场结构区

主矩阵之后保留并重排现有研究：

1. `价格 × OI 四象限`；
2. 排行榜：日涨幅、日跌幅、放量、增仓、高波动；
3. 板块宽度：参与数、上涨数、下跌数、日涨跌中位数；
4. 全市场明细表。

排行榜只对 `participant_count` 内有效 item 排序。null、stale、unavailable 不得进入数值排序尾部伪装为最低值。

明细表列：

```text
品种 / 主力合约 / 板块 / 日涨跌 / 5日涨跌 / 20日位置
量比 / OI日变 / ATR分位 / 数据状态 / 当前观察徽标 / 当前事件徽标
```

不增加目标价列，因为项目当前没有权威目标价事实。

## 19. Deep link 与交互

点击来源决定 chart query：

- Radar / 数据卡：保留当前 preference frequency，`series_kind=actual_dominant`；
- Daily Watch：`frequency=15m&overlay=subing&entry=subing-daily-watch`；
- SuBing Formal Event：使用其 exact entry / action identity；
- HTDY Event：使用 exact symbol、frequency、overlay 和 Event identity；
- 不从页面展示文案反推路由参数。

返回首页时恢复：

- 图层；
- 搜索与板块筛选；
- 矩阵滚动位置；
- 明细排序；
- 不恢复已过期 Event 内容，数据仍以新响应为准。

## 20. 视觉规范

### 20.1 视觉方向

高保真参考牛哇的紫色品牌条、黄蓝状态和密集列表，但使用归一量化现有 token 体系：

- Shell：现有深海军蓝；
- 页面强调：新增语义别名 `--gy-watch-purple`，取深靛紫，不直接复制源站 CSS；
- 多头观察：暖黄；
- 空头观察：深蓝；
- 趋势不明确：中性灰；
- 涨跌：`--gy-up / --gy-down`；
- 系统状态：`--gy-status-*`，与方向色隔离。

### 20.2 密度

- 页面内容最大宽度不设窄居中容器，充分使用工作站屏幕；
- 主间距 12px，卡片间距 6~8px；
- 品种中文名 13px / 600；symbol 11px mono；主状态 12px；
- 避免大面积渐变、玻璃效果、强阴影和装饰动画；
- hover 只提升边框和轻阴影，不改变状态色。

### 20.3 状态可读性

每个方向或状态必须至少同时有两种表达：

```text
颜色 + 文字
颜色 + 图标
文字 + 边框样式
```

黄色不得单独等于“买入”，蓝色不得单独等于“卖出”。

## 21. Shell 调整

仅 `/market` 允许采用更紧凑的侧栏初始状态，目标是把宽度让给 60 品种矩阵：

- 1440px 以下默认 64px collapsed；
- 用户手动展开后保持用户选择；
- `/market/chart` 不因本任务改变现有侧栏、图表宽度或工具栏；
- 若 route-specific shell 会导致复制 layout 或大范围回归，保留当前 shell，紧凑侧栏不作为阻塞项。

## 22. 响应式设计

### 22.1 宽桌面 ≥ 1600px

- 矩阵 9~10 列；
- 焦点栏右侧 sticky；
- 四项摘要单行；
- 四象限、排行榜、板块并排。

### 22.2 1200~1599px

- 矩阵 7~8 列；
- 焦点栏 280~300px；
- 结构区 2 列；
- 明细表横向滚动。

### 22.3 760~1199px

- 焦点栏移到矩阵上方；
- 矩阵 4~6 列；
- 工具栏分两行；
- 摘要 2×2。

### 22.4 < 760px

移动端顺序固定为：

```text
可信状态
→ 正式事件
→ Daily Watch 摘要
→ 图层切换
→ 2 列品种卡
→ 排行榜
→ 明细入口
```

移动端不先渲染大 Scatter。Scatter 放入“市场结构”折叠区，但正式事件和 60 品种矩阵不折叠。

## 23. API 与读模型

### 23.1 优先复用

复用现有全局接口：

```text
GET /market/research/radar
GET /market/research/subing-daily-watch/current
GET /market/dominants
GET /api/runtime/* health
GET /api/alerts/strategy-actions/current
```

页面刷新最多并行调用一组全局资源。禁止为 60 个品种逐个请求 product research、current events 或 state。

### 23.2 Formal Event 全局读模型

若 Issue #286 实现后仍没有可供首页使用的全局 Event 列表，新增 Alert Domain 的最小只读投影：

```text
GET /api/alerts/current-events
```

有限字段：

```text
status
trading_day
items <= 50
  event_id
  rule_code
  display_name
  kind
  symbol
  product_name
  frequency
  result
  bar_end
  detected_at
  contract
  chart_entry
```

该接口只读取 immutable Event，不返回 token、Topic、provider reference、文件路径或原始异常，不组合 Radar/Daily Watch，不成为 mega endpoint。

### 23.3 #286 依赖

Boundary completeness、normal silence、Watch Candidate 和新 Rule lineage 完全服从 #286。首页只消费其公开 read model：

- 不复制 formula；
- 不从 heartbeat 推断业务完成；
- expected denominator 来自 Session authority；
- status 缺失或 TTL 过期显示 `unobserved`；
- Shadow Candidate 不冒充 Formal Event。

## 24. 请求、刷新与性能

- 初次加载并行读取全局资源；
- 页面重新可见时仅刷新 operational state 和 Event / boundary；
- Radar 与 Daily Watch 按其事实时点刷新，不进行秒级轮询；
- 同一资源使用 single-flight，旧请求通过 AbortController 取消或丢弃；
- 保留上一份成功数据时必须显示 stale；
- 切图层只做本地投影，不重新请求；
- 60 卡片不需要虚拟滚动；
- 不引入新状态管理框架或图表库。

性能验收：

- 60 卡片切图层无明显布局跳动；
- 网络面板不存在 O(N) 请求；
- 首页无持续高频 timer；
- 1440px 下首屏不因 Scatter 初始化阻塞矩阵交互；
- 数据量扩展到 90 个卡片仍保持功能正确，性能结论以实测记录为准。

## 25. Loading、空态与故障合同

### 25.1 首次 loading

- 先渲染页面骨架和工具栏；
- 摘要与矩阵使用固定尺寸 skeleton；
- 不显示伪造的 0；
- 某资源完成即可独立呈现，不等待全部资源。

### 25.2 Radar 失败

- 有旧快照：保留旧矩阵并标 stale；
- 无旧快照：矩阵显示不可用，Runtime/Event 区仍可用；
- 不把 Daily Watch 列表当成 active universe 替代品。

### 25.3 Daily Watch 失败

- 苏冰图层显示 unavailable；
- Radar、Event 和数据状态继续工作；
- 不回退到旧交易日并隐藏时点。

### 25.4 Event 失败

- 显示“正式事件读取失败”；
- 不显示“暂无正式事件”；
- 不影响 Radar 和 Daily Watch。

### 25.5 Boundary status 缺失

- 显示“边界状态未观测 / 已过期”；
- 不显示正常静默；
- 不以 Alert heartbeat 替代。

### 25.6 Partial identity

任何跨资源 join 必须使用规范化 symbol 和明确 trading day。交易日不一致时：

- 各块保留自己的事实时点；
- 顶部标记 partial；
- 不合成统一“当前状态”。

## 26. 前端组件边界

建议最小组件树：

```text
pages/market/index.vue                 只编排资源和路由
MarketWatchToolbar.vue                工具栏 / 图层 / 筛选
MarketTrustStrip.vue                  freshness / Runtime / boundary
MarketWatchSummary.vue                四项摘要
MarketUniverseGrid.vue                60 品种矩阵
MarketUniverseTile.vue                单卡纯展示
MarketFocusRail.vue                   Event / 异常 / 观察摘要
MarketStructureSection.vue            Scatter / 排行 / 板块
MarketDetailTable.vue                 复用并扩展
```

纯投影函数放在 `utils/marketHomeProjection.ts`：

- join identities；
- Daily Watch complement 验证；
- 当前图层 tile view model；
- 稳定排序；
- route intent。

函数不得计算策略公式。避免把每个小区域拆成独立 fetch 组件，避免新增通用 dashboard schema。

## 27. 测试合同

### 27.1 纯函数 / Unit

必须覆盖：

- 60、59、61、90 个品种布局数据；
- symbol join 与重复 identity fail-closed；
- Daily Watch complement 对账成功；
- count、交易日、symbol 不一致时不推断 excluded；
- null 数值不当作 0；
- 事件最近一条与 `+N`；
- 无 Event 文案不是 normal silence；
- active / operational / boundary / Scope 标签分离；
- stale/unavailable 优先级；
- 各入口 query 精确；
- preference migration；
- 筛选不改变 Scope。

### 27.2 组件测试

必须覆盖：

- 四图层切换；
- 默认苏冰图层 unavailable 不静默回退；
- 正式 Event、数据异常和 Daily Watch 徽标；
- skeleton 尺寸稳定；
- keyboard focus；
- aria label 包含中文状态；
- 颜色之外存在文字；
- focus rail 不重复生成业务事实。

### 27.3 E2E

必须覆盖：

```text
1440×900 desktop
1280×800 compact desktop
390×844 mobile
```

场景：

1. 全部资源 ready；
2. Radar degraded + partial participants；
3. Runtime degraded；
4. Daily Watch unavailable；
5. Event endpoint empty；
6. Event endpoint failure；
7. boundary normal silence；
8. boundary incomplete / expired；
9. 60 品种搜索和板块筛选；
10. Daily Watch / SuBing Event / HTDY Event deep link；
11. 返回首页恢复状态；
12. 网络请求数量不是按品种增长。

### 27.4 构建与回归

实现必须运行当前仓库正式命令：

- Web unit；
- Market Playwright；
- Web build；
- 涉及 read-only API 时运行对应后端 tests、Ruff、Mypy；
- OpenSpec / canonical 引用检查；
- secret scan；
- diff check。

不得因为首页重构删除现有 chart、SuBing、HTDY、Runtime 或 Radar 回归测试。

## 28. 视觉并列验收

实现完成后，必须用真实浏览器对以下页面进行并列验收：

```text
参考页：牛哇首页
目标页：归一量化 /market
```

截图尺寸：1920×1080、1440×900、390×844。审查：

- 信息密度与“一眼扫完”是否达到参考页目的；
- 黄蓝状态是否同样直接，但语义没有越权；
- 列表/矩阵中的品种、状态、数值是否对齐稳定；
- 提醒是否比研究图表更先被看见；
- 归一量化的可信状态是否比参考页更清楚；
- 60 品种是否无需分页完整可达；
- 是否误复制品牌资产或私有结论。

像素不要求完全相同；产品骨架、视觉优先级和扫描体验必须高保真。

## 29. 实施拆分

### Task A：页面骨架与现有事实投影

- 仅使用现有 Radar、Daily Watch、Runtime、Strategy Action；
- 实现工具栏、可信条、摘要、60 品种矩阵和焦点栏；
- 复用 Scatter / Detail；
- 不新增后端接口。

### Task B：正式 Event 全局读投影

- 前置：#286 的 Rule / Event / boundary Web 合同已经进入最新 `develop`；
- 先审计是否已有全局 Event endpoint；
- 缺失时只添加最小只读 Alert endpoint；
- 不修改 Event 写入、Rule、Scope、migration、transport。

### Task C：响应式、性能与无障碍

- 完成三个断点；
- O(1) 全局请求验证；
- keyboard / aria / contrast；
- screenshot E2E。

### Task D：真实页面并列 Review 与收口

- 在可访问两个真实 URL 的环境运行；
- 只修视觉层级和交互偏差；
- 不借 UI Review 修改策略或 Alert 语义；
- 完成独立 Review 后才允许集成 `develop`。

每个 Task 使用独立 branch/worktree，默认从执行时最新 `develop` 创建。普通 Lane 2 满足测试和 Review 后可以按仓库流程集成 `develop`；不得触碰 `main`、tag、Runtime 或真实写入。

## 30. 提交前 Review 记录

本 Spec 提交前按产品、事实、范围、实现和验收五类反向审查，并完成以下修正：

1. **买卖语义越权**：黄蓝改为“多头观察 / 空头观察”，不写买入卖出；
2. **把 60 写死**：所有数量改从 authority 响应读取；
3. **把 Event 为空写成正常**：固定为“暂无正式事件”；
4. **把 heartbeat 当完成**：normal silence 只认 #286 finalized boundary；
5. **混淆 active 与 operational**：分母和标签完全分开；
6. **混淆 Scope 与 evaluation**：Scope 只表达通知授权；
7. **Radar 冒充实时**：图层名称和时点明确为日线快照；
8. **缺少 excluded 明细却伪造周期事实**：只允许严格补集得出中性状态；
9. **复制牛哇目标价**：因无 authority 删除目标价列；
10. **合成期货“大盘状态”**：改为市场宽度与板块结构；
11. **每品种请求风暴**：冻结为全局读模型，禁止 O(N) 请求；
12. **Formal Event 与 Candidate 混合**：焦点栏和图层只认 immutable Event；
13. **Runtime degraded 被漂亮 UI 掩盖**：可信状态条置于首屏；
14. **全市场研究继续折叠**：取消桌面默认折叠；
15. **移动端图表先于事件**：改成 event-first 顺序；
16. **过度组件化**：冻结最小组件树，不引入 dashboard 框架；
17. **与 #286 并行冲突**：Task B 明确等待其公共合同进入 `develop`；
18. **Shell 改动扩大到 chart**：route-specific compact 是可选，chart 非回归；
19. **声称已像素审查真实 URL**：明确当前访问限制并加入强制并列验收。

Review 结论：未发现需要扩大到 Lane 3 的页面设计变更；所有策略、Alert 写入、Scope、Runtime、release 和生产操作继续保持 Gate。

## 31. 验收标准

### 产品验收

- `/market` 首屏依次回答可信状态、正式 Event、苏冰今日观察和全市场结构；
- active universe 全量卡片可达，无分页；
- 默认苏冰图层使用黄/蓝/灰/异常有限状态并配文字；
- Event、Daily Watch、Radar、Runtime 与 Scope 不合成综合状态；
- 无权威目标价、仓位、止损或自动交易入口；
- 任一卡片一次点击到正确图表上下文。

### 事实验收

- Radar 时点、participation 和缺失显式；
- Daily Watch 补集只有严格对账后可显示；
- Event empty / failed / unavailable 文案不同；
- normal silence 只来自 #286 权威账本；
- active / operational / boundary / Scope 分母都带语义；
- Runtime degraded 不得显示绿色完成态。

### 工程验收

- 无 O(N) 请求；
- unit、E2E、build 及必要后端检查通过；
- 现有 chart / SuBing / HTDY / Runtime 能力不回归；
- 无生产写入、通知、Scope、main、tag、Release 或 Runtime 操作；
- 独立 Review 无 Critical / Important 未解决项；
- 用户批准后才进入 Implementation Plan 或实现。

## 32. Gate 与冻结结论

当前只达到：

```text
SPEC_READY_FOR_USER_REVIEW
```

用户明确批准本 Spec 后，下一步才是：

```text
允许编写 Implementation Plan
```

本 Spec 的批准不等于：

```text
允许实现
允许集成 develop
允许发布 main/tag
允许 Runtime promotion
允许生产写入
允许真实通知
```

冻结结论：

> 首页采用牛哇式“简单看盘、有限状态、全列表扫描、提醒优先”的高保真产品语法；结合归一量化只有 60 个期货品种，使用无分页全景矩阵和焦点事件栏；同时严格保留 Market Radar、Daily Watch、Formal Event、Runtime、Boundary 与 Scope 的事实边界，最终交易决定始终由用户完成。
