# Alert 可靠性优先与苏冰盯盘 15m V1 Spec

状态：`SPEC_READY_FOR_USER_REVIEW`

日期：2026-08-31

规划基线：`develop@7c4d33cbdd4fb7e4eed3d2b8054124f238f9b07b`

设计 ID：`alert_reliability_subing_watch_15m_v1`

候选 Rule code：`subing_watch_15m_v1`

正式名称：`苏冰盯盘`

## 1. 文档职责

本文件定义归一量化下一版本的优先产品闭环：

```text
可信 completed Live Bar
→ 每个应处理 15m 边界可证明
→ 简单、透明的苏冰盯盘候选
→ immutable AlertEvent
→ one-shot PushPlus
→ 用户打开图表并人工判断
```

本版本先解决两件事：

1. 系统必须能区分“所有应处理品种均已评估但没有信号”与“系统没有完整运行”；
2. 苏冰的正式通知面回归一个无需持仓状态、无需 1m/5m 协同、可逐 Bar 复核的 15m 观察公式。

本文件是设计合同，不是 active canonical。只有实现、测试、独立 Review、用户批准 release、production migration、Runtime promotion，并取得自然运行证据后，才按职责更新：

- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- `docs/ARCHITECTURE.md`
- Alert deep canonical / OpenSpec
- `STATUS.md`

本 Spec 不授权真实数据库写入、Scope 修改、真实通知、`main`、tag、release 或 Runtime 操作。

## 2. 背景与问题陈述

归一量化的稳定产品定位已经是：

```text
可信行情 → 研究观察 → Alert → 人工判断
```

当前偏差不在长期定位，而在开发优先级和可观测性：

- Alert heartbeat 可以证明进程还活着，但不能证明每个应处理 15m 边界均已完成；
- 全局 `last_processed_bar_at` 不能证明 active operational universe 中每个应处理品种均被处理；
- 没有 Event 时，用户无法直接判断是“正常无信号”、Scope 未覆盖、数据未到、计算失败，还是触发消息被漏掉；
- 当前 `subing_strategy_v1` 的 Live 路径依赖 1m/5m/15m、Daily Context、增量策略状态、物理段 continuation、Action 和 Episode，复杂度已经超过“收到预警后人工判断”的最低产品目标；
- 2026-08-31 的 v1.9.7 Runtime promotion 因 `live_unavailable / last_bar_at=null` fail-closed 回滚，生产 Runtime 回到 v1.9.6；同日 `STATUS.md` 的 release commit 与 GitHub 当前 `main`、annotated tag、GitHub Release 事实又不一致。

因此，下一版本不得继续以增加策略条件或新策略数量为首要目标。第一优先级必须是：

> 先证明系统在盯盘，再优化系统提醒什么。

## 3. 事实冲突与前置阻塞

规划时读取到：

```text
STATUS.md:
v1.9.7@b3efda13347570d25ddb25b41c0737b6751fb37f

GitHub main / annotated tag / latest GitHub Release:
v1.9.7@66c3be8035774a510e914e80a11e4669b15d42ab
```

该冲突不在本设计 PR 中顺手修正。原因：

- `STATUS.md` 是当前 release、Runtime、Scope 与 evidence 的事实文档；
- release identity 修正应基于一次单独的事实核对；
- 不能把产品设计和当前部署事实修正混入同一提交。

在任何下一次 release 或 Runtime promotion 前，必须先由独立小任务完成：

1. 核对 `main`、annotated tag、GitHub Release、API/Web version；
2. 核对当前五项 launchd service 的 exact root；
3. 只修改 `STATUS.md` 中被真实证据支持的当前事实；
4. 不借该任务切换 Runtime、发送通知或修改生产状态。

## 4. 产品原则

### 4.1 核心价值

苏冰盯盘不是自动交易策略，也不是仓位管理器。它只负责：

```text
在值得用户打开图表时提醒
+ 提供少量可解释上下文
+ 保留最终买卖决定给用户
```

正式产品承诺按优先级排序：

1. **不静默失效**：缺失、失败和未评估必须可见；
2. **信号可复核**：用户能从同一根 completed 15m K 线复算；
3. **消息不过度解释**：只陈述触发事实和上下文，不给出“应当下单”的结论；
4. **简单优先**：V1 不引入持仓、Action 生效价、Episode、加减仓和多周期硬门控；
5. **人工 Gate**：AI、Codex 和 Runtime 均不能自动晋升公式、发布版本或下单。

### 4.2 版本完成定义

本版本只有同时满足以下条件，才可在 `STATUS.md` 中宣布闭环：

```text
CODE_COMPLETE
+ TEST_COMPLETE
+ independent Review approved
+ RELEASED
+ production migration completed
+ RUNTIME_READY
+ natural 15m boundary evidence
+ at least one natural Watch Event transport attempt
+ owner manually confirms one real WeChat delivery
```

其中：

- release 批准与 Runtime promotion 批准是两个独立 Gate；
- production migration 是独立真实写入 Gate；
- owner canary 与自然业务消息不是同一证据；
- provider accepted 不是微信送达证据。

## 5. 方案选择

### 5.1 采用方案：可靠性账本 + 简单观察 + 解释标签

采用以下纵向闭环：

```text
A. Session-aware 15m 边界账本
B. 苏冰盯盘基础观察公式
C. 只读上下文标签
D. Historical / Live Shadow
E. forward-only Rule replacement
F. Web 状态与消息
G. release / migration / Runtime / natural evidence
```

### 5.2 未采用方案

#### 继续修补当前复杂苏冰并直接作为正式提醒

不采用为下一版本主线。当前复杂策略保留研究价值，但其状态依赖过多，不能继续作为“最容易证明正确”的日常盯盘基线。

#### 新建独立脚本绕开现有 Market/Alert

不采用。它会复制主力合约、交易时段、Live Bar、Scope、去重、PushPlus 和 health，形成第二套不可信事实链。

#### 一次加入大周期、震荡、量能、零轴和突破硬过滤

不采用。V1 先保留基础触发，附加上下文但不吞信号。后续是否升级为硬过滤，只能依据实际 review 标签和独立版本研究决定。

#### 引入 queue、retry、outbox 或 fallback

不采用。V1 保持 Event-first、one-shot transport。先把每一层事实显式化，不用重试掩盖根因。

## 6. 产品身份与现有能力关系

### 6.1 新正式观察

```text
public_name: 苏冰盯盘
rule_code: subing_watch_15m_v1
formula_version: subing_watch_15m_v1
policy_id: subing_watch_15m_v1
kind: indicator_observation
scope_authority: product
series_kind: actual_dominant
frequency: 15m
completed_bar_only: true
repainting_risk: none
auto_order: false
```

### 6.2 现有 `subing_strategy_v1`

现有复杂苏冰：

- 保留 Historical Projection；
- 保留 Current Strategy 只读能力；
- 保留 Market Web 研究展示和历史效果；
- 不修改既有公式、Action、Episode 或历史口径；
- 在新 Rule 完成 production replacement 后，不再是正式 Alert Runtime 通知 owner 的 Rule；
- 不删除其源码、研究快照或 Git lineage。

### 6.3 HTDY

HTDY 保持完全独立：

- Rule code 仍为 `htdy_original_15m`；
- Scope 仍是 `symbol × frequency`；
- forward-only first-seen repaint observation 语义不变；
- Topic、audience、Event identity 和 one-shot transport 不变；
- 本版本不得以修苏冰为由扩展 HTDY 当前生产 Scope。

### 6.4 不新增长期第三条 Rule

稳定 production 仍只保留两条 Rule：

```text
htdy_original_15m
subing_watch_15m_v1
```

不长期并存：

```text
subing_strategy_v1
subing_watch_15m_v1
```

Shadow 阶段的新观察不依赖新 DB Rule，不写 `AlertEvent`、不发送通知。

## 7. 基础观察公式

### 7.1 用户来源公式

```text
DIFF = EMA(close, 12) - EMA(close, 26)
DEA  = EMA(DIFF, 9)
MACD = 2 * (DIFF - DEA)
MA21 = MA(close, 21)

BUY  = CROSS(DIFF, DEA) AND close > MA21
SELL = CROSS(DEA, DIFF) AND close < MA21
```

原公式中的：

```text
幅度
偏移
DRAWTEXT
```

只用于指标子图箭头位置，不属于观察条件。

原公式画出零轴，但没有把“靠近零轴”写成 BUY/SELL 的硬条件。V1 不得偷偷加入零轴门槛。

### 7.2 固定参数

```text
source = close
decision_frequency = 15m
ma_type = simple_moving_average
ma_period = 21
macd_fast = 12
macd_slow = 26
macd_signal = 9
macd_histogram_scale = 2
ema_seed_policy = sma_window
round_digits = 6
```

`ema_seed_policy=sma_window` 是归一量化 V1 的固定政策，原因是仓库当前 Quant Core 与 Web 兼容政策已经支持该 seed，并可用同一增量内核证明 batch/Live parity。

这里的 `MA21` 固定为 **21 期简单移动平均线（SMA21）**，不是现有苏冰 Overlay 中的 EMA21。实现、API、消息和图表都不得用 EMA21 冒充 MA21。

实现不得为了 Watch 直接把通用 Web MACD definition 全局升级为 `live_capable=true`。应由 Watch 的正式 formula policy 精确 pin `12/26/9 + sma_window + histogram_scale=2`，只给 Watch consumer 授权。

用户给出的公式没有说明同花顺内置 EMA 的初始化细节。因此：

- 本版本称为“按公式 clean-room 实现”；
- 不声明与同花顺所有历史 Bar 字节级一致；
- 若后续取得同花顺导出的逐 Bar DIFF/DEA/信号样本，只用于 source compatibility 验证；
- 若验证要求改变 seed，必须创建 `subing_watch_15m_v2`，不能改写 V1。

### 7.3 CROSS 精确定义

对连续、同一物理合约的 completed 15m Bar `t-1` 与 `t`：

```text
golden_cross_t =
    DIFF[t-1] <= DEA[t-1]
and DIFF[t]   >  DEA[t]

dead_cross_t =
    DEA[t-1] <= DIFF[t-1]
and DEA[t]   >  DIFF[t]
```

等价地，死叉也可写为：

```text
DIFF[t-1] >= DEA[t-1]
and DIFF[t] < DEA[t]
```

观察真值表：

```text
BUY_t =
    golden_cross_t
and close[t] > MA21[t]

SELL_t =
    dead_cross_t
and close[t] < MA21[t]
```

必须满足：

- `BUY_t` 与 `SELL_t` 不能同时为真；
- `close == MA21` 不产生观察；
- DIFF/DEA/MA21 任一未 ready、invalid 或非有限值时，该 Bar 为 `source_unavailable`；
- 未完成 Bar 不计算正式观察；
- 相同 completed Bar 重复到达必须为 idempotent no-op。

### 7.4 Warm-up 与物理段

每个 rank1 物理合约段独立维护观察状态：

- MA21、MACD、previous DIFF/DEA 在物理段开始时重置；
- 不使用上一主力合约的递归状态触发新合约观察；
- 只有 DIFF、DEA、MA21 和 previous DIFF/DEA 全部 ready 后才允许观察；
- 物理段第一根 Bar 永远不产生 CROSS；
- 不跨合约比较 `t-1` 与 `t`；
- Runtime restore 从当前物理段起点确定性重放 Canonical completed 15m，再接续同合约 completed Live 15m；
- 不允许用固定值、前值、其他周期或 continuous dataset 静默填充 warm-up。

按当前 `sma_window` MACD 政策，V1 应以 Quant Core 实际 ready 标志为权威，不在应用层复制“第几根开始 ready”的第二套算法。

## 8. 观察事实合同

每个 completed 15m Bar输出一个 `SubingWatchEvaluation`：

```text
formula_version
symbol
contract
segment_start_trading_day
trading_day
frequency
bar_end
source_mode
source_identity_digest
outcome
observation_types
close
ma21
dif
dea
macd_histogram
context
```

`outcome` 只能为：

```text
evaluated_no_signal
evaluated_candidate
source_unavailable
processing_failed
```

`observation_types`：

```text
()
("buy",)
("sell",)
```

禁止：

- `action_id`
- `strategy_payload`
- position
- pending action
- effective open
- Episode
- PnL
- “建多”“建空”“清多”“清空”

Candidate 的稳定观察 ID：

```text
sha256(
  formula_version
  + symbol
  + contract
  + segment_start_trading_day
  + frequency
  + bar_end
  + observation_type
)
```

该 ID 先用于 Shadow 对账。正式 AlertEvent 仍使用 Alert Domain 的唯一约束，不新建第三张业务表。

## 9. 解释标签

解释标签只帮助用户减少看盘后的初步判断，不参与 V1 BUY/SELL 真值表。

### 9.1 15m 必选标签

```text
ma21_slope_5_bps_per_bar
distance_to_ma21_atr14
macd_zero_distance_atr14
volume_ratio_20
range_state
```

定义：

```text
ma21_slope_5_bps_per_bar
= 最近 5 个 valid MA21 点的线性回归斜率 / 当前 MA21 × 10,000

distance_to_ma21_atr14
= (close - MA21) / ATR14

macd_zero_distance_atr14
= max(abs(DIFF), abs(DEA)) / ATR14

volume_ratio_20
= current_volume / mean(previous 20 completed 15m volumes)
```

`range_state` 读取已有 `range_detector_lux_v1` 的因果状态，公开值：

```text
range_unavailable
no_active_range
intact
broken_up
broken_down
```

### 9.2 高周期可选标签

允许读取截至当前 15m cutoff 已完成的最近一根 60m Bar，生成：

```text
higher_timeframe_alignment =
    aligned
    opposed
    neutral
    unavailable
```

判断仅使用 60m close 相对 60m SMA21 和 SMA21 slope。对当前 Candidate 方向：

```text
aligned:
  60m price side 与 slope 同时支持 Candidate 方向

opposed:
  60m price side 与 slope 同时支持 Candidate 的反方向

neutral:
  其余已就绪组合

unavailable:
  source / warm-up / identity 不可用
```

15m `MA21` 文案：

```text
向上: slope > 0
向下: slope < 0
走平: slope == 0（按固定 round_digits 后）
不可用: slope 未 ready 或 invalid
```

严格要求：

- 60m 标签缺失不得阻止基础 15m Candidate；
- 60m 必须是 completed Bar；
- 不允许读取 cutoff 之后完成的 60m；
- 不用 5m 作为基础信号确认；
- 不用 Daily Context 作为基础信号 Gate。

### 9.3 标签失败策略

基础公式 ready、但某个解释标签不可用时：

- Candidate 仍可成立；
- 对应标签值为 `unavailable`；
- 消息不得省略失败而伪装为同向或非震荡；
- 标签异常不得污染基础 evaluator state。

## 10. Historical 与 Live 共用内核

唯一公式 authority 是纯增量内核：

```text
initial_state(source_identity)
step(state, completed_15m_bar)
→ next_state + SubingWatchEvaluation
```

必须由同一个 `step` 支持：

- Historical segment replay；
- Current read-only projection；
- Live Runtime；
- restart restore；
- Shadow comparison；
- test fixtures。

禁止：

- Historical 单独使用 pandas 向量公式，而 Live 复制另一套逻辑；
- Web 重新实现正式 BUY/SELL；
- notification formatter 重新判断公式；
- AlertEvent 反向作为 evaluator state authority。

## 11. Session-aware 15m 边界账本

### 11.1 目的

边界账本回答：

```text
这一个 15m 边界，哪些品种本来应该处理？
哪些已经处理？
哪些正常无信号？
哪些产生候选？
哪些数据不可用？
哪些计算失败？
哪些触发消息根本没有到达？
```

它不是交易账本，不记录订单、持仓或资金。

### 11.2 Boundary identity

```text
BoundaryKey:
  trading_day
  frequency = 15m
  bar_end
```

同一 `bar_end` 可能只对部分 operational products 构成正式 15m boundary。不能固定要求每次都是 `60/60`。

### 11.3 Expected set

`expected_symbols` 必须由以下权威共同解析：

```text
operational_products.txt
+ TradingCalendar
+ TradingSession
+ formal 15m bucket
+ current trading day
```

禁止：

- 用“实际收到多少消息”反推 expected；
- 用全 operational 60 作为所有时段固定分母；
- 在休市、午休、无夜盘时段伪造 missing；
- 用其他品种 Session 代替当前品种 Session。

### 11.4 Per-product boundary state

每个 expected symbol 在一个 BoundaryKey 中最终只能为：

```text
evaluated_no_signal
evaluated_candidate
source_unavailable
processing_failed
missing_trigger
```

`missing_trigger` 只能在 boundary finalize 时产生，表示在 arrival grace 内未收到该 expected symbol 的对应 completed 15m 触发。

### 11.5 Finalize

复用现有 Alert Runtime heartbeat loop 完成 finalize，不新增 scheduler。

Boundary 在以下任一条件成立时 finalize：

1. 所有 expected symbol 已出现终态；
2. `now >= bar_end + existing shared Live arrival grace`。

finalize 后：

- 相同 symbol 的迟到重复消息不能改写已冻结结果；
- 可记录 `late_duplicate_count`；
- 不回填 Event、不补发通知；
- 若迟到消息证明此前 `missing_trigger`，只增加新的诊断事实，不能把旧 boundary 伪装成当时已正常完成；
- 重启不能将 startup drain 变成自然 Event。

### 11.6 Boundary summary

```text
schema_version
runtime_instance_id
boundary
finalized_at
expected_count
evaluated_count
no_signal_count
candidate_count
source_unavailable_count
processing_failed_count
missing_trigger_count
event_created_count
event_deduplicated_count
transport_attempt_count
provider_accepted_count
notification_failure_count
normal_silence
candidate_ids
public_reason_codes
```

计数不变量：

```text
expected_count
=
no_signal_count
+ candidate_count
+ source_unavailable_count
+ processing_failed_count
+ missing_trigger_count
```

```text
evaluated_count = no_signal_count + candidate_count
```

本账本中的 Event、transport 和 acceptance 计数只统计 `subing_watch_15m_v1`，不得混入同一时刻的 HTDY 事实。

正式启用后：

```text
event_created_count <= candidate_count
event_deduplicated_count <= candidate_count
transport_attempt_count <= event_created_count
provider_accepted_count <= transport_attempt_count
```

Shadow 阶段：

```text
event_created_count = 0
transport_attempt_count = 0
provider_accepted_count = 0
```

### 11.7 正常静默

`normal_silence=true` 当且仅当：

```text
expected_count > 0
and evaluated_count == expected_count
and no_signal_count == expected_count
and candidate_count == 0
and source_unavailable_count == 0
and processing_failed_count == 0
and missing_trigger_count == 0
```

以下都不是正常静默：

- boundary 尚未 finalize；
- expected set 不可解析；
- 只有部分品种评估；
- 数据 unavailable；
- evaluator failed；
- trigger missing；
- 有 Candidate 但 Event 未创建；
- 有 Event 但 transport 未尝试。

### 11.8 公开 reason code

仅允许固定、脱敏 code，例如：

```text
BOUNDARY_EXPECTATION_UNAVAILABLE
LIVE_TRIGGER_MISSING
SOURCE_WINDOW_UNAVAILABLE
SOURCE_IDENTITY_INVALID
PHYSICAL_SEGMENT_PENDING
EVALUATION_FAILED
EVENT_PERSIST_FAILED
NOTIFICATION_PREPARATION_FAILED
NOTIFICATION_TRANSPORT_FAILED
NOTIFICATION_ACCEPTANCE_INVALID
```

不得写入：

- token
- Topic code
- provider reference
- SQL
- stack trace
- 文件系统私有路径
- 原始异常正文

## 12. Runtime 状态存储

新增独立、短 TTL 的 Redis public status：

```text
key: alert:watch-runtime-status
schema_version: 1
ttl_seconds: 90
```

独立 key 的原因：

- 不改变当前 `alert:runtime-status` rollback compatibility；
- Watch boundary schema 可以独立演进；
- 旧 Runtime 读取不到新 key 时只表示 `unobserved`，不能伪造健康；
- 不把 boundary history 塞入现有单一全局时间戳。

Payload 只保留：

```text
generated_at
runtime_instance_id
mode
formula_version
latest_finalized_boundary
recent_boundaries
recent_candidates
current_open_boundaries
```

边界：

```text
mode = shadow | active
recent_boundaries <= 8
recent_candidates <= 20
current_open_boundaries <= 4
```

这不是永久审计存储。永久业务事实仍只有正式 `AlertEvent`。Boundary status 过期即表示当前 Runtime 无可读证明，不创建 PostgreSQL 第三张表。

## 13. Alert Domain 与 Rule replacement

### 13.1 解耦 Rule kind 与 Scope authority

当前实现把：

```text
indicator_observation → product_frequency scope
strategy_action       → product scope
```

写成隐式绑定。新 Watch 是 observation，但应使用 product scope。

Rule metadata 必须显式拆成：

```text
kind:
  indicator_observation
  strategy_action

scope_authority:
  product
  product_frequency
```

固定组合：

```text
HTDY:
  kind = indicator_observation
  scope_authority = product_frequency

SuBing Watch:
  kind = indicator_observation
  scope_authority = product

Legacy SuBing Strategy:
  kind = strategy_action
  scope_authority = product
```

`kind` 决定 Event payload；`scope_authority` 决定 Scope 读写。两者不能继续互相推导。

### 13.2 Watch Event

正式 Watch Candidate 创建：

```text
result_codes = ("buy",) | ("sell",)
action_id = null
strategy_payload = null
frequency = 15m
bar_end = observation Bar end
detected_at = Runtime first evaluation time
notification_attempted_at = commit-first attempt time
```

Event identity 继续使用：

```text
rule_id × symbol × frequency × bar_end
```

同一 Bar 后续重算：

- 相同 Candidate：immutable no-op；
- Candidate 消失：不撤回；
- 方向变化：consistency failure，不能改写；
- replay/backfill/startup drain：不补 Event、不补通知。

### 13.3 Forward-only production migration

production migration 必须原子执行：

1. 锁定现有唯一 `subing_strategy_v1` Rule row；
2. 校验其 `enabled`、`scope_products`、`scope_product_frequencies` 与预期；
3. 删除该 Rule 既有 SuBing Strategy `AlertEvent`，防止新 Rule code 错误解释旧 strategy payload；
4. 保留 Rule row 的 `id`、`enabled` 和 `scope_products`；
5. 将 `rule_code` 改为 `subing_watch_15m_v1`；
6. 将 `scope_product_frequencies` 规范化为空对象；
7. 校验最终数据库只存在两条 code-defined Rule；
8. 不提供 downgrade，不保留 archive Rule，不保留双 Rule。

production 执行前必须：

- isolated PostgreSQL migration test 通过；
- 当前 production head 精确匹配预期；
- migration preflight 只读通过；
- 用户明确批准本次 production DB mutation。

### 13.4 单一 lineage 的 cutover compatibility

用于本次 release 的 Alert registry 必须接受以下两种数据库状态之一：

```text
pre-migration:
  htdy_original_15m
  subing_strategy_v1

post-migration:
  htdy_original_15m
  subing_watch_15m_v1
```

硬约束：

- 任一时刻只能存在其中一种 SuBing Rule row；
- 两种 SuBing Rule 同时存在必须启动失败；
- 任何第三个未知 Rule 必须启动失败；
- pre-migration 只允许 Watch shadow；
- post-migration 才允许 Watch active；
- 这是一次 forward-only cutover seam，不是长期双 reader，也不允许旧 Event 被新 Rule 解释。

### 13.5 迁移前 Shadow

在 migration 之前：

- Watch evaluator 运行于 `shadow`；
- 不需要 DB 新 Rule；
- 不创建 Watch Event；
- 不发送 Watch 通知；
- 旧 `subing_strategy_v1` 是否继续正式发信号，只服从当时 production Rule/Scope，不由 Shadow 偷偷修改；
- legacy strategy 故障不得阻断 Watch boundary accounting。

迁移之后：

- Watch 切换 `active`；
- legacy strategy evaluator 不进入 Watch/HTDY critical path；
- legacy strategy研究能力仍可由只读服务使用；
- Alert Runtime 若不能确认 DB lineage，启动 fail-closed。

## 14. 通知合同

### 14.1 Audience

```text
SuBing Watch → owner
HTDY → htdy_observers Topic
```

Watch 不传 Topic，不读取成员清单，不声明多人送达。

### 14.2 标题

```text
归一量化 苏冰盯盘
```

### 14.3 内容

多头示例：

```text
【苏冰盯盘】RB 螺纹钢

15m 多头观察
触发：MACD 金叉 + 收盘在 MA21 上方
主力：RBxxxx
观察K线：15m · HH:MM

环境：
- MA21：向上 / 向下 / 走平 / 不可用
- 60m：同向 / 逆向 / 中性 / 不可用
- 箱体：箱体内 / 无活动箱体 / 已向上突破 / 已向下突破 / 不可用
- 零轴距离：N.NN ATR / 不可用
- 距 MA21：+N.NN ATR / 不可用
- 量能：N.NN × 20根均量 / 不可用

研究观察，非交易指令
```

空头完全对称。

禁止出现：

- 买入
- 卖出
- 建仓
- 清仓
- 仓位比例
- 止损价
- 目标价
- 胜率
- 盈利承诺

方向用“多头观察 / 空头观察”，明确保留人工判断。

### 14.4 one-shot

继续保持：

```text
Event commit
→ 最多一次 transport attempt
→ provider accepted 或 fixed public failure
```

不增加：

- retry
- queue
- fallback
- replay
- backfill
- 逐收件人状态

## 15. Web 与只读诊断

### 15.1 路由

不新增顶级 route。继续使用：

```text
/market
/market/chart
/api/runtime/*
/api/alerts/*
```

### 15.2 Market 状态卡

Market 页面增加一个紧凑、只读的“苏冰盯盘”状态卡，优先显示最近一个 finalized 15m boundary：

```text
盯盘状态：正常 / 降级 / 未观察
边界：HH:MM
应处理：N
已评估：N
候选：N
不可用：N
缺失：N
通知：accepted M / attempted K
```

状态文案：

```text
normal_silence=true:
  已完整评估，本边界无候选

candidate_count>0 且 active 链路完整:
  已完整评估，产生 N 个候选

任一 unavailable / failure / missing:
  本边界不完整，请先检查 Runtime

无 public status:
  尚无可证明的盯盘状态
```

不得只显示绿色 heartbeat 而隐藏 boundary incomplete。

### 15.3 Candidate 入口

最近 Candidate 支持打开：

```text
/market/chart
?series_kind=actual_dominant
&frequency=15m
&symbol=<symbol>
&entry=subing-watch
&bar_end=<bar_end>
```

保持现有 `overlay=subing`，不增加第四个产品 Overlay。该 Overlay 可继续展示既有 EMA10/21 趋势带，但 Watch 入口必须另外显示权威 SMA21；不得把 Overlay 的 EMA21 当作 Watch MA21。Watch persistent marker 与现有 SuBing Strategy Action marker必须在文案和图形上可区分。

当前 Web 的分钟 K 线以区间开端作为视觉坐标，而 API/业务事实仍以 `bar_end` 标识。Watch 必须保持：

```text
Event / URL identity = formal bar_end
chart coordinate = existing period-aware opening-time projection
tooltip = 同时让用户看清 15m 区间与正式 bar_end
```

不得为了对齐画面而改写 Event 的 `bar_end`。

建议名称：

```text
苏冰盯盘（15m 观察）
苏冰策略 V1（研究）
```

### 15.4 图表复核

Event 入口至少显示：

- Candidate 所在 completed 15m Bar；
- Watch 权威 SMA21，标签明确为 `MA21 (SMA)`；
- MACD 子图；
- Watch persistent marker；
- Candidate message 中的固定数值。

Web 只渲染 API/Kernel 输出，不在 TypeScript 重新判断 BUY/SELL。

## 16. Historical 诊断与人工 Review

V1 的 Historical 目标是控制消息质量和验证因果，不是建立正式回测账户。

至少输出：

```text
per product candidate count
buy / sell count
candidates per trading day
same-direction clustering
session distribution
context availability rate
range_state distribution
higher_timeframe_alignment distribution
```

允许追加 research-only forward diagnostics：

```text
1 / 2 / 4 / 8 根后 close change
MFE
MAE
```

但必须满足：

- outcome 只用于 retrospective 分析；
- 不进入 Runtime；
- 不回填 Candidate；
- 不自动生成 threshold；
- 不自动筛选 winner；
- 不以 reference change 声称真实 PnL；
- 不把 retrospective 结果写成 prospective OOS。

人工 Review Gate：

- 至少 review 30 个 Historical/Shadow Candidate；
- 若整个样本少于 30，则 review 全部；
- 每个样本记录 `keep_open_chart / dismiss` 和固定理由；
- V1 不根据本轮 review 临时改公式；
- 改公式必须另建 V2 Spec。

## 17. Shadow 验收

### 17.1 最小自然窗口

Watch Shadow 至少覆盖：

1. 一个完整日盘；
2. 一次自然夜盘进入下一 trading day；
3. 一次 Runtime restart 后的首个完整 15m boundary；
4. 至少一个 `normal_silence` boundary；
5. 至少一个 Candidate；若自然窗口无 Candidate，则继续 Shadow，不能用 synthetic Candidate 代替自然信号；
6. 若自然窗口发生 rank1 切换，验证物理段 reset；若未发生，保持该 evidence pending，不伪造完成。

### 17.2 Shadow 对账

对每个 finalized boundary：

- expected set 与 Session authority 一致；
- 每个 expected symbol 恰有一个终态；
- Historical replay 到相同 cutoff 与 Live incremental Candidate 一致；
- restart 前后相同 prefix 结果一致；
- future tail 不改写过去 Candidate；
- startup drain 不创建 Event；
- Shadow counters 永远不产生 transport attempt。

### 17.3 进入 active 的条件

必须全部通过：

```text
formula tests
boundary ledger tests
full backend tests
Web tests/build
OpenSpec
secret scan
independent Sol/high Review
natural Shadow evidence
manual Candidate review
release identity conflict closed
```

## 18. Runtime、release 与真实 Gate

### Gate 0：Spec

当前 Gate。只有用户批准本 Spec，才进入 Implementation Plan。

### Gate 1：实现与 develop

- 从最新 `develop` 创建独立 task worktree；
- Lane 3，TDD；
- 独立 exact-head Review；
- 用户批准后才允许集成 `develop`；
- 不执行真实 migration、Scope、通知或 Runtime。

### Gate 2：release candidate

- canonical 与 OpenSpec 同步；
- version identity 冻结；
- CI 与本地完整验证；
- release packet 只陈述代码/测试事实；
- 不自动 merge main/tag。

### Gate 3：release

用户单独批准：

```text
release PR → main
annotated tag
GitHub Release
```

### Gate 4：Shadow Runtime promotion

用户单独批准：

- exact approved tag；
- clean detached runtime root；
- DB 仍保持旧 Rule lineage；
- Watch 只运行 shadow；
- 保留切换前 rollback root；
- 首根 completed Live Bar、heartbeat 和 boundary status 必须可读；
- 失败立即回滚，不进行 migration。

### Gate 5：production migration

完成 Shadow 后，用户单独批准一次：

- preflight；
- production PostgreSQL forward-only migration；
- readback 两条 Rule、Scope、Event count；
- 不发送通知；
- migration 成功后不得启动旧版本 Alert Runtime。

### Gate 6：Active Runtime

用户单独批准：

- exact same approved tag；
- Watch mode 切为 active；
- completed 15m boundary readback；
- no startup backfill；
- no delayed historical Event；
- HTDY non-regression。

### Gate 7：真实送达

分开核验：

1. owner canary：通道测试，不替代自然 Candidate；
2. 下一次自然 Watch Candidate：
   - Candidate；
   - immutable Event；
   - transport attempt；
   - provider accepted；
   - owner 人工确认微信收到。

完成后才可声明版本闭环。

## 19. 故障与恢复

### 19.1 fail-closed

以下任一情况禁止创建 Watch Event：

- expected set 或 Session 无法解析；
- source identity 不完整；
- current Bar 未 completed；
- Live contract 与 current physical segment 不一致；
- warm-up 不足；
- evaluator state stale；
- duplicate 与既有事实冲突；
- DB Rule lineage 不匹配；
- migration 未完成但 active mode 被请求。

### 19.2 隔离

- 单个 product source failure 只标记该 product，不阻断其他 product；
- DB/session fatal failure 不发送任何尚未提交的消息；
- notification failure 不撤销已提交 Event；
- Watch failure 不改变 HTDY Event；
- legacy strategy research failure 不阻断 Watch/HTDY；
- public status write failure使 health 降级，不能继续声称 normal silence。

### 19.3 migration 后恢复

migration 是 forward-only：

- 不回滚 DB 到 `subing_strategy_v1`；
- 旧 v1.9.7 Runtime 不再是可用 rollback root；
- active Watch 出现问题时，只能在新的明确授权下禁用 Alert Runtime 或禁用 Watch Rule，保留 Market Runtime；
- 修复版本必须读取新 Rule lineage；
- 不以手工改 Event 或重放通知恢复。

## 20. 测试合同

### 20.1 公式

必须覆盖：

- MA21 SMA；
- MACD 12/26/9 + `sma_window`；
- exact golden/dead CROSS；
- equality boundary；
- warm-up；
- invalid/non-finite input；
- same Bar duplicate；
- physical segment reset；
- cross-contract previous Bar 禁止；
- batch/incremental parity；
- prefix invariance；
- future-tail invariance；
- restart restore parity；
- fixed golden fixture。

### 20.2 上下文

必须覆盖：

- context 不改变 Candidate；
- ATR unavailable；
- volume denominator zero；
- Range unavailable；
- 60m strict-before；
- 60m missing 不阻断 Candidate；
- all formatting paths。

### 20.3 Boundary ledger

必须覆盖：

- 不同品种交易 Session；
- 日盘、夜盘、午休、无夜盘；
- expected count 非 60；
- all no-signal normal silence；
- partial arrival；
- missing trigger after grace；
- source unavailable；
- evaluator failure；
- late duplicate；
- restart；
- boundary freeze；
- counter invariants；
- public status TTL/missing；
- status write failure。

### 20.4 Alert

必须覆盖：

- Rule kind / scope authority 正交；
- HTDY product-frequency scope non-regression；
- Watch product scope；
- immutable Event identity；
- duplicate no-op；
- conflict fail-closed；
- Event-first；
- one-shot transport；
- provider accepted ≠ delivery；
- no startup/replay/backfill send；
- legacy strategy payload cannot enter Watch Event。

### 20.5 Migration

isolated PostgreSQL 必须覆盖：

- expected old head；
- exact old Rule；
- preserve row id/enabled/scope_products；
- delete old strategy Events；
- replace code；
- clear frequency scope；
- exactly two Rules；
- unexpected third Rule fails；
- malformed Scope fails；
- partial mutation atomic rollback；
- no downgrade。

### 20.6 Web

必须覆盖：

- normal silence copy；
- incomplete boundary copy；
- Candidate count；
- missing status；
- deep link；
- Watch/Strategy marker distinction；
- no hidden Scope mutation；
- mobile/narrow width；
- build。

## 21. 禁止范围

本版本明确不做：

- 自动下单；
- 订单、账户、真实持仓或资金域；
- Signal 直接转委托；
- 加仓、减仓、反手；
- 目标价、自动止损或仓位建议；
- 把 60m、D1、Range、零轴距离、量能变成 V1 硬过滤；
- 调整 HTDY 公式或生产 Scope；
- 通知 retry、queue、outbox、fallback；
- 新建通用策略平台或 UniversalStrategyAdapter；
- 新建 PostgreSQL boundary history 表；
- 让 Web 计算正式公式；
- 恢复已退役产品；
- 同时实施 `苏冰趋势策略-日`、Newow 或其他新策略；
- 未经 Gate 修改 `main`、tag、Runtime、production DB、Scope 或真实通知。

## 22. 开发优先级与暂停项

本 Spec 获批后，下一版本的唯一主线为：

```text
release identity convergence
→ boundary reliability ledger
→ Watch formula/kernel
→ Shadow
→ Web/Alert/migration implementation
→ release
→ migration
→ Runtime
→ natural delivery evidence
```

以下 active Issue/计划保持文件和 Git lineage，但暂停执行：

- `苏冰趋势策略-日` Stage A；
- Newow 趋势/震荡策略；
- 新的策略候选与参数优化；
- 额外 Alert 周期扩张。

暂停不是删除。只有本版本达到 `RUNTIME_READY` 并完成自然证据后，才重新排序后续研究。

## 23. Canonical 更新职责

实现进入 active surface 时：

### `PROJECT_SOURCE.md`

更新稳定产品面：

- 苏冰正式通知改为 observation-only 15m Watch；
- `subing_strategy_v1` 标记为只读研究；
- 增加 normal silence / boundary completeness 产品承诺。

### `DECISIONS.md`

增加：

- Alert Rule kind 与 scope authority 正交；
- Watch direct Rule replacement；
- boundary status 是短 TTL Runtime public evidence，不是业务永久表；
- context-only 不参与 V1 formula。

### `docs/ARCHITECTURE.md`

增加：

```text
Live 15m
→ Watch evaluator
→ Boundary ledger
→ Runtime public status
→ AlertEvent
→ one-shot PushPlus
```

并把 legacy strategy Runtime 从 active notification critical path 移除。

### OpenSpec

至少覆盖：

- Watch formula；
- Alert Rule metadata；
- boundary completeness；
- Runtime health projection；
- Web read-only presentation；
- migration lineage。

### `STATUS.md`

只在真实操作发生后记录：

- release identity；
- production migration；
- current Runtime exact root；
- current Rule/Scope；
- natural boundary / Event / delivery evidence；
- pending Gate。

## 24. Spec 自审记录

本设计完成后按 placeholder、内部一致性、范围和歧义四类检查。

### 24.1 已修正：固定 60/60 误判

初稿思路曾把每个 15m boundary 简化为 60/60。不同品种存在不同 Session、夜盘和休市边界，因此已改为 Session-aware expected set。只有 expected set 中的品种才计入分母。

### 24.2 已修正：解释标签吞掉基础信号

零轴、Range、量能和高周期曾可能被理解为硬 Gate。现在固定为 context-only；缺失时公开 `unavailable`，不能阻止基础 BUY/SELL。

### 24.3 已修正：第三条长期 Rule

不新增长期第三条 Rule。先 Shadow，后 forward-only 直接替换 `subing_strategy_v1` Rule row，稳定 production 仍为两条 Rule。

### 24.4 已修正：同花顺完全等价声明

来源公式没有给出 EMA 初始化细节。V1 固定仓库可复算的 `sma_window`，只声明 clean-room 公式实现，不声明与同花顺所有历史 Bar 字节级等价。

### 24.5 已修正：把 heartbeat 当作业务完成

heartbeat 只证明进程更新。`normal_silence` 现在必须由 finalized boundary、完整 expected set 和逐品种终态共同证明。

### 24.6 已修正：旧复杂策略直接删除

现有 `subing_strategy_v1` 保留研究/Web能力，仅退出正式通知 critical path；不删除公式、Historical、Current 或 Git lineage。

### 24.7 已修正：release、migration、Runtime 和送达混成一个 Gate

四类操作已经拆开：

```text
release
production migration
Runtime promotion
real delivery evidence
```

任何前一项成功都不能自动授权后一项。

### 24.8 已修正：MA21 与现有 EMA21 混淆

用户公式使用 `MA(C,21)`。现在固定为 SMA21，并要求 Watch 图表单独显示权威 SMA21；现有苏冰 Overlay 的 EMA21 不能冒充该公式输入。

### 24.9 已修正：cutover 无法兼容迁移前后数据库

release code 现在必须接受“旧 SuBing Rule 或新 Watch Rule 恰好一个”的单一 lineage 状态，以便先做同版本 Shadow、再执行 forward-only migration；双 Rule 或第三 Rule 仍 fail-closed。

### 24.10 已修正：分钟 K 线视觉时间与 Event 时间混淆

最新 `develop` 已将分钟 K 线画在区间开端，但业务 `bar.time` 仍是 formal `bar_end`。本 Spec 现在固定 Event/URL 使用 `bar_end`，图表只做现有 opening-time 视觉投影，二者不互相改写。

### 24.11 自审结论

- 无未解析 placeholder；
- 公式、Event、Scope、Runtime 和 release identity 分层明确；
- 设计足以进入一个分阶段 Implementation Plan；
- 未授权真实外部操作；
- 下一步只能是用户 review 本 Spec，不能直接开始实现。

## 25. 用户 Review 决策点

用户批准本 Spec，即表示批准以下方向，而不表示批准任何真实外部操作：

1. 下一版本暂停新策略扩张，优先完成 Alert 可靠性闭环；
2. 新正式提醒采用 `subing_watch_15m_v1`；
3. 基础公式只使用 15m MACD CROSS + MA21；
4. 其他判断第一版只作解释标签；
5. 先 Shadow，后直接替换当前 SuBing Alert Rule；
6. 稳定 production 不长期保留第三条 Rule；
7. `subing_strategy_v1` 保留为研究，不再作为正式 owner Alert；
8. 版本必须以自然 boundary 与真实送达证据闭环。
