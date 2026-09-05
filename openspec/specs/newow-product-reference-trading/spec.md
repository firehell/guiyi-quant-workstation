# Newow Product Reference Trading

## Purpose

定义 Newow 趋势、震荡、主升浪在 `1w / 1d / 60m` 上的只读产品合同，以及主动作、Hint、
ReferenceTrade、乐观参考摘要、多周期解释、证据状态和回看图层之间不可混淆的边界。
该能力服务个人期货研究复核，不创建 Position、Order、Account、Execution、Fill、Ledger、AlertEvent，
不授权生产数据写入、通知、Runtime、策略晋升或真实交易。

## Requirements

### Requirement: Parallel development without production promotion

Newow 产品 SHALL 以趋势、震荡、主升浪 × `1w / 1d / 60m` 九个独立组合提供只读主状态、
主动作、Hint、ReferenceTrade 和乐观参考摘要。这是新的产品能力，不是恢复已退役 Historical Projection、
账户、策略 Event 或 Runtime。既有 `view=trend` 与 `GET /api/v1/market/newow/trend-detail`
MUST 保持固定 `actual_dominant + 1d + trend` 兼容语义，并允许薄适配复用同一公式 authority。

本阶段 MUST 与 SuBing 公式、Rule、Scope、Event、PushPlus、进程、launchd、Canonical、生产数据和
现役 Runtime 隔离；`auto_order=false` 不变。代码、测试或文档通过不能改变 SuBing 自然验收、
release、Runtime、通知送达或交易 Gate。

#### Scenario: SuBing has not produced a natural Event

- **GIVEN** SuBing Task 11–13 尚待自然市场证据
- **WHEN** Newow 产品开始设计、测试或实现
- **THEN** 可以推进独立 Newow 开发，但不得更新 SuBing 闭环状态、触发通知或切换现役 Runtime

### Requirement: Independent completed series and owner validation

各组合 MUST 只消费 `active_products.txt` 研究边界内、由 `MarketDataService` 读取的 completed
Canonical `actual_dominant`。`1w / 1d / 60m` SHALL 独立读取本周期 Canonical，逐 Bar 校验
`physical_contract / segment_id / trading_day / bar_end`；浏览器和应用层不得用分钟线拼周线、
猜测主力或跨频回退。

同合约生命周期前缀可用于 warm-up，但跨物理合约或不连续 owner 区段 MUST 重置递归状态和参考持有。
warm-up Bar 不得产生有效主力区段内的 BUILD；新主力起点已经处于持有状态时，只能显示 HOLD 和
“无本段有效建仓记录”。60m 同一交易日可有多根 Bar，完整前缀 MUST 通过有界分页取得，不得静默截断。

#### Scenario: Weekly owner segment has no Bar

- **GIVEN** 全局映射包含一个没有该周期 Bar 的合法区段
- **WHEN** 查询周线
- **THEN** 不生成填充 Bar，也不要求周线区段集合等于日线集合；只逐根验证实际返回的周线 owner

### Requirement: Explicit as-of context

综合解释 SHALL 提供每个输入周期自己的 `bar_end` 与快照 `as_of`，并只使用该历史时点已经 completed
的事实。当前综合摘要不得冒充历史开仓依据；不能证明当时可知时 MUST 返回不可用。若公开页面使用未完成
大周期值，公式 parity 与 completed-only 期货输入适配身份 MUST 分别声明，不能笼统声称整体 page-exact。

#### Scenario: A higher-period Bar was not complete at the historical time

- **GIVEN** 某 60m Bar 发生时，本周周线尚未完成
- **WHEN** 显示该历史时点的多周期解释
- **THEN** 只允许使用当时已完成的大周期事实；不能借当前完整周线回填，不足时明确不可用

### Requirement: Separate trade actions from explanatory hints

主动作 MUST 只有各策略自身的 `BUILD / CLEAR`。J、D1–D3、D4–D6、4/7/11、阶段、风险和结构信息
均为 `quantity_effect=none` 的 Hint，不得改变 entry、持有、收益、手数或仓位。无主动作是完成计算后的
有效结果，MUST 与 `EVIDENCE_REQUIRED`、`NOT_APPLICABLE` 和 retrospective repaint 分开表达，不能合并为
“无信号”。

Action MUST 带稳定 identity、策略及公式、周期、品种、物理合约、区段、Bar 时间、同 Bar 顺序、
动作类型和语义参考价。配对必须使用关联 identity 或策略 adapter 的确定状态机；Web 不得模糊搜索最近
BUILD。同身份不同内容、乱序、跨策略/周期/合约/区段关联 MUST fail-closed。震荡同 Bar 顺序固定为
CLEAR 后 BUILD；无法证明相对顺序的同 Bar Hint 只能作为 Bar 级提示。

#### Scenario: A reduction hint occurs during an open reference trade

- **GIVEN** 已有有效 BUILD，尚无 CLEAR
- **WHEN** 内核输出 J 或 D 风险提示
- **THEN** 图表与过程列表保留提示，但 entry、参考持有状态和收益公式不因该提示改变

#### Scenario: CLEAR then BUILD on the same Bar

- **GIVEN** 震荡内核同 Bar 输出两个有序动作
- **WHEN** 投影历史
- **THEN** 先关闭原交易，再建立新交易并保留两个 ID；不按日期去重，也不反转顺序

### Requirement: Reference return is not an account return

`ReferenceTrade` SHALL 是从当前数据和固定版本规则重算的只读投影，绝不是 Position、Order、Account、
Execution、Fill、Ledger 或 AlertEvent。趋势 BUILD/CLEAR MUST 使用内核慢线 B，震荡 MUST 使用 BUILD Bar
Low 与 CLEAR Bar High，主升浪 MUST 使用主带信号 MA45；绘图锚点、Hint 价格和 Close 不得替代这些语义价。

所有价格和参考收益 MUST 使用 Decimal 并序列化为十进制字符串；显示舍入不得反向影响统计。对正数且有限的
有效参考价，CLOSED 单笔 SHALL 计算
`(exit_reference_price / entry_reference_price - 1) * 100`。该 long/flat 零成本乐观口径 MUST 明示
未计手续费、滑点、资金占用和真实成交限制，且不得推断手数、空单、账户净值或真实收益。

#### Scenario: A chart label uses a displaced price

- **GIVEN** D4 文字锚点为 Low×0.99，而主升浪 BUILD 语义参考价为 MA45
- **WHEN** 计算主升浪参考交易
- **THEN** 只使用主动作输出的 MA45，不使用 D4 锚点，也不推断真实成交

### Requirement: Do not manufacture exits

有效 BUILD 后在本 owner 区段未出现 CLEAR 时 MUST 保持 OPEN；样本结束、缩小图表或改变查询 through
不得制造 CLEAR。当前参考浮动只使用同周期、同物理合约的最新 completed Close；没有合法价格时明确
unavailable。

权威映射证明旧主力区段结束且尚未 CLEAR 时，记录 SHALL 转为 `ROLLOVER_INTERRUPTED`，保留原 BUILD，
并仅用旧主力有效区段内同周期最后一根 completed Close 单列 `mark_change_pct` 与估值时间。该值不是清仓价
或已实现收益，MUST 不计入 CLOSED 统计；不得跨频、跨合约、跨区段或用新主力补价。

#### Scenario: Rollover interrupts a losing trade

- **GIVEN** 旧合约已有 BUILD，尚无 CLEAR，中断时参考浮动为负
- **WHEN** 权威主力区段结束
- **THEN** 保留整笔历史并标为 `ROLLOVER_INTERRUPTED`，单列负浮动；不删除、不记成盈利或零收益，也不生成 CLEAR

#### Scenario: No eligible valuation price

- **GIVEN** 已发生换月但无法取得合法旧合约同周期估值
- **WHEN** 返回中断记录
- **THEN** 保留中断状态和原 BUILD，估值字段为不可用并带原因；不跨频或跨合约补价

### Requirement: Statistics independent of chart viewport

`display_window` SHALL 只决定图表 Bar；`performance_since / performance_through` MUST 是明确选择、显示且
独立的统计窗口。分页、缩放或拖动不得改变 ReferenceTrade identity 或统计。数据不完整时不得静默缩短后
仍称“全部历史”。

默认 membership 使用 `entry_in_window_v1`：BUILD 在统计窗口内才进入样本，且只有截止时点内已 CLEAR 的
CLOSED 交易进入胜率、均值与 `sum(single_trade_return_pct)` 简单百分比点合计。OPEN、
ROLLOVER_INTERRUPTED 与期初已有记录 MUST 分列。零笔 CLOSED 时胜率、均值和收益合计显示“— / 暂无已完成
参考交易”，不得以 0% 暗示表现；不得输出账户净值、年化、资金回撤、组合 Sharpe 或跨品种/组合账户收益。

#### Scenario: Viewport changes

- **GIVEN** 策略、数据、公式及 performance window 未变
- **WHEN** 用户向左加载或缩放图表
- **THEN** 已完成交易数、统计与记录 identity 不变，仅图表展示窗口变化

### Requirement: Isolate exact page comparator semantics

五窗口 `10/20/24/30/52` 比较器若恢复，MUST 使用独立、已验证的页面 identity。同 Bar Close、零成本、
收益相加与样本末理论平仓只属于比较器假设结果，不得替换三策略 Action 参考价或不伪造退出政策。
比较器排名 SHALL 标注样本内，不自动改主策略参数，不接因果研究、ReferenceTrade 或候选晋升。

#### Scenario: The page comparator closes a sample-end position

- **GIVEN** 五窗口比较器按其独立页面合同计算期末理论平仓
- **WHEN** 同页展示三策略参考历史
- **THEN** 理论结果只属于比较器，不改变 ReferenceTrade 的 OPEN 状态，也不新增 CLEAR

### Requirement: Explain without changing main actions

综合解释 SHALL 输出输入事实、来源周期与时间、规则 ID、方向、参考仓位区间、确定性拆分、波动率、第一行动
和稳定 token；它 MUST 不产生第十条综合策略，也不得反向改变 BUILD/CLEAR。13 格不可达 warning 分支与周日
16 组合保持其解释 identity；第一版不调用外部 LLM。

证据状态 MUST 与功能结果分离为 `ACTIVE_CODE_VERIFIED / RESEARCH_EVIDENCE_ONLY / EVIDENCE_REQUIRED /
OUT_OF_SCOPE`。缺原始证据的阈值、评分、排序或诊断映射 MUST 标为 `EVIDENCE_REQUIRED` 并阻塞该功能的
精确复刻验收；不得用通用技术分析、0 分或“暂无信号”填补。其他已验证功能可以独立交付。

#### Scenario: Only a research summary is available

- **GIVEN** 某评分只有汇总匹配率而缺可核对的完整规则或输入
- **WHEN** 恢复其产品功能
- **THEN** 标记 `EVIDENCE_REQUIRED` 并阻止该功能被验收为精确复刻，不用通用指标知识补分支

### Requirement: Keep retrospective display outside trade authority

照妖镜 MUST 保持 `repainting=true / formal_signal_eligible=false`，只在独立回看副图显示，不进入
BUILD/CLEAR、ReferenceTrade、胜率、综合交易动作或历史当时可知 Hint。杯柄 SHALL 保持既有 D1 clean-room
identity 与确认时间语义；`pivot_at` 不得冒充首次可知时间，其他周期为 `NOT_APPLICABLE`。

组件公式 parity、期货输入适配、参考交易政策和证据包可重放性 MUST 分别声明；completed-only、换月中断、
统计窗口与本合同收益摘要不属于证券页面原样行为，整个产品不得笼统标记 `page_parity=true`。

#### Scenario: Retrospective marker changes

- **GIVEN** 照妖镜随新增 Bar 重绘历史图形
- **WHEN** 刷新页面
- **THEN** 只更新标明回看的图层，不改 ReferenceTrade 的 BUILD/CLEAR 与收益，也不把回绘点写为当时的交易原因
