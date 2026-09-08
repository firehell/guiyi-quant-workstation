# Newow 桌面工作站 Engineering Spec V1

> 当前实现入口为 [白色 V2 设计](2026-09-07-newow-detail-light-design.md) 与 [实施计划](2026-09-07-newow-detail-light-implementation-plan.md)。它们替代本文深色/右栏/底部解释 tab/参考宽表；MACD 内核复用、身份、时间与证据边界继续按未冲突部分约束，不将本历史设计视作实现完成记录。

日期：2026-09-07
阶段：Stage 5；文档设计与自审，不执行产品代码。
读取基线：`98a834d9674c51117d911f5c9df0c9f2cc5dce7a`（develop）。
上游输入：[视觉基线与交互规格 V1.1](2026-09-07-newow-desktop-visual-interaction.md)。
状态：`ENGINEERING_DESIGN / SELF_REVIEWED_FOR_TASK_PLANNING`。

> 用户已批准交互基线，唯一修订为周期继续显示 `1w / 1d / 60m` 等原始键；并授权编写、自审、修正文档后提交 develop。本文是后续实现的设计输入，不表示新增接口、组件、MACD 接入、浏览器视觉或真实运行验收已完成。未修改 active OpenSpec 业务合同；需要的新协议扩展须在实现任务中同步相应 spec、schema、reader 和测试。

## 1. 目标、范围与优先级

在现有 Market 中实现个人、本地优先、单用户的期货研究桌面：无左侧常驻功能栏，无账户/成员管理，无股票式全市场搜索。以行情、策略事实、主副图、参考交易组成连续阅读路径，保留批准的深色、橙色激活和局部半透明层次。

本轮设计覆盖公共 Shell、牛哇三个策略的展示架构、单副图区默认 MACD、中文提示别名、上下文切换、精确定位、错误状态、桌面尺寸适配及测试合同。HTDY、苏冰、Free 只复用必要外观与导航，业务消费者保持隔离。市场首页仅保留入口与既有资源合同，不借此改造成新首页。

不新增研究笔记、回测复盘产品、AI 助手、评分引擎、仓位模型、账户收益、订单、自动交易、通知管理或移动端专项。不删除现有自由看盘、参考交易、综合解释、合法合约控制或兼容测试。

优先级：active canonical 的业务不变量 > 用户明确的范围/显示要求 > 本交互基线 > 本工程细节 > 概念图中的演示文字与数字。产生业务冲突须停止对应实现，不以设计图修订策略公式。相关 authority 为 [PROJECT_SOURCE](../../PROJECT_SOURCE.md)、[AGENTS](../../AGENTS.md)、[DECISIONS](../../DECISIONS.md)、[Newow OpenSpec](../../openspec/specs/newow-product-reference-trading/spec.md)。

## 2. 当前实现与设计增量

以下“当前”仅指读取基线的源码，不是现场 Runtime 观测。

| 已核对当前事实 | 设计增量，不冒充已有能力 |
|---|---|
| Web 为 Vue；package 声明 lightweight-charts `^5.2.0`，不是已核对安装的精确版本 | 沿用仓库锁文件与现有图表库，不换框架、不升级依赖 |
| 详情 route 为 `/market/chart`，Newow/HTDY/SuBing/Free 已分视角 | 调整 Shell 与控件布局，不创建四套应用或新 URL 协议 |
| 新工作台位于 `components/market/detail/newow/` | 不使用 Stage 1 缺少 `newow/` 的旧路径作为实现依据 |
| `NewowProductBar` 已含 volume、open_interest、completed、physical_contract、segment_id | 成交量直接来自当前 chart 响应，无须另拉一份行情 |
| 新工作台辅助项只有主力控盘、涨跌动能、照妖镜；API 还支持杯柄 | 展示选择位增加 MACD；杯柄保持主图结构能力，不占副图 tab |
| 通用 `macd_series` 已有显式 seed、柱倍数、round_digits 与版本 | 后端薄适配接入，不在浏览器重算，也不改通用内核 |
| 旧 `NewowTrendChartStage.vue` 已有同 chart 多 pane、volume、primitive、hover、全屏 | 借鉴绘制及资源释放结构，不能整段搬入其固定 D1 的时间转换和数据装配 |
| `useNewowProduct` 已有 generation、按 section 取消、快照兼容、LRU、分页边界 | 保留并扩展现有 lifecycle；不另建一套并行 store |
| 照妖镜内核多组幅值与状态输出不等于原站正负柱映射已核验 | 图形角色与符号映射独立审查；不能把 MACD 换标题，也不能随意取负 |

完整源路径与核对范围见第 18 节。历史源码可提供候选绘制方式，不改变现役版本、P6 状态或任何外部 Gate。

## 3. 架构选择与组件边界

采用“现有详情页 + 新工作台内聚绘制 + 一个 chart 的多 pane”。相比整页重写，此方案保留 typed consumer；相比主副图分离 chart/SVG，减少时间索引、resize、crosshair 的重复同步。无需新增状态框架、图表引擎或通用可配置 Dashboard。

| 落点 | 职责与限制 |
|---|---|
| `MarketDetailPage.vue`、现有 TopBar/QuoteHeader/ViewNav | 页面布局、品种入口、视角/策略/频率选择；不计算指标，不拥有通知权限 |
| `NewowProductWorkspace.vue` | 组合 chart、单副图、解释、参考表；维护纯界面选择，调用现有 loader |
| `NewowProductChartStage.vue` | 一个 IChartApi；主价格 pane、volume pane、一个 active auxiliary pane；统一 time/hover/resize/生命周期 |
| `newowProductChartPrimitives.ts` | 只做展示投影、段内几何、标记 hit-test、坐标转换；不得配对交易、推导买卖或重新算线 |
| `useNewowProduct.ts` 与 API/type guard | 请求、取消、快照、分页、资源状态；保留单一 authority |
| `NewowReferencePanel.vue` / `NewowExplanationPanel.vue` | 原有参考窗口、精确定位、来源/缺证据；重排展示，不改统计或解释公式 |
| 拟新增 `newowDisplayLabels.ts` | 周期原始键、策略名称、Action/Hint 别名；不改变 wire identity |
| 拟新增 `newowAuxiliaryRenderProfiles.ts` | 按 component/series key 定义颜色、线/柱/标记、独立尺度及证据状态；不用数组索引轮转配色 |
| 现有 `styles/chartTheme.ts` + 拟新增 `newow-workstation.css` | 局部 CSS tokens 与图表显式取色；主题作用于工作站根节点，不改变首页或其他应用全局默认 |
| 拟新增 API 层 `market_data/newow/product_display_indicators.py` | 复用通用 MACD 内核的无写入薄适配；不是新的策略 authority |

拟新增文件路径是建议落点，不是已存在文件。实施可按依赖内聚调整文件名，但不得改变职责或绕开现有契约。公共 Shell 不复制 HTDY、苏冰公式，也不把独立视角合成“综合交易信号”。

## 4. 导航、品种与周期显示

### Requirement ENG-01: 原始频率键

所有可见的周期按钮、摘要、表格、图例、tooltip 与来源周期 MUST 保留 `1w / 1d / 60m` 形式。Newow 仅这三个；苏冰为 `15m（固定）`；HTDY 为 `1m / 5m / 15m / 30m / 60m / 1d / 1w`；Free 使用现有允许集合。不得改为日K/日线/周线/1小时/1h，不新增 4h、月线或分时。解释层可附中文含义。时间轴上的实际日期/时刻仍按现有上海时区工具显示。

D1–D6 是独立 Hint 身份，按上游中文别名显示，详情保留编号。周期 `1d` 与风险 D1 不得共用格式化函数或键值转换。

### Requirement ENG-02: 小品种集合与路由

“市场”回 `/market`；“牛哇 / 火天大有 / 苏冰预警”切既有详情视角；“自由看盘”放在清晰的视角菜单中。保留路由解析与 `resolveViewSwitchIdentity` 的合法恢复规则，不在按钮里拼不完整身份。新 URL、深链、back/forward 与旧 `view=trend` 固定 D1 兼容入口均须回归。

品种面板复用既有 bulk 目录/元数据：优先复用已加载资源，详情直接进入时最多一次 `/api/v1/market/dominants` 目录读取，按既有 taxonomy 分组。该接口返回集合及可用性仍以服务端为准，不用缺失主力映射自行淘汰或加入品种。UI 不硬编码 60、具体合约或常用品种名单；快捷条取目录既有顺序的前若干项，当前品种保持可见，不新增收藏持久化产品。

active 与 operational 的语义不合并；目录展示不授予 Runtime Scope。期货主选择键为 product，物理合约由当前/hover Bar 或现有映射显示；Newow 固定 actual_dominant，HTDY/Free 的合法合约控制继续可达。

面板有中文名/代码、分组、当前项、键盘焦点、Esc 返回；不新增全市场证券搜索和六十路轮询。空、读取失败、无映射与无主动作分别处理。

## 5. 布局与视觉 token

以下为归一工程默认值，服务已批准视觉方向；不是从牛哇在线页面提取的精确 CSS，也不是已通过浏览器校准的 golden。

### 5.1 布局

主校准为 1440×900 CSS px，复核 1920×1080、1280×800 和 1024×768；DPR=1 为回归基线，DPR=2 补充图形清晰度。浏览器/字体/缩放固定。原图 1672×941 仅为图片像素，不能充当浏览器 viewport。

页面只保留一层 12px 外边距，主栏与右栏 gap=12px。≥1200px 使用 `minmax(0,1fr)` 主栏与 320px 右栏；≥1600px 右栏 360px；更窄时右栏内容按原序进入主图区及记录区域下方，不恢复左侧功能栏。顶栏基准48px、品种条40px、行情条72px、图表工具条36px；文字变长允许合理增高，不裁断错误提示。

图表绘图区高度默认 `clamp(500px, calc(100dvh - 290px), 760px)`，三个 pane 的 stretch 约 64:12:24。最小可读目标：价格280px、成交量64px、副图112px；不足时页面纵向滚动，不能通过压成不可读高度强塞首屏。底部参考表保持明确入口并可纵向延展，不虚构“任何屏幕都一屏展示全部”。

右栏：当前策略事实 → 综合解释摘要/展开 → 已有合法参考价 → 简化只读状态。无证据的数值不占固定虚假位置；缺证据本身在摘要可见。底部：参考交易 / 策略解释，日期统计窗独立于图表 viewport。

### 5.2 色值与透明度

| Token（局部前缀 `--gy-newow-`） | 工程默认值 | 使用 |
|---|---|---|
| `canvas` | `#07131F` | 页面与图表连续底 |
| `surface` | `rgba(14,29,43,0.94)` | 局部面板，不对父节点设置 opacity |
| `surface-solid` | `#0E1D2B` | 不支持透明效果时的稳定底 |
| `text` | `#E5E9EF` | 正文 |
| `text-secondary` | `#A9B7C8` | 次级信息 |
| `text-muted` | `#8395AA` | 辅助信息；关键错误不降到此层 |
| `accent` | `#FF6B35` | 当前策略和核心激活 |
| `accent-soft` | `rgba(255,107,53,0.18)` | 周期/次级激活底 |
| `hover` | `rgba(255,255,255,0.08)` | 未激活 hover |
| `border` | `rgba(138,169,196,0.20)` | 1px 分隔 |
| `grid` | `rgba(138,169,196,0.10)` | 图内低对比网格 |
| `up` / `down` | `#FF453A` / `#30D17E` | 红涨绿跌，不能代替 Action 文义 |
| `yellow-line` / `blue-line` | `#F5B942` / `#3A91FF` | 现有趋势状态对应绘制 |
| `yellow-fill` / `blue-fill` | `rgba(245,185,66,0.20)` / `rgba(58,145,255,0.20)` | 段内趋势填充 |
| `tooltip` | `rgba(9,21,34,0.96)` | 独立文字层全不透明 |
| `focus` | `#9BC9FF` | 2px focus-visible，与 selected 可共存 |
| `warning` / `error` | `#F5B942` / `#FF6B6B` | 文字加图形，不只靠颜色 |

激活控件若用橙实底，正文用深色 `#07131F`；不用低对比橙底白小字。控件默认不发光，激活可用局部 `0 0 10px rgba(255,107,53,0.16)`；不做整屏霓虹扫光、频繁动画或大面积 backdrop-filter。半透明层验收按与实际背景合成后的颜色，而非只比较源 RGBA。深色 tooltip 必须有清晰边界且不泄漏下一层无关数据。

正文14px、次级12px、价格30px、品种名20px；数字 `tabular-nums`，不是全页等宽字体。4/6/8/12/16px 间距，控件圆角4px、面板6px。图标视觉16/18px、桌面可操作盒最小32px；既有移动兼容不减小其触控面积。悬停/焦点/选中/禁用分开，禁用项有原因而非仅透明化。

Canvas 不读取 CSS `opacity` 继承；`resolveChartTheme` 显式解析根 token，传给 candle/grid/axis/primitive。普通线1px、主要策略线2px、十字线1px虚线；所有参数集中，不在各组件复制常量。浏览器样本如需显著偏离此视觉方向，回到视觉审查，不借 CSS “校准”增加业务功能。

## 6. 主图与时间模型

### Requirement ENG-03: 单一行情身份

主图、成交量、Action/Hint 使用同一 chart 响应；每一绘制对象保留 `bar_end + physical_contract + segment_id`。`1d/1w` 的显示时间从 `trading_day` 构建，`60m` 从 bar_end 构建；保留反向映射到原始时间与物理身份。不得把实际日期简单当业务主键、跨时区重复转换或直接复用旧 D1 的 dayTime 处理所有频率。

主副图共享同一 chart 时间索引；纵轴分别计算。辅助响应可含主图窗口外的完整计算前缀，投影只能映射主图已存在的时间键；不让副图多出的历史时间扩展主图时间轴。先验证每个 segment 数组长度/次序/唯一性，再按 bar_ends 对齐，不能用压缩后的数组序号对齐。

价格/收益字符串保留给展示与身份核对；仅坐标绘制允许转有限 Number，不以 Number 计算参考收益、可成交价或配对关系。小数位遵循已核验合约元数据；字段不足不能猜 tick 或对锚点偷偷吸附。格式化可四舍五入展示但不改原始参考价格，详情可查原值。

### Requirement ENG-04: 图形不是新公式

趋势使用服务器 page-v2 A/B 与已有状态；在同物理段内填充有效相邻点间区域，不把快线/慢线硬改成上下通道，不用效果图 MA20/MA60 替代。震荡使用自身 upper/lower，主升浪使用自身 MA35/MA45；所有线型/颜色映射跟随实际 main_values 键校验，不读不适用字段补线。

缺值、warming、合约/segment 边界与数据无效处断开线/填充。非交易时段的连续显示由现有时间模型处理；不能将正常休市误判缺失或在换月跳价间画平滑桥。合约边界用细虚线和可查物理身份说明，不新增交易动作。

杯柄仍仅 trend×1d 的既有 clean-room witness 展示；不是第五个副图，不补提前已知的 pivot，不放入订单或参考收益。已有不适用/证据不足仍按原字段显示。

成交量直接读取 `NewowProductBar.volume`，颜色随同 Bar 的 close/open，零为真实零、缺失为缺失；open_interest 独立。图中不添加不存在的成交量 MA，也不把本周期量柱误称 D1 总量。行情摘要沿用现有 quote authority 与时间标签，不以 hover 或 Newow 当前频率替换“最新行情”。

## 7. MACD 接入：Q01 的工程收敛

### 7.1 接入选择

采用既有 `GET /api/v1/market/newow/strategy-detail` 的 `section=auxiliary&component=macd` 扩展。相比并行通用指标请求，这条路径复用现有 product identity、as_of、snapshot proof 与 segment reader，避免两次读取的版本拼接。此 enum 分支当前不存在，是明确的未来接口增量；不新开路由，不改变 section 列表，不把 MACD 注册为第四个策略。

扩展点为 API Query enum、`AuxiliaryComponent`、响应 schema、serializer、前端 `NewowAuxiliaryComponent/NewowAuxiliaryData`、type guard、loader 缓存键及 render profile。不能只在 Vue 加一个 tab 就声称完成。新增分支由服务层薄适配调用通用内核，原三副图及 cup_handle 分支不改算法。

### 7.2 数学来源与前缀

唯一计算来源为 `packages/quant-core/guiyi_quant/indicators/macd.py::macd_series`，参数沿用其 Web 显示口径：fast=12、slow=26、signal=9、ema_seed_policy=`sma_window`、histogram_scale=2、round_digits=6。保留内核实际版本（当前源码 `v1-draft`）与 `parameters_hash`，不得以本次 UI 审批把它重命名为正式新公式版本。

输入使用 `ProductReadSet.replay_bars` 的同 frequency、completed、as_of 以内、同物理生命周期前缀；分别按 physical_contract/segment 重置状态，再按图表时间范围裁剪输出。固定种子起点采用现有 Newow 同物理生命周期前缀，不承诺与其他采用不同起点的通用图表逐值一致；比较 golden 必须使用相同前缀。不能在当前屏幕500根上重新 seed；扩大显示范围不能改变相同快照中重叠 Bar 的 MACD。warm-up-only 输入可用于正确种子，但只有匹配 chart 的 Bar 可见；缺合法前缀时明确 warming/unavailable，不下载行情补齐，不借邻合约。

DIF 可先 ready，DEA/柱尚 warming。按每点 `ready / valid / value / reason` 保留状态；值为0是有效值，不用真假判断丢弃；非法值与预热缺值不画成零。MACD 图形不触发 SuBing Event，也不添加零轴/量能/斜率过滤。

### 7.3 拟新增 payload 合同

沿用 Newow auxiliary envelope：meta.identity/as_of/snapshot_token、component、segments、status、formula_version、repainting、formal_signal_eligible、page_parity、allowed_uses。每段 data 采用明确的 MACD discriminated shape：

| 字段 | 设计要求 |
|---|---|
| `component` | `macd`；客户端只接受显式白名单 |
| `formula_version` | 原内核 MACD_VERSION；不是 Newow 三策略 formula_versions 的追加项 |
| `display_adapter_version` | 新展示适配身份 `guiyi_newow_macd_display_v1`；与内核版本分开 |
| `parameters` / `parameters_hash` | 上述显式参数与内核生成 hash |
| `segments[].physical_contract / segment_id / bar_ends` | 复用现有段 envelope；严格升序，所有数组长度一致 |
| `segments[].data.dif / dea / histogram` | 每项一条 IndicatorPoint 序列；bar_end 与外层索引相等，value 可 null，ready/valid/reason 不丢失 |
| `repainting / formal_signal_eligible / page_parity` | false / false / false；非重绘不等于正式交易信号，未证明牛哇 MACD 精确 page parity |
| `allowed_uses` | 只允许研究显示；不得传给主动作、参考收益或 Alert |

数据类型应在 serializer、Python schema、TypeScript 与测试 fixture 中同批定义。新字段仅属于 macd 分支；旧响应 shape 不被追溯改写。frontend 面对旧服务端不支持时只显示“MACD 展示接口不可用”，不静默切指标或回落浏览器算法。此次不更换既有顶层 `newow_product_detail_v1`，前提是旧组合响应仍保持兼容；兼容性无法满足则停止该实现任务重新审查协议，而非静默改版。

服务缓存的 component 分支加入 adapter_version、parameters_hash，完整返回值/证明/索引占用继续计入已有预算。共用 snapshot namespace 不修改三策略身份；不因副图增加使 Action ID、ReferenceTrade ID、reference model version 或 futures adaptation version 改变。

## 8. 副图绘制与证据 Gate

### Requirement ENG-05: 单选择位

工作台首次进入/身份切换默认选择 MACD；重复点击当前项不关闭。按 chart 成功后取得的同身份快照和明确 chart_from/chart_through 请求 active auxiliary。切换其他项取消该 section 旧请求并校验 generation；未选中的副图不预加载。自动读取按 identity generation、selected component、接受的 chart 范围及兼容快照共同去重；同一响应的重新渲染不再次发请求，单 section 不存在两个当前请求。参考/解释窗口变化不重新选择副图。成交量常驻但不占副图选择位。

辅助历史数据必须覆盖主图已加载的显示时间范围；向左分页导致范围扩展时，只为当前选中项发一次合并范围读取，不逐 Bar 请求、不每帧请求。窗口超出现有资源限额时按既有有界规则裁剪/失败，不新增无限历史缓存。

### 8.1 各指标 profile

| 指标 | 原始输出与本次可定义绘制 | 保留的核验边界 |
|---|---|---|
| MACD | histogram 单系列红/绿正负柱，DIF 黄线、DEA 蓝线，零轴；各点状态独立 | 本项目通用内核显示适配，不宣称原站精确版本 |
| 主力控盘 | kongpan 原值柱；按服务器 status 分类着色；图例保留六个已知状态，tooltip 展示数值与状态 | 分类颜色为归一设计值；完整原站启用态仍为 E05 |
| 照妖镜 | 原 entry/wash/distribution/markup/exit/inducement 幅值分别映射类别；peaks/caution 是提示数据，不当收益或价格 | 原站正负方向、重叠次序和宽度没有完整 profile；不能对 raw 幅值任意取负后称复刻 |
| 涨跌动能 | var4、ma10、var3、ma120 和 band/rebound/oversold 返回字段分别核对；读值保留原始单位与身份 | 价格序列、比例序列与状态编码不能挤同一纵轴或机械画成触发柱；原站 profile 为 E05 |

主力控盘分类颜色的归一工程映射为：无庄控盘 `#8395AA`、开始控盘 `#F5B942`、有庄控盘 `#FF453A`、高度控盘 `#FF6B35`、主力出货 `#30D17E`、高控+出货 `#BD9CFF`；未知枚举显示原始安全文本并标识映射缺失，不静默套用最后一种颜色。该映射不宣称来自牛哇原站。

MACD profile 为本次可落地的默认路径。三种 Newow 副图的产品输出继续可读；未核验完整 render profile 前，保留现有只读显示/数值入口，并明确“图形一致性待核验”，不得把用户已要求的功能藏掉，也不得关闭完整视觉验收 Gate。后续若选择归一自定义形态，必须明确获得适配批准，不能自动当成牛哇 parity。

照妖镜 header 与 hover 常驻“历史回看 · 会重绘”，并带当前计算 as_of；标记非当时可知。其他副图也保留返回的 repaint/证据属性，不能因为 raw 数据来自服务端就把所有层默认非重绘。缺精确映射只阻塞该 profile 的一致性验收，不阻塞 Shell、MACD、volume 和其他已确定工程拆分。

### 8.2 不造副图语义

同一 Bar 多类别非零时，不默认相加堆叠或“取最大”；category overlap 必须由已核验 render profile 定义。维度不同的系列不共用刻度；0/null/枚举占位分别表达。不按 series 下标循环颜色，不为了对称美观修改纵值。视觉映射不进入后端公式参数或正式 signal eligibility。

## 9. Hover、Marker 与详情

### Requirement ENG-06: 时间联动与读取分层

采用显式 Normal 十字线作为归一交互选择；不是已证明当前牛哇线上行为。一个 IChartApi 同步垂直时间位置，水平值仅取当前 pane 的独立刻度。hover 只按精确 bar_end/物理段查表，休市空白或该序列无值时显示缺值，不吸附邻合约/邻日。

tooltip 与“所选K线”读值来自同一 index：time、合约、OHLC、volume、OI 和 active auxiliary。顶部最新行情不被覆盖。tooltip 在容器内翻转避让，最大宽280px；离开 chart 隐藏，已选 Action 不取消。图表全屏时 tooltip/弹层须仍在全屏根节点内，不被挂到不可见 body 层。

### Requirement ENG-07: 稳定身份与可操作性

Action 使用 signal_id；Hint 使用 hint_id；引用详情仍使用服务器原始时间、价格、关联ID。CLEAR 只能显示参考清仓，不创建做空。中文别名不参与缓存、URL、配对或数据去重。Hint 不推导 quantity/仓位，不把 D4–D6 放到非主升浪组合。

选中反馈为边框/轮廓提升，保留事件角色本色，不统一染成紫色或买入红。图中短标签“参考建仓 / 参考清仓”，价格仅取对应对象；收益只在存在合法关联 ReferenceTrade 时显示，不在前端从相邻标记计算。

标签碰撞以屏幕盒检测、段内候选避让与细引导线处理；最多三行标签，溢出入口仅是“多个标记”的呈现分组，展开仍逐ID列出，不合成新动作。选中项提升至最上层且可键盘达到。默认字号12px，plot 边缘留8px；不得改变 Bar 锚点来避让。

图例按 series key 显隐，仅影响绘制。当前选择、副图切换和鼠标离开互不误清；全局换身份才清掉不适用选择。为所有关键 canvas 标记提供 DOM 详情/列表入口，使键盘与屏幕阅读也能取得事实。界面操作不修改任何业务 Event。

## 10. 请求状态、窗口与资源

### Requirement ENG-08: 不创建第二套数据状态

扩展现有 useNewowProduct，不新增 Vue global store、后台轮询或浏览器公式。纯视图状态和数据身份分离：selectedAuxiliary、selectedAction、selectedHint、hover、展开与图例显隐不得加入后端策略事实。

初始：现有 chart 自动读取 → 校验成功 → 一次读取默认 MACD。右栏 strategy 摘要从当前 frame 取事实；综合解释初始显示“尚未加载”与展开入口，展开才加载 explanation。Comparator 仍仅在其明确适用入口按需读取；不能因为右栏出现综合标题就拉取全部重型区段。参考表保持原先按需读取，不自动重扫全历史。

| 动作 | 数据与界面处理 |
|---|---|
| 换视角/品种/频率 | generation++、取消旧请求、清选择/hover/不兼容图层；恢复目标视角合法身份 |
| 换 Newow 策略 | 保留品种与频率，清旧动作、提示、收益；与旧视角存在相同物理Bar时间键、且新服务端响应验证有效时才恢复显示时间范围；不跨策略沿用旧snapshot token或旧参考身份 |
| 换副图 | 仅更新辅助选择和辅助 section；保留主图范围、已选 Action、统计窗 |
| 图表平移缩放 | 只改可见范围，不变 performance_since/through、不重新算公式 |
| 历史分页 | 通过现有游标；兼容 proof 与共享Bar一致检查下保留参考表与精确目标；不同窗口input hash不同不单独构成冲突，真实冲突使依赖失效 |
| 409 | 保留现有一次受控重建；重建只重取只读快照，不能无限重试 |
| 429 / 读取失败 | 明确局部失败与人工只读重试，不启动循环或生产修复 |
| 关闭/卸载 | abort、unsubscribe、disconnect observer、移除 chart/markers/DOM listener；释放映射 |

现有前端 chart累计3000行、reference累计300条等边界保持，不以这次设计自动提高上限。辅助 LRU 继续有界，不按鼠标位置缓存；cache 命中需完整身份/范围/快照校验。服务端 SnapshotCache 容量预算涵盖 MACD 新输出，不能只计旧核心对象后追加无预算字段。

辅助请求前显式带当前 chart 范围，避免主图游标窗口与“默认最近500根”的辅助窗口不同。切换三次副图的乱序响应也只能使最后选择成为当前数据。

不新增持久化偏好 schema：继续保留既有 lastView、strategy、frequency 的合法恢复；MACD 默认与本次 tab 选择在界面会话内管理，不写成跨产品共享的无限状态。刷新/后退/前进仍由既有 route/parser 决定上下文，不能让过期 LocalStorage 覆盖显式 URL。

## 11. 参考交易、解释与只读状态

ReferenceTrade 与 AlertEvent 完全分域。底部名称“参考交易”，不写真实持仓、成交或回测账户；保留 CLOSED/OPEN/ROLLOVER_INTERRUPTED，闭合收益、参考浮动与中断浮动分别显示。统计以服务器显式窗口和 summary 为准，不随图表缩放而变，也不把简单收益率合计叫复利累计净值。

`holding_bars` 展示“持有K线数”，不能当日历天/交易日。`reference_return_pct` 与 `mark_change_pct` 不混列；无退出为“未清仓”，换月中断不伪造 CLEAR。仅后端 reference_trade_id/entry_signal_id/exit_signal_id 用于精确定位。

综合解释只绑定已返回的 context slots/source facts，缺少评分/目标/原站文案明确 evidence_required；不生成“信号强度五格”“保持多单”“建议仓位”等效果图补充。价格名保留字段本来的参考身份，不能把目标/吸筹直接改名止盈/止损或期货主力席位。

状态区只复用只读来源并带观察时间；process running、aggregate ok、Rule error、provider accepted 各自展示，不以绿色总状态覆盖错误。无成员列表、未读人数、重发/测试发送、Scope 开关或 acknowledgment 新控件。最新 STATUS 的运行结论不在本文重复冻结；只以 [STATUS](../../STATUS.md) 及后续真实观测为准。

## 12. 兼容、安全与维护成本

所有网络资源按既有 API 边界读取；不改两个 Market route、Legacy D1、HTDY/苏冰/Free 的业务能力。已有移动测试作为非回归保留，本阶段仅新增桌面规格，不宣称完成手机 parity。

长文本与 tooltip 采用文本绑定，不插入原站 HTML、不执行下载脚本、不加载第三方私有字体/icon，不将截图内数据写入 production fixture。错误只呈现已有安全 reason，不泄露数据库地址、内部路径、凭据或堆栈。新文件不包含任何用户本机完整路径。

不增加永久 feature flag、新配置平台、独立 chart 基础设施或用户权限系统。若为了 MACD 需要改已有策略数学、成本、成交时序或数据权威，应拆出独立高风险任务并停止本次相关实现。正常 UI 与只读适配可走工程车道，但 contract 扩展仍须独立代码审查；文档合入不授权 main/tag/Runtime 或任何真实写入。

## 13. 验收与测试映射

原交互 UX-01..UX-20 全部保留；以下为新增工程必测场景，不是本次已经运行的结果。测试命令统一引用 [TESTING](../../TESTING.md)，不在此创建第二份命令 authority。

| ID | 必测内容 | 层 |
|---|---|---|
| EN-T01 | 三策略×1w/1d/60m 按钮与摘要原始键一致，Hint D1/D4 不变成周期；苏冰15m固定 | Unit/E2E |
| EN-T02 | 无左侧栏/账户/未来功能，Free、参考交易与解释仍可发现 | DOM/Visual |
| EN-T03 | 目录 bulk 单次读取，无60路请求；坏目录、缺映射和 Scope不变 | Unit/E2E |
| EN-T04 | volume/OI 直接来自同一 chart：0/null 分离，物理合约与频率一致 | Contract/Unit |
| EN-T05 | MACD 同内核、同参数、同输入逐点一致，含DIF先ready与DEA/柱warming | Backend golden |
| EN-T06 | MACD换月重置、无跨段seed；更改显示窗口后重叠时间值不变 | Backend/Unit |
| EN-T07 | 旧服务不支持macd、结构缺字段、长度不一、NaN、错误time/segment均安全失败 | Schema/Unit |
| EN-T08 | 加辅助不改变Action/Hint/ReferenceTrade ID、统计与版本；无Alert/Event写入 | Backend contract |
| EN-T09 | 辅助缓存/证明/索引完整预算、取消与并发、有界LRU、409一次、429不循环 | Backend/Unit |
| EN-T10 | 副图跨窗口前缀不扩张主轴，历史分页后time映射仍正确 | Unit/E2E |
| EN-T11 | 一个chart的三pane，价格/volume/指标独立纵轴，hover不取邻近值 | Unit/E2E |
| EN-T12 | 快速切品种/策略/副图的乱序响应不覆盖当前；清失效选择 | Unit/E2E |
| EN-T13 | 参考定位只找精确ID，缺目标明示，无附近日期降级 | Unit/E2E |
| EN-T14 | 参考统计窗独立、OPEN/CLOSED/换月中断分列、holding_bars不显示成天数 | Unit/E2E |
| EN-T15 | 照妖镜repaint标识不丢；未核验符号profile不能被“视觉完成”标记掩盖 | Contract/Visual |
| EN-T16 | 能量原始状态/不同量纲不乱画；控盘分类不被解释成真实机构持仓 | Contract/Visual |
| EN-T17 | 标记碰撞/选择/中文别名/图例显隐只改绘制，不改信号与数字 | Unit/Visual |
| EN-T18 | 全屏promise失败、Esc退出、tooltip portal、resize、unmount无泄漏 | Unit/E2E |
| EN-T19 | 四桌面视口、DPR1/2、200%浏览器缩放不裁断关键错误和控制 | Visual/E2E |
| EN-T20 | 键盘选择、可见focus、长中文、低对比与半透明合成后的可读性 | DOM/Visual |
| EN-T21 | process正常但Rule失败仍显示；provider accepted不显示送达人数 | Unit/E2E |
| EN-T22 | Legacy D1、HTDY、SuBing、Free、Market首页资源上限与现有手机兼容不回归 | Existing suites |
| EN-T23 | 缺证据、不适用、空行情、无主动作、warming、过期、读取失败均不同状态 | Unit/Visual |
| EN-T24 | 发布前确认无策略数学、数据权威、Scope/通知、订单或生产配置变更 | Diff/Review |

### 13.1 视觉验证方法

使用本仓库固定 route fixture 和明确标为模拟的期货输入，固定 snapshot/as_of、时区、字体、viewport、DPR、动画关闭及hover坐标。分别留全屏、局部细节、错误态、选中态；禁止仅截图漂亮常态。跨OS字体/DPR不是同一像素比较组。

与批准概念图比布局、颜色、比例与信息层级；概念图不作价格/文字/曲线逐像素 golden。首个用户确认的真实浏览器稿才成为同环境回归基准。结构对齐误差目标≤2 CSS px；关键文义、频率键、提示与数值完整性必须精确。稳定区域截图差异预算建议≤0.5%，须按噪声样本校准后固定，不通过放大阈值或大面积mask隐藏错位。市场动态内容若用fixture已冻结，原则上不再mask。

交付分别标明：GUIYI_SPEC_PASS、REFERENCE_PARITY_EVIDENCE、BUSINESS_REGRESSION、REAL_WORKSTATION_EVIDENCE。前两者不能代替后两者；一个静态图不证明全部交互、公式或性能。

### 13.2 性能与资源验收

不新增定时刷新或N品种扇出；hover不发网络请求，不每次全量setData；layout/resize批处理到帧，身份替换/分页才更新所需series。图例显隐不重跑kernel。测现有最大有界数据集与连续20次视角/指标切换后的监听器、chart实例及内存释放，记录真实环境与before/after，不在文档虚写帧率或延时达标。实际MDS性能须另按既有manual acceptance完成，fixture不得冒充。

## 14. 证据缺口与放行边界

| Gate | 当前来源事实 | 允许推进 / 不允许声称 |
|---|---|---|
| Q01 | volume/OI字段、MACD内核和同快照接入结构已完成源码核对与本文设计 | 可拆适配任务；未实现、未通过组合golden |
| Q02 | 公共Shell/趋势方向已批准；其他策略及HTDY/苏冰差异态未逐屏验收 | 复用不代表整套页面视觉已批准 |
| Q03 | 第5节给出确定工程默认token与布局 | 须浏览器样本校准；不是牛哇computed style |
| E03/E04/E05/E06/E09 | 原站hover、点击、各副图profile、弹层、持久化缺完整动态证据 | 归一已批准适配可实现；精确原站一致性保持待核验 |
| E01/E11 | 历史版本冲突及未取回的旧素材 | 不以索引或生成图片宣称当前在线版本 |
| E12/E14 | 当前候选浏览器及真实MDS证据待补 | 不宣称真实产品闭环/性能已通过 |
| E13 | 目标价/组合评分/诊断/比较器等产品真值缺口仍在 | 不由UI改造关闭、不造默认数值 |
| 视觉资产 | 会话附件 `霓虹量化交易终端界面.png`，SHA-256见交互规格；未随本次纯文档提交导入Git | 视觉任务执行前必须取得hash一致原图；无图不凭文件名猜，文档不建立虚假相对图片链接 |

E02/E07/E08/E10 以及其他 Stage1 缺口沿用交互规格完整表。本轮缩减手机专项不是填平手机证据。原始正负柱 profile 的缺证据不是要求修改指标公式的理由。

## 15. 集成边界与下一阶段

本次产物只有两个相互引用的任务设计文档，位于 `docs/tasks/`；不恢复 `docs/superpowers/` 历史设计副本，不新增active策略spec，不改STATUS的P6/Runtime结论。上游V1.1是用户确认的交互；本文工程方案经过自审后供任务规划，不自动构成全套实现批准。

下一阶段为 Stage6 实现任务拆分。按已确定的依赖拆分：显示字典/局部主题与Shell → 主图/volume渲染 → 同快照MACD适配 → 主副图交互/记录 → 各副图受证据约束的profile → 综合回归。这里只定义依赖，不发执行Prompt、不自动创建或执行所有实现任务。

涉及MACD enum/schema的任务在首次修改前需要再次对照当前active OpenSpec，提交最小只读显示扩展及向后兼容测试；不得悄悄把接口扩展藏在CSS任务里。图表外观任务无需也不得改公式。正式发布main/tag、Runtime promotion、DB/Canonical/Scope/真实通知各自另有明确Gate。

若用户全项目Review在期间修改共同文件，实施先对照新的develop基线重新核验；不能以本设计基线覆盖后来变更。文档集成应以确切父commit派生、仅添加本轮文件、无force更新；并发移动时重读冲突后重建，不重写他人提交。

## 16. 自审记录

自审范围：上游逐条需求、当前源代码事实、工程方案内部一致性、兼容/失效边界、来源与交付声明。用户请求的是自审；本次没有独立 reviewer，不将自审称为独立Review。

| Finding | 自审发现与修订 | 结果 |
|---|---|---|
| SR-01 | V1.1 部分段落仍称交互“提案”、MACD接入“待核对”，与本轮确认及工程核对不同；统一为交互已确认、接入已设计未实现 | 已修正 |
| SR-02 | 默认MACD自动请求缺少明确去重键，重渲染可能造成重复请求；补identity generation/component/chart范围/兼容快照去重 | 已修正 |
| SR-03 | 跨策略“保留范围”容易被误实现为沿用旧snapshot token；补充只恢复兼容时间键，新策略重新验证，不继承旧token/收益身份 | 已修正 |
| SR-04 | 不同分页窗口hash可能不同，不能机械当冲突；明确proof加共享Bar校验，保留既有兼容窗口语义 | 已修正 |
| SR-05 | MACD复用内核不保证不同seed起点的页面逐值相同；明确固定物理生命周期前缀、同前缀golden及viewport不改变重叠值 | 已修正 |
| SR-06 | 控盘“分类着色”缺确定映射；补六状态工程色表和未知枚举处理，不假称原站取色 | 已修正 |
| SR-07 | 镜像原始多类别幅值不能仅凭截图变为正负柱；保留独立render-profile证据Gate，不改公式，不错误宣布副图parity完成 | 核对并保留Gate |
| SR-08 | 文档集成与产品完成容易混写；明确仅两份文档、asset仍需转交、未运行检查、无独立Review与无生产授权 | 已澄清 |

修订后二次对照：未发现需要阻止纯文档集成的范围/身份冲突；保留的E/Q Gate都有明确作用域和关闭条件，不把这些证据缺口写成自审已解决。结论：允许集成 develop（仅文档），可进入实现任务拆分；不得宣称所有副图或原站交互已经完成。

## 17. 本次验证范围

本次只读GitHub读取与本地文档验证，不连接生产DB/Redis/RQData，不发送通知，不修改运行代码。容器直接访问GitHub DNS失败，不能clone完整仓库；GitHub连接可用，采用远端tree/文件读取与最终atomic docs commit。本地验证目录是文档工作区，不是用户本机worktree，不声称用户工作树clean。

文档提交前执行本地检查：正文/来源编号、频率字典、NUX/UX/ENG/EN-T需求追踪、代码围栏/表格、文档互链、引用源路径登记、原图与审计hash、常见凭据模式、无本机绝对路径及git diff whitespace。远端提交后再核对parent、changed files、blob与develop HEAD。常见凭据模式扫描不是仓库全量secret_scan替代，也不构成无泄露的绝对保证。未运行的OpenSpec CLI、仓库unit/E2E/build及独立Review明确不报告通过。active OpenSpec没有修改，本次不把这些未运行检查伪造为源码或产品完成。

## 18. 来源与追踪

所有仓库来源固定为本文件开头基线，default-branch search只用于发现路径，设计判断使用develop对应内容。

| 源码/文档 | 已核对范围与用途 |
|---|---|
| `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` | 产品范围、当前状态、写入与文档职责；本次develop HEAD与上轮同SHA |
| `openspec/specs/newow-product-reference-trading/spec.md` | 产品/公式/Hint/参考/证据不变量；本次不改 |
| `apps/quant-web/package.json` | 声明依赖版本；不是安装环境证明 |
| `apps/quant-web/src/types/newowProduct.ts` 1–300行 | bar字段、辅助union、point/segment、reference语义 |
| `apps/quant-web/src/composables/useNewowProduct.ts` 1–200行 | 按需section、generation、bounded rows、取消与缓存入口 |
| `apps/quant-web/src/components/market/detail/newow/NewowProductWorkspace.vue` | 上轮同SHA核对：三副图、按需reference/explanation、选择清理与定位 |
| `apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue` | 上轮同SHA核对：四视角、序列与频率边界 |
| `apps/quant-web/src/components/market/detail/NewowTrendChartStage.vue` 1–280行 | 既有同chart多pane/volume/primitive/资源释放；旧D1不可直接复制多周期 |
| `services/quant-api/app/api/market.py` 1–200行 | bulk目录与既有只读Market入口 |
| `services/quant-api/app/api/market_newow.py` 1–175行 | strategy-detail入口、query enum、active universe与服务组合 |
| `services/quant-api/app/market_data/newow/product_service.py` 1–200、470–660行 | AuxiliaryComponent、chart结构、同snapshot proof与缓存路径 |
| `services/quant-api/app/market_data/newow/product_reader.py` 1–240行 | ProductReadSet、同物理生命周期前缀、as_of裁剪 |
| `packages/quant-core/guiyi_quant/newow/product_auxiliary.py` 1–270行 | 现有段校验、回看属性、auxiliary分域 |
| `packages/quant-core/guiyi_quant/newow/subplots.py` 1–290行 | 控盘分类、镜像幅值/提示、动能不同量纲；不推定未观察原站render profile |
| `packages/quant-core/guiyi_quant/indicators/macd.py`、`docs/INDICATOR_KERNEL.md` | 通用MACD真实签名、版本、参数、ready/valid与柱倍数 |
| `TESTING.md` | 唯一验证命令入口；未运行检查不冒充通过 |
| 已确认交互规格 [V1.1](2026-09-07-newow-desktop-visual-interaction.md) | NUX-01..15、UX-01..20、A1源hash、U1批准、E01..14 |

| 交互需求 | 工程落实 |
|---|---|
| NUX-01 / NUX-02 | 第3–5节；ENG-01/02，EN-T01..03/22 |
| NUX-03 | 第6/10节；ENG-03/08，EN-T06/09/10/12 |
| NUX-04 / NUX-05 | 第6节；ENG-03/04，EN-T04/11/17 |
| NUX-06 / NUX-07 | 第7–9节；ENG-05/06，EN-T05..11/15/16 |
| NUX-08 / NUX-09 | 第4/9节；ENG-01/07，EN-T01/13/17/20 |
| NUX-10 / NUX-11 / NUX-12 | 第10/11节；EN-T08/13/14/23 |
| NUX-13 / NUX-14 | 第10–12节；EN-T07/09/12/21/23 |
| NUX-15 | 第5/9/12/13节；EN-T18..20/22 |
