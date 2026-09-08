# SuBing THS Alert Specification

## Purpose

定义新的 `subing_ths_alert_15m_v1` 研究观察产品：只对 completed actual_dominant 15m 按
`subing_ths_15m_v3` 公式创建 immutable AlertEvent、最多尝试一次通知，并由 Market Web 提供人工复核。
它不恢复 `subing_strategy_v1`，不创建持仓或订单，且 `auto_order=false`。

## Requirements

### Requirement: Identity and input are exact

Rule identity SHALL 为 `subing_ths_alert_15m_v1`，public name SHALL 为“苏冰预警”，kind SHALL 为
`indicator_observation`，formula version SHALL 为 `subing_ths_15m_v3`。输入 MUST 仅为 operational Scope
内、由 `MainContractMap rank=1` 证明的 completed `actual_dominant` 15m Bar；preview、未完成 Bar、其它周期、
continuous 或错误物理合约 MUST fail closed。

#### Scenario: A completed rank1 15m Bar arrives

- **WHEN** Rule enabled、symbol × 15m 在 Scope 内且 completed Bar 与 current rank1 physical contract 一致
- **THEN** single Alert Runtime dispatch 到 SuBing evaluator，且只以该 Bar 为本次候选 cutoff

#### Scenario: Input identity cannot be proven

- **WHEN** completed、frequency、rank1 mapping、physical contract 或 coverage 任一不可证明
- **THEN** 不创建 Event，不跨频或回退 continuous

### Requirement: The formula has one exact authority

`SubingThs15mKernel` SHALL 是唯一 Candidate authority，并按以下固定公式计算：

```text
DIFF = EMA(CLOSE, 12) - EMA(CLOSE, 26)
DEA = EMA(DIFF, 9)
MACD = 2 * (DIFF - DEA)
EMA21 = EMA(CLOSE, 21)

BUY = previous_DIF <= previous_DEA
      AND current_DIF > current_DEA
      AND CLOSE > EMA21
SELL = previous_DIF >= previous_DEA
       AND current_DIF < current_DEA
       AND CLOSE < EMA21
```

EMA seed MUST 为 `sma_window`，histogram scale MUST 为 `2`，projection MUST 使用六位确定性值。
`CLOSE == EMA21`、当前 `DIFF == DEA`、warm-up 不足、invalid input 或同 Bar 双向结果 MUST 不触发并
fail closed。API、notification formatter 与 Web MUST NOT 复制 Candidate 公式。

#### Scenario: Exact golden cross passes EMA21

- **WHEN** previous DIF ≤ DEA、current DIF > DEA 且 current close > current EMA21
- **THEN** Kernel 只返回 `buy`

#### Scenario: Exact dead cross passes EMA21

- **WHEN** previous DIF ≥ DEA、current DIF < DEA 且 current close < current EMA21
- **THEN** Kernel 只返回 `sell`

### Requirement: V1 has no hidden filters

Candidate Gate MUST NOT 使用零轴、MACD 柱强弱、Range Detector、成交量、OI、ATR、EMA21 斜率、
Daily Watch、5m/30m/60m/D1 共振、评分、胜率或其它历史过滤。任何新增过滤 MUST 使用新的 formula
version，不得静默修改 `subing_ths_15m_v3`。v3 与 v2 的数学公式相同，但 v3 只接受 session 锚点修正后的
正式 Bar、completed time 与 Candidate；不得把旧锚点结果标记为 v3。

#### Scenario: An optional study disagrees with the exact formula

- **WHEN** exact CROSS + EMA21 条件成立而任一被禁止的辅助指标不成立
- **THEN** 辅助指标不得阻止 SuBing Candidate

### Requirement: Warm-up and reconciliation stay within one physical contract

首次观察、重启、漏 Bar 或 rank1 rollover 后，evaluator SHALL 只通过 typed Market read seam 重建当前物理
合约从上市有效期到 cutoff 的 15m prefix。递归 cursor MUST 以 symbol + physical contract 隔离；换月 MUST
丢弃旧合约状态。中间 Bar 只推进状态，只有当前 trigger cutoff 可返回 Candidate，禁止历史 backfill。
physical Canonical 的第一页 MUST 从 latest page bootstrap（`before=None`）开始，再严格裁剪为
`after < bar_end <= cutoff`；这不得放宽 `MarketDataService` 的 identity、coverage 或物理可读性合同。缺少
同合约 lifecycle prefix MUST 以 `MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE` fail closed，不得以当日 Live、
continuous 或前一合约替代。

#### Scenario: Rank1 contract rolls

- **WHEN** current actual-dominant owner 与 cursor contract 不同
- **THEN** evaluator 从新合约自己的有效历史重建，不继承旧合约 EMA/MACD 状态

#### Scenario: Downtime contains an earlier cross

- **WHEN** replay prefix 中的早期 Bar 有 Candidate、当前 cutoff 没有
- **THEN** evaluator 只推进 cursor，不为早期 Bar 创建 Event

#### Scenario: Canonical stops at the prior completed day

- **WHEN** cutoff 位于当日 completed Live，而同物理合约 Canonical 只覆盖至最近完整交易日
- **THEN** latest-page bootstrap 读回历史前缀并与同合约 Live 严格合并；Canonical future tail 不进入 Kernel

#### Scenario: Physical history is absent

- **WHEN** 当前 rank1 physical contract 没有可证明的 lifecycle Canonical prefix
- **THEN** evaluator 不创建 Event，且不以 Live-only 或跨合约 warm-up 降级

### Requirement: Live recovery cannot create historical notifications

当日受控 Live recovery MUST 默认关闭且只恢复已验证同物理合约的 completed observation，不发布历史
completed-Bar 消息。恢复后的窗口 MUST 携带同一次读取的 recovery revision 与提交水位；水位与订阅
身份在窗口读取、replay 后及 Event 准备前 MUST 一致。cutoff 不晚于恢复水位的旧/积压触发 MUST 不创建
Event、不发送通知；只有之后新到达的 completed Bar 才可继续正常评估。中间 Bar 仅推进同合约状态，
不改变公式或 Event identity。

Live recovery 最终提交与 Alert 窗口读取至 Event commit/one-shot send MUST 使用同品种进程间互斥。
该锁 MUST 随进程退出释放，不以可在 Event commit 中途到期的租约替代。启用恢复前 MUST 证明 Live、
Alert 的 exact Runtime root/version 与恢复开关一致；发布或 Runtime promotion 不隐含恢复启用授权。

#### Scenario: An old trigger remains queued when recovery completes

- **WHEN** trigger cutoff 不晚于恢复提交水位，包含进程重启后的重复触发
- **THEN** Event 和通知计数不增加，同 Rule 当前错误不能因跳过而被错误清除

#### Scenario: A new completed Bar crosses after recovery

- **WHEN** trigger cutoff 晚于恢复水位且同合约完整输入通过既有校验，公式产生当前 Candidate
- **THEN** 先提交唯一 Event，再最多一次 transport；重复触发、重启和 provider 失败均不补发

#### Scenario: Recovery races with an admitted Alert

- **WHEN** Alert 正在读取窗口、提交 Event 或发送一次通知
- **THEN** 同品种 recovery 不得提交新水位；反向顺序时 Alert 必须读到已提交水位并拒绝旧触发

### Requirement: Event modes and identity remain distinct

HTDY Rule SHALL 保持 forward-only `first_seen`；SuBing Rule SHALL 使用 `exact`。SuBing Event identity SHALL
为 `(rule_id, symbol, frequency, bar_end)`；重复创建只有在 contract、trading_day 与 result_codes 完全一致时
返回 no-op，事实冲突 MUST fail closed。Event 创建后不可改写方向、时间或合约。

#### Scenario: The same exact Event is observed again

- **WHEN** 相同 identity 与相同冻结事实再次出现
- **THEN** 不新增 Event、不重发通知

#### Scenario: The same identity carries different facts

- **WHEN** 相同 identity 的 contract、trading_day 或 result_codes 不同
- **THEN** 系统报告 consistency failure，不覆盖既有 Event

### Requirement: Event persistence precedes one-shot transport

系统 MUST 先 commit AlertEvent，随后才可调用该 Rule 固定 formatter、固定 audience 与 shared PushPlus
transport；每个新 Event 最多一次 transport attempt，无 retry、queue、outbox、replay、backfill、fallback
或逐收件人状态。formatter、taxonomy、transport 或 provider acceptance 失败 MUST 保留 Event。
provider accepted MUST NOT 表述为微信实际送达。

#### Scenario: Transport fails after Event commit

- **WHEN** Event 已持久化而 formatter 或 transport 失败
- **THEN** Event 仍可由 Web 读取，Runtime 记录公开失败且不自动 retry

### Requirement: Web is Event-backed and adds no SuBing overlay

Market Home 与 `/market/chart` 的正式 SuBing 预警 facts SHALL 只从 typed Alert Event API 获取。实际主力 15m 图上可显示
Event-backed `S↑/S↓` marker 并按正式 `bar_end` 定位；Overlay 仍只允许 `none | htdy`，不得增加 SuBing
通用 overlay、复制 BUY/SELL 公式、发起 O(N) per-product 请求或产生写入。专用页面的历史参考 SHALL 使用下面的独立只读接口和来源标记，不冒充 Event。

#### Scenario: A SuBing Event is opened from Market Home

- **WHEN** 用户点击一条 SuBing Event
- **THEN** Web 打开对应 symbol、actual_dominant、15m 与 bar_end 供人工复核，不推导交易动作

### Requirement: 0044 seeds a disabled empty Rule and generic writes stay guarded

Forward-only `20260902_0044` SHALL 只在精确 0043 HTDY-only schema 上新增一条
`subing_ths_alert_15m_v1` Rule，且 `enabled=false`、`scope_product_frequencies={}`；它 MUST 保留 HTDY Rule/Event，
不得硬编码 operational universe，downgrade MUST 拒绝。通用 Scope API MUST 在任何 Scope mutation 前拒绝
disabled Rule。

#### Scenario: 0044 succeeds on exact 0043 state

- **WHEN** isolated PostgreSQL 的 Rule/Event schema 与 0043 postflight 精确一致
- **THEN** upgrade 后恰有 HTDY + disabled empty-scope SuBing 两条 Rule，既有 HTDY facts 不变

#### Scenario: Generic scope write targets disabled SuBing

- **WHEN** caller 经通用 API 尝试写 SuBing symbol × frequency Scope
- **THEN** 返回公开 disabled-Rule error 且数据库保持 empty scope

### Requirement: 0045 normalizes the RQData session anchor forward-only

Forward-only `20260903_0045` SHALL 只在精确 0044、恰好两条 Rule、SuBing disabled + empty scope 且
零 SuBing Event 的状态上，把既有 RQData 1m session 首根 `bar_end` 标签减一分钟，转为
`SessionWindow(start, end]` 的排他 start。它 MUST 保留两条 Rule 与既有 HTDY Event，不修改、删除或回放
任何 Event；downgrade MUST 拒绝。

#### Scenario: 0045 normalizes real provider labels

- **WHEN** RQData session start 为 `09:01/10:31/13:31/21:01`
- **THEN** upgrade 后 start 精确为 `09:00/10:30/13:30/21:00`，session 不重叠且 Rule/Event facts 不变

### Requirement: First activation is one atomic dedicated operation

专用 `guiyi runtime subing-ths-scope` seam SHALL 从 execution-time `operational_products.txt` 构造排序后的
symbol × 15m Scope。无 `--apply` 时 MUST 零数据库 mutation 并返回 count/hash；`--apply` 时 MUST 只在精确
0045、恰好两 Rule、HTDY snapshot 合法且 SuBing disabled + empty scope 的 preflight 后锁定两 Rule，在一次
transaction 同时写 full Scope 与 `enabled=true`，commit 后精确 readback。任何并发、持久化或 readback
异常 MUST fail closed，不得留下部分 Scope。

#### Scenario: Dry-run plans first activation

- **WHEN** operator 未传 `--apply`
- **THEN** 返回 stable sorted count/hash、`enabled=false` 与 readonly=true，Rule 不变

#### Scenario: Apply loses the preflight state

- **WHEN** lock 后 Rule、revision 或 Scope 不再匹配 preflight
- **THEN** transaction rollback 并返回公开 preflight/persist failure，不部分启用

### Requirement: Compatibility precedes production activation and every external Gate stays separate

外部顺序 SHALL 为 session-anchor repair、exact-tag Runtime readback、重新执行 `G10` 同花顺兼容性只读
evidence，最后才是 `G9` production Scope activation + Rule enable。
G10 至少核对两个品种、可获得时五个金叉与五个死叉的 direction、completed bar time、CROSS、Close/EMA21
与主力合约；不发 PushPlus、不启用 Rule、不写 Scope。G9 及 production migration、release/main/tag、Runtime
promotion、真实通知、provider acceptance 与微信实际送达均是彼此独立的 owner Gate；测试、dry-run、代码、
配置存在或历史授权不能替代任何一次真实 mutation 意图。

#### Scenario: Compatibility evidence is missing or inconsistent

- **WHEN** G10 尚未完成或样本差异未解释
- **THEN** G9 不得执行，Rule 保持 disabled + empty scope

#### Scenario: Code and tests pass

- **WHEN** implementation、full verification 与 independent review 完成
- **THEN** 结论最多为允许进入 release candidate，不能声明 RELEASED、RUNTIME_READY、真实通知或业务闭环

### Requirement: Runtime aggregate health preserves current rule errors

聚合Alert health MUST 检查两条Rule当前error_type；任一Rule仍为evaluation_failed等当前错误时，
不能因进程运行或aggregate旧字段为ok而显示整体健康。后续成功eval清空当前error_type后可以回绿，
Rule的last_failure_at MUST 保留，现有全局失败事实继续按原合同保存；不新增Rule历史分类或计数字段。
不得用历史失败永久阻止回绿，也不得把回绿宣称自然Event或通知已完成。

#### Scenario: Successful evaluation follows a previous failure

- **GIVEN** Rule保留last_failure_at，但成功eval已清空当前error_type
- **WHEN** 计算聚合health
- **THEN** 允许当前health为ok并继续呈现历史失败；若error_type仍存在则不能回绿


### Requirement: Historical reference uses the existing formula and an independent model

苏冰专用历史参考 SHALL 复用唯一 `SubingThs15mKernel` 和 `subing_ths_15m_v3`，不得恢复已退役策略。
参考模型 SHALL 为 `subing_reference_reverse_close_v1`：首次 buy 开多、首次 sell 开空；反向信号在同一已完成
信号 Bar close 平仓并反手，同向信号不加仓、不重置入场。参考身份 MUST 绑定品种、物理合约、rank1 segment、
公式、参考模型及入场信号，平仓显式关联入场；不得依赖显示窗口或最近标记猜测。
历史参考 SHALL 标记 `source=historical_replay`、`executable=false`、`auto_order=false`，不创建 Event、订单、
持仓账本、通知或 Scope 写入，也不声明牛哇公式 parity、因果回测或账户收益。

#### Scenario: A reverse signal follows an open reference

- **WHEN** 同合约同 segment 内已有多头参考并出现 sell
- **THEN** 使用该 completed Bar close 平多并开空，signal 同时关联已平和新开的 reference_trade_id；空头到 buy 对称处理

#### Scenario: The same direction occurs again

- **WHEN** 参考方向未变化而出现同向有效信号
- **THEN** 保留该历史信号及既有参考身份，不创建第二笔交易或变更入场价格

### Requirement: Historical reads prove the selected completed window

历史参考 SHALL 只通过现有 `MarketDataService`、rank1 segment loader、Calendar 和 Session 读取 Canonical，
不读取 Live、不下载或补写。默认最近 20 个完成交易日由完整 Calendar/Session 决定，不以现有数据回退；
显式日期区间 MUST 完整读取，结束日为已完成交易日，单请求跨度最多 365 个日期间隔。
每个 owner SHALL 读取并验证自己的完整物理 lifecycle prefix，状态不跨合约继承；只有 owner 有效期间可输出信号。
前段结束、Session、映射、Calendar、Bar coverage 或物理事实冲突 MUST 整个参考面 fail closed，不能缩短窗口。

#### Scenario: Calendar tail or an owner final day is missing

- **WHEN** Calendar 覆盖不完整，或任一物理合约的主力有效末日 Bar 缺失
- **THEN** 返回不可用，不能把更早日期当作完整请求结果

#### Scenario: Ownership changes

- **WHEN** 后续 owner 的 Session 起点已生效
- **THEN** 前段未平参考成为 ROLLOVER_INTERRUPTED，无 synthetic exit 或已平收益；新 owner 独立 warm-up 和建仓

### Requirement: Reference arithmetic and statistics are explicit

价格和收益 MUST 使用独立固定 Decimal context（28 位、ROUND_HALF_EVEN）；费用与滑点为零。
多头收益为 `(exit-entry)/entry*100`，空头为 `(entry-exit)/entry*100`。
OPEN 只用本合约已完成 Bar 标记浮动；中断记录不生成退出价格、已平收益或当前浮动，不制造窗口末端平仓。
统计 SHALL 只包括窗口内新开且已平的交易；期初已有、OPEN 和 ROLLOVER_INTERRUPTED 单独分组，
已在窗口开始前结束的中断记录不返回。汇总包含胜/负/平、胜率、平均收益和收益简单相加百分点，不称复利净值。

#### Scenario: Paging or chart zoom changes

- **WHEN** 用户翻交易页或缩放 K 线
- **THEN** 相同窗口和输入的信号、交易身份与汇总不变，游标绑定窗口、cutoff 和完整输入 hash；输入改变要求重新读取

### Requirement: Historical reference API and visual sources stay distinct

`GET /api/v1/market/{symbol}/subing/reference` SHALL 固定 actual_dominant/15m，接受 `since`、`through`、
`as_of`、`before`、`limit`（默认 50，最大 200）；拒绝未知/重复 query、未来或无时区截止。
返回 typed signal/trade/summary、窗口、cutoff、版本和 input_snapshot_hash；价格/收益为十进制字符串。
单进程 SHALL 最多一个计算和 30 秒协作式检查预算，不落盘派生缓存，不输出内部错误详情。
图表 SHALL 显示可避让的白底细边框价格/平仓收益标注，空间不足收起为可交互标记；只锚定匹配的时间与物理合约。
列表 SHALL 显示方向、状态、合约、开平时间价格、持有 Bar 数和参考收益，点击记录定位对应 Bar。
历史与实际 Event MUST 分别保留身份、来源和详情；刷新/切换窗口撤销旧参考详情，迟到响应不得覆盖新身份。

#### Scenario: Historical data is unavailable but actual events exist

- **WHEN** 历史参考查询失败而 Event API 有已保存预警
- **THEN** 历史面明确显示不可用，日期仍可编辑；实际预警入口保留，不伪造历史参考或 Event
