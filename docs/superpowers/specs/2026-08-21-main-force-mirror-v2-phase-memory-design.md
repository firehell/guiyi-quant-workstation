# 主力照妖镜 V2 Phase Memory Research 设计

状态：DESIGN_APPROVED / IMPLEMENTATION_PLAN_READY

日期：2026-08-21

阶段属性：historical-only / observation-only / research-only / 60m-only / no promotion

## 1. 开始编码前的五问 Review

本设计先按个人量化项目的五个问题重新审查，不以“技术上能做”为实施理由。

### 1.1 未来一年真的会用吗？

**判断：有条件地会。**

主力照妖镜已经是 Market Web 的 active research observation。用户实际会持续遇到“单根 60m 压力很强，但后续很快反转”的解释问题；如果系统只能给逐 Bar 五状态，仍需要人工把连续 Bar 拼成故事。

但“Phase 标签”本身是否值得长期保留尚未被历史证据证明，因此当前只批准最小 research/forensic 能力，不批准 active Phase 产品化。

### 1.2 不做会不会影响四项价值？

当前问题至少影响三项：

1. **减少盯盘时间**：逐根解释 `long_build → long_liquidation → short_build` 需要人工回看；
2. **提高执行一致性**：同一序列容易被不同时间点主观解释为“继续强势”或“已经退潮”；
3. **增加复盘证据**：现有结果保存了单点压力，但没有保存“当时已经可见的状态迁移事实”。

对“提高发现机会概率”的价值目前只是间接假设，不作为实施理由。

因此当前 research-only 工作满足项目价值门槛；如果 retrospective 结果不能证明前述三项中的至少一项得到实质改善，则停止，不进入 Phase 产品化。

### 1.3 能不能直接复用现有 MarketDataService / Research / Member Snapshot？

**能。结论：不建新产品模块。**

直接复用：

```text
MarketDataService
→ existing MainForceMirrorV2Service
→ existing MainForceMirrorV2ResearchService
→ existing guiyi research main-force-mirror-v2
```

Member 继续复用：

```text
main_force_member_rank_v1
MemberRankSnapshotRepository
existing snapshot builder
```

本任务不新增：

```text
新的 Application Domain
新的 DB 表
新的 Catalog
新的 API endpoint
新的 Web 页面/Pane
新的 CLI command
新的 snapshot 格式
新的 provider seam
新的 scheduler/cache/checkpoint
```

### 1.4 哪些是真实复杂度，哪些只是“以后可能需要”？

**真实业务复杂度只有一项：60m 状态序列的 causal memory。**

已观察到的实际问题是：当前 V2 能正确描述每根 60m Bar，却不能直接回答“最近的强方向是否已经发生减仓或反向建仓”。这需要最小的前序状态记忆。

以下全部属于“以后可能需要”，本任务延迟设计：

```text
15m / 5m / 1m 辅助确认
跨周期模型
CLIMAX / UNWIND / TAKEOVER 正式阈值
Web Phase Marker
Live Phase
Alert / PushPlus
新的 member 3d/5d 指标体系
member 增量 cache/archive
自动 snapshot refresh
通用 phase framework
策略/回测/订单
```

### 1.5 半年后一个人还能快速理解、修改和删除吗？

**设计目标：可以。**

本轮只修改现有 V2 research service、现有 research CLI serializer/parser 和对应测试；不新增持久状态或运行服务。若结果无价值，删除 sequence facts/cohorts 和 `--forensic` 即可回到当前 V2，不涉及 migration、数据回滚或 Runtime 清理。

## 2. 本轮唯一目标

本轮不实现“Phase 模型”。只回答一个问题：

> 在严格 60m、只看当时已知信息的条件下，保存最小状态迁移事实，是否能稳定解释当前 V2 逐 Bar 压力无法直接表达的“强方向退潮 / 反方向接管”现象？

因此本轮交付物是：

```text
existing V2 points
→ causal 60m sequence facts
→ exact transition cohorts
→ existing 1/3/5/10-bar retrospective summaries
→ optional forensic JSON for one requested window
```

**没有正式 Phase label，没有新参数 policy，没有 Web 展示。**

## 3. 周期和身份边界

固定：

```text
frequency   = 60m only
series_kind = actual_dominant | contract
bar_source  = Historical confirmed Canonical only
identity    = existing main_force_mirror_v2
status      = research_only / readonly
```

严格禁止：

```text
15m / 5m / 1m / 30m / 1d / 1w
continuous
Redis Live
未确认 Bar
跨 physical contract memory
```

不新增 `phase_indicator_code`、`phase_policy_id` 或其他 active identity。

## 4. 复用现有 V2，不修改 Kernel 语义

本任务不得修改：

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py
```

因此以下全部冻结：

```text
instant pressure 五状态
instant pressure 公式
EMA5 accumulated pressure
caution score / >=70 threshold
caution conflict / latch
member direction / strength / relation
parameters_hash
```

Phase Memory Research 只消费 `MainForceMirrorV2Point` 已有字段。

## 5. 最小 Sequence Fact

在 existing `main_force_mirror_v2_research_service.py` 内增加一个纯 research dataclass：

```python
MainForceMirrorV2SequenceFact
```

每个 fact 对齐一个当前 `pressure_ready` point，只保存已经存在或由相邻历史点直接推导的字段：

```text
bar_end
trading_day
physical_contract
previous_state
current_state
state_transition
previous_instant_pressure
current_instant_pressure
previous_accumulated_pressure
current_accumulated_pressure
accumulated_delta
accumulated_sign_flip
state_sequence_3
state_sequence_5
range_position
caution
member_relation_to_accumulated
```

不新增 ATR、价格结构、摆动点、N 字、VWAP、订单流或其他指标。

### 5.1 `state_transition`

格式固定：

```text
<previous_state>-><current_state>
```

只有当前点和上一根**同 physical-contract、连续 pressure-ready** 点都存在时才有值，否则为 `None`。

### 5.2 `accumulated_delta`

只有前后两根都 `accumulated_ready` 时：

```text
current_accumulated_pressure - previous_accumulated_pressure
```

否则为 `None`。

### 5.3 `accumulated_sign_flip`

只允许：

```text
positive_to_negative
negative_to_positive
None
```

零值不猜方向，不触发 sign flip。

### 5.4 `state_sequence_3/5`

只包含当前 physical-contract calculation block 内连续 `pressure_ready` 状态；不足长度时返回实际已有 prefix，不向前跨换月或 invalid gap 补齐。

## 6. exact Transition Cohorts

本轮不使用 `CLIMAX / UNWIND / TAKEOVER` 作为代码语义，只统计以下 exact observed sequence：

```text
long_build_to_long_liquidation
long_build_to_short_build
long_build_to_long_liquidation_to_short_build

short_build_to_short_cover
short_build_to_long_build
short_build_to_short_cover_to_long_build

accumulated_positive_to_negative
accumulated_negative_to_positive
```

定义要求：

1. 两步 cohort 必须是相邻、同 physical-contract、连续 pressure-ready Bar；
2. 三步 cohort 必须是三个连续、同 physical-contract、pressure-ready Bar；
3. 不允许在中间跳过 turnover 或其他状态；
4. 不允许跨换月；
5. long / short 规则严格镜像；
6. 不设置 strength、百分比衰减、ATR 距离等新阈值。

这些 cohort 是 retrospective diagnostic 名称，不是市场事实标签或交易信号。

## 7. 复用现有 Outcome 研究

Sequence cohort 直接复用现有 `MainForceMirrorV2ResearchService` 的 outcome machinery：

```text
forward horizons = 1 / 3 / 5 / 10 根 60m Bar
same physical contract only
```

继续输出：

```text
sample_count
median_directional_return
median_reversal_return
hit_rate
median_mfe
median_mae
```

继续按：

```text
product
year
state/cohort
```

组织；pooled 只能作为摘要，不得覆盖单品种/年份异质性。

不新增 Sharpe、PnL、收益曲线、交易成本或 backtest engine。

## 8. Forensic 模式：复用现有 CLI

不新增 CLI command，只给现有命令增加一个布尔开关：

```text
guiyi research main-force-mirror-v2 ... --forensic
```

默认不带 `--forensic` 时，保持当前 compact summary，仅增加 sequence cohort summary。

带 `--forensic` 时，额外返回请求窗口内逐 Bar：

```text
bar_end
trading_day
physical_contract
pressure_state
instant_pressure
accumulated_pressure
range_position
caution
long_caution_score
short_caution_score
caution_reason_codes
member_status
member_trade_date
member_direction
member_strength
member_relation_to_accumulated
sequence_fact
```

Forensic 只是 stdout JSON；不保存 report、不写 DB/Canonical/Redis。

JM 2026-03 高位案例通过该模式人工解释，不允许在代码中硬编码日期、JM 或预期标签。

## 9. Member：当前只复用，不扩展

为了遵守“能复用就不建新模块”，本轮**不新增**：

```text
member_bias_3d
member_bias_5d
member_bias_turn
新的 member history reducer
新的 snapshot cache/archive
```

Sequence fact 只引用当前已经计算好的：

```text
member.relation_to_accumulated
```

Member unavailable 不阻断 pressure-only sequence cohort。

真实 `jm/ag/cu/m` member snapshot 若需要补建，只使用仓库已有 `MemberRankSnapshotBuilder`，属于独立受控外部数据操作；不在本轮代码实现里修改 builder/repository。

## 10. 60m-only 因果与 Prefix Invariance

Sequence fact 必须满足：

```text
facts(points[0:t])[-1]
==
facts(points[0:N])[t-1]
```

对所有公开 sequence 字段成立。

禁止：

- 使用未来 1/3/5/10 根结果创建或修改 sequence fact；
- 因为后续大跌，把前面某根重新命名为“出货”；
- 在完整历史输入时得到与 prefix 重算不同的当前 sequence；
- 使用低周期辅助确认。

Forward outcome 只用于 retrospective evaluation，与 sequence fact 生成完全单向隔离。

## 11. JM Golden Behavior Case 的正确定位

JM 2026-03 案例只回答：

1. 强拉升 Bar 当时为什么是 `long_build`；
2. 后续最早哪根出现 `long_liquidation`；
3. 后续最早哪根出现 `short_build`；
4. accumulated pressure 何时开始下降、何时反号；
5. exact 2-step/3-step sequence 在什么时点形成；
6. 当时已有 member relation 是什么（若 snapshot 可用）。

不得要求：

```text
“顶部必须标出货”
“必须在最高点预警”
“为了匹配截图调参数”
```

## 12. 全历史验证顺序

### Stage A — Pressure-only

不需要任何新数据写入，直接使用本地 Historical Canonical：

```text
active 60
× actual_dominant
× 60m
× existing V2
× sequence cohorts
```

先看：

```text
count
product/year stability
long/short symmetry
形成时间
1/3/5/10-bar outcome
```

### Stage B — Member-enriched（可选 Gate）

仅在用户明确授权真实 member snapshot build 后，对已有 admitted：

```text
jm / ag / cu / m
```

叠加 existing `member_relation_to_accumulated` 分层。

没有 snapshot 时 Stage A 仍完整成立，不允许为了 member 阻塞 pressure-only 研究。

## 13. Go / Stop Gate

完成 Stage A 后必须先做价值判断，不能自动进入 Phase 实现。

只有同时满足以下条件，才允许新开独立设计冻结 Phase：

1. exact sequence 在多个品种、多个年份重复出现，而不是只解释 JM 单例；
2. sequence 的形成时点明显早于主要后验走势结束，具有人工观察价值；
3. long / short 镜像没有明显结构性失衡；
4. 输出能实质减少逐 Bar 人工拼接，或明显增强复盘证据；
5. 规则仍能保持少量、可解释、可删除。

任一核心条件不满足：

```text
STOP
不实现 CLIMAX / UNWIND / TAKEOVER
不改 Web
不接 Alert
```

Member 只作为附加解释，不能成为是否进入 Phase 的必要前置。

## 14. 明确延迟到下一任务

即使 Stage A/B 看起来有效，本计划也**不实现**：

```text
NORMAL / CLIMAX / UNWIND / TAKEOVER active reducer
Phase parameters/policy/hash
Web Phase panel/marker
API Phase schema
Live/Alert/PushPlus
prospective OOS Phase candidate
```

这些必须在 evidence review 后重新回答五个问题，并形成新的 Design/Plan。

## 15. 允许修改 / 禁止修改

本轮允许修改：

```text
services/quant-api/app/market_data/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md
```

必要时可更新本 Design、Plan、Task Contract。

本轮禁止修改：

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py
services/quant-api/app/market_data/main_force_mirror_v2_service.py
services/quant-api/app/market_data/member_rank_snapshot.py
services/quant-api/app/market_data/member_rank_snapshot_builder.py
services/quant-api/app/api/*
apps/quant-web/*
Alert / Execution Review / Runtime
Data Foundation / Catalog / Canonical / MainContractMap
STATUS.md
main / tag / release
```

如果实现发现必须突破上述边界，停止并重新设计，不得顺手扩范围。

## 16. 验收

代码验收：

1. 现有 V2 Kernel / API / Web 行为零变化；
2. `--frequency` 仍只有 `60m`；
3. default research CLI 保持 read-only；
4. sequence facts 不跨 physical contract / invalid gap；
5. exact 2-step/3-step cohorts long/short 对称；
6. prefix invariance 通过；
7. sequence outcome 不跨 physical contract；
8. `--forensic` 只增加 stdout 明细，不写任何数据；
9. member unavailable 不阻断 pressure-only；
10. 没有 Phase 正式标签、阈值或 active semantic drift；
11. 相关 V2 tests、research CLI tests、Ruff、Mypy、secret scan、`git diff --check` 通过。

研究验收与代码验收分离。测试通过只表示 research capability 正确，不表示 Phase 值得产品化。

## 17. 最终边界

当前唯一允许的结论是：

> 已获得一个最小、60m-only、causal、可删除的 V2 sequence forensic/research 能力，用现有 V2 压力事实检验“状态记忆是否有长期价值”。

不得声明：

```text
已经识别真实主力出货
Phase 有效
策略有效
可交易
可进入 Alert/Runtime
```

`auto_order=false` 始终成立。
