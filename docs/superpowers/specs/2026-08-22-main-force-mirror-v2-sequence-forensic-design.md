# 主力照妖镜 V2 60m Sequence Forensic 设计

状态：DESIGN_APPROVED / PLAN_READY

日期：2026-08-22

基线：`develop@e8b615e0453f00128ea4f2a385aca8699a958744`

阶段属性：historical-only / research-only / 60m-only / no promotion

## 1. 这轮为什么做，以及为什么只做这么多

当前 active `main_force_mirror_v2` 已经能用 confirmed 60m OHLCV/OI 给出：

```text
long_build / short_build / short_cover / long_liquidation / turnover
instant_pressure
accumulated_pressure EMA5
frozen caution
T-1 member context（有 pinned snapshot 时）
```

它回答“当前这一根 Bar 正在发生什么”，但对如下连续序列没有直接归纳：

```text
强 long_build
→ accumulated pressure 衰减
→ long_liquidation
→ short_build
```

用户因此仍需人工把多个 60m Bar 拼成“原方向高潮后是否退潮、是否被反方向接管”的判断。用户指定的 JM 2026-03 高位快速拉升案例暴露了这个盲点，但该案例只能作为 forensic case，不得成为单品种拟合目标。

本轮只增加 **sequence forensic research facts**，不增加正式 `CLIMAX / UNWIND / TAKEOVER` 产品语义。只有 sequence evidence 在跨品种、跨年份和 long/short 两侧都足够稳定，才允许另开 Lane 3 任务冻结正式 Phase 规则。

## 2. 编码前五问审查

### Q1：未来一年自己真的会用吗？

会长期使用的是“解释一次强压力之后发生了什么”的能力，不是一个新的 Phase 子系统。因此本轮只把该能力放进现有 `MainForceMirrorV2ResearchService`，不建新的 service/package/repository/endpoint。

### Q2：不做会不会影响核心价值？

满足至少两项长期价值：

1. **减少盯盘和人工拼接**：当前逐 Bar 状态不能直接回答峰值之后是否出现压力衰减和状态切换；
2. **增加复盘证据**：需要一个 causal、可复算的序列 dossier，避免用后续暴跌倒推顶部标签。

“发现机会”和“执行一致性”是否改善尚无证据，本轮不得宣称。

### Q3：能不能直接复用现有能力？

可以，而且必须复用：

```text
MarketDataService
→ existing MainForceMirrorV2Service
→ existing MainForceMirrorV2ResearchService
→ existing guiyi research main-force-mirror-v2 CLI
```

因此明确禁止新增：

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

### Q4：哪些只是“以后可能需要”？

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

真实 member snapshot 也不是本轮前置条件。pressure-only sequence forensic 必须先证明有价值；需要 member 对比时只复用现有 `main_force_member_rank_v1` builder/repository，并另取真实写入 Gate。

### Q5：半年后一个人还能快速理解、修改和删除吗？

本轮代码面限定为现有 research/CLI 文件和测试：

```text
services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_payloads.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
```

不改 V2 Kernel、不改 MarketDataService、不改 Web、不改 API。删除本功能时应能通过删除一个小型 derived-fact helper、其 summary/forensic DTO 字段、CLI flag 与对应测试完整移除，不留下数据库、migration、缓存或兼容层。

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

在 existing research service 内部新增一个 research-only immutable fact，建议命名：

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceFact:
    index: int
    side: Literal["long", "short", "neutral"]
    pressure_state: str | None
    instant_pressure: float | None
    accumulated_pressure: float | None
    recent_peak_window: int | None
    peak_index: int | None
    peak_pressure: float | None
    bars_since_peak: int | None
    decay_ratio: float | None
    liquidation_seen: bool
    opposite_build_seen: bool
    accumulated_reversal_seen: bool
    state_transition: str | None
```

它不是 API/Kernel 事实，不得被 Web 或其他 consumer import。

### 5.1 同一 calculation block

Sequence fact 必须复用 `MainForceMirrorV2Point.physical_contract` 身份，且只在连续同一物理合约的 ready points 内回看。

以下任何情况都必须清空候选 peak memory：

- physical contract 改变；
- point `pressure_ready=false`；
- 时间顺序异常（现有 service 正常情况下应已 fail-closed，但 helper 不得跨异常继续）；
- accumulated pressure 不可用时只允许 pressure-state fact，不伪造 decay/reversal。

不得跨换月连接峰值和后续状态。

### 5.2 对称方向语义

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

## 6. 固定 Candidate Grid，不做最优参数搜索

第一轮只比较一个很小、预先冻结的 forensic grid：

```text
peak_windows          = 3 / 5 / 10 / 20 bars
decay_thresholds      = 0.25 / 0.40 / 0.55
transition_windows    = 1 / 2 / 3 bars
```

Peak candidate 不使用绝对 strength 阈值，而使用同 block、strict-prior 的 rolling percentile：

```text
peak_quantiles = 0.85 / 0.90 / 0.95
```

计算当前 Bar 是否为 peak candidate 时，percentile baseline 只能来自当前 Bar 之前的同 block ready pressure magnitude；当前 Bar 不进入自己的 baseline。baseline 样本不足对应 window 时该 candidate unavailable。

Grid 的目的仅是判断结论是否对小范围参数扰动稳定；不得按产品选不同参数，不得输出“best parameters”。

## 7. Candidate Sequence Events

本轮只研究布尔/时间事实，不发布正式 Phase：

```text
peak_seen
peak_then_decay
peak_then_liquidation
peak_then_opposite_build
peak_then_accumulated_reversal
```

其中后四项都必须在该事件实际发生的当前 Bar 才变为 true，不能回标 peak Bar。

### 7.1 Decay

对 long peak：

```text
decay_ratio = (peak_accumulated - current_accumulated) / abs(peak_accumulated)
```

仅在 `peak_accumulated > 0` 且 current accumulated 可用时计算。

对 short peak 镜像：

```text
decay_ratio = (abs(peak_accumulated) - abs(current_accumulated)) / abs(peak_accumulated)
```

如果当前 accumulated 已反号，`accumulated_reversal_seen=true`，decay ratio 允许大于 1；不得 clip 为 1。

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

状态必须发生在对应 `transition_window` 内；超过窗口则该 grid cell 不命中。

## 8. Retrospective Outcome

继续复用现有 research service 的：

```text
HORIZONS = 1 / 3 / 5 / 10 × 60m
```

所有 forward outcome 不跨 physical contract。

新增 sequence cohort 只比较：

```text
peak_only
peak_then_decay
peak_then_liquidation
peak_then_opposite_build
peak_then_accumulated_reversal
```

输出仍按：

```text
product
year
side = long / short
```

分层；pooled 只做次要摘要。

评价优先级：

1. 样本数是否足够；
2. long/short 是否近似对称；
3. 产品间是否方向一致或至少可解释；
4. 年份间是否严重漂移；
5. sequence 后验发生时间是否早到具有人工观察价值；
6. 参数 grid 是否呈稳定区域，而不是单个尖峰。

不得以收益最大化挑参数，不输出 Sharpe、权益曲线、PnL 或 winner。

## 9. JM Forensic Dossier

现有 `guiyi research main-force-mirror-v2` 增加一个 opt-in：

```text
--forensic
```

默认不加 flag 时维持当前 summary 行为，只增加小型 `sequence` 摘要字段。

`--forensic` 时在 stdout JSON 额外输出 requested window 的 per-bar sequence points，至少包括：

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
sequence facts
member status/relation（若现有 V2 point 已有；不新增 member 公式）
```

JM 2026-03 case 用它回答“最早何时发生 decay/liquidation/opposite build/reversal”，但不要求命中任何预设 Phase 标签。

## 10. Prefix invariance

Sequence derivation 必须满足：

```text
derive(points[0:t])[-1]
==
derive(points[0:N])[t]
```

至少对以下输出逐点成立：

```text
peak candidate identity
decay_ratio
liquidation_seen
opposite_build_seen
accumulated_reversal_seen
state_transition
```

任何使用 future horizon 的 outcome 都必须位于 summarizer/evaluation 层，不能进入 SequenceFact。

## 11. 实施文件边界

### 允许修改

```text
services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_payloads.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md（仅在命令合同确实新增 --forensic 后补充）
```

### 禁止修改

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py
services/quant-api/app/market_data/main_force_mirror_v2_service.py
services/quant-api/app/market_data/member_rank_snapshot.py
services/quant-api/app/market_data/member_rank_snapshot_builder.py
MarketDataService / MainContractMap / Canonical / DB migrations
apps/quant-web/**
Alert / Execution Review / Runtime
STATUS.md / PROJECT_SOURCE.md / DECISIONS.md（第一轮实验不宣布 active semantic）
```

如果实现发现必须突破禁止范围，应停止并升级设计，不得顺手扩张。

## 12. 第一轮明确不做真实 member 写入

当前 `STATUS.md` 仍记录真实 member snapshot 和 retrospective matrix 未执行。本轮 implementation 和 pressure-only forensic 不需要真实 member snapshot，因此：

- 不调用 RQData；
- 不执行 `guiyi data member-rank snapshot --apply`；
- 不写 research-data-root；
- 不把 member data 作为 sequence Gate。

只有 pressure-only evidence 证明值得继续，才另开任务决定是否使用现有 member snapshot 能力补充解释。该后续动作涉及真实 provider 请求和研究数据写入，必须另取一次性 Gate。

## 13. 验收

代码验收：

1. 默认 `guiyi research main-force-mirror-v2` 现有字段和语义不回归；
2. sequence facts strict 60m only、same physical-contract only；
3. long/short mirror tests；
4. contract switch reset tests；
5. prefix invariance tests；
6. no future outcome leaks into sequence facts；
7. `--forensic` 只改变 stdout detail，不改变 market/V2 calculation；
8. V2 Kernel golden/Registry/Service tests保持通过；
9. 无新 module/package/service/endpoint/migration；
10. 无 RQData/Canonical/DB/Redis 写入。

研究 Gate：

- 先运行 JM forensic；
- 再运行 active60 pressure-only matrix；
- 只形成 retrospective diagnosis；
- evidence 不稳定则 `STOP`，不进入正式 Phase；
- evidence 稳定才允许另开 Lane 3 Phase-freeze 设计。

## 14. 删除性验收

如果半年后不再需要，本轮功能应该能通过删除以下内容完全移除：

```text
MainForceMirrorV2SequenceFact + sequence helper/summarizer
research result 的 sequence/forensic 字段
--forensic flag
两处对应测试
TESTING.md 的 forensic 文案
```

删除后无需 migration、数据清理、缓存重建或 Runtime rollback。
