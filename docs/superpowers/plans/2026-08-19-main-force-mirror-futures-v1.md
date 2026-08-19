# 主力照妖镜·期货 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `main_force_mirror_futures_v1` as a 60m-only, observation-only futures position-pressure indicator with exact physical-contract resets, five symmetric futures states, bilateral chase-risk cautions, deterministic Python/Web parity, a three-tab Web pane, and a read-only Historical Shadow research entry.

**Architecture:** Python `quant-core` remains the sole formula authority. The Web receives the same Canonical bars, enriches each bar with an exact physical contract, and runs a browser-only mirror constrained by one shared frozen golden fixture; the existing bottom pane switches locally among MACD, Futures V1, and V0 without changing market identity or fetching data. Historical Shadow uses only `MarketDataService`, evaluates outcomes inside one physical-contract segment, and emits stdout JSON without persistence or promotion.

**Tech Stack:** Python 3.13, NumPy, FastAPI service composition, `MarketDataService`, Vue 3, TypeScript 6, Lightweight Charts 5.2, Node test, Playwright, pytest, Ruff, Mypy, Vite.

**Spec:** `docs/superpowers/specs/2026-08-19-main-force-mirror-futures-v1-design.md`

## Global Constraints

- Execution starts from the then-latest clean `origin/develop`; its ancestry must contain Spec-fix commit `a5180f97c5ac6675a6d73e6a48bc837efac8be06`. If the active canonical conflicts with this Plan, stop and revise the Plan instead of guessing.
- Preserve `main_force_mirror_v0` code, version, formula, golden outputs, Registry capabilities, and existing Web behavior. V1 is a new indicator and never silently replaces V0 history.
- V1 exact identity is `main_force_mirror_futures_v1@futures-research-v1`; exact policy is `main_force_mirror_futures_observation_v1`.
- V1 supports only `60m + contract|actual_dominant`. `continuous` and `1m/5m/15m/30m/1d/1w` fail closed; the UI must not silently fall back to V0.
- `open_interest` and `physical_contract` are required inputs. Missing/invalid OI invalidates the whole bar; a legal physical-contract switch starts a fresh block; input/timestamp failure invalidates the offending bar and the next valid block starts later.
- The first state-ready point is block index 20, the first complete caution-ready/ready point is block index 30, `warmup_bars=30`, and `lookback_bars=31`.
- The frozen parameter key is `liquidation_dominated_oi_threshold`; the retired draft name must not appear in executable code, metadata, fixtures, or tests.
- Public numbers use `half_away_from_zero_binary64`; threshold and state decisions use unrounded values. Do not use Python `round()` or JavaScript `toFixed()` as the mathematical implementation.
- `reason` describes base input/state availability; `caution_availability_reason` describes caution warm-up or direction conflict. A state-ready/caution-warm-up point has `reason=null` and `caution_availability_reason=MFM_FUTURES_V1_CAUTION_WARMUP`; a conflict has base `reason=null` and caution reason `MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT`.
- A dual-direction candidate is fail-closed: no directional caution, no Shadow event, neither latch is consumed, and all re-arm counters pause for that bar.
- Re-arm streaks reset directly to zero when their condition is false; warm-up/derived-unavailable/conflict pauses them; input/identity/timestamp failure and physical-contract change reset them with the calculation block.
- Caution markers are Lightweight Charts series markers attached outside the V1 histogram bar. V1 creates no fixed `+92/-92` numeric caution points.
- `70` is an evidence-score threshold, not 70% outflow, a probability, member-position evidence, participant identity, or measured capital flow.
- V1 remains `observation_only`: `web=true`, `backtest=false`, `live=false`, `alert=false`, `notification=false`, `auto_order=false`.
- No Task may add or modify Alert Rule/Scope/evaluator, Clawbot/owner/transport, Execution Review, DB/migration, DatasetKey, the eight-table Market Catalog, Canonical schema/data, Redis state, worker, queue, account, position, or order code.
- Tasks may commit and integrate only into `develop`. `main`, release/tag, Runtime worktrees, Runtime reload/promotion, real notification, real Shadow matrix execution, formal evidence persistence, and production DB/Canonical writes remain separate human Gates.
- Every behavior change follows TDD: observe RED, make the minimum implementation, observe GREEN, then run the scoped regression and review the exact diff.
- `STATUS.md` may be changed only in Task 8 after all repository-native verification and independent review pass; it may record develop-only implementation, never release, Runtime promotion, profitability, or strategy validity.
- Tracked-file changes require `python3 scripts/engineering/secret_scan.py --json` before final closeout.

---

## Codex Task Dispatch Matrix

| Task | Lane | Model | Reasoning | Session | Plan mode | Workspace | Integration Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Python contract, validation, readiness, rounding | Lane 3 | Sol | 高 | 新开会话 | Plan-only, then execute only after Task approval | New task worktree from latest `develop` | Scoped tests + independent formula-contract review |
| 2. Python exact math and five states | Lane 3 | Sol | 高 | 新开会话 | Plan-only, then approved execution | New task worktree from latest `develop` | Exact-math tests + prefix review |
| 3. Caution, conflict, latch, Registry/Policy, V0 guard | Lane 3 | Sol | 高 | 新开会话 | Plan-only, then approved execution | New task worktree from latest `develop` | Independent formula review, Critical=0 / Important=0 |
| 4. Web physical-contract identity propagation | Lane 2 | Terra | 中 | 新开会话 | Plan-then-execute | New task worktree from latest `develop` | Web unit regression |
| 5. Web mirror and shared golden parity | Lane 3 | Sol | 高 | 新开会话 | Plan-only, then approved execution | New task worktree from latest `develop` | Python/Web exact parity review |
| 6. Three-tab pane, dynamic markers, hover | Lane 2 | Terra | 中 | 新开会话 | Plan-then-execute | New task worktree from latest `develop` | Unit + focused Playwright + build |
| 7. Read-only Historical Shadow service and CLI | Lane 1 | Sol | 高 | 新开会话 | Plan-then-execute | New task worktree from latest `develop` | Segment/outcome leakage review |
| 8. Full regression, docs, independent closeout | Lane 3 review | Sol | 高 | 新开独立 Review 会话 | Review-only; code fixes require a new fix Task | New closeout worktree from latest `develop` | Full green suite + Critical=0 / Important=0 |

Task worktree lifecycle:

```text
latest origin/develop
→ task branch/worktree
→ RED/GREEN + scoped verification
→ self-review
→ required independent review
→ task branch → develop
→ read back develop ancestry
→ remove merged task worktree and merged task branch
```

Recommended branch names:

```text
feature/mfm-futures-v1-contracts
feature/mfm-futures-v1-math
feature/mfm-futures-v1-caution-policy
feature/mfm-futures-v1-physical-identity
feature/mfm-futures-v1-web-parity
feature/mfm-futures-v1-web-pane
research/mfm-futures-v1-shadow
docs/mfm-futures-v1-closeout
```

No Task touches `main`, a release worktree, an exact-tag Runtime worktree, or loaded service state.

---

## File Structure

### Create

- `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py` — Python formula authority, validation/block state, exact math, five states, bilateral scoring, latch/re-arm, metadata.
- `services/quant-api/tests/test_main_force_mirror_futures.py` — Python exact-contract, math, readiness, caution, latch, reason, prefix, and V0-regression tests.
- `tests/fixtures/main_force_mirror_futures_v1_golden.json` — single Git-tracked deterministic cross-runtime fixture; test evidence only, never Canonical or production data.
- `apps/quant-web/src/utils/mainForceMirrorFutures.ts` — browser observation mirror and identical rounding/state/latch semantics.
- `apps/quant-web/tests/mainForceMirrorFutures.test.ts` — shared-fixture parity and Web calculation tests.
- `apps/quant-web/e2e/main-force-mirror-futures.spec.mjs` — three-tab, availability, marker, hover, no-refetch, responsive acceptance.
- `services/quant-api/app/market_data/main_force_mirror_futures_research_service.py` — Historical-only, segment-local Shadow orchestration through `MarketDataService`.
- `services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py` — read-path, event, outcome, and no-cross-segment tests.

### Modify

- `packages/quant-core/guiyi_quant/indicators/__init__.py` — export V1 result/types/function only after Task 3 completes.
- `packages/quant-core/guiyi_quant/indicators/registry.py` — register V1 with exact 60m support, parameters, readiness, and capability.
- `packages/quant-core/guiyi_quant/indicators/policy.py` — add exact Web-only observation policy.
- `services/quant-api/tests/test_indicator_registry_v1.py` — replace the global all-seven-frequency assertion with per-indicator contracts and verify V1 blocked consumers.
- `services/quant-api/tests/test_main_force_mirror.py` — retain and assert V0 deterministic output/metadata unchanged.
- `apps/quant-web/src/types/market.ts` — add per-bar physical contract, V1 hover/output types, and secondary-panel identity types.
- `apps/quant-web/src/composables/useMarketSeries.ts` — bind Historical and completed overlay bars to exact physical contracts without guessing.
- `apps/quant-web/tests/marketSeries.test.ts` — contract/actual-dominant/segment/snapshot/bar identity cases.
- `apps/quant-web/src/components/kline/KlineChart.vue` — three local tabs, V1 histogram, dynamic V1 markers, mutual clearing, unsupported-state behavior.
- `apps/quant-web/src/components/kline/KlineHoverLegend.vue` — V1 physical-contract/features/readiness/reason display.
- `apps/quant-web/src/utils/klineViewModel.ts` — timestamp-aligned V1 hover projection.
- `apps/quant-web/src/pages/market/chart.vue` — pass effective `seriesKind` to the chart; no new market request.
- `apps/quant-web/tests/kline-view-model.test.ts` — V1 hover alignment and unavailable rendering.
- `apps/quant-web/e2e/main-force-mirror.spec.mjs` — preserve explicit V0 access under `原型V0`.
- `apps/quant-web/e2e/market-runtime.spec.mjs` — preserve existing Historical/Live/Post-close behavior with enriched bars.
- `services/quant-api/app/market_data/composition.py` — compose the read-only V1 research service.
- `services/quant-api/app/guiyi_cli/research_parser.py` — register the exact read-only CLI command and choices.
- `services/quant-api/app/guiyi_cli/research_commands.py` — immutable request, result rendering, and command dispatch type.
- `services/quant-api/app/guiyi_cli/main.py` — inject/select the V1 research service without changing other research commands.
- `services/quant-api/tests/test_research_cli.py` — parser, JSON, readonly, error, and factory-selection tests.
- `docs/INDICATOR_KERNEL.md` — document implemented V1 exact contract after code is green.
- `TESTING.md` — add focused V1 verification commands.
- `STATUS.md` — Task 8 only, after all verification/review gates pass.

### Explicitly untouched

- `packages/quant-core/guiyi_quant/indicators/main_force_mirror.py`
- Alert application code and tables
- Execution Review code and tables
- Market Catalog/Canonical schema/data
- Runtime/install/launchd files
- `main`, release tags, Runtime worktrees

---

### Task 1: Python Exact Contract, Validation, Readiness, and Rounding

**Lane:** Lane 3. Formula/input contract. Sol/high in a new session; Plan-only until this Task is explicitly approved.

**Files:**
- Create: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- Create: `services/quant-api/tests/test_main_force_mirror_futures.py`

**Interfaces:**
- Consumes: the exact Spec parameters/reasons and NumPy only.
- Produces:
  - `INDICATOR_CODE = "main_force_mirror_futures_v1"`
  - `INDICATOR_VERSION = "futures-research-v1"`
  - immutable `DEFAULT_PARAMETERS`
  - `MainForceMirrorFuturesState`
  - `MainForceMirrorFuturesCaution`
  - frozen `MainForceMirrorFuturesResult`
  - `round_half_away_from_zero_binary64(value: float, digits: int) -> float`
  - `compute_main_force_mirror_futures(datetimes, physical_contract, open_, high, low, close, volume, open_interest) -> MainForceMirrorFuturesResult`
- Task 1 implements validation, block boundaries, ATR/volume/range/OI seed availability, readiness/reason arrays, and public rounding. State/caution numeric output remains unavailable until Tasks 2–3.
- Internal deterministic seams used by Task 2 tests:
  - `_wilder_atr14(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray`
  - `_ema_sma_seed(values: np.ndarray, period: int) -> np.ndarray`

- [ ] **Step 1: Write the shared synthetic-input helpers and RED tests for exact constants/rounding**

Add these test helpers once at the top of `test_main_force_mirror_futures.py`:

```python
from datetime import UTC, datetime, timedelta

def make_valid_inputs(
    count: int,
    contract: str = "JM2609",
) -> dict[str, list[object]]:
    close = [100.0 + index for index in range(count)]
    return {
        "datetimes": [
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
            for index in range(count)
        ],
        "physical_contract": [contract] * count,
        "open_": [value - 0.5 for value in close],
        "high": [value + 1.0 for value in close],
        "low": [value - 1.0 for value in close],
        "close": close,
        "volume": [1000.0 + index for index in range(count)],
        "open_interest": [5000.0 + 10.0 * index for index in range(count)],
    }

def assert_array_prefix_equal(
    full: np.ndarray,
    prefix: np.ndarray,
    count: int,
) -> None:
    assert len(prefix) == count
    for left, right in zip(full[:count], prefix, strict=True):
        if isinstance(left, (float, np.floating)) and np.isnan(left):
            assert isinstance(right, (float, np.floating)) and np.isnan(right)
        else:
            assert left == right
```

Then add assertions equivalent to:

```python
def test_futures_v1_exact_identity_parameters_and_rounding() -> None:
    from guiyi_quant.indicators.main_force_mirror_futures import (
        DEFAULT_PARAMETERS,
        INDICATOR_CODE,
        INDICATOR_VERSION,
        round_half_away_from_zero_binary64,
    )

    assert INDICATOR_CODE == "main_force_mirror_futures_v1"
    assert INDICATOR_VERSION == "futures-research-v1"
    assert DEFAULT_PARAMETERS["liquidation_dominated_oi_threshold"] == 0.5
    assert "closing_dominated_oi_threshold" not in DEFAULT_PARAMETERS
    assert DEFAULT_PARAMETERS["rounding_policy"] == "half_away_from_zero_binary64"
    assert round_half_away_from_zero_binary64(1.25, 1) == 1.3
    assert round_half_away_from_zero_binary64(-1.25, 1) == -1.3
    assert round_half_away_from_zero_binary64(-0.0, 6) == 0.0
```

- [ ] **Step 2: Run the rounding RED test**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k exact_identity_parameters_and_rounding
```

Expected: FAIL because the V1 module does not exist.

- [ ] **Step 3: Implement exact constants and the shared rounding helper**

Use the Spec formula literally:

```python
def round_half_away_from_zero_binary64(value: float, digits: int) -> float:
    if not np.isfinite(value):
        return value
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise ValueError("digits must be a non-negative integer")
    scale = float(10**digits)
    if value == 0:
        return 0.0
    magnitude = np.floor(abs(value) * scale + 0.5) / scale
    result = float(np.copysign(magnitude, value))
    return 0.0 if result == 0 else result
```

Store `DEFAULT_PARAMETERS` behind `MappingProxyType`, preserving the exact key order and values from Spec §5.2.

- [ ] **Step 4: Run the rounding test GREEN**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Write RED tests for input reason priority and block reset**

Build deterministic 60m bars and assert:

```python
def test_oi_failure_is_invalid_and_resets_the_block() -> None:
    payload = make_valid_inputs(63)
    payload["open_interest"][31] = None
    result = compute_main_force_mirror_futures(**payload)

    assert result.reason[31] == "MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE"
    assert not bool(result.valid[31])
    assert not bool(result.state_ready[31])
    assert not bool(result.caution_ready[31])
    assert bool(result.state_ready[52])
    assert bool(result.caution_ready[62])
```

Add separate tests for:
- physical contract missing;
- generic OHLC/volume invalid;
- timestamp parse failure;
- duplicate timestamp;
- timestamp regression;
- a post-regression timestamp still below the historical maximum;
- the first later timestamp above the historical maximum starting block index 0;
- legal contract A→B transition making B’s first bar valid but warm-up.

- [ ] **Step 6: Run validation RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k "invalid or timestamp or contract or oi_failure"
```

Expected: FAIL because validation/block semantics are not implemented.

- [ ] **Step 7: Implement input normalization, reason priority, and maximal blocks**

Implementation requirements:
- process input order without sorting;
- keep `max_seen_parseable_time`;
- normalize physical contract with `str(value).strip().upper()`, accepting only a non-empty result;
- validate all required numeric fields and OHLC/volume/OI relations;
- an invalid/timestamp/OI bar clears all block state and is never a seed;
- a valid physical-contract change clears block state and seeds a new block with the current valid bar;
- reason priority follows Spec §15 exactly;
- return aligned arrays with no fabricated zero observations.

- [ ] **Step 8: Write RED tests for closed-form readiness**

Assert exact zero-based boundaries:

```python
def test_readiness_boundaries_are_exact() -> None:
    result = compute_main_force_mirror_futures(**make_valid_inputs(31))
    assert not bool(result.state_ready[19])
    assert bool(result.state_ready[20])
    assert not bool(result.caution_ready[29])
    assert bool(result.caution_ready[30])
    assert np.array_equal(result.ready, result.caution_ready)
```

Also assert `state_ready=true/caution_ready=false` retains no caution score/event and uses `MFM_FUTURES_V1_CAUTION_WARMUP`.

- [ ] **Step 9: Run readiness RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k readiness
```

Expected: FAIL.

- [ ] **Step 10: Implement ATR14, volume SMA20, OI abs-delta EMA20 seed, range20, and readiness arrays**

Use these first-ready indices:
- ATR: 13;
- volume/range: 19;
- OI impulse: 20;
- state: 20;
- caution/ready: 30.

A derived invalidity (`ATR<=0`, volume mean `<=0`, equal range) pauses output but does not end a raw-valid block.

- [ ] **Step 11: Run all Task 1 tests and Ruff**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_futures.py
```

Expected: PASS.

- [ ] **Step 12: Review and commit Task 1**

```bash
git diff --check
git status --short
git add \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_futures.py
git commit -m "feat(indicators): add futures mirror input contracts"
```

Independent review must verify readiness arithmetic, timestamp maximum handling, and OI whole-bar invalidation before integration to `develop`.

---

### Task 2: Python Exact Math and Five-State Kernel

**Lane:** Lane 3. Formula semantics. Sol/high, new session, Plan-only until approved.

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- Modify: `services/quant-api/tests/test_main_force_mirror_futures.py`

**Interfaces:**
- Consumes Task 1 validation, readiness, rounding, block state, and result shape.
- Produces aligned, rounded public values for ATR-derived price impulse, CLV, direction, volume ratio, OI impulse, range position, pressures, strength, state, and signed score.
- It does not yet emit bilateral caution events; those remain unavailable until Task 3.

- [ ] **Step 1: Add RED tests for exact rolling math**

Use a hand-computable fixture to assert:
- ATR14 Wilder SMA seed at index 13;
- recursive ATR at index 14;
- volume SMA20 at index 19;
- OI abs-delta SMA seed at index 20;
- recursive OI EMA at index 21;
- range position at index 19;
- clipping at ±3.

Example:

```python
def test_atr_and_oi_seed_follow_exact_contract() -> None:
    inputs = make_valid_inputs(22)
    atr = _wilder_atr14(
        np.asarray(inputs["high"], dtype=float),
        np.asarray(inputs["low"], dtype=float),
        np.asarray(inputs["close"], dtype=float),
    )
    oi_delta = np.diff(np.asarray(inputs["open_interest"], dtype=float))
    oi_baseline = _ema_sma_seed(np.abs(oi_delta), 20)

    assert atr[13] == 2.0
    assert atr[14] == 2.0
    assert np.isnan(oi_baseline[18])
    assert oi_baseline[19] == 10.0

    result = compute_main_force_mirror_futures(**inputs)
    assert np.isnan(result.oi_impulse[19])
    assert result.oi_impulse[20] == 1.0
```

- [ ] **Step 2: Run math RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k "atr or volume or impulse or range"
```

Expected: FAIL for missing derived outputs.

- [ ] **Step 3: Implement exact raw math in the Spec order**

For each state-ready bar, calculate from unrounded binary64 inputs:
1. `price_impulse`;
2. `clv`;
3. `direction`;
4. `participation`;
5. `oi_impulse`;
6. `long_open_pressure`;
7. `short_open_pressure`;
8. `strength`.

Apply public rounding only when assigning result arrays.

- [ ] **Step 4: Add RED tests for all five states and boundary equality**

Assert exact deadband semantics:

```python
@pytest.mark.parametrize(
    ("direction", "oi_impulse", "expected"),
    [
        (0.149999, 1.0, "turnover"),
        (0.15, 0.25, "long_build"),
        (-0.15, 0.25, "short_build"),
        (0.15, -0.25, "short_cover"),
        (-0.15, -0.25, "long_liquidation"),
        (1.0, 0.249999, "turnover"),
    ],
)
def test_five_state_boundaries(direction, oi_impulse, expected):
    assert classify_main_force_mirror_futures_state(direction, oi_impulse) == expected
```

Also assert:
- TURNOVER display cap 15;
- `direction==0 → signed_score==0`;
- strength cap 100;
- long/short pressure sign and mutual exclusivity.

- [ ] **Step 5: Run state RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k "state or turnover or strength or pressure"
```

Expected: FAIL.

- [ ] **Step 6: Implement state classification and signed score**

Add:

```python
def classify_main_force_mirror_futures_state(
    direction: float,
    oi_impulse: float,
) -> MainForceMirrorFuturesState:
```

Use strict `< deadband` for TURNOVER so equality at 0.15/0.25 enters the quadrant table. Keep state explanations outside the numerical function.

- [ ] **Step 7: Add prefix-invariance RED/GREEN test**

```python
def test_futures_v1_base_outputs_are_prefix_invariant() -> None:
    full_inputs = make_valid_inputs(80)
    prefix_inputs = {key: values[:60] for key, values in full_inputs.items()}
    full = compute_main_force_mirror_futures(**full_inputs)
    prefix = compute_main_force_mirror_futures(**prefix_inputs)

    for field in (
        "valid",
        "state_ready",
        "caution_ready",
        "ready",
        "reason",
        "state",
        "signed_score",
        "strength",
        "price_impulse",
        "clv",
        "volume_ratio",
        "delta_oi",
        "oi_impulse",
        "direction",
        "range_position",
        "long_open_pressure",
        "short_open_pressure",
    ):
        assert_array_prefix_equal(getattr(full, field), getattr(prefix, field), 60)
```

The comparison covers validity, readiness, reasons, base features, state, strength, and signed score.

- [ ] **Step 8: Run Task 2 scope**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_futures.py
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git diff --check
git add \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_futures.py
git commit -m "feat(indicators): add futures mirror pressure states"
```

Review must compare every formula and equality boundary against Spec §§7–8.

---

### Task 3: Bilateral Caution, Conflict, Latch/Re-arm, Registry/Policy, and V0 Guard

**Lane:** Lane 3. Risk formula and lifecycle semantics. Sol/high, new session, Plan-only until approved.

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `services/quant-api/tests/test_main_force_mirror_futures.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`
- Modify: `services/quant-api/tests/test_main_force_mirror.py`

**Interfaces:**
- Consumes Task 2 state-ready features and pressures.
- Produces:
  - exact long/short reason-code tuples and scores;
  - `is_main_force_mirror_futures_candidate(score: float) -> bool`;
  - frozen latch state/step contracts;
  - conflict fail-closed semantics;
  - final `compute_main_force_mirror_futures`;
  - package exports;
  - Registry/Policy entry.

Define testable immutable latch contracts:

```python
@dataclass(frozen=True)
class MainForceMirrorFuturesLatchState:
    long_armed: bool
    short_armed: bool
    long_low_score_streak: int
    short_low_score_streak: int
    long_build_streak: int
    short_build_streak: int

@dataclass(frozen=True)
class MainForceMirrorFuturesLatchStep:
    state: MainForceMirrorFuturesLatchState
    caution: MainForceMirrorFuturesCaution | None
    reason: str | None
```

- [ ] **Step 1: Write RED tests for the eight evidence reasons and 69/70**

Assert each isolated reason contributes exactly its frozen weight and that:
- score 69 is not a candidate;
- score 70 is a candidate;
- threshold uses raw score, not rounded display score;
- the parameter name is the revised liquidation name.

- [ ] **Step 2: Run evidence RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k "caution_reason or candidate_threshold"
```

Expected: FAIL.

- [ ] **Step 3: Implement exact evidence evaluation**

Implement pure evidence evaluators that receive the current unrounded feature set plus the previous ten state-ready points. Do not compute partial scores before caution readiness. Return reason tuples in fixed Spec order, so Python/Web JSON comparison is stable.

- [ ] **Step 4: Write RED tests for conflict and latch state**

Cover:
- single long/short event consumes only its side;
- conflict emits no event;
- conflict leaves both latch booleans unchanged;
- conflict leaves all four counters unchanged;
- next legal bar triggers immediately;
- event bar clears triggered-side counters;
- non-triggered side continues its own re-arm.

- [ ] **Step 5: Run conflict/latch RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k "conflict or latch"
```

Expected: FAIL.

- [ ] **Step 6: Implement candidate resolution and latch transitions**

The transition order must match Spec §10.1. Conflict assigns `MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT` to `caution_availability_reason`, keeps base `reason` clear, and bypasses all latch/re-arm mutation.

- [ ] **Step 7: Write RED tests for all four re-arm paths and counter resets**

Cover:
- long range;
- long build;
- short range;
- short build;
- false condition resets directly to zero;
- derived-unavailable pauses;
- state-ready/caution-warmup pauses;
- invalid/block change resets;
- armed-side counters remain zero;
- re-arm becomes effective after the current bar.

- [ ] **Step 8: Implement re-arm and integrate it into `compute_main_force_mirror_futures`**

Only caution-ready, non-conflict bars can advance re-arm counters. Keep the long and short sides independent.

- [ ] **Step 9: Add Registry/Policy RED tests**

Assert:

```python
definition = get_indicator("main_force_mirror_futures_v1")
assert definition.supported_intervals == ("60m",)
assert definition.lookback_bars == 31
assert definition.warmup_bars == 30
assert definition.status == "observation_only"
assert definition.web_capable is True
assert definition.backtest_capable is False
assert definition.live_capable is False
assert definition.alert_capable is False
```

Assert the exact parameters and `parameters_hash`. Verify only `Web_manual_observation` is allowed; `formal_backtest/live/alert/notification/auto_order` are blocked.

Replace the old global frequency test with:
- existing Registry entries equal the original seven-frequency tuple;
- V1 equals `("60m",)`.

- [ ] **Step 10: Add V0 regression characterization**

Retain the existing V0 deterministic expected outputs:

```text
20  -0.654814  distribute
21   0.697117  exit
22   1.896099  exit
23  -2.603149  lure
24  -0.181907  lure
25  -2.923248  pull_up
26  -0.584624  lure
27  -2.445683  lure
```

Also assert its indicator version, default parameters, policy, and caution indexes are unchanged.

- [ ] **Step 11: Implement Registry, Policy, and exports**

Add V1 without altering V0 entries. Use `input_fields=("open","high","low","close","volume","open_interest","physical_contract")`, exact 60m support, exact parameters, and interpretation/capability notes.

- [ ] **Step 12: Run Task 3 regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

Expected: PASS.

- [ ] **Step 13: Independent formula review and commit**

Review checklist:
- all four weights and both directions;
- conflict does not consume latch;
- counter reset/pause semantics;
- no V0 diff;
- no forbidden consumer capability.

```bash
git diff --check
git add \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py
git commit -m "feat(indicators): add futures mirror cautions and policy"
```

Critical and Important findings must be zero before integration.

---

### Task 4: Web Physical-Contract Identity Propagation

**Lane:** Lane 2. Ordinary read-model enrichment, no formula change. Terra/medium.

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/composables/useMarketSeries.ts`
- Modify: `apps/quant-web/tests/marketSeries.test.ts`
- Modify: `apps/quant-web/e2e/market-runtime.spec.mjs`

**Interfaces:**
- Consumes existing `MarketBarsPageResponse.request`, `resolved_contract_segments`, and WebSocket snapshot contract.
- Produces:
  - `BarData.physicalContract?: string`;
  - `resolveHistoricalPhysicalContract(page, bar) -> string | undefined`;
  - stable `MarketSeriesPhysicalIdentityError` with code `MFM_FUTURES_V1_SEGMENT_CONFLICT`;
  - Historical and overlay bars enriched without a new HTTP/API field or request.

- [ ] **Step 1: Write RED unit tests for Historical mapping**

Tests:
- `contract` maps every bar to normalized `request.contract`;
- `actual_dominant` maps each bar to exactly one inclusive segment;
- zero segment match leaves `physicalContract` undefined;
- two segment matches throw `MFM_FUTURES_V1_SEGMENT_CONFLICT`;
- `continuous` leaves the field undefined;
- prepend performs the same mapping independently.

- [ ] **Step 2: Run mapping RED**

```bash
cd apps/quant-web
node --test tests/marketSeries.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement Historical physical identity**

Change `toBarData` to accept an optional exact physical contract. Make `mergeInitialPage` and `prependHistoricalPage` map from the page’s own request/segments. Do not infer from the latest dominant or symbol.

- [ ] **Step 4: Write RED tests for completed overlay identity**

Cover:
- snapshot bars use payload contract;
- contract request rejects/makes unavailable a mismatched snapshot contract;
- actual-dominant accepts the exact snapshot contract;
- ordinary `bar` reuses an established overlay contract;
- ordinary `bar` before any snapshot identity receives no physical contract;
- reset/identity change clears overlay identity;
- existing realtime/post-close seam behavior remains unchanged.

- [ ] **Step 5: Implement overlay binding**

Reuse the existing `overlayIdentity.contract`; do not use `marketState.live_contract` as a fallback for an unbound bar. Keep `physicalContract` through normalization, prepend, replace, and live mutations.

- [ ] **Step 6: Run Web unit and focused Market E2E**

```bash
pnpm --dir apps/quant-web test

pnpm --dir apps/quant-web exec playwright test \
  e2e/market-runtime.spec.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git diff --check
git add \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/composables/useMarketSeries.ts \
  apps/quant-web/tests/marketSeries.test.ts \
  apps/quant-web/e2e/market-runtime.spec.mjs
git commit -m "feat(web): bind bars to physical contracts"
```

Review must confirm no new market fetch, no API change, and no physical-contract guessing.

---

### Task 5: Web Mirror and One Shared Python/Web Golden Fixture

**Lane:** Lane 3. Cross-runtime formula parity. Sol/high, new session, Plan-only until approved.

**Files:**
- Create: `tests/fixtures/main_force_mirror_futures_v1_golden.json`
- Create: `apps/quant-web/src/utils/mainForceMirrorFutures.ts`
- Create: `apps/quant-web/tests/mainForceMirrorFutures.test.ts`
- Modify: `services/quant-api/tests/test_main_force_mirror_futures.py`

**Interfaces:**
- Consumes Task 3 Python public contract and Task 4 `BarData.physicalContract`.
- Produces:
  - TypeScript state/caution/result types matching Python names;
  - `roundHalfAwayFromZeroBinary64(value: number, digits: number): number`;
  - `calculateMainForceMirrorFutures(bars: BarData[]): MainForceMirrorFuturesResult`;
  - one shared immutable golden JSON read by both runtimes.

Golden JSON schema:

```json
{
  "schema_version": 1,
  "indicator_code": "main_force_mirror_futures_v1",
  "indicator_version": "futures-research-v1",
  "parameters_hash": "f7fd0c9bce0b08d1",
  "bars": [
    {
      "time": "2026-01-01T01:00:00Z",
      "physical_contract": "JM2609",
      "open": 100.0,
      "high": 102.0,
      "low": 99.0,
      "close": 101.0,
      "volume": 1000.0,
      "open_interest": 5000.0
    }
  ],
  "rounding_cases": [
    {"value": 1.25, "digits": 1, "expected": 1.3},
    {"value": -1.25, "digits": 1, "expected": -1.3}
  ],
  "expected_points": [
    {
      "valid": true,
      "state_ready": false,
      "caution_ready": false,
      "ready": false,
      "reason": "MFM_FUTURES_V1_WARMUP",
      "caution_availability_reason": "MFM_FUTURES_V1_CAUTION_WARMUP",
      "state": null,
      "signed_score": null,
      "strength": null,
      "price_impulse": null,
      "clv": null,
      "volume_ratio": null,
      "delta_oi": null,
      "oi_impulse": null,
      "direction": null,
      "range_position": null,
      "long_open_pressure": null,
      "short_open_pressure": null,
      "long_caution_score": null,
      "short_caution_score": null,
      "caution": null,
      "caution_reason_codes": []
    }
  ]
}
```

The committed fixture must include two contracts, all five states, long/short caution, one conflict, one re-arm, an OI gap, timestamp regression, readiness boundaries, and positive/negative rounding ties.

- [ ] **Step 1: Add Python RED test requiring the absent shared fixture**

The test reads `tests/fixtures/main_force_mirror_futures_v1_golden.json`, calculates Python output, converts non-finite numeric outputs to JSON `null`, and compares every listed field exactly.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  -k shared_golden
```

Expected: FAIL because the fixture does not exist.

- [ ] **Step 3: Create the deterministic input sequence and freeze Python expected output**

Use a one-off local Python command that calls the approved Python Kernel and writes the exact JSON schema. The test itself must never rewrite the fixture. Inspect the resulting diff to confirm the required cases and no sensitive/real market data.

- [ ] **Step 4: Run Python shared-golden GREEN**

Run Step 2 again.

Expected: PASS.

- [ ] **Step 5: Write TypeScript RED parity tests**

Import the same root fixture using `fs.readFileSync(new URL('../../../tests/fixtures/main_force_mirror_futures_v1_golden.json', import.meta.url))`. Assert:
- exact parameter identity;
- every point field;
- ordered reason codes;
- positive/negative tie rounding;
- `-0` normalization;
- threshold decisions remain based on raw values.

- [ ] **Step 6: Run TypeScript RED**

```bash
cd apps/quant-web
node --test tests/mainForceMirrorFutures.test.ts
```

Expected: FAIL because the Web mirror does not exist.

- [ ] **Step 7: Implement the TypeScript mirror**

Mirror the Python operation order and block machine exactly. Use no `toFixed()` in mathematical code. Do not hard-code chart colors or UI text in the business utility.

- [ ] **Step 8: Run parity and full Web unit GREEN**

```bash
cd apps/quant-web
node --test tests/mainForceMirrorFutures.test.ts
cd ../..
pnpm --dir apps/quant-web test

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py
```

Expected: PASS.

- [ ] **Step 9: Independent parity review and commit**

Reviewer compares Python/TypeScript arithmetic order, raw-vs-rounded decisions, reason priority, conflict, and latch behavior.

```bash
git diff --check
git add \
  tests/fixtures/main_force_mirror_futures_v1_golden.json \
  apps/quant-web/src/utils/mainForceMirrorFutures.ts \
  apps/quant-web/tests/mainForceMirrorFutures.test.ts \
  services/quant-api/tests/test_main_force_mirror_futures.py
git commit -m "test(indicators): freeze futures mirror cross-runtime parity"
```

Critical and Important findings must be zero.

---

### Task 6: Three-Tab Pane, Dynamic Markers, and Hover

**Lane:** Lane 2. Web integration. Terra/medium.

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/e2e/main-force-mirror.spec.mjs`
- Create: `apps/quant-web/e2e/main-force-mirror-futures.spec.mjs`

**Interfaces:**
- Consumes Task 5 `calculateMainForceMirrorFutures`.
- Produces secondary panel IDs:
  - `macd`;
  - `main_force_mirror_futures`;
  - `main_force_mirror_v0`.
- Adds `seriesKind: SeriesKind` to `KlineChart` props.
- Adds nullable `mainForceFutures` details to `HoverKlineContext`.
- Keeps MACD selected by default.

- [ ] **Step 1: Write E2E RED for tab order, support, and no refetch**

Test:
- exact labels `MACD`, `主力照妖镜`, `原型V0`;
- MACD selected initially;
- V1 enabled for 60m actual-dominant and contract;
- V1 disabled for 15m and continuous;
- clicking V1/V0/MACD does not add `/bars/page` requests;
- changing identity while V1 is selected and unsupported moves selection to MACD, never V0.

- [ ] **Step 2: Run E2E RED**

```bash
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror-futures.spec.mjs
```

Expected: FAIL.

- [ ] **Step 3: Refactor series names and add local three-tab control**

Rename current V0 variables explicitly (`mainForceV0Histogram`, `mainForceV0Caution`, `mainForceV0Markers`). Add V1 histogram and V1 marker plugin on pane 2. Keep pane count and stretch factors unchanged.

Map V1 colors only through existing theme values:

```text
LONG_BUILD       → theme.up
SHORT_BUILD      → theme.down
SHORT_COVER      → theme.ema21
LONG_LIQUIDATION → theme.macdDif
TURNOVER         → theme.textMuted
```

Do not place colors in `mainForceMirrorFutures.ts`.

- [ ] **Step 4: Add fixed histogram scale without caution points**

Configure the V1 histogram’s `autoscaleInfoProvider` to return `minValue=-105`, `maxValue=105`. The V1 data series contains only signed scores; there is no V1 caution histogram.

- [ ] **Step 5: Write marker RED tests/E2E**

Assert:
- long caution marker is `aboveBar`, `arrowDown`, text `追多小心 {score}`;
- short caution marker is `belowBar`, `arrowUp`, text `追空小心 {score}`;
- conflict draws no directional marker;
- marker creation does not add a ±92 data point;
- a strength-100 bar keeps the fixed histogram scale.

- [ ] **Step 6: Implement dynamic V1 markers**

Create markers from the V1 observation and attach them to the V1 histogram with `createSeriesMarkers`. Clear V1 markers whenever another tab is selected.

- [ ] **Step 7: Write hover RED tests**

Add a V1 hover object containing:
- physical contract;
- state;
- state/caution readiness;
- strength;
- price impulse;
- volume ratio;
- delta OI;
- OI impulse;
- range position;
- long/short scores;
- reason codes;
- availability reason.

Assert missing values format as `—`.

- [ ] **Step 8: Implement timestamp-aligned hover projection**

Keep generic OHLC/EMA behavior unchanged. `KlineChart` stores the current V1 result and passes the matching point into `resolveKlineHoverContext`; the legend shows V1 fields only on the V1 tab.

- [ ] **Step 9: Add legend/status copy**

V1 legend includes:

```text
70 = 风险证据评分阈值，不是资金流比例或概率
```

Differentiate:
- unsupported identity;
- OI/input unavailable;
- state warm-up;
- caution warm-up;
- conflict;
- ready.

No missing value becomes zero.

- [ ] **Step 10: Preserve V0 under `原型V0`**

Update the existing V0 E2E so its original bars/caution/legend remain accessible and deterministic. The label move must not modify V0 calculation or tests.

- [ ] **Step 11: Run Web verification**

```bash
pnpm --dir apps/quant-web test

pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs \
  e2e/main-force-mirror-futures.spec.mjs \
  e2e/market-runtime.spec.mjs

pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 12: Responsive review and commit**

Verify 1440×900, 1280×720, and 1024×768 have no horizontal overflow.

```bash
git diff --check
git add \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/kline/KlineHoverLegend.vue \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/kline-view-model.test.ts \
  apps/quant-web/e2e/main-force-mirror.spec.mjs \
  apps/quant-web/e2e/main-force-mirror-futures.spec.mjs
git commit -m "feat(web): add futures main-force mirror pane"
```

---

### Task 7: Read-Only Historical Shadow Service and CLI

**Lane:** Lane 1 with Sol/high because segment-local outcomes and future-horizon accounting require leakage review.

**Files:**
- Create: `services/quant-api/app/market_data/main_force_mirror_futures_research_service.py`
- Create: `services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**
- Consumes `MarketDataService` and Python V1 only.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesResearchRequest:
    symbol: str
    series_kind: SeriesKind
    contract: str | None
    frequency: BarFrequency
    since: date
    through: date

@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesEvent:
    indicator_code: str
    indicator_version: str
    parameters_hash: str
    symbol: str
    series_kind: SeriesKind
    physical_contract: str
    trading_day: date
    bar_end: datetime
    caution_direction: str
    score: float
    reason_codes: tuple[str, ...]
    state: str

@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesHorizonSummary:
    horizon_bars: int
    sample_count: int
    reversal_returns: tuple[float, ...]
    warning_mfe: tuple[float, ...]
    warning_mae: tuple[float, ...]

@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesResearchResult:
    products: tuple[str, ...]
    bars_valid_count: int
    bars_state_ready_count: int
    bars_caution_ready_count: int
    event_count_long: int
    event_count_short: int
    conflict_count: int
    missing_oi_count: int
    segment_reset_count: int
    timestamp_invalid_count: int
    state_distribution: Mapping[str, int]
    reason_code_distribution: Mapping[str, int]
    score_distribution: tuple[int, ...]
    horizon_summary: Mapping[int, MainForceMirrorFuturesHorizonSummary]

MainForceMirrorFuturesResearchService.run(
    request: MainForceMirrorFuturesResearchRequest
) -> MainForceMirrorFuturesResearchResult
```

The method signature above is the exact public contract. Task 7 supplies the complete implementation before merge.

- [ ] **Step 1: Write request-validation RED tests**

Reject:
- frequency other than 60m;
- continuous;
- contract without contract code;
- actual-dominant with a contract argument;
- invalid symbol/date order.

- [ ] **Step 2: Write MarketDataService-only RED tests**

Use a fake implementing `query(SeriesQuery)` and `query_actual_dominant_trading_days(ActualDominantTradingDayQuery)`. Assert the service does not accept a Parquet path, store, provider, Redis, or DB writer.

- [ ] **Step 3: Run service RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py
```

Expected: FAIL.

- [ ] **Step 4: Implement exact Historical read orchestration**

- `actual_dominant`: use `query_actual_dominant_trading_days` for 60m and the returned resolved segments.
- `contract`: use `SeriesQuery` through `MarketDataService.query`.
- bind every bar to one physical contract;
- run Python V1 once over the aligned sequence;
- never fabricate a segment or bridge a gap.

- [ ] **Step 5: Write event/outcome RED tests**

Cover:
- long/short events only when Kernel caution is directional;
- conflict count increments but creates no event;
- horizons 1/3/5/10;
- exact long/short mirrored formulas;
- insufficient future bars produce no sample for that horizon;
- physical-contract change before `t+h` makes that outcome unavailable;
- event identity contains exact code/version/hash/contract/time/reasons/state.

- [ ] **Step 6: Implement event extraction and segment-local outcomes**

Use only bars after the event for outcomes; never feed forward outcomes back into event creation. This separation is required for prefix invariance and leakage safety.

- [ ] **Step 7: Write CLI RED tests**

Exact command:

```text
guiyi research main-force-mirror-futures
  --symbol jm
  --series-kind actual_dominant
  --frequency 60m
  --since 2023-01-01
  --through 2026-08-18
```

Contract mode requires `--contract`. JSON asserts:
- `command="research.main-force-mirror-futures"`;
- `readonly=true`;
- no `promotion`, `recommendation`, or profitability field;
- stable counts/distributions/horizon schema;
- factory selection does not affect existing research commands.

- [ ] **Step 8: Implement parser, request union, renderer, composition, and CLI selection**

Add a dedicated injected factory to `guiyi_cli.main.main`. Do not overload the SuBing lifecycle or candidate-validation service.

- [ ] **Step 9: Run Task 7 tests, Ruff, and Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/main_force_mirror_futures_research_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data/main_force_mirror_futures_research_service.py \
  services/quant-api/app/guiyi_cli
```

Expected: PASS.

- [ ] **Step 10: Leakage/identity review and commit**

Reviewer checks that:
- only `MarketDataService` reads data;
- outcomes stay within one segment;
- future bars affect only outcome metrics, never caution creation;
- real representative-matrix research was not run;
- no persistence/promotion path exists.

```bash
git diff --check
git add \
  services/quant-api/app/market_data/main_force_mirror_futures_research_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "feat(research): add futures mirror shadow analysis"
```

---

### Task 8: Full Regression, Documentation, Independent Review, and Develop Closeout

**Lane:** Lane 3 review. Sol/high in a fresh independent Review session.

**Files:**
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `TESTING.md`
- Modify: `STATUS.md` only after all verification/review gates pass.

**Interfaces:**
- Consumes the integrated Tasks 1–7 on latest `develop`.
- Produces repository-native verification evidence, accurate canonical docs, and a develop-only status statement.
- Task 8 does not make production-code fixes. A failure opens a targeted fix Task and ends with `FULL_VERIFICATION_FAILED`.

- [ ] **Step 1: Verify ancestry and exact scope**

```bash
git fetch origin
git checkout develop
git pull --ff-only origin develop
git merge-base --is-ancestor a5180f97c5ac6675a6d73e6a48bc837efac8be06 HEAD
git status --short
```

Expected: ancestor check exit 0 and clean status.

- [ ] **Step 2: Run the focused Python indicator matrix**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: PASS.

- [ ] **Step 3: Run full backend and engineering tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  tests/engineering
```

Expected: PASS. PostgreSQL tests run only with an explicitly isolated test database satisfying `TESTING.md`; never use the Runtime/production database.

- [ ] **Step 4: Run Ruff and Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app \
  services/quant-api/tests \
  packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/app/api/execution_review.py
```

Expected: PASS.

- [ ] **Step 5: Run Web unit, E2E, and production build**

```bash
pnpm --dir apps/quant-web test

pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs \
  e2e/main-force-mirror-futures.spec.mjs \
  e2e/market-runtime.spec.mjs \
  e2e/market-research.spec.mjs \
  e2e/alert-v1.spec.mjs

pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 6: Run safety and diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected:
- secret `finding_count=0`;
- no diff errors;
- only Task 8 documentation changes, if any.

- [ ] **Step 7: Update canonical documentation**

`docs/INDICATOR_KERNEL.md` records:
- V1 exact identity/status/support;
- required inputs and physical-contract reset;
- first state-ready/complete-ready indices;
- five states and bilateral score;
- conflict/latch/rounding contract;
- no measured fund-flow claim;
- no formal consumer capability;
- shared golden fixture path.

`TESTING.md` records the focused commands from Steps 2 and 5.

- [ ] **Step 8: Conduct independent final review**

New Review session compares Spec, Plan, all diffs, tests, and forbidden boundaries. Required result:

```text
Critical = 0
Important = 0
```

Minor findings are either fixed in a separate reviewed commit or explicitly accepted as non-behavioral.

- [ ] **Step 9: Update `STATUS.md` only after Steps 1–8 pass**

Allowed wording:

```text
develop 已完成 main_force_mirror_futures_v1 的 60m Web observation
实现与仓库原生验证；V0 保持不变。V1 仍为 observation_only，
未进入 Alert、notification、正式 backtest、Runtime consumer 或订单路径。
本次未运行真实代表矩阵 Shadow，未形成策略有效性或晋升结论。
```

Do not claim release, tag, Runtime promotion, production deployment, profitability, or formal evidence.

- [ ] **Step 10: Commit and integrate closeout**

```bash
git add docs/INDICATOR_KERNEL.md TESTING.md STATUS.md
git commit -m "docs: close futures main-force mirror v1 on develop"
```

After integration:
- read back `develop` ancestry;
- remove the merged closeout worktree/branch;
- leave `main`, tags, and Runtime unchanged.

---

## Plan Self-Review Record

### Spec coverage

- Indicator identity, capability, parameters, support set: Tasks 1 and 3.
- Closed-form readiness and OI/timestamp/block rules: Task 1.
- Exact math and five states: Task 2.
- Bilateral evidence, conflict, latch, re-arm: Task 3.
- Physical-contract mapping: Task 4.
- Binary64 round and Python/Web parity: Task 5.
- Three tabs, dynamic markers, hover, unsupported states: Task 6.
- Historical Shadow/outcomes/CLI: Task 7.
- Full regression, documentation, independent Review, develop-only status: Task 8.
- V0 zero-change guard and forbidden capability paths: Tasks 3 and 8.

### Placeholder scan

This Plan contains no reserved placeholder tokens or undefined cross-task shorthand. Every Task identifies exact files, interfaces, RED/GREEN commands, and commit boundary.

### Type consistency

The following names are fixed across Tasks:
- `MainForceMirrorFuturesResult`
- `MainForceMirrorFuturesState`
- `MainForceMirrorFuturesCaution`
- `compute_main_force_mirror_futures`
- `round_half_away_from_zero_binary64`
- `calculateMainForceMirrorFutures`
- `roundHalfAwayFromZeroBinary64`
- `MainForceMirrorFuturesResearchRequest`
- `MainForceMirrorFuturesResearchResult`
- secondary panel IDs `macd`, `main_force_mirror_futures`, `main_force_mirror_v0`.

Any implementation that changes these names must update the Plan before code integration.
