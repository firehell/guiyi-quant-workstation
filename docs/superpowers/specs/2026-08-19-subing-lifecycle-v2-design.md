# SuBing Lifecycle V2 Design

- 日期：2026-08-19
- 状态：设计已确认，研究能力待实现
- 范围：SuBing 5m / 15m 研究观察生命周期
- 推荐方案：独立 `SubingLifecycleEvaluation`，复用并冻结 SuBing V1 Factor / Signal
- 政策地位：`RESEARCH_PENDING`

## 1. 结论

SuBing Lifecycle V2 采用独立评估模型，不扩写现有
`SubingSignalEvaluation`，也不先建设通用研究框架。V2 把 V1 已回答的“当前是否形成
入场观察”作为一个不可变输入，新增因果结构、生命周期状态和解释组件；所有新规则首先只在
shadow / research 路径运行，不进入现有 Alert、production Rule 或 Runtime。

V2 是市场观察生命周期，不是账户或持仓生命周期。系统不知道用户是否下单，因此状态中不出现
`POSITION`、`ORDER`、`HOLDING_REQUIRED`、`AUTO_EXIT` 或 `AUTO_ADD`，也不从状态推导任何真实交易动作。

本文使用四类来源标记：

| 标记 | 含义 |
| --- | --- |
| `EXISTING_ACCEPTED` | 当前仓库代码、测试或 accepted policy 已冻结的正式语义 |
| `SOURCE_HYPOTHESIS` | 来自用户交易系统资料、尚未成为归一量化正式政策的研究假设 |
| `NEW_DESIGN_PROPOSAL` | 本文提出的模块、数据结构、状态或接口设计 |
| `RESEARCH_PENDING` | 需要通过非重绘、样本、OOS / Walk-forward / Shadow 证据后再决定的公式或政策 |

新设计结构本身属于 `NEW_DESIGN_PROPOSAL`；其具体交易研究公式、阈值和是否晋升均属于
`RESEARCH_PENDING`。设计通过不等于政策 accepted，更不授权 Runtime promotion。

## 2. Git 与仓库事实基线

开始设计前已执行谱系检查并完成用户明确要求的 main → develop 同步：

- `main`：`957d19893187c7876b88e58f82fd5656536ee214`，对应 `v1.5.0` release；
- 同步前 `develop`：`84165ff98bfa4606916ca28f8349514c00d1ab4b`；
- 同步前 merge-base：`4d5e5c160714dcbadf27f53c61d52bbcbb76571a`；
- 同步前 `main` 不是 `develop` ancestor；
- 同步提交：`f5330a8e5341480928d5dd4c249e39cb9910fefe`；
- 同步后 `main` 是 `develop` ancestor，且 `origin/develop` 精确回读为同步提交。

本设计以同步后的 `develop` 为基线。设计不改变 active canonical 的事实或正式合同，因此不需要同时
修改 `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` 或其他 deep canonical。

## 3. SuBing V1 真实能力

### 3.1 Factor Observation

`EXISTING_ACCEPTED`：`subing_factor_observation` 在单一、已确认 K 线序列上计算：

- EMA21，初始化方式为 `sma_window`；
- 收盘价相对 EMA21 的位置；
- EMA21 最近 5 / 10 点线性回归斜率，包含原始值和 bps 表达；
- MACD `12 / 26 / 9`，初始化为 `sma_window`，缩放为 2；
- MACD 金叉、死叉及零轴距离描述；
- 当前成交量、上一根成交量及相邻成交量比值；
- 底层 `CanonicalBar` 带有持仓量事实，但 V1 Factor snapshot 不输出、accepted entry policy 也不消费
  持仓量变化。

EMA 和 MACD kernel 按输入前缀顺序计算；现有 kernel 测试已覆盖追加未来数据不改变既有点值。

### 3.2 Entry Signal V1

`EXISTING_ACCEPTED`：`subing_entry_signal_v1` 只回答当前 confirmed cutoff 是否匹配一个
LONG / SHORT 入场研究观察，输出状态为：

- `MATCHED`；
- `NOT_MATCHED`；
- `RESEARCH_PENDING`；
- `INSUFFICIENT_DATA`。

方向为 `LONG`、`SHORT` 或 `NONE`，并由模型约束状态和方向组合。

5m / 15m intraday accepted policy 的执行条件为：

- primary 收盘价位于 EMA21 正确一侧；
- primary 5 点斜率 bps 严格越过该周期 accepted 阈值；
- primary 10 点斜率方向一致；
- primary 出现 MACD 金叉或死叉；
- primary 相邻成交量比值大于等于 3；
- companion 收盘价位于 EMA21 正确一侧；
- companion 5 点斜率越过其 accepted 阈值；
- companion 10 点斜率方向一致；
- companion MACD 与成交量仅为观察值，不是 accepted gate。

accepted calibration 为 `subing_intraday_v1`：

- 5m EMA slope threshold：`0.688190651160584793944957992` bps；
- 15m EMA slope threshold：`1.329531078893356968545882036` bps。

MACD 与政策的等价身份固定为
`("sma_window", 2, "fast12_slow26_signal9", true)`。MACD 零轴距离当前只描述，不是
accepted entry gate。D1 保持 `RESEARCH_PENDING`。

### 3.3 5m / 15m resolver

`EXISTING_ACCEPTED`：`SubingReadService` 通过现有 Market Data seams 构造 current snapshot：

- historical 只走 `MarketDataService`；
- live 只走现有 `MarketReadService` seam；
- 只消费 current-rank1、segment-local 数据；
- 不使用 pre-rank1 warmup，不跨 roll 继承 EMA / MACD；
- live 只在实际合约、映射日期、segment、`bar_end` 和 `trading_day` 身份有效时合并；
- companion 只能看到不晚于 primary cutoff 的 confirmed 数据；
- 同一 boundary 互相评估；
- 同方向双 MATCH 时 15m 为 resolved signal，并标记 lower-timeframe confirmation；
- 方向冲突 fail-closed。

### 3.4 现有外部表面

`EXISTING_ACCEPTED`：

- HTTP：`GET /api/v1/market/research/subing?symbol=...&frequency=...`；
- Web：展示 V1 Factor、primary / resolved signal 与 current-rank1 identity；
- Alert：只消费 frozen V1 resolved `MATCHED`，并保留 event cutoff、5m 同 boundary 延后、
  no replay / backfill / retry 等合同；
- Calibration service：只读地计算 future horizon 3 / 5 / 8 的研究结果，不自动晋升 policy；
- V1 不写新的 SuBing 持久化表。

## 4. 当前缺口

V1 不提供以下能力：

- 无因果确认的 pivot 及 preview / confirmed 区分；
- 无在当时可知的结构区间及其有效期；
- 无突破过程组件、连续站稳过程或失败过程；
- 无回踩及二次确认表达；
- 无入场观察后的 continuation、exit-risk、invalidated、ended 生命周期；
- 无不可变生命周期事实流；
- 无针对结构与状态的完整 prefix-invariance 证明；
- 无把 5m 择时和 15m 上下文明确分层的 accepted lifecycle policy；
- 无面向结构生命周期的 Shadow / OOS / Walk-forward evidence。

这些缺口不应通过向 V1 evaluation 继续追加可选字段来解决，否则会把 frozen entry signal 和尚未接受的
生命周期政策耦合在同一个返回模型中。

## 5. V1 冻结边界

以下全部保持 `EXISTING_ACCEPTED` 且不由 V2 修改：

- `subing_entry_signal_v1` 的公式、状态、方向、阈值、same-boundary 和 resolver 语义；
- `subing_factor_observation` 的 EMA / MACD / slope / volume 计算语义；
- `subing_intraday_v1` calibration identity 与 accepted 阈值；
- `htdy_original_15m`；
- Alert Registry、两张 Alert 表和当前 production Rule Scope；
- `clawbot-openclaw-weixin`（Clawbot / `openclaw-weixin`）single-shot 通知合同；
- Execution Review；
- Canonical / `DatasetKey` / 八表 Catalog；
- `MarketDataService` Historical Gateway；
- production Runtime 与现有 release identity；
- `auto_order=false`；
- 当前 V1 HTTP / Web response 兼容行为；
- D1 的 `RESEARCH_PENDING` 状态。

V2 不成为现有 Alert Rule 的依赖，不改变 V1 Rule 注册，不新增 Scope，不产生 Event，不发送通知。

## 6. 方案比较

| 维度 | A. 扩写 `SubingSignalEvaluation` | B. 独立 `SubingLifecycleEvaluation` | C. 通用 Research Evaluation Framework |
| --- | --- | --- | --- |
| V1 稳定性 | 高风险；V1 response、序列化、Web 和 Alert 模型被迫认识新字段 | 低风险；V1 作为只读输入且模型不变 | 表面隔离，但迁移到框架会触碰 V1 运行路径 |
| 未来 N 字复用 | 字段只服务 SuBing，复用差 | 复用四个小型 causal primitives，N 字另有 policy | 抽象复用高，但需求尚不足以证明公共边界 |
| 测试复杂度 | V1 与 V2 笛卡尔组合，回归负担高 | V1 characterization + V2 独立状态与因果测试 | 框架、plugin、DAG、版本、注册和适配测试最大 |
| API / Web 演进 | 初期字段追加便宜，后期语义混杂且兼容成本高 | additive endpoint / panel，旧表面不动 | 需要通用 schema、注册和动态展示，成本最高 |
| 过度设计风险 | 中高；逐步形成巨型 evaluation | 低；只增加本任务必要的评估和 primitive | 极高；属于明确禁止的泛化平台方向 |

选择 B。它与仓库“一个 active 入口、YAGNI、冻结正式 Rule、新研究先 shadow”的真实边界一致。
方案 A 会把 V1 稳定合同变成 V2 的迁移对象；方案 C 则在没有第二个已确认消费者前建设框架，直接违反
本任务 Non-goals。

## 7. 模块边界

`NEW_DESIGN_PROPOSAL`：V2 最小模块分为三层：

1. **Confirmed Series Assembly seam**：从现有 `MarketDataService` / `MarketReadService` 获取并规范化
   5m、15m confirmed bars。实现时可抽取 V1 已有组装逻辑，但 V1 的公共返回和 resolver 行为不变。
2. **Causal Structure primitives**：`ConfirmedPivot`、`StructuralRange`、
   `BreakoutAssessment`、`RetestAssessment`，全部为纯计算、segment-local、无持久化。
3. **SuBing Lifecycle evaluator**：消费 frozen V1 evaluation、四个 primitive 和独立的 V2 research policy，
   产生 confirmed facts、当前 projection 与隔离的 preview。

不建设 plugin engine、Rule DAG、Signal Center、Research Platform、第二套行情服务或新 Catalog。

## 8. Availability 与生命周期状态

### 8.1 Availability 独立于状态

`UNAVAILABLE` 不作为生命周期状态。它表示本次无法安全评估，例如：

- current-rank1 identity 不可解析；
- mapping / contract / segment / trading-day 身份 stale；
- completed bars 不足；
- 5m / 15m cutoff 无法按合同对齐；
- policy identity 或参数 hash 不一致；
- Historical / Live 输入违反既有 seam 合同。

输出采用：

```text
LifecycleAvailability = AVAILABLE | UNAVAILABLE
LifecycleState = null | CONTEXT_READY | SETUP_ARMED | ENTRY_CONFIRMED
                 | CONTINUATION | EXIT_RISK | INVALIDATED | ENDED
```

瞬时 `UNAVAILABLE` 不伪造状态转换，也不把最后 confirmed state 改成 `ENDED`。返回中可携带上一已确认
state 的只读引用，但本次 `formal_eligible=false`。只有恢复同一 identity 后才继续评估；发生 rank1 segment
变化时，旧 lifecycle 只能由明确的 segment-end fact 结束，新 segment 从空状态重建。

### 8.2 状态定义

以下状态集合属于 `NEW_DESIGN_PROPOSAL`：

#### `CONTEXT_READY`

进入条件类别：

- availability 为 `AVAILABLE`；
- 5m / 15m confirmed series 同属 current-rank1 segment；
- frozen V1 Factor / Signal 所需 warmup 充分；
- V2 policy 声明的 primitive 最小 confirmed window 充分；
- V2 policy identity 可验证；
- 当前没有 active setup。

退出：形成 causally valid setup 时进入 `SETUP_ARMED`；发生 hard segment end 时进入 `ENDED`；普通数据暂时
不可用只改变 availability。

#### `SETUP_ARMED`

进入条件类别：

- 已有一个方向候选；
- 存在由 confirmed pivots 形成且当前有效的 `StructuralRange`；
- 5m / 15m context categories 满足 V2 research policy；
- setup invalidation 尚未出现。

方向候选、range 选择、跨周期角色和 invalidation 的具体公式均为 `RESEARCH_PENDING`。

退出：满足 entry-confirmation categories 时进入 `ENTRY_CONFIRMED`；结构前提被明确破坏时进入
`INVALIDATED`；hard segment end 时进入 `ENDED`。

#### `ENTRY_CONFIRMED`

进入条件类别：

- 只能从 `SETUP_ARMED` 进入；
- frozen V1 resolved signal 在同一 confirmed cutoff 为 `MATCHED`，方向与 setup 一致；
- `BreakoutAssessment` 和可选的 `RetestAssessment` 满足当前 V2 research policy；
- 所消费的所有事实 `confirmed_at <= evaluation_cutoff`；
- 无同 cutoff 的冲突或 stale identity。

V1 `MATCHED` 是 `EXISTING_ACCEPTED` 输入；把它与结构、突破、回踩如何组合是
`NEW_DESIGN_PROPOSAL + RESEARCH_PENDING`，不得反向改写 V1。

退出：后续 confirmed cutoff 到来后，continuation basis 仍在则进入 `CONTINUATION`；立刻出现结构失效可进入
`INVALIDATED`；hard end 进入 `ENDED`。

#### `CONTINUATION`

进入条件类别：

- 已有同 lifecycle 的 `ENTRY_CONFIRMED`；
- 后续 confirmed facts 表明 continuation basis 仍在；
- 未达到 exit-risk 或 invalidation categories。

这是“继续观察趋势”的市场状态，不表示用户持仓，也不要求持有。

退出：出现风险类别进入 `EXIT_RISK`；核心结构前提失效进入 `INVALIDATED`；明确 lifecycle end 或 segment end
进入 `ENDED`。

#### `EXIT_RISK`

进入条件类别：

- 只能在已出现 `ENTRY_CONFIRMED` 的 lifecycle 中进入；
- confirmed facts 命中至少一个风险类别，例如均线结构破坏、上一根 confirmed K 线高低点破坏、
  结构位失守或 MACD 背离候选；
- 风险事实有明确 reason code 和因果输入。

上述风险类别来源于 `SOURCE_HYPOTHESIS`，具体检测公式全部 `RESEARCH_PENDING`。
该状态不是退出指令，不产生订单、平仓或通知。

退出：风险解除且 continuation basis 恢复时回到 `CONTINUATION`；核心前提被确认失效时进入
`INVALIDATED`；明确结束条件或 segment end 时进入 `ENDED`。

#### `INVALIDATED`

进入条件类别：

- 从 `SETUP_ARMED`、`ENTRY_CONFIRMED`、`CONTINUATION` 或 `EXIT_RISK` 进入；
- 一个定义明确的 confirmed structural premise 被破坏；
- invalidation 不能由 preview 或未完成 bar 触发。

它是当前 lifecycle 的终止状态。后续新 setup 必须生成新的 `lifecycle_id`，不得复活旧 lifecycle。

#### `ENDED`

进入条件类别：

- current-rank1 segment 已结束或实际合约 identity 改变；或
- V2 policy 定义的显式自然结束类别被 confirmed。

segment end 是强制类别；其他自然结束公式为 `RESEARCH_PENDING`。`ENDED` 是市场观察 episode 的结束，
不是仓位关闭。新 lifecycle 必须使用新 ID。

### 8.3 允许的转换

```text
CONTEXT_READY ──setup confirmed──> SETUP_ARMED
SETUP_ARMED ──entry categories──> ENTRY_CONFIRMED
SETUP_ARMED ──premise broken──> INVALIDATED
ENTRY_CONFIRMED ──next confirmed continuation──> CONTINUATION
ENTRY_CONFIRMED ──premise broken──> INVALIDATED
CONTINUATION ──risk observed──> EXIT_RISK
CONTINUATION ──premise broken──> INVALIDATED
EXIT_RISK ──risk cleared──> CONTINUATION
EXIT_RISK ──premise broken──> INVALIDATED
any non-terminal state ──hard end──> ENDED
```

初次可评估时由空 projection 进入 `CONTEXT_READY`。`INVALIDATED` / `ENDED` 对其原
`lifecycle_id` 永久终止；后续若形成新观察，只能先建立新的空 projection / `lifecycle_id`，再按上述顺序
进入新 lifecycle，不存在 terminal state 的“复活”转换。

禁止跳过 `SETUP_ARMED` 直接从 `CONTEXT_READY` 进入 `ENTRY_CONFIRMED`。同一 cutoff 同时满足多个转换时，
优先级固定为：identity / hard end → invalidation → exit risk → entry / continuation。该顺序是
`NEW_DESIGN_PROPOSAL`，其市场有效性仍需 shadow 验证；确定性顺序本身用于消除事件到达顺序差异。

## 9. 最小因果 primitive

四个 primitive 全部必要，但只实现 SuBing V2 当前需要的窄接口。删除任意一个都会迫使 lifecycle evaluator
重新内嵌相同因果逻辑：pivot 提供结构事实，range 提供突破基准，breakout 提供入场前后过程，retest 提供
二次确认和失败过程。四者不构成通用策略框架。

### 9.1 `ConfirmedPivot`

职责：表达某个历史 pivot 在何时发生，以及系统在何时第一次有足够 confirmed 数据确认它。

建议字段：

```text
pivot_id
symbol, actual_contract, segment_start, timeframe
kind: HIGH | LOW
pivot_time
confirmed_at
price: Decimal
confirmation_rule_id
input_start, input_end
status: CONFIRMED
```

合同：

- `pivot_time` 是极值 bar 时间；`confirmed_at` 是确认所需最后一根 completed bar 的 cutoff；二者不得混用；
- 计算只能读取 `confirmed_at` 及以前的数据；
- `pivot_id` 由 identity、timeframe、kind、pivot_time、confirmed_at 和 rule identity 确定；
- confirmed pivot 一经产生不得因 future tail 被移动、删除或改价；新的相反事实只能追加新 pivot；
- 不得跨 current-rank1 segment 边界；
- Preview pivot 使用独立模型 / 字段，状态为 `PREVIEW`、`formal_eligible=false`，允许重绘但不能转成
  同 ID confirmed 记录。

确认窗口、左右宽度、同价处理属于 `RESEARCH_PENDING`。

### 9.2 `StructuralRange`

职责：把当时已经确认的上下结构边界冻结为有时间有效性的 range。

建议字段：

```text
range_id
symbol, actual_contract, segment_start, timeframe
direction_context
upper, lower: Decimal
upper_pivot_id, lower_pivot_id
valid_from
invalidated_at: datetime | null
invalidation_reason: str | null
formation_rule_id
status_at_cutoff: ACTIVE | INVALIDATED
```

合同：

- 上沿 / 下沿必须引用 confirmed pivots 或同样可追踪的 confirmed bar fact；首版只允许引用
  `ConfirmedPivot`，避免第二套隐式来源；
- `valid_from = max(upper_pivot.confirmed_at, lower_pivot.confirmed_at, formation_cutoff)`；
- range 只能使用 `valid_from` 当时及以前可知数据产生；
- future tail 不得回看并把旧 range 替换成更漂亮的历史区间；
- range formation record 永久不可变；invalidation 以独立 fact 追加，当前 projection 的
  `invalidated_at` 由该 fact 推导，不得改写 range 在更早 cutoff 的 active 事实；
- 同一 cutoff 的 projection 可显示它已失效，但按历史 cutoff 查询仍复现当时状态；
- 不得跨 segment。

range 选择、最小宽度、最大年龄和 invalidation 公式属于 `RESEARCH_PENDING`。

### 9.3 `BreakoutAssessment`

职责：以可解释组件描述相对某个 frozen range 的突破过程，不输出神秘总分。

建议字段：

```text
assessment_id, range_id
direction: LONG | SHORT
assessed_at
status: NONE | OBSERVING | CONFIRMED | FAILED
price_break: bool
close_outside: bool
bars_held_outside: int
outside_distance_bps: Decimal
volume_expansion_state: PASS | FAIL | UNAVAILABLE
volume_ratio: Decimal | null
open_interest_expansion_state: PASS | FAIL | UNAVAILABLE
open_interest_delta: Decimal | null
open_interest_ratio: Decimal | null
reason_codes
```

合同：

- 所有组件相对同一个 `range_id` 和 confirmed cutoff；
- `bars_held_outside` 只计 completed bars，不能由 future tail 回填；
- volume / open-interest 的缺失明确为 `UNAVAILABLE`，不得静默当成 0、PASS 或 FAIL；
- status 由有版本的 V2 research policy 从组件推导；组件与 policy 结论同时保留；
- 不引入汇总分数。

“约 3 根 K 线”、成交量和持仓量阈值以及是否必须全部通过均为 `RESEARCH_PENDING`。

### 9.4 `RetestAssessment`

职责：描述突破后是否发生回踩、是否重新进入原区间、是否守住突破位以及是否再次确认。

建议字段：

```text
assessment_id, breakout_assessment_id, range_id
assessed_at
status: NOT_OBSERVED | IN_PROGRESS | HELD | FAILED | RECONFIRMED
occurred: bool
retest_started_at: datetime | null
depth_bps: Decimal | null
depth_as_range_fraction: Decimal | null
reentered_range: bool | null
held_breakout_level: bool | null
reconfirmed: bool
reconfirmed_at: datetime | null
failed_at: datetime | null
reason_codes
```

合同：

- 回踩深度以 frozen breakout level / range 为基准，不因未来选择新的 range；
- 每个 cutoff 只从当时 confirmed bars 推导当前 assessment；
- later reconfirmation 是新 confirmed fact，不改写此前 `IN_PROGRESS` / `HELD` 事实；
- Preview retest 与 confirmed assessment 分离；
- 回踩是否为 entry 的必需条件由 policy 决定，不内嵌在 primitive。

回踩容差、最大等待 bars、守位和再次突破公式属于 `RESEARCH_PENDING`。

## 10. Preview / Confirmed 因果合同

### 10.1 Formal lifecycle 只消费 Confirmed

`NEW_DESIGN_PROPOSAL`：评估结果分为两个互斥命名空间：

```text
confirmed:
  facts[]
  current_projection

preview:
  candidates[]
  repainting: true
  formal_eligible: false
```

以下约束不可配置：

- 未完成 bar 只能进入 preview；
- preview 不得作为 `ConfirmedPivot`、range、breakout、retest 或状态转换的输入；
- preview 不得进入 formal lifecycle、Alert、accepted calibration 或 shadow 的正式 feature；
- preview 可以消失、移动或改变，但必须明确标记 `repainting=true`；
- confirmed fact 使用 append-only 语义。后来的 invalidation、risk 或 end 通过新 fact 表达，不覆盖旧事实；
- 当前 projection 可以随新 facts 更新，但按历史 cutoff 重放时必须恢复该 cutoff 当时的 projection。

### 10.2 Prefix invariance

对任意 current-rank1 segment 内 cutoff `T`：

```python
prefix = evaluate(bars[:T])
extended = evaluate(bars[:T] + bars[T:])

assert confirmed_facts(extended, confirmed_at_le=T) == prefix.confirmed_facts
assert projection_at(extended, T) == prefix.current_projection
```

等价性包含 ID、时间、价格、上下沿、组件值、reason codes、状态转换和 policy identity。future tail 可以：

- 追加新的 confirmed pivot / range / assessment / lifecycle facts；
- 使当前 projection 在 `T` 之后失效或前进；
- 改变 preview。

future tail 不可以：

- 改写或删除 `confirmed_at <= T` 的 fact；
- 把历史 pivot_time 移到更漂亮的位置；
- 回溯改变 range 的 `valid_from` 或边界；
- 回溯增加 `T` 时尚未发生的 held bars、retest 或再次确认；
- 回溯改变 `T` 时的 lifecycle state。

## 11. 5m / 15m 协作语义

### 11.1 已冻结部分

`EXISTING_ACCEPTED`：

- 第一版周期集合固定为 5m / 15m；
- current V1 reciprocal companion evaluation 和 same-boundary resolver 不变；
- 5m 与 15m 必须来自相同 actual contract 和 current-rank1 segment；
- companion cutoff 不晚于 primary cutoff；
- D1 不进入设计能力。

### 11.2 V2 协作提案

`NEW_DESIGN_PROPOSAL`：V2 每次产生一个联合 cutoff observation，而不是两个互相竞争的 lifecycle：

- 15m 提供较大周期 context 候选；
- 5m 提供较小周期 setup / timing 候选；
- 每个 timeframe 的 pivot / range 独立计算，不把不同周期 pivot 混成一个 range；
- 联合评估 cutoff 取本次可见 completed facts 的共同安全时间；
- 若 5m cutoff 落在未完成的 15m bucket 内，只能使用上一根 completed 15m；
- 在共同 15m boundary，先构造同 cutoff 的 15m 与 5m facts，再一次性执行 state transition，结果不得依赖
  live bar 到达顺序；
- current V1 resolved signal 作为冻结输入，其 15m 优先和 direction-conflict fail-closed 继续生效。

“大周期定方向、小周期择时”和“5m / 15m 共振”仍是 `SOURCE_HYPOTHESIS`；15m context / 5m timing
的确切门槛与组合是 `RESEARCH_PENDING`，不能因采用上述协调结构就称为 accepted policy。

## 12. rank1 / roll / warmup 边界

以下为 V2 强制合同：

- 所有 bars、V1 inputs、primitives 和 lifecycle facts 都必须 current-rank1 segment-local；
- 不使用 pre-rank1 bars warmup；
- 不跨 roll 继承 EMA、MACD、pivot、range、breakout、retest 或 lifecycle state；
- roll / actual-contract identity 改变时旧 lifecycle 追加 `ENDED(reason=RANK1_SEGMENT_ENDED)`，新 segment
  从无结构状态开始；
- Historical 只通过 `MarketDataService`；
- Live 只通过现有 `MarketReadService` seam；
- completed / confirmed data 才能进入 formal lifecycle；
- stale identity fail-closed；
- 不直接读取 Parquet，不调用 RQData，不写 DB / Canonical / Redis。

当前 V1 read service 的有限查询窗口不能被 V2 静默解释为完整结构窗口。V2 policy 必须声明所需最小窗口；
窗口不足时返回 `UNAVAILABLE(reason=INSUFFICIENT_CONFIRMED_HISTORY)`，不得缩短公式、跨 segment 补数或跨频回退。
若后续实现需要扩大查询条数，只能通过现有 MarketDataService 接口完成，不新建行情入口。

## 13. Observation output schema

`NEW_DESIGN_PROPOSAL`：纯 evaluator 的权威输出为 `SubingLifecycleEvaluation`，current HTTP projection
使用 `SubingLifecycleObservation`。核心 schema：

```text
SubingLifecycleEvaluation
  schema_version
  formula_version
  policy_id
  policy_status
  policy_parameters_hash
  identity
    symbol, product, actual_contract
    dominant_mapping_date, segment_start
    evaluation_cutoff, trading_day
    source_mode: HISTORICAL | LIVE
  availability
    status: AVAILABLE | UNAVAILABLE
    reason_codes[]
  v1_inputs
    factor_policy_id
    signal_policy_id
    calibration_id
    primary_signal_ref
    resolved_signal_ref
  confirmed
    lifecycle_id | null
    state | null
    state_since | null
    direction: LONG | SHORT | NONE
    transition_sequence
    facts[]
    pivots[]
    active_range | null
    breakout | null
    retest | null
  preview
    candidates[]
    repainting: true
    formal_eligible: false
  formal_eligible: false
  auto_order: false
```

所有价格、比例、斜率和深度使用 `Decimal` 语义；HTTP 以十进制字符串序列化，禁止 float 参与政策比较。

`confirmed.facts[]` 的每条 fact 至少包括：

```text
fact_id
lifecycle_id
fact_type
effective_at
confirmed_at
from_state | null
to_state | null
direction
subject_ids[]
reason_codes[]
formula_version
policy_id
policy_parameters_hash
```

纯 evaluator 可以返回完整前缀事实流；current HTTP endpoint 只返回当前 projection、当前 lifecycle 的紧凑
facts 和当前 primitives，避免无界 response。V2 首版无历史 HTTP replay endpoint，也无持久化表。

## 14. Formula version 与 policy identity

V2 不复用 `subing_entry_signal_v1` 的 identity 命名空间：

- `formula_version`：标识 primitive 算法、因果确认规则和 state transition 计算语义；
- `policy_id`：标识一组研究门槛、周期角色、组件组合和 risk / invalidation / end policy；
- `policy_status`：首版固定 `RESEARCH_PENDING`；
- `policy_parameters_hash`：对规范化参数内容计算稳定 hash，同 ID 内容漂移时 fail-closed。

建议首个身份：

```text
formula_version = subing_lifecycle_formula_v2_1
policy_id = subing_lifecycle_shadow_candidate_v1
policy_status = RESEARCH_PENDING
```

命名只用于版本隔离，不表示 accepted。以下变化必须新建 identity，不能覆盖旧版本：

- pivot / range / breakout / retest 因果公式变化 → 新 `formula_version`；
- 阈值、5m / 15m 角色、状态 gate、invalidation / risk / end 条件变化 → 新 `policy_id`；
- schema 不兼容变化 → 新 `schema_version`。

未来只有独立任务、充分 evidence 和用户明确人工批准后，某个精确 policy identity 才可能成为 accepted candidate。
本设计不定义该 promotion，也不把 V2 接入 Alert。

## 15. API / read-service 边界

### 15.1 Read service

`NEW_DESIGN_PROPOSAL`：新增窄接口 `SubingLifecycleReadService.get_current_observation(symbol)`：

- 复用现有 confirmed-series assembly seam；
- 调用 frozen V1 factor / signal evaluator，不复制公式；
- 同时装配 5m / 15m，调用纯 lifecycle evaluator；
- 无 DB / Canonical / Redis 写入；
- 不修改 `SubingReadService.get_snapshot()` 的公共合同；
- 不创建第二套 MarketDataService 或自行解析 Parquet / rank1。

若共享组装逻辑需要从现有 `SubingReadService` 抽取，必须先以 V1 characterization tests 证明返回值、异常、
same-boundary、stale 和 live merge 行为完全相同。

### 15.2 HTTP interface

建议 additive endpoint：

```text
GET /api/v1/market/research/subing/lifecycle?symbol=JM
```

不增加 `frequency` 参数：V2 首版是固定的 5m / 15m 联合观察。也不增加任意 `as_of` / replay 参数，避免
把 current read service 扩成研究平台。

错误边界：

- 非法 symbol / 参数：422；
- Catalog、mapping、physical identity 或 policy identity 硬冲突：409，fail-closed；
- 正常 warmup 不足或暂时无 completed context：200，`availability=UNAVAILABLE`，并给稳定 reason code；
- 不返回内部路径、SQL、stack trace 或 credential。

V1 endpoint 保持不变。V2 endpoint 全部标记 research / shadow，`formal_eligible=false`。

## 16. Web 后续展示边界

Web 是后续独立实现任务，不阻塞纯 evaluator。建议在现有 Market 研究区新增独立、可折叠的
“SuBing Lifecycle V2 · Shadow”面板：

- availability 与原因；
- 当前 observation state、方向和 state since；
- 15m context / 5m timing 的 confirmed cutoff；
- frozen range 上下沿及来源 pivot；
- breakout 的 price / close / held bars / volume / OI 组件；
- retest 的发生、深度、re-entry、守位和再次确认；
- exit-risk / invalidation reason codes；
- formula / policy identity 和 `RESEARCH_PENDING` badge；
- preview 单独区域并醒目标注“可重绘，不进入正式观察”。

Web 不：

- 替换或改名现有 V1 Signal 卡片；
- 显示仓位、持仓要求、加仓、自动退出或交易按钮；
- 提供 Alert 开关、Scope mutation 或 Runtime 控件；
- 把 `ENTRY_CONFIRMED` 表述为已下单，把 `EXIT_RISK` 表述为应平仓。

## 17. Shadow / research evidence

`NEW_DESIGN_PROPOSAL`：首版 evidence 通过离线、只读、segment-local prefix evaluation 产生，不进入
production Runtime。数据只从 `MarketDataService` 读取；future outcomes 与 lifecycle feature 计算完全隔离。

最小 evidence 包含：

- 每个 formula / policy identity 的样本数量和 unavailable 原因分布；
- 每种状态转换、方向、周期上下文和产品的计数；
- setup → entry、entry → continuation / risk / invalidation / end 的持续 bars 和时长；
- breakout 各解释组件与 outcome 的分层统计；
- retest 发生率、深度、重入、守位、再次确认与 outcome 的分层统计；
- 与 frozen V1 `MATCHED` 的交集、遗漏和冲突；
- long / short、product、波动环境分层；
- OOS / Walk-forward 与 policy 参数稳定性；
- prefix-invariance 和 historical/live consistency 结果。

future return / MFE / MAE 等 outcome 只能在 evaluation facts 完成后由独立 label pass 计算，不能反馈到 pivot、
range、state 或当前 cutoff。缺少 OI、窗口不足或 segment 太短必须显式计数，不得从其他频率或旧合约填充。

首版 evidence 输出优先采用可复算 stdout / JSON artifact；不新增 DB 表、Catalog 表或长期行情副本。任何
accepted promotion、正式报告保留或外部发布都需独立任务。

## 18. Prefix-invariance 测试方案

### 18.1 Primitive 单元测试

- 每个 cutoff 逐步追加 bar，验证 confirmed pivot 的 ID、pivot_time、confirmed_at、price 不变；
- 在 future tail 制造更高高点 / 更低低点，验证旧 confirmed pivot 不重选；
- 验证 preview pivot 可改变，但不出现在 confirmed facts；
- 验证 range 上下沿、pivot refs 和 valid_from 在追加 future tail 后不变；
- 验证 range invalidation 追加新 fact，不改写之前 cutoff 的 active projection；
- 验证 held bars 只随 completed bar 单调增加，retest / reconfirmation 不回填；
- 验证所有 primitive 在 segment 边界清空。

### 18.2 Lifecycle property / metamorphic 测试

对一组手工 fixtures、真实去敏 bar fixtures 和生成式序列，枚举每个可用 cutoff `T`：

```python
expected = evaluate(bars[:T])
for tail in representative_future_tails:
    actual = evaluate(bars[:T] + tail)
    assert canonical_confirmed_prefix(actual, T) == canonical_confirmed(expected)
    assert projection_at(actual, T) == expected.current_projection
```

tail 至少包括：趋势延续、急速反转、同价 pivot、gap、volume / OI 缺失、roll 前后和末尾未完成 bar。

另外验证：

- 非法状态跳转被拒绝；
- 同 cutoff 多条件按固定优先级产生唯一 transition；
- `UNAVAILABLE` 不产生伪 transition；
- recovery 在同 identity 下不改写此前 facts；
- V1 SignalEvaluation serialization 和 Alert evaluation 与基线完全相同；
- preview 数据无法通过类型或运行时入口进入 formal lifecycle / Alert。

允许变化的只有 `preview` 和 `T` 之后追加的 confirmed facts；测试必须明确过滤并分别断言这两类输出。

## 19. Historical / Live 一致性测试方案

构造同一 actual contract、segment、trading day 和 completed bar 集合，经两条受支持 seam 输入：

1. Historical：`MarketDataService` 返回 canonical bars；
2. Live：`MarketReadService` 返回相同 completed bars，并带有效 live identity。

规范化 `bar_source` 等来源元数据后，断言：

- formula / policy identity 相同；
- ConfirmedPivot、StructuralRange、BreakoutAssessment、RetestAssessment 相同；
- confirmed facts、state、direction、cutoff 和 reason codes 相同；
- 5m 落在未完成 15m bucket 时都使用相同上一根 15m cutoff；
- common 15m boundary 不受 5m / 15m live arrival order 影响；
- final session bar 仍服从既有 shared Live arrival grace；
- stale actual contract、mapping date、segment、bar_end 或 trading_day 均为 `UNAVAILABLE` / fail-closed；
- roll 后两边都不继承旧 segment 的任何 primitive 或 state；
- 未完成 live bar 只影响 preview，去除 preview 后与 historical 正式结果一致。

回归层继续运行现有 SuBing API / Web / Alert suites，额外断言 V2 不注册新 Alert Rule、不创建 Event、不调用
notification seam，并通过测试隔离证明不写 DB / Canonical / Redis。

## 20. 研究来源逐项分类

| # | 来源内容 | 当前分类与边界 |
| --- | --- | --- |
| 1 | 大周期定方向、小周期择时 | `SOURCE_HYPOTHESIS`；15m context / 5m timing 是 `NEW_DESIGN_PROPOSAL`，具体规则 `RESEARCH_PENDING` |
| 2 | 5m / 15m 周期共振 | 5m / 15m companion 与 same-boundary resolver 为 `EXISTING_ACCEPTED`；“共振”作为 lifecycle gate 是 `SOURCE_HYPOTHESIS + RESEARCH_PENDING` |
| 3 | EMA / 21 均线及均线斜率 | EMA21、5 / 10 slope 和 V1 accepted threshold 为 `EXISTING_ACCEPTED`；用于 setup / continuation / risk 的新公式为 `SOURCE_HYPOTHESIS + RESEARCH_PENDING` |
| 4 | MACD 在零轴附近的金叉 / 死叉 | V1 MACD 金死叉与 kernel identity 为 `EXISTING_ACCEPTED`；“零轴附近”当前仅描述，其门槛与 lifecycle 用法为 `SOURCE_HYPOTHESIS + RESEARCH_PENDING` |
| 5 | 成交量放大 | V1 primary `volume_ratio_prev >= 3` 为 `EXISTING_ACCEPTED`；breakout / continuation 中的量能政策为 `SOURCE_HYPOTHESIS + RESEARCH_PENDING` |
| 6 | 持仓量变化 | 输入 bar 存在 OI 事实，但 SuBing accepted policy 未使用；作为 breakout 组件为 `SOURCE_HYPOTHESIS + NEW_DESIGN_PROPOSAL + RESEARCH_PENDING` |
| 7 | 前高 / 前低或震荡区间突破 | `SOURCE_HYPOTHESIS`；ConfirmedPivot / StructuralRange / BreakoutAssessment 为 `NEW_DESIGN_PROPOSAL`；选择与突破公式 `RESEARCH_PENDING` |
| 8 | 突破后约 3 根 K 线不回区间 | `SOURCE_HYPOTHESIS`；`bars_held_outside` 为解释组件 `NEW_DESIGN_PROPOSAL`；“3 根”及真突破结论 `RESEARCH_PENDING` |
| 9 | 突破、回踩、守住起点、再次突破 | `SOURCE_HYPOTHESIS`；RetestAssessment 为 `NEW_DESIGN_PROPOSAL`；容差、等待期和二次确认公式 `RESEARCH_PENDING` |
| 10 | 持有依据仍存在时继续观察趋势 | “继续观察”是 `SOURCE_HYPOTHESIS`；`CONTINUATION` 为无账户语义的 `NEW_DESIGN_PROPOSAL`；basis 公式 `RESEARCH_PENDING` |
| 11 | 均线破坏、上一 K 高低点破坏、MACD 背离等退出风险 | `SOURCE_HYPOTHESIS`；`EXIT_RISK` 为 `NEW_DESIGN_PROPOSAL`；检测公式 `RESEARCH_PENDING`，永远不是自动下单或自动平仓 |

四类标记没有隐式晋升关系。特别是，把某个 SOURCE_HYPOTHESIS 设计成可解释字段，不会使它变成
`EXISTING_ACCEPTED`。

## 21. 与未来 N 字的复用边界

可以复用：

- `ConfirmedPivot` 的 pivot_time / confirmed_at / segment-local / non-repainting 合同；
- `StructuralRange` 的因果来源、valid_from 和 append-only invalidation 合同；
- Breakout / Retest 的解释组件 schema，前提是 N 字确实需要相同市场事实；
- confirmed fact identity、Decimal 和 prefix-invariance 测试助手。

不直接复用：

- SuBing V2 的状态 gate、方向、5m / 15m 角色、阈值和 policy identity；
- frozen `subing_entry_signal_v1` 作为 N 字 entry gate；
- SuBing HTTP / Web 文案或 lifecycle ID namespace；
- 未经第二个真实消费者验证的 registry、plugin、DAG 或通用 evaluator。

未来 N 字必须以自己的研究假设、数据边界和 policy identity 组合这些小 primitive。只有在 SuBing 与 N 字
出现第二个一致、稳定的调用模式后，才评估是否抽取更上层共享模块。

## 22. Non-goals

本设计明确不包含：

- 修改或替代 `subing_entry_signal_v1`；
- 生产公式、accepted threshold 或 policy promotion；
- D1 SuBing；
- 通用 Strategy Plugin Engine、Rule DAG、Signal Center 或 Research Platform；
- 第二套 MarketDataService、直接 Parquet / RQData 读取；
- 新 Catalog 表、新长期行情副本或任意 DB / Canonical / Redis 写入；
- Alert Registry / Rule / Scope / Event / notification 变更；
- Web 交易动作、账户、委托、持仓、自动加仓或自动退出；
- Execution Review 变更；
- historical replay / backfill Alert；
- production Runtime、release、tag 或 Runtime promotion；
- 真实微信发送；
- 自动将 research evidence 晋升为正式政策。

## 23. 风险清单

| 风险 | 后果 | 设计缓解 |
| --- | --- | --- |
| pivot 需要右侧 bars，误用 pivot_time | 未来函数、历史信号提前 | 强制 `confirmed_at`，formal 只消费 confirmed |
| future tail 重选 range | 结构重绘、证据失真 | range ID / valid_from 冻结，invalidation 追加 fact |
| 把 preview 混入 formal | 实时与历史不一致 | 独立 schema、`formal_eligible=false`、类型与回归测试 |
| 5m / 15m arrival race | live 结果依赖消息顺序 | 共同安全 cutoff、common boundary 原子评估 |
| roll / warmup 污染 | 跨合约泄漏 | current-rank1 segment-local，全面 reset |
| 查询窗口不足却静默评估 | range / lifecycle 截断 | policy 声明最小窗口，不足 `UNAVAILABLE` |
| OI 缺失被当成否定或零 | 组件语义错误 | 三态 PASS / FAIL / UNAVAILABLE |
| EXIT_RISK 被用户理解为平仓 | 越过无订单边界 | 市场观察文案、无 action、`auto_order=false` |
| 新 endpoint 被 Alert 误用 | 未批准 policy 进入 production | 独立 read service、无 registry、formal_eligible false |
| policy ID 内容漂移 | evidence 无法复算 | parameters hash，不一致 fail-closed |
| 结构参数过拟合 | 样本内好看、OOS 失败 | 分层样本、OOS / Walk-forward、稳定性与淘汰结论 |
| 为未来 N 字过度抽象 | 复杂度高、边界失真 | 只共享四个窄 primitive，不建框架 |

## 24. 后续实现任务拆分

以下是未来任务，不在本文执行范围内。每项都保持 research-only，按 RED → GREEN 和 review 顺序推进：

1. **V1 characterization freeze**
   - 固定 V1 Factor / Signal / resolver / API / Alert 现有输出；
   - 建立共享 series assembly 前后的等价测试；
   - 不修改 V1 policy identity。
2. **Causal primitives**
   - 先写 ConfirmedPivot / StructuralRange / Breakout / Retest prefix tests；
   - 再实现纯函数和 Decimal models；
   - 不接 HTTP、Web 或 Runtime。
3. **Lifecycle evaluator 与 research policy identity**
   - 实现状态机、immutable facts、preview 隔离和 fail-closed policy loader；
   - 初始 policy 固定 `RESEARCH_PENDING`、`formal_eligible=false`。
4. **Historical / Live read seam**
   - 新增 `SubingLifecycleReadService`；
   - 复用现有 MDS / MarketReadService，并完成 common-boundary、stale、roll 和一致性测试。
5. **Additive API / Web Shadow**
   - 新增独立 lifecycle endpoint 和研究面板；
   - 保留 V1 response / UI，明确 preview 与无交易语义。
6. **Shadow evidence**
   - 只读运行 segment-local prefix evaluation；
   - 输出分层、OOS / Walk-forward、参数稳定性和淘汰证据；
   - outcome label pass 与 feature pass 隔离。
7. **独立政策评审**
   - 只有 evidence 足够时另起任务决定保留、修改或淘汰候选；
   - Alert、Rule Scope、release 和 Runtime promotion 不属于上述任何实现任务，必须继续独立审批。

## 25. 验收标准

未来 V2 实现只有同时满足以下条件才可称为 research implementation complete：

- V1 全部冻结测试无变化；
- 四个 primitive 与 lifecycle 对所有测试 cutoff 满足 prefix-invariance；
- historical / live 在相同 confirmed inputs 上 confirmed 输出一致；
- Preview 只能重绘于独立输出，无法进入 formal facts 或 Alert；
- 5m / 15m 共同 boundary 与 event arrival order 无关；
- roll、stale identity、窗口不足全部 fail-closed；
- 没有直接 Parquet / RQData、第二套行情服务或任何新持久化写入；
- V2 policy 仍为 `RESEARCH_PENDING`，没有 Alert Rule / Scope / Event / send；
- `auto_order=false` 且不存在账户、订单、持仓或自动退出语义。

本文仅冻结设计边界，不冻结尚未研究的生产公式。任何具体 pivot 窗口、range 选择、突破阈值、3-bar
规则、回踩容差、continuation basis 或 exit-risk 公式，都必须作为带新 policy identity 的后续研究候选。
