# TASK-N-STRUCTURE-V1-20260820 — N 字 Structural Domain V1 执行合同

> 状态：PLANNED_ONLY
>
> Design：`docs/superpowers/specs/2026-08-20-n-structure-v1-design.md`
>
> Plan：`docs/superpowers/plans/2026-08-20-n-structure-v1.md`
>
> 本合同只定义后续 Codex 执行边界；当前 docs 提交不授权实现、release、Runtime、Alert、数据/DB 写入、通知或订单。
>
> 本合同是 Lane 3 实施的规范性补充：当 Design / Plan 对某个边界保持沉默、而本合同给出更精确的执行规则时，执行与 Review 以本合同的精确边界为准；若出现真正语义冲突则 `BLOCKED_CANONICAL_DRIFT`，不得自行裁决。

## 1. 目标

建立：

```text
5m Historical actual-dominant
→ causal Swing(epoch)
→ immutable Completed N / break / band facts
→ BULL/BEAR/RANGE Structure
→ Historical N research
→ N Candidate Validation
→ jm retrospective/rolling evidence
```

最终仍保持：

```text
research_only=true
auto_order=false
```

## 2. 必读事实源

每个 Task 开始前按顺序读取：

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
docs/superpowers/specs/2026-08-20-n-structure-v1-design.md
docs/superpowers/plans/2026-08-20-n-structure-v1.md
本文件
任务相关实现与测试
```

若 active canonical 与本合同冲突：`BLOCKED_CANONICAL_DRIFT`，停止。

## 3. 全局禁止

任何 Task 均不得：

```text
修改 Data Foundation / DatasetKey / 八表 Catalog / Canonical 语义
修改 SuBing V1/V2 公式或 Alert Rule/Scope
恢复旧 Strategy/Signal/Review/backtest 平台
建立 Strategy Plugin/Registry
直接读取 Parquet/RQData/Redis 作为 N Historical source
引入 Live N / Web N / HTTP N API
引入强中弱数值阈值、ATR/ZigZag 参数优化
递归 N 分型 / 多周期 N
写 production DB/Canonical/Redis
发送真实通知
创建第三条 production Alert Rule
创建订单、账户、持仓、PnL/equity 路径
发布 main/tag
Runtime promotion/switch/reload
自动 KEEP/DROP/PROMOTE Candidate
```

## 4. Task Gate 表

| Task | 内容 | Lane | 实施前 Gate | 完成 Gate |
| --- | --- | --- | --- | --- |
| 1 | Exact N Policy | Lane 3 | 用户批准 Lane 3 Plan | Policy exact + Review C0/I0 |
| 2 | Swing epoch reducer | Lane 3 | 用户批准 Lane 3 Plan | prefix/epoch + Review C0/I0 |
| 3 | N completion/break/band | Lane 3 | 用户批准 Lane 3 Plan | completion/events + Review C0/I0 |
| 4 | Structure + defense | Lane 3 | 用户批准 Lane 3 Plan | structure causality + Review C0/I0 |
| 5 | Shared segment loader | Lane 2 | Task 4 in develop | SuBing zero regression |
| 6 | N research + price outcome | Lane 1 | Task 5 in develop | temporal/leakage Review |
| 7 | Shared candidate schedule | Lane 2 | Task 6 in develop | SuBing Candidate parity |
| 8 | N Candidate Validation | Lane 1 | Task 7 in develop | embargo/OOS Review |
| 9 | cumulative verification | Lane 3 Review | Tasks 1-8 in develop | Critical=0 / Important=0 |
| 10 | jm evidence | Lane 1 | Task 9 accepted | Evidence Critical=0 / Important=0 |

## 5. Lane 3 公式冻结

Tasks 1～4 不得自行做新的业务选择。必须精确实现 Spec 与本合同：

```text
5m only
previous-bar strict breach
equal not breach
tie keep first
inside no reversal
outside → new swing_epoch
N never crosses epoch
first strict N1 breach → completion
same-boundary completion + N break → record both boundary facts, no intrabar-order claim
completed N immutable
N2 break != reversal confirmed
N1-N2 exact span only
no machine STRONG/MEDIUM/WEAK
Structure >=2 completed N in same evidence epoch
HH+HL bull / LH+LL bear / otherwise range
strict defense break → range, no auto reverse
same-boundary new Structure/new defense + defense breach → record establishment/advance fact first, then defense break → RANGE at the same bar_end; no intrabar-order claim
```

### 5.1 Same-boundary Structure defense 规范性澄清

这是 Planning Review 的最终 Important 修复。

当某根 completed 5m boundary **首次建立 BULL/BEAR Structure，或推进其 trailing defense**，而同一根 K 线的已知 high/low 已经严格越过这个刚刚建立/推进的 defense 时：

```text
BULL:
new_defense = qualifying LOW
current.low < new_defense.price

BEAR:
new_defense = qualifying HIGH
current.high > new_defense.price
```

必须在同一个 `bar_end` 记录：

```text
1. Structure establishment / defense advancement fact
2. BULL_STRUCTURE_BROKEN 或 BEAR_STRUCTURE_BROKEN
3. final Structure state = RANGE
```

固定事实顺序为“建立/推进 → break → RANGE”，但**不得声称这就是 intrabar 真实先后顺序**；它只表示截至该 completed boundary，建立/推进证据与 strict defense breach 两组价格事实同时可知。

禁止：

```text
把刚刚已被同 boundary 严格越过的 defense 保留为 active 到下一根 K
因为无法知道 intrabar 顺序而丢弃已知 strict level breach
在该 boundary 自动反手建立相反方向 Structure
```

Task 4 必须有两个独立 RED→GREEN 用例：

```text
same-boundary initial establishment + defense break
same-boundary trailing-defense advancement + defense break
```

Task 9 的 prefix matrix 必须覆盖这两个场景。

需要改变本节任意语义：输出 `FORMULA_DRIFT_REQUIRES_NEW_TASK`，停止当前 Task。

## 6. Temporal / OOS 冻结

```text
candidate_id = n_structure_5m_candidate_v1
policy_id = n_structure_5m_v1
formula_version = n_structure_v1
protocol_id = n_structure_validation_v1
candidate_frozen_at = 2026-08-20T00:22:00+08:00
retrospective = 2023-01-01..2026-08-19
embargo = trading_day 2026-08-20
prospective OOS first = trading_day 2026-08-21
rolling = 12m reference + 3m test + 3m step; 10 folds
```

任何把 2026-08-20 计入 retrospective/prospective 的实现都是 Critical。

## 7. Worktree / integration

每个可独立集成 Task：

```text
latest develop
→ new task branch/worktree
→ TDD + verification
→ required Review
→ develop
→ ancestry readback
→ cleanup
```

Tasks 1～4 必须 PR to develop 并保留独立 Review。Tasks 5～8 可以按普通 develop 流程，但不得绕过本合同测试。Task 10 使用独立 evidence branch。

不触及 main/tag/Runtime。

## 8. Review severity

```text
Critical
= future leak / repaint / intrabar-order fabrication / cross-contract structure / OOS backfill /
  production boundary violation / automatic promotion

Important
= source-vs-engineering semantic mismatch / missing exact edge rule / SuBing regression /
  shared abstraction leaks source-specific semantics / non-deterministic evidence

Minor
= naming/formatting/readability that does not change behavior
```

Tasks 1～4、9、10 的集成 Gate：

```text
Critical = 0
Important = 0
```

## 9. 最终允许结论

Phase 完成最多只能写：

```text
N Structural Domain V1 已形成可复算的 5m Historical structure kernel；
N Candidate 已形成 retrospective/rolling evidence；
prospective OOS 从 2026-08-21 起按真实未来样本积累。
```

不得写：

```text
N 字策略有效
可交易
可发第三条 Alert
可晋升 Formal Rule
允许 main/tag release
允许 Runtime promotion
```
