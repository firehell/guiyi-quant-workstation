# 苏冰趋势策略-日 Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `苏冰趋势策略-日 / subing_daily_trend_v1` 的最小 completed-D1 增量策略内核、Historical Projection 与研究报告，先得到 JM/AG/RB/EG 和 active60 的真实历史效果，再决定是否继续 Current/API/Web/Alert。

**Architecture:** 新策略放在独立 `subing_daily_trend` 包中，不修改现行 `subing_strategy_v1`。Python completed-D1 增量状态机是唯一策略语义 owner；EMA/MACD/ATR 与 Range 复用现有 Quant Core，Range 只做 CHOP regime gate。Historical 通过 `MarketDataService` 的 `actual_dominant + 1d` 和权威 rank1 物理段重放同一个状态机；效果计算只消费 Action/Episode，不建设账户或正式回测域。

**Tech Stack:** Python 3.12、dataclasses、Decimal、quant-core indicator kernel、MarketDataService、pytest、现有 `guiyi research` CLI。

**Spec:** `docs/tasks/2026-08-31-subing-trend-daily-strategy-spec.md`

**Issue:** `#275`

**Planning baseline inspected:** `develop@472db690b9ecf41cdde18c4558367588cd06c24b`

## Global Constraints

- 本任务为 **Lane 3**；公式、成交时序和研究口径必须由 Sol/high 独立 Review。
- 开工前必须确认 Spec 与本 Plan 已进入执行时最新 `origin/develop`；本页 baseline 只记录计划编写时事实。
- 正式名称固定为 `苏冰趋势策略-日`；`strategy_id / formula_version / policy_id` 均固定为 `subing_daily_trend_v1`。
- 正式数据身份固定为 `actual_dominant + 1d`，只消费 completed D1。
- Range 固定 `range_detector_lux_v1 / length=20 / width=1.0×ATR500 / wilder_sma_seed`，只做 CHOP gate。
- EMA 固定 EMA21、`sma_window` seed、最近 5 个 EMA21 点的线性回归 slope；10-bar slope 不参与。
- MACD 固定 `12/26/9`、`sma_window` seed、histogram scale 2；near-zero 固定 `max(abs(DIF), abs(DEA)) / ATR14 <= 0.25`。
- 多头只认 `TREND_ELIGIBLE + close>EMA21 + slope5>0 + near-zero golden cross`；空头完全对称。
- 不加入 Range breakout、EMA crossover、1.5 ATR 距离、成交量、持仓量、BOLL、3-Bar confirmation、前高前低、多周期共振或二次确认。
- completed D1 `t` 只做 decision；普通参考生效价固定下一根同物理合约 D1 open。
- 普通退出只有 EMA21 opposite cross；物理段终止使用旧段最后一根 D1 close。
- 不加仓、不减仓、不反手、不跨物理段，不建设账户、订单、仓位或资金曲线。
- Stage A 不实现 Current、HTTP API、Market Web、Alert Rule、migration、Scope、PushPlus、main/tag、release 或 Runtime。
- 不写 RQData、Canonical、production PostgreSQL、Redis 或 Git 外生产状态。
- 真实 Historical 效果运行若读取本机正式 Catalog/Canonical，必须在运行前另取一次明确的 read-only 环境与 through-date 授权；单元测试和 fake fixture 不构成该授权。
- 必要检查失败时只报告失败，不声明完成。

## Execution Topology

```text
latest origin/develop
→ feature/subing-daily-trend-v1-historical task worktree
→ Task 1..7 小步 TDD / commit
→ Draft PR to develop
→ 独立 Sol/high Review
→ owner 批准只读 Historical 环境与 through date
→ JM/AG/RB/EG evidence
→ active60 evidence
→ owner Historical Gate
```

源码实现不得复用文档分支。实现 PR 在独立 Review 和 owner 明确批准前不得自动合入 `develop`；合入 `develop` 也不授权 main/tag、Runtime、生产写入或通知。

## File Map

### New files

```text
data/research_policies/subing_daily_trend_v1.json
services/quant-api/app/market_data/subing_daily_trend/__init__.py
services/quant-api/app/market_data/subing_daily_trend/contracts.py
services/quant-api/app/market_data/subing_daily_trend/policy.py
services/quant-api/app/market_data/subing_daily_trend/indicators.py
services/quant-api/app/market_data/subing_daily_trend/machine.py
services/quant-api/app/market_data/subing_daily_trend/replay.py
services/quant-api/app/market_data/subing_daily_trend/report.py
services/quant-api/app/research/subing/subing_daily_trend_research_service.py
services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py
services/quant-api/tests/research/test_subing_daily_trend_indicators.py
services/quant-api/tests/research/test_subing_daily_trend_machine.py
services/quant-api/tests/research/test_subing_daily_trend_replay.py
services/quant-api/tests/research/test_subing_daily_trend_report.py
services/quant-api/tests/research/test_subing_daily_trend_research_service.py
services/quant-api/tests/research/test_subing_daily_trend_cli.py
```

### Modified files

```text
packages/quant-core/guiyi_quant/indicators/range_detector_lux.py
packages/quant-core/guiyi_quant/indicators/__init__.py
services/quant-api/app/market_data/subing_ema_trend.py
services/quant-api/tests/test_subing_ema_trend.py
services/quant-api/tests/test_range_detector_lux.py
services/quant-api/app/research/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/research/test_research_cli_parser_requests.py
TESTING.md
```

禁止新增 generic strategy adapter、universal replay engine、账户模型、数据库表、snapshot store、worker、queue、scheduler 或 Alert Rule。

---

## Task 1: Range physical-segment regime reset seam

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/range_detector_lux.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test: `services/quant-api/tests/test_range_detector_lux.py`

**Produces:** `reset_range_detector_lux_regime(state: RangeDetectorLuxState) -> RangeDetectorLuxState`。

其唯一语义是：保留 `parameters / source_identity / atr / index / last_bar_end`，清空 `close_window / previous_candidate_valid / active_snapshot / active_detection_right_index`。

- [ ] **Step 1: 先写失败测试**

新增测试，构造已 ready 且存在 active range 的状态，调用尚不存在的 reset helper，并断言：

```python
before_atr = state.atr
reset = reset_range_detector_lux_regime(state)
assert reset.atr == before_atr
assert reset.parameters == state.parameters
assert reset.source_identity == state.source_identity
assert reset.index == state.index
assert reset.last_bar_end == state.last_bar_end
assert reset.close_window == ()
assert reset.previous_candidate_valid is False
assert reset.active_snapshot is None
assert reset.active_detection_right_index is None
```

再继续喂当前新物理段 Bar，证明 ATR 已 ready 也不能提前产生 Range regime；必须重新积累 `minimum_range_length + 1` 根当前段 close。

- [ ] **Step 2: 运行测试，确认因缺少 reset helper 而失败**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py
```

- [ ] **Step 3: 实现最小 helper 并导出**

实现只使用 `dataclasses.replace` 清理四个 regime-local 字段；不得修改 candidate、confirmation、revision、break、ATR 或 Web display 语义。

- [ ] **Step 4: 回归 Range 与 ATR/MACD kernel**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/range_detector_lux.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/tests/test_range_detector_lux.py
git commit -m "feat(indicators): add Range regime segment reset"
```

---

## Task 2: Exact policy and immutable strategy contracts

**Files:**
- Create: `data/research_policies/subing_daily_trend_v1.json`
- Create: `services/quant-api/app/market_data/subing_daily_trend/__init__.py`
- Create: `services/quant-api/app/market_data/subing_daily_trend/contracts.py`
- Create: `services/quant-api/app/market_data/subing_daily_trend/policy.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py`

**Exact policy JSON:**

```json
{
  "schema_version": 1,
  "strategy_id": "subing_daily_trend_v1",
  "formula_version": "subing_daily_trend_v1",
  "policy_id": "subing_daily_trend_v1",
  "research_only": true,
  "series_kind": "actual_dominant",
  "decision_frequency": "1d",
  "range": {
    "indicator_code": "range_detector_lux_v1",
    "minimum_range_length": 20,
    "range_width_atr_multiplier": 1.0,
    "range_atr_length": 500,
    "source": "close",
    "atr_smoothing_policy": "wilder_sma_seed",
    "regime_rule": "ready_and_no_intact_range_is_trend_eligible"
  },
  "ema": {
    "period": 21,
    "seed_policy": "sma_window",
    "slope_window": 5,
    "direction_rule": "price_side_and_slope"
  },
  "macd": {
    "fast": 12,
    "slow": 26,
    "signal": 9,
    "ema_seed_policy": "sma_window",
    "histogram_scale": 2,
    "near_zero_atr14_max": 0.25
  },
  "atr14": {
    "period": 14,
    "smoothing_policy": "wilder_sma_seed"
  },
  "execution": {
    "decision_basis": "completed_d1_close",
    "effective_fill_basis": "next_existing_same_physical_contract_d1_open",
    "allow_reverse": false
  },
  "exit": {
    "ordinary": "ema21_opposite_cross",
    "segment_terminal": "last_same_physical_contract_d1_close"
  }
}
```

**Contracts:**

```text
SUBING_DAILY_TREND_ID = subing_daily_trend_v1
Regime = data_unavailable | chop | trend_eligible
MacdCross = none | golden | dead
Position = flat | long | short
ActionKind = open_long | open_short | close_long | close_short
FillBasis = next_d1_open | segment_terminal_close
```

新增 frozen dataclass：`SubingDailyTrendFacts`、`SubingDailyTrendPendingAction`、`SubingDailyTrendAction`、`SubingDailyTrendCancellation`、`SubingDailyTrendEpisode`。价格、比率、gap、reference change 使用 `Decimal`。Action/Episode ID 对排序后的稳定 identity JSON 做 SHA-256，前缀固定 `subing-daily-trend-action:` / `subing-daily-trend-episode:`。

- [ ] **Step 1: 先写 policy drift 与 ID 测试**

逐字段篡改固定 policy，必须得到统一 typed policy error；相同 identity 必须生成相同 ID，修改 symbol、contract、segment、kind、decision/effective time 任一 identity 字段必须改变 ID。

- [ ] **Step 2: 运行测试并确认缺少模块/合同而失败**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py
```

- [ ] **Step 3: 用现有 `load_exact_json` 实现 policy loader 和 frozen contracts**

不得提供运行时可修改阈值的入口。

- [ ] **Step 4: 回归新合同与现行 SuBing strategy engine**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  data/research_policies/subing_daily_trend_v1.json \
  services/quant-api/app/market_data/subing_daily_trend \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py
git commit -m "feat(subing): freeze daily trend policy and contracts"
```

---

## Task 3: One stitched daily indicator stream

**Files:**
- Modify: `services/quant-api/app/market_data/subing_ema_trend.py`
- Modify: `services/quant-api/tests/test_subing_ema_trend.py`
- Create: `services/quant-api/app/market_data/subing_daily_trend/indicators.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_indicators.py`

**Produces:**
- `ema_regression_slope_bps(values: Sequence[Decimal]) -> Decimal`，公开现有 regression slope bps 数学，不改变现有 5/10-bar snapshot。
- `initial_subing_daily_trend_indicator_state(source_identity: str) -> SubingDailyTrendIndicatorState`。
- `reset_subing_daily_trend_segment(state: SubingDailyTrendIndicatorState) -> SubingDailyTrendIndicatorState`。
- `step_subing_daily_trend_indicators(state: SubingDailyTrendIndicatorState, bar: CanonicalBar) -> tuple[SubingDailyTrendIndicatorState, SubingDailyTrendFacts]`。

`SubingDailyTrendIndicatorState` 只保存：EMA21 state、最近 5 个 ready EMA21 Decimal、MACD state、上一组 ready DIF/DEA、ATR14 state、Range state 和 last bar timestamp。

**Facts algorithm:**

```text
Range point not-ready / invalid -> DATA_UNAVAILABLE
Range ready + active snapshot intact -> CHOP
Range ready + no active snapshot -> TREND_ELIGIBLE
Range ready + active snapshot broken_up/down -> TREND_ELIGIBLE

close > EMA21 -> ABOVE
close < EMA21 -> BELOW
close == EMA21 -> EQUAL

slope5 = existing EMA21 regression slope bps over last 5 ready EMA21 values
GOLDEN = previous_dif <= previous_dea and current_dif > current_dea
DEAD   = previous_dif >= previous_dea and current_dif < current_dea
near_zero_ratio = max(abs(current_dif), abs(current_dea)) / ATR14
ATR14 not-ready, invalid or <= 0 -> DATA_UNAVAILABLE
```

Segment reset必须保留 stitched EMA21、MACD、ATR14、Range ATR500 的 warm-up state，只调用 Task 1 helper 清空 Range segment-local regime。

- [ ] **Step 1: 先写失败测试**

锁定：现有 EMA slope parity、zero slope、close exactly EMA21、golden/dead equality boundary、near-zero `0.25` 接受而 `0.2500001` 拒绝、Range ready/no box 为 TREND_ELIGIBLE、intact Range 为 CHOP、segment reset 不清 EMA/MACD/ATR warm-up。

- [ ] **Step 2: 运行测试并确认新接口缺失**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py
```

- [ ] **Step 3: 实现 indicator stream**

只能调用 Quant Core `initial_ema_state/step_ema`、`initial_macd_state/step_macd`、`initial_atr_state/step_atr`、Range state/step/reset；不得复制 EMA、MACD、ATR 或 Range 公式。

- [ ] **Step 4: 运行 focused + kernel regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_ema_trend.py \
  services/quant-api/app/market_data/subing_daily_trend/indicators.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py
git commit -m "feat(subing): add daily trend indicator stream"
```

---

## Task 4: Single completed-D1 strategy machine

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_trend/machine.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_machine.py`

**Produces:**
- `initial_subing_daily_trend_machine(symbol: str, policy: SubingDailyTrendPolicy) -> SubingDailyTrendMachineState`。
- `step_subing_daily_trend_machine(state: SubingDailyTrendMachineState, bar: CanonicalBar, segment: ResolvedContractSegment) -> SubingDailyTrendMachineState`。

Machine state 只包含：symbol、policy、indicator state、current segment、segment bar count、position、pending action、current/open Episode、closed Episodes、Actions、cancellations、previous facts、last bar end。

**Per-Bar order is authoritative:**

```text
1 validate monotonic Bar + exactly-one physical segment ownership
2 on segment transition: require previous segment position/pending already terminal/canceled; preserve stitched indicators; reset Range regime and segment-local strategy state
3 apply previous pending action at current same-segment D1 open before reading current close facts
4 advance current completed-D1 indicators
5 if current Bar is authoritative segment terminal: close open position at current close with CONTRACT_SEGMENT_END; cancel pending open; prohibit new decision
6 else if LONG/SHORT: evaluate only EMA21 opposite-cross and create pending close for next same-segment D1 open
7 else FLAT: require segment_bar_count > 1, TREND_ELIGIBLE, EMA side/slope, near-zero golden/dead cross; create one pending open
8 store current facts as previous facts
```

Long predicate：`TREND_ELIGIBLE && ABOVE && slope5>0 && GOLDEN && zero_distance<=0.25`。Short 完全对称。

普通退出：LONG 仅 `previous_close >= previous_ema21 && current_close < current_ema21`；SHORT 仅反向条件。

- [ ] **Step 1: 先写 machine 失败测试**

至少独立覆盖：首个 segment D1 不入场、CHOP 阻断、ready/no box 允许检查入场、long/short、无 cross 不入场、错误 EMA side/slope 不入场、signal close 不作为 fill、pending 只在下一同合约 D1 open 生效、gap 不取消且记录、EMA-only exit、反向 MACD 不退出、Range 重新 intact 不退出、不同 Bar 不自动反手、terminal close precedence、不同 segment 不携带 position/pending、duplicate/stale input fail-closed。

- [ ] **Step 2: 运行并确认缺少 machine**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py
```

- [ ] **Step 3: 实现 pure machine**

`machine.py` 不允许 MarketDataService、filesystem、DB、HTTP、Alert 依赖。

- [ ] **Step 4: 联跑 Task 2–4**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_trend/machine.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py
git commit -m "feat(subing): add daily trend D1 state machine"
```

---

## Task 5: Deterministic rank1 Historical Projection

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_trend/replay.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_replay.py`

**Produces:** `replay_subing_daily_trend(symbol, bars, segments, policy) -> SubingDailyTrendHistoricalResult`。

Result 固定包含：strategy ID、symbol、source first/last day、source bar count、resolved segments、Actions、cancellations、open Episode、closed Episodes、final machine state。

Replay 开始前必须验证：bars 严格递增；每根 D1 Bar 被 exactly one `ResolvedContractSegment` 覆盖；segments 不重叠；segment contract 与 actual-dominant restored identity 一致。随后只循环调用 Task 4 machine，不增加第二套 batch 公式。

- [ ] **Step 1: 先写 replay invariance tests**

锁定：batch replay == 手工逐 Bar step；每个完整 warm-up 前缀与 full run 对应 Action prefix 一致；future tail 不改旧 Action/ref price；prepend 只补 warm-up、稳定前缀不漂移；`visual_start_at` 不提前产生 Action；segment reset 防止旧合约 box 压制新合约；Action/Episode 不跨段。

- [ ] **Step 2: 运行并确认 replay 缺失**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
```

- [ ] **Step 3: 实现 thin replay**

不得实现独立批量 entry/exit evaluator。

- [ ] **Step 4: 联跑 replay/machine/Range causality**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_trend/replay.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
git commit -m "feat(subing): add daily trend historical replay"
```

---

## Task 6: Read-only full-history loading and effect report

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_trend/report.py`
- Create: `services/quant-api/app/research/subing/subing_daily_trend_research_service.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_report.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_research_service.py`

**Request contract:** scope 仅 `representative | active`，through 为 exact trading day，`include_episodes` 默认 false。Representative 固定 `jm/ag/rb/eg`；Active 只读取 `active_products.txt`，不得偷换成 `operational_products.txt`。

**Earliest-history algorithm:**

```text
1 query_actual_dominant_recent_bars(symbol, D1, through, limit=2000)
2 while has_more_before: query_page(ACTUAL_DOMINANT, symbol, D1, before=next_before, limit=2000)
3 每一页必须严格向更早 next_before 前进，并实际增加更早 Bar；否则 fail-closed
4 记录最早 discovered trading_day
5 调现有 ActualDominantResearchSegmentLoader.load(symbol, (D1,), earliest, through) 一次
6 使用 loader 返回的 authoritative full bars + restored true segments 调 replay
```

不直接查询 Catalog 表，不直接读 Parquet，不自建第二个 Market reader。

**80/20 split:** 按 closed Episode 的 sorted unique entry trading day 切分；`cut=max(1,min(len(days)-1,int(len(days)*0.8)))`，`holdout_start=days[cut]`，同一 entry day 永不跨 split。少于两个 unique entry day 时 holdout 显式 unavailable。

**Metrics:** closed/open count、long/short、positive ratio、mean/median/q25/q75/min/max reference change、mean/median holding D1 bars、两类 exit count、entry gap abs/ATR14 distribution、按年份/方向、development/holdout。closed Episode `<30` 标 `INSUFFICIENT_SAMPLE`。Quantile 使用 Decimal 排序和线性插值，不转换 float。

- [ ] **Step 1: 先写 report 数学测试**

使用手算 Decimal Episode 锁定 mean/median/q25/q75、same-day split、sample status。

- [ ] **Step 2: 写 fake reader/service 测试**

锁定分页 progress、no-progress fail-closed、只读 D1/actual_dominant、representative 精确四品种、active universe、单产品失败隔离、无任何 write method 调用。

- [ ] **Step 3: 运行并确认模块缺失**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py
```

- [ ] **Step 4: 实现 report/service**

输出必须绑定 strategy ID、policy SHA-256、through、每产品 source first/last day、bar count、segment count；不写 cache 或文件。

- [ ] **Step 5: 联跑 report/research/replay**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
```

- [ ] **Step 6: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_trend/report.py \
  services/quant-api/app/research/subing/subing_daily_trend_research_service.py \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py
git commit -m "feat(subing): add daily trend research reporting"
```

---

## Task 7: One read-only research CLI

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/research/test_research_cli_parser_requests.py`
- Create: `services/quant-api/tests/research/test_subing_daily_trend_cli.py`
- Modify: `TESTING.md`

**CLI:**

```text
guiyi research subing-daily-trend --scope representative --through YYYY-MM-DD --include-episodes
guiyi research subing-daily-trend --scope active --through YYYY-MM-DD
```

`include-episodes` 只允许 representative；命令必须被 `_execution_is_readonly` 识别为只读；stdout 只返回 JSON，不发布 report cache/file。全部请求品种成功才 `passed`，部分产品失败返回 `degraded` + stable public code；不得输出 storage path、SQL、stack、token 或 env。

- [ ] **Step 1: 先写 parser/request/output 失败测试**

`RESEARCH_COMMAND_NAMES` 在现有三个命令后增加 `subing-daily-trend`。测试 representative/active request、invalid `include_episodes + active`、safe exception mapping、readonly flag、injected fake service payload。

- [ ] **Step 2: 运行并确认新 command 缺失**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_daily_trend_cli.py
```

- [ ] **Step 3: 实现 CLI/composition**

复用既有 MarketDataService composition，不构造第二套 data reader。

- [ ] **Step 4: 运行全部 Stage A focused tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_daily_trend_cli.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_requests.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_daily_trend_cli.py \
  TESTING.md
git commit -m "feat(cli): expose daily trend historical research"
```

---

## Task 8: Full verification, independent Review, Historical evidence Gate

### Part A — code verification

- [ ] **Step 1: Full non-isolated backend**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  -m "not isolated_postgresql" services/quant-api/tests
```

- [ ] **Step 2: Ruff + Mypy**

```bash
uv run --project services/quant-api --no-sync ruff check \
  packages/quant-core/guiyi_quant services/quant-api/app services/quant-api/tests
uv run --project services/quant-api --no-sync mypy \
  packages/quant-core/guiyi_quant services/quant-api/app
```

- [ ] **Step 3: Repository contract checks**

严格使用执行时 `TESTING.md` 中的 authoritative commands 运行适用 OpenSpec strict validation、canonical consistency、secret scan 和 `git diff --check`。不得自造替代命令后宣称通过。

- [ ] **Step 4: 创建/更新一个 Draft implementation PR to `develop`**

标题固定：`feat: add 苏冰趋势策略-日 Historical Projection`。正文记录真实命令/结果、strategy/policy identity、固定公式，并明确 Current/API/Web/Alert 未实现。

- [ ] **Step 5: 独立 Sol/high Review**

Reviewer 必须逐项检查：Range reset 保留 ATR500；ready/no active box 为 TREND_ELIGIBLE；intact Range 阻断；EMA21 side + 5-bar slope only；MACD near-zero cross 是唯一 entry trigger；next same-contract D1 open；EMA-only ordinary exit；segment terminal；deterministic IDs；batch/incremental、prefix、future-tail、prepend invariance；80/20 split；无 Current/API/Web/Alert/DB-write 扩张。

Review 只允许：`允许进入 Historical evidence run`、`要求修正后再 Review`、`阻塞`。

### Part B — real Historical effect run，单独 read-only Gate

- [ ] **Step 6: 向 owner 请求明确的只读环境与 exact through date**

获批后由 operator 明确设置：

```bash
export APPROVED_TRADING_DAY='YYYY-MM-DD'
python -c "from datetime import date; import os; date.fromisoformat(os.environ['APPROVED_TRADING_DAY'])"
```

第二行必须成功后才允许运行研究命令。该环境变量只能来自当次 owner 授权，不得从旧日志或默认值推断。

- [ ] **Step 7: 先跑 representative**

```bash
uv run --project services/quant-api --no-sync guiyi research subing-daily-trend \
  --scope representative \
  --through "$APPROVED_TRADING_DAY" \
  --include-episodes
```

先人工检查 JM/AG/RB/EG 的 Action/Episode 时序、segment、reference fill 和样本状态；结构不正确时停止，不跑 active60。

- [ ] **Step 8: representative 结构正确后才跑 active**

```bash
uv run --project services/quant-api --no-sync guiyi research subing-daily-trend \
  --scope active \
  --through "$APPROVED_TRADING_DAY"
```

- [ ] **Step 9: 写版本化 evidence**

在同一 implementation branch 新增 `docs/tasks/2026-08-31-subing-trend-daily-historical-evidence.md`，记录 code SHA、policy SHA-256、exact through date、两条实际命令、每产品 source window/bar/segment counts、JM/AG/RB/EG episode/sample status、active60 aggregate/product failures、development/holdout，以及“gross reference change，不是账户 PnL；不自动 promotion”。

- [ ] **Step 10: 停在 Historical Gate**

最高只能声明：

```text
CODE_COMPLETE
TEST_COMPLETE
HISTORICAL_REPORT_READY
```

用户读完 evidence 并明确决定继续之前，不实现 Current/API/Web/Alert。

## Plan Self-Review Result

- Spec Stage A 的 policy、指标、状态机、Historical、Action/Episode、代表品种、active60、80/20、因果测试均有对应 Task。
- 没有 Current/API/Web/Alert 实现任务。
- 没有 runtime-adjustable strategy threshold。
- `subing_strategy_v1` 不在修改清单中；只允许作为回归测试对象。
- Range segment reset 明确只清 regime-local state，ATR500 继续 stitched warm-up。
- Historical replay 与未来增量语义共享 Task 4 的唯一 step function。
- Research loader 只走 MarketDataService/public research loader seam。
- 报告统计保持 Decimal；同一 entry trading day 不跨 development/holdout。
- 真实 Historical 读取位于独立 owner Gate 之后。
- 本计划不授权 main/tag、Runtime、生产写入、Scope 或通知。
- 文档中不存在未解析的源码实现占位；Historical 日期通过 owner 批准后设置的受控环境变量进入命令。