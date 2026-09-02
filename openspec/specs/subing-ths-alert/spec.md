# SuBing THS Alert Specification

## Purpose

定义新的 `subing_ths_alert_15m_v1` 研究观察产品：只对 completed actual_dominant 15m 按
`subing_ths_15m_v2` 公式创建 immutable AlertEvent、最多尝试一次通知，并由 Market Web 提供人工复核。
它不恢复 `subing_strategy_v1`，不创建持仓或订单，且 `auto_order=false`。

## Requirements

### Requirement: Identity and input are exact

Rule identity SHALL 为 `subing_ths_alert_15m_v1`，public name SHALL 为“苏冰预警”，kind SHALL 为
`indicator_observation`，formula version SHALL 为 `subing_ths_15m_v2`。输入 MUST 仅为 operational Scope
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
version，不得静默修改 `subing_ths_15m_v2`。

#### Scenario: An optional study disagrees with the exact formula

- **WHEN** exact CROSS + EMA21 条件成立而任一被禁止的辅助指标不成立
- **THEN** 辅助指标不得阻止 SuBing Candidate

### Requirement: Warm-up and reconciliation stay within one physical contract

首次观察、重启、漏 Bar 或 rank1 rollover 后，evaluator SHALL 只通过 typed Market read seam 重建当前物理
合约从上市有效期到 cutoff 的 15m prefix。递归 cursor MUST 以 symbol + physical contract 隔离；换月 MUST
丢弃旧合约状态。中间 Bar 只推进状态，只有当前 trigger cutoff 可返回 Candidate，禁止历史 backfill。

#### Scenario: Rank1 contract rolls

- **WHEN** current actual-dominant owner 与 cursor contract 不同
- **THEN** evaluator 从新合约自己的有效历史重建，不继承旧合约 EMA/MACD 状态

#### Scenario: Downtime contains an earlier cross

- **WHEN** replay prefix 中的早期 Bar 有 Candidate、当前 cutoff 没有
- **THEN** evaluator 只推进 cursor，不为早期 Bar 创建 Event

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

Market Home 与 `/market/chart` SHALL 只从 typed Alert Event API 获取 SuBing facts。实际主力 15m 图上可显示
Event-backed `S↑/S↓` marker 并按正式 `bar_end` 定位；Overlay 仍只允许 `none | htdy`，不得增加 SuBing
overlay、复制 BUY/SELL 公式、发起 O(N) per-product 请求或产生写入。

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

### Requirement: First activation is one atomic dedicated operation

专用 `guiyi runtime subing-ths-scope` seam SHALL 从 execution-time `operational_products.txt` 构造排序后的
symbol × 15m Scope。无 `--apply` 时 MUST 零数据库 mutation 并返回 count/hash；`--apply` 时 MUST 只在精确
0044、恰好两 Rule、HTDY snapshot 合法且 SuBing disabled + empty scope 的 preflight 后锁定两 Rule，在一次
transaction 同时写 full Scope 与 `enabled=true`，commit 后精确 readback。任何并发、持久化或 readback
异常 MUST fail closed，不得留下部分 Scope。

#### Scenario: Dry-run plans first activation

- **WHEN** operator 未传 `--apply`
- **THEN** 返回 stable sorted count/hash、`enabled=false` 与 readonly=true，Rule 不变

#### Scenario: Apply loses the preflight state

- **WHEN** lock 后 Rule、revision 或 Scope 不再匹配 preflight
- **THEN** transaction rollback 并返回公开 preflight/persist failure，不部分启用

### Requirement: Compatibility precedes production activation and every external Gate stays separate

外部顺序 SHALL 为 `G10` 同花顺兼容性只读 evidence 先于 `G9` production Scope activation + Rule enable。
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
