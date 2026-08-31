# Newow Implementation Plan 自审修正

状态：`NORMATIVE_PLAN_AMENDMENT`

日期：2026-08-31

任务：Issue #265

基线文档：`docs/tasks/2026-08-31-newow-independent-strategy-implementation-plan.md`

> 本文是 Implementation Plan 的规范性组成部分。发生冲突或正文使用简写签名时，以本文为准。本文不改变已批准 Spec：Newow 与 SuBing 完全隔离；趋势 V1 只绑定 completed D1；震荡 V1 只绑定 completed 15m；当前不接 Alert、Runtime、订单或真实通知。

---

## 1. 计划批准与执行边界

- PR #263 已合入 `develop`，因此主 Spec 头部残留的 `DESIGN_REVIEW_PENDING` 只是陈旧元数据，不再阻塞 Implementation Plan。
- 本 Plan PR 仍是 Plan-only；合入前后都不自动开始源码实现。
- 每个源码任务从执行时最新 `origin/develop` 创建独立 worktree、branch 和 Draft PR；不得在 Spec 分支或 Plan 分支编码。
- 任何实现 PR 合入 `develop` 都不授权 main、tag、release、Runtime、Alert、Scope、PushPlus、RQData、Canonical、production DB/Redis 或真实通知。
- Candidate/Protocol、Gold Set 和 snapshot 的真实发布各有独立 Gate；测试与 dry-run 不能替代该 Gate。

---

## 2. 固定 Child Branch 与 PR 边界

正文中的通用 task 名只表示工作流。执行时固定使用以下 branch 名，不得把多个任务堆进一个 PR：

| Task | branch | PR 交付物 |
|---:|---|---|
| 0 | `docs/remove-superseded-newow-subing-design` | 删除旧方向文档并关闭 active reference |
| 1 | `feature/range-detector-lux-v1` | 执行 Issue #258 的独立 Range Detector |
| 2 | `feature/newow-contracts-profiles` | contracts、Profiles、Bindings、Kernel Bundle、indicator policies |
| 3 | `feature/newow-phase-kernel` | Phase moments Kernel |
| 4 | `feature/newow-swing-structure` | causal Swing 与 Structure Graph |
| 5 | `feature/newow-pattern-kernel` | Pattern geometry、enumeration、lifecycle、candle context |
| 6 | `feature/newow-risk-execution-engine` | Target/Risk、Evidence、Execution、Newow engine |
| 7 | `feature/newow-trend-d1` | `newow_trend_v1 @ newow_tf_1d_v1` |
| 8 | `feature/newow-range-15m` | `newow_range_v1 @ newow_tf_15m_v1` |
| 9 | `feature/newow-historical-projection` | source segment、warm-up、Historical projection |
| 10 | `feature/newow-snapshot-incremental` | snapshot、lineage、tail、performance、bootstrap CLI |
| 11 | `feature/newow-readonly-api` | read-only API 与 schemas |
| 12 | `feature/newow-market-web` | Market Web Overlay 与二级策略工作区 |
| 13 | `feature/newow-validation-infra` | Candidate/Protocol、Gold/OOS validation infrastructure |
| 14 | `research/newow-gold-oos-evidence` | 人工 Gold Set 与 retrospective/rolling evidence |
| 15 | `docs/newow-research-product-surface` | canonical docs、OpenSpec、全量验证与独立 Review |

以 Task 2 为例，标准命令是：

```bash
git fetch origin
git worktree add ../guiyi-newow-contracts-profiles \
  -b feature/newow-contracts-profiles origin/develop
cd ../guiyi-newow-contracts-profiles
git branch --show-current
git status --short
git log -5 --oneline
```

其他任务只替换为上表的固定 branch 和对应目录名。

---

## 3. Range Detector 参数化政策

Issue #258 的 Kernel 公式身份保持 `range_detector_lux_v1`，但 policy 不能把业务语义写死为 ATR500，因为批准的 Newow Profiles 是：

```text
newow_tf_1d_v1:
  minimum_range_length = 20
  range_atr_length = 100
  range_width_atr_multiplier = 1.0

newow_tf_15m_v1:
  minimum_range_length = 20
  range_atr_length = 500
  range_width_atr_multiplier = 1.0
```

因此 Task 1 在首次实现 policy 时必须使用：

```text
policy_id       = range_detector_lux_v1
lookback        = parameterized_range_length_and_atr_length
smoothing       = wilder_sma_seed
registry default = range20_atr500_multiplier1
```

Registry 的 ATR500 只是独立标准观察指标默认值，不限制 named research consumer 传入已冻结 Profile 参数。`parameters_hash` 必须区分 D1 ATR100 与 15m ATR500。

Task 1 必须增加两个同 Kernel、不同参数的测试：

```python
def test_range_detector_supports_both_frozen_newow_profiles() -> None:
    daily = range_detector_lux_series(
        daily_highs(),
        daily_lows(),
        daily_closes(),
        bar_ends=daily_bar_ends(),
        source_identity="newow:rb:contract:RB2610:1d",
        minimum_range_length=20,
        range_width_atr_multiplier=1.0,
        range_atr_length=100,
        round_digits=6,
    )
    intraday = range_detector_lux_series(
        intraday_highs(),
        intraday_lows(),
        intraday_closes(),
        bar_ends=intraday_bar_ends(),
        source_identity="newow:rb:contract:RB2610:15m",
        minimum_range_length=20,
        range_width_atr_multiplier=1.0,
        range_atr_length=500,
        round_digits=6,
    )
    assert daily.parameters.range_atr_length == 100
    assert intraday.parameters.range_atr_length == 500
    assert daily.parameters != intraday.parameters
```

Allowed named consumers are exactly：

```text
range_detector_readonly_display
subing_daily_trend_research
newow_historical
```

保留 SuBing named consumer 不表示 Newow 读取苏冰事实；两者只共享独立的 pure Range Kernel。

---

## 4. 正式 Python 接口签名

正文中的括号简写不是代码模板。实际 public signature 必须精确到以下字段；提交中不得保留未实现函数体或省略参数。

### 4.1 Range prerequisite

```python
def initial_range_detector_lux_state(
    *,
    source_identity: str,
    minimum_range_length: int = 20,
    range_width_atr_multiplier: float = 1.0,
    range_atr_length: int = 500,
    round_digits: int = 6,
) -> RangeDetectorLuxState:
```

```python
def step_range_detector_lux(
    state: RangeDetectorLuxState,
    *,
    high: float | int | None,
    low: float | int | None,
    close: float | int | None,
    bar_end: str,
    trading_day: str | None = None,
) -> tuple[RangeDetectorLuxState, RangeDetectorPoint]:
```

```python
def range_detector_lux_series(
    highs: Sequence[float | int | None],
    lows: Sequence[float | int | None],
    closes: Sequence[float | int | None],
    *,
    bar_ends: Sequence[str],
    source_identity: str,
    trading_days: Sequence[str | None] | None = None,
    minimum_range_length: int = 20,
    range_width_atr_multiplier: float = 1.0,
    range_atr_length: int = 500,
    round_digits: int = 6,
) -> RangeDetectorSeries:
```

### 4.2 Authority and identity

```python
def load_newow_authority(
    *,
    root: Path | None = None,
) -> NewowAuthority:
```

```python
def strategy_instance_id(
    *,
    binding: NewowStrategyFrequencyBinding,
    profile: NewowTimeframeProfile,
    bundle: NewowKernelBundleIdentity,
) -> str:
```

```python
def rounded_decimal(
    value: float,
    *,
    digits: int = 8,
) -> Decimal:
```

### 4.3 Phase

```python
def calculate_newow_moments(
    returns: Sequence[float],
    *,
    epsilon: float = 1e-12,
) -> NewowMoments:
```

```python
def initial_newow_phase_state(
    profile: NewowTimeframeProfile,
) -> NewowPhaseState:
```

```python
def step_newow_phase(
    state: NewowPhaseState,
    *,
    bar: NewowCompletedBar,
    indicators: NewowIndicatorSnapshot,
) -> tuple[NewowPhaseState, NewowPhaseSnapshot]:
```

### 4.4 Swing and Structure

```python
def initial_newow_swing_state(
    *,
    scale: NewowSwingScale,
    reversal_atr: float,
    min_leg_bars: int,
    segment_id: str,
) -> NewowSwingState:
```

```python
def step_newow_swing(
    state: NewowSwingState,
    *,
    bar: NewowCompletedBar,
    atr: Decimal,
) -> tuple[NewowSwingState, NewowSwingPoint | None]:
```

```python
def initial_newow_structure_state(
    *,
    segment_id: str,
) -> NewowStructureState:
```

```python
def step_newow_structure(
    state: NewowStructureState,
    *,
    bar: NewowCompletedBar,
    newly_confirmed_swings: Sequence[NewowSwingPoint],
    atr: Decimal,
) -> tuple[NewowStructureState, NewowStructureSnapshot]:
```

### 4.5 Pattern

```python
def enumerate_newow_patterns(
    *,
    swings: Sequence[NewowSwingPoint],
    structure: NewowStructureSnapshot,
    phase: NewowPhaseSnapshot,
    profile: NewowTimeframeProfile,
) -> NewowPatternSet:
```

```python
def select_primary_visual_pattern(
    candidates: Sequence[NewowPatternCandidate],
) -> NewowPatternCandidate | None:
```

```python
def select_primary_action_pattern(
    candidates: Sequence[NewowPatternCandidate],
) -> NewowPatternCandidate | None:
```

```python
def step_newow_pattern_lifecycle(
    state: NewowPatternState,
    *,
    bar: NewowCompletedBar,
    context: NewowPatternStepContext,
) -> tuple[NewowPatternState, tuple[NewowPatternTransition, ...]]:
```

### 4.6 Risk, Evidence and Engine

```python
def build_newow_risk_plan(
    *,
    setup: NewowSetup,
    pattern: NewowPatternCandidate | None,
    range_snapshot: RangeDetectorSnapshot | None,
    atr: Decimal,
    profile: NewowTimeframeProfile,
) -> NewowRiskPlan:
```

```python
def fuse_newow_evidence(
    inputs: NewowEvidenceInputs,
) -> NewowEvidenceSnapshot:
```

```python
class NewowIncrementalEngine:
    @classmethod
    def initial_state(
        cls,
        *,
        segment: NewowSourceSegmentIdentity,
        profile: NewowTimeframeProfile,
        binding: NewowStrategyFrequencyBinding,
    ) -> NewowEngineState:
```

```python
class NewowIncrementalEngine:
    def step(
        self,
        state: NewowEngineState,
        *,
        completed_bar: NewowCompletedBar,
    ) -> tuple[NewowEngineState, NewowStepResult]:
```

### 4.7 Strategy machines

```python
class NewowTrendMachine:
    @classmethod
    def initial_state(
        cls,
        *,
        binding: NewowStrategyFrequencyBinding,
        profile: NewowTimeframeProfile,
        segment: NewowSourceSegmentIdentity,
    ) -> NewowTrendMachineState:
```

```python
class NewowTrendMachine:
    def step(
        self,
        state: NewowTrendMachineState,
        *,
        context: NewowStepContext,
    ) -> tuple[NewowTrendMachineState, NewowTrendDecision]:
```

```python
class NewowRangeMachine:
    @classmethod
    def initial_state(
        cls,
        *,
        binding: NewowStrategyFrequencyBinding,
        profile: NewowTimeframeProfile,
        segment: NewowSourceSegmentIdentity,
    ) -> NewowRangeMachineState:
```

```python
class NewowRangeMachine:
    def step(
        self,
        state: NewowRangeMachineState,
        *,
        context: NewowStepContext,
    ) -> tuple[NewowRangeMachineState, NewowRangeDecision]:
```

### 4.8 Historical and snapshot

```python
class NewowHistoricalProjectionService:
    def history(
        self,
        request: NewowHistoricalRequest,
    ) -> NewowHistoricalProjection:
```

```python
class NewowSnapshotStore:
    def read_current(
        self,
        *,
        strategy_instance_id: str,
        symbol: str,
    ) -> NewowStrategySnapshotDocument:
```

```python
class NewowSnapshotStore:
    def publish_current(
        self,
        snapshot: NewowStrategySnapshotDocument,
    ) -> NewowSnapshotReceipt:
```

```python
class NewowSnapshotQuery:
    def current(
        self,
        *,
        strategy_code: str,
        profile_id: str,
        symbol: str,
    ) -> NewowCurrentProjection:
```

```python
class NewowIncrementalRefresher:
    def refresh(
        self,
        *,
        strategy_code: str,
        profile_id: str,
        symbol: str,
        through: date,
    ) -> NewowHistoricalProjection:
```

### 4.9 Validation

```python
def load_newow_candidate_authority(
    *,
    candidate_path: Path,
    protocol_path: Path,
) -> NewowCandidateAuthority:
```

```python
def validate_newow_gold_set(
    gold_set: NewowGoldSet,
    *,
    authority: NewowCandidateAuthority,
) -> NewowGoldSetValidation:
```

```python
def run_newow_pattern_validation(
    *,
    authority: NewowCandidateAuthority,
    gold_set: NewowGoldSet,
    projection: NewowOverlayProjection,
) -> NewowPatternValidationReport:
```

```python
def run_newow_strategy_validation(
    *,
    authority: NewowCandidateAuthority,
    projections: Sequence[NewowHistoricalProjection],
    through: date,
) -> NewowStrategyValidationReport:
```

---

## 5. 正式 TypeScript API 签名

```typescript
export function getNewowDefinitions(): Promise<NewowDefinitionsResponse>
```

```typescript
export function getNewowOverlayHistory(
  params: NewowOverlayHistoryRequest,
  signal?: AbortSignal,
): Promise<NewowOverlayHistoryResponse>
```

```typescript
export function getNewowStrategyCurrent(
  params: NewowStrategyCurrentRequest,
  signal?: AbortSignal,
): Promise<NewowStrategyCurrentResponse>
```

```typescript
export function getNewowStrategyHistory(
  params: NewowStrategyHistoricalRequest,
  signal?: AbortSignal,
): Promise<NewowStrategyHistoricalResponse>
```

```typescript
export function getNewowStrategyPerformance(
  params: NewowStrategyPerformanceRequest,
  signal?: AbortSignal,
): Promise<NewowStrategyPerformanceResponse>
```

`NewowStrategyHistoricalRequest` 只含：

```text
strategy_code
profile_id
symbol
since
through
```

浏览器不得提交 `series_kind` 或 `frequency`，两者只由 Binding 决定。

---

## 6. Phase Golden 的确定性修正

正文中 Phase test 的示例数值不构成 authority。Task 3 必须先对以下固定 returns 直接测试公开纯函数 `calculate_newow_moments`：

```text
returns = [-0.04, -0.02, -0.01, 0.01, 0.03, 0.08]
N       = 6
mean    = 0.008333333333333333
m2      = 0.001513888888888889
m3      = 0.000039407407407407415
m4      = 0.000005469143518518519
skew    = 0.91608864
excess_kurtosis = 0.71014224
```

对应测试：

```python
def test_newow_moments_match_fixed_hand_calculation() -> None:
    result = calculate_newow_moments(
        (-0.04, -0.02, -0.01, 0.01, 0.03, 0.08),
    )
    assert result.mean == pytest.approx(0.008333333333333333, abs=1e-15)
    assert result.m2 == pytest.approx(0.001513888888888889, abs=1e-15)
    assert result.m3 == pytest.approx(0.000039407407407407415, abs=1e-15)
    assert result.m4 == pytest.approx(0.000005469143518518519, abs=1e-15)
    assert result.skew == pytest.approx(0.91608864, abs=1e-8)
    assert result.excess_kurtosis == pytest.approx(0.71014224, abs=1e-8)
```

生产 Phase snapshot 仍要求完整 `moment_window=60`，不得用 6 个 returns 绕过 warm-up。60-window fixture 另行提交并以 payload hash 固定。

---

## 7. Pattern Transition 返回值说明

`step_newow_pattern_lifecycle` 返回 tuple 是因为同一 completed Bar 可以让多个独立 Pattern revision 分别失效、过期或推进；但：

- 同一个 `pattern_id + revision` 每根 Bar 最多一个 transition；
- Strategy 只消费 `primary_action_pattern`；
- Execution 每根 Bar 最多一个 Action；
- transition 排序固定为 `pattern_id asc, revision asc, lifecycle precedence asc`；
- 未来 append 不得改写旧 transition。

Lifecycle precedence 固定：

```text
INVALIDATED
EXPIRED
BREAKOUT_A
BREAKOUT_VALIDATED
RETESTING
REBREAK_B
COMPLETED
```

---

## 8. Snapshot Root 与 Bootstrap CLI 边界

Snapshot 路径固定为：

```text
$GUIYI_NEWOW_OBSERVATION_ROOT/
  snapshots/{strategy_instance_id}/{symbol}/{through}/{snapshot_sha256}.json
  current/{strategy_instance_id}/{symbol}.json
```

安全规则：

```text
root 必须是绝对路径
root 与所有 parent 不能是 symlink
目录 owner=current user，mode=0700
文件 owner=current user，mode=0600
snapshot immutable
current manifest 原子替换
发布后必须物理读回
```

CLI dry-run 不创建 root、目录、临时文件或 manifest。`--publish` 缺少安全 root 时返回 `NEWOW_SNAPSHOT_ROOT_INVALID`。本计划阶段与普通测试都不得执行真实 `--publish`。

---

## 9. Intraday Mapping Availability 的精确判定

15m Historical 报告必须分别保存：

```text
mapping_trade_date
mapping_source_identity
mapping_observed_at
first_session_bar_start
mapping_availability_status
```

判定：

```text
mapping_observed_at is None
  -> HISTORICAL_MAPPING_AVAILABILITY_UNPROVEN

mapping_observed_at > first_session_bar_start
  -> HISTORICAL_MAPPING_AVAILABILITY_UNPROVEN

mapping_observed_at <= first_session_bar_start
  -> PROSPECTIVE_OWNER_AVAILABLE
```

Retrospective 图表可以显示 unproven 段，但 prospective OOS、completed-Live parity、Alert/Runtime 证据必须排除。未来 prospective freeze 与最终 Canonical owner 不一致时，整 trading day 标记 `MAPPING_AUTHORITY_CONFLICT`，不得换合约回填结果。

该规则只增加 Newow 证据强度，不改变全局 MainContractMap 或 MarketDataService。

---

## 10. Gold Set 与 OOS 的不可伪造 Gate

- Task 13 只能提交 schema、loader、validator、candidate/protocol authority 和 synthetic test fixtures。
- Task 14 才能提交 200–300 个真实人工 review window；没有人工复核，不得用程序输出冒充标签。
- Gold reviewer 不得看到 Episode return、future horizon 或策略效果。
- Candidate/Profile/Protocol/Formula/Pattern digest 在 Gold/rolling report 前冻结；失败指标不得通过改参数原地修复。
- Prospective OOS 从冻结后的下一个权威交易日自然累积。即使 retrospective/rolling 通过，初始状态仍必须为 `OOS_PENDING`。
- Trend maturity：至少 6 个自然月且至少 30 个完整 Episode；Range maturity：至少 3 个自然月且至少 100 个完整 Episode。
- 只有另一个未来任务读取自然 prospective evidence；当前实施程序不能缩短时间、补录历史或自动晋升。

---

## 11. 自审新增的 Review Checkpoints

### Checkpoint A：Task 2 后

检查 Profile 原始字节、参数 hash、Kernel Bundle digest、named indicator consumer、D1/15m Binding 和新增 60m 不改变旧 digest 的测试。

### Checkpoint B：Task 5 后

独立复算 Swing confirmation、WLS、各 Pattern family、primary ordering、strict-before、revision 与 anti-backpaint。

### Checkpoint C：Task 6 后

使用两根相同 open、不同 completed tail 的 Bar 证明 pending application 相同；检查 B milestone、target/profit-floor 延后、行政关闭和 one-action-per-Bar。

### Checkpoint D：Task 10 后

检查 secure snapshot、immutable prefix、lineage decision、incremental/full parity、dry-run zero-write 和无 after-market/Runtime wiring。

### Checkpoint E：Task 12 后

检查浏览器无权威公式、无隐藏跨周期请求、forming temporal disclosure、rollover label、preference v9 migration 和无 Alert surface。

### Checkpoint F：Task 14 后

检查 label/outcome 隔离、Pattern Gate、rolling/embargo、product concentration、mapping availability、prospective no-backfill 和研究状态措辞。

---

## 12. Plan 自审结论

经本修正后：

- Range policy 同时支持 D1 ATR100 和 15m ATR500，不把 registry default 冒充唯一公式参数；
- 所有跨层 public signature 有单一精确定义；
- Phase golden 使用可独立复算的固定样本；
- child branch、PR 和 Review checkpoint 不再依赖通用 task 代号；
- open-only、mapping availability、snapshot root、Gold/OOS 外部 Gate 均可直接测试；
- Plan 仍保持个人项目规模，不引入通用策略平台、账户、订单、DB result table、queue、scheduler 或 live evaluator；
- 本轮只完成 Implementation Plan，不开始源码实现。
