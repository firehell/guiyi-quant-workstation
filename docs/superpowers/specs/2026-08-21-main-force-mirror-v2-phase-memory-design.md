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

但在典型的快速拉升见顶段中，逐 Bar 事实可能依次表现为：

```text
强 long_build
→ long_liquidation
→ short_build
```

当前模型不会把这个序列归纳为“多头压力高潮 → 多头退潮 → 空头接管”。因此用户仍需要人工把多个 Bar、累计压力、价格位置与席位变化拼接成阶段判断。

本设计增加一个 **causal Phase Memory 研究层**，专门回答：

> 最近发生过什么，以及当前状态相对最近的强势阶段发生了什么变化？

它不是“出货预测器”，不回看未来确认顶部，不修改现有 V2 即时压力、累计压力、“小心”或席位公式。

## 2. 已批准约束

1. 周期继续严格只做 `60m`。
2. 不引入 15m / 5m / 1m 作为 Phase Memory 输入、确认或辅助 Gate。
3. 不构造 60m + 15m 多周期模型。
4. 现有 V2 五状态、instant pressure、EMA5 accumulated pressure、“小心”公式和 member relation 首轮全部保持不变。
5. Phase Memory 首先是 historical research / forensic，不直接进入 Web active semantics、Alert、notification、Runtime 或 Execution Review。
6. 任何阶段标签都只能使用当前 Bar 及其之前的 60m Historical confirmed facts；禁止未来函数、后验回标和重绘。
7. 用户指定的 JM 高位快速拉升案例只作为解释性 Golden Behavior Case，不作为必须拟合成功的参数目标。
8. `auto_order=false` 始终成立。

## 3. 不做什么

本任务明确不做：

```text
15m/5m/1m phase confirmation
跨周期共振
修改 MarketDataService / Canonical / MainContractMap
新增 Market Catalog 表
实时 RQData 查询
Live phase
Alert / PushPlus
Signal / Strategy promotion
回测撮合、PnL、成本、仓位
自动寻找“最优出货参数”
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

Member 历史仍采用现有：

```text
main_force_member_rank_v1
```

不可变研究快照。

第一阶段不新增第二套 raw archive、Catalog、SQLite 或 member cache 子系统。第一次真实 retrospective 所需缺失席位数据可通过现有 exact-contract RQData snapshot builder 在一次明确 Gate 下构建；快照发布后，重复研究全部只读本地 pinned dataset。

因此长期形态是：

```text
RQData（外部唯一来源）
→ 一次受控 snapshot build
→ immutable local member snapshot
→ 后续反复本地研究
```

如果未来 provider 请求量或重复 snapshot 构建成本成为真实问题，再单独设计增量复用；本任务不提前建设。

## 5. 四层解释模型

Phase Memory 建立在现有 V2 之上，不替代底层事实：

```text
Layer 1  Instant Pressure
当前这一根 Bar 在做什么？

Layer 2  Accumulated Pressure
当前方向压力最近是否持续、衰减或反转？

Layer 3  Phase Memory
最近是否出现过压力高潮？高潮之后是否正在退潮或被反方向接管？

Layer 4  Member Context
更慢一级的 T-1 席位结构是否同向、背离或发生转折？
```

后续价格结果只用于 retrospective evaluation，不允许反向修改当时 Phase。

## 6. Phase Memory Research Facts

第一阶段只新增可解释的 forensic facts，不冻结阶段阈值。

每个同 physical-contract calculation block 内，对每个 `pressure_ready` 60m point 计算候选研究字段：

```text
recent_pressure_peak
bars_since_pressure_peak
peak_instant_pressure
peak_accumulated_pressure

accumulated_pressure
accumulated_pressure_delta
pressure_decay_ratio

recent_price_extreme
bars_since_price_extreme
close_distance_from_extreme_atr
range_position

previous_pressure_state
state_transition
same_side_build_streak
opposite_build_streak
liquidation_streak

recent_state_sequence_3
recent_state_sequence_5
```

### 6.1 方向对称

所有研究字段必须 long / short 对称定义。

例如：

```text
多头高潮后的 long_liquidation
```

与：

```text
空头高潮后的 short_cover
```

必须使用镜像规则，不允许只针对 JM 顶部写单边特例。

### 6.2 calculation block

Phase Memory 与 V2 同样严格按 physical contract block：

- 合法换月立即清空；
- invalid Bar 结束 block；
- timestamp 冲突结束 block；
- 不跨旧主力合约继承 climax / unwind / takeover memory。

## 7. Member History Research Facts

现有单日字段继续保留：

```text
change_bias
member_strength
position_skew
top5_volume_share
```

Phase research 允许额外计算描述性 causal history：

```text
member_bias_3d
member_bias_5d
member_bias_delta
member_bias_turn
```

原则：

1. 只使用当前 Bar 可见的 T-1 或更早 member day；
2. 不把 member 数据融合进 instant pressure；
3. 第一版不把 member turn 作为 Phase Gate；
4. member unavailable 时 pressure-only Phase research 仍可执行；
5. member facts 只对当前 admitted products `jm/ag/cu/m` 研究，其他 active products 明确 unavailable，不降级到产品汇总排名。

## 8. 最小阶段模型

最终若 retrospective evidence 支持，只考虑以下最小状态，不扩展 Wyckoff 全套阶段术语：

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

人类解释层示例：

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

第一阶段只研究结构，不冻结具体数字。

候选结构为：

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

- 用未来 3/5/10 根下跌把早先高点回标为 CLIMAX 或 UNWIND；
- 在当前 Bar 尚无证据时预先标记“出货”；
- 因为后续价格大跌就强制要求顶部附近一定出现特定标签。

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

对用户指定的 2026-03 高位快速拉升区间，输出逐 Bar forensic dossier：

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
Phase research facts
```

必须回答：

1. 为什么强拉升 Bar 是 `long_build`；
2. 最早哪一根 60m Bar 出现多头压力衰减；
3. 最早哪一根出现 `long_liquidation`；
4. 最早哪一根出现 `short_build`；
5. accumulated pressure 何时开始衰减、何时反号；
6. member context 当时是同向、背离还是转折；
7. 在不看未来价格的前提下，最早可合理称为 `UNWIND` / `TAKEOVER` 的时点。

该 case 只用于解释和回归，不允许为了让它命中特定结果而单独调参。

### 11.2 Pressure-only matrix

范围：

```text
active 60
× 60m actual_dominant
× Historical confirmed
```

使用本地 Canonical，仅研究：

```text
pressure peak
accumulated decay
state transition
climax → unwind
climax → takeover
```

### 11.3 Member-context matrix

范围只限：

```text
jm / ag / cu / m
```

在 pressure-only cohort 上叠加：

```text
member aligned
member divergent
member bias turn
member unavailable
```

member layer不得决定 pressure-only cohort 是否成立。

## 12. Retrospective evaluation

复用现有 V2 research infrastructure，不新增 backtest engine。

固定 forward horizons 仍为：

```text
1 / 3 / 5 / 10 根 60m Bar
```

且不得跨 physical contract。

主要比较 cohort：

```text
climax_only
climax_then_decay
climax_then_liquidation
climax_then_opposite_build
climax_then_unwind
climax_then_takeover

以上 cohort
× member aligned / divergent / turn / unavailable
```

输出至少按：

```text
product
year
long / short side
```

分层。

pooled 只作为摘要，不能掩盖品种和年份异质性。

第一阶段评价重点不是“哪组赚钱最多”，而是：

1. cohort 是否稳定表达同一种市场行为；
2. 发生时间是否足够早而不是完全后验；
3. long / short 是否近似对称；
4. 是否只在极少数单品种有效；
5. member history 是否增加解释力，还是只增加复杂度。

## 13. 阈值冻结规则

本设计暂不批准任何新的 Phase 数值阈值。

例如以下数值目前全部禁止直接写入正式参数：

```text
高潮 strength >= ?
pressure decay >= ?%
几根内出现 liquidation
几根 opposite build 算 takeover
距离极值多少 ATR
```

只有完成 forensic matrix 后，才能冻结最小必要阈值。

冻结时必须满足：

1. 使用统一跨品种规则，不按 JM 单独优化；
2. long / short 对称；
3. 参数进入独立 Phase policy hash；
4. 任何后续修改产生新版本或新 hash；
5. 阈值数量保持最少，避免组合爆炸。

## 14. Prefix invariance / 防未来函数

Phase reducer 必须通过逐 prefix 重算验证：

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

如果未来完整序列改变历史 Phase，则任务直接阻塞，不允许进入 Web。

## 15. Web 设计边界

Phase 规则冻结并通过 retrospective review 前，不修改 active Web 阶段语义。

研究通过后，Web 最终只增加少量阶段变化 Marker，不恢复 V0“每根柱子都写进场/拉高/出货”的模式。

目标信息层级：

```text
当前阶段：多头退潮观察
即时：多头减仓 -72
累计：+41 → +17 → -3
席位 T-1：多头结构转弱
```

图形仍保持：

```text
柱 = instant pressure
线 = accumulated pressure
Marker = frozen caution
Marker = CLIMAX / UNWIND / TAKEOVER transition
```

不显示资金净流入比例、胜率、未来反转概率或交易指令。

## 16. 分阶段实施顺序

### Stage A — 真实数据准备

目标：获得可重复使用的真实 member retrospective snapshot。

- 只使用现有 snapshot builder；
- 先 dry-run；
- 用户明确 Gate 后才允许真实 RQData 请求与研究数据写入；
- 发布 immutable dataset 后固定 dataset_id；
- 不触碰 Canonical / DB / Runtime。

### Stage B — Forensic facts

目标：只增加 research-only 60m Phase facts 和 CLI/report 输出。

- 不改 active V2 Web；
- 不改 caution；
- 不冻结 Phase threshold；
- 先完成 JM dossier；
- 再跑 active60 pressure-only matrix；
- member context 只跑 jm/ag/cu/m。

### Stage C — Freeze Phase policy

只有 Stage B evidence 足够清晰时才进入。

- 冻结 `NORMAL / CLIMAX / UNWIND / TAKEOVER` reducer；
- 冻结最少数阈值；
- 建立 policy identity / parameters hash；
- 运行 prefix invariance、long/short symmetry、contract-reset 测试；
- 独立 Review。

### Stage D — Web observation

只有 Stage C Review 通过后：

- additive API fields；
- Web 中文阶段语义与少量 Marker；
- 仍只支持 60m Historical confirmed；
- 不进入 Alert / Runtime / notification。

## 17. 验收标准

### Stage A

- member snapshot exact physical contract；
- pinned immutable dataset；
- `jm/ag/cu/m` 质量 Gate 通过或明确 fail-closed；
- 不新增第二套 member 存储架构；
- 不写 Canonical/DB。

### Stage B

- 所有 Phase research facts 只由 60m confirmed historical 输入得到；
- JM dossier 可解释 peak → decay → liquidation/opposite-build 的真实发生顺序；
- active60 pressure-only matrix 完整保留 unavailable cells；
- member matrix 不把缺席位品种伪造成 neutral；
- 不输出正式 Phase 结论或策略有效性。

### Stage C

- reducer long/short 对称；
- prefix invariance 逐点通过；
- 换月/reset 不继承旧阶段；
- 阈值最小化且统一跨品种；
- JM 不是唯一支持案例；
- 不因 retrospective 后续走势回标早期 Phase。

### Stage D

- Web 只展示已冻结 causal Phase；
- 其他周期明确 unsupported；
- 不偷偷使用 15m；
- caution 与 Phase 独立；
- 不修改 Alert/Runtime/订单能力。

## 18. Gate 与最终边界

本设计涉及主力压力/阶段公式、真实 RQData member 数据和未来 Web 可信口径，因此后续属于 Lane 3。

必须保持：

```text
Sol + 高推理
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
