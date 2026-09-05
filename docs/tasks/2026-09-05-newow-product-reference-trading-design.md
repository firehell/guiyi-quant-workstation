# Newow 策略与指标产品化 + 乐观参考交易 Design Spec

日期：2026-09-05
状态：`DESIGN_DRAFT / OWNER_CONFIRMED_SCOPE / FULL_DESIGN_REVIEW_PENDING / IMPLEMENTATION_NOT_STARTED`
规划基线：`develop@4f4754ed6df67a1d828e35b82fe2269d7f020469`
文档分支：`docs/newow-product-reference-trading-v1`
文档性质：第三阶段产品与领域设计提案；不是已接受的 active OpenSpec，不授权实现、集成、发布或生产操作。

## 1. 目标与已确认决定

目标是把已有 Newow 研究资产变成日常可用的单品种策略工作台：打开品种，选择策略与周期，看到指标、状态和解释，再查看历史上怎样建仓、经历哪些提示、怎样清仓，以及对应的乐观参考结果。

Owner 已逐项明确确认：

| 决策 | 已确认范围 |
|---|---|
| 周期 | `1w / 1d / 60m`，不在第一版扩至七周期 |
| 主策略 | 趋势、震荡、主升浪；三策略乘三周期，共九个独立组合 |
| 交易动作 | BUILD/CLEAR 形成参考交易；不因 D4–D6 自动加仓，不因 J、D1–D3 自行设定减仓比例 |
| 过程记录 | 适用的减仓、风险、建仓阶段及结构提示完整保留在图表与历史中 |
| 换月 | 旧合约未清仓则标为换月中断，保留记录并单列中断时参考浮动；不伪造 CLEAR、不跨合约拼接盈亏 |
| 演进顺序 | 本阶段先完成牛哇式指标与参考交易，后续才建设风险模块、模拟账户、执行和交易账本 |
| 排除范围 | 不反推私有选股，不建设 A 股选股平台，不逐字复制 AI 自然语言诊股 |

以下各节是把这些决定组织成可实施系统的设计建议，整体仍待 Owner 审阅。具体新模块名与参考统计身份是本提案定义，不代表现有代码已经存在，也不代表牛哇原服务端实现。

## 2. 当前事实与来源边界

事实基线来自上述 exact develop 的代码、研究手册及已分发证据，而不是旧对话中的完成百分比。

| 能力 | 基线事实 | 本阶段工作 |
|---|---|---|
| 趋势 | `NewowTrendD1Engine`、page-v2 profile、D1 detail API/Workspace 已存在 | 复用公式，完成三周期产品合同与参考交易 |
| 震荡/主升浪 | Core primitive 与研究评估入口存在 | 补齐产品应用服务、typed API、图表、状态和历史 |
| D1–D6、4/7/11、三个副图 | Core 能力存在，适用范围各异 | 按能力矩阵接入，不把辅助提示变成交易动作 |
| 杯柄 | `newow_cup_handle_v1` 是已存在的 D1 clean-room 能力 | 保留日线展示，不冒充私有筛选公式，不自动迁移到周线/60m |
| 目标/吸筹显示选择、参数比较、综合决策 | 冻结研究身份及 parity 摘要存在，部分没有 active Core 入口 | 恢复精确证据后重新落地实现与 golden tests |
| ReferenceTrade | 尚无本阶段完整产品领域 | 新建纯计算投影，不建立账户 |
| 期货 OOS | 研究材料记载 D1/60m 的结果与 W1 执行事实阻塞 | 保留证据等级，不把产品验收当盈利或 OOS 验收 |

`REPLICATION_MANUAL.md` 是整理后的说明；公式细节首先核对保留代码与对应测试。`REPORT.md` 是历史研究现场副本，其中“已实现”不能替代当前树中真实可调用入口。

GitHub-safe 资料不包含全部原始页面脚本、逐 Bar 输入和完整行情快照。摘要中的 `27/27 matched` 只能引用为既有研究结果；本次未重新执行其完整原始重放。对于没有 active 实现的功能，不能仅凭摘要或自然语言填补精确阈值、分支、排序及价格规则。

## 3. 与苏冰及生产环境隔离

### Requirement: Parallel development without production promotion

本阶段 SHALL 在独立开发分支推进。现役 `v1.9.15` 的苏冰自然验收 Task 11–13 保持 pending，不能因 Newow 设计或开发被标为完成。

本阶段不改 SuBing 公式、Rule、Scope、Event、PushPlus、运行进程、launchd、Canonical 或生产数据。`auto_order=false` 不变。开发、设计审阅和本地 fixture 测试不以自然苏冰信号已出现为前提；未来 release/Runtime 切换仍须另行授权。

#### Scenario: SuBing has not produced a natural Event

- GIVEN 苏冰 Task 11–13 尚待自然市场证据；
- WHEN 本阶段开始设计、测试或实现；
- THEN 可以推进独立 Newow 开发，但不得更新苏冰闭环状态、触发通知或切换现役 Runtime。

## 4. 产品范围与分层

第一版只使用 `active_products.txt` 定义的研究品种和 completed Canonical `actual_dominant` 序列。`operational_products.txt` 继续只表示持续 Runtime 授权，不能因为集合相同而合并概念。

九个主策略组合都必须具备主图、适用辅助指标、策略状态、主动作、历史过程及参考统计。九个组合完整，不意味着每个辅助形态都必须在九个组合机械复制。

| 组件 | 范围及职责 |
|---|---|
| 趋势主状态 | 三周期黄蓝带、BUILD/HOLD/CLEAR/FLAT |
| 震荡主状态 | 三周期 HHV/LLV10、BUILD/CLEAR、通道位置与已有事件评分 |
| 主升浪主状态 | 三周期 MA35/MA45、BUILD/CLEAR |
| 风险/阶段/结构提示 | 按已验证公式显示 S、D1–D6、J、4/7/11，不隐藏可用提示；不自行扩大硬交易条件 |
| 三副图 | 主力控盘、照妖镜、涨跌动能；每项显式标识公式、warming 与重绘属性 |
| 杯柄 | 维持既有 D1 clean-room profile；其他周期为 `NOT_APPLICABLE`，不把不适用伪装成无信号 |
| 目标/吸筹 | 完成通道值及有来源的日/周展示选择，显示来源周期和时点 |
| 综合解释 | 13 格决策、方向/确定性、ATR20/Close、第一行动、周日16组合；不产生第十条综合交易策略 |
| 页面比较器 | 有充分证据后恢复五窗口页面比较；独立于三策略交易记录，不自动替换默认参数 |

私有选股、私有排名/推荐、AI 自由文案逐字复刻、实时 AI 调用、机会排序、多策略组合资金分配均不属于本阶段。牛哇术语可以保留，但“主力”指标不证明真实机构持仓，“确定性”分数不等于胜率，“参考仓位区间”不等于期货保证金占用或手数。

## 5. 架构方案

推荐在现有模块化单体内增加独立的参考交易投影，而不是在 Vue 中临时配对 Marker，也不是提前建设模拟账户。

```text
Canonical + Catalog + MainContractMap
                  |
          MarketDataService
                  |
     Newow 多周期/物理区段读取适配
                  |
       三个独立 Strategy Adapter
          /               \
 Frame / Action / Hint     多周期事实与解释
          |
 ReferenceTradeProjector
          |
 ReferenceSummary
          \               /
          只读 Newow API
                  |
  统一 /market/chart 的 Newow Workspace
```

模块职责：

- **数据适配**：唯一通过 MarketDataService 读取各周期、物理前缀和权威分段；不自己聚合、不猜主力。
- **策略适配**：复用各策略内核，将已有输出归一为类型明确的主动作与提示；不修改原公式。
- **参考投影**：主动作配对、状态迁移、参考价计算、换月中断与统计；不访问网络/DB。
- **解释计算**：目标/吸筹、决策矩阵、评分与 token，保持其独立身份；不能反向更改 BUILD/CLEAR。
- **应用/API**：校验输入、组织只读查询、序列化 Decimal 与证据状态、返回数据身份。
- **Web**：展示服务器事实、选择和定位；不重新计算公式、配对交易或汇总收益。

“无新增数据库”准确指不新增交易表、migration、账户或持仓事实源；仍然使用现有 PostgreSQL Catalog 元数据。第一版不新增持久缓存、Redis authority、scheduler 或后台任务。

## 6. 页面与已发布合同

页面仍为 `/market/chart`，建议视角导航为 `Newow / HTDY / SuBing / Free`；Newow 内部选择 `trend / oscillation / main_rise` 和 `1w / 1d / 60m`。默认普通品种入口为 Newow 趋势日线。

现有 `view=trend` 与 `/api/v1/market/newow/trend-detail` 已随 v1.9.15 发布。本阶段必须保留其原有 D1 含义和可用性；可通过薄适配复用新服务，不维持第二套公式。不得直接删旧深链、放宽非法参数或改变苏冰 Event 深链。新 API 的具体路径及参数由后续 Implementation Plan 在本合同下冻结。

建议页面内容顺序：

```text
品种与数据身份 + Newow 策略/周期选择
→ 当前策略状态、最近主动作、当前风险
→ 主图与可选择副图
→ 多周期综合解释、目标/吸筹、参考评分
→ 已完成/当前未清仓/换月中断的统计
→ 历史参考交易表及展开的过程提示
→ 全部提示历史、公式与数据来源详情
```

三套选择器不能各管一份品种或周期。交易行点击后定位对应 Marker；同 Bar 多动作必须可分别查看。切换品种、策略或周期时清除旧选择、隔离请求 generation，不显示上一组合的收益、Hint 或图层。

照妖镜属于带重绘徽标的回看图层；不能作为“当时已经知道”的交易过程证据混进时间线。非重绘提示在空仓时也应保留于全部提示历史，不因无法归属某笔交易而丢弃。

## 7. 数据、时间与物理身份

### Requirement: Independent completed series and owner validation

各周期 SHALL 独立读取该周期 Canonical；第一版不消费 Live preview，不在浏览器或应用层用分钟线拼周线。每根 Bar 审核 `physical_contract / segment_id / trading_day / bar_end`。

W1 的 owner 子集不必包含每个全局权威分段。例如已有 SC2302 反例中某权威段没有 W1 Bar，这是合法的；但存在的每根 W1 Bar 必须正确归属。60m 同一 trading_day 可有多根 Bar，不能套用 D1“交易日必须严格递增”的校验。

同合约生命周期内前缀用于公式 warm-up；跨合约或跨不连续 owner 区段不继承递归状态或参考持有。60m 前缀可能超过现有 D1 单页上限，必须通过 MarketDataService 分页完整读取；不得因 2000 根限制截掉前缀还声称完整，也不能改为上一合约 seed。

warm-up Bar 不属于有效主力区段时只服务指标计算，不产生参考建仓。新主力一开始已为黄色，不自动补 BUILD。策略可显示 HOLD，但参考交易显示“无本段有效建仓记录”；后续 CLEAR 若只对应前缀中的不可交易 BUILD，应显示原因，不伪造一笔闭合收益。

#### Scenario: Weekly owner segment has no Bar

- GIVEN 全局映射包含一个没有该周期 Bar 的合法区段；
- WHEN 查询周线；
- THEN 不生成填充 Bar，也不要求周线区段集合等于日线集合；逐根验证实际返回的周线 owner。

### Requirement: Explicit as-of context

综合解释 SHALL 提供每个输入周期自己的 `bar_end` 和快照 `as_of`。不得将周五才完成的周线结论写回周一的60m历史记录。不能证明当时可知的历史多周期解释时，返回不可用；当前综合摘要不能冒充历史开仓依据。

如果公开页面使用未完成大周期值，本产品 completed-only 适配不能对整体输出声明无差别 page-exact；公式 parity 与输入/时间适配身份必须分别展示。

#### Scenario: A higher-period Bar was not complete at the historical time

- GIVEN 某60m Bar发生时，本周周线尚未完成；
- WHEN 显示该历史时点的多周期解释；
- THEN 只允许使用当时已完成的大周期事实；不能借当前完整周线回填，不足则明确不可用。

## 8. 主动作与过程提示合同

### Requirement: Separate trade actions from explanatory hints

主动作只有各策略自身 `BUILD / CLEAR`。J、D1–D3、D4–D6、4/7/11 等在本版属于 Hint；`quantity_effect=none`。不得因为提示名带“减仓”就扣除三分之一，也不得据参考仓位区间创建手数。

归一动作至少带：`signal_id`、策略及公式身份、周期、品种、物理合约、区段、Bar时间、同 Bar 顺序、动作类别、语义参考价。绘图锚点价格与语义参考价必须分开，不能拿文字偏移坐标计算收益。

趋势已有 `related_marker_ids` 必须精确校验配对。没有关联ID的内核由该策略适配器在同一有效区段按确定状态机生成引用，不能由 Web 模糊搜索最近 BUILD。重复相同身份只保留一次；同身份不同内容、乱序、跨策略/周期/合约关联均明确失败。

震荡同 Bar 固定顺序为 CLEAR 后 BUILD；旧交易关闭后才开始新交易。只有一个时间戳不足以作唯一键，动作ID必须包含动作类别与内核顺序。

#### Scenario: A reduction hint occurs during an open reference trade

- GIVEN 已有有效 BUILD，尚无 CLEAR；
- WHEN 内核输出 J 或 D 风险提示；
- THEN 图表与过程列表保留提示，但 entry、参考持有状态和收益公式不因该提示改变。

#### Scenario: CLEAR then BUILD on the same Bar

- GIVEN 震荡内核同 Bar 输出两个有序动作；
- WHEN 投影历史；
- THEN 先关闭原交易，再建立新交易，保留两个ID；不按日期去重，不反转顺序。

同 Bar Hint 没有可证明的主动作前后顺序时，作为 Bar 级提示显示，不强行归属已关闭或刚建立的交易。

## 9. ReferenceTrade 与价格口径

本提案新增 `ReferenceTrade`，不是 PaperOrder、Fill、Position 或 AlertEvent。它由当前数据和固定版本规则重算；发生合法数据修订时可以产生新的重算结果，不能假称它是不可变实盘记录。

主要字段：

```text
reference_trade_id
product / strategy_code / frequency
physical_contract / segment_id
formula_versions / reference_model_version / futures_adaptation_version
entry_signal_id / entry_bar_end / entry_reference_price
exit_signal_id / exit_bar_end / exit_reference_price
status = OPEN | CLOSED | ROLLOVER_INTERRUPTED
holding_bars
reference_return_pct
mark_bar_end / mark_reference_price / mark_change_pct
interrupted_at / interruption_reason
statistics_membership / hint_ids
```

各策略沿用已核实的主动作参考价，不统一替换为 Close：

| 策略 | BUILD参考价 | CLEAR参考价 |
|---|---|---|
| 趋势 | 内核输出的慢线 B | 内核输出的慢线 B |
| 震荡 | BUILD信号的当根 Low | CLEAR信号的当根 High |
| 主升浪 | 主带信号输出的 MA45 | 主带信号输出的 MA45 |

以上来自现有内核与复刻手册；实现前必须用测试核对字段含义，不能用 Hint 的 High 或 Low×0.99 替代主动作价格。参考价未必可成交；不补真实成交时序、手续费、滑点、tick、保证金、资金或手数假设。

建议参考身份为 `newow_marker_reference_zero_cost_v1`，期货适配为 `newow_futures_segment_interrupt_v1`；它们是本提案的新身份，不是牛哇原始版本号。

### Requirement: Reference return is not an account return

对正数且有限的有效参考价格，CLOSED 单笔计算：

```text
reference_return_pct = (exit_reference_price / entry_reference_price - 1) * 100
```

价格及参考收益使用 Decimal，序列化为十进制字符串，显示舍入不能反向影响统计。第一版为 long/flat；蓝带或 bearish 解释不自动转换为开空。

UI 固定说明：`牛哇式乐观参考：按策略参考价计算，未计手续费、滑点、资金占用与真实成交限制；非模拟账户或实盘收益。`

#### Scenario: A chart label uses a displaced price

- GIVEN D4文字锚点为Low×0.99，而主升浪BUILD语义参考价为MA45；
- WHEN 计算主升浪参考交易；
- THEN 只使用主动作输出的MA45，不使用D4锚点，不推断真实成交。

## 10. 未清仓、换月与样本末

### Requirement: Do not manufacture exits

有效 BUILD 后未出现本段 CLEAR 的当前交易为 OPEN。当前参考浮动使用同周期、同合约最新 completed Close，记录对应时间；没有合格价格时显示 unavailable。

权威映射已证明旧主力区段结束而交易未 CLEAR 时，转换为 ROLLOVER_INTERRUPTED。即使后续某个 owner 区段没有本周期 Bar，也不能因此让旧参考持有跨越映射边界。

中断参考价只取旧主力有效区段内该周期最后一根 completed Close；单列 `mark_change_pct` 和估值时间。该值不是清仓价、不是已实现收益，不计入 CLOSED 统计。周线估值可能早于实际换月日，页面须显示原时间，不能换用日线、下一合约或区段外行情。

样本结束本身不是 CLEAR。OPEN 不因为缩小图表或更改查询 through 而被强制关闭。新合约独立等待其有效 BUILD。

#### Scenario: Rollover interrupts a losing trade

- GIVEN 旧合约已有 BUILD，尚无 CLEAR，中断时参考浮动为负；
- WHEN 权威主力区段结束；
- THEN 保留整笔历史，状态为 ROLLOVER_INTERRUPTED，单列负浮动；不删除、不记成盈利或零收益，不生成CLEAR。

#### Scenario: No eligible valuation price

- GIVEN 已发生换月但无法取得合法旧合约同周期估值；
- WHEN 返回中断记录；
- THEN 保留中断状态和原 BUILD，估值字段为不可用并带原因；不跨频或跨合约补价。

## 11. 统计范围与页面比较器

### Requirement: Statistics independent of chart viewport

图表窗口与统计窗口 SHALL 独立。`display_window` 只决定画哪些 Bar；`performance_since / performance_through` 是明确选择并显示的固定统计窗口。缩放、拖动、向左加载不得自动改变统计窗口。

默认统计范围建议采用该品种既有研究历史起点至最近可用完整交易日，响应明确给出实际起止；数据不完整时不能静默缩短后仍标为“全部历史”。用户可显式修改统计范围。

统计纳入规则建议固定为 `entry_in_window_v1`：BUILD 在统计窗口内的交易属于本次样本；清仓亦在截止时点内才计 CLOSED。BUILD 在左边界之前的已知交易单列“期初已有参考交易”，不混入本窗口胜率/收益；前缀中没有有效 BUILD 时不补开仓。

第一版统计：已完成数量、胜/负/平数量、胜率、单笔平均参考收益、已完成参考收益率合计，以及 OPEN、换月中断、期初记录数量与明细。

本提案的“已完成参考收益率合计”采用 `sum(single_trade_return_pct)`，标签明确为简单相加，单位为百分比点；这只是独立交易结果摘要，不是复利净值或账户累计收益。该统计设计不能借页面参数比较器使用相加的证据，就声称与牛哇所有策略收益模块精确一致。

零笔 CLOSED 时胜率、均值及展示的收益合计均显示“— / 暂无已完成参考交易”，不使用0%暗示稳定。第一版不提供账户净值、年化收益、资金回撤或组合Sharpe，不将60品种或九个组合的收益相加成账户收益。

#### Scenario: Viewport changes

- GIVEN 策略、数据、公式及 performance window 未变；
- WHEN 用户向左加载或缩放图表；
- THEN 已完成交易数、统计与记录身份不变，仅图表展示窗口变化。

### Requirement: Isolate exact page comparator semantics

五窗口 `10/20/24/30/52` 比较器若恢复，必须采用已验证的独立页面身份。研究手册支持该比较器的同 Bar Close、零成本、收益相加、样本末强平规则；这些规则不替代第9节三策略Marker参考价或第10节不伪造CLEAR的政策。

比较器的期末理论平仓只能存在于其独立假设结果中，不能写入 ReferenceTrade、图表主动作或交易历史。页面排名标注样本内，不自动选参数覆盖正式图表，不接因果研究或候选晋升。

#### Scenario: The page comparator closes a sample-end position

- GIVEN 五窗口比较器按其独立页面合同计算期末理论平仓；
- WHEN 同页展示三策略参考历史；
- THEN 该理论结果只属于比较器，不改变ReferenceTrade的OPEN状态，也不新增CLEAR。

## 12. 综合解释与证据不足

### Requirement: Explain without changing main actions

综合解释 SHALL 输出输入事实、来源周期/时间、规则ID、方向、参考仓位区间、确定性拆分、波动率、第一行动和稳定token。第一版不调用外部LLM。

保留源页面已确认的控制流，包括13格矩阵中不可达的warning分支；任何修正必须使用新clean-room身份并另行审阅，不能借产品化静默修复。周日16组合是解释矩阵，不等于九个策略/周期组合，更不能因此生成新的综合交易记录。

原始证据缺失的参数、六组合评分或诊断映射不得按通用技术分析补齐。缺精确合同的功能标记 `EVIDENCE_REQUIRED` 并阻塞该功能的完成声明；不以“暂无信号”或0分替代。已经验证的其他功能可以继续交付。

证据状态与功能状态分开：`ACTIVE_CODE_VERIFIED / RESEARCH_EVIDENCE_ONLY / EVIDENCE_REQUIRED / OUT_OF_SCOPE`。界面不必展示内部英文枚举，但必须给出准确的人类可读说明。

#### Scenario: Only a research summary is available

- GIVEN 某评分只有汇总匹配率而缺可核对的完整规则或输入；
- WHEN 恢复其产品功能；
- THEN 标记EVIDENCE_REQUIRED并阻止该功能被验收为精确复刻，不用通用指标知识补分支。

## 13. 重绘与page-parity标签

### Requirement: Keep retrospective display outside trade authority

照妖镜继续为 `repainting=true / formal_signal_eligible=false`。可在独立回看副图显示，不进入BUILD/CLEAR、ReferenceTrade、胜率、综合交易动作或历史当时可知的提示事实。

杯柄维持既有clean-room身份与确认时间语义；`pivot_at` 不是首次可知时间。不因形态画在历史位置就回填一笔当时不存在的建仓。

组件级别的公式parity、输入适配、参考交易政策和证据包可重放性必须分别声明。期货换月适配、completed-only约束、统计窗口和本提案的收益摘要不属于牛哇证券页面的精确原样行为；整个产品不得笼统写成 `page_parity=true`。

#### Scenario: Retrospective marker changes

- GIVEN 照妖镜随新增Bar重绘历史图形；
- WHEN 刷新页面；
- THEN 只更新标明回看的图层，不改参考交易的BUILD/CLEAR及收益，不把回绘点写为当时的交易原因。

## 14. 查询身份、错误与性能

只读响应至少标识品种、策略、周期、series、公式集合、profile、reference model、期货适配版本、请求窗口、统计窗口、as-of、数据来源及可用状态。

当前数据层没有稳定全局revision摘要时，`data_revision_identity` 允许为空并说明；不能用请求时间或固定字符串冒充。可以对本次真实读取的有序Bar和映射事实计算 `input_content_sha256`，但它只是输入指纹，不建立第二套Canonical版本体系，也不代表完整离线复算包。

不同窗口的输入指纹可以不同；不能仅以整包hash不同判定共同可见Bar冲突。共同部分的时间、OHLCV/OI与物理身份仍必须严格对齐。数据修订后相关只读结果显式重算，不能混显示两个不同输入世代的交易摘要。

错误至少区分：非法身份、缺失数据/前缀、warming、映射冲突、配对冲突、缺证据、不适用、同身份旧快照。warming遵守原公式，不额外把所有指标统一要求120根。

主行情可用但辅助解释失败时，保留可验证行情与主策略，辅助区域显示不可用；主策略输入或配对完整性失败时，其交易统计不可显示旧值冒充当前成功。切换身份后不能保留上一身份的快照。

保持首页既有bulk读取，不增加逐品种的九组合请求。详情按当前品种和必要上下文加载；长历史通过有界分页、取消过期请求和请求内复用控制成本，不以静默截断、背景生产写入或新常驻服务解决性能。

## 15. Canonical修改提案

本次仅新增设计文件，不修改以下active文档。实现前的首个工作包须提交精确修改并审阅：

| 事实源 | 需要的变化 |
|---|---|
| `PROJECT_SOURCE.md` | 允许Newow只读策略状态、参考交易与乐观摘要；继续禁止账户、订单和自动交易；消除与已发布Trend入口的文字冲突 |
| `DECISIONS.md` | 记录策略/参考交易/账户分层、无仓位比例推断、换月中断和双收益身份 |
| `docs/ARCHITECTURE.md` | 加入Newow多周期适配、解释与纯参考投影；不改变行情authority |
| `openspec/specs/` | 批准后新增Newow产品与参考交易能力合同；不复活旧策略域 |
| `TESTING.md` | 只在实施时加入真实可执行的测试入口，不复制假命令 |
| `STATUS.md` | 只记录已发生阶段事实，保留苏冰Task11–13待自然证据 |

已有D1详情设计涉及“固定Trend日线、禁止历史策略效果”的条款必须在新合同接入时明确替代；不能留下两个冲突的active authority。`AGENTS.md`的外部操作授权、密钥、数据完整性与无真实订单规则不放松。

## 16. 实施工作包边界

这不是Implementation Plan；此处只冻结依赖与交付边界，避免一个巨型PR。

| 包 | 交付 | 依赖 |
|---|---|---|
| P0 | 范围/证据盘点、canonical精确提案与缺失证据定位 | 整体Design批准 |
| P1 | 三周期物理读取、前缀、owner校验和三策略typed输出 | P0 |
| P2 | ReferenceTrade、Hint分离、价格政策、换月及统计纯内核 | P1 |
| P3 | 三副图、目标/吸筹、综合解释与页面比较器；逐项证据Gate | P0/P1 |
| P4 | 只读API与原D1合同兼容 | P1/P2/P3的已验证接口 |
| P5 | 统一Newow Workspace、九组合、历史/统计联动及错误呈现 | P4 |
| P6 | 全量回归、视觉、无副作用、证据标识和独立双轴Review | P1–P5 |

P3的缺证据项可独立阻塞自身，不允许用占位功能把“完整产品化”标成完成。已经通过的主策略纵向切片可以进入开发集成，但最终完整完成必须覆盖范围内全部适用能力。

每包使用独立上下文、测试与Review；真正可并行的只读审阅可以并行，共享数据/路由/API文件不由多个实现者同时写。具体任务步骤、命令和文件改动由批准后的Implementation Plan定义。

## 17. 验收矩阵

| 编号 | 必须通过的场景 |
|---|---|
| AC01 | 三策略×三周期均有独立身份、主状态、动作与参考历史；不可用显式说明 |
| AC02 | 保留的page公式与golden输入逐值一致；缺本地原件不冒充本次重放 |
| AC03 | 60m同日多Bar、W1零Bar权威段、同合约前缀分页均正确 |
| AC04 | 非重绘主动作通过prefix/batch/incremental及同物理区段校验 |
| AC05 | 前缀内BUILD不伪造成新主力有效建仓；期初已有记录独立于统计样本 |
| AC06 | BUILD/CLEAR精确配对；同Bar震荡先CLEAR再BUILD |
| AC07 | J、D等提示不改变参考持有与收益；空仓期提示不丢失 |
| AC08 | 换月未清仓标中断，保留正负参考浮动；无价不跨频补价 |
| AC09 | 样本末/图表缩放不生成CLEAR；统计窗口不随viewport改变 |
| AC10 | 三策略参考价不误用Close、Hint价或绘图偏移价 |
| AC11 | Decimal单笔公式/汇总/舍入一致；零交易不显示误导性0%表现 |
| AC12 | 中断/OPEN/期初记录与CLOSED分列；不输出账户净值、年化或组合收益 |
| AC13 | 页面比较器理论期末结果不能进入ReferenceTrade或正式主动作 |
| AC14 | 多周期as-of明确；未来完成周线不能回填历史60m解释 |
| AC15 | 照妖镜重绘不污染参考交易；杯柄保留D1 clean-room及确认时间 |
| AC16 | view=trend与原D1 API继续可用；HTDY/SuBing/Event深链/Free无回归 |
| AC17 | 身份切换、旧请求、数据修订、API失败、stale与warming均不混结果 |
| AC18 | 不新增RQData请求、Canonical/交易DB写入、Rule、Runtime、通知或订单路径 |
| AC19 | Web桌面/移动/键盘操作可用，历史选中与图表Marker一致 |
| AC20 | 同exact head定向及全量适用验证通过，Standards/Spec独立Review无P1/P2 |

测试必须分别证明公式、参考政策、应用数据和UI投影；不能只凭截图或数字看起来合理验收。完整收益离线复算包、周线执行日limit修复、OOS/Walk-forward扩展与Shadow盈利判断不作为本阶段新增实现，但其未完成状态必须保留。

## 18. 完成定义、审阅与下一步

本阶段实现完成的目标是 `NEWOW_PRODUCT_AND_REFERENCE_TRADING_COMPLETE`，不等于 `PAPER_ACCOUNT_READY`、`RUNTIME_READY`、`OOS_PASSED` 或盈利策略。参考交易计算无误不证明可执行，也不保证乐观口径总高于因果结果。

当前只写成Design草案。已确认的是第1节的Owner决定，尚未批准的是整体架构、统计摘要/样本口径、页面组织及实施分包。Design审阅通过后再写Implementation Plan，不在本次执行代码或改生产。

审阅重点：是否接受独立参考投影、九组合与辅助能力矩阵、仅CLOSED的简单相加摘要及期初记录单列、原D1深链兼容、证据不足不伪装完成。

## 19. 来源索引

以下是本设计核对的仓库依据；本设计新增政策已在正文标明为提案，不借来源名称冒充原规则。

- [工程授权与硬约束](../../AGENTS.md)
- [开发流程](../DEVELOPMENT.md)
- [当前阶段事实](../../STATUS.md)
- [稳定产品边界](../../PROJECT_SOURCE.md)
- [研究资料与分发边界](../research/newow-v3.2.82/README.md)
- [整理后的复刻手册](../research/newow-v3.2.82/REPLICATION_MANUAL.md)
- [page primitive与因果研究历史合同](2026-09-04-newow-page-parity-research-kernels.md)
- [现有趋势profile](../../packages/quant-core/guiyi_quant/newow/profile.py)
- [现有震荡内核](../../packages/quant-core/guiyi_quant/newow/oscillation_channel.py)
- [现有主升浪内核](../../packages/quant-core/guiyi_quant/newow/main_rise.py)
- [现有D1详情应用服务](../../services/quant-api/app/market_data/newow/trend_detail_service.py)
- [现有D1 API](../../services/quant-api/app/api/market_newow.py)
