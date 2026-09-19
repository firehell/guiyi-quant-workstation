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

恢复缺失 1m 的请求 MUST 在领取 provider 尝试预算前校验带时区的当前时钟与冻结 cutoff，只有
`0 <= now - cutoff <= 60 秒` 时才允许领取预算及查询。已过期、未来或无时区时钟 MUST 以
`LIVE_RECOVERY_CLOCK_INVALID` 拒绝，不初始化 provider、不消耗尝试预算、不写 Bar 或水位；后续请求
仍由前台下一轮正常调度重新采集 authority，后台 MUST NOT 刷新 cutoff、扩大预算或补发旧通知。
查询实际开始后发生超时仍计一次尝试，最终提交 MUST 在共享锁内再次检查同一60秒边界。

#### Scenario: A recovery request expires behind other products

- **WHEN** 单worker处理前序品种后，后排缺口请求已经超过冻结cutoff的60秒有效期
- **THEN** 后排请求在领取预算和查询前失败关闭，已有预算保持不变
- **AND** 后续前台新鲜请求可使用剩余预算恢复；恢复后旧触发仍不能创建Event或通知

#### Scenario: A provider query starts fresh but finishes too late

- **WHEN** 请求在有效时效内领取预算，查询或等待提交锁后已超过60秒
- **THEN** 已消耗的尝试不撤销，Bar和恢复水位不提交，不扩大预算或静默重试

正常 Live 的同品种 completed 1m、ready heartbeat、发布与派生写入/发布 MUST 与恢复初始快照、最终
提交共用同一进程间锁；不同品种 MUST NOT 被同一次持锁串成全局临界区。锁忙时 MUST 保留 pending，
不得丢弃正常 Bar 或把锁忙报告为 Redis 故障。恢复调度 MUST 位于本轮正常 ingest/flush 收尾之后，
已有 completed pending 的品种 MUST 暂缓恢复，纯 BREAK、provider cooldown 或订阅失败不得新增调度。
provider 查询 MUST 保持锁外；提交锁内 MUST 重读订阅、state 与各周期前像，拒绝旧事实删除/改写或身份
漂移，对与查询源一致的正常追加重新计算缺口。全部缺口已消失时 MUST 返回 NO_GAP，不推进水位；
否则仍以重读前像执行严格 Lua CAS，并在重算后检查原 cutoff 的提交时效。真实派生缺口仍可无 provider 修复。

#### Scenario: Normal completed bars arrive during a recovery query

- **WHEN** provider 查询期间正常 Live 写入与查询源完全一致的 Bar，冻结订阅和原事实均未改变
- **THEN** 恢复在提交锁内重读并只提交剩余缺口，不因一致追加浪费后续尝试
- **AND** 若前台已补齐所有周期，则返回 NO_GAP，不创建恢复水位、不改变正常通知资格

#### Scenario: A normal derived bucket is being completed

- **WHEN** 前台已写入最后一根 1m、尚未完成当前 5m/15m/60m 桶的正常派生和发布
- **THEN** 恢复不得观察并修复该临界区的中间态，正常 Bar 完成后仍保有原通知资格
- **AND** 因锁忙保留的 completed pending 不得在本轮被恢复线程抢先生成

#### Scenario: Releasing the normal Live guard fails

- **WHEN** 正常 Bar 已完成写入及发布，但退出共享锁时发生异常
- **THEN** Live MUST 报告不可用、保留已完成事实，不重放 Bar、不丢弃健康 provider 或安排 provider 重连
- **AND** 只有获取阶段的 busy 可以视为普通等待；锁拥有者 MUST 先显式解锁并在 finally 中关闭一次 fd，
  解锁失败仍执行关闭，不根据 close 异常盲目重关可能已被复用的 fd

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

### Requirement: Event reads preserve the requested frequency

`GET /api/alerts/events` SHALL 接受可选 `frequency`；省略时保持原查询行为，传入时 MUST 校验该 Rule 的
支持周期并在数据库查询中精确过滤。不支持的周期 MUST 返回明确 4xx，不能退回全周期结果。
Web 持久 Event 查询 SHALL 携带当前页面周期，并继续对 Rule、symbol、frequency 不一致的响应失败关闭；
切换页面身份后，旧异步响应不得覆盖新身份的数据。本接口不修改既有 Event、Scope 或公式。

#### Scenario: One Rule has observations at two frequencies

- **WHEN** 同一品种同一 Rule 有 5m 与 15m Event，页面查询 5m
- **THEN** 只返回 5m Event；合法的 15m Event 不应令 5m 页面整体不可用

### Requirement: Event persistence precedes one-shot transport

系统 MUST 先 commit AlertEvent，随后才可调用该 Rule 固定 formatter、固定 audience 与 shared PushPlus
transport；每个新 Event 最多一次 transport attempt，无 retry、queue、outbox、replay、backfill、fallback
或逐收件人状态。formatter、taxonomy、transport 或 provider acceptance 失败 MUST 保留 Event。
provider accepted MUST NOT 表述为微信实际送达。
transport 失败 SHALL 在既有有界 Runtime 日志中仅记录固定白名单诊断码，并用 `rule_code`、`symbol`、
`contract`、`frequency`、`bar_end` 关联已保存 Event；不得记录 provider message/body、URL、token、通知正文、
原始异常或 cause。SDK 明确返回拒绝码时可分类为 provider rejected，`900` 分类为 rate limited；SDK 的
`-1` 或无法证明请求结果的异常必须保守分类为 request outcome unknown，无法安全分类时回落 `UNKNOWN`。
诊断分类不得改变 schema v6 聚合状态、通用 `notification_transport_failed` 兼容语义或发送次数。
单次或连续 PushPlus 投递失败属于保留的通知诊断事实，不得仅凭 `notification_state=failed` 把
Alert operational health、Runtime aggregate health 或每日盘后增量数据结果判为失败/降级。
`last_notification_failure_at`、`notification_error_type` 与失败次数仍须可读；formatter 准备失败、
sender acceptance 无效、未分类 sender 异常、通知配置缺失、
heartbeat/Rule 评估异常、到期 coverage 缺口，以及盘后行情和质量失败继续按各自合同降级或阻断。

#### Scenario: Transport fails after Event commit

- **WHEN** Event 已持久化而 formatter 或 transport 失败
- **THEN** Event 仍可由 Web 读取，Runtime 记录公开失败且不自动 retry

### Requirement: Shared Alert transport and configuration stay bounded

HTDY Topic audience SHALL 由 PushPlus 外部人工维护，范围不得超过 owner + 三位朋友；系统 MUST NOT 读取成员
清单或声明精确送达人数。Git 外通知配置 SHALL 只包含 message token 与 HTDY Topic code；父目录 MUST 是当前
用户所有的 `0700` 目录，配置文件 MUST 是当前用户所有的 `0600` 普通文件。结构 health MUST NOT 联网或发送。
配置、所有权或权限不满足合同 MUST fail closed，不得借 fallback、retry 或其它 transport 放宽。

#### Scenario: Notification configuration is structurally invalid

- **WHEN** 配置包含额外通知身份、路径所有权不符、父目录不是 0700 或文件不是 0600 普通文件
- **THEN** health 报告公开配置错误且不联网、不发送、不自动修复权限

### Requirement: HTDY observation preserves frequency and forward-only facts

HTDY 五个日内周期 SHALL 只消费同周期 completed Live Bar；D1/W1 SHALL 只响应
`market:state(reason=canonical_updated)` 并读取 Canonical，不新增 scheduler、Scope 表或 Live 日/周聚合。
日内 evaluator 使用最后 32 根前，MarketRead SHALL 以 Calendar、逐日 Session 与逐 Bar rank1 owner 证明
从首根到 cutoff 的预期端点精确相等。午休、周末、夜盘归属和短 Session 尾桶只按 authority 解释；缺失、
重复、额外、错误 trading_day 或 owner 均 MUST fail closed。当日 MainContractMap 尚未发布时可使用同一次读取
冻结的 Live rank1 identity，但历史日 owner 仍必须来自 MainContractMap；不得缩窗、补值或改读 continuous。
共享预警窗口 MUST 通过 typed `LiveBarObservation` 保留并逐根校验 Live payload contract、trading_day
和端点唯一性，读取范围 MUST 不晚于事件 cutoff。缺失、错误或非规范的合约身份 MUST 拒绝，
不得丢弃原始 contract 后以冻结 snapshot 为其补写身份；历史多 owner 窗口仍按 MainContractMap 校验。
Canonical 历史前缀的选择 MUST 截止于事件 cutoff，但前缀端点校验只覆盖已发布历史；不得在合并 Live
之前要求当前交易日已有历史 MainContractMap 或 Canonical。共享 `bars_until` MUST 在合并后验证整个
返回窗口的 Calendar/Session/owner 端点；历史尾部缺失、Live 缺失或重叠冲突均拒绝。普通历史分页
继续按请求 cutoff 严格校验，不允许借此将 Live 视作 Canonical。
forward-only `first_seen` 只接受触发窗口的最新 completed Bar；Kernel repaint zone 中的历史 Bar 仅供
Web retrospective 研究展示，不创建持久 Event 或通知。
`AlertEvent.bar_end` SHALL 是观察 Bar 时间，`detected_at` SHALL 是 Runtime 首次识别时间；Event 冻结后，
重绘消失、重现或方向变化均不得改写或重发。startup、repair、replay、backfill 与 EOD recalculation MUST NOT
创建历史 HTDY Event 或通知。

#### Scenario: Published history precedes the current Live trading day

- **WHEN** 日盘或夜盘的 completed Live cutoff 已到达，而当前交易日 MainContractMap 尚未盘后发布
- **THEN** Alert 合并经过验证的历史前缀和 frozen Live owner，按交易日归属校验完整窗口后才运行评价
- **AND** 周五夜盘归属下一交易日、换月和历史/Live 间隙使用相同规则，不合成映射或 Bar

#### Scenario: A 5m, 15m or 60m context has an internal Session gap

- **WHEN** cutoff 仍存在且窗口数量仍足够，但 Calendar/Session/owner 预期端点中有一根缺失
- **THEN** Kernel 不运行，Rule 记录公开评价失败，Event 与通知均不增加

#### Scenario: An actual-dominant context crosses a legal owner boundary

- **WHEN** 历史日 owner 由 MainContractMap 证明、当日 frozen owner 有效且每个 Session 端点完整
- **THEN** HTDY 可保留跨物理合约的 actual-dominant 策略窗口，不强制退化为单合约预热

#### Scenario: A Live payload disagrees with the frozen owner

- **WHEN** HTDY 5m、15m或60m窗口包含错误/缺失contract、错误trading_day或重复Live端点
- **THEN** 共享MarketRead返回`MARKET_READ_LIVE_UNAVAILABLE`，不以snapshot覆盖payload身份，不运行Kernel或创建Event/通知

#### Scenario: A daily or weekly Canonical update is observed

- **WHEN** 收到 `canonical_updated` 且对应 D1/W1 completed Canonical 可读
- **THEN** HTDY 只评估该周期的 current prefix，不聚合 Live、不补评更早 Candidate

#### Scenario: A historical repaint candidate appears

- **WHEN** retrospective Kernel 结果在 repaint zone 出现、消失或变向
- **THEN** Web 可展示回看结果，但既有 Event 不改写且不创建历史通知

### Requirement: Web is Event-backed and adds no SuBing overlay

Market Home 与 `/market/chart` 的正式 SuBing 预警 facts SHALL 只从 typed Alert Event API 获取。实际主力 15m 图上可显示
Event-backed `S↑/S↓` marker 并按正式 `bar_end` 定位；Overlay 仍只允许 `none | htdy`，不得增加 SuBing
通用 overlay、复制 BUY/SELL 公式、发起 O(N) per-product 请求或产生写入。专用页面的历史参考 SHALL 使用下面的独立只读接口和来源标记，不冒充 Event。

页面 MUST 将以下四类事实分开呈现：当前品种的 Scope、全局 Rule/Runtime 状态、全局最近评价，以及当前品种
精确匹配的已存 Alert Event。全局最近评价不得冒充当前品种评价；当前品种没有 Event 不等于中性信号，也不
证明公式已评价。若现有接口没有提供当前品种的即时策略状态，页面 MUST 明示“当前接口未提供”，不得从
Scope、Rule、全局评价或历史 reference 推导。所有 Event 与评价时间按北京时间展示并保留原始 instant。

#### Scenario: A SuBing Event is opened from Market Home

- **WHEN** 用户点击一条 SuBing Event
- **THEN** Web 打开对应 symbol、actual_dominant、15m 与 bar_end 供人工复核，不推导交易动作

#### Scenario: The current product has no stored Event

- **GIVEN** SuBing Rule 已启用且全局最近评价成功，但当前品种没有精确匹配的 stored Event
- **WHEN** 用户查看该品种详情
- **THEN** 页面分别显示 Scope、Rule/Runtime 与全局评价，并明确当前品种无已存 Event
- **AND** 页面不得显示中性策略状态或把全局评价时间标成当前品种评价时间

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

### Requirement: Market operational health and Alert diagnostics are independent

Runtime operational health v2 SHALL aggregate only DB, Redis, Live market and after-market incremental maintenance.
Alert processing, Rule, coverage, transport and notification configuration failures SHALL remain visible in the Alert
component but SHALL NOT degrade the top-level operational health. Optional weekly audit remains independent.
Fresh, available Live with all operational products explicitly CLOSED and complete phase counts SHALL be operationally
healthy despite unverified coverage after cleanup or a closed-session restart. Coverage MUST remain unverified;
this exception MUST NOT hide known lagging, stale/missing/future heartbeats, unavailable connections, or unverified
coverage during trading or unknown/incomplete phases. After-market failure/missed/stuck/invalid-state semantics remain unchanged.

#### Scenario: Closed Live and completed increments with Alert failures

- **WHEN** DB/Redis are healthy, Live heartbeat is fresh and available with all products CLOSED, and the expected after-market increment passed
- **THEN** top-level health is ok even if Live coverage is unverified and Alert processing or notifications failed; diagnostic evidence remains unchanged

### Requirement: Alert component health preserves current rule errors

Live and Alert heartbeats SHALL additionally expose bounded per-product coverage for the operational Scope. Live coverage MUST retain the first unresolved completed 1m endpoint even if a later Bar arrives. Alert coverage MUST be keyed by Rule, product and enabled frequency; a successful evaluation for one key MUST NOT erase another key's failure. Alert component health SHALL distinguish due data lag from evaluation lag using Session-derived Live frequency endpoints and a fixed evaluation budget. Legacy heartbeats lacking coverage SHALL be `unverified`, not evidence that every Scope item is healthy. These health projections MUST NOT create or retry Events, transport messages, or historical repairs, and MUST NOT alter the `alert:runtime-status` v6 notification record.
When the Live subscription snapshot is absent, current-day coverage SHALL be `unverified`, including after authorized cleanup unless a separate persisted completion fact proves it. An unresolved prior-day Live gap or prior-day Alert evaluation failure SHALL remain visible across a trading-day change. D1 evaluation coverage MAY use a successful after-market trading day as its source deadline. W1 coverage SHALL not infer a new weekly deadline from an ISO week change alone; it requires a completed trading week in the exchange Calendar, and absent W1 Canonical completion proof remains `unverified`.

#### Scenario: One operational product stops while peers continue

- **WHEN** a completed endpoint for one product remains unresolved beyond its due budget while another product publishes later Bars
- **THEN** aggregate health is degraded and names the stalled product without declaring the entire transport unavailable

#### Scenario: A Rule evaluates one product but not another

- **WHEN** the second product has a due completed input and no successful evaluation
- **THEN** Alert health identifies that Rule, product and frequency as evaluation lagging despite the first product succeeding

聚合Alert health MUST 检查两条Rule当前error_type；任一Rule仍为evaluation_failed等当前错误时，
不能因进程运行或aggregate旧字段为ok而显示整体健康。后续成功eval清空当前error_type后可以回绿，
Rule的last_failure_at MUST 保留，现有全局失败事实继续按原合同保存；不新增Rule历史分类或计数字段。
不得用历史失败永久阻止回绿，也不得把回绿宣称自然Event或通知已完成。

#### Scenario: Successful evaluation follows a previous failure

- **GIVEN** Rule保留last_failure_at，但成功eval已清空当前error_type
- **WHEN** 计算聚合health
- **THEN** 允许当前health为ok并继续呈现历史失败；若error_type仍存在则不能回绿

#### Scenario: A failed or warming SuBing cutoff is delivered again

- **WHEN** evaluator 已推进同合约 kernel 状态但该 cutoff 未完成一次成功评价，随后收到相同 trigger
- **THEN** 重复项作为 typed skip，不更新成功评价时间、不清当前 Rule/global failure，也不重跑 Event 或通知

#### Scenario: An older contract arrives after a newer accepted cutoff

- **WHEN** 新主力窗口已成为该 symbol 的最新 identity，随后收到更早 cutoff 或旧合约 trigger
- **THEN** evaluator 单调跳过，不恢复旧合约 cursor、不产生历史 Candidate

### Requirement: Runtime failure classification preserves the failing boundary

`ALERT_RECOVERY_GUARD_UNAVAILABLE` SHALL 只表示 recovery guard 获取或释放失败。DB、evaluator、Event、status
或编排体异常 SHALL 保留为 processing/rule failure，不能伪报 guard；任何日志只包含 bounded public code 与
既有允许身份，不输出 provider、SQL、地址、stack 或凭据。Event commit 后的状态失败 MUST 阻止 sender，
且不得借重复 trigger 重试 Event 或清除失败。

#### Scenario: Event commits and runtime status then fails

- **WHEN** Event 已 commit，但随后的 status/CAS 写失败
- **THEN** Event 保留、sender 不调用，日志为 processing failure 且没有 guard failure；相同 Bar 不补发

### Requirement: Runtime status and acknowledgment stay bounded

`alert:runtime-status` SHALL 写 schema v6，只保留通用 Alert 状态与两条固定 Rule 各四个 bounded health 字段；
兼容读取 v1-v5 时 SHALL 丢弃已退役策略字段，并为空缺 Rule health 填充空状态。notification acknowledgment
MUST 以当前 failure timestamp 做一次精确 CAS，保留原失败、公开分类与计数，不重放或补发；同一 timestamp
内出现任何新 failure MUST 原子清空 acknowledgment。状态写失败或并发事实变化 MUST fail closed。

#### Scenario: Acknowledgment races with a new failure

- **WHEN** acknowledgment 的 failure timestamp 已不再精确匹配，或同一 timestamp 内出现新 failure
- **THEN** CAS 不得掩盖新事实，acknowledgment 保持未应用或被原子清空，且不触发重放或补发


### Requirement: Historical reference uses the existing formula and an independent model

苏冰专用历史参考 SHALL 复用唯一 `SubingThs15mKernel` 算法；15m 保持 `subing_ths_15m_v3`，
30m、60m、1d 分别使用 `subing_ths_30m_v1`、`subing_ths_60m_v1`、`subing_ths_1d_v1`。
参数按各周期 Bar 数计算，不按分钟换算；新增周期只用于历史研究，不得恢复已退役策略或扩大正式 Alert Rule。
参考模型 SHALL 为 `subing_reference_reverse_close_v1`：首次 buy 开多、首次 sell 开空；反向信号在同一已完成
信号 Bar close 平仓并反手，同向信号不加仓、不重置入场。参考身份 MUST 绑定品种、物理合约、rank1 segment、
周期、公式、参考模型及入场信号，平仓显式关联入场；不得依赖显示窗口或最近标记猜测。
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
不读取 Live、不下载或补写。日内默认最近 20 个完成交易日、1d 默认最近 120 个完成交易日，
均由完整 Calendar/Session 决定，不以现有数据回退；
显式日期区间 MUST 完整读取，结束日为已完成交易日，单请求跨度最多 365 个日期间隔。
每个 owner SHALL 读取并验证自己的完整物理 lifecycle prefix，状态不跨合约继承；只有 owner 有效期间可输出信号。
前段结束、Session、映射、Calendar、Bar coverage 或物理事实冲突 MUST 整个参考面 fail closed，不能缩短窗口。
完整输入若仍未满足指标预热，SHALL 返回 `warming`，不得把零交易解释为已计算无信号。

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

`GET /api/v1/market/{symbol}/subing/reference` SHALL 固定 actual_dominant，`frequency` 缺省 15m，
仅接受 15m、30m、60m、1d；接受 `since`、`through`、
`as_of`、`before`、`limit`（默认 50，最大 200）；拒绝未知/重复 query、未来或无时区截止。
返回 typed signal/trade/summary、窗口、cutoff、版本和 input_snapshot_hash；价格/收益为十进制字符串。
用于展示 EMA21/MACD 的逐 Bar 值 SHALL 来自同一次物理合约前缀内核重放，并带物理合约身份；
图表不能用当前已加载 K 线另行初始化指标作为苏冰信号依据。
单进程 SHALL 最多一个计算和 30 秒协作式检查预算，不落盘派生缓存，不输出内部错误详情。
图表 SHALL 显示可避让的白底细边框价格/平仓收益标注，空间不足收起为可交互标记；只锚定匹配的时间与物理合约。
列表 SHALL 显示方向、状态、合约、开平时间价格、持有 Bar 数和参考收益，点击记录定位对应 Bar。
历史与实际 Event MUST 分别保留身份、来源和详情；刷新/切换窗口或周期撤销旧参考详情，
迟到响应不得覆盖新身份。30m、60m、1d 不读取或展示仅支持 15m 的苏冰 Event/Scope/Runtime 事实，
并标为历史研究、本周期未启用预警。

#### Scenario: Historical data is unavailable but actual events exist

- **WHEN** 历史参考查询失败而 Event API 有已保存预警
- **THEN** 历史面明确显示不可用，日期仍可编辑；实际预警入口保留，不伪造历史参考或 Event

### Requirement: D1 quality segments are versioned and re-warm independently

仅 D1 历史参考 SHALL 通过显式 opt-in MarketDataService seam 消费
`ValidCanonicalBar | PRICE_UNAVAILABLE | NONPOSITIVE_CLOSE` 的完整端点互斥集合，并使用
`subing_reference_reverse_close_quality_segment_v2`。未知缺口、重复端点、Session/Map/owner/identity 冲突
或未知分类 MUST 整体 fail closed。全零价格属于 `NONPOSITIVE_CLOSE`，不得推导为 `NO_TRADE`。

owner segment 身份 SHALL 绑定物理合约与权威 owner 起点；calculation segment 身份 SHALL 绑定 1d、品种、
物理合约、owner 起点、质量策略版本、前置不可变 break 身份及首根有效 Bar。owner 终点、未来追加映射和
全局变化 revision MUST NOT 改写已有前缀身份。break 后不得继承指标、previous CROSS 状态或未平参考。

第 1–33 根有效 Bar SHALL 为 `WARMING`，第 34 根为
`INDICATOR_READY_CROSS_UNEVALUABLE`，第 35 根起为 `CROSS_EVALUATED`。质量 break 处未平交易 SHALL
成为 `DATA_INTERRUPTED`，且无退出信号、退出价、收益或当前浮动；统计须与 `ROLLOVER_INTERRUPTED` 分列。
15m/30m/60m、正式 15m Rule/Event/Scope/通知/Runtime 继续使用既有合同。

#### Scenario: A proven quality break follows an open D1 reference

- **WHEN** 当前 D1 calculation segment 有未平参考，随后出现已证实的质量 break
- **THEN** 该参考成为 DATA_INTERRUPTED 且清空退出和当前浮动字段；下一有效 Bar 从全新状态重新预热

#### Scenario: Future mapping data is appended

- **WHEN** 同一历史前缀之后追加 owner 终点、后续 owner 或有效 Bar
- **THEN** 已完成 owner/calculation segment、信号和交易身份保持不变
