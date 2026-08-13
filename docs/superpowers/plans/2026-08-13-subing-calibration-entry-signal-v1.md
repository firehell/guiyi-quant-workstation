# SuBing Calibration and Entry Signal V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Factor Observation 已独立验收后，建立可重复、只读的 5m/15m Calibration Research，经过人工 Gate 将最小 intraday Calibration 固化为 Git 事实，再交付确定性的 `MATCHED LONG/SHORT` 入场 Signal；1d 保持非阻塞研究轨，Alert V2 仍不实现。

**Architecture:** 历史研究只通过 `MarketDataService` 获取 actual-dominant 结果，并按 `resolved_contract_segments` 将 bars 切成互不继承状态的 rank1 segment；每个 segment 单独调用已有 `calculate_subing_factor_series()`，再生成 3/5/8K future labels 与聚合报告。研究 CLI 只向 stdout 输出 JSON、不写 DB/Canonical/报告文件；只有人工批准后的最小 Calibration 才写入 `data/research_policies/` 并由 `SubingReadService` 注入 pure Signal evaluator。

**Tech Stack:** Python 3 / argparse unified `guiyi` CLI / Decimal / SQLAlchemy read session / MarketDataService / quant-core policy registry / FastAPI / Vue 3 / TypeScript / Vitest / Playwright / Git-tracked JSON policy artifact.

## Global Constraints

- 前置条件：`docs/superpowers/plans/2026-08-13-subing-factor-observation-v1.md` 已全部通过并独立 Review。
- 设计事实源：`docs/superpowers/specs/2026-08-13-subing-factor-signal-research-design.md`。
- 5m/15m 是主路径；1d Calibration/Signal Research 不阻塞 intraday Signal。
- 所有历史研究只读 `MarketDataService`；不得直接读 Catalog 表、Parquet、Redis、RQData 或写 Canonical。
- 每个 rank1 segment 独立计算 EMA/MACD/Slope；不得跨 segment 继承 indicator state，不得取 pre-rank1 数据补 warm-up。
- 5m/15m 3/5/8K future labels 不跨 `trading_day`，也不跨 rank1 segment。
- Slope 必须先于 MACD Zero-Band；禁止联合优化两个阈值。
- 第一轮 Slope 与 Zero-Band 都从 timeframe-wide threshold 开始；Zero-Band 使用 `zero_distance_bps`，不预建 product×timeframe 全矩阵。
- Discovery 只提出候选；Validation 使用人工冻结的精确阈值。系统不得自动选择“最优”或自动晋升。
- Accepted Calibration 必须 Git-tracked、versioned、human-reviewable；聊天、临时 CLI 参数、stdout 报告或 localStorage 不得驱动正式 Signal。
- Generic `macd` registry 继续保持 `compatibility_validated/live_capable=False/alert_capable=False`；本计划通过独立、明确命名的 scoped FormalPolicy 批准 SuBing confirmed Signal consumer，不做全局 MACD capability 晋升。
- Formal Signal 只有 `status == MATCHED && direction in {LONG, SHORT}`；`RESEARCH_PENDING` 不是 Signal。
- 不实现持仓、退出、8K、止损止盈、Backtest、Alert V2、WeCom、DB migration、Runtime switch 或任何订单。
- Alert V1 代码、表、Scope、Runtime 和 WeCom sender 必须保持原样。

---

## File Map

**Create**
- `services/quant-api/app/market_data/subing_calibration.py` — pure future-label、统计聚合、accepted calibration schema/loader。
- `services/quant-api/app/market_data/subing_calibration_service.py` — MarketDataService-only historical segment research orchestration。
- `services/quant-api/tests/test_subing_calibration.py` — labels、bucket/candidate、artifact validation tests。
- `services/quant-api/tests/data_foundation/test_subing_calibration_service.py` — rank1 segment isolation and discovery/validation tests。
- `services/quant-api/app/guiyi_cli/research_parser.py` — read-only research CLI parser。
- `services/quant-api/app/guiyi_cli/research_commands.py` — calibration command execution/output mapping。
- `services/quant-api/tests/test_research_cli.py` — no-side-effect CLI contract tests。
- `data/research_policies/subing_calibration_intraday_v1.json` — **只在最终人工 Calibration Gate 后创建**，包含精确批准值；不得提前创建示例 production 文件。
- `services/quant-api/tests/fixtures/subing_calibration_test_v1.json` — test-only deterministic calibration values。

**Modify**
- `services/quant-api/app/guiyi_cli/main.py` — add read-only `research` domain。
- `services/quant-api/app/market_data/subing_research.py` — add policy/calibration-aware Signal evaluator and same-boundary resolver。
- `packages/quant-core/guiyi_quant/indicators/policy.py` — add scoped `subing_macd_sma_window_scale2_v1` formal Signal policy after Gate review。
- `docs/INDICATOR_KERNEL.md` — document scoped SuBing MACD Signal policy without globally promoting generic MACD。
- `services/quant-api/app/market_data/subing_read_service.py` — inject accepted calibration and expose Signal evaluation。
- `services/quant-api/app/market_data/composition.py` — load tracked calibration artifact into `SubingReadService`。
- `services/quant-api/app/schemas/market.py` — add Signal DTO to SuBing response。
- `services/quant-api/app/api/market.py` — serialize Signal evaluation, endpoint identity unchanged。
- `services/quant-api/tests/test_subing_research.py` — Signal condition/resolver tests。
- `services/quant-api/tests/data_foundation/test_subing_read_service.py` — accepted/pending calibration integration tests。
- `services/quant-api/tests/test_subing_api.py` — Signal HTTP contract tests。
- `apps/quant-web/src/types/market.ts` — Signal response types。
- `apps/quant-web/src/api/market.ts` — carry Signal fields through existing normalization。
- `apps/quant-web/src/components/market/SubingStatusStrip.vue` — matched/pending/not-matched display。
- `apps/quant-web/src/components/market/SubingResearchSection.vue` — Signal condition explanation without adding trade-management UI。
- `apps/quant-web/tests/subingResearch.test.ts` — Signal display tests。
- `apps/quant-web/e2e/market-research.spec.mjs` — matched Signal Web regression。
- `TESTING.md` — add calibration/signal read-only commands and tests。
- `docs/ARCHITECTURE.md` — record Calibration Research + accepted Git fact + pure Signal boundary after implementation exists。
- `STATUS.md` — only after all code/test gates actually pass; no Alert/Runtime Ready claim。

---

### Task 1: Build segment-local future labels and deterministic Calibration statistics

**Files:**
- Create: `services/quant-api/app/market_data/subing_calibration.py`
- Create: `services/quant-api/tests/test_subing_calibration.py`

**Interfaces:**
- Consumes: `SubingFactorResult`, `SubingFactorSnapshot` from `subing_research.py`.
- Produces: `DirectionalSide`, `SubingOutcome`, `SubingResearchSample`, `ThresholdEvaluation`, `CalibrationReport`.
- Produces: `build_research_samples(...)`, `evaluate_threshold(...)`, `candidate_quantiles(...)`.

- [ ] **Step 1: Write failing tests for 3/5/8K labels and hard boundaries**

Use explicit test bars and assert exact bps semantics:

```python
def test_long_three_bar_outcome_uses_close_high_low_and_same_day_only():
    samples = build_research_samples(factor_results, bars, horizons=(3, 5, 8))
    sample = samples[0]
    assert sample.direction is DirectionalSide.LONG
    assert sample.outcomes[3].directional_return_bps == Decimal("300")
    assert sample.outcomes[3].mfe_bps == Decimal("500")
    assert sample.outcomes[3].mae_bps == Decimal("-200")


def test_intraday_horizon_becomes_unavailable_at_trading_day_boundary():
    samples = build_research_samples(factor_results, bars, horizons=(3, 5, 8))
    assert samples[-2].outcomes[3] is None
```

Add mirrored SHORT tests and a rank1 segment boundary case where a following bar with another `segment_start_trading_day` must not satisfy the horizon.

- [ ] **Step 2: Run focused tests and confirm the module is missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_calibration.py
```

Expected: FAIL on missing module/types.

- [ ] **Step 3: Implement exact research label formulas**

Use next-N bars **after** the sample bar. For entry close `C0` and direction sign `s` (`+1` long, `-1` short):

```python
directional_return_bps = s * (future_n.close - C0) / C0 * Decimal(10000)
```

MFE/MAE:

```python
# LONG
mfe_bps = (max(highs) - C0) / C0 * Decimal(10000)
mae_bps = (min(lows) - C0) / C0 * Decimal(10000)

# SHORT
mfe_bps = (C0 - min(lows)) / C0 * Decimal(10000)
mae_bps = (C0 - max(highs)) / C0 * Decimal(10000)
```

Thus MFE is non-negative when price moves favorably and MAE is non-positive when price moves adversely.

`ema21_failure=True` when any future Factor snapshot inside the horizon has confirmed close below EMA21 for LONG or above EMA21 for SHORT.

For 5m/15m, require all N future bars to have the same `trading_day`, `contract`, and `segment_start_trading_day`; otherwise outcome is `None`. For 1d require same contract/segment only.

- [ ] **Step 4: Define the Slope research cohort without inventing a flat threshold**

A sample is eligible for Slope discovery when:

```text
LONG baseline:
price_side == ABOVE
slope_5_bps_per_bar > 0
slope_10_bps_per_bar > 0

SHORT baseline:
price_side == BELOW
slope_5_bps_per_bar < 0
slope_10_bps_per_bar < 0
```

The studied scalar is `abs(slope_5_bps_per_bar)`. No flat threshold is used to create this cohort.

- [ ] **Step 5: Implement candidate quantiles and threshold evaluation with bounded memory**

`candidate_quantiles(values)` is used only on one product at a time. Compute inclusive P10/P20/P30 using the stdlib `statistics.quantiles(..., n=100, method="inclusive")` when there are at least two values; one value returns that value for all three quantiles; zero values returns no candidates.

Global discovery candidates are **not** chosen here. The service task will take the median of each product's P10/P20/P30, preserving equal product weight rather than allowing the most active products to dominate.

`evaluate_threshold(samples, threshold, selector)` returns sample count and, for each available horizon, count, median directional return, median MFE, median MAE and EMA21 failure rate. It must not rank candidates or return `best`.

- [ ] **Step 6: Run pure Calibration tests**

Run the new file; expected PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: add SuBing calibration research math"
```

---

### Task 2: Build MarketDataService-only historical Calibration orchestration

**Files:**
- Create: `services/quant-api/app/market_data/subing_calibration_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_calibration_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`

**Interfaces:**
- Produces: `CalibrationResearchRequest` and `SubingCalibrationResearchService.run(request)`.
- Request fields: `phase`, `mode`, `frequency`, `since`, `through`, optional `symbol`, optional explicit thresholds.
- The service performs no writes and never uses `MarketReadService`/Redis.

- [ ] **Step 1: Write failing tests proving segment isolation**

Construct a fake `MarketDataService.query(ACTUAL_DOMINANT)` response containing two `ResolvedContractSegment`s with a large rollover price gap. Assert the service calls `calculate_subing_factor_series()` separately per segment and never generates an outcome whose future bars cross from segment A to B.

Also assert requests outside `1d|5m|15m` are rejected and `since > through` fails before any data read.

- [ ] **Step 2: Run focused tests and confirm the service is missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py
```

Expected: FAIL on missing module/types.

- [ ] **Step 3: Implement a trading-day-safe MarketDataService query window**

Resolve the outer UTC query window from Shanghai trading-day dates so night-session bars belonging to `since` are included, then filter returned bars by `bar.trading_day`:

```python
_SHANGHAI = ZoneInfo("Asia/Shanghai")

def _research_window(since: date, through: date) -> tuple[datetime, datetime]:
    start = datetime.combine(since - timedelta(days=1), time.min, _SHANGHAI).astimezone(UTC)
    end = datetime.combine(through + timedelta(days=1), time.max, _SHANGHAI).astimezone(UTC)
    return start, end
```

Query:

```python
result = self._market_data.query(
    SeriesQuery(
        SeriesKind.ACTUAL_DOMINANT,
        symbol,
        frequency,
        start,
        end,
    )
)
```

Filter bars to `since <= trading_day <= through` before segment processing.

- [ ] **Step 4: Split the returned bars strictly by `resolved_contract_segments` before indicators**

For each segment:

```python
segment_bars = tuple(
    bar for bar in result.bars
    if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
)
```

Assert each selected bar lies in the segment and call `calculate_subing_factor_series(segment_bars, contract=segment.contract, segment_start_trading_day=segment.start_trading_day, ...)` **once per segment**. Never concatenate factor state between segments.

The actual-dominant query is only the MarketDataService facade selecting the correct physical rank1 bars; no consumer may direct-read Catalog/Parquet.

- [ ] **Step 5: Implement Slope discovery/validation modes**

`phase="slope", mode="discovery"`:
1. Process one product at a time.
2. Build its eligible Slope samples.
3. Calculate product P10/P20/P30 of `abs(slope_5_bps_per_bar)`.
4. Discard its raw rows before the next product.
5. Global candidate A/B/C = median across available product P10/P20/P30 respectively.
6. Second read pass evaluates those three fixed candidates across products and aggregates outcomes.
7. Return all three candidate rows; never choose one.

`phase="slope", mode="validation"` requires an explicit `slope_threshold_bps` and evaluates only that threshold on the requested later time window.

- [ ] **Step 6: Implement Zero-Band discovery/validation modes**

Zero-Band always requires an explicit human-approved `slope_threshold_bps` from the earlier Gate.

Cohort A: all confirmed MACD crosses with valid Factor snapshots.

Cohort B requires every other SuBing hard condition except zero-band:

```text
primary price side matches direction
primary slope_5 passes explicit flat threshold
primary slope_10 sign matches direction
primary volume_ratio_prev >= 3 for 5m/15m
companion relationship is not part of this historical single-series Calibration service
```

Because full 5m↔15m companion reconstruction would couple two historical streams into Calibration complexity, V1 Zero-Band report must label this cohort `primary_context_cohort`, not claim full SuBing multi-TF qualification. Final Signal still requires companion alignment in the live/read model.

Discovery uses per-product P20/P40/P60 of `macd_zero_distance_bps`, then median-across-products to form three timeframe-wide candidate bands and evaluates all three. Validation requires explicit `zero_band_bps` and evaluates only `distance_bps <= zero_band_bps`.

Do not create product overrides in this task.

- [ ] **Step 7: Add composition builder and run tests**

Add:

```python
def build_subing_calibration_research_service(session: Session) -> SubingCalibrationResearchService:
    return SubingCalibrationResearchService(
        market_data=build_market_data_service(session),
        products=load_active_products(),
    )
```

Run the new tests plus `test_market_research.py`; expected PASS and no Redis/provider construction.

- [ ] **Step 8: Commit Task 2**

```bash
git add services/quant-api/app/market_data/subing_calibration_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/app/market_data/composition.py
git commit -m "feat: add SuBing calibration research service"
```

---

### Task 3: Expose a read-only, reproducible Calibration CLI

**Files:**
- Create: `services/quant-api/app/guiyi_cli/research_parser.py`
- Create: `services/quant-api/app/guiyi_cli/research_commands.py`
- Create: `services/quant-api/tests/test_research_cli.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`

**Interfaces:**
- Command:
  `guiyi research subing-calibration --phase {slope,zero-band} --mode {discovery,validation} --frequency {5m,15m,1d} --since YYYY-MM-DD --through YYYY-MM-DD [--symbol X] [--slope-threshold-bps DECIMAL] [--zero-band-bps DECIMAL]`.
- stdout JSON only; zero DB/Canonical/Redis/RQData writes.

- [ ] **Step 1: Write parser/command tests for the exact mode matrix**

Require:

```text
slope discovery       -> no threshold accepted/required
slope validation      -> --slope-threshold-bps required
zero-band discovery   -> --slope-threshold-bps required, zero-band threshold forbidden
zero-band validation  -> both --slope-threshold-bps and --zero-band-bps required
```

`--symbol` is optional; omitted means active 60. Invalid frequency or negative threshold exits with code 2 and the existing redacted CLI argument payload.

- [ ] **Step 2: Run CLI tests and confirm `research` domain is missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py
```

Expected: FAIL because parser/domain is not registered.

- [ ] **Step 3: Add the `research` parser without changing data/runtime semantics**

Implement `add_research_commands()` in `research_parser.py`. Parse dates with `date.fromisoformat`, thresholds with `Decimal`, reject non-finite/negative values before service construction.

- [ ] **Step 4: Add read-only command execution**

`research_commands.py` builds `CalibrationResearchRequest` and returns `report.as_payload()` with:

```text
schema_version
phase
mode
frequency
since
through
products
sample_count
product_sample_counts
candidate_thresholds      # discovery only
threshold_evaluation      # validation or each discovery candidate
cohort_name               # zero-band only
```

No field may be named `best_threshold`, `recommended_trade`, or `approved`.

- [ ] **Step 5: Wire `guiyi_cli.main` with injected research-service factory**

Add a `research` branch parallel to `data` and `runtime`. `readonly=True` must be used for execution errors. Existing `data` and `runtime` parser tests must remain unchanged.

- [ ] **Step 6: Run CLI regressions**

Run `test_research_cli.py`, `test_alert_cli.py`, and the data CLI tests referenced by `TESTING.md`; expected PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "feat: add read-only SuBing calibration CLI"
```

---

### Gate A: Human approval of the intraday Slope candidate

This is a **hard stop**, not an implementation step.

Run Discovery separately for 5m and 15m over the chosen Discovery window. Review all candidate rows, product coverage and outcome stability. Then run Validation on a later non-overlapping window with the exact candidate under review.

The plan must not choose the threshold. Continue only after the user explicitly approves exact Decimal values for both:

```text
5m slope_flat_threshold_bps_per_bar
15m slope_flat_threshold_bps_per_bar
```

Do not create the accepted Calibration artifact yet; these approved Slope values become explicit inputs to Zero-Band research.

---

### Task 4: Complete Zero-Band research with the approved Slope thresholds

**Files:**
- Primarily execution of the already implemented read-only CLI.
- Modify code/tests only if a genuine correctness bug is found; do not tune methodology to make results look better.

**Interfaces:**
- Inputs are the exact Gate A slope thresholds.
- Output remains research report JSON; no accepted artifact yet.

- [ ] **Step 1: Run 5m Zero-Band Discovery with the exact approved 5m Slope threshold**

Use the chosen Discovery window and capture stdout for review. Verify report records the exact slope threshold and `cohort_name`.

- [ ] **Step 2: Run 15m Zero-Band Discovery with the exact approved 15m Slope threshold**

Same requirements as Step 1.

- [ ] **Step 3: Human-select one 5m and one 15m Zero-Band candidate**

The system presents candidate bands but does not select them. Stop until the user names the exact candidate values to validate.

- [ ] **Step 4: Run later-window Validation for both exact Zero-Band candidates**

Use non-overlapping later windows and explicit `--zero-band-bps`. Do not change Slope values during Zero-Band validation.

- [ ] **Step 5: Present the two validation reports for Gate B**

Do not commit research stdout and do not update runtime state.

---

### Gate B: Human approval of final intraday Calibration

Hard stop. Continue only after the user explicitly approves all four exact Decimal values:

```text
5m slope_flat_threshold_bps_per_bar
15m slope_flat_threshold_bps_per_bar
5m macd_zero_band_bps
15m macd_zero_band_bps
```

If any value changes after Validation, create a new candidate and rerun the relevant later-window validation before approval.

---

### Task 5: Persist the accepted intraday Calibration as a minimal Git fact

**Files:**
- Create after Gate B: `data/research_policies/subing_calibration_intraday_v1.json`
- Create: `services/quant-api/tests/fixtures/subing_calibration_test_v1.json`
- Modify: `services/quant-api/app/market_data/subing_calibration.py`
- Modify: `services/quant-api/tests/test_subing_calibration.py`

**Interfaces:**
- Produces: `SubingCalibration`, `load_subing_calibration(path)`, `pending_subing_calibration()`.
- Initial production artifact accepts exactly 5m and 15m; 1d remains pending.

- [ ] **Step 1: Add a test-only calibration fixture with explicit non-production values**

Create `services/quant-api/tests/fixtures/subing_calibration_test_v1.json` using these values **only for deterministic tests**:

```json
{
  "schema_version": 1,
  "calibration_id": "subing_test_intraday_v1",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {"5m": "1.25", "15m": "0.80"},
  "macd_zero_band_bps": {"5m": "12.50", "15m": "8.00"}
}
```

No production code may use this fixture.

- [ ] **Step 2: Write failing loader tests**

Test successful load, missing file -> pending object, unknown schema -> fail closed, non-finite/negative values -> fail, missing accepted timeframe value -> fail, and `1d` lookup -> pending/unaccepted.

- [ ] **Step 3: Implement the calibration value object and loader**

```python
@dataclass(frozen=True, slots=True)
class SubingCalibration:
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]
    macd_zero_band_bps: Mapping[BarFrequency, Decimal]

    def is_accepted(self, timeframe: BarFrequency) -> bool: ...
```

Use immutable mappings (`MappingProxyType`) and no environment override. Missing production artifact returns `pending_subing_calibration()`; malformed existing artifact raises a stable configuration error rather than silently downgrading.

- [ ] **Step 4: Create the production artifact with the exact Gate B values**

Create `data/research_policies/subing_calibration_intraday_v1.json` with:
- `schema_version=1`
- `calibration_id="subing_calibration_intraday_v1"`
- `accepted_timeframes=["5m","15m"]`
- exact four Decimal strings approved at Gate B.

Do not include 1d, product overrides, timestamps, performance claims or research output rows.

- [ ] **Step 5: Run loader tests and inspect the artifact diff manually**

Expected: PASS. Confirm the only production values are the four approved numbers.

- [ ] **Step 6: Commit Task 5**

```bash
git add data/research_policies/subing_calibration_intraday_v1.json \
  services/quant-api/tests/fixtures/subing_calibration_test_v1.json \
  services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: accept SuBing intraday calibration v1"
```

This commit is the repository fact that authorizes later Signal code to consume those values; it does not authorize Alert or Runtime.

---

### Task 6: Pass the MACD formal Signal capability Gate with a scoped policy

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py` only if needed to assert generic registry remains unpromoted.

**Interfaces:**
- Produces formal policy ID: `subing_macd_sma_window_scale2_v1`.
- Allows consumer: `subing_signal` only.
- Does **not** grant generic MACD live/alert/backtest capability.

- [ ] **Step 1: Write failing scoped-policy tests**

Require:

```python
policy = require_formal_policy(
    "subing_macd_sma_window_scale2_v1",
    consumer="subing_signal",
)
assert policy.seed_policy == "sma_window"
assert policy.histogram_scale == 2

with pytest.raises(ValueError):
    require_formal_policy("subing_macd_sma_window_scale2_v1", consumer="alert")
```

Also assert `get_indicator("macd").status == "compatibility_validated"`, `live_capable is False`, `alert_capable is False`.

- [ ] **Step 2: Add edge/golden tests proving the scoped policy matches the already observed MACD math**

Cover:
- first ready DIF/DEA index;
- equality edge for Golden/Dead cross;
- historical and completed-live identical close sequence produces identical `macd_series` points;
- no repaint of earlier points when one later confirmed close is appended.

- [ ] **Step 3: Run tests and confirm missing formal policy**

Expected: FAIL on unknown `subing_macd_sma_window_scale2_v1`.

- [ ] **Step 4: Add the scoped policy without changing generic `macd` definition**

```python
"subing_macd_sma_window_scale2_v1": FormalPolicy(
    policy_id="subing_macd_sma_window_scale2_v1",
    indicator_family="MACD",
    seed_policy="sma_window",
    smoothing_policy=None,
    histogram_scale=2,
    lookback="fast12_slow26_signal9",
    confirmed_only=True,
    frozen_legacy=False,
    allowed_consumers=("subing_signal",),
    blocked_consumers=(FORMAL_BACKTEST_CONSUMER, "alert", "notification", "generic_live"),
    notes="Scoped confirmed MACD policy approved only for SuBing V1 entry-signal evaluation; generic MACD registry capability remains unchanged.",
),
```

- [ ] **Step 5: Update Indicator deep canonical**

Document that this is a scoped SuBing Signal consumer policy, not a global promotion of `macd`, and Alert V2 would require a separate capability decision.

- [ ] **Step 6: Run full indicator regressions**

Run all Indicator Kernel commands listed in `docs/INDICATOR_KERNEL.md`; expected PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add packages/quant-core/guiyi_quant/indicators/policy.py \
  docs/INDICATOR_KERNEL.md \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py
git commit -m "feat: approve scoped SuBing MACD signal policy"
```

---

### Task 7: Implement deterministic intraday Entry Signal evaluation and resolver

**Files:**
- Modify: `services/quant-api/app/market_data/subing_research.py`
- Modify: `services/quant-api/tests/test_subing_research.py`

**Interfaces:**
- Produces: `SubingSignalStatus`, `SubingDirection`, `ConditionState`, `SubingSignalEvaluation`, `ResolvedSubingSignal`.
- Produces: `evaluate_subing_signal(primary, companion, calibration)` and `resolve_subing_signals(five_minute, fifteen_minute)`.

- [ ] **Step 1: Write failing Signal condition tests with the test calibration fixture**

Cover exact LONG and SHORT paths, hard failure, pending 1d, insufficient Factor, companion conflict and same-boundary resolution.

Required assertions:

```python
result = evaluate_subing_signal(primary_long, companion_long, calibration)
assert result.status is SubingSignalStatus.MATCHED
assert result.direction is SubingDirection.LONG

conflict = evaluate_subing_signal(primary_long, companion_short, calibration)
assert conflict.status is SubingSignalStatus.NOT_MATCHED
assert conflict.direction is SubingDirection.NONE
```

- [ ] **Step 2: Encode the immutable V1 hard conditions**

For LONG primary 5m/15m:

```text
price_side == ABOVE
slope_5_bps_per_bar > calibration.slope_threshold(primary timeframe)
slope_10_bps_per_bar > 0
macd_cross == GOLDEN
macd_zero_distance_bps <= calibration.zero_band(primary timeframe)
volume_ratio_prev >= 3
```

SHORT mirrors all signs/cross direction.

Companion alignment for the requested direction:

```text
LONG:
price_side == ABOVE
slope_5_bps_per_bar > calibration.slope_threshold(companion timeframe)
slope_10_bps_per_bar > 0

SHORT:
price_side == BELOW
slope_5_bps_per_bar < -calibration.slope_threshold(companion timeframe)
slope_10_bps_per_bar < 0
```

Do not inspect companion MACD or volume.

- [ ] **Step 3: Implement status/direction priority**

```text
primary/companion Factor insufficient -> INSUFFICIENT_DATA / NONE
calibration not accepted for either intraday timeframe -> RESEARCH_PENDING / candidate direction or NONE
scoped MACD policy unavailable -> RESEARCH_PENDING / candidate direction or NONE
any known hard condition fails -> NOT_MATCHED / NONE
all pass -> MATCHED / LONG|SHORT
```

Require `subing_macd_sma_window_scale2_v1` with consumer `subing_signal` before returning MATCHED.

- [ ] **Step 4: Implement same-boundary resolver**

If 5m and 15m are both MATCHED with the same `bar_end` and direction, return only 15m with `lower_tf_confirmation=True` and `resolution="higher_timeframe_wins"`.

If both are MATCHED at the same boundary but directions differ, raise/fail closed with stable `SUBING_SIGNAL_DIRECTION_CONFLICT`; never choose one.

Otherwise return whichever timeframe is independently MATCHED.

- [ ] **Step 5: Run pure Factor + Signal tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_calibration.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_research.py
git commit -m "feat: evaluate SuBing entry signals"
```

---

### Task 8: Inject accepted Calibration into the read model and expose Signal to Web

**Files:**
- Modify: `services/quant-api/app/market_data/subing_read_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_read_service.py`
- Modify: `services/quant-api/tests/test_subing_api.py`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/components/market/SubingStatusStrip.vue`
- Modify: `apps/quant-web/src/components/market/SubingResearchSection.vue`
- Modify: `apps/quant-web/tests/subingResearch.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Existing `/api/v1/market/research/subing` gains `signal` but retains Factor fields/identity.
- No Alert persistence/event side effect.

- [ ] **Step 1: Write failing read/API tests for accepted vs pending timeframes**

5m/15m with the test fixture can return `MATCHED`; 1d must remain `RESEARCH_PENDING` because the initial production/test intraday calibration does not accept 1d.

Assert no DB writes and no Alert service calls.

- [ ] **Step 2: Inject Calibration through composition**

`SubingReadService.__init__` receives `calibration: SubingCalibration`. `build_subing_read_service()` loads the tracked production path:

```python
PROJECT_ROOT / "data/research_policies/subing_calibration_intraday_v1.json"
```

No environment variable or runtime override is allowed.

- [ ] **Step 3: Evaluate primary Signal and the relevant companion at the same snapshot cutoff**

For 5m request evaluate 5m primary against aligned 15m companion. For 15m request evaluate 15m primary against aligned 5m companion.

To honor same-boundary 15m priority on a 5m request whose primary `bar_end` is also a 15m completed boundary, compute both formal evaluations and apply `resolve_subing_signals`; the returned resolved Signal may therefore have `trigger_timeframe="15m"`.

Do not create an event or remember previous signals.

- [ ] **Step 4: Extend HTTP DTOs**

Add:

```python
class SubingConditionOut(BaseModel):
    code: str
    state: str

class SubingSignalOut(BaseModel):
    status: str
    direction: str
    trigger_timeframe: str | None
    lower_tf_confirmation: bool
    resolution: str | None
    conditions: list[SubingConditionOut]
```

Return the evaluation even when pending/not-matched so Web can explain state.

- [ ] **Step 5: Update Web types/status presentation**

Display only:

```text
MATCHED + LONG  -> 买入信号
MATCHED + SHORT -> 卖出信号
RESEARCH_PENDING -> 研究参数/能力待冻结
INSUFFICIENT_DATA -> 指标 warm-up 中
NOT_MATCHED -> 当前不匹配
```

Do not add position, exit, trade button, Alert toggle or notification side effect.

- [ ] **Step 6: Extend E2E**

Mock MATCHED LONG and assert the Product Workspace shows `买入信号`, current contract and trigger timeframe. Assert HTDY Alert controls remain the existing HTDY-only behavior and no SuBing alert rule is requested/created.

- [ ] **Step 7: Run backend/Web regressions**

Run all SuBing tests, Alert V1 tests, Web tests, `market-research.spec.mjs`, `alert-v1.spec.mjs`, and Web build. Expected PASS.

- [ ] **Step 8: Commit Task 8**

```bash
git add services/quant-api/app/market_data/subing_read_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/test_subing_api.py \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/components/market/SubingStatusStrip.vue \
  apps/quant-web/src/components/market/SubingResearchSection.vue \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat: expose SuBing entry signal observation"
```

---

### Task 9: Add the non-blocking 1d Calibration research path without delaying intraday acceptance

**Files:**
- Reuse calibration code and CLI from Tasks 1-3.
- Modify tests only if 1d-specific behavior is missing.
- Do **not** modify `subing_calibration_intraday_v1.json`.

**Interfaces:**
- 1d can run Slope and Zero-Band Discovery/Validation.
- 1d formal Signal remains `RESEARCH_PENDING` until a future independently approved 1d calibration artifact/version exists.

- [ ] **Step 1: Run 1d Slope Discovery on the chosen historical window**

Confirm segment-local warm-up and daily outcomes can cross trading days but never rank1 segment.

- [ ] **Step 2: Review 1d results independently**

No intraday threshold may be changed because of 1d findings.

- [ ] **Step 3: If the user wants to continue 1d Calibration, use the same human Gate pattern**

Run explicit later-window Validation and Zero-Band research. Do not create an accepted 1d artifact unless the user separately approves exact 1d values.

- [ ] **Step 4: Verify 5m/15m Signal remains unchanged**

Run intraday Signal tests after any 1d research-code fix. Expected identical outputs.

No commit is required if this task is research execution only; any correctness code change must get its own focused test and commit.

---

### Task 10: Close testing/canonical/status boundaries without touching Alert or Runtime

**Files:**
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md` only after all executable tasks and required tests pass.

**Interfaces:**
- No new Runtime or notification interface.
- Final state is SuBing Entry Signal available in Web/research read model, Alert integration absent.

- [ ] **Step 1: Add read-only Calibration CLI examples to `TESTING.md`**

Document discovery/validation examples using clearly labeled **example research windows**, and state that the commands only query existing Canonical/Catalog via MarketDataService and print JSON. Do not put accepted production threshold values into command examples unless they are already present in the tracked calibration artifact.

- [ ] **Step 2: Add SuBing Signal tests to the no-side-effect validation block**

Include:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/test_subing_api.py
```

- [ ] **Step 3: Align `docs/ARCHITECTURE.md`**

Document:

```text
MarketDataService -> read-only Calibration Research
Git-tracked accepted Calibration -> pure Signal evaluation
SubingReadService -> Web observation
```

Explicitly state no research DB, no Signal persistence and no Alert integration in this version.

- [ ] **Step 4: Run full required repository verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: PASS with no real notification, Runtime switch, migration, RQData write or Canonical mutation.

- [ ] **Step 5: Update `STATUS.md` conservatively if all executable gates passed**

Record only:

```text
SuBing 5m/15m accepted Calibration exists as tracked Git fact
scoped MACD SuBing Signal policy passed
5m/15m Entry Signal evaluation available in Product Workspace
1d remains research/pending unless separately accepted
Alert V1 unchanged
SuBing Alert V2 not implemented
no Runtime deployment/switch performed
```

Do not claim profitability, backtest validity, Alert Ready or Runtime Ready.

- [ ] **Step 6: Commit Task 10**

```bash
git add TESTING.md docs/ARCHITECTURE.md STATUS.md
git commit -m "docs: record SuBing entry signal boundaries"
```

---

## Plan Acceptance

This plan is complete when all of the following are true:

```text
5m/15m Slope candidate -> later-window Validation -> human approval
5m/15m Zero-Band candidate -> later-window Validation -> human approval
accepted intraday Calibration exists as a Git-tracked versioned artifact
scoped MACD SuBing Signal policy is explicitly approved and tested
deterministic MATCHED LONG/SHORT Signal is available in the read model/Web
same-boundary 15m wins
1d does not block intraday and remains pending unless independently accepted
no Signal persistence
no Alert V2
no DB/Canonical/Redis schema addition
no Runtime mutation
no automatic parameter promotion
```

Future `Alert V2 — SuBing Entry Signal Integration` must remain a separate design/spec/plan after a real Live observation period.