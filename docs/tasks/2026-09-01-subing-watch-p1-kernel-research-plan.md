# P1 — 苏冰盯盘 15m 内核、Current 与 Historical 诊断计划

> **Execution:** Use TDD. Every formula behavior starts RED, then GREEN, then minimal REFACTOR.

状态：`PLAN_READY_FOR_USER_REVIEW`

父计划：`docs/tasks/2026-09-01-alert-reliability-subing-watch-15m-implementation-plan.md`

Issue：`#286`

Lane：Lane 3 formula / causal data identity。

## Goal

实现 `subing_watch_15m_v1` 的唯一 completed-15m 增量公式 authority、context-only 标签、actual-dominant Historical/Current/restore parity 和只读诊断。P1 不接 Alert Rule、不写 Event、不写 Redis、不发送通知。

## Workspace

```text
base: P0 合入后的最新 origin/develop
branch: feature/subing-watch-kernel-research
worktree: 新 task worktree
integration: develop
PR: Draft PR required
review: independent Sol/high formula checkpoint
human Gate: 允许集成 develop
```

## Numeric Boundary

现有 Quant Core `step_ema`、`step_macd`、`step_atr` 使用 finite `float | int` 数值。本任务不得为了 Watch 全局改写这些公共接口。

固定边界：

```text
CanonicalBar / application domain price and volume = Decimal
single adapter to kernel = validated finite float
Quant Core rolling state and points = float, round_digits=6
application SubingWatchEvaluation = Decimal restored from canonical rounded text
identity, candidate_id and dedupe = never derived from float values
```

因此：

- `SubingWatchKernelBar` 和 `SubingWatchKernelEvaluation` 位于 Quant Core，数值字段使用 `float`；
- `SubingWatchEvaluation` 位于应用层 `contracts.py`，公开数值字段使用 `Decimal`；
- 唯一转换函数 `to_subing_watch_kernel_bar(CanonicalBar)` 校验 Decimal 有限、OHLC 顺序和范围后转换；
- `from_kernel_evaluation` 使用固定六位十进制文本恢复 `Decimal`；
- 不允许多个调用点各自做 float/Decimal 转换。

## File Map

### New

```text
data/research_policies/subing_watch_15m_v1.json
packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py
services/quant-api/app/market_data/subing_watch/__init__.py
services/quant-api/app/market_data/subing_watch/contracts.py
services/quant-api/app/market_data/subing_watch/replay.py
services/quant-api/app/market_data/subing_watch/current_service.py
services/quant-api/app/research/subing/subing_watch_research_service.py
services/quant-api/tests/fixtures/subing_watch_15m_v1_golden.json
services/quant-api/tests/test_subing_watch_formula.py
services/quant-api/tests/research/test_subing_watch_replay.py
services/quant-api/tests/data_foundation/test_subing_watch_current_service.py
services/quant-api/tests/research/test_subing_watch_report.py
services/quant-api/tests/research/test_subing_watch_research_service.py
services/quant-api/tests/research/test_subing_watch_cli.py
```

### Modified

```text
packages/quant-core/guiyi_quant/indicators/__init__.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/research/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/research/test_research_cli_parser_requests.py
```

## Task 1 — Freeze exact policy and typed contracts

### Exact policy

Create `data/research_policies/subing_watch_15m_v1.json`:

```json
{
  "schema_version": 1,
  "formula_version": "subing_watch_15m_v1",
  "policy_id": "subing_watch_15m_v1",
  "series_kind": "actual_dominant",
  "frequency": "15m",
  "completed_bar_only": true,
  "ma": {
    "type": "simple_moving_average",
    "period": 21,
    "source": "close"
  },
  "macd": {
    "fast": 12,
    "slow": 26,
    "signal": 9,
    "ema_seed_policy": "sma_window",
    "histogram_scale": 2
  },
  "context": {
    "atr_period": 14,
    "atr_smoothing_policy": "wilder_sma_seed",
    "ma_slope_points": 5,
    "volume_previous_bars": 20,
    "range_indicator_code": "range_detector_lux_v1",
    "higher_timeframe": "60m"
  },
  "round_digits": 6,
  "auto_order": false
}
```

Any missing/extra field, type drift or value drift raises:

```text
SubingWatchPolicyError("SUBING_WATCH_POLICY_INVALID")
```

### Quant Core contracts

Create in `packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py`:

```python
SUBING_WATCH_FORMULA_VERSION = "subing_watch_15m_v1"

@dataclass(frozen=True, slots=True)
class SubingWatchKernelIdentity:
    symbol: str
    contract: str
    segment_start_trading_day: str
    series_kind: Literal["actual_dominant"] = "actual_dominant"
    frequency: Literal["15m"] = "15m"

@dataclass(frozen=True, slots=True)
class SubingWatchKernelBar:
    bar_end: str
    trading_day: str
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True, slots=True)
class SubingWatchKernelHigherTimeframe:
    bar_end: str
    close: float | None
    ma21: float | None
    ma21_slope_5_bps_per_bar: float | None
    ready: bool
    valid: bool

@dataclass(frozen=True, slots=True)
class SubingWatchKernelContext:
    ma21_slope_5_bps_per_bar: float | None
    distance_to_ma21_atr14: float | None
    macd_zero_distance_atr14: float | None
    volume_ratio_20: float | None
    range_state: Literal[
        "range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"
    ]
    higher_timeframe_alignment: Literal[
        "aligned", "opposed", "neutral", "unavailable"
    ]

@dataclass(frozen=True, slots=True)
class SubingWatchKernelEvaluation:
    formula_version: str
    identity: SubingWatchKernelIdentity
    trading_day: str
    bar_end: str
    outcome: Literal[
        "evaluated_no_signal", "evaluated_candidate", "source_unavailable"
    ]
    observation_types: tuple[Literal["buy", "sell"], ...]
    close: float | None
    ma21: float | None
    dif: float | None
    dea: float | None
    macd_histogram: float | None
    context: SubingWatchKernelContext
    public_reason_codes: tuple[str, ...]
```

`SubingWatchKernelState` is immutable and bounded. It may contain only policy/identity, rolling SMA21, latest five valid SMA21 values, existing Quant Core MACD/ATR/Range states, previous ready DIF/DEA, previous 20 volumes, last Bar fingerprint/evaluation and a fail-closed blocked reason.

### Application contracts

Create in `services/quant-api/app/market_data/subing_watch/contracts.py`:

```python
@dataclass(frozen=True, slots=True)
class SubingWatchSourceIdentity:
    symbol: str
    contract: str
    segment_start_trading_day: date
    series_kind: Literal["actual_dominant"] = "actual_dominant"
    frequency: Literal["15m"] = "15m"

@dataclass(frozen=True, slots=True)
class SubingWatchEvaluation:
    formula_version: str
    source_identity: SubingWatchSourceIdentity
    source_identity_digest: str
    trading_day: date
    bar_end: datetime
    source_mode: Literal["canonical", "canonical_live"]
    outcome: Literal[
        "evaluated_no_signal", "evaluated_candidate", "source_unavailable", "processing_failed"
    ]
    observation_types: tuple[Literal["buy", "sell"], ...]
    close: Decimal | None
    ma21: Decimal | None
    dif: Decimal | None
    dea: Decimal | None
    macd_histogram: Decimal | None
    context: SubingWatchContext
    candidate_id: str | None
    public_reason_codes: tuple[str, ...]
```

Add exactly one adapter pair:

```python
def to_subing_watch_kernel_bar(bar: CanonicalBar) -> SubingWatchKernelBar: ...
def from_kernel_evaluation(
    evaluation: SubingWatchKernelEvaluation,
    *,
    source_mode: Literal["canonical", "canonical_live"],
) -> SubingWatchEvaluation: ...
```

### RED tests

```python
def test_policy_pins_sma21_and_macd_seed() -> None:
    policy = load_subing_watch_policy(POLICY_PATH)
    assert policy.ma_type == "simple_moving_average"
    assert policy.ma_period == 21
    assert policy.macd == (12, 26, 9)
    assert policy.ema_seed_policy == "sma_window"
    assert policy.histogram_scale == 2
    assert policy.auto_order is False


def test_policy_rejects_ema21_drift(tmp_path: Path) -> None:
    payload = json.loads(POLICY_PATH.read_text())
    payload["ma"]["type"] = "exponential_moving_average"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SubingWatchPolicyError, match="SUBING_WATCH_POLICY_INVALID"):
        load_subing_watch_policy(path)


def test_decimal_float_boundary_is_single_and_deterministic() -> None:
    kernel = to_subing_watch_kernel_bar(canonical_bar(close=Decimal("123.4567894")))
    assert kernel.close == 123.4567894
    app = from_kernel_evaluation(kernel_evaluation(ma21=123.456789), source_mode="canonical")
    assert app.ma21 == Decimal("123.456789")
```

Also cover invalid symbol, contract mismatch, non-aware time, non-15m frequency, `auto_order=true`, unknown policy field, NaN/Inf conversion and OHLC ordering.

### RED / GREEN / commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  -k "policy or identity or decimal_float"
```

Implement exact JSON validation, private bounded rolling SMA state and the single numeric adapter. Do not change generic EMA/MACD/ATR public types or Registry capabilities.

```bash
git add \
  data/research_policies/subing_watch_15m_v1.json \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/app/market_data/subing_watch/contracts.py \
  services/quant-api/tests/test_subing_watch_formula.py
git commit -m "feat(indicators): freeze SuBing Watch policy"
```

## Task 2 — Implement the only completed-15m incremental formula

### Public interface

```python
def initial_subing_watch_kernel_state(
    identity: SubingWatchKernelIdentity,
    policy: SubingWatchPolicy,
) -> SubingWatchKernelState: ...

def step_subing_watch_15m(
    state: SubingWatchKernelState,
    bar: SubingWatchKernelBar,
    *,
    higher_timeframe: SubingWatchKernelHigherTimeframe | None = None,
) -> tuple[SubingWatchKernelState, SubingWatchKernelEvaluation]: ...
```

### Fixed per-Bar order

```text
1. validate identity, aware ISO bar_end, finite OHLCV and OHLC ordering;
2. detect same-Bar duplicate before mutation;
3. return unavailable when state is blocked;
4. advance private SMA21 using close;
5. advance MACD 12/26/9 via existing step_macd;
6. derive exact golden/dead cross from previous ready DIF/DEA and current values;
7. derive BUY/SELL using current close versus current SMA21;
8. calculate context separately;
9. save current ready DIF/DEA for the next Bar;
10. freeze rounded output.
```

Exact truth table:

```text
golden = previous_dif <= previous_dea and current_dif > current_dea
dead   = previous_dif >= previous_dea and current_dif < current_dea
buy    = golden and close > sma21
sell   = dead and close < sma21
```

`close == SMA21` produces no Candidate. BUY and SELL cannot both be true.

Invalid completed input cannot be skipped. It produces `source_unavailable`, sets a blocked reason and prevents recursive continuation until deterministic restore or a new physical-segment state.

Same `bar_end` + same fingerprint is idempotent and returns the frozen prior evaluation. Same `bar_end` + different OHLCV raises `SUBING_WATCH_DUPLICATE_CONFLICT`.

### RED matrix

- first ready golden/dead cross;
- previous equality allowed, current equality not cross;
- close above/below/equal SMA21;
- warm-up and first segment Bar;
- invalid/non-finite input;
- duplicate/conflict;
- identity mismatch;
- cross-contract comparison forbidden;
- batch/incremental parity;
- every prefix stable;
- future-tail invariance;
- candidate ID stability at application boundary.

Candidate ID is generated after application conversion from identity/time/type only:

```text
sha256(formula_version + symbol + contract + segment_start_trading_day + frequency + bar_end + observation_type)
```

No float value participates in the ID.

### Golden fixture

`services/quant-api/tests/fixtures/subing_watch_15m_v1_golden.json` contains complete policy, identity, input bars, expected kernel points, expected application evaluations and a real `payload_sha256`. Include warm-up, no-signal, buy, sell, equality and duplicate cases. Expected values are committed, not generated by the code under test.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_range_detector_lux.py

git add \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  services/quant-api/app/market_data/subing_watch/contracts.py \
  services/quant-api/tests/fixtures/subing_watch_15m_v1_golden.json \
  services/quant-api/tests/test_subing_watch_formula.py
git commit -m "feat(indicators): add SuBing Watch kernel"
```

## Task 3 — Implement context-only facts and prove non-suppression

Exact formulas:

```text
ma21_slope_5_bps_per_bar
= linear-regression slope of latest 5 valid SMA21 points / current SMA21 × 10000

distance_to_ma21_atr14
= (close - SMA21) / ATR14

macd_zero_distance_atr14
= max(abs(DIF), abs(DEA)) / ATR14

volume_ratio_20
= current volume / mean(previous 20 completed 15m volumes)
```

Range maps existing causal state to:

```text
range_unavailable
no_active_range
intact
broken_up
broken_down
```

60m alignment uses latest completed same-contract 60m Bar with `bar_end <= 15m cutoff`:

```text
aligned: price side and SMA21 slope support Candidate direction
opposed: both support opposite direction
neutral: any other ready combination
unavailable: missing/not-ready/invalid/identity mismatch
```

Required test:

```python
@pytest.mark.parametrize(
    "case",
    [
        "all_ready",
        "atr_unavailable",
        "volume_denominator_zero",
        "range_unavailable",
        "higher_timeframe_missing",
        "higher_timeframe_opposed",
    ],
)
def test_context_never_suppresses_base_candidate(case: str) -> None:
    state, bar, higher = candidate_fixture(case)
    _, evaluation = step_subing_watch_15m(state, bar, higher_timeframe=higher)
    assert evaluation.outcome == "evaluated_candidate"
    assert evaluation.observation_types == ("buy",)
```

A 60m Bar after cutoff raises `SUBING_WATCH_HIGHER_TIMEFRAME_FUTURE`. Missing context renders unavailable. `volume_ratio_20` excludes current volume and zero denominator is unavailable.

Calculate observation before context projection. Context exceptions cannot change Candidate.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py

git add \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  services/quant-api/tests/test_subing_watch_formula.py
git commit -m "feat(indicators): add Watch context facts"
```

## Task 4 — Historical replay, Current projection and restore parity

### Files

```text
services/quant-api/app/market_data/subing_watch/__init__.py
services/quant-api/app/market_data/subing_watch/replay.py
services/quant-api/app/market_data/subing_watch/current_service.py
services/quant-api/app/market_data/composition.py
services/quant-api/tests/research/test_subing_watch_replay.py
services/quant-api/tests/data_foundation/test_subing_watch_current_service.py
```

### Interfaces

```python
def replay_subing_watch_segment(
    identity: SubingWatchSourceIdentity,
    bars_15m: tuple[CanonicalBar, ...],
    completed_60m: tuple[CanonicalBar, ...],
    policy: SubingWatchPolicy,
) -> SubingWatchSegmentProjection: ...

class SubingWatchCurrentProjectionService:
    def current(self, request: SubingWatchCurrentRequest, now: datetime) -> SubingWatchProjection: ...
    def restore_state(self, symbol: str, now: datetime) -> SubingWatchRestoreState: ...
```

Replay is a thin physical-segment loop over `to_subing_watch_kernel_bar -> step_subing_watch_15m -> from_kernel_evaluation`. It must not use pandas, `ewm`, `rolling`, a second CROSS or Web formula.

For each MainContractMap rank1 segment:

```text
new state
completed 15m in order
latest same-contract completed 60m strict-before/equal cutoff
one kernel step
immutable application evaluation
```

Do not prepend an earlier contract for warm-up.

Current merges Canonical/completed Live only through existing services. Live contract must match frozen physical segment. It never writes Event/cache/Canonical.

Tests:

- one kernel step per Bar;
- two segments reset state;
- current at cutoff equals Historical replay;
- restore then Live append equals full replay;
- 60m future/mismatch unavailable but non-gating;
- Canonical/Live duplicate idempotency;
- conflicting overlap fail-closed;
- missing MainContractMap/partition/identity fail-closed.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  services/quant-api/tests/research/test_subing_watch_replay.py \
  services/quant-api/tests/data_foundation/test_subing_watch_current_service.py \
  services/quant-api/tests/data_foundation/test_market_read_service.py

git add \
  services/quant-api/app/market_data/subing_watch \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/research/test_subing_watch_replay.py \
  services/quant-api/tests/data_foundation/test_subing_watch_current_service.py
git commit -m "feat(market): add SuBing Watch projections"
```

## Task 5 — Read-only diagnostics and CLI

CLI:

```bash
guiyi research subing-watch \
  --symbols jm,ag,rb,eg \
  --since 2024-01-01 \
  --through 2026-08-31 \
  --forward-bars 1,2,4,8 \
  --format json
```

Rules:

- explicit through required;
- stdout JSON by default;
- no cache/publish/write flag;
- no RQData connection;
- `--symbols active` reads only active_products;
- sorted deterministic output.

Report includes Candidate counts, direction, daily clustering, session distribution, context availability, Range/60m distributions and optional retrospective 1/2/4/8-Bar close change/MFE/MAE. Forward diagnostics never enter Candidate, Runtime or policy and do not create PnL/winner/promotion claims.

Tests cover exact shape, deterministic order, empty sample, denominator zero, future-tail truncation and forbidden CLI mutation flags.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_watch_report.py \
  services/quant-api/tests/research/test_subing_watch_research_service.py \
  services/quant-api/tests/research/test_subing_watch_cli.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py

git add \
  services/quant-api/app/research/subing/subing_watch_research_service.py \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/research/test_subing_watch_report.py \
  services/quant-api/tests/research/test_subing_watch_research_service.py \
  services/quant-api/tests/research/test_subing_watch_cli.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py
git commit -m "feat(research): add SuBing Watch diagnostics"
```

## Packet Verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  services/quant-api/tests/research/test_subing_watch_replay.py \
  services/quant-api/tests/data_foundation/test_subing_watch_current_service.py \
  services/quant-api/tests/research/test_subing_watch_report.py \
  services/quant-api/tests/research/test_subing_watch_research_service.py \
  services/quant-api/tests/research/test_subing_watch_cli.py

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  services/quant-api/app/market_data/subing_watch \
  services/quant-api/app/research/subing/subing_watch_research_service.py

uv run --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  services/quant-api/app/market_data/subing_watch \
  services/quant-api/app/research/subing/subing_watch_research_service.py \
  services/quant-api/tests/test_subing_watch_formula.py \
  services/quant-api/tests/research/test_subing_watch_replay.py \
  services/quant-api/tests/data_foundation/test_subing_watch_current_service.py
```

## Independent Formula Review

Pin exact head and check:

- SMA21 vs EMA21;
- Decimal/application versus float/Quant Core boundary is single and deterministic;
- MACD seed and CROSS equality;
- invalid input blocking/restore;
- physical-segment reset;
- context-only non-suppression;
- 60m strict-before;
- batch/incremental/prefix/future-tail/restore parity;
- golden/policy digests;
- no second formula in replay/CLI/Web;
- no Alert/Runtime/migration/send change.

PR stops at `允许集成 develop`. Any real Historical run needs a separately defined read-only environment and through-date permission.
