# Newow 独立策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改苏冰、HTDY、Alert、Runtime、Canonical 或订单边界的前提下，交付独立的 Newow 牛哇策略产品族：`newow_trend_v1 @ newow_tf_1d_v1` 与 `newow_range_v1 @ newow_tf_15m_v1`，并完成纯 Kernel、同一增量状态机、Historical/Incremental 快照、只读 API、Market Web、形态 Gold Set 与 rolling/prospective OOS 验证链。

**Architecture:** Python/NumPy quant-core 是 Phase、Swing、Structure、Pattern、Target/Risk、Evidence 与 Execution 的唯一公式权威；FastAPI application 只通过 `MarketDataService` 解析 actual-dominant 物理合约段、同合约数值 warm-up、Historical fold、原子 snapshot 与只读查询；Web 只投影 typed API，不复制公式。趋势 D1 与震荡 15m 使用同一个 Newow-specific `step(completed_bar)` 引擎，但各有独立 Binding、Profile、状态机、Action、Episode、Snapshot 与 OOS 身份。

**Tech Stack:** Python 3.13、NumPy 2.4、frozen dataclasses、Decimal、FastAPI、Pydantic 2、SQLAlchemy Catalog read-only seams、pytest、mypy、ruff；Vue 3、TypeScript、Naive UI、Lightweight Charts、Node test runner、Playwright、pnpm；OpenSpec、Git worktree、GitHub Draft PR。

**Spec:**

- `docs/tasks/2026-08-31-newow-independent-strategy-spec.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-spec-review-amendments.md`

**Existing prerequisite plan:** `docs/tasks/2026-08-31-range-detector-lux-v1-implementation-plan.md`

**Issue:** `#265`

**Approved design:** PR `#263`, merge commit `6aad39299f2da6dca9db3d8bbae75fcb61e86989`

**Planning baseline:** `develop@6aad39299f2da6dca9db3d8bbae75fcb61e86989`

## Global Constraints

- Newow 与 `subing_strategy_v1`、SuBing Daily Context、SuBing Current、SuBing Action/Episode、SuBing Alert/Scope/Runtime 完全隔离；禁止从苏冰筛选、继承、改写或删除事实。
- V1 唯一正式 Binding 是 `newow_trend_v1 @ newow_tf_1d_v1` 与 `newow_range_v1 @ newow_tf_15m_v1`。趋势只消费 completed D1；震荡只消费 completed 15m；禁止 W1、D1→15m、5m、1m 或任何隐藏跨周期输入。
- `live_capable=false`、`alert_capable=false`、`auto_order=false`。实现不得接 Alert Rule、Scope、PushPlus、Redis Live evaluator、scheduler、真实通知或订单。
- Historical 唯一数据链是 `RQData -> staging validation -> Canonical Parquet -> Catalog + MainContractMap -> MarketDataService`。Newow 不得 glob、自选主力、读 continuous 代替 actual-dominant、跨频回退或从 Web bars 反算权威事实。
- 所有 Strategy/Swing/Pattern/Range/pending/Episode/outcome 状态按 rank1 真实物理合约段隔离；同合约跨 trading day 可以继续，物理合约变化必须 reset。
- 同合约成为 rank1 前的 Bar 只允许 warm EMA、ATR、MACD 与 rolling moments；Swing、Structure、Pattern、Range、Action、Episode 必须在 `effective_start_trading_day` 重置。
- `numeric_dtype=float64`、`numeric_epsilon=1e-12`、`published_round_digits=8`、价格与风险层级使用 `Decimal`；`sample_std` 固定 `ddof=1`。
- 当前 Bar open 应用上一 Bar pending Action 时，只能读取 current bar 的 contract、segment、frequency、trading_day、bar identity 与 open；严禁读取该 Bar 最终 high/low/close/volume/OI 或 ONE_PRICE_BAR 结果。
- 普通策略 OPEN/CLOSE 只在下一实际同物理合约 Bar open 形成 `REFERENCE_OPEN_ONLY_UNVERIFIED` 参考；换月段末使用 `NewowAdministrativeClosure`，不得伪造 Strategy CLOSE Action。
- 所有效果数据标记为 `gross / pre-cost / reference-only`；禁止资金曲线、年化收益、Sharpe、净收益、手数、保证金、手续费、滑点或“已证明盈利”结论。
- Historical、Incremental、Current 与未来 completed-Live 必须复用唯一 `NewowIncrementalEngine.step()`；不得另写向量化公式或浏览器简化公式。
- HTTP 只读已发布 snapshot；不得在请求路径 replay Historical、写 cache、修复 snapshot 或更改 Candidate/OOS authority。
- V1 不新增 Alembic migration，不写 production PostgreSQL、Redis、Canonical 或 RQData，不修改 `.env`，不执行 main/tag/release/Runtime promotion。
- causality、completed-only、strict-before、future-tail、prefix/append/prepend invariance、batch/incremental parity、restore parity、segment isolation、open-only parity、API/Web identity parity 与 fail-closed 测试不可删除。
- 每个执行任务从执行时最新 `origin/develop` 建独立 branch/worktree；每个任务一个 Draft PR、独立 Review、用户 Gate。任何任务合入 `develop` 都不构成 release、Runtime、Alert 或真实数据写入授权。

---

## Program Dependency Graph

```text
Task 0  superseded 文档清理 ───────────────────────────────────────────────┐
Task 1  range_detector_lux_v1 前置实现                                   │
                                  └── Task 2 contracts/profiles/policies  │
                                                ├── Task 3 Phase          │
                                                └── Task 4 Swing/Structure
                                                         └── Task 5 Pattern
Task 1 + Task 2 + Task 3 + Task 4 + Task 5 ── Task 6 Risk/Evidence/Execution
                                                   ├── Task 7 Trend D1
                                                   └── Task 8 Range 15m
Task 7 + Task 8 ── Task 9 Source/Historical ── Task 10 Snapshot/Tail/CLI
                                                    ├── Task 11 API
                                                    └── Task 13 Validation infra
Task 11 ── Task 12 Market Web
Task 13 ── Task 14 Gold Set + rolling/OOS report
Task 12 + Task 14 ── Task 15 canonical docs + independent acceptance review
```

Task 0 可以与 Task 1 并行。Task 3 与 Task 4 在 Task 2 后可以并行。Task 7 与 Task 8 在 Task 6 后可以并行。Task 11 与 Task 13 在 Task 10 的 snapshot schema 冻结后可以并行。

## Worktree and Review Protocol

每个任务开始时执行：

```bash
git fetch origin
git worktree add ../guiyi-newow-task-N -b feature/newow-task-N origin/develop
cd ../guiyi-newow-task-N
git branch --show-current
git status --short
git log -5 --oneline
```

预期：branch 名与当前任务一致、worktree clean、基线包含前置任务已批准的 merge commit。

每个任务的固定循环：

1. 写失败测试并记录预期失败原因；
2. 运行最小定向测试，确认测试确实失败；
3. 写最小实现；
4. 运行定向测试、相邻回归测试、静态检查；
5. 小步 commit；
6. push 并创建 Draft PR；
7. 独立 reviewer 先审公式/因果，再审工程边界；
8. 修复 blocking findings；
9. 用户明确批准后才合入 `develop`。

---

## Program File Map

### Quant-core authority

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── contracts.py
├── identity.py
├── profiles.py
├── numeric.py
├── phase.py
├── swing.py
├── structure.py
├── target_risk.py
├── evidence.py
├── execution.py
└── patterns/
    ├── __init__.py
    ├── models.py
    ├── geometry.py
    ├── lifecycle.py
    ├── channels.py
    ├── flags.py
    ├── double_patterns.py
    ├── head_shoulders.py
    ├── cup_handle.py
    └── candles.py
```

### Application and snapshot layer

```text
services/quant-api/app/market_data/newow/
├── __init__.py
├── bindings.py
├── contracts.py
├── source_segments.py
├── engine.py
├── trend_machine.py
├── range_machine.py
├── historical_service.py
├── current_service.py
├── overlay_projection.py
├── performance.py
├── snapshot.py
├── snapshot_store.py
├── snapshot_query.py
├── lineage.py
├── incremental.py
└── composition.py
```

### Research validation

```text
services/quant-api/app/research/newow/
├── __init__.py
├── candidate_authority.py
├── gold_set.py
├── pattern_validation.py
├── strategy_validation.py
├── reports.py
└── composition.py
```

### API and Web

```text
services/quant-api/app/api/market_newow.py
services/quant-api/app/schemas/newow_research.py

apps/quant-web/src/types/newow.ts
apps/quant-web/src/composables/useNewowDefinitions.ts
apps/quant-web/src/composables/useNewowOverlay.ts
apps/quant-web/src/composables/useNewowStrategyCurrent.ts
apps/quant-web/src/composables/useNewowStrategyPerformance.ts
apps/quant-web/src/components/market/NewowStrategySidebar.vue
apps/quant-web/src/components/market/NewowStrategyPerformancePanel.vue
apps/quant-web/src/components/kline/newowPatternPrimitive.ts
apps/quant-web/src/components/kline/newowStructurePrimitive.ts
apps/quant-web/src/utils/newowOverlayViewModel.ts
apps/quant-web/src/utils/newowMarkers.ts
```

### Immutable authorities and fixtures

```text
data/research_policies/newow/newow_tf_1d_v1.json
data/research_policies/newow/newow_tf_15m_v1.json
data/research_policies/newow/newow_strategy_bindings_v1.json
data/research_policies/newow/newow_kernel_bundle_v1.json

data/research_candidates/newow_pattern_newow_tf_1d_v1_candidate_v1.json
data/research_candidates/newow_pattern_newow_tf_15m_v1_candidate_v1.json
data/research_candidates/newow_trend_newow_tf_1d_v1_candidate_v1.json
data/research_candidates/newow_range_newow_tf_15m_v1_candidate_v1.json

data/research_protocols/newow_pattern_newow_tf_1d_v1_validation_v1.json
data/research_protocols/newow_pattern_newow_tf_15m_v1_validation_v1.json
data/research_protocols/newow_trend_newow_tf_1d_v1_validation_v1.json
data/research_protocols/newow_range_newow_tf_15m_v1_validation_v1.json

tests/fixtures/newow/
├── phase_v1_golden.json
├── swing_structure_v1_golden.json
├── pattern_v1_golden.json
├── execution_open_only_v1_golden.json
├── trend_d1_v1_golden.json
└── range_15m_v1_golden.json
```

Do not add a generic strategy adapter, generic opportunity DTO, account/order domain, DB result table, queue, scheduler, backtest worker or live evaluator.

---

## Task 0: Remove the Superseded Newow-to-SuBing Design Direction

**Deliverable:** 删除 PR #260 引入、现已无 active consumer 的两份旧研究设计，给 Issue #259 留下 superseded 记录并关闭；不修改任何苏冰代码或事实。

**Files:**

- Delete: `docs/tasks/2026-08-31-newow-layered-contribution-research-design.md`
- Delete: `docs/tasks/2026-08-31-newow-layered-contribution-research-review-amendments.md`
- Verify references in: `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/ARCHITECTURE.md`, `TESTING.md`, `openspec/`

**Interfaces:**

- Consumes: approved independent Newow Spec merge `6aad39299f2da6dca9db3d8bbae75fcb61e86989`.
- Produces: repository with no active documentation claiming Newow filters or inherits SuBing.

- [ ] **Step 1: Write the failing engineering assertion**

Add a temporary local assertion command before deletion:

```bash
test -f docs/tasks/2026-08-31-newow-layered-contribution-research-design.md
test -f docs/tasks/2026-08-31-newow-layered-contribution-research-review-amendments.md
```

Expected before cleanup: both commands succeed, proving the obsolete files still exist.

- [ ] **Step 2: Resolve every active reference before deletion**

```bash
git grep -n "newow-layered-contribution-research\|T0/T1/T2/T3\|R1/R2" -- ':!docs/tasks/2026-08-31-newow-layered-contribution-research-design.md' ':!docs/tasks/2026-08-31-newow-layered-contribution-research-review-amendments.md'
```

Expected: no active source, API, CLI, Web, Runtime, OpenSpec or canonical document depends on the old direction. Any result must be removed or rewritten in the same PR before deleting the files.

- [ ] **Step 3: Delete only the two obsolete files**

```bash
git rm \
  docs/tasks/2026-08-31-newow-layered-contribution-research-design.md \
  docs/tasks/2026-08-31-newow-layered-contribution-research-review-amendments.md
```

- [ ] **Step 4: Run documentation checks**

```bash
git diff --check
python3 scripts/engineering/secret_scan.py --json
```

Expected: zero formatting errors and zero secret findings.

- [ ] **Step 5: Commit and open the cleanup PR**

```bash
git commit -m "docs: remove superseded Newow to SuBing design"
```

The PR body must state that Git/Alembic history remains the lineage and no archive/legacy copy was created. After merge, comment on Issue #259 that PR #263 superseded it and close #259.

**Review Gate:** reviewer confirms the diff contains only documentation deletion/reference closure and no SuBing source change.

---

## Task 1: Complete the Independent `range_detector_lux_v1` Prerequisite

**Deliverable:** finish Issue #258 and its existing implementation plan before any Newow strategy machine consumes Range facts.

**Files:** use the exact file set in `docs/tasks/2026-08-31-range-detector-lux-v1-implementation-plan.md`.

**Interfaces:**

- Consumes: existing ATR/EMA indicator state APIs.
- Produces:

```text
initial_range_detector_lux_state(...)
step_range_detector_lux(...)
range_detector_lux_series(...)
RangeDetectorLuxParameters
RangeDetectorSnapshot
RangeDetectorVisualRange
RangeDetectorLuxState
RangeDetectorSeries
formal policy range_detector_lux_v1
```

**Required policy alignment before implementation:** because the approved independent Newow Spec post-dates the original #258 consumer list, the first #258 commit must add the named consumer `newow_historical` to `range_detector_lux_v1.allowed_consumers`. Retain any already-approved named SuBing research consumer; do not grant `generic_strategy`, formal generic backtest, live, alert or notification access. This is a consumer-boundary amendment only; Range formula, IDs, timing and golden outputs remain unchanged.

- [ ] **Step 1: Update Issue #258 and the Range plan consumer boundary**

The approved policy must resolve to:

```text
allowed:
  range_detector_readonly_display
  subing_daily_trend_research
  newow_historical

blocked:
  formal_backtest
  generic_strategy
  generic_live
  alert
  notification
```

- [ ] **Step 2: Execute Tasks 1 through 8 of the existing Range plan with TDD**

Do not copy Range calculation into `guiyi_quant.newow`. Newow later imports the Python authority.

- [ ] **Step 3: Add a named-consumer policy test**

```python
def test_range_detector_policy_allows_newow_historical_only_by_name() -> None:
    policy = require_formal_policy(
        "range_detector_lux_v1",
        consumer="newow_historical",
    )
    assert policy.confirmed_only is True
    for blocked in ("generic_strategy", "generic_live", "alert", "notification"):
        with pytest.raises(ValueError):
            require_formal_policy("range_detector_lux_v1", consumer=blocked)
```

- [ ] **Step 4: Run the prerequisite verification suite**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py
pnpm -C apps/quant-web test
pnpm -C apps/quant-web build
openspec validate --specs --strict --no-interactive
git diff --check
```

- [ ] **Step 5: Independent formula review and merge Gate**

Reviewer must inspect candidate indexing, `visual_start_at` versus `confirmed_at`, overlap revision, exact boundaries, invalid reset, prefix/future-tail tests and policy consumers. Newow Task 2 cannot start until #258 is merged into `develop`.

---

## Task 2: Freeze Newow Contracts, Profiles, Kernel Bundle and Indicator Policies

**Deliverable:** create immutable Newow domain types and application loaders for the two exact Profiles/Bindings, with digest-pinned policy files and Newow-only indicator consumers.

**Files:**

- Create: `packages/quant-core/guiyi_quant/newow/__init__.py`
- Create: `packages/quant-core/guiyi_quant/newow/contracts.py`
- Create: `packages/quant-core/guiyi_quant/newow/identity.py`
- Create: `packages/quant-core/guiyi_quant/newow/profiles.py`
- Create: `packages/quant-core/guiyi_quant/newow/numeric.py`
- Create: `services/quant-api/app/market_data/newow/__init__.py`
- Create: `services/quant-api/app/market_data/newow/bindings.py`
- Create: four JSON files under `data/research_policies/newow/`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test: `services/quant-api/tests/newow/test_newow_contracts.py`
- Test: `services/quant-api/tests/newow/test_newow_profiles.py`
- Test: `services/quant-api/tests/newow/test_newow_indicator_policies.py`

**Interfaces:**

```text
NewowCompletedBar
NewowKernelEnvelope
NewowTimeframeProfile
NewowStrategyFrequencyBinding
NewowKernelBundleIdentity
NewowSourceIdentity
NewowUnavailableReason
load_newow_authority() -> NewowAuthority
strategy_instance_id(binding, profile, bundle) -> str
rounded_decimal(value: float) -> Decimal
```

`NewowCompletedBar` fields are fixed:

```text
product
contract
segment_id
frequency
trading_day
bar_start
bar_end
open
high
low
close
volume
turnover
open_interest
source_identity
```

Profiles must encode the exact approved parameters, including D1 Range ATR 100 and 15m Range ATR 500. Bindings must reject any frequency/series pair other than `actual_dominant + 1d` for trend and `actual_dominant + 15m` for range.

- [ ] **Step 1: Write exact-key and digest-drift tests first**

```python
def test_only_two_v1_bindings_are_loadable() -> None:
    authority = load_newow_authority()
    assert tuple(binding.strategy_code for binding in authority.bindings) == (
        "newow_trend_v1",
        "newow_range_v1",
    )
    trend, range_strategy = authority.bindings
    assert (trend.profile_id, trend.frequency.value) == ("newow_tf_1d_v1", "1d")
    assert (range_strategy.profile_id, range_strategy.frequency.value) == (
        "newow_tf_15m_v1",
        "15m",
    )
    assert trend.live_capable is False and trend.alert_capable is False
    assert range_strategy.live_capable is False and range_strategy.alert_capable is False
```

```python
def test_same_policy_id_with_changed_raw_bytes_fails_closed(tmp_path: Path) -> None:
    copied = copy_newow_authority_files(tmp_path)
    profile_path = copied / "newow_tf_1d_v1.json"
    profile_path.write_text(profile_path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(NewowAuthorityError, match="NEWOW_PROFILE_INVALID"):
        load_newow_authority(root=copied)
```

- [ ] **Step 2: Run tests and confirm import/file failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_contracts.py \
  services/quant-api/tests/newow/test_newow_profiles.py \
  services/quant-api/tests/newow/test_newow_indicator_policies.py
```

Expected initial failure: `guiyi_quant.newow` and Newow authority files do not exist.

- [ ] **Step 3: Implement immutable types and JSON loaders**

Rules:

```text
exact JSON keys only
raw-byte SHA-256 pin
profile.parameters_hash recomputed from canonical business fields
kernel bundle digest includes every consumed kernel version
strategy_instance_id includes binding, profile, source policy, indicator policy and kernel bundle digest
all dataclasses frozen=True, slots=True
published Decimal constructed from Decimal(str(round(float_value, 8)))
```

- [ ] **Step 4: Add exactly three Newow formal policies**

```text
newow_ema_sma_window_v1
  allowed: newow_historical, newow_research
  blocked: live, alert, notification, web_formula

newow_atr_wilder_sma_seed_v1
  allowed: newow_historical, newow_research
  blocked: live, alert, notification, web_formula

newow_macd_sma_window_scale1_v1
  allowed: newow_historical, newow_research
  blocked: live, alert, notification, web_formula
```

Do not broaden existing EMA/MACD/ATR policies.

- [ ] **Step 5: Run targeted and existing indicator regression tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

- [ ] **Step 6: Commit and open the contracts PR**

```bash
git add packages/quant-core/guiyi_quant/newow \
  packages/quant-core/guiyi_quant/indicators/policy.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/app/market_data/newow \
  services/quant-api/tests/newow \
  data/research_policies/newow
git commit -m "feat(newow): freeze contracts profiles and policies"
```

**Review Gate:** exact profile values, raw-byte drift, kernel bundle identity, no period-specific branch in algorithms, Newow-only policy consumers, no SuBing import.

---

## Task 3: Implement the Phase Moments Kernel

**Deliverable:** a pure incremental Phase kernel with exact skew/kurtosis, ER, realized-volatility ratio, deviation, progress, volume and OI availability semantics.

**Files:**

- Create: `packages/quant-core/guiyi_quant/newow/phase.py`
- Modify: `packages/quant-core/guiyi_quant/newow/contracts.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`
- Create: `tests/fixtures/newow/phase_v1_golden.json`
- Test: `services/quant-api/tests/newow/test_newow_phase.py`

**Interfaces:**

```text
NewowPhaseState
NewowPhaseInputs
NewowPhaseSnapshot
initial_newow_phase_state(profile) -> NewowPhaseState
step_newow_phase(state, bar, indicators) -> (NewowPhaseState, NewowPhaseSnapshot)
```

State names are exactly the neutral names from the Spec. API authority never emits proprietary-intent claims.

- [ ] **Step 1: Write formula golden tests**

```python
def test_phase_moments_match_hand_calculated_sample() -> None:
    state = initial_newow_phase_state(profile_1d())
    snapshots = []
    for bar in deterministic_phase_bars():
        state, snapshot = step_newow_phase(state, bar, deterministic_indicators(bar))
        snapshots.append(snapshot)
    ready = snapshots[-1]
    assert ready.ready is True
    assert ready.skew == pytest.approx(-0.21129447, abs=1e-8)
    assert ready.excess_kurtosis == pytest.approx(-0.82411621, abs=1e-8)
    assert ready.er20 == pytest.approx(0.48762341, abs=1e-8)
```

The fixture generator must use reviewed fixed closes and commit exact expected values plus canonical payload hash.

- [ ] **Step 2: Add boundary tests**

Required cases:

```text
ATR <= 1e-12 -> ATR_NORMALIZATION_UNAVAILABLE
m2 <= 1e-12 -> MOMENTS_UNAVAILABLE
ER denominator <= 1e-12 -> ER20 == 0
RV40 and RV10 <= 1e-12 -> VolatilityRatio == 0
RV40 <= 1e-12 and RV10 > 1e-12 -> VOLATILITY_RATIO_UNAVAILABLE
previous volume median <= 0 -> VOLUME_RATIO_UNAVAILABLE
previous OI missing or <= 0 -> OI_DELTA_UNAVAILABLE
segment change -> all rolling windows reset
```

- [ ] **Step 3: Add batch/incremental and future-tail tests**

```python
def test_phase_prefix_is_unchanged_by_future_tail() -> None:
    base = fold_phase(deterministic_phase_bars())
    changed = fold_phase((*deterministic_phase_bars()[:70], *extreme_future_bars()))
    assert changed[:70] == base[:70]
```

- [ ] **Step 4: Run failing tests, implement minimal state, rerun**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_phase.py
```

- [ ] **Step 5: Verify fixture hash and commit**

```bash
git add packages/quant-core/guiyi_quant/newow/phase.py \
  packages/quant-core/guiyi_quant/newow/contracts.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/test_newow_phase.py \
  tests/fixtures/newow/phase_v1_golden.json
git commit -m "feat(newow): add causal phase moments kernel"
```

**Review Gate:** reviewer recomputes one skew/kurtosis sample independently and checks `ddof=1`, epsilon branches, OI null handling, segment reset and no pandas/SciPy defaults.

---

## Task 4: Implement Causal Swing and Structure Graph

**Deliverable:** independent minor/major reversal-distance Swing machines and deterministic HH/HL/LH/LL, EQH/EQL, BOS/CHOCH, support/resistance Zone projection.

**Files:**

- Create: `packages/quant-core/guiyi_quant/newow/swing.py`
- Create: `packages/quant-core/guiyi_quant/newow/structure.py`
- Modify: `packages/quant-core/guiyi_quant/newow/contracts.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`
- Create: `tests/fixtures/newow/swing_structure_v1_golden.json`
- Test: `services/quant-api/tests/newow/test_newow_swing.py`
- Test: `services/quant-api/tests/newow/test_newow_structure.py`

**Interfaces:**

```text
NewowSwingState
NewowSwingPoint
NewowStructureState
NewowStructureSnapshot
initial_newow_swing_state(scale, reversal_atr, min_leg_bars) -> NewowSwingState
step_newow_swing(state, bar, atr) -> (NewowSwingState, NewowSwingPoint | None)
initial_newow_structure_state(segment_id) -> NewowStructureState
step_newow_structure(state, confirmed_swings, bar, atr) -> (NewowStructureState, NewowStructureSnapshot)
```

- [ ] **Step 1: Write pivot-time versus confirmation-time tests**

```python
def test_swing_high_is_visible_only_on_reversal_confirmation_bar() -> None:
    state = initial_newow_swing_state("MINOR", Decimal("1.0"), 3)
    emitted = []
    for bar, atr in swing_high_fixture():
        state, point = step_newow_swing(state, bar, atr)
        emitted.append(point)
    point = next(item for item in emitted if item is not None)
    assert point.pivot_at == fixture_time("2026-01-05T07:00:00Z")
    assert point.confirmed_at == fixture_time("2026-01-08T07:00:00Z")
    assert all(item is None for item in emitted[:7])
```

- [ ] **Step 2: Add minor/major independence and exact tolerance tests**

Assert `equal_tolerance = 0.35 * max(ATR_current, ATR_previous)`, alternate high/low identity, minimum leg bars, and no forming extreme in Structure.

- [ ] **Step 3: Add BOS/CHOCH strict completed-close tests**

```python
def test_bos_requires_completed_close_beyond_buffer() -> None:
    before = structure_with_last_major_high(Decimal("100"), atr=Decimal("10"))
    equal_boundary = completed_bar(close=Decimal("101"), high=Decimal("105"))
    _, snapshot = step_newow_structure(before, (), equal_boundary, Decimal("10"))
    assert snapshot.last_bos is None
    beyond = completed_bar(close=Decimal("101.01"), high=Decimal("105"))
    _, snapshot = step_newow_structure(before, (), beyond, Decimal("10"))
    assert snapshot.last_bos.direction == "UP"
```

- [ ] **Step 4: Add Zone weighted-median tests and segment reset tests**

Verify major weight 2, minor weight 1, distance `<=0.50 ATR`, half-width `0.25 * median_ATR`, and no cross-segment node.

- [ ] **Step 5: Run tests, implement, and verify prefix parity**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_swing.py \
  services/quant-api/tests/newow/test_newow_structure.py
```

- [ ] **Step 6: Commit**

```bash
git add packages/quant-core/guiyi_quant/newow/swing.py \
  packages/quant-core/guiyi_quant/newow/structure.py \
  packages/quant-core/guiyi_quant/newow/contracts.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/test_newow_swing.py \
  services/quant-api/tests/newow/test_newow_structure.py \
  tests/fixtures/newow/swing_structure_v1_golden.json
git commit -m "feat(newow): add causal swing and structure graph"
```

**Review Gate:** anti-backpaint, exact buffer comparison, confirmed-only nodes, independent scales, deterministic IDs and segment isolation.

---

## Task 5: Implement Deterministic Pattern Geometry and Lifecycle

**Deliverable:** deterministic candidate enumeration, geometry, primary visual/action selection, lifecycle and contextual candle confirmation for all V1 pattern families.

**Files:** create all files under `packages/quant-core/guiyi_quant/newow/patterns/`, update exports/contracts, add tests below.

- Test: `services/quant-api/tests/newow/test_newow_pattern_geometry.py`
- Test: `services/quant-api/tests/newow/test_newow_pattern_families.py`
- Test: `services/quant-api/tests/newow/test_newow_pattern_lifecycle.py`
- Test: `services/quant-api/tests/newow/test_newow_candle_context.py`
- Create: `tests/fixtures/newow/pattern_v1_golden.json`

**Interfaces:**

```text
NewowPatternState
NewowPatternCandidate
NewowPatternRevision
NewowPatternSet
NewowCandleConfirmation
enumerate_newow_patterns(swings, structure, phase, profile) -> NewowPatternSet
select_primary_visual_pattern(candidates) -> NewowPatternCandidate | None
select_primary_action_pattern(candidates) -> NewowPatternCandidate | None
step_newow_pattern_lifecycle(state, bar, context) -> (NewowPatternState, tuple[NewowPatternTransition, ...])
```

- [ ] **Step 1: Write deterministic suffix enumeration tests**

Channel candidates must use every alternating contiguous suffix of length 4 through 12 ending at the newest confirmed Swing; fixed skeletons use the most recent consecutive 3 or 5 major Swings; no skipped Pivot may improve fit.

```python
def test_channel_enumerator_never_skips_an_interior_swing() -> None:
    result = enumerate_newow_patterns(
        swings=alternating_swings_with_one_bad_interior_node(),
        structure=range_structure(),
        phase=balanced_phase(),
        profile=profile_15m(),
    )
    assert all(candidate.major_swing_ids != skipped_interior_solution_ids() for candidate in result.candidates)
```

- [ ] **Step 2: Add geometry positive/negative fixtures**

Cover rectangle, symmetric/ascending/descending triangle, bull/bear flag, rising/falling wedge, double top/bottom, head-and-shoulders top/bottom, reversal wedge. D1 cup-handle is visual/research-only; 15m cup-handle is unavailable. Explicitly reject triple top/bottom, rounded, diamond, bat and wave-count requests.

- [ ] **Step 3: Add weighted regression and hard-condition tests**

Verify per-side touches, `touch_error<=0.35 ATR`, `RMSE_ATR<=0.35`, height `>=1.50 ATR`, boundary non-crossing, fixed slope thresholds, flag impulse `>=3 ATR`, and quality thresholds 70/80.

- [ ] **Step 4: Add identity and primary ordering tests**

```python
def test_primary_action_excludes_visual_only_cup_handle() -> None:
    candidates = (confirmed_cup_handle(quality=95), confirmed_rectangle(quality=80))
    assert select_primary_visual_pattern(candidates).family == "CUP_HANDLE"
    assert select_primary_action_pattern(candidates).family == "RECTANGLE"
```

Ordering is exactly hard-valid, quality, specificity, earliest confirmed time, pattern ID, revision.

- [ ] **Step 5: Add strict-before lifecycle tests**

A Bar may confirm a Pattern for display, but the same Bar cannot consume it for `BREAKOUT_A`. A, 3-Bar validation and B rebreak must have distinct immutable timestamps. Future append may add revisions/events but may not alter old confirmed identity.

- [ ] **Step 6: Add contextual candle tests**

Hammer, shooting star, engulfing, morning/evening star, white/black soldiers are valid only within `0.35 ATR` of support/resistance, Range edge or retest level. They never generate Action alone.

- [ ] **Step 7: Run tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_pattern_geometry.py \
  services/quant-api/tests/newow/test_newow_pattern_families.py \
  services/quant-api/tests/newow/test_newow_pattern_lifecycle.py \
  services/quant-api/tests/newow/test_newow_candle_context.py
```

```bash
git add packages/quant-core/guiyi_quant/newow/patterns \
  packages/quant-core/guiyi_quant/newow/contracts.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/test_newow_pattern_*.py \
  services/quant-api/tests/newow/test_newow_candle_context.py \
  tests/fixtures/newow/pattern_v1_golden.json
git commit -m "feat(newow): add deterministic pattern kernel"
```

**Formula Checkpoint:** a fresh reviewer must independently inspect suffix enumeration, fixed skeletons, WLS normalization, all family thresholds, primary ordering, `pivot_at/visual_start_at/confirmed_at`, revision identity and anti-backpaint before Task 6.

---

## Task 6: Implement Target/Risk, Evidence, Execution and the Newow Incremental Engine

**Deliverable:** deterministic Decimal risk plans, same-identity evidence fusion, open-only pending application, milestone/episode accounting, serializable state and one Newow-specific orchestration engine.

**Files:**

- Create: `packages/quant-core/guiyi_quant/newow/target_risk.py`
- Create: `packages/quant-core/guiyi_quant/newow/evidence.py`
- Create: `packages/quant-core/guiyi_quant/newow/execution.py`
- Create: `services/quant-api/app/market_data/newow/contracts.py`
- Create: `services/quant-api/app/market_data/newow/engine.py`
- Modify: Newow exports
- Create: `tests/fixtures/newow/execution_open_only_v1_golden.json`
- Test: `services/quant-api/tests/newow/test_newow_target_risk.py`
- Test: `services/quant-api/tests/newow/test_newow_evidence.py`
- Test: `services/quant-api/tests/newow/test_newow_execution.py`
- Test: `services/quant-api/tests/newow/test_newow_engine_parity.py`

**Interfaces:**

```text
NewowRiskPlan
NewowEvidenceSnapshot
NewowExecutionState
NewowPendingAction
NewowStrategyAction
NewowStrategyMilestone
NewowEpisode
NewowAdministrativeClosure
NewowEngineState
NewowStepContext
NewowStepResult
build_newow_risk_plan(setup, pattern_or_range, atr, profile) -> NewowRiskPlan
fuse_newow_evidence(inputs) -> NewowEvidenceSnapshot
NewowIncrementalEngine.initial_state(segment, profile, binding) -> NewowEngineState
NewowIncrementalEngine.step(state, completed_bar) -> (NewowEngineState, NewowStepResult)
```

The internal machine seam is Newow-only and exposes two named implementations later: `NewowTrendMachine` and `NewowRangeMachine`. It must not become a repository-wide UniversalStrategyAdapter.

- [ ] **Step 1: Write exact Decimal risk tests**

Verify pattern targets, range edge targets, structural invalidation, RR, positive initial risk and `Decimal(str(round(value, 8)))` conversion. Zero/negative risk fails closed.

- [ ] **Step 2: Write evidence identity tests**

Every input must match product, contract, segment, frequency, profile and source bar end. One mismatch yields `EVIDENCE_IDENTITY_MISMATCH`; no partial score is returned.

- [ ] **Step 3: Write open-only causality fixture**

```python
def test_pending_open_uses_only_open_time_fields() -> None:
    state = state_with_pending_open()
    first = completed_bar(open="100", high="110", low="90", close="105", volume=1000, oi=500)
    second = completed_bar(open="100", high="1000", low="1", close="2", volume=0, oi=None)
    next_a, result_a = engine().step(state, first)
    next_b, result_b = engine().step(state, second)
    assert result_a.applied_action == result_b.applied_action
    assert next_a.active_episode.entry_action == next_b.active_episode.entry_action
```

Current-Bar completion diagnostics may differ, but applied Action identity/reference must be identical.

- [ ] **Step 4: Add execution ordering and one-action-per-Bar tests**

Processing order is fixed: apply old pending at open, compute completed-Bar kernels, evaluate active exit, update milestones, evaluate new entry only when FLAT, freeze snapshot/state. No same-Bar reversal, re-entry or confirm-and-fill.

- [ ] **Step 5: Add B milestone and administrative closure tests**

B updates milestone/reference diagnostics only; it never creates a second OPEN. Segment closure sets `Episode.exit_action=None` and attaches `NewowAdministrativeClosure(reference_basis="segment_terminal_close_non_executable")`.

- [ ] **Step 6: Add target/profit-floor and MFE/MAE timing tests**

Target hit is confirmed from completed high/low; new profit floor applies from the next Bar. Entry reference Bar counts in MFE/MAE; exit reference Bar does not.

- [ ] **Step 7: Add state serialization/restore parity**

Serialize canonical JSON, parse it, continue at multiple cut points, and assert byte-stable state digest plus identical StepResult sequence.

- [ ] **Step 8: Run tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_target_risk.py \
  services/quant-api/tests/newow/test_newow_evidence.py \
  services/quant-api/tests/newow/test_newow_execution.py \
  services/quant-api/tests/newow/test_newow_engine_parity.py
```

```bash
git add packages/quant-core/guiyi_quant/newow/target_risk.py \
  packages/quant-core/guiyi_quant/newow/evidence.py \
  packages/quant-core/guiyi_quant/newow/execution.py \
  services/quant-api/app/market_data/newow/contracts.py \
  services/quant-api/app/market_data/newow/engine.py \
  services/quant-api/tests/newow \
  tests/fixtures/newow/execution_open_only_v1_golden.json
git commit -m "feat(newow): add risk evidence and execution engine"
```

**Review Gate:** open-only proof, no second B entry, exit precedence, state digest, administrative closure, gross-reference terminology and no order/account types.

---

## Task 7: Implement `newow_trend_v1 @ newow_tf_1d_v1`

**Deliverable:** completed-D1 trend band, Setup/Gate/state machine, A validation, B milestone, holding and exit rules.

**Files:**

- Create: `services/quant-api/app/market_data/newow/trend_machine.py`
- Modify: `services/quant-api/app/market_data/newow/engine.py`
- Create: `tests/fixtures/newow/trend_d1_v1_golden.json`
- Test: `services/quant-api/tests/newow/test_newow_trend_machine.py`
- Test: `services/quant-api/tests/newow/test_newow_trend_causality.py`

**Interfaces:**

```text
NewowTrendMachineState
NewowTrendDecision
NewowTrendMachine.initial_state(binding, profile, segment) -> NewowTrendMachineState
NewowTrendMachine.step(state, NewowStepContext) -> (NewowTrendMachineState, NewowTrendDecision)
```

States follow the amendment:

```text
CASH
SETUP_ARMED
ENTRY_A_PENDING
ACTIVE_A
BREAKOUT_VALIDATION
RETEST_WAIT
RETEST_CONFIRMING
ACTIVE_CONFIRMED
EXIT_PENDING
CLOSED
```

- [ ] **Step 1: Write exact trend-band tests**

Assert spread/slope/close thresholds, NEUTRAL behavior, and `flip_count_20 > 3` chop blocker. Equal boundaries remain NEUTRAL where the approved inequalities do not pass.

- [ ] **Step 2: Write MACD and participation tests**

Use 12/26/9 SMA seed, histogram scale 1, near-zero threshold `<=0.25 ATR`, transition cross within 3 Bars, continuation histogram growth, volume/OI availability fail-closed.

- [ ] **Step 3: Parameterize every approved Gate as a named failing case**

The test matrix must independently fail Band, EMA side, slope, Structure, reverse BOS, Phase, chop, distance, Evidence 70, Setup, Risk, RR 2.0, participation, FLAT, cooldown and signal-Bar marketability.

- [ ] **Step 4: Write A/B/exit lifecycle tests**

A validation uses 3 completed D1 Bars and frozen boundary; B requires positive MFE, retest tolerance, rebreak, MACD continuation and VolumeRatio; B only emits `B_RETEST_CONFIRMED`. Verify exit precedence and next-open pending close.

- [ ] **Step 5: Add strict D1 binding rejection**

```python
def test_trend_machine_rejects_non_d1_context() -> None:
    with pytest.raises(NewowBindingError, match="NEWOW_BINDING_UNSUPPORTED"):
        NewowTrendMachine(binding=trend_binding(), profile=profile_15m())
```

- [ ] **Step 6: Run golden, prefix and append parity tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_trend_machine.py \
  services/quant-api/tests/newow/test_newow_trend_causality.py \
  services/quant-api/tests/newow/test_newow_engine_parity.py
```

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/market_data/newow/trend_machine.py \
  services/quant-api/app/market_data/newow/engine.py \
  services/quant-api/tests/newow/test_newow_trend_*.py \
  tests/fixtures/newow/trend_d1_v1_golden.json
git commit -m "feat(newow): add completed D1 trend strategy machine"
```

**Review Gate:** strict D1 only, no lower-period inputs, exact band/MACD/Gate formulas, B milestone only, next-open timing and no SuBing import.

---

## Task 8: Implement `newow_range_v1 @ newow_tf_15m_v1`

**Deliverable:** completed-15m directional-range bias, edge arming, two-of-three confirmation, one-use range revision, risk and exit machine.

**Files:**

- Create: `services/quant-api/app/market_data/newow/range_machine.py`
- Modify: `services/quant-api/app/market_data/newow/engine.py`
- Create: `tests/fixtures/newow/range_15m_v1_golden.json`
- Test: `services/quant-api/tests/newow/test_newow_range_machine.py`
- Test: `services/quant-api/tests/newow/test_newow_range_causality.py`

**Interfaces:**

```text
NewowRangeMachineState
NewowRangeBias
NewowRangeDecision
NewowRangeMachine.initial_state(binding, profile, segment) -> NewowRangeMachineState
NewowRangeMachine.step(state, NewowStepContext) -> (NewowRangeMachineState, NewowRangeDecision)
```

- [ ] **Step 1: Write Range authority strict-before tests**

The machine imports `RangeDetectorSnapshot` from `guiyi_quant.indicators`. A Range confirmed/revised on Bar t is displayable at t but first strategy-visible on a later Bar where `confirmed_at < source_bar_end`.

- [ ] **Step 2: Write frozen bias tests**

At each new `range_id + revision`, use exact same-period two-of-three votes: EMA21 5-Bar slope, pre-range displacement, Structure. Bias remains frozen inside the revision and does not follow EMA crossings.

- [ ] **Step 3: Write position/width/edge tests**

Verify LOWER 0–0.35, MIDDLE 0.35–0.65, UPPER 0.65–1; width 1.50–6.00 ATR; neutral Range display-only; RANGE_UP long only at lower edge; RANGE_DOWN short only at upper edge.

- [ ] **Step 4: Write two-stage confirmation tests**

Armed lasts 5 Bars and needs one extreme condition. Entry confirmation requires at least two of rejection-close, Phase contraction, context-valid candle, plus previous-close, Evidence 65, Risk, RR 1.50 and signal-Bar marketability.

- [ ] **Step 5: Write one-Episode-per-revision tests**

Consumed key is `(range_id, revision, direction)`. Exit cannot re-arm the same key. Active Episode retains frozen boundaries after a later Range revision.

- [ ] **Step 6: Write resolution and exit tests**

Test structural invalidation, opposite range break, opposite BOS, resolution with trend, opposite edge reached and time stop. Range resolution never creates a 15m trend Episode and is invisible to D1 trend state.

- [ ] **Step 7: Reject non-15m context and run parity tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_range_machine.py \
  services/quant-api/tests/newow/test_newow_range_causality.py \
  services/quant-api/tests/newow/test_newow_engine_parity.py
```

- [ ] **Step 8: Commit**

```bash
git add services/quant-api/app/market_data/newow/range_machine.py \
  services/quant-api/app/market_data/newow/engine.py \
  services/quant-api/tests/newow/test_newow_range_*.py \
  tests/fixtures/newow/range_15m_v1_golden.json
git commit -m "feat(newow): add completed 15m range strategy machine"
```

**Review Gate:** strict 15m only, Range strict-before, frozen bias, one-use revision, no hidden D1/5m input, no 15m trend creation.

---

## Task 9: Implement Physical Segments, Same-Contract Warm-up and Historical Projection

**Deliverable:** MarketDataService-only Historical loader that freezes rank1 physical segments, obtains same-contract numeric warm-up, constructs authoritative session/bar identities and folds the same engine per segment.

**Files:**

- Create: `services/quant-api/app/market_data/newow/source_segments.py`
- Create: `services/quant-api/app/market_data/newow/historical_service.py`
- Create: `services/quant-api/app/market_data/newow/overlay_projection.py`
- Create: `services/quant-api/app/market_data/newow/composition.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Test: `services/quant-api/tests/newow/test_newow_source_segments.py`
- Test: `services/quant-api/tests/newow/test_newow_historical_service.py`
- Test: `services/quant-api/tests/newow/test_newow_historical_causality.py`
- Test: `services/quant-api/tests/newow/test_newow_strategy_isolation.py`

**Interfaces:**

```text
NewowHistoricalRequest
NewowSourceSegment
NewowSegmentSummary
NewowHistoricalProjection
NewowHistoricalProjectionService.history(request) -> NewowHistoricalProjection
NewowOverlayProjection
```

`NewowSourceSegment` includes mapping policy/date/source/observed-at/availability status. The application may wrap `ActualDominantResearchSegmentLoader` but may not alter MainContractMap owner selection.

- [ ] **Step 1: Write exact request/binding tests**

Client request accepts strategy code, profile ID, symbol, since and through. Series kind/frequency come only from Binding; conflicting public values are not accepted.

- [ ] **Step 2: Write actual-dominant parity tests**

For each test trading day, Newow segment owner must equal `MarketDataService` owner. Missing Calendar, Session, mapping, partition or contract metadata maps to stable Newow errors without shortening the window.

- [ ] **Step 3: Write same-contract warm-up tests**

Use `ContractTradingDayQuery`, enforce `[listed_date, expired_date)`, warm numeric indicators only, emit no structural event before rank1 effective start, and block entry for exact cooldown Bars.

- [ ] **Step 4: Write night/session identity tests**

15m `bar_start` and next-bar relation derive from TradingSession buckets; no fixed clock arithmetic. Friday night assigned to Monday trading_day remains in the same segment when contract is unchanged.

- [ ] **Step 5: Write segment terminal tests**

No next same-contract open means pending Action is not adopted from the incoming contract. Active Episode receives non-executable administrative closure; pending ordinary close is cancelled.

- [ ] **Step 6: Write full-run prefix/append/prepend tests**

```python
def test_historical_projection_matches_every_prefix() -> None:
    full = service().history(request_through(last_day()))
    for through in all_days_after_warmup():
        prefix = service().history(request_through(through))
        assert prefix_identity_slice(prefix) == prefix_identity_slice(full, through=through)
```

Prepending same-contract numeric warm-up may only turn prior unavailable numeric points ready; it may not change already-ready structural/action prefixes.

- [ ] **Step 7: Write explicit SuBing isolation test**

Run SuBing and Newow for the same symbol; assert module imports, IDs, state files and outputs share no Strategy/Action/Episode identity and neither service receives the other projection.

- [ ] **Step 8: Run targeted suite and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_source_segments.py \
  services/quant-api/tests/newow/test_newow_historical_service.py \
  services/quant-api/tests/newow/test_newow_historical_causality.py \
  services/quant-api/tests/newow/test_newow_strategy_isolation.py
```

```bash
git add services/quant-api/app/market_data/newow \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/newow
git commit -m "feat(newow): add physical segment historical projection"
```

**Review Gate:** MarketDataService only, no owner inference, no fixed session clock, no cross-contract fill, warm-up boundary, administrative closure and full historical/step parity.

---

## Task 10: Implement Immutable Snapshot, Lineage, Incremental Tail, Performance and Explicit Bootstrap CLI

**Deliverable:** secure schema-v1 immutable Newow snapshot/current manifest, source lineage decisions, incremental refresh, read-only current/performance projection and an explicit CLI publish command. No after-market automatic integration.

**Files:**

- Create: `services/quant-api/app/market_data/newow/snapshot.py`
- Create: `services/quant-api/app/market_data/newow/snapshot_store.py`
- Create: `services/quant-api/app/market_data/newow/snapshot_query.py`
- Create: `services/quant-api/app/market_data/newow/lineage.py`
- Create: `services/quant-api/app/market_data/newow/incremental.py`
- Create: `services/quant-api/app/market_data/newow/performance.py`
- Create: `services/quant-api/app/market_data/newow/current_service.py`
- Modify: `services/quant-api/app/market_data/newow/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Test: snapshot/store/lineage/incremental/performance/current/CLI files under `services/quant-api/tests/newow/`

**Interfaces:**

```text
NewowStrategySnapshotDocument
NewowSnapshotReceipt
NewowSnapshotStore.read_current(...)
NewowSnapshotStore.publish_current(...)
NewowSnapshotQuery.current(...)
NewowLineageDecision: UNCHANGED | APPEND_CURRENT_SEGMENT | REPLAY_CURRENT_SEGMENT | NEW_PHYSICAL_SEGMENT | FULL_REBUILD_REQUIRED
NewowIncrementalRefresher.refresh(...)
NewowPerformanceProjection
NewowCurrentProjection
```

Snapshot root is resolved from `GUIYI_NEWOW_OBSERVATION_ROOT`. Missing or insecure root fails closed. Code must not edit `.env`. Files/directories use the existing secure atomic-store rules: trusted containment, no symlink, owner-only 0700 directories, owner-only 0600 files, fsync, immutable payload, readback, atomic current manifest.

- [ ] **Step 1: Write schema exact-key/hash tests**

Snapshot includes strategy instance, formula/profile/engine/source digests, coverage, cutoff, immutable prefix count, segment facts, current checkpoint, projection and created_at. Duplicate keys, wrong hash, byte drift, unexpected field and stale identity fail closed.

- [ ] **Step 2: Write filesystem security and atomicity tests**

Cover symlink root/path, wrong owner/mode fixture where supported, immutable collision, interrupted temporary write, failed readback and current-manifest replacement. Last valid current snapshot remains readable after failure.

- [ ] **Step 3: Write lineage decision table tests**

```text
same identity/no new bars -> UNCHANGED
same current segment with appended bars -> APPEND_CURRENT_SEGMENT
current segment source revision -> REPLAY_CURRENT_SEGMENT
formal new rank1 segment -> NEW_PHYSICAL_SEGMENT
closed-prefix drift, formula/profile drift, prefix mismatch -> FULL_REBUILD_REQUIRED
```

No automatic fallback from FULL_REBUILD_REQUIRED to full rebuild.

- [ ] **Step 4: Write incremental/full replay parity tests**

Append and current-segment replay must produce a projection byte-equivalent to a clean full Historical fold for the same frozen window.

- [ ] **Step 5: Write performance formula tests**

Verify direction-sign reference change, initial risk/R, MFE/MAE inclusion boundaries, complete/non-administrative main stats and separate administrative/marketability strata. No annualized, equity or net fields are allowed in schema.

- [ ] **Step 6: Add explicit bootstrap CLI**

Register exactly:

```text
guiyi research newow-strategy-snapshot
  --strategy-code newow_trend_v1|newow_range_v1
  --profile-id newow_tf_1d_v1|newow_tf_15m_v1
  (--symbol SYMBOL | --scope active)
  --since YYYY-MM-DD
  --through YYYY-MM-DD
  [--publish]
```

Without `--publish`, command returns the frozen plan and performs no write. `--publish` writes only the Git-external Newow snapshot root and must be executed later under a separate explicit data-write Gate. This task implements and tests the command but does not run a real publish.

- [ ] **Step 7: Confirm no after-market/Runtime integration**

```bash
git diff --name-only origin/develop...HEAD | grep -E 'after_market|runtime|alerts|migrations' && exit 1 || true
```

- [ ] **Step 8: Run targeted tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_snapshot.py \
  services/quant-api/tests/newow/test_newow_snapshot_store.py \
  services/quant-api/tests/newow/test_newow_lineage.py \
  services/quant-api/tests/newow/test_newow_incremental.py \
  services/quant-api/tests/newow/test_newow_performance.py \
  services/quant-api/tests/newow/test_newow_current_service.py \
  services/quant-api/tests/newow/test_newow_cli.py
```

```bash
git add services/quant-api/app/market_data/newow \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/newow
git commit -m "feat(newow): add immutable projection snapshots and tail refresh"
```

**Application Checkpoint:** independent reviewer inspects secure store, lineage drift behavior, incremental/full parity, CLI dry-run boundary, outcome exclusions and absence of after-market/Runtime writes.

---

## Task 11: Add Read-only Newow API Contracts

**Deliverable:** typed definitions, overlay/history/current/history/performance endpoints under `/api/v1/market/research/newow`, backed only by static authorities or current snapshots.

**Files:**

- Create: `services/quant-api/app/api/market_newow.py`
- Create: `services/quant-api/app/schemas/newow_research.py`
- Modify: `services/quant-api/app/main.py`
- Test: `services/quant-api/tests/test_market_newow_api.py`
- Create: `openspec/specs/newow-research/spec.md`

**Interfaces:**

```text
GET /definitions
GET /overlay/history
GET /strategy/current
GET /strategy/history
GET /strategy/performance
```

- [ ] **Step 1: Write 422 request tests**

Invalid strategy/profile/symbol/date/order and unsupported Binding return 422 with only the approved stable code. Client never supplies series kind or frequency.

- [ ] **Step 2: Write 409 source/snapshot tests**

Map snapshot missing/stale/identity/full-rebuild, Calendar/Session/contract/warm-up/OI/one-price/gap/next-bar/mapping availability/OOS pending to stable public codes. Responses contain no path, SQL, provider reference or stack trace.

- [ ] **Step 3: Prove HTTP never calls Historical replay or publish**

Use fakes whose `history()` and `publish_current()` raise if called. All endpoint tests must succeed from snapshot query alone.

```python
def test_history_endpoint_slices_snapshot_without_replay(client, services) -> None:
    services.historical.history = forbidden_call
    services.store.publish_current = forbidden_call
    response = client.get(
        "/api/v1/market/research/newow/strategy/history",
        params=trend_history_params(),
    )
    assert response.status_code == 200
    assert response.json()["source_mode"] == "snapshot"
```

- [ ] **Step 4: Test Decimal wire shape and forming default**

Decimal fields serialize as strings; `include_forming=false` by default; overlay carries both `visual_start_at` and `confirmed_at`; current declares `Historical / Post-close` capability.

- [ ] **Step 5: Add OpenSpec and run validation**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_market_newow_api.py
openspec validate --specs --strict --no-interactive
```

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/api/market_newow.py \
  services/quant-api/app/schemas/newow_research.py \
  services/quant-api/app/main.py \
  services/quant-api/tests/test_market_newow_api.py \
  openspec/specs/newow-research/spec.md
git commit -m "feat(api): add readonly Newow research endpoints"
```

**Review Gate:** route/payload identity, no replay/write, stable redaction, strict binding, gross-reference copy and no Alert controls.

---

## Task 12: Add the Newow Market Web Overlay and Strategy Workspace

**Deliverable:** one top-level `newow` Overlay with internal Trend/Range switch, explicit period capability, typed backend primitives, sidebar, settings, performance panel and chart rendering. Browser never computes authoritative Newow formulas.

**Files:**

- Create all Web files listed in Program File Map
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Add unit tests under `apps/quant-web/tests/`
- Create: `apps/quant-web/e2e/market-newow.spec.mjs`

**Interfaces:**

```text
ResearchOverlayId adds "newow"
NewowStrategyMode = "trend" | "range"
NewowProfileId = "newow_tf_1d_v1" | "newow_tf_15m_v1"
getNewowDefinitions()
getNewowOverlayHistory(...)
getNewowStrategyCurrent(...)
getNewowStrategyHistory(...)
getNewowStrategyPerformance(...)
```

The range prerequisite moves main-chart preferences to v8; this task moves v8 to v9 and preserves all existing overlay/EMA/range settings. Failed migration returns safe defaults without blocking the chart.

- [ ] **Step 1: Write type normalization and API tests**

Normalize every Decimal at the HTTP display boundary. No utility in `apps/quant-web/src` may import or implement EMA/ATR/MACD/moments/Swing/Pattern/strategy formulas for Newow.

- [ ] **Step 2: Write overlay capability tests**

Trend supports only actual-dominant D; Range supports only actual-dominant 15m. Mismatch shows explicit message and switch button; it does not issue a hidden request for another frequency.

- [ ] **Step 3: Write preference v8→v9 migration tests**

Preserve existing selected Overlay, optional EMAs, Range Detector toggle, SuBing settings and period; initialize `newowStrategy="trend"`, forming off, Swing/Structure off, Phase on, Target2 off, performance off.

- [ ] **Step 4: Implement typed view model and markers**

Trend main chart renders band, confirmed primary Pattern/Range, A/validation/B, OPEN/CLOSE, stop, Target1 and rollover seam. Range renders boundaries/mid/edges/Bias, confirmation Bar, OPEN/CLOSE, frozen stop/target, consumed/invalidated. Administrative closure label is “主力切换，历史段结束”.

- [ ] **Step 5: Implement temporal disclosure**

FORMING is off by default and low-opacity dashed when enabled. Tooltip always distinguishes visual start and confirmation. Pivot time is never styled as signal time.

- [ ] **Step 6: Implement sidebar and settings**

First screen shows strategy, period, real contract, segment start, cutoff, direction, lifecycle, Setup/Pattern, Evidence, blockers, confirmed/effective time, stop/target and Episode. Include trading day/session, OI availability, segment age, one-price diagnostic, reference/admin closure and rollover tags. Do not display Alert Scope or PushPlus state.

- [ ] **Step 7: Add request-generation cancellation tests**

Symbol, strategy, profile and period changes abort stale requests; late old responses cannot overwrite new identity. Prepend/pan slices retain snapshot identities.

- [ ] **Step 8: Add E2E scenarios**

Desktop and narrow viewport; trend D; range 15m; unsupported period switch; forming toggle; pagination; fullscreen; rollover seam; performance off by default; no Newow Alert control; Historical/Post-close badge.

- [ ] **Step 9: Run Web verification**

```bash
pnpm -C apps/quant-web test
pnpm -C apps/quant-web exec vue-tsc -b
pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/market-newow.spec.mjs
pnpm -C apps/quant-web build
```

- [ ] **Step 10: Commit**

```bash
git add apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e/market-newow.spec.mjs
git commit -m "feat(web): add Newow research workspace"
```

**UI Checkpoint:** independent reviewer compares API payloads with chart primitives, confirms no browser formula, no hidden cross-period request, temporal disclosure, preference migration and no Alert surface.

---

## Task 13: Implement Candidate Authority, Gold Set Schema and OOS Validation Infrastructure

**Deliverable:** digest-pinned Pattern/Strategy Candidate and Protocol loaders, deterministic Gold Set schema/export/import, rolling window/embargo/prospective-no-backfill engine and research reports. This task builds infrastructure; it does not fabricate human labels or mature prospective time.

**Files:** create all files under `services/quant-api/app/research/newow/`, candidate/protocol JSON files, CLI parser/request/command/payload changes, tests under `services/quant-api/tests/research/newow/`.

**Interfaces:**

```text
NewowCandidateAuthority
NewowPatternGoldWindow
NewowGoldSet
NewowPatternValidationReport
NewowStrategyValidationReport
load_newow_candidate_authority(...)
validate_newow_gold_set(...)
run_newow_pattern_validation(...)
run_newow_strategy_validation(...)
```

Add read-only/report CLI commands:

```text
guiyi research newow-pattern-gold-export --profile-id ... --since ... --through ... --output PATH
guiyi research newow-pattern-validate --profile-id ... --gold-set PATH
guiyi research newow-strategy-validate --strategy-code ... --profile-id ... --through ...
```

Export writes only the explicitly named local output path after containment/type checks; it does not write Canonical/DB/Runtime. The committed candidate/protocol files pin exact formula/profile/kernel/pattern digests. Prospective first trading day is resolved at authority freeze and committed as an exact date, never inferred from retrospective run time.

- [ ] **Step 1: Write exact-key/raw-byte drift tests**

Candidate and Protocol same-ID byte changes fail closed. Strategy Candidate references the exact frozen Pattern Candidate digest.

- [ ] **Step 2: Write Gold Set schema tests**

Each window includes immutable source identity, profile, segment, time bounds, expected family/variant/direction, expected lifecycle/confirmation, primary flag, negative/near-miss reason and reviewer metadata. No label contains return/outcome fields.

- [ ] **Step 3: Write rolling-window calendar tests**

Trend: 18m reference/6m test/3m step/20 D1 embargo/horizons 3,5,10,20. Range: 12m/3m/3m/16×15m embargo/horizons 3,5,8,16. Resolve through authoritative TradingCalendar/Session and never split an Episode across reference/test.

- [ ] **Step 4: Write prospective no-backfill tests**

Retrospective Bars before `prospective_oos_first_trading_day` can never enter prospective result. Missing mapping availability or `MAPPING_AUTHORITY_CONFLICT` excludes the whole affected trading day.

- [ ] **Step 5: Write report/status tests**

Only `RESEARCH_SUPPORT_OBSERVED`, `RESEARCH_SUPPORT_NOT_OBSERVED`, `INSUFFICIENT_SAMPLE`, `OOS_PENDING`, `CONTRACT_FAILED` are allowed. No winner/promotion/tradable/profitability field exists.

- [ ] **Step 6: Run research tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/newow
```

```bash
git add services/quant-api/app/research/newow \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/research/newow \
  data/research_candidates/newow_* \
  data/research_protocols/newow_*
git commit -m "feat(research): add Newow candidate and OOS validation contracts"
```

**Review Gate:** digest authority, label/outcome separation, embargo, prospective no-backfill, mapping availability and no auto-promotion.

---

## Task 14: Build the Human-reviewed Pattern Gold Set and Produce Retrospective/Rolling Reports

**Deliverable:** 200–300 reviewed windows with required futures coverage, deterministic validation metrics, trend/range retrospective and rolling reports, and explicit prospective `OOS_PENDING` state.

**Files:**

- Create: `data/research_gold/newow/newow_pattern_gold_v1.json`
- Create: `docs/tasks/newow-validation/newow-pattern-gold-v1-report.json`
- Create: `docs/tasks/newow-validation/newow-trend-d1-v1-report.json`
- Create: `docs/tasks/newow-validation/newow-range-15m-v1-report.json`
- Test: `services/quant-api/tests/research/newow/test_newow_committed_gold_set.py`

**Interfaces:** consumes Task 13 CLI and current read-only Canonical/Catalog data. Produces immutable reviewed labels and reports; does not update formulas automatically.

- [ ] **Step 1: Export deterministic candidate windows read-only**

Select 200–300 windows covering active60 representatives, all exchanges, D1/15m, long/short, continuation/reversal/near-miss/negative, A/B, day/night, long breaks, holidays, roll-near, OI missing, one-price, gaps, successes and failures.

- [ ] **Step 2: Human review without outcome access**

Reviewer sees bars/geometry/identity only, not Episode return or later horizon. Every label records reviewer and review timestamp; disagreements are resolved before commit rather than averaged by strategy outcome.

- [ ] **Step 3: Validate Pattern Gates**

```text
confirmed identity stability = 100%
primary precision >= 80%
per-family precision >= 70% for each family with at least 20 labels
no cross-contract pattern at roll seam
FORMING strategy participation = 0
```

Recall is reported but cannot lower causality or precision gates.

- [ ] **Step 4: Run retrospective and rolling strategy reports**

Report all required strata, gross/pre-cost/reference-only outcomes, administrative/marketability exclusions, product contribution concentration and fold medians. Do not create a rank or winner.

- [ ] **Step 5: Freeze prospective authority**

Resolve the next authoritative trading day after candidate/profile/protocol/formula freeze. Reports must show `OOS_PENDING` until natural time/sample maturity; retrospective results are never copied into prospective fields.

- [ ] **Step 6: Run committed-data validation**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/newow/test_newow_committed_gold_set.py \
  services/quant-api/tests/research/newow
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 7: Commit the data-only evidence PR**

```bash
git add data/research_gold/newow \
  docs/tasks/newow-validation \
  services/quant-api/tests/research/newow/test_newow_committed_gold_set.py
git commit -m "test(newow): add reviewed pattern and rolling evidence"
```

**Evidence Gate:** formula code is frozen before labels/results. Failed thresholds remain failed; this PR must not tune parameters, alter Candidate IDs or backfill prospective OOS.

---

## Task 15: Canonical Documentation, Full Verification and Independent Acceptance Review

**Deliverable:** active architecture/product/decision/testing/OpenSpec documentation aligned with implemented research-only Newow, complete local verification evidence, and independent cross-layer review. No release or Runtime promotion.

**Files:**

- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `TESTING.md`
- Modify: `openspec/specs/newow-research/spec.md`
- Modify: `openspec/specs/range-detector/spec.md` only if implementation-required clarifications preserve the accepted formula identity
- Do not modify: `STATUS.md` with a release/runtime claim unless a separate release task later changes production facts

- [ ] **Step 1: Update stable product and dependency language**

Document Newow as research-only, same-frequency, snapshot-backed and independent from SuBing. Explicitly retain `live_capable=false`, `alert_capable=false`, `auto_order=false`, gross-reference outcomes and prospective OOS pending semantics.

- [ ] **Step 2: Run the complete backend suite**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

- [ ] **Step 3: Run engineering consistency and Web suites**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

- [ ] **Step 4: Run contract/static checks**

```bash
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: Run architecture guard searches**

```bash
git grep -n "subing_strategy" -- packages/quant-core/guiyi_quant/newow services/quant-api/app/market_data/newow services/quant-api/app/research/newow && exit 1 || true
git grep -n "PushPlus\|scope_products\|AlertEvent\|auto_order" -- packages/quant-core/guiyi_quant/newow services/quant-api/app/market_data/newow services/quant-api/app/research/newow && exit 1 || true
git grep -n "annualized\|sharpe\|equity_curve\|net_profit" -- services/quant-api/app/market_data/newow services/quant-api/app/schemas/newow_research.py apps/quant-web/src/types/newow.ts && exit 1 || true
```

Expected: no prohibited dependency or profitability schema.

- [ ] **Step 6: Independent four-part review**

Reviewer A: formulas/numeric/golden; Reviewer B: causality/open-only/segments/snapshot; Reviewer C: API/Web/no formula/temporal disclosure; Reviewer D: Gold/OOS/no backfill/no promotion. Each posts findings on the final Draft PR. All blocking findings are fixed and reverified.

- [ ] **Step 7: Record completion states accurately**

Allowed declarations after evidence:

```text
CODE_COMPLETE
TEST_COMPLETE
PROSPECTIVE_OOS_PENDING
RELEASE_NOT_REQUESTED
RUNTIME_NOT_REQUESTED
ALERT_NOT_REQUESTED
```

Do not declare `RELEASED` or `RUNTIME_READY`.

- [ ] **Step 8: Commit documentation**

```bash
git add PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md docs/INDICATOR_KERNEL.md TESTING.md openspec/specs
git commit -m "docs: register Newow research-only product surface"
```

---

## Required Causality Matrix by Task

| Contract | First implemented | Reverified |
|---|---|---|
| completed-only | Tasks 3–8 | Tasks 9, 15 |
| strict-before Swing/Range/Pattern | Tasks 1, 4, 5 | Tasks 7–9, 15 |
| future-tail invariance | Tasks 1, 3–5 | Tasks 7–10, 15 |
| prefix invariance | Tasks 1, 3–5 | Tasks 7–10, 15 |
| append parity | Tasks 1, 6 | Tasks 7–10, 15 |
| prepend numeric warm-up invariance | Task 9 | Tasks 10, 15 |
| batch/incremental parity | Tasks 1, 3–6 | Tasks 7–10, 15 |
| engine restore parity | Task 6 | Tasks 9–10, 15 |
| physical-segment isolation | Tasks 4, 9 | Tasks 10, 14–15 |
| same-contract cross-day | Task 9 | Tasks 10, 15 |
| TradingSession next-bar identity | Task 9 | Tasks 10–11, 15 |
| one-price diagnostics | Task 6 | Tasks 7–10, 14–15 |
| open-only pending application | Task 6 | Tasks 7–10, 15 |
| no cross-contract fill | Task 9 | Tasks 10, 14–15 |
| administrative closure | Tasks 6, 9 | Tasks 10–15 |
| range revision freeze | Tasks 1, 8 | Tasks 9–15 |
| pattern anti-backpaint | Task 5 | Tasks 7, 9, 12, 14–15 |
| A/validation/B separation | Tasks 5, 7 | Tasks 9–15 |
| OI null/no cross-contract fill | Tasks 3, 9 | Tasks 10, 14–15 |
| same-ID byte drift | Tasks 2, 10, 13 | Tasks 14–15 |
| API read-only snapshot | Task 11 | Tasks 12, 15 |
| Web no-formula parity | Task 12 | Task 15 |
| Newow/SuBing isolation | Tasks 2, 9 | Task 15 |
| Profile extension isolation | Task 2 | Tasks 7–9, 15 |
| outcome segment boundary | Tasks 9–10 | Tasks 13–15 |
| prospective no-backfill | Task 13 | Tasks 14–15 |

All rows must pass 100%; statistical thresholds cannot waive a causality failure.

## Spec Coverage Self-Review

| Approved Spec area | Implementation task |
|---|---|
| independent product identity and SuBing isolation | Tasks 0, 2, 9, 15 |
| D1/15m immutable Profiles and Bindings | Task 2 |
| futures trading day, Session, physical segments, warm-up | Task 9 |
| numeric determinism and indicator policies | Tasks 1–3 |
| Phase moments | Task 3 |
| causal Swing/Structure | Task 4 |
| deterministic Pattern and primary selection | Task 5 |
| Range primitive | Task 1 |
| Target/Risk/Evidence/Execution | Task 6 |
| B milestone only and open-only reference | Task 6 |
| Trend D1 machine | Task 7 |
| Range 15m machine | Task 8 |
| Historical single-step fold | Task 9 |
| snapshot, lineage, incremental tail, performance | Task 10 |
| read-only API | Task 11 |
| Market Web | Task 12 |
| Pattern Gold Set and OOS authority | Tasks 13–14 |
| causality matrix and independent Review | Task 15 |
| no Alert/Runtime/order/release | Global Constraints and Tasks 10–15 |

Self-review result:

- Every normative section in the main Spec and review amendment maps to at least one executable task.
- Interface names remain consistent across Kernel, application, API and Web tasks.
- Range formula is not duplicated; Newow consumes the independent prerequisite.
- No task requires a migration, production write, real notification, Runtime switch or order path.
- Human Gold labels and prospective maturity are identified as explicit evidence Gates rather than fabricated completion.

## Execution Handoff

The approved execution mode for this repository should be **Subagent-Driven**: one fresh implementation agent per task branch/worktree, followed by a formula/contract review agent and user Gate. Start with Task 0 and Task 1 in parallel; Task 2 begins only after Task 1 is merged. No implementation task may reuse the Spec or Plan branch.
