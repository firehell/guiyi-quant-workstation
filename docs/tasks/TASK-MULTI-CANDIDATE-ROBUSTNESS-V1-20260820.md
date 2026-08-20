# TASK-MULTI-CANDIDATE-ROBUSTNESS-V1-20260820 — 执行合同

> 状态：PLANNED_ONLY
>
> Design：`docs/superpowers/specs/2026-08-20-multi-candidate-robustness-v1-design.md`
>
> Plan：`docs/superpowers/plans/2026-08-20-multi-candidate-robustness-v1.md`
>
> 本合同约束后续 Codex 实施与 Review。当前 docs 提交不实现代码、不运行真实 evidence、不修改 main/tag/Runtime/Alert/DB/Canonical，也不形成策略晋升授权。

## 1. 任务目标

建立：

```text
frozen SuBing Candidate
+
frozen N Candidate
        ↓
existing Candidate Validation + source research
        ↓
Temporal dossier
+
active60 cross-symbol dossier
+
jm event relationship dossier
        ↓
versioned retrospective robustness evidence
```

全程保持：

```text
research_only=true
readonly=true
auto_order=false
```

## 2. 必读事实源

每个 Task 开始前依次读取：

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
docs/superpowers/specs/2026-08-20-multi-candidate-robustness-v1-design.md
docs/superpowers/plans/2026-08-20-multi-candidate-robustness-v1.md
本文件
任务相关 current implementation/tests
```

若 active canonical 已与本任务冲突：

```text
BLOCKED_CANONICAL_DRIFT
```

停止，不自行改写计划。

## 3. Exact Identity Freeze

只允许：

```text
Candidate A
candidate_id    = subing_lifecycle_v2_candidate_v1
policy_id       = subing_lifecycle_v2_research_v1
formula_version = subing_lifecycle_v2
protocol_id     = candidate_validation_v1

Candidate B
candidate_id    = n_structure_5m_candidate_v1
policy_id       = n_structure_5m_v1
formula_version = n_structure_v1
protocol_id     = n_structure_validation_v1
```

Robustness：

```text
protocol_id = multi_candidate_robustness_v1
frozen_at   = 2026-08-20T21:33:00+08:00
anchor      = jm
common      = 2023-01-01..2026-08-18
```

任何现有 Candidate/Policy/Formula/Protocol 内容变化：

```text
FORMULA_OR_CANDIDATE_DRIFT
→ stop
→ 新开独立 Candidate task
```

不得在本任务中“顺便修公式”。

## 4. Frozen 60 Product Identity

exact 顺序：

```text
a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i
j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps
pt px rb rm rs ru sa sc sf sh si sm sn sr ss ta ur v y zn
```

总数精确为：

```text
60
```

Cross-symbol matrix 精确：

```text
2 candidates × 60 products = 120 retained cells
```

禁止：

```text
删除 unavailable symbol
删除 zero-event symbol
按样本数筛掉某品种
换成运行时新的 active 列表
只保留“表现好”的品种
```

当前 active set 与 frozen 60 drift 时 fail-closed：

```text
MULTI_CANDIDATE_ACTIVE_UNIVERSE_DRIFT
```

## 5. Temporal / OOS Freeze

Temporal baseline 请求只能是：

```text
SuBing:
through = 2026-08-19
prospective first = 2026-08-20

N:
through = 2026-08-20
2026-08-20 = embargo
prospective first = 2026-08-21
```

共同历史比较只能是：

```text
2023-01-01..2026-08-18
```

本阶段：

```text
creates_new_prospective_protocol = false
backfills_oos = false
```

禁止因为现实时间已经推进而把新 trading day 混入首份 robustness baseline artifact。

## 6. Event Semantics Freeze

### SuBing

唯一 relationship anchor：

```text
SubingLifecycleTransition.to_stage == ENTRY_CONFIRMED
```

### N

唯一 relationship anchor：

```text
CompletedNPattern.completed_at
```

### Common event identity

必须携带：

```text
candidate_id
source_kind
source_event_kind
source_event_id
symbol
physical contract
segment_start_trading_day
observed_at
trading_day
segment_bar_index
direction
```

不得用新计算替代 source event identity。

## 7. Relationship Matching Freeze

Relationship 只在 `jm / 2023-01-01..2026-08-18`。

Match eligibility：

```text
same symbol
AND same physical contract
AND same segment_start_trading_day
```

signed distance：

```text
target_bar_index - source_bar_index
```

nearest target：

```text
minimum abs(distance)
then smaller target_bar_index
then lexicographically smaller target_event_id
```

即 equal-distance tie 选择 earlier target。

同一个 target 可以成为多个 source 的 nearest target；本 V1 **不是 one-to-one assignment**。

### 7.1 Exact counts

```text
exact_same_direction_count
exact_opposite_direction_count
```

是 **event-pair count**。

如果同一 boundary：

```text
2 source LONG × 2 target LONG
→ exact_same_direction_count += 4
```

### 7.2 Proximity counts

```text
within_3_same_direction_source_count
within_5_same_direction_source_count
within_8_same_direction_source_count
```

是 **source-event coverage count**。

同一个 source 在每个 bucket 最多计 1 次。

必须满足：

```text
within_3 <= within_5 <= within_8 <= source_event_count
```

### 7.3 双向

必须同时有：

```text
SuBing → N
N → SuBing
```

不能用其中一个推导另一个。

## 8. Metric Compatibility Freeze

Common 只投影：

```text
sample_count
median_directional_return_bps
median_mfe_bps
median_mae_bps
```

但必须保留：

```text
SuBing = same_trading_day_only
N      = same_rank1_segment
```

以及：

```text
EVALUABLE_UNIT_DIFFERS
HORIZON_SEMANTICS_DIFFERS
```

禁止：

```text
SuBing return - N return
MFE ratio
统一 horizon 后重新计算
通过某一 common metric 自动判 winner
```

SuBing EMA21 failure 继续留在 SuBing source report，不进入 common projection。

## 9. Parameter / Candidate Version Freeze

本阶段：

```text
parameter_perturbation=false
```

禁止：

```text
threshold sweep
random search
grid search
optimizer
自动生成 Candidate A/B/C
无 lineage 参数实验
```

如果想研究参数变化，先新建 exact Policy/Candidate，再独立 Candidate Validation。

## 10. Decision / Promotion Prohibition

任何输出、代码模型、JSON key、文档结论不得出现策略决策语义：

```text
KEEP
DROP
PROMOTE
RANK
SCORE
WINNER
BETTER_CANDIDATE
PASS_STRATEGY
GOOD_STRATEGY
BAD_STRATEGY
PROFITABILITY
EXPECTED_PROFIT
```

允许：

```text
counts
rates
distributions
sample availability
signed distance
historical median return/MFE/MAE
quality/data flags
```

“历史 median return”是 outcome 描述，不等于盈利能力判断。

## 11. Historical Boundary

唯一 source：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
→ existing SuBing/N reducers
```

禁止：

```text
direct Parquet read
direct RQData read
Redis Live read
second rank1 resolver
cross-frequency fallback
manual contract stitching
```

## 12. Task Gate Table

| Task | 内容 | Lane | Model | Review Gate |
| --- | --- | --- | --- | --- |
| 1 | exact protocol + contracts | Lane 2 | Sol high | focused tests/self-review |
| 2 | causal source event seams | Lane 1 | Sol high | source parity + temporal review |
| 3 | event relationship engine | Lane 1 | Sol high | segment/leakage review |
| 4 | active60 cross-symbol | Lane 1 | Sol high | no-silent-drop/source identity |
| 5 | anchor temporal dossier | Lane 1 | Sol high | exact baseline/OOS review |
| 6 | orchestration + CLI | Lane 2 | Terra medium | readonly/composition tests |
| 7 | cumulative verification | Lane 1 Review | Sol high | Critical=0 / Important=0 |
| 8 | real evidence | Lane 1 | Sol high | Evidence Critical=0 / Important=0 |

## 13. Review Severity

```text
Critical
= future leak / OOS backfill / cross-contract or cross-segment relationship /
  modifying exact Candidate formula under same identity /
  automatic rank or promotion /
  production boundary violation

Important
= source event semantic mismatch /
  aggregate source regression /
  silent symbol omission /
  zero-event and unavailable conflation /
  horizon semantics lost /
  baseline request-through drift /
  nondeterministic ordering/result /
  duplicated formula or rank1 resolver

Minor
= naming/format/readability issue with no behavioral impact
```

Tasks 7/8 Gate：

```text
Critical = 0
Important = 0
```

## 14. Worktree / Integration

每个 Task 1–6：

```text
latest develop
→ independent task worktree/branch
→ TDD
→ focused validation
→ required review
→ develop
→ origin ancestry readback
→ cleanup
```

Task 7：clean develop independent Review。

Task 8：独立 evidence worktree/branch。

普通 task 可按仓库正式流程合入 `develop`；不得因此执行：

```text
main merge
tag/release
Runtime switch/promotion
Alert Scope write
notification
DB/Canonical/Redis write
order
```

## 15. Verification Freeze

至少运行：

```text
new robustness focused tests
current N full-chain regression
current SuBing zero-regression
current Candidate Validation regression
Ruff
Mypy
secret_scan
git diff --check
```

真实 evidence 前必须证明两份 tracked anchor baseline 仍可由 exact historical command 复算一致。

Evidence artifact 必须 deterministic rerun byte-identical。

## 16. Evidence Freeze

唯一首份 artifact：

```text
reports/research/candidate_robustness/
  multi_candidate_robustness_v1/
  anchor-jm-active60-retrospective-freeze-2026-08-20.json
```

Artifact identity：

```text
protocol = multi_candidate_robustness_v1
anchor = jm
common window = 2023-01-01..2026-08-18
candidates = exact two frozen identities
cross-symbol products = exact 60
cross-symbol cells = 120
relationships = 2 directions
```

该 artifact 名称中的 `freeze-2026-08-20` 是 Robustness Protocol 设计冻结日期，不表示 prospective OOS 已完成。

## 17. Global Prohibitions

整个阶段禁止：

```text
修改 Data Foundation / DatasetKey / 八表 Catalog / Canonical 语义
修改 SuBing/N formulas/policies/manifests/protocols
恢复旧 Strategy/Signal/Review/backtest platform
创建 Strategy Plugin/Registry
参数优化
Web/API dashboard
DB/Redis persistence
worker/queue/scheduler
Alert Rule/Scope
真实通知
Execution Review consumer
order/account/position/cost/PnL/equity
main/tag/release
Runtime promotion/switch
自动 Candidate promotion
```

## 18. Final Allowed Conclusion

Phase 完成最多只能写：

```text
Multi-Candidate Research & Robustness V1 已形成可复算的 retrospective robustness dossier；
已描述两个 frozen Candidate 的 anchor temporal stability、active60 cross-symbol distribution
与 jm historical event relationship；prospective OOS 仍由各自 exact Candidate Protocol 独立累积。
```

不得写：

```text
SuBing 比 N 好
N 比 SuBing 好
某 Candidate 有效或盈利
应该 KEEP/DROP/PROMOTE
可发第三条 Alert
可发布 main/tag
可 Runtime promotion
```
