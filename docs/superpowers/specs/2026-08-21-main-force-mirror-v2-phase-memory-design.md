# 主力照妖镜 V2 Phase Memory 设计

状态：DIRECTION_APPROVED / SPEC_REVIEW_PENDING

日期：2026-08-21

阶段属性：historical-only / observation-only / 60m-only / no promotion

## 1. 背景与问题

当前 active identity `main_force_mirror_v2` 已完成 60m 期货主力压力观察：

```text
Canonical confirmed 60m OHLCV + open_interest
→ instant pressure 五状态
→ accumulated pressure EMA5
→ frozen “小心” caution

T-1 exact physical-contract Top20 member snapshot
→ member direction / strength / relation
```

现有 V2 能回答“当前 Bar 正在发生什么”，例如：

```text
long_build
short_build
short_cover
long_liquidation
turnover
```

但在典型快速拉升见顶段中，逐 Bar 事实可能依次表现为：

```text
强 long_build
→ long_liquidation
→ short_build
```

当前模型不会把这个序列归纳为“多头压力高潮 → 多头退潮 → 空头接管”。用户仍需人工把多个 Bar、累计压力、价格位置与席位变化拼接成阶段判断。

本设计增加一个 **causal Phase Memory 研究层**，专门回答：

> 最近发生过什么，以及当前状态相对最近的强势阶段发生了什么变化？

它不是“出货预测器”，不回看未来确认顶部，不修改现有 V2 即时压力、累计压力、“小心”或席位公式。

## 2. 已批准约束

1. 周期严格只做 `60m`。
2. 不引入 15m / 5m / 1m 作为输入、确认、辅助 Gate 或 forensic 子结构。
3. 不构造任何 60m + 低周期多周期模型。
4. 现有 V2 五状态、instant pressure、EMA5 accumulated pressure、“小心”公式和 member relation 首轮全部保持不变。
5. Phase Memory 首先是 historical research / forensic，不直接进入 Web active semantics、Alert、notification、Runtime 或 Execution Review。
6. 任何阶段标签都只能使用当前 Bar 及其之前的 60m Historical confirmed facts；禁止未来函数、后验回标和重绘。
7. 用户指定的 JM 高位快速拉升案例只作为解释性 Golden Behavior Case，不作为必须拟合成功的参数目标。
8. `auto_order=false` 始终成立。

## 3. 明确不做

```text
15m/5m/1m phase confirmation
跨周期共振
修改 MarketDataService / Canonical / MainContractMap
新增 Market Catalog 表
API 请求时实时调用 RQData
Live phase
Alert / PushPlus
Signal / Strategy promotion
回测撮合、PnL、成本、仓位
自动搜索“最优出货参数”
把会员席位解释为确定主力账户
真实资金净流入/流出金额
```

## 4. 数据与长期记忆原则

### 4.1 60m 市场事实

价格、成交量、持仓量继续只从：

```text
Canonical Historical
→ MarketDataService
→ exact physical-contract calculation block
```

读取。

Phase Memory 不直接读取 Parquet，不复制 rank1 resolver，不跨 physical contract 继承状态。

### 4.2 Member 数据

Member 历史继续采用现有：

```text
main_force_member_rank_v1
```

不可变研究快照。

第一阶段不新增第二套 raw archive、Catalog、SQLite 或 member cache 子系统。第一次真实 retrospective 所需席位数据通过现有 exact-contract RQData snapshot builder 在一次明确 Gate 下构建；快照发布后，重复研究全部只读本地 pinned dataset。

长期形态：

```text
RQData（外部唯一来源）
→ 一次受控 snapshot build
→ immutable local member snapshot
→ 后续反复本地研究
```

如果未来 provider 请求量或重复 snapshot 构建成本成为真实问题，再单独设计增量复用；本任务不提前建设。

## 5. 四层解释模型

```text
Layer 1  Instant Pressure
当前这一根 60m Bar 在做什么？

Layer 2  Accumulated Pressure
当前方向压力最近是否持续、衰减或反转？

Layer 3  Phase Memory
最近是否出现过强压力？之后是否出现退潮或反方向接管？

Layer 4  Member Context
更慢一级的 T-1 席位结构是否同向、背离或发生转折？
```

后续价格结果只用于 retrospective evaluation，不允许反向修改当时 Phase。

## 6. Stage B 的 exact forensic facts

Stage B 只产生可复算 research facts，不产生正式 `CLIMAX / UNWIND / TAKEOVER` 标签。

### 6.1 Side-relative pressure

对每个 point 和方向 `side ∈ {long, short}` 定义：

```text
side_sign(long)  = +1
side_sign(short) = -1

side_instant = max(side_sign * instant_pressure, 0)
side_accumulated = max(side_sign * accumulated_pressure, 0)
```

如果对应 pressure/accumulated 尚未 ready，则相关 research fact 为 unavailable，不补零。

### 6.2 固定 diagnostic windows

Stage B 允许且只允许以下 trailing 60m windows：

```text
W = 3 / 5 / 10 / 20 bars
```

这些只是 retrospective sensitivity grid，不是正式 Phase 参数。

对每个 W、每个 side 计算：

```text
peak_instant_W
bars_since_peak_instant_W
peak_accumulated_W

accumulated_ratio_to_peak_W =
  current_side_accumulated / peak_accumulated_W

decay_from_peak_W = 1 - accumulated_ratio_to_peak_W
```

规则：

- peak 只在当前点及之前 W 根、同一 calculation block 内计算；
- `peak_accumulated_W <= 0` 时 ratio/decay unavailable；
- 当前 accumulated 已反向时 `side_accumulated=0`，因此 `decay_from_peak_W=1`；
- 不 clamp decay，不用未来数据。

### 6.3 价格位置 facts

继续复用 V2 已计算的 ATR14 与 HHV/LLV20 语义：

```text
long_distance_from_extreme_atr = (HHV20(high) - close) / ATR14
short_distance_from_extreme_atr = (close - LLV20(low)) / ATR14
```

同时保留现有：

```text
range_position
price_impulse
volume_ratio
delta_oi
oi_impulse
```

### 6.4 状态序列 facts

在同 calculation block 内精确输出：

```text
previous_pressure_state
state_transition = previous_state -> current_state
recent_state_sequence_3
recent_state_sequence_5
```

以及相对 remembered side 的连续计数：

```text
same_side_build_streak
same_side_liquidation_streak
opposite_build_streak
```

多头 remembered side：

```text
same_side_build        = long_build
same_side_liquidation  = long_liquidation
opposite_build         = short_build
```

空头完全镜像：

```text
same_side_build        = short_build
same_side_liquidation  = short_cover
opposite_build         = long_build
```

这些 streak 只描述连续状态，不直接产生阶段结论。

### 6.5 calculation block

Phase research 与 V2 同样严格按 physical contract block：

- 合法换月立即清空；
- invalid Bar 结束 block；
- timestamp 冲突结束 block；
- 不跨旧主力合约继承任何 peak、sequence 或 streak。

## 7. Member History exact research facts

现有单日字段继续保留：

```text
change_bias
member_strength
position_skew
top5_volume_share
```

仅对当前 Bar 可见的 T-1 或更早 member days 计算：

```text
member_bias_3d = mean(latest 3 available change_bias values ending at current member_trade_date)
member_bias_5d = mean(latest 5 available change_bias values ending at current member_trade_date)
member_bias_delta = current change_bias - immediately previous available change_bias
```

要求完整 3/5 个历史 member day；不足时对应字段 unavailable，不缩短窗口。

`member_bias_turn` 只采用零轴穿越，不新增阈值：

```text
previous member_bias_3d >= 0 and current member_bias_3d < 0
→ long_to_short

previous member_bias_3d <= 0 and current member_bias_3d > 0
→ short_to_long

otherwise
→ none
```

原则：

1. member history 不融合进 instant pressure；
2. Stage B 不把 member turn 作为 Phase Gate；
3. member unavailable 时 pressure-only research 仍可执行；
4. member facts 只对 admitted products `jm/ag/cu/m` 研究；其他 active products明确 unavailable，不降级到产品汇总排名。

## 8. 目标最小阶段模型

只有 Stage B evidence 足够支持时，Stage C 才允许冻结：

```text
NORMAL
CLIMAX
UNWIND
TAKEOVER
```

并独立携带：

```text
side = long | short | neutral
```

人类解释示例：

```text
LONG + CLIMAX
→ 多头压力高潮

LONG + UNWIND
→ 多头退潮 / 高位派发观察

SHORT + TAKEOVER
→ 空头接管
```

对称地：

```text
SHORT + CLIMAX
→ 空头压力高潮

SHORT + UNWIND
→ 空头退潮 / 低位回补观察

LONG + TAKEOVER
→ 多头接管
```

“派发观察”只能是 `UNWIND` 的人类解释，不作为可验证真实资金出货事实。

## 9. 因果状态机原则

候选结构：

```text
NORMAL
  ↓
CLIMAX
  ↓
UNWIND
  ↓
TAKEOVER
```

允许：

```text
CLIMAX → NORMAL      # 原趋势继续，无退潮成立
UNWIND → NORMAL      # 退潮失败，原方向重新建立
TAKEOVER → NORMAL    # 新方向接管结束
```

禁止：

- 用未来 1/3/5/10 根价格结果把早先 Bar 回标为 CLIMAX 或 UNWIND；
- 当前 Bar 尚无证据时预先标记“出货”；
- 因为后续大跌就强制要求顶部附近出现某个阶段标签。

## 10. “小心”与 Phase 完全分离

现有 frozen caution 继续回答：

> 当前方向是否拥挤、追涨/追空是否需要警戒？

Phase Memory 回答：

> 最近强方向是否已经出现退潮或反方向接管？

因此：

```text
caution != phase
CLIMAX != caution
CLIMAX != 出货
UNWIND ≈ 退潮 / 派发观察
TAKEOVER ≈ 反方向接管
```

Phase 不修改 caution score，不修改 `>=70` candidate threshold，不消费或重置现有 caution latch。

## 11. 60m-only forensic protocol

### 11.1 Case A：JM Golden Behavior Case

对用户指定的 2026-03 高位快速拉升区间，输出逐 Bar dossier：

```text
bar_end
physical_contract
OHLCV / OI
pressure_state
instant_pressure
accumulated_pressure
price_impulse
volume_ratio
delta_oi
oi_impulse
range_position
caution / scores / reasons
member T-1 facts（若可用）
Stage B forensic facts
```

必须回答：

1. 为什么强拉升 Bar 是 `long_build`；
2. 最早哪一根 60m Bar 的 accumulated pressure 开始衰减；
3. 最早哪一根出现 `long_liquidation`；
4. 最早哪一根出现 `short_build`；
5. accumulated pressure 何时反号；
6. member context 当时是同向、背离还是发生 3d bias turn；
7. 哪些 candidate grid 能在不看未来价格的情况下形成合理阶段解释。

该 case 只用于解释和回归，不允许为了让它命中特定结果而单独调参。

### 11.2 Pressure-only matrix

范围：

```text
active 60
× 60m actual_dominant
× Historical confirmed
```

使用本地 Canonical，完整保留各 W 的：

```text
peak / decay
state transitions
streaks
price distance from 20-bar extreme
```

### 11.3 Member-context matrix

范围只限：

```text
jm / ag / cu / m
```

叠加：

```text
member aligned / divergent / unavailable
member_bias_3d / 5d
member_bias_turn
```

member layer不得决定 pressure-only cell 是否成立。

## 12. Stage B candidate grid

Stage B 允许比较候选定义，但不得选择单品种最优参数。

固定 grid：

```text
climax instant-pressure threshold:
60 / 70 / 80 / 90

decay_from_peak threshold:
0.25 / 0.50 / 0.75 / 1.00

transition horizon after candidate climax:
1 / 2 / 3 / 5 bars

opposite-build persistence:
1 / 2 / 3 bars
```

候选模板只允许：

```text
candidate_climax
= side_instant reaches selected threshold
  within same physical-contract block

candidate_unwind
= prior candidate_climax exists within selected transition horizon
  AND decay_from_peak_W reaches selected threshold
  AND [same_side_liquidation OR failed pressure extension]

candidate_takeover
= prior candidate_climax/unwind exists
  AND opposite_build_streak reaches selected persistence
  AND accumulated pressure is neutralized or reversed
```

其中 `failed pressure extension` 在 Stage B 只使用已定义 facts 表达：当前 `side_instant` 未超过对应 W 的历史 `peak_instant_W`，且 `decay_from_peak_W > 0`；不看未来高低点。

Stage B 必须保留全部 grid cells 与样本数，不能只输出 winner。

## 13. Retrospective evaluation

复用现有 V2 research infrastructure，不新增 backtest engine。

固定 forward horizons 仍为：

```text
1 / 3 / 5 / 10 根 60m Bar
```

且不得跨 physical contract。

比较 cohort：

```text
candidate_climax
candidate_climax_then_decay
candidate_climax_then_liquidation
candidate_climax_then_opposite_build
candidate_unwind
candidate_takeover

以上 cohort
× member aligned / divergent / turn / unavailable
```

输出至少按：

```text
product
year
long / short side
parameter-grid cell
```

分层。

pooled 只作为摘要，不能掩盖品种和年份异质性。

评价重点不是“哪组赚钱最多”，而是：

1. cohort 是否稳定表达同一种市场行为；
2. 发生时间是否足够早而不是完全后验；
3. long / short 是否近似对称；
4. 是否只在极少数单品种有效；
5. 参数邻域是否稳定，还是只有一个尖锐最优点；
6. member history 是否增加解释力，还是只增加复杂度。

## 14. Stage C 阈值冻结规则

Stage B grid 不是正式参数。

只有完成 forensic matrix 后，Stage C 才能选择最小必要规则。冻结必须满足：

1. 使用统一跨品种规则，不按 JM 单独优化；
2. long / short 对称；
3. 参数邻域稳定，不选择孤立最优 cell；
4. 参数进入独立 Phase policy hash；
5. 后续修改产生新版本或新 hash；
6. 阈值数量保持最少，避免组合爆炸；
7. 如果 Stage B 不能形成稳定规则，则结论为“不冻结 Phase”，保留现有 V2，不为了功能存在而强行实现。

## 15. Prefix invariance / 防未来函数

Stage C reducer 必须通过逐 prefix 重算验证：

```text
compute(bars[0:t])[-1]
==
compute(bars[0:N])[t]
```

对以下字段逐点成立：

```text
phase
phase_side
phase_reason_codes
phase_memory
```

并增加：

- exact physical-contract reset test；
- invalid-Bar reset test；
- long/short mirror test；
- pagination/page-boundary recomputation parity。

如果未来完整序列改变历史 Phase，则任务直接阻塞，不允许进入 Web。

## 16. Web 设计边界

Stage C 规则冻结并通过独立 Review 前，不修改 active Web 阶段语义。

研究通过后，Web 最终只增加少量阶段变化 Marker，不恢复 V0“每根柱子都写进场/拉高/出货”的模式。

目标信息层级：

```text
当前阶段：多头退潮观察
即时：多头减仓 -72
累计：+41 → +17 → -3
席位 T-1：多头结构转弱
```

图形保持：

```text
柱 = instant pressure
线 = accumulated pressure
Marker = frozen caution
Marker = CLIMAX / UNWIND / TAKEOVER transition
```

不显示资金净流入比例、胜率、未来反转概率或交易指令。

非 60m 永远明确 unsupported，不做 fallback。

## 17. 分阶段实施顺序

### Stage A — 真实数据准备

目标：获得可重复使用的真实 member retrospective snapshot。

- 只使用现有 snapshot builder；
- 先 dry-run；
- 用户明确 Gate 后才允许真实 RQData 请求与研究数据写入；
- 发布 immutable dataset 后固定 dataset_id；
- 不触碰 Canonical / DB / Runtime。

### Stage B — Forensic research

目标：新增 research-only 60m facts、candidate grid 与 dossier/matrix 输出。

- 不改 active V2 Web；
- 不改 caution；
- 不产生正式 Phase；
- 先完成 JM dossier；
- 再跑 active60 pressure-only matrix；
- member context 只跑 jm/ag/cu/m；
- 保存全部 grid cells，不生成自动 winner。

### Stage C — Freeze Phase policy

只有 Stage B evidence 足够清晰时才进入。

- 冻结 `NORMAL / CLIMAX / UNWIND / TAKEOVER` reducer；
- 冻结最少数阈值；
- 建立 policy identity / parameters hash；
- 运行 prefix invariance、long/short symmetry、contract/reset 测试；
- 独立 Review。

### Stage D — Web observation

只有 Stage C Review 通过后：

- additive API fields；
- Web 中文阶段语义与少量 Marker；
- 仍只支持 60m Historical confirmed；
- 不进入 Alert / Runtime / notification。

## 18. 验收标准

### Stage A

- member snapshot exact physical contract；
- pinned immutable dataset；
- `jm/ag/cu/m` 质量 Gate 通过或明确 fail-closed；
- 不新增第二套 member 存储架构；
- 不写 Canonical/DB。

### Stage B

- 所有 forensic facts 只由 60m confirmed Historical 输入得到；
- JM dossier 可解释 peak → decay → liquidation/opposite-build 的真实发生顺序；
- active60 pressure-only matrix 完整保留 unavailable cells 与全部 parameter-grid cells；
- member matrix 不把缺席位品种伪造成 neutral；
- 不输出正式 Phase、策略有效性或交易结论。

### Stage C

- reducer long/short 对称；
- prefix invariance 逐点通过；
- 换月/reset 不继承旧阶段；
- 阈值最小化且统一跨品种；
- JM 不是唯一支持案例；
- 不因 retrospective 后续走势回标早期 Phase；
- 证据不足时允许明确结论“不冻结 Phase”。

### Stage D

- Web 只展示已冻结 causal Phase；
- 非 60m 明确 unsupported；
- 不存在任何低周期隐式输入；
- caution 与 Phase 独立；
- 不修改 Alert/Runtime/订单能力。

## 19. Gate 与最终边界

本设计涉及主力压力/阶段公式、真实 RQData member 数据和未来 Web 可信口径，因此后续属于 Lane 3。

默认：

```text
Sol + 高推理
新会话
Plan-only
独立 Review
人工 Gate
```

其中：

- 真实 RQData snapshot build / research-data write：单独真实写入 Gate；
- Phase policy 冻结：Plan 批准 + 独立 Review；
- 代码合入 develop 不授权 release/main/tag；
- Web observation 合入 develop 不授权 Runtime promotion；
- 任何未来 Alert/notification/Signal 化必须另立任务。

最终研究目标不是证明“顶部一定能抓到”，而是：

> 在当时已经可见的 60m 数据下，系统能否以稳定、可解释、跨品种且不偷看未来的方式，识别强方向从高潮到退潮再到反方向接管的过程。
