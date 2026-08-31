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

### Files

- Create: `data/research_policies/subing_watch_15m_v1.json`
- Create: `packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test: `services/quant-api/tests/test_subing_watch_formula.py`

### Exact policy

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

### Public contracts

```python
SUBING_WATCH_FORMULA_VERSION = "subing_watch_15m_v1"

@dataclass(frozen=True, slots=True)
class SubingWatchSourceIdentity:
    symbol: str
    contract: str
    segment_start_trading_day: date
    series_kind: Literal["actual_dominant"] = "actual_dominant"
    frequency: Literal["15m"] = "15m"

@dataclass(frozen=True, slots=True)
class SubingWatchBarInput:
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

@dataclass(frozen=True, slots=True)
class SubingWatchHigherTimeframeInput:
    bar_end: datetime
    close: Decimal | None
    ma21: Decimal | None
    ma21_slope_5_bps_per_bar: Decimal | None
    ready: bool
    valid: bool

@dataclass(frozen=True, slots=True)
class SubingWatchContext:
    ma21_slope_5_bps_per_bar: Decimal | None
    distance_to_ma21_atr14: Decimal | None
    macd_zero_distance_atr14: Decimal | None
    volume_ratio_20: Decimal | None
    range_state: Literal[
        "range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"
    ]
    higher_timeframe_alignment: Literal[
        "aligned", "opposed", "neutral", "unavailable"
    ]

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

`SubingWatchState` must be immutable and bounded. It may contain only policy/identity, rolling SMA21 state, latest five valid MA21 values, existing Quant Core MACD/ATR/Range states, previous ready DIF/DEA, previous 20 volumes, last Bar fingerprint/evaluation and a fail-closed blocked reason.

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
```

Also cover invalid symbol, contract/symbol mismatch, non-aware time, non-15m frequency, `auto_order=true`, unknown fields and wrong numeric types.

### Run RED

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  -k "policy or identity"
```

Expected: module/contracts missing.

### GREEN implementation

- Implement exact JSON validation and stable digest.
- Implement a private bounded rolling SMA state; do not create a second general indicator platform.
- Export only Watch public contracts/functions from `indicators/__init__.py`.
- Do not change generic MACD Registry `live_capable/alert_capable`; Watch policy is the scoped authority.

### Verify and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  -k "policy or identity"

git add \
  data/research_policies/subing_watch_15m_v1.json \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/tests/test_subing_watch_formula.py
git commit -m "feat(indicators): freeze SuBing Watch policy"
```

## Task 2 — Implement the only completed-15m incremental formula

### Files

- Modify: `packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py`
- Create: `services/quant-api/tests/fixtures/subing_watch_15m_v1_golden.json`
- Modify: `services/quant-api/tests/test_subing_watch_formula.py`

### Public interface

```python
def initial_subing_watch_state(
    identity: SubingWatchSourceIdentity,
    policy: SubingWatchPolicy,
) -> SubingWatchState: ...

def step_subing_watch_15m(
    state: SubingWatchState,
    bar: SubingWatchBarInput,
    *,
    source_mode: Literal["canonical", "canonical_live"],
    higher_timeframe: SubingWatchHigherTimeframeInput | None = None,
) -> tuple[SubingWatchState, SubingWatchEvaluation]: ...
```

### Fixed per-Bar order

```text
1. validate exact identity, timezone, finite OHLCV and OHLC ordering;
2. detect same-Bar duplicate before mutation;
3. reject/return unavailable when state is blocked;
4. advance SMA21 using close;
5. advance MACD 12/26/9 via existing step_macd;
6. derive exact golden/dead cross from previous ready DIF/DEA and current values;
7. derive BUY/SELL using current close versus current SMA21;
8. calculate context separately;
9. save current ready DIF/DEA for the next Bar;
10. freeze rounded output and candidate_id.
```

Exact truth table:

```text
golden = previous_dif <= previous_dea and current_dif > current_dea
dead   = previous_dif >= previous_dea and current_dif < current_dea
buy    = golden and close > sma21
sell   = dead and close < sma21
```

`close == SMA21` produces no Candidate. BUY and SELL cannot both be true.

Invalid completed input cannot be skipped. It produces `source_unavailable`, sets a blocked reason and prevents recursive continuation until deterministic restore or new physical-segment initialization.

Same `bar_end` + same fingerprint is idempotent and returns the frozen prior evaluation. Same `bar_end` + different OHLCV raises `SUBING_WATCH_DUPLICATE_CONFLICT`.

### RED matrix

- first ready golden cross;
- first ready dead cross;
- previous equality allowed, current equality not cross;
- close above/below/equal SMA21;
- warm-up and first physical-segment Bar;
- invalid/non-finite OHLCV;
- same duplicate and conflicting duplicate;
- identity mismatch;
- cross-contract previous Bar forbidden;
- source mode validation;
- candidate ID stability and field sensitivity.

Candidate ID uses stable SHA-256 over:

```text
formula_version
symbol
contract
segment_start_trading_day
frequency
bar_end
observation_type
```

### Golden fixture

`subing_watch_15m_v1_golden.json` contains complete values for:

```text
schema_version
formula_version
parameters
source_identity
bars
expected evaluations
payload_sha256
```

The digest is computed over every top-level field except `payload_sha256`, stable sorted-key compact UTF-8 JSON. Include complete warm-up, no-signal, buy, sell, equality and duplicate cases. No ellipsis or generated-at-test expected values.

### Prefix tests

```python
@pytest.mark.parametrize("prefix_length", range(1, GOLDEN_BAR_COUNT + 1))
def test_each_prefix_is_stable(prefix_length: int) -> None:
    full = run_incremental(FIXTURE)
    prefix = run_incremental(FIXTURE, stop=prefix_length)
    assert prefix == full[:prefix_length]


def test_future_tail_cannot_change_frozen_prefix() -> None:
    original = run_incremental(FIXTURE)
    mutated = run_incremental(mutate_only_future_tail(FIXTURE))
    assert mutated[:FROZEN_PREFIX] == original[:FROZEN_PREFIX]
```

### Verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_range_detector_lux.py
```

Commit:

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py \
  services/quant-api/tests/fixtures/subing_watch_15m_v1_golden.json \
  services/quant-api/tests/test_subing_watch_formula.py
git commit -m "feat(indicators): add SuBing Watch kernel"
```

## Task 3 — Implement context-only facts and prove non-suppression

### Files

- Modify: `packages/quant-core/guiyi_quant/indicators/subing_watch_15m.py`
- Modify: `services/quant-api/tests/test_subing_watch_formula.py`

### Exact context formulas

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

`range_state` reads the existing causal Range Detector state and maps to:

```text
range_unavailable
no_active_range
intact
broken_up
broken_down
```

60m alignment uses the latest completed same-contract 60m Bar whose `bar_end <= 15m cutoff`:

```text
aligned: price side and SMA21 slope both support Candidate direction
opposed: both support opposite direction
neutral: any other ready combination
unavailable: missing/not-ready/invalid/identity mismatch
```

### Required non-suppression test

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
    _, evaluation = step_subing_watch_15m(
        state, bar, source_mode="canonical", higher_timeframe=higher
    )
    assert evaluation.outcome == "evaluated_candidate"
    assert evaluation.observation_types == ("buy",)
```

A 60m Bar after the Candidate cutoff raises `SUBING_WATCH_HIGHER_TIMEFRAME_FUTURE`. Missing context renders `None`/`unavailable`; it never becomes false alignment or no active range.

`volume_ratio_20` excludes current volume from the denominator. Zero denominator yields unavailable, not zero or infinity.

Calculate `observation_types` before context projection. Context exceptions are mapped to unavailable context without changing Candidate.

### Verification and commit

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

- Create: `services/quant-api/app/market_data/subing_watch/__init__.py`
- Create: `services/quant-api/app/market_data/subing_watch/contracts.py`
- Create: `services/quant-api/app/market_data/subing_watch/replay.py`
- Create: `services/quant-api/app/market_data/subing_watch/current_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Test: `services/quant-api/tests/research/test_subing_watch_replay.py`
- Test: `services/quant-api/tests/data_foundation/test_subing_watch_current_service.py`

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

Replay loops over the exact kernel step. It must not use pandas, `ewm`, `rolling`, a second CROSS or a Web formula.

For each MainContractMap rank1 physical segment:

```text
initialize new Watch state
iterate completed 15m in order
select latest same-contract completed 60m strict-before/equal cutoff
call step_subing_watch_15m
append immutable evaluation
```

Do not prepend an earlier contract for warm-up. Every Candidate carries exact contract and `segment_start_trading_day`.

Current projection merges Canonical and completed Live only through existing services. Live contract must match frozen current physical segment. It never writes state, Event, cache or Canonical.

### Parity tests

- replay calls one incremental step per Bar;
- two physical segments reset state;
- current at cutoff equals Historical replay at same cutoff;
- restore then Live append equals full replay;
- future 60m unavailable but does not suppress Candidate;
- duplicated Canonical/Live same Bar is idempotent;
- conflicting overlap fails closed;
- missing MainContractMap/partition/source identity fails closed.

### Verification and commit

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

### Files

- Create: `services/quant-api/app/research/subing/subing_watch_research_service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Test: `services/quant-api/tests/research/test_subing_watch_report.py`
- Test: `services/quant-api/tests/research/test_subing_watch_research_service.py`
- Test: `services/quant-api/tests/research/test_subing_watch_cli.py`
- Modify: `services/quant-api/tests/research/test_research_cli_parser_requests.py`

### CLI

```bash
guiyi research subing-watch \
  --symbols jm,ag,rb,eg \
  --since 2024-01-01 \
  --through 2026-08-31 \
  --forward-bars 1,2,4,8 \
  --format json
```

Rules:

- explicit `through` required;
- default stdout JSON;
- no cache/publish/write flag;
- no RQData connection;
- `--symbols active` only reads `active_products.txt`;
- output sorted and deterministic.

Report includes:

```text
formula_version
source_identity_digest
window
per-product Candidate count
buy/sell count
candidates per trading day
same-direction clustering
session distribution
context availability rate
range_state distribution
higher_timeframe_alignment distribution
optional retrospective 1/2/4/8-Bar close change, MFE and MAE
```

Forward diagnostics never enter Candidate, Runtime or policy. They do not create thresholds, rank, winner, promotion or PnL claims. Truncating the future tail removes diagnostics only; Candidate identities remain unchanged.

### Verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_watch_report.py \
  services/quant-api/tests/research/test_subing_watch_research_service.py \
  services/quant-api/tests/research/test_subing_watch_cli.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py
```

Commit:

```bash
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

Independent Sol/high reviewer pins exact head and checks:

- SMA21 vs EMA21;
- MACD seed and exact CROSS equality boundaries;
- invalid input poisoning/restore behavior;
- physical-segment reset and no cross-contract warm-up;
- context-only non-suppression;
- 60m strict-before;
- batch/incremental/prefix/future-tail/restore parity;
- golden fixture and policy digest;
- no second formula in replay, CLI or Web;
- no Alert/Runtime/migration/send change.

PR stops at `允许集成 develop`. After integration, delete task worktree/branch. No production data read is required for code completion; any real Historical run needs a separately defined read-only environment and through-date permission.
