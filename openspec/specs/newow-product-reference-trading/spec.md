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

产品实现 MUST 服从下列完整能力矩阵；“三策略 × 三周期完整”不表示每个辅助能力可机械复制到全部组合。
每个实际输出 MUST 携带适用的 formula/rule identity、输入周期、`bar_end`、请求 `as_of`、warming 与
repaint/evidence 状态。表中的 `ACTIVE_CODE_VERIFIED` 只表示 BASE 保留源码和测试入口，不表示本阶段已经
完成产品包装；`RESEARCH_EVIDENCE_ONLY` 必须先恢复并核对冻结原件再实现；`EVIDENCE_REQUIRED` 必须阻塞
对应子功能验收。若证据没有证明某能力的 repaint 属性，响应 MUST 标为 unavailable，而不是默认非重绘。

| 能力 | 适用策略与周期 | formula identity | evidence status | warming / repaint / as-of 边界 |
|---|---|---|---|---|
| 趋势主状态 | `trend × 1w/1d/60m` | `newow_trend_band_page_v2` | `ACTIVE_CODE_VERIFIED` | completed 本周期、同物理区段 warm-up；BUILD/HOLD/CLEAR/FLAT 不跨合约继承 |
| 震荡主状态 | `oscillation × 1w/1d/60m` | `newow_oscillation_hhv_llv10_page_v1` + `newow_hhv_llv_channel_page_v1` | `ACTIVE_CODE_VERIFIED` | completed 本周期、同物理区段 warm-up；HHV/LLV10 与同 Bar `CLEAR → BUILD` |
| 主升浪主状态 | `main_rise × 1w/1d/60m` | `newow_main_rise_ma35_ma45_page_v1` | `ACTIVE_CODE_VERIFIED` | completed 本周期、同物理区段 warm-up；MA35/MA45 主动作不由 Hint 改写 |
| S 跑 / D1–D3 | `trend/main_rise × 1w/1d/60m`，Hint only | `newow_escape_d123_page_v2` | `ACTIVE_CODE_VERIFIED` | 必须报告公式所需 warming 与已验证 repaint 属性；只使用当时 completed 输入，不改变 BUILD/CLEAR |
| D4–D6 | `main_rise × 1w/1d/60m`，Hint only | `newow_buy_d456_page_v1` | `ACTIVE_CODE_VERIFIED` | 同物理区段、当时 completed 输入；Low×0.99 仅为显示锚点，不产生加仓 |
| J 风险 | `main_rise × 1w/1d/60m`，Hint only | `newow_main_rise_j_reduce_page_v1` | `ACTIVE_CODE_VERIFIED` | 同物理区段、当时 completed 输入；不推导减仓比例 |
| 4/7/11 | `main_rise × 1w/1d/60m`，结构 Hint | `newow_magic11_page_v1` | `ACTIVE_CODE_VERIFIED` | 按物理区段重置；不得产生独立 Action |
| 主力控盘副图 | 三策略 × `1w/1d/60m`，共享解释层 | `newow_main_force_control_page_v1` | `ACTIVE_CODE_VERIFIED` | 必须报告公式 warming 与已验证 repaint 属性；“主力”不证明真实持仓或席位 |
| 主力照妖镜副图 | 三策略 × `1w/1d/60m`，retrospective only | `newow_zhaoyao_mirror_repainting_page_v1` | `ACTIVE_CODE_VERIFIED` | `repainting=true / formal_signal_eligible=false`；不进入 Hint、Action、ReferenceTrade、收益或历史 as-of 事实 |
| 涨跌动能副图 | 三策略 × `1w/1d/60m`，共享解释层 | `newow_up_down_energy_page_v1` | `ACTIVE_CODE_VERIFIED` | 短区段 warming/unavailable；不得跨合约借值，且必须报告已验证 repaint 属性 |
| 杯柄 | `trend × 1d`；`1w/60m = NOT_APPLICABLE` | `newow_cup_handle_v1`，`page_parity=false` | `ACTIVE_CODE_VERIFIED`（clean-room） | 只显示 confirmed D1 witness；`pivot_at` 不是首次可知时间 |
| 目标/吸筹显示选择 | 三策略共享 `1w/1d/60m` context | `newow_target_absorb_display_selection_page_v2` | `RESEARCH_EVIDENCE_ONLY` | 实现前必须核对日/周选择、周线覆盖、昨收、clamp 与 warm-up；输出来源周期、来源 `bar_end` 与 `as_of`，只读展示不等于交易目标或真实吸筹 |
| 综合解释（13 格、方向/确定性、ATR20/Close、第一行动、周日 16 组合） | 三策略共享多周期 context | `newow_composite_decision_page_v3_2_82` 及待冻结子身份 | `RESEARCH_EVIDENCE_ONLY` | 每项输入使用各自 completed `bar_end` 与 `as_of`；不产生第十条策略或改变主动作 |
| 五窗口页面比较器 | `oscillation × 1w/1d/60m`，独立 comparator | `newow_hhv_llv_window_optimizer_page_v1` | `RESEARCH_EVIDENCE_ONLY` | 独立页面 as-of/样本假设；期末理论平仓不进入 ReferenceTrade |
| 页面诊断 token / 六组合评分映射 | 三策略共享解释层候选 | `UNFROZEN` | `EVIDENCE_REQUIRED` | 缺稳定机器合同时 unavailable；不得以“无信号”、0 分或通用知识填补 |

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
动作类型和语义参考价。内核提供 `related_marker_ids` 时 MUST 优先精确验证并使用该关联；只有内核没有
关联 ID 时，策略 adapter 才可在同一策略、周期、物理合约和有效 segment 内运行确定状态机。Web 不得
模糊搜索最近 BUILD。完全相同的 identity/content MUST 幂等去重为一项；相同 identity 但 content 不同，
或出现乱序、跨策略/周期/合约/区段关联时 MUST fail-closed。震荡同 Bar 顺序固定为 CLEAR 后 BUILD；
无法证明相对顺序的同 Bar Hint 只能作为 Bar 级提示。

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
和稳定 token；它 MUST 不产生第十条综合策略，也不得反向改变 BUILD/CLEAR。13 格 MUST 保留源页面已经确认的
原控制流及其不可达 warning 分支，周日 16 组合保持其解释 identity；任何行为修正 MUST 使用新的 clean-room
formula/rule identity 并经过独立审阅，不得覆盖或静默改写现有 page identity。第一版不调用外部 LLM。

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

### Requirement: Sectioned product delivery is computation-bounded

新的 `GET /api/v1/market/newow/strategy-detail` MUST 使用单一路由和显式
`section = chart | auxiliary | reference | explanation | comparator`；省略时仅为 `chart`，MUST NOT
提供隐式 `all`。每次请求只读取和计算该 section 的必要依赖，不能先计算整包再删掉未请求字段。

`chart` SHALL 只装配当前组合的 completed Bar、主图值、状态、有序 BUILD/CLEAR、适用 Hint 与诊断；
`auxiliary` SHALL 只计算显式选择的一个副图或杯柄；`reference` SHALL 使用完整统计输入并分页投影；
`explanation` SHALL 只读取趋势/震荡在 `1w/1d/60m` 的必要事实和 D1 波动前缀；`comparator`
SHALL 只在显式请求时运行。图表默认 500 根、单页最多 2000 根并使用严格向左时间游标；这些响应限制
MUST NOT 截断 warm-up、owner 验证、参考统计或比较器的必要计算输入。

所有 section SHALL 返回共同查询身份、实际读取身份和该 section 的真实输入指纹。响应中的五个 section
字段各自使用 `{delivery, status, value}` wrapper：请求项 `delivery=delivered` 并保留真实运行/证据状态，
四个未请求项 `delivery=not_requested, status=null, value=null`。`not_requested` 不是 Core `FeatureStatus`，
客户端 loading 也不是业务运行状态。

#### Scenario: Chart is requested before research panels

- **GIVEN** 客户端只请求默认 `chart`
- **WHEN** 服务装配响应
- **THEN** 不调用 ReferenceTrade 统计、三副图、多周期解释或比较器，主图不等待未请求研究

### Requirement: Reference cutoff is authoritative and independent of chart data

`performance_since / performance_through` SHALL 表示用户明确选择的统计 membership 窗口，并必须成对。
Reference 的实际估值/状态截止 MUST 由所选 `performance_through`、权威 Calendar/Session 与请求 `as_of`
共同解析，且不得晚于 `as_of`。服务 MUST 返回请求统计窗口、实际 `reference_cutoff`、实际可用 through
及其 availability；数据不完整、节假日、非交易日、夜盘跨自然日和未完成 W1 不得用自然日午夜、服务端
当前时间或任意一根 Bar 静默替代。

投影 MUST 以 `reference_cutoff` 重放，且 `ReferenceProjection.as_of == PerformanceWindow.cutoff`。
所有时间比较按同一 UTC instant 进行，`fact_time <= reference_cutoff <= request_as_of` 的事实可见，严格晚于
cutoff 的事实不可见；`as_of == server_now` 合法，只有 `as_of > server_now` 为 422。若 `as_of` 早于所选
through 的权威 session 完成时点，服务返回实际更早的 available through/cutoff 与降级 availability，
不得读未来或伪称完整窗口。
统计截止之后发生的 CLEAR、Hint 或 owner 边界不得进入早期快照；图表即使展示更晚行情也不得关闭早期
ReferenceTrade。显式延长统计截止后可以形成新的 CLOSED，但 reference trade identity 仍只由 entry 与
固定政策决定。viewport、chart cursor 与 `history_limit` MUST NOT 改变同一统计窗口的 summary、trade id
或 reference 指纹。

#### Scenario: A later CLEAR is visible only on the chart

- **GIVEN** BUILD 位于统计窗口内，CLEAR 晚于已解析的 reference cutoff，但图表窗口已经包含该 CLEAR
- **WHEN** 同一查询身份请求 `reference`
- **THEN** 截止时 ReferenceTrade 仍为 OPEN 且 closed_count 不增加；只有用户显式延长截止后才变为 CLOSED

#### Scenario: Night session belongs to the authoritative trading day

- **GIVEN** 夜盘 Bar 的自然日与 trading_day 不同
- **WHEN** 解析统计 membership 与 cutoff
- **THEN** 使用权威 trading_day 和 Session，不使用 `bar_end.date()`

### Requirement: Explanation inputs are server constructed and source bound

HTTP 客户端 MUST NOT 提交 evidence 对象、任意 signal 值、原件 hash 或公式参数来获得 verified 状态。
应用层 SHALL 从 ProductReader 的 completed Bar、受控 strategy replay 与 owner 上下文构造 P3 输入；每项
输入 MUST 携带 role、来源类别、公式/适配版本、周期、`bar_end`、physical contract、segment、`as_of`
和实际依赖。固定原件 hash 只证明规则来源身份，不证明当前数值来源。

可直接核验的价格 MUST 与读取的权威 Bar 值逐字段一致；不得仅以相同时间证明相同数值。页面前端、页面
API、clean-room 与归一期货适配 SHALL 分开标识；页面 API 与前端的已知冲突不得机械统一。不能从现有原件
证明来源或时机的字段 MUST 只使对应子功能 `evidence_required`/`unavailable`，并列出缺失项；不能用当前
选择的主策略状态替代综合解释的全部趋势/震荡输入。`previous_close=None` 时价格 guard SHALL 明示未激活，
并保留 raw/display 值，不能把上一根当前周期 Close 擅自称为页面昨收。

#### Scenario: Client supplies a forged evidence hash

- **GIVEN** 客户端尝试提交 evidence、signal 或 hash 参数
- **WHEN** 请求新 GET
- **THEN** 以 422 拒绝，不能因此产生 verified P3 输出

### Requirement: Snapshot reuse and bounded resources never replace validation

应用层 SHALL 分开查询身份、输入事实身份和实际读取时间。若无可靠全局 revision，
`data_revision_identity` MUST 为 null；`input_content_sha256` 仅为真实输入指纹，不是 Canonical revision 或
历史 PIT 快照。跨 section 拼接只能在共同依赖逐字段一致且相关来源版本兼容时发生。

客户端可省略 snapshot token；服务端 snapshot/cache 机制仍是 P4 必做。token MUST 是有界、进程内、不透明
且非权限凭证，绑定 product/strategy/frequency/series/as-of、共同 owner/Bar 逐事实证明和来源版本；entry namespace
只使用规范化查询身份，entry 内保存并扩充已验证的共同事实集合。跨 section 时 MUST 至少存在共同事实，且相同
frequency/contract/segment/bar_end 的 OHLCV/OI、trading_day、source identity 与 eligibility 必须逐值相等；无共同事实或
任一重叠事实冲突均拒绝。section result/dedup key MUST 另含实际 section 输入指纹与规范化参数：chart 的
from/through/cursor/page identity、auxiliary component、reference performance window 与 history cursor/page identity。
summary 可在同 reference 指纹下共享，页结果不得跨 cursor/limit 复用。TTL 固定 300 秒且只负责淘汰，不能证明新鲜度。
最多保留 32 条、总计 128 MiB、单条超过 32 MiB 不缓存，按 LRU 淘汰。旧 cursor、失效 token、数据修订或共同事实冲突 MUST 返回
可分类 409，要求客户端清除相关旧结果并重建快照；不得无限自动重试或继续旧 cursor。

失败、不完整读取和未验证结果不得缓存。关闭缓存时结果、身份和错误语义 MUST 不变。reference/comparator
共享同一个重型预算：运行并发 1、FIFO 等待队列最多 2、等待 5 秒超时；第三个等待者或超时返回429。
排队取消必须移除 waiter 并释放名额，运行阶段在安全边界释放 permit，不新增常驻 worker。取消 MUST
传至分页和安全计算边界；共享计算以相同 entry key+section result key 去重且只有最后消费者取消才停止。对不可抢占原语不得承诺
浏览器 abort 即瞬时停止，也不得跨线程共享不安全数据库 Session。

#### Scenario: A data revision invalidates a cursor

- **GIVEN** 客户端持有旧 reference cursor 或 snapshot token
- **WHEN** 服务重新验证发现共同输入事实已变化
- **THEN** 返回 409 数据世代冲突，不把旧 summary 与新图表拼接

#### Scenario: Same facts with different section parameters do not collide

- **GIVEN** 两个请求共用相同事实指纹但 component、requested window 或 cursor 不同
- **WHEN** 服务查找已验证结果
- **THEN** 不得命中另一组专属参数的 section 结果

### Requirement: Typed API keeps availability and legacy semantics explicit

新 GET MUST 只接受 active product、三策略、`1w/1d/60m`、`actual_dominant`、合法 section 及其专属参数；
日期有序、performance 成对、`as_of` 带时区且不晚于服务器当前时间。非法参数为 422；身份、数据、token
或 cursor 世代冲突为 409；资源队列满为明确 429。opaque cursor 不得作为路径、SQL 或对象反序列化入口。

wire 模型 MUST 完整传递 delivery、运行/证据/子功能状态、reason、来源、known parity difference、
repainting、formal-signal eligibility、允许用途、实际图表/统计窗口、reference cutoff、分页身份和输入
指纹。Decimal 价格与收益 MUST 序列化为十进制字符串或 null；合法零 CLOSED 的聚合指标保持 null。
顶层 ready 不得掩盖子功能 `evidence_required`，也不得把参考交易资格表达成真实下单授权。
旧 `/trend-detail` 的参数、profile、marker 和响应语义 MUST 保持不变。未预期内部错误使用固定
`500 {"detail":{"code":"NEWOW_INTERNAL_ERROR"}}`，不得返回异常文本、SQL、内部路径、stack 或凭据。

#### Scenario: A requested explanation has an evidence gap

- **GIVEN** 主策略事实可用，但某解释输入来源无法证明
- **WHEN** 请求 `section=explanation`
- **THEN** 仅对应子功能返回准确 evidence status/reason/source，不能用 0、空数组、neutral 或“暂无信号”掩盖
