# TASK-MFM-V2-PHASE-MEMORY-RESEARCH-20260821 — 执行合同

> 状态：PLANNED_ONLY
>
> Design：`docs/superpowers/specs/2026-08-21-main-force-mirror-v2-phase-memory-design.md`
>
> Plan：`docs/superpowers/plans/2026-08-21-main-force-mirror-v2-phase-memory-research.md`
>
> 本合同只冻结 60m-only sequence forensic/research 的实施边界。它不实现代码、不执行真实 member snapshot、不调用 RQData 写入、不修改 Web/API/Kernel/Alert/Runtime，也不批准 Phase、策略或候选晋升。

## 1. 五问后的最终结论

开始编码前按项目长期维护原则得到以下结论：

```text
1. 一年内是否会用：有条件会；逐 Bar 状态拼接是当前真实使用痛点。
2. 四项价值：至少满足减少盯盘、提高解释/执行一致性、增加复盘证据。
3. 能否复用：能；完全复用现有 MDS + V2 Service + V2 Research + existing CLI。
4. 真实复杂度：只有 60m causal sequence memory；Phase、低周期、member history、Web/Alert 均延迟。
5. 半年后可维护：只改现有 research/CLI/tests，无持久状态；可直接删除回退。
```

因此：

```text
允许实现：最小 sequence research capability
禁止实现：正式 Phase 模型及其所有产品化扩展
```

## 2. Mandatory fact sources

每次 Plan / Implementation / Review / Evidence 必须先读：

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
Design
Plan
本合同
current implementation/tests
TESTING.md
```

冲突处理：

```text
active canonical / current code 与本合同冲突
→ BLOCKED_CANONICAL_DRIFT
→ 不猜测，不自行“兼容”旧方案
```

## 3. Exact scope

唯一目标：

```text
existing main_force_mirror_v2 60m confirmed points
→ causal adjacent sequence facts
→ exact 2-step / 3-step transition cohorts
→ separate 1/3/5/10-bar retrospective warning summaries
→ optional stdout-only --forensic
```

不产生：

```text
NORMAL / CLIMAX / UNWIND / TAKEOVER
出货/吸筹正式标签
新参数、新 policy、新 hash
新 indicator identity
新 API/Web/module/storage
member 3d/5d/turn
member-sequence full-history cohorts
15m/5m/1m
Live/Alert/notification
strategy/backtest/PnL/order
```

## 4. Exact frequency / market identity

```text
frequency   = 60m only
series_kind = actual_dominant | contract
source      = existing Historical confirmed V2 points
continuous  = forbidden
live        = forbidden
```

任何低周期输入、确认、投影或回退 = `LOWER_TIMEFRAME_SCOPE_VIOLATION`。

## 5. Frozen V2 semantics

以下不得改变：

```text
main_force_mirror_v2
futures-member-research-v2
main_force_mirror_observation_v2
instant pressure formula
long_build / short_build / short_cover / long_liquidation / turnover
EMA5 accumulated pressure
caution >=70 / conflict / latch
member direction / strength / relation
parameters_hash
```

禁止修改：

`packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`。

## 6. Exact sequence fact contract

Task 1 必须定义：

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceFact:
    bar_end: datetime
    trading_day: date
    physical_contract: str
    previous_state: str | None
    current_state: str
    state_transition: str | None
    previous_instant_pressure: float | None
    current_instant_pressure: float
    previous_accumulated_pressure: float | None
    current_accumulated_pressure: float | None
    accumulated_delta: float | None
    accumulated_sign_flip: Literal[
        "positive_to_negative",
        "negative_to_positive",
    ] | None
    state_sequence_3: tuple[str, ...]
    state_sequence_5: tuple[str, ...]
    range_position: float | None
    caution: str | None
    member_relation_to_accumulated: str
```

公开 builder：

```python
def build_main_force_mirror_v2_sequence_facts(
    points: tuple[MainForceMirrorV2Point, ...],
) -> tuple[MainForceMirrorV2SequenceFact | None, ...]: ...
```

### Reset

以下任一发生立即断开 sequence：

```text
pressure_ready=false
pressure_state=None
physical_contract=None
instant_pressure=None
physical_contract change
```

下一 ready Bar `previous_state=None`，不得跨 gap/roll。

### Prefix invariance

必须逐 prefix：

```text
build(points[:t])[-1] == build(points)[t-1]
```

## 7. Exact sequence cohort contract

固定且只允许：

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

不允许 fuzzy match、跳过 turnover、N-bar 搜索、strength threshold 或“最近出现过”式回溯匹配。

### Evaluation direction

Sequence 是 warning/reversal diagnostic，方向锚定原 build side：

```text
long_build...       original_side=+1
short_build...      original_side=-1
positive_to_negative original_side=+1
negative_to_positive original_side=-1
```

主要阅读：`median_reversal_return` 和 reversal hit rate。

不得把 direct takeover cohort 自动称为新方向交易信号。

## 8. Existing research isolation

Sequence 必须与当前 V2 `COHORTS` 分开。

新增：

```text
sequence_pooled
sequence_yearly
```

禁止将 sequence 名称加入现有：

```text
COHORTS
top_bottom_spreads
member sensitivity
```

现有结果语义必须 zero-regression。

## 9. Forensic contract

现有命令只增加：

```text
--forensic
```

不新增 command。

默认：

```text
forensic=false
compact summary
```

开启：

```text
stdout JSON 额外逐 Bar existing V2 point + sequence_fact
```

禁止文件写入、DB/Canonical/Redis mutation、provider request。

JM 2026-03 case 不是硬编码测试目标。

## 10. Member contract

本轮 member 只允许读取 existing point 已有：

```text
member.relation_to_accumulated
```

不增加任何新 member formula。

真实 member snapshot 仍是 `STATUS.md` 所述 pending 状态；本任务不执行、不修改 builder、不把 snapshot 作为 Stage A 前置条件。

## 11. Allowed / forbidden files

### Allowed

```text
services/quant-api/app/market_data/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md
Design / Plan / 本合同
```

### Forbidden

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

需要 forbidden path = `BLOCKED_SCOPE_EXPANSION`。

## 12. Codex 调度矩阵

| Plan Task | Deliverable | Lane | Model | Reasoning | Session | Plan | Workspace | Human Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | causal sequence fact + reset/prefix tests | Lane 3 | Sol | 高 | Implementation 主会话 | Plan-only → 批准后继续当前会话实现 | task worktree from `develop` | Plan 批准；最终独立 Review |
| 2 | separate sequence summaries + `--forensic` + TESTING | Lane 3 | Sol | 高 | 继续 Task 1 同一实现会话/branch | approved plan execute | 同一 task worktree | 最终独立 Review |
| 3 | cumulative causal/scope Review | Lane 3 | Sol | 高 | 新开独立 Review 会话 | Direct review-only | detached/clean review worktree at implementation head | C0/I0；发现问题阻塞 |
| 4 | JM forensic + active60 Stage A | Lane 1 | Sol | 高 | 新开 evidence 会话 | Plan-then-execute | evidence worktree from accepted `develop` | Go/Stop 人工判断 |

Task 1+2 是一个独立可集成功能，因此共用**一个 Codex implementation 会话 + 一个 task branch/worktree**，避免为机械步骤制造额外分支。Task 3 强制独立会话。

## 13. Codex 调度建议 — Implementation（Plan Tasks 1+2）

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话；Plan 批准后继续当前会话实现
- Plan：Plan-only；人工批准后执行 Design/Plan
- 工作区：从最新 `develop` 创建 `research/main-force-v2-sequence-memory` task branch/worktree
- 人工 Gate：Plan 批准 / 独立 Review

Worktree：

```text
from: develop
branch: research/main-force-v2-sequence-memory
integrate to: develop
```

规则：

```text
不得修改 main/runtime worktree
不得发布 main/tag
不得 Runtime promotion
不得真实 member snapshot/RQData 写入
独立 Review C0/I0 后，用户批准才允许 branch → develop
确认进入 develop 后清理 task worktree/branch
PR 非强制；如创建，仅用于 review，不形成额外业务 Gate
```

### 可直接复制的 Codex Prompt — Implementation

```text
请先阅读：
`STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`TESTING.md`，
以及：
`docs/superpowers/specs/2026-08-21-main-force-mirror-v2-phase-memory-design.md`
`docs/superpowers/plans/2026-08-21-main-force-mirror-v2-phase-memory-research.md`
`docs/tasks/TASK-MFM-V2-PHASE-MEMORY-RESEARCH-20260821.md`。

本任务为 Lane 3，Sol，高推理。
先 Plan-only，不要编码。先检查最新 develop、相关实现和测试，给出与你准备执行的 Plan Task 1+2 对齐的最小实施计划；不得扩范围。等我批准 Plan 后再继续当前会话实现。

目标：
只在现有 MainForceMirrorV2ResearchService / existing research CLI 上增加 60m-only causal sequence facts、exact transition summaries 和 stdout-only `--forensic`。

必须保持：
- `main_force_mirror_v2` Kernel、公式、五状态、EMA5、caution、member、parameters_hash 不变；
- frequency 仍只支持 60m；
- sequence 不跨 physical contract / unready gap；
- prefix invariance；
- sequence summaries 与现有 COHORTS/top_bottom_spreads/member sensitivity 分离；
- member unavailable 不阻断 pressure-only；
- no Phase labels / thresholds / policy / Web / API / Alert / Runtime / storage。

允许修改仅为任务合同 Allowed files。
Forbidden path 或发现需要低周期/member history/new storage/new API 时立即停止，报告 `BLOCKED_SCOPE_EXPANSION`。

按 TDD 执行 Plan Task 1+2：先失败测试，再最小实现，再定向回归、完整 V2 regression、Ruff、Mypy、secret scan、git diff --check。

不得执行真实 RQData/member snapshot，不得发布 main/tag，不得切 Runtime。

实现完成后不要合并 develop；输出：
修改摘要、测试结果、branch/head、diff 范围、风险、未完成项，并等待独立 Review。
```

## 14. Codex 调度建议 — Independent Review（Plan Task 3）

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开独立 Review 会话
- Plan：Direct / review-only
- 工作区：clean detached review worktree at implementation head
- 人工 Gate：独立 Review C0/I0

### 可直接复制的 Codex Prompt — Review

```text
这是独立 Review，不实现新功能，不扩大范围。

先读：STATUS.md、AGENTS.md、docs/DEVELOPMENT.md、PROJECT_SOURCE.md、DECISIONS.md、TESTING.md，
以及 Main Force V2 Phase Memory Design、Implementation Plan、Task Contract。

Review implementation head 相对其 develop base 的完整 diff。
重点检查：
1. changed paths 是否严格在 Allowed files；
2. 是否任何形式读取/使用 15m/5m/1m；
3. sequence 是否只依赖当前/历史 confirmed 60m V2 points；
4. invalid/unready gap、physical contract switch 是否 reset；
5. prefix invariance 是否真实覆盖；
6. 2-step/3-step cohort 是否 exact adjacent、long/short 镜像；
7. sequence 是否意外进入现有 COHORTS/top_bottom_spreads/member sensitivity；
8. 是否修改 Kernel/公式/caution/member/parameters_hash；
9. `--forensic` 是否 stdout-only、无写入/联网；
10. 是否偷偷加入 Phase label/threshold/policy/new module/storage/API/Web/Alert/Runtime。

重新运行任务合同要求的定向测试、V2 regression、Ruff、Mypy、secret scan、git diff --check。

只输出：
- C0/I0 — 允许集成 develop；或
- BLOCKED — 按严重度列出 finding、文件/行、为什么违反 Design/Contract、最小修正方向。

Review worktree 不修改代码。发现问题必须回到独立 fix branch。
```

## 15. Codex 调度建议 — Stage A Evidence（Plan Task 4）

- 任务车道：Lane 1
- 执行入口：Codex App + CLI automation
- 推荐模型：Sol
- 推理强度：高
- 会话：新开 evidence 会话
- Plan：Plan-then-execute
- 工作区：从已接受的最新 `develop` 创建临时 evidence worktree；不提交代码
- 人工 Gate：Go / Stop 结论

Evidence 只读本地 Canonical 和 existing V2 query path；不调用真实 member snapshot builder/RQData mutation。

### 可直接复制的 Codex Prompt — Evidence

```text
请先读 STATUS.md、AGENTS.md、docs/DEVELOPMENT.md、PROJECT_SOURCE.md、DECISIONS.md、TESTING.md，
以及 Main Force V2 Phase Memory Design/Plan/Task Contract。

本任务为 Lane 1 research evidence，Sol，高推理，60m-only。
不得修改源码、不得生成新 Phase 规则、不得调参。

先确认当前 develop 已包含通过独立 Review 的 sequence research capability。
然后严格执行 Plan Task 4：

A. JM forensic：
`jm / actual_dominant / 60m / 2026-03-20..2026-03-27 / --forensic`
只记录已有 causal facts：long_build、long_liquidation、short_build、accumulated 变化、exact sequence、已有 member relation（若 unavailable 就明确 unavailable）。不要写“出货/CLIMAX/UNWIND/TAKEOVER”。

B. active60 Stage A：
对 `data/universe/active_products.txt` 全部 active product 运行 `actual_dominant + 60m + 2023-01-01..2026-08-20` existing research command，输出只放 `/tmp/guiyi-mfm-phase-memory-stage-a-20260821/`。
任一真实失败立即停止并报告，不跳过、不补零、不缩小 universe。

C. 汇总：
按 exact sequence cohort 检查 product/year sample、long/short mirror coverage、1/3/5/10 reversal outcome；pooled 只能作摘要，不自动 ranking。

最终按 Design 五个 Go 条件输出：
- `GO_TO_NEW_PHASE_DESIGN`；或
- `STOP_PHASE_DESIGN`。

无论结论如何，本任务都不得：
真实 member snapshot/RQData 写入、Git-tracked evidence、Web/API/Alert/Runtime/main/tag/release、Phase 实现或订单。
```

## 16. Verification boundary

Implementation 必须至少通过：

```text
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
完整 TESTING.md 主力照妖镜 V2 pytest group
Ruff
Mypy
secret_scan.py --json
git diff --check
```

不要求 Web tests，因为本任务禁止修改 Web；如果实现导致 Web/API 测试需要修改，视为 scope drift。

## 17. Integration / cleanup

Implementation：

```text
latest develop
→ research/main-force-v2-sequence-memory task worktree
→ Plan approved
→ TDD implementation
→ independent Review C0/I0
→ 用户批准
→ integrate develop
→ ancestry/readback
→ delete task worktree + merged branch
```

Review：完成后删除 detached review worktree。

Evidence：完成后删除 evidence worktree 和 `/tmp/guiyi-mfm-phase-memory-stage-a-20260821/`；不产生 branch merge。

全流程不得触及 `main`、tag 或 Runtime。

## 18. Final allowed conclusions

实现 Review 后：

```text
允许集成 develop
```

或：

```text
要求修正后再集成
```

Stage A 后只能：

```text
GO_TO_NEW_PHASE_DESIGN
```

或：

```text
STOP_PHASE_DESIGN
```

不得把任何结果写成：

```text
允许进入 release candidate
允许发布 main/tag
允许 Runtime promotion
策略有效/盈利/可交易
```
