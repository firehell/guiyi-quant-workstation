# TASK-JDJ-1M-CANDIDATE-V1-20260821 — 执行合同

> 状态：PLANNED_ONLY
>
> Design：`docs/superpowers/specs/2026-08-21-jdj-1m-candidate-v1-design.md`
>
> Plan：`docs/superpowers/plans/2026-08-21-jdj-1m-candidate-v1.md`
>
> 当前提交只冻结实施合同，不实现代码、不运行真实 JDJ evidence、不修改 `main`/tag/Runtime/Alert/DB/Canonical，也不形成 Candidate 晋升授权。
>
> 本合同是 Design/Plan 的规范性执行补充。Design 中 `eligible pivot`、`公共 ARMED`、`复用 previous-bar trigger` 等概括措辞，按本合同 precise fail-closed 定义执行；真正冲突则 `BLOCKED_CANONICAL_DRIFT`。

## 1. Goal / Boundary

只实现：

```text
existing domestic-futures Historical facts
→ 5m N Structure trend context
+ 1m EMA20/price facts
→ 3 JDJ pure setup reducers
→ immutable trigger events
→ read-only source research
→ exact Candidate Validation
→ jm retrospective / 10-fold / prospective freeze
```

不实现：

```text
stop/take-profit/trailing stop
position/add-on/daily trade count/profit target
other book strategies
parameter sweep
fill/slippage/fee/PnL/backtest engine
Web/API/DB/Redis/worker
Alert/PushPlus/Execution Review/order
active60 Robustness V2
main/tag/release/Runtime
```

始终：`research_only=true`、`readonly=true`、`auto_order=false`。

## 2. Mandatory fact sources

每个 Task：

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
```

冲突：`BLOCKED_CANONICAL_DRIFT`。

## 3. Source-derived vs GUIYI V1

来源只支持：

```text
Trend Follow: trend → pullback → 20MA reaction → previous-bar high/low entry
Reentry 6: cross 20MA → return trend-side → higher-low/lower-high → same entry trigger
Key Level: return to key level → first break do not chase → wait retest second chance
```

用户明确：所有 MA 均使用 EMA。因此 `20MA→EMA20` 是 `GUIYI_ENGINEERING_V1`，不是原作者明确公式。

## 4. Exact identities

```text
policy_id       = jdj_1m_policy_v1
formula_version = jdj_1m_v1
source_kind     = jdj_1m
```

Candidate：

```text
jdj_trend_follow_1m_candidate_v1
→ jdj_trend_follow_triggered

jdj_trend_reentry_6_1m_candidate_v1
→ jdj_trend_reentry_6_triggered

jdj_key_level_breakout_1m_candidate_v1
→ jdj_key_level_breakout_triggered
```

Protocol：

```text
jdj_candidate_validation_v1
frozen_at = 2026-08-21T09:34:00+08:00
anchor = jm
retrospective = 2023-01-01..2026-08-20
embargo = 2026-08-21
prospective_first = 2026-08-24
baseline_through = 2026-08-21
rolling = exact existing 10 folds (12/3/3)
horizons = 3/5/8/20
```

Identity/date/horizon drift = `FORMULA_OR_CANDIDATE_DRIFT`。

## 5. Exact policy must mechanically freeze formula semantics

`data/research_policies/jdj_1m_policy_v1.json` 不能只保存 period/timeframe；必须 exact nested freeze：

```text
trend_context:
  existing n_structure_5m_v1 / n_structure_v1
  strict_before=true
  same_epoch_key_level=true

ema:
  kind=ema
  period=20
  seed_policy=sma_window
  round_digits=6
  input_field=close

previous_bar_trigger:
  dynamic_reference=true
  equal_is_breach=false
  fill_model=false

trend_follow:
  reaction=ema_touch_and_close_on_trend_side
  armed_invalidation=ema_close_failure_or_trend_lost
  same_bar_trigger_invalidation=ambiguous_no_event

trend_reentry_6:
  trend_side_prerequisite=true
  excursion_reference=opposite_ema_side_extreme
  reclaim=first_close_back_on_trend_side
  reclaim_bar_can_react=false
  first_post_reclaim_reaction_only=true
  failed_first_reaction_terminal=true
  armed_invalidation=ema_close_failure_or_trend_lost

key_level_breakout:
  pivot_source=latest_same_epoch_confirmed_n_swing
  post_confirmation_origin_side_required=true
  first_break_basis=close_cross
  first_break_creates_entry=false
  first_break_bar_can_retest=false
  volume_rule=all_first_break_do_not_chase
  retest=touch_level_and_close_on_breakout_side
  failed_retest=close_not_on_breakout_side
  same_pivot_single_episode=true
  armed_invalidation=close_back_through_frozen_level_or_trend_lost

outcome:
  reference_price=trigger_bar_close
  horizons_bars=[3,5,8,20]
  trigger_bar_in_future_window=false
  same_trading_day=true
  same_physical_contract=true
  same_rank1_segment=true

parameter_sweep=false
automatic_ranking=false
automatic_promotion=false
```

Loader exact recursive key/type/value match；任何缺失/额外/变值失败 `JDJ_POLICY_INVALID`。

## 6. Historical identity

唯一：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
```

JDJ source request exactly：

```python
frequencies=(BarFrequency.M1, BarFrequency.M5)
```

必须 same symbol + physical contract + rank1 segment；不自判主力、不 direct provider/storage。

## 7. EMA20

Exact call：

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

ready point 仅 `Decimal(str(point.value))` 进入业务比较；EMA not ready=normal no-op。

## 8. 5m→1m strict-before

当前 1m only consumes：

```text
fact.observed_at <= previous_1m.bar_end
```

09:35 新 5m fact 不能供 09:35 1m；最早 09:36。

Trend：

```text
BULL→LONG only
BEAR→SHORT only
RANGE/UNDEFINED/no snapshot→no setup
```

## 9. Same-epoch Key Level

Eligible LONG pivot：

```text
kind=HIGH
confirmed_at <= previous_1m.bar_end
epoch == pre_known_snapshot.epoch
```

SHORT mirror LOW。多个候选 deterministic max：`(confirmed_at,pivot_time,pivot_id)`。

outside reset 后旧 epoch pivot 永久不再供新 episode。

## 10. State identity/reset

State identity：

```text
symbol + contract + segment_start_trading_day + trading_day
```

Day/contract/segment/source identity change or trend no longer matches current direction → terminal/reset。不得自动反手；新方向从后续 boundary 按前置条件重建。

## 11. Trend Follow exact state

LONG：

```text
BULL
+ low <= EMA20 <= high
+ close > EMA20
→ ARMED_LONG

later current.high > previous.high
AND close > EMA20
AND trend=BULL
→ TRIGGERED

close <= EMA20 OR trend != BULL
→ INVALIDATED
```

Trigger + invalidation same OHLC → `AMBIGUOUS_TRIGGER_INVALIDATION` → no event。SHORT mirror。

## 12. Reentry 6 exact state

LONG：

```text
BULL + observed close>EMA20 prerequisite
→ later close<=EMA20 opens excursion
→ excursion_low=min(lows while close<=EMA20)
→ first close>EMA20 reclaim
→ reclaim bar cannot react
→ first later support reaction only
→ reaction.low > excursion_low => ARMED
→ reaction.low <= excursion_low => terminal
```

Reclaim 后 first reaction 前再次 close<=EMA20：旧 reclaim 失败，当前 bar 开新 excursion。

ARMED 使用 Trend Follow 的 dynamic previous-bar trigger + EMA/trend invalidation + ambiguity。SHORT mirror。不得创建 position/real exit。

## 13. Key-Level exact state

Key-Level setup **不使用 EMA20 entry/invalidation**。

LONG：

```text
BULL + same-epoch HIGH pivot
→ post-confirmation observed close<=level
→ previous.close<=level AND current.close>level = FIRST_BREAK
→ first break no entry / do not chase
→ next bar onward wait retest
→ low<=level AND close>level = accepted → ARMED
→ close<=level = failed retest → terminal
→ ARMED trigger current.high>previous.high
→ ARMED invalid if trend!=BULL OR close<=frozen level
→ trigger+invalid same bar = ambiguous/no event
```

Short mirror。

FIRST_BREAK freeze pivot id/price/confirmed_at/first_break_at；new pivot cannot replace active episode。同 pivot terminal 后 same day/segment consumed，不再开第二个 episode。

No retest to day-end=`EXPIRED_NO_RETEST`；trend/segment lost=`EXPIRED_CONTEXT_LOST`。

“放量突破不要追”因没有 volume threshold：V1 对 **all first breaks** do-not-chase；禁止 high_volume 判定。

## 14. Exact implementation types

Task 2 defines：

```python
class JdjContextError(ValueError):
    code = "JDJ_CONTEXT_INVALID"
```

Task 6 defines：

```python
class JdjSourceUnavailableError(RuntimeError):
    code = "JDJ_SOURCE_UNAVAILABLE"

JdjTriggerEvent: TypeAlias = (
    JdjTrendFollowTriggerEvent
    | JdjTrendReentryTriggerEvent
    | JdjKeyLevelBreakoutTriggerEvent
)
```

Task 7 defines in dedicated file `jdj_candidate_validation_calendar.py`：

```python
class JdjProspectiveCalendarError(ValueError):
    code = "JDJ_PROSPECTIVE_CALENDAR_INVALID"

def assert_jdj_prospective_calendar(session: Session) -> None: ...
```

Task 8 composition consumes that exact function before exposing JDJ Candidate Validation。

## 15. Immutable events

Common fields：

```text
event_id candidate_id source_event_kind direction
symbol contract segment_start_trading_day trading_day
observed_at segment_bar_index trigger_level observation_close
```

Setup-specific provenance exactly per Design/Plan。Event id only stable business identity/provenance；no UUID/random/Python hash/DB id。

Ordering：`(observed_at, segment_bar_index, event_id)`。

## 16. Outcome

```text
reference = trigger bar close
future = bars index+1 .. index+H
H = 3/5/8/20
```

Trigger bar high/low excluded。Must same day/contract/segment and `trading_day<=request.through`。不足 H no sample。

## 17. Candidate Validation/OOS

Reuse：

```text
CandidateValidationRequest
build_rolling_validation_windows
prospective_window
```

No second scheduler。

Baseline through 2026-08-21：

```text
retrospective through 2026-08-20
prospective pending
first 2026-08-24
through 2026-08-21
result=null
```

No 2026-08-21/history backfill。

Calendar validator read-only proves via existing Instrument/TradingCalendar：

```text
2026-08-21 trading
2026-08-22/23 non-eligible
2026-08-24 trading
```

Missing/conflict → stable error；do not alter dates/calendar。

## 18. Exception boundary

JDJ source maps only：

```text
MarketDataError
ActualDominantResearchSegmentIdentityError
→ JDJ_SOURCE_UNAVAILABLE
```

Context invariant → `JDJ_CONTEXT_INVALID`。

Candidate Validation only converts `JdjSourceUnavailableError` / `JdjContextError` to shared `CandidateValidationSourceError`。

Must propagate programming failures：

```text
TypeError
AssertionError
programming ValueError
unexpected RuntimeError
KeyError
result/candidate identity mismatch
reducer invariant failure
```

No `except Exception` source swallowing。

## 19. CLI

```text
guiyi research jdj-1m --candidate <exact3> --symbol <symbol> --since <date> --through <date>
```

and existing `candidate-validation` + exact JDJ candidate + `jdj_candidate_validation_v1`。

Reject：`--ema-period --volume-multiple --timeout-bars --trend-method --key-level-distance`。

stdout JSON only；artifact files only explicit Task 10 shell redirect/copy。

## 20. Allowed / forbidden files

Allowed new/modified：exact JDJ JSONs, `jdj_*.py`, JDJ tests, composition/research CLI files, TESTING/STATUS/PROJECT_SOURCE/ARCHITECTURE, three JDJ evidence files。

Forbidden modification：existing N policy/candidate/protocol/implementation/evidence；existing SuBing policy/candidate/protocol/evidence；Data Foundation/Catalog/Canonical；Alert/Execution Review/Runtime/release files。

## 21. Codex 调度建议

- 任务车道：Tasks 1–6 Lane 3；Task 7/10 Lane 1；Task 8 Lane 2；Task 9 Lane 3 Review
- 执行入口：Codex App
- 推荐模型：Tasks 1–7/9/10 Sol；Task 8 Terra
- 推理强度：Tasks 1–7/9/10 高；Task 8 中
- 会话：每个 Task 独立；Lane 3 implementation 后另开独立 Review
- Plan：Tasks 1–6 Plan-only→人工批准；Task 7/8/10 Plan-then-execute；Task 9 Review-only
- 工作区：task worktree from latest develop；Task9 detached review；Task10 evidence worktree
- 人工 Gate：Tasks1–6 Plan批准+Review；Task7 Review；Task9 C0/I0；Task10 Evidence C0/I0

| Task | Deliverable | Lane | Model | Gate |
| --- | --- | --- | --- | --- |
| 1 | exact policy/candidates/protocol | 3 | Sol 高 | Plan + Review C0/I0 |
| 2 | strict-before context | 3 | Sol 高 | Plan + Review C0/I0 |
| 3 | Trend Follow | 3 | Sol 高 | Plan + Review C0/I0 |
| 4 | Reentry 6 | 3 | Sol 高 | Plan + Review C0/I0 |
| 5 | Key Level | 3 | Sol 高 | Plan + Review C0/I0 |
| 6 | source research/outcome | 3 | Sol 高 | Plan + Review C0/I0 |
| 7 | Validation/OOS/calendar | 1 | Sol 高 | Review C0/I0 |
| 8 | composition/CLI | 2 | Terra 中 | tests/self-review |
| 9 | cumulative Review | 3 | Sol 高 | C0/I0 |
| 10 | exact evidence | 1 | Sol 高 | Evidence C0/I0 |

## 22. Worktree lifecycle

Tasks1–8：latest develop→new branch/worktree→required Plan gate→TDD→verification→Review→develop→ancestry readback→cleanup。

Task9：clean develop detached review；finding fix separate branch；rerun/re-review。

Task10：accepted develop→evidence worktree→fresh verification→old baseline parity→3 new reports→rerun parity→Evidence Review→docs/evidence develop→cleanup。

No task authorizes main/tag/Runtime/Alert/notification/DB/Canonical/order。

## 23. Review severity

Critical：future leak/same-boundary use；cross-day/contract/segment state；N same-identity formula change；OOS backfill；optimistic OHLC order；fill/order/position path；production boundary violation。

Important：EMA exact drift；cross-epoch pivot；Key-Level EMA invalidation；first-break direct entry；Reentry skip first failed reaction；candidate mixing；trigger bar in future metrics；broad exception swallow；nondeterminism；duplicate resolver。

Lane3/final Review Gate：`Critical=0 / Important=0`。

## 24. Verification

Required：all JDJ focused tests；N full-chain；SuBing zero-regression；existing Candidate Validation；Multi-Candidate Robustness V1；Ruff；Mypy；secret_scan；diff-check。

Specific proof：09:35/09:36 strict-before；same-epoch after reset；3 reducer symmetry/prefix；same-bar ambiguous no-event；Key-Level ignores EMA after retest；request-through outcome cutoff；2026-08-24 pending/no backfill。

## 25. Evidence

Exact paths：

```text
reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
```

Before tracking: existing SuBing/N tracked baselines exact rerun `cmp`。Each JDJ artifact exact identity/dates/folds/horizons/pending OOS and byte-identical rerun。Evidence Review no winner/rank/KEEP/DROP/PROMOTE/profit/fill/order conclusion。

## 26. Final allowed conclusion

```text
JDJ V1 已把 Trend Follow、Trend Reentry 6、Key-Level Breakout 三条 source-derived 1m setup
转换为三个 exact causal Candidate；趋势上下文复用 existing 5m N Structure，
形成 jm retrospective / 10-fold rolling baseline 并冻结 prospective OOS；结果仍为 research-only。
```

禁止声明有效/盈利/最好/KEEP/DROP/PROMOTE/可 Alert/可交易/可 main-tag/可 Runtime promotion。
