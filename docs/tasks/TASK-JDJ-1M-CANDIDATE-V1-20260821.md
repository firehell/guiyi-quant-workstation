# TASK-JDJ-1M-CANDIDATE-V1-20260821 — 执行合同

> 状态：PLANNED_ONLY
>
> Design：`docs/superpowers/specs/2026-08-21-jdj-1m-candidate-v1-design.md`
>
> Plan：`docs/superpowers/plans/2026-08-21-jdj-1m-candidate-v1.md`
>
> 本合同约束后续 Codex 实施、Implementation Review 与 Evidence Review。当前文档提交不实现 JDJ 代码、不运行真实研究窗口、不生成 baseline、不修改 `main`/tag/Runtime/Alert/DB/Canonical，也不形成策略晋升授权。
>
> 本合同是 Design / Plan 的规范性执行补充：当 Design 使用“eligible pivot”“复用公共 trigger”等概括措辞时，以本合同的 precise fail-closed 定义执行；如出现真正语义冲突则 `BLOCKED_CANONICAL_DRIFT`，不得由实现者自行解释。

## 1. 任务目标

建立：

```text
Domestic futures actual-dominant
        ↓
1m completed bars ── EMA20
        +
existing 5m N Structure V1
        ↓ strict-before / same segment
JDJ 1m Research Domain
├─ TREND_FOLLOW
├─ TREND_REENTRY_6
└─ KEY_LEVEL_BREAKOUT
        ↓
3 exact Candidate producers
        ↓
existing rolling/prospective Candidate Validation pattern
        ↓
jm retrospective + 10-fold baseline
        +
prospective freeze
```

始终：

```text
research_only=true
readonly=true
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
docs/superpowers/specs/2026-08-21-jdj-1m-candidate-v1-design.md
docs/superpowers/plans/2026-08-21-jdj-1m-candidate-v1.md
本文件
任务相关 current implementation/tests
```

若 active canonical 与本合同不一致：

```text
BLOCKED_CANONICAL_DRIFT
→ stop
→ 不猜测、不顺手修改 canonical
```

## 3. Source Scope Freeze

唯一 source-derived 交易语义：

```text
TREND_FOLLOW
趋势 → 回撤到 20MA 看反应 → 有支撑/阻力 → 过上一根 K 高/低

TREND_REENTRY_6
过 20MA 后再次进入趋势侧 → 更高低点/更低高点 → 入场同 Trend Follow

KEY_LEVEL_BREAKOUT
再次到达关键位 → 第一次突破不追 → 等回撤第二次机会 → 不回撤则放弃
```

明确禁止导入：

```text
止损 / 止盈 / 移动止损
仓位 / 加仓 / 每日次数 / 盈利目标
VWAP / ABC / 三角形 / 多空陷阱
MACD / BOLL / OI filter
volume multiple
ATR/bp/tick proximity
固定 3/5/N-bar setup timeout
手续费 / 滑点 / fill / position / PnL
```

原资料写 `20MA`；用户明确决定 JDJ 全部 MA 采用 EMA。因此：

```text
SOURCE_DERIVED = 20MA
GUIYI_ENGINEERING_V1 = EMA20
```

不得反向声称原资料明确规定 EMA20。

## 4. Exact Identity Freeze

### Common source policy

```text
policy_id       = jdj_1m_policy_v1
formula_version = jdj_1m_v1
source_kind     = jdj_1m
source_tf       = 1m
trend_tf        = 5m
```

### Three Candidate identities

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

三者 manifest 均：

```text
source_kind     = jdj_1m
policy_id       = jdj_1m_policy_v1
formula_version = jdj_1m_v1
research_only   = true
```

### Source event identity

```text
jdj_trend_follow_1m_candidate_v1
→ source_event_kind = jdj_trend_follow_triggered

jdj_trend_reentry_6_1m_candidate_v1
→ source_event_kind = jdj_trend_reentry_6_triggered

jdj_key_level_breakout_1m_candidate_v1
→ source_event_kind = jdj_key_level_breakout_triggered
```

禁止一个 source event 被另一个 Candidate 消费/重标。

### Validation protocol

```text
protocol_id = jdj_candidate_validation_v1
frozen_at = 2026-08-21T09:34:00+08:00
anchor_symbol = jm
retrospective = 2023-01-01..2026-08-20
embargo = [2026-08-21]
prospective_first = 2026-08-24
baseline_request_through = 2026-08-21
horizons = [3,5,8,20]
rolling = 12m reference / 3m test / 3m step / exact 10 folds
```

任何 identity/date/horizon 变化：

```text
FORMULA_OR_CANDIDATE_DRIFT
→ stop
→ 重新设计/新 Candidate 或 Protocol 版本
```

## 5. Historical / Market Identity Boundary

唯一链路：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
→ exact restored rank1 segments
→ JDJ
```

一次 JDJ source request 必须请求：

```python
frequencies=(BarFrequency.M1, BarFrequency.M5)
```

联合事实必须：

```text
same symbol
same physical contract
same rank1 segment
```

JDJ 不得：

```text
direct Parquet
RQData direct query
Redis Live read
第二 rank1 resolver
continuous fallback
另建 physical actual-dominant dataset
```

## 6. EMA20 Exact Contract

必须调用：

```python
ema_series(
    closes,
    20,
    bar_ends=bar_ends,
    seed_policy="sma_window",
    indicator_code="ema20",
    round_digits=6,
)
```

Exact semantics：

```text
first ready index = 19
seed = first 20 close SMA
alpha = 2/(20+1)
closed_bar_only = true
repainting_risk = none
```

ready/valid point 的 float value 只能通过：

```python
Decimal(str(point.value))
```

转回 Decimal；业务比较中禁止继续传播 float。

EMA not ready：正常 no-op，不是 source unavailable。

## 7. 5m N Context Strict-Before Contract

JDJ 复用 current exact：

```text
n_structure_5m_v1
n_structure_v1
```

当前 1m bar 的 eligible N facts：

```text
fact.observed_at <= previous_completed_1m.bar_end
```

等价必要条件：

```text
fact.observed_at < current_1m.bar_end
```

因此：

```text
09:35 1m 不得消费 09:35 新确认 5m fact
09:36 1m 才可消费 09:35 5m fact
```

若没有 previous 1m bar，当前 bar 无 pre-known trend context。

映射：

```text
BULL → LONG only
BEAR → SHORT only
RANGE / UNDEFINED / no snapshot → no setup
```

same-boundary future use = Critical。

## 8. Same-Epoch Key Level Eligibility

Design 中的 `latest eligible confirmed 5m N Pivot` 精确定义为：

```text
pivot.confirmed_at <= previous_1m.bar_end
AND
pivot.epoch == pre_known_structure_snapshot.epoch
AND
LONG:  pivot.kind == HIGH
SHORT: pivot.kind == LOW
```

若多个满足，按以下 deterministic ordering 取最后一个：

```text
(confirmed_at, pivot_time, pivot_id)
```

一旦 N Swing outside reset 把 snapshot epoch 从 E 变为 E+1：

```text
所有 epoch=E 的旧 pivot 对新的 JDJ key-level episode 不再 eligible
```

不得因为价格仍接近旧 pivot 而跨 epoch 复用。

## 9. State Boundary / Direction Change

所有 reducer state identity：

```text
symbol + physical_contract + segment_start_trading_day + trading_day
```

以下发生立即 terminal/reset：

```text
trading_day change
contract change
rank1 segment change
source identity invalid
pre-known trend 不再匹配当前 episode direction
```

若 trend 从 BULL 变 BEAR：

```text
当前 LONG episode 先 terminal/reset
不能同一 state 自动反手
新 SHORT episode 只能由后续满足其前置条件的 boundary 新建
```

## 10. Common EMA Reaction

LONG：

```text
pre-known N = BULL
low <= EMA20 <= high
close > EMA20
→ support reaction
```

SHORT：

```text
pre-known N = BEAR
low <= EMA20 <= high
close < EMA20
→ resistance reaction
```

等于 EMA 的 close 不算收回趋势侧。

## 11. Common Dynamic Previous-Bar Trigger

ARMED state 必须已经存在于 previous boundary。

LONG：

```text
current.high > previous_1m.high
```

SHORT：

```text
current.low < previous_1m.low
```

Equal 不触发。

未触发时下一分钟 trigger reference 自动更新到新的 previous bar；不固定 reaction bar。

记录：

```text
trigger_level = previous high/low
observed_at = current bar_end
observation_close = current close
```

禁止：

```text
fill_price
order_price
executed_price
slippage
fee
position
pnl
```

## 12. TREND_FOLLOW Normative State Machine

LONG：

```text
IDLE
→ BULL + support reaction
→ ARMED_LONG

ARMED_LONG:
  current.high > previous.high
  AND close > EMA20
  AND pre-known trend == BULL
  → TRIGGERED

  close <= EMA20 OR pre-known trend != BULL
  → INVALIDATED
```

若同一 bar：

```text
high > previous.high
AND close <= EMA20
```

则：

```text
AMBIGUOUS_TRIGGER_INVALIDATION
→ no event
→ terminal
```

SHORT mirror。

TRIGGERED/INVALIDATED 后新的 EMA reaction 可以开始新 episode；V1 无每日次数限制。

## 13. TREND_REENTRY_6 Normative State Machine

### LONG

必须先在匹配 BULL context 下真实观察：

```text
close > EMA20
→ trend-side prerequisite satisfied
```

之后：

```text
close <= EMA20
→ below-EMA excursion
```

连续 excursion：

```text
excursion_low = min(all excursion bar lows)
```

首次：

```text
close > EMA20
→ reclaim
```

reclaim bar 本身不能成为 post-reclaim reaction。

下一阶段第一次 support reaction：

```text
low <= EMA20 <= high
AND close > EMA20
```

若：

```text
reaction.low > excursion_low
→ higher-low setup → ARMED_LONG
```

若：

```text
reaction.low <= excursion_low
→ episode terminal failed
```

禁止跳过 first failed reaction 等后面的“更好”reaction。

reclaim 后、first reaction 前若再次 `close <= EMA20`：旧 reclaim 失败，从当前 bar 开始新的 excursion；旧/new extreme 不合并。

ARMED 后使用 Trend Follow 的 dynamic previous-bar trigger + EMA/trend invalidation + same-bar ambiguity。

### SHORT

全部镜像：trend-side prerequisite `close < EMA20`；above-EMA excursion high；reclaim below EMA；first resistance reaction `reaction.high < excursion_high`；dynamic previous-low trigger。

来源中的“平仓”只叫 `EMA20_EXIT_PROXY` / excursion，不创建真实/模拟 position。

## 14. KEY_LEVEL_BREAKOUT Normative State Machine

KEY_LEVEL_BREAKOUT 只使用：

```text
pre-known N direction
same-epoch 5m pivot
1m close/high/low
```

不使用 EMA20 作为该 setup 的 entry/invalidation filter。

### LONG

1. BULL + eligible same-epoch HIGH pivot。
2. pivot confirmed 后必须先观察 `close <= key_level`，才进入 first-break eligibility。
3. FIRST_BREAK：`previous.close <= key_level AND current.close > key_level`。
4. FIRST_BREAK 永远 `DO_NOT_CHASE`，不生成 Candidate event。
5. freeze `pivot_id/price/confirmed_at/first_break_at`；新 pivot 不替换。
6. retest 从 first-break **下一根** bar 起：
   - accepted=`low <= key_level AND close > key_level` → ARMED_LONG；
   - failed=`close <= key_level` → terminal。
7. ARMED_LONG：
   - trigger=`current.high > previous.high`；
   - invalid=`pre-known trend != BULL OR close <= frozen key_level`；
   - trigger+invalid same bar → ambiguous/no event。
8. trading-day end waiting retest → `EXPIRED_NO_RETEST`；trend/segment lost → `EXPIRED_CONTEXT_LOST`。
9. terminal 后同 `pivot_id` 在 same day/segment 被 consumed，不得再开第二个 episode。

### SHORT

镜像：eligible LOW pivot；先 `close >= key_level`；first-break `previous.close >= level AND current.close < level`；accepted retest `high >= level AND close < level`；invalid `close >= frozen key_level`；trigger previous-low strict breakdown。

### Volume interpretation

原话“放量突破不要追”没有量化阈值。因此 V1：

```text
ALL FIRST_BREAK → DO_NOT_CHASE
```

可以保留原始 first-break volume provenance；禁止生成 `high_volume` boolean 或 1.5x/2x threshold。

## 15. Immutable Event Contract

三个 event 类型都必须 frozen/slots，公共字段至少：

```text
event_id
candidate_id
source_event_kind
direction
symbol
contract
segment_start_trading_day
trading_day
observed_at
segment_bar_index
trigger_level
observation_close
```

Trend Follow provenance：

```text
trend_snapshot_observed_at
reaction_at
ema20_at_reaction
```

Reentry provenance：

```text
trend_snapshot_observed_at
excursion_started_at
excursion_extreme
reclaimed_at
reaction_at
```

Key Level provenance：

```text
trend_snapshot_observed_at
trend_epoch
key_level_pivot_id
key_level_price
key_level_confirmed_at
first_break_at
retest_at
```

Canonical event ID 必须由业务 identity/provenance 构造，不使用随机 UUID、运行序号、Python hash 或 DB id。

Ordering：source service events 按：

```text
(observed_at, segment_bar_index, event_id)
```

相同 exact 输入重复运行完全一致。

## 16. Outcome Contract

Reference：

```text
reference_price = trigger completed bar close
```

不是 trigger level/fill。

Horizon H：

```text
future = subsequent completed 1m bars [1..H]
```

Trigger bar high/low 不进入 MFE/MAE。

必须同时：

```text
same trading_day
same physical contract
same rank1 segment
bar.trading_day <= request.through
```

不足 H：no sample。

H：

```text
3, 5, 8, 20
```

输出：

```text
sample_count
median_directional_return_bps
median_mfe_bps
median_mae_bps
```

只描述价格后验，不等于盈利能力。

## 17. Candidate Validation / OOS Contract

必须复用 existing：

```text
CandidateValidationRequest
build_rolling_validation_windows
prospective_window
```

禁止第二 rolling engine。

Exact 10 folds 与现有 SuBing/N schedule 一致。

Baseline through=`2026-08-21` 时：

```text
retrospective = 2023-01-01..2026-08-20
2026-08-21 = embargo
prospective status = pending
prospective first = 2026-08-24
prospective through = 2026-08-21
prospective result = null
```

禁止使用 2026-08-21 或任何 retrospective 数据回填 OOS。

### Calendar validation

实施必须 read-only 验证 existing metadata：

```text
anchor = jm
2026-08-21 trading day
2026-08-22 not eligible
2026-08-23 not eligible
2026-08-24 trading day
```

exchange 通过 existing `Instrument` 解析；calendar 通过 existing `TradingCalendar`。缺失/冲突：

```text
JDJ_PROSPECTIVE_CALENDAR_INVALID
→ fail closed
```

不得修改 Calendar，不得自动选 2026-08-25 等替代日期。

## 18. Source / Exception Boundary

JDJ Research source only converts：

```text
MarketDataError
ActualDominantResearchSegmentIdentityError
→ JdjSourceUnavailableError(code="JDJ_SOURCE_UNAVAILABLE")
```

JDJ context invariant/identity errors：

```text
JdjContextError(code="JDJ_CONTEXT_INVALID")
```

Candidate Validation only converts those typed source/context errors to shared `CandidateValidationSourceError`。

以下必须原样逃逸并 fail whole run：

```text
TypeError
AssertionError
programming ValueError
unexpected RuntimeError
KeyError
candidate/result identity mismatch
reducer invariant failure
```

禁止：

```python
except Exception:
    raise CandidateValidationSourceError()
```

这种 broad swallowing。

错误 artifact/CLI 只暴露 stable public code，不暴露 canonical path/provider internal message。

## 19. File Boundary

### Allowed new/modified implementation files

```text
data/research_policies/jdj_1m_policy_v1.json
data/research_candidates/jdj_*_candidate_v1.json
data/research_protocols/jdj_candidate_validation_v1.json
services/quant-api/app/market_data/jdj_*.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/test_jdj_*.py
services/quant-api/tests/data_foundation/test_jdj_*.py
services/quant-api/tests/test_research_cli.py
TESTING.md
STATUS.md
PROJECT_SOURCE.md
docs/ARCHITECTURE.md
three exact reports/research/candidate_validation/jdj_* artifacts
```

### Explicitly forbidden modifications

```text
data/research_policies/n_structure_5m_v1.json
data/research_candidates/n_structure_5m_candidate_v1.json
data/research_protocols/n_structure_validation_v1.json
existing SuBing policy/candidate/protocol files
existing tracked SuBing/N baseline JSON
Market Foundation DatasetKey/Catalog/Canonical schema
Alert Rule/Scope/notification files
Execution Review migrations/schema
Runtime deployment identity
main/tag/release files for publication
```

Existing N implementation files should remain unchanged unless a separately approved defect task proves JDJ cannot consume current public facts. “方便 JDJ”不是修改 N 的理由。

## 20. Read-only CLI Freeze

Source command：

```text
guiyi research jdj-1m \
  --candidate <exact one of three> \
  --symbol <symbol> \
  --since YYYY-MM-DD \
  --through YYYY-MM-DD
```

Candidate baseline：

```text
guiyi research candidate-validation \
  --candidate <exact JDJ candidate> \
  --protocol jdj_candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-21
```

禁止 runtime tuning flags：

```text
--ema-period
--volume-multiple
--timeout-bars
--trend-method
--key-level-distance
```

stdout JSON only；不写 artifact 文件。版本化 artifact 只在 Evidence Task 由 shell redirect/cp 显式创建。

## 21. Codex 调度建议

- 任务车道：Tasks 1–6 Lane 3；Task 7/10 Lane 1；Task 8 Lane 2；Task 9 Lane 3 Review
- 执行入口：Codex App
- 推荐模型：Tasks 1–7/9/10 Sol；Task 8 Terra
- 推理强度：Tasks 1–7/9/10 高；Task 8 中
- 会话：每个 Task 独立会话；Tasks 1–6 代码实现后另开独立 Review；Task 9/10 各自独立 Review 会话
- Plan：Tasks 1–6 Plan-only → 人工批准后实现；Task 7 Plan-then-execute；Task 8 Plan-then-execute；Task 9 Review-only；Task 10 Plan-then-execute
- 工作区：每个实现 Task 从最新 `develop` 新 task worktree；Task 9 clean detached review worktree；Task 10 independent evidence worktree
- 人工 Gate：Tasks 1–6 Plan 批准 + 独立 Review；Task 7 独立 Review；Task 8 无真实写入 Gate；Task 9 C0/I0；Task 10 Evidence C0/I0

### Task Matrix

| Task | Deliverable | Lane | Model | Plan | Integration Gate |
| --- | --- | --- | --- | --- | --- |
| 1 | exact Policy/Candidates/Protocol | Lane 3 | Sol 高 | Plan-only | Plan approval + Review C0/I0 |
| 2 | 1m/5m causal context | Lane 3 | Sol 高 | Plan-only | temporal Review C0/I0 |
| 3 | Trend Follow reducer | Lane 3 | Sol 高 | Plan-only | formula Review C0/I0 |
| 4 | Reentry 6 reducer | Lane 3 | Sol 高 | Plan-only | formula Review C0/I0 |
| 5 | Key-Level reducer | Lane 3 | Sol 高 | Plan-only | formula Review C0/I0 |
| 6 | source research + outcomes | Lane 3 | Sol 高 | Plan-only | source/outcome Review C0/I0 |
| 7 | Candidate Validation/OOS | Lane 1 | Sol 高 | Plan-then-execute | OOS Review C0/I0 |
| 8 | composition + readonly CLI | Lane 2 | Terra 中 | Plan-then-execute | tests + self-review |
| 9 | cumulative implementation review | Lane 3 | Sol 高 | Review-only | Critical=0/Important=0 |
| 10 | exact develop evidence/closeout | Lane 1 | Sol 高 | Plan-then-execute | Evidence C0/I0 |

## 22. Worktree / Integration Lifecycle

Tasks 1–8：

```text
latest origin/develop
→ independent task branch/worktree
→ Plan/Gate as required
→ TDD
→ focused verification
→ self-review / independent Review as required
→ task branch → develop
→ read back origin/develop ancestry
→ cleanup task worktree/merged branch
```

Task 9：

```text
clean exact develop
→ detached Review worktree
→ no edits unless concrete finding
→ finding fix uses separate branch
→ rerun affected+cumulative verification
→ Review C0/I0
```

Task 10：

```text
exact accepted develop
→ evidence branch/worktree
→ fresh verification
→ existing baseline byte parity
→ 3 JDJ exact historical commands
→ deterministic reruns
→ Evidence Review C0/I0
→ canonical docs closeout
→ develop
→ cleanup
```

任何 task→develop 都不授权：

```text
main merge
tag/release
Runtime switch/promotion
Alert Scope/notification
DB/Canonical/Redis write
order/account action
```

## 23. Review Severity

```text
Critical
= future leak / same-boundary 5m use /
  cross-contract/segment/day state leak /
  modify N formula under same identity /
  OOS backfill/relabel /
  optimistic OHLC trigger ordering /
  fill/order/position path /
  production/Runtime/Alert violation

Important
= EMA exact contract drift /
  key-level cross-epoch pivot reuse /
  key-level inherits EMA invalidation after retest /
  first-break directly creates entry /
  reentry skips first failed reaction /
  candidate/source-event identity mixing /
  trigger bar included in future outcome /
  broad exception swallowing /
  nondeterministic event/report /
  duplicated Historical/rank1/N resolver

Minor
= naming/format/readability issue with no semantic effect
```

All Lane 3 formula/temporal implementation Reviews and final Task 9 must satisfy：

```text
Critical = 0
Important = 0
```

## 24. Verification Freeze

至少：

```text
all new JDJ focused tests
current N full-chain regression
current SuBing zero-regression
current Candidate Validation regression
current Multi-Candidate Robustness V1 regression
Ruff
Mypy
secret_scan
git diff --check
```

必须额外证明：

```text
strict-before 09:35/09:36 boundary
same-epoch pivot after outside reset
LONG/SHORT symmetry for three reducers
prefix causality
same-bar ambiguous no-event
key-level no EMA invalidation
request-through horizon cutoff
prospective 2026-08-24 pending/no backfill
```

## 25. Evidence Freeze

三份首版 artifact：

```text
reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-21.json

reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-21.json

reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-21.json
```

每份必须：

```text
candidate exact
protocol exact
symbol=jm
retrospective through=2026-08-20
10 folds exact
prospective=pending
first=2026-08-24
through=2026-08-21
3/5/8/20 horizon keys exact
rerun byte-identical
```

Evidence 前必须先证明 existing tracked SuBing/N baseline byte-identical；任何 mismatch 阻塞 JDJ evidence，不更新旧 baseline。

Evidence Review 禁止输出 winner/rank/KEEP/DROP/PROMOTE/盈利结论。

## 26. Global Prohibitions

整个 Phase 6 禁止：

```text
改变 Data Foundation / DatasetKey / 八表 Catalog / Canonical
新增 QQQ/美股 provider
修改 N Structure V1 formula/policy/candidate/evidence
修改 SuBing formula/policy/candidate/evidence
参数 sweep / optimizer
backtest fill/cost engine
Strategy Plugin/Registry platform
Web/API dashboard
DB/Redis persistence
worker/queue/scheduler
Alert Rule/Scope
PushPlus send/canary
Execution Review consumer
order/account/position/PnL
main/tag/release
Runtime promotion/switch
自动 Candidate promotion
```

## 27. Final Acceptance / Allowed Conclusion

Phase 6 最多允许结论：

```text
JDJ V1 已将 Trend Follow、Trend Reentry 6、Key-Level Breakout 三条 source-derived 1m setup
转换为三个 exact causal Candidate；趋势上下文复用 existing 5m N Structure，
已形成 jm retrospective / 10-fold rolling baseline 并冻结 prospective OOS；结果仍为 research-only。
```

禁止：

```text
JDJ 有效/盈利
某 JDJ Candidate 最好
应该 KEEP/DROP/PROMOTE
允许新增 Alert/PushPlus
允许交易/下单
允许 main/tag release
允许 Runtime promotion
```
