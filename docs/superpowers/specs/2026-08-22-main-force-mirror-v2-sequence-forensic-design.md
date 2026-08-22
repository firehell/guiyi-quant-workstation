# 主力照妖镜 V2 60m Sequence Forensic 设计

状态：DESIGN_APPROVED / READY_FOR_IMPLEMENTATION

日期：2026-08-22

原始代码基线：`develop@e8b6152665d3ff27c470ecc6c56840c7da254897`

原计划起点：`develop@91baeecb028a537b79e69d6726e274c015ddbe79`

实际执行起点：`develop@fef886ac77b97136a0d222f5751ee63289ef2991`

阶段属性：historical-only / research-only / 60m-only / no promotion

## 1. 目标

当前 active `main_force_mirror_v2` 已经能用 confirmed 60m OHLCV/OI 给出五种即时压力、EMA5 累计压力、frozen caution，以及已有 pinned member snapshot 能提供的 T-1 member context。

它能回答“当前这一根 Bar 正在发生什么”，但不会直接归纳：

```text
强 long_build
→ accumulated pressure 衰减
→ long_liquidation
→ short_build
```

用户仍需要人工把多个 60m Bar 拼成“原方向高潮后是否退潮、是否被反方向接管”的判断。

本轮只增加 **sequence forensic research facts**，不增加正式 `CLIMAX / UNWIND / TAKEOVER` 产品语义。只有 sequence evidence 在跨品种、跨年份和 long/short 两侧都足够稳定，才允许另开 Lane 3 任务冻结正式 Phase 规则。

用户指定的 JM 2026-03 高位快速拉升案例只是 forensic case，不得成为单品种拟合目标。

## 2. 编码前五问审查

### 2.1 未来一年自己真的会用吗？

长期有价值的是“解释一次强压力之后发生了什么”，不是一个新的 Phase 子系统。因此本轮能力放进现有 `MainForceMirrorV2ResearchService`，不建新 service/package/repository/endpoint。

### 2.2 不做会不会影响核心价值？

至少满足两项：

1. **减少盯盘和人工拼接**：逐 Bar 状态不能直接回答峰值之后是否出现压力衰减和状态切换；
2. **增加复盘证据**：需要 causal、可复算的序列 dossier，避免用后续暴跌倒推顶部标签。

“发现机会”和“执行一致性”是否改善尚无证据，本轮不得宣称。

### 2.3 能不能直接复用现有能力？

必须直接复用：

```text
MarketDataService
→ existing MainForceMirrorV2Service
→ existing MainForceMirrorV2ResearchService
→ existing guiyi research main-force-mirror-v2 CLI
```

明确禁止新增：

```text
PhaseMemoryService
PhaseRepository
Phase API endpoint
Phase DB table
Phase snapshot/cache/checkpoint
第二套 MarketData reader
第二套 rank1 resolver
Alert/Runtime consumer
```

当前仓库 research 已收敛到 `services/quant-api/app/research/`；此前旧设计中 `app/market_data/main_force_mirror_v2_research_service.py` 的路径已过时，不能恢复旧路径。

### 2.4 哪些只是“以后可能需要”？

以下全部延迟：

- 正式 `NORMAL / CLIMAX / UNWIND / TAKEOVER` reducer；
- Web Phase Marker 和首页使用；
- member 3d/5d turn 新公式；
- 本地 raw member archive / provider cache / 增量 snapshot 复用层；
- 新 research protocol 文件；
- 自动参数搜索；
- 15m/5m/1m 辅助确认；
- Live、Alert、通知、Runtime；
- 持久化 research evidence。

真实 member snapshot 也不是本轮前置条件。pressure-only sequence forensic 必须先证明有价值；后续若需要 member 对比，只能复用现有 `main_force_member_rank_v1` builder/repository，并另取真实写入 Gate。

### 2.5 半年后一个人还能快速理解、修改和删除吗？

本轮代码面限定为现有 research/CLI 文件和测试；不改 V2 Kernel、不改 MarketDataService、不改 Web、不改 API。

删除本功能时应能通过删除一个小型 derived-fact helper、sequence summary/forensic DTO 字段、CLI flag 与对应测试完整移除，不留下数据库、migration、缓存或兼容层。

## 3. 固定范围

```text
frequency     = 60m only
series_kind   = actual_dominant | contract
bar_source    = Historical confirmed only
market_source = existing MarketDataService path
pressure      = existing main_force_mirror_v2 points
status        = research_only
readonly      = true
auto_order    = false
```

严禁读取、投影或辅助使用 15m/5m/1m。即使只是 forensic confirmation 也不允许。

## 4. 不修改的 active V2 语义

以下全部 zero-change：

- `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`；
- 五种 pressure state；
- instant pressure 公式和阈值；
- accumulated pressure EMA5；
- caution 评分、`>=70`、conflict 和 latch；
- member daily observation 和 relation；
- `MainForceMirrorV2Service` 的 API/Web point 合同；
- member snapshot schema/builder/repository；
- Web `MACD | 主力照妖镜 V2`；
- Alert / notification / Runtime。

因此本轮不能通过降低 caution threshold、修改 OI deadband、修改 EMA5 或给 JM 单独参数来“修截图”。

## 5. Sequence Forensic Fact

在 existing research service 内部新增一个 research-only immutable fact：

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceFact:
    index: int
    current_side: Literal["long", "short", "neutral"]
    pressure_state: str | None
    instant_pressure: float | None
    accumulated_pressure: float | None
    active_peak_index: int | None
    active_peak_side: Literal["long", "short"] | None
    active_peak_instant_pressure: float | None
    active_peak_accumulated_pressure: float | None
    bars_since_active_peak: int | None
    decay_ratio: Decimal | None
    installed_peak_index: int | None
    installed_peak_side: Literal["long", "short"] | None
    installed_peak_instant_pressure: float | None
    installed_peak_accumulated_pressure: float | None
    peak_seen: bool
    decay_seen: bool
    liquidation_seen: bool
    opposite_build_seen: bool
    accumulated_reversal_seen: bool
    state_transition: str | None
```

`current_side` 只表示当前 instant pressure 的符号。`active_peak_*` 是进入当前 Bar 时依然活跃、用于评价后续事件的旧 peak；`installed_peak_*` 是当前 Bar 在评价旧 peak 之后新安装的 build peak。`peak_seen` 等价于当前 Bar 安装了新 peak。该 fact 不是 API/Kernel 事实，不得被 Web 或其他 active consumer import。

### 5.1 Same physical-contract only

Sequence fact 只在连续同一 `physical_contract` 的 ready points 内回看。

以下任一条件出现时清空候选 peak memory：

- physical contract 改变；
- `pressure_ready=false`；
- 时间顺序异常；
- instant pressure 缺失或非有限；
- accumulated pressure 不可用时不清除 pressure-state memory，但只允许 pressure-state/liquidation/opposite-build fact，不伪造 decay/reversal。

不得跨换月连接峰值和后续状态。

### 5.2 Long / short 对称

Long side：

```text
same-side build   = long_build
liquidation       = long_liquidation
opposite build    = short_build
positive pressure = instant/accumulated > 0
```

Short side 镜像：

```text
same-side build   = short_build
liquidation       = short_cover
opposite build    = long_build
negative pressure = instant/accumulated < 0
```

不允许只针对 JM 顶部写单边规则。

### 5.3 First occurrence only

同一个 active peak 对 `decay_seen / liquidation_seen / opposite_build_seen / accumulated_reversal_seen` 每类最多产生一次事件。后续 Bar 仍可保留 `active_peak_index / bars_since_active_peak / decay_ratio` 作为 forensic context，但不得重复生成同一 cohort 事件。

## 6. 五个预定义 Research Profiles

不做笛卡尔积网格，不做最优参数搜索。只冻结 5 个简单 profile，用来判断结论是否对“更快/更慢/更宽松/更严格”扰动稳定：

| profile | peak_window | peak_quantile | decay_threshold | transition_window |
|---|---:|---:|---:|---:|
| `balanced` | 10 | 0.90 | 0.40 | 2 |
| `fast` | 5 | 0.90 | 0.40 | 1 |
| `slow` | 20 | 0.90 | 0.40 | 3 |
| `loose` | 10 | 0.85 | 0.25 | 2 |
| `strict` | 10 | 0.95 | 0.55 | 2 |

规则：

- 不允许按品种选择不同 profile；
- 不输出 `best_profile`、winner 或自动排序；
- forensic per-bar detail 只展示 `balanced`；
- summary 同时保留五个 profile 的样本和 outcome，供人工判断稳定性。

Peak candidate 使用同 block、strict-prior rolling percentile。当前 Bar 不进入自己的 percentile baseline；prior ready 样本不足 `peak_window` 时该 Bar 不能成为 peak candidate。

Percentile 固定采用 **nearest-rank**，避免插值策略和额外依赖：

```text
ordered = sort(abs(prior ready instant pressure))
rank = ceil(q * N)
threshold = ordered[max(1, rank) - 1]
peak_candidate = abs(current instant pressure) >= threshold
```

Peak candidate 第一轮只允许 `long_build` / `short_build`。`turnover`、`short_cover`、`long_liquidation` 不安装新的 active peak：这样既保持“强建仓压力高潮”的研究语义，也避免在“旧方向 liquidation → 新方向 build”过程中用 liquidation Bar 抢占旧 peak memory。若未来证据表明 short-cover/long-liquidation climax 本身值得独立研究，再另开设计，不在本轮提前扩张。

## 7. Candidate Sequence Events

本轮只研究事件事实，不发布正式 Phase：

```text
peak_seen
peak_then_decay
peak_then_liquidation
peak_then_opposite_build
peak_then_accumulated_reversal
```

后四项都必须在事件实际发生的当前 Bar 才命中，不能回标 peak Bar。

如果当前 Bar 既是前一个 peak 的 causal sequence event，又满足反方向的新 build peak candidate，处理顺序固定为：先把旧 peak 保存在 `active_peak_*` 并记录当前事件，再把当前 Bar 保存在 `installed_peak_*` 并安装为后续 Bar 的 active peak。同一 Bar 必须同时形成旧方向 sequence-event observation 和新方向 `peak_only` observation，不得丢失任一 cohort。

### 7.1 Decay

Long / short 统一先投影到 peak 方向：

```text
direction = +1 for long, -1 for short
projected_current = direction * current_accumulated
decay_ratio = (abs(peak_accumulated) - projected_current) / abs(peak_accumulated)
```

仅在 peak accumulated 与 peak side 同号且 current accumulated 可用时计算。穿越零轴后
long `+80 -> -40` 与 short `-80 -> +40` 都得到 `decay_ratio = 1.5`，保持严格镜像；
不得对 current 先取绝对值。`projected_current < 0` 时
`accumulated_reversal_seen=true`；decay ratio 允许大于 1，不 clip。

### 7.2 Liquidation / opposite build

只记录 peak 之后实际看到的 state：

```text
long peak:
  long_liquidation → liquidation_seen
  short_build      → opposite_build_seen

short peak:
  short_cover      → liquidation_seen
  long_build       → opposite_build_seen
```

状态必须发生在 profile 的 `transition_window` 内；超过窗口则该 profile 不命中，active peak memory 过期。

## 8. Retrospective Outcome

继续复用现有 research service 的：

```text
HORIZONS = 1 / 3 / 5 / 10 × 60m
```

所有 forward outcome 不跨 physical contract。

新增 sequence cohort：

```text
peak_only
peak_then_decay
peak_then_liquidation
peak_then_opposite_build
peak_then_accumulated_reversal
```

每个 profile 输出这些 cohort 的 summary。输出继续按 product/year 分层，并新增 side=`long|short` 维度；pooled 只作摘要。

`peak_only` 的 observation time 是 peak Bar；其余 sequence cohort 的 observation time 都是对应 evidence 首次实际出现的 Bar。这样 future horizon 从“当时已经知道该事实”的时点开始，禁止从 peak Bar 回测后验事件。

评价优先级：

1. 样本数；
2. long/short 对称性；
3. 产品间稳定性；
4. 年份间漂移；
5. sequence 事件是否足够早而有人工观察价值；
6. 五个 profile 是否形成稳定方向，而不是只有一个 profile 好看。

不得以收益最大化挑 profile，不输出 Sharpe、权益曲线、PnL 或 winner。

## 9. JM Forensic Dossier

现有 `guiyi research main-force-mirror-v2` 增加 opt-in：

```text
--forensic
```

默认不加 flag 时维持当前 summary 字段和语义，只 additive 增加小型 `sequence_profiles` 摘要。

`--forensic` 时额外输出 requested window 的 per-bar `balanced` sequence points，至少包括：

```text
bar_end
trading_day
physical_contract
pressure_state
instant_pressure
accumulated_pressure
price_impulse
volume_ratio
delta_oi
oi_impulse
range_position
caution
long_caution_score
short_caution_score
caution_reason_codes
balanced sequence fact
member status/relation（如果当前 V2 point 已有；不新增 member 公式）
```

JM 2026-03 case 用它回答“最早何时发生 decay/liquidation/opposite build/reversal”，但不要求命中任何预设 Phase 标签。

## 10. Prefix invariance

Sequence derivation 必须满足：

```text
derive(points[0:t], profile)[-1]
==
derive(points[0:N], profile)[t]
```

至少对以下输出逐点成立：

```text
peak identity
decay_ratio
peak_seen
decay_seen
liquidation_seen
opposite_build_seen
accumulated_reversal_seen
state_transition
```

任何使用 future horizon 的 outcome 都只能位于 summarizer/evaluation 层，不能进入 SequenceFact。

## 11. 实施文件边界

允许修改：

```text
services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_payloads.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md（仅补充 --forensic 合同）
docs/superpowers/specs/2026-08-22-main-force-mirror-v2-sequence-forensic-design.md
docs/superpowers/plans/2026-08-22-main-force-mirror-v2-sequence-forensic.md
docs/tasks/TASK-MFM-V2-SEQUENCE-FORENSIC-20260822.md
```

禁止修改：

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py
services/quant-api/app/market_data/main_force_mirror_v2_service.py
services/quant-api/app/market_data/member_rank_snapshot.py
services/quant-api/app/market_data/member_rank_snapshot_builder.py
MarketDataService / MainContractMap / Canonical / DB migrations
apps/quant-web/**
Alert / Execution Review / Runtime
STATUS.md / PROJECT_SOURCE.md / DECISIONS.md
```

如实现发现必须突破禁止范围，停止并升级设计，不得顺手扩张。

## 12. 第一轮不做真实 member 写入

当前 `STATUS.md` 仍记录真实 member snapshot 和 retrospective matrix 未执行。本轮 implementation 与 pressure-only forensic 不需要真实 member snapshot：

- 不调用 RQData；
- 不执行 `guiyi data member-rank snapshot --apply`；
- 不写 research-data-root；
- 不把 member data 作为 sequence Gate。

只有 pressure-only evidence 证明值得继续，才另开任务决定是否用现有 member snapshot 能力补充解释。该后续动作涉及真实 provider 请求和研究数据写入，必须另取一次性 Gate。

## 13. 验收

代码验收：

1. 默认 `guiyi research main-force-mirror-v2` 现有字段和语义不回归；
2. sequence facts strict 60m only、same physical-contract only；
3. long/short mirror tests；
4. contract switch reset tests；
5. prefix invariance tests；
6. physical-contract、pressure unavailable 和时间非严格递增全部 reset；
7. accumulated unavailable 时不伪造 decay/reversal；
8. 同 Bar 旧 peak event + 新 peak installation 双事实不丢样；
9. no future outcome leaks into sequence facts；
10. 同一 peak 的每类 sequence event 只首次产生一次；
11. `--forensic` 只改变 stdout detail，不改变 market/V2 calculation；
12. V2 Kernel golden/Registry/Service tests保持通过；
13. 无新 module/package/service/endpoint/migration；
14. 无 RQData/Canonical/DB/Redis 写入。

研究 Gate：

- 先运行 JM forensic；
- 再人工循环 active60 运行 pressure-only summary；
- 只形成 retrospective diagnosis；
- evidence 不稳定则 `STOP`，不进入正式 Phase；
- evidence 稳定才允许另开 Lane 3 Phase-freeze 设计。

本轮不新增 active60 orchestrator；需要批量运行时使用已有 CLI 的简单外层 shell loop 或 Codex CLI automation，不把机械批处理做成产品模块。

## 14. 删除性验收

半年后若不再需要，应可通过删除以下内容完整移除：

```text
MainForceMirrorV2SequenceProfile / SequenceFact + helper/summarizer
research result 的 sequence/forensic 字段
--forensic flag
对应测试
TESTING.md 的 forensic 文案
```

无需 migration、数据清理、缓存重建或 Runtime rollback。
