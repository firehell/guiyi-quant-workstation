# SuBing Calibration and Entry Signal V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Factor Observation 已独立验收后，建立可重复、只读的 5m/15m Calibration Research，经过人工 Gate 将最小 intraday Calibration 固化为 Git 事实，再交付确定性的 `MATCHED LONG/SHORT` 入场 Signal；1d 保持非阻塞研究轨，Alert V2 仍不实现。

**Architecture:** 历史研究只通过 `MarketDataService` 获取 actual-dominant 结果，并按 `resolved_contract_segments` 将 bars 切成互不继承状态的 rank1 segment；每个 segment 单独调用已有 `calculate_subing_factor_series()`，再生成 3/5/8K future labels。Zero-Band 的 decision cohort 必须同时重建 5m↔15m confirmed companion relationship，不允许降级成 primary-only。研究 CLI 只向 stdout 输出 JSON、不写 DB/Canonical/报告文件；只有人工批准后的最小 Calibration 才写入 `data/research_policies/` 并由 `SubingReadService` 注入 pure Signal evaluator。

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
- Zero-Band Cohort B 必须满足“除 zero-band 外的其他 SuBing 条件”，包括 5m↔15m latest-confirmed companion alignment；不得把 cohort 改名后偷偷删除 multi-TF 条件。
- Discovery 只提出候选；Validation 使用人工冻结的精确阈值。系统不得自动选择“最优”或自动晋升。
- Accepted Calibration 必须 Git-tracked、versioned、human-reviewable；聊天、临时 CLI 参数、stdout 报告或 localStorage 不得驱动正式 Signal。
- Generic `macd` registry 继续保持 `compatibility_validated/live_capable=False/alert_capable=False`；本计划通过独立、明确命名的 scoped FormalPolicy 批准 SuBing confirmed Signal consumer，不做全局 MACD capability 晋升。
- Formal Signal 只有 `status == MATCHED && direction in {LONG, SHORT}`；`RESEARCH_PENDING` 不是 Signal。
- 不实现持仓、退出、8K、止损止盈、Backtest、Alert V2、WeCom、DB migration、Runtime switch 或任何订单。
- Alert V1 代码、表、Scope、Runtime 和 WeCom sender 必须保持原样。

---

## File Map

**Create**
- `services/quant-api/app/market_data/subing_calibration.py` — pure future labels、统计聚合、accepted calibration schema/loader。
- `services/quant-api/app/market_data/subing_calibration_service.py` — MarketDataService-only historical segment/multi-TF research orchestration。
- `services/quant-api/tests/test_subing_calibration.py` — labels、candidate evaluation、artifact validation tests。
- `services/quant-api/tests/data_foundation/test_subing_calibration_service.py` — rank1 segment isolation、multi-TF cohort、discovery/validation tests。
- `services/quant-api/app/guiyi_cli/research_parser.py` — read-only research CLI parser。
- `services/quant-api/app/guiyi_cli/research_commands.py` — calibration command execution/output mapping。
- `services/quant-api/tests/test_research_cli.py` — no-side-effect CLI contract tests。
- `data/research_policies/subing_calibration_intraday_v1.json` — **只在最终人工 Calibration Gate 后创建**，包含精确批准值；不得提前创建示例 production 文件。
- `services/quant-api/tests/fixtures/subing_calibration_test_v1.json` — test-only deterministic calibration values。

**Modify**
- `services/quant-api/app/guiyi_cli/main.py` — add read-only `research` domain。
- `services/quant-api/app/market_data/subing_research.py` — add policy/calibration-aware Signal evaluator and same-boundary resolver。
- `packages/quant-core/guiyi_quant/indicators/policy.py` — add scoped `subing_macd_sma_window_scale2_v1` formal Signal policy after human capability Gate。
- `docs/INDICATOR_KERNEL.md` — document scoped SuBing MACD Signal policy without globally promoting generic MACD。
- `services/quant-api/app/market_data/subing_read_service.py` — inject accepted calibration and expose Signal evaluation。
- `services/quant-api/app/market_data/composition.py` — build Calibration service and load tracked calibration artifact into `SubingReadService`。
- `services/quant-api/app/schemas/market.py` — add Signal DTO to SuBing response。
- `services/quant-api/app/api/market.py` — serialize Signal evaluation, endpoint identity unchanged。
- `services/quant-api/tests/test_subing_research.py` — Signal condition/resolver tests。
- `services/quant-api/tests/data_foundation/test_subing_read_service.py` — accepted/pending calibration integration tests。
- `services/quant-api/tests/test_subing_api.py` — Signal HTTP contract tests。
- `apps/quant-web/src/types/market.ts` — Signal response types。
- `apps/quant-web/src/api/market.ts` — carry Signal fields through existing normalization。
- `apps/quant-web/src/components/market/SubingStatusStrip.vue` — matched/pending/not-matched display。
- `apps/quant-web/src/components/market/SubingResearchSection.vue` — Signal condition explanation without trade-management UI。
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

Use explicit local bar/factor builders and assert exact bps semantics:

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

Add mirrored SHORT tests and a rank1 segment boundary case where a following bar with another `segment_start_trading_day` cannot satisfy the horizon.

- [ ] **Step 2: Run focused tests and confirm module missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_calibration.py
```

Expected: FAIL.

- [ ] **Step 3: Implement exact research label formulas**

Use next-N bars **after** the sample bar. For entry close `C0` and direction sign `s` (`+1` LONG, `-1` SHORT):

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

MFE is favorable/non-negative; MAE is adverse/non-positive.

`ema21_failure=True` when any future ready Factor snapshot in the horizon has confirmed close below EMA21 for LONG or above EMA21 for SHORT.

For 5m/15m require all N future bars to have the same `trading_day`, `contract`, and `segment_start_trading_day`; otherwise outcome is `None`. For 1d require same contract/segment only.

- [ ] **Step 4: Define the Slope discovery cohort without a flat threshold**

Eligible sample:

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

Studied scalar = `abs(slope_5_bps_per_bar)`. No flat threshold is used to form this cohort.

- [ ] **Step 5: Implement candidate quantiles and threshold evaluation with product-bounded memory**

`candidate_quantiles(values)` is called only on one product at a time. Compute inclusive P10/P20/P30 via stdlib `statistics.quantiles(..., n=100, method="inclusive")` for at least two values; one value returns the same value for all three; zero values yields no candidates.

`evaluate_threshold(samples, threshold, selector)` returns sample count and, for each horizon, available count, median directional return, median MFE, median MAE and EMA21 failure rate. It must not rank candidates or return a `best` field.

- [ ] **Step 6: Run pure Calibration tests and commit**

Expected: PASS.

```bash
git add services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: add SuBing calibration research math"
```

---

### Task 2: Build MarketDataService-only historical Calibration and full multi-TF cohort orchestration

**Files:**
- Create: `services/quant-api/app/market_data/subing_calibration_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_calibration_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`

**Interfaces:**
- Produces: `CalibrationResearchRequest`, `SlopeThresholds`, `SubingCalibrationResearchService.run(request)`.
- Service performs no writes and never uses `MarketReadService`/Redis.
- For intraday Zero-Band it reconstructs both 5m and 15m Factor streams and aligns latest confirmed companion `<= primary.bar_end`.

- [ ] **Step 1: Write failing tests proving segment isolation and full companion Cohort B**

Use a fake MarketDataService returning explicit M5 and M15 actual-dominant results with the same rank1 segment. Assert:

```text
- each frequency is factorized segment-by-segment
- no Factor state crosses a rollover
- 5m primary at 10:25 uses latest 15m <= 10:25
- 15m primary at 10:30 uses latest 5m <= 10:30
- Cohort B rejects an otherwise valid primary when companion direction/slope conflicts
- Cohort B accepts when all other SuBing conditions including companion alignment pass
```

Also reject unsupported frequencies and `since > through` before any data read.

- [ ] **Step 2: Run focused tests and confirm service missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py
```

Expected: FAIL.

- [ ] **Step 3: Implement trading-day-safe historical query and segment factorization**

```python
_SHANGHAI = ZoneInfo("Asia/Shanghai")

def _research_window(since: date, through: date) -> tuple[datetime, datetime]:
    start = datetime.combine(since - timedelta(days=1), time.min, _SHANGHAI).astimezone(UTC)
    end = datetime.combine(through + timedelta(days=1), time.max, _SHANGHAI).astimezone(UTC)
    return start, end
```

For each requested product/frequency:

```python
result = self._market_data.query(
    SeriesQuery(SeriesKind.ACTUAL_DOMINANT, symbol, frequency, start, end)
)
```

Filter `since <= bar.trading_day <= through`. For every `resolved_contract_segment`, slice only bars inside its trading-day interval and call `calculate_subing_factor_series()` separately with `contract=segment.contract` and that segment start. Never concatenate Factor state between segments.

- [ ] **Step 4: Implement reusable latest-confirmed companion alignment**

For one product, build M5 and M15 Factor series separately. Align by a monotonic two-pointer helper rather than O(N²):

```python
def latest_companion_at_or_before(
    companion_results: Sequence[SubingFactorResult],
    primary_bar_end: datetime,
    *,
    contract: str,
    segment_start_trading_day: date,
) -> SubingFactorResult | None:
    ...
```

Eligible companion must be READY, `bar_end <= primary_bar_end`, same contract and same segment start. Never use a later companion.

- [ ] **Step 5: Implement Slope discovery/validation modes**

`phase="slope", mode="discovery"`:
1. Process one product at a time.
2. Build its eligible Slope samples.
3. Calculate product P10/P20/P30 of `abs(slope_5_bps_per_bar)`.
4. Discard raw rows before next product.
5. Global candidate A/B/C = median across product P10/P20/P30 respectively.
6. Second read pass evaluates all three fixed candidates across products.
7. Return all three; never select one.

`phase="slope", mode="validation"` requires explicit `slope_threshold_bps` and evaluates only that threshold on the later requested window.

- [ ] **Step 6: Implement Zero-Band Cohort A and full SuBing Cohort B**

For 5m/15m, request must contain both human-approved Slope thresholds via `SlopeThresholds(m5=..., m15=...)`.

Cohort A:

```text
all confirmed MACD GOLDEN/DEAD crosses with READY primary Factor
```

Cohort B = every SuBing hard condition **except zero-band**:

```text
Primary LONG:
price_side == ABOVE
slope_5 > approved primary timeframe threshold
slope_10 > 0
macd_cross == GOLDEN
volume_ratio_prev >= 3
latest confirmed companion exists
companion price_side == ABOVE
companion slope_5 > approved companion timeframe threshold
companion slope_10 > 0

Primary SHORT:
mirror price/slope signs
macd_cross == DEAD
volume_ratio_prev >= 3
latest confirmed companion exists
companion direction/slope mirror passes
```

For 1d Cohort B there is no companion and daily volume is not a hard gate: price side + approved daily slope + cross only, excluding zero-band.

Discovery candidates are derived from per-product P20/P40/P60 of **Cohort B** `macd_zero_distance_bps`, then median-across-products. Each candidate report must evaluate both Cohort A and Cohort B so the user can compare generic cross behavior against SuBing-context behavior.

Validation requires explicit `zero_band_bps` and evaluates `distance_bps <= threshold` for both cohorts; no auto selection and no product overrides.

- [ ] **Step 7: Add composition builder and run tests**

```python
def build_subing_calibration_research_service(session: Session) -> SubingCalibrationResearchService:
    return SubingCalibrationResearchService(
        market_data=build_market_data_service(session),
        products=load_active_products(),
    )
```

Run new tests plus `test_market_research.py`; prove no Redis/provider construction.

- [ ] **Step 8: Commit Task 2**

```bash
git add services/quant-api/app/market_data/subing_calibration_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/app/market_data/composition.py
git commit -m "feat: add SuBing calibration research service"
```

---

### Task 3: Expose a read-only reproducible Calibration CLI

**Files:**
- Create: `services/quant-api/app/guiyi_cli/research_parser.py`
- Create: `services/quant-api/app/guiyi_cli/research_commands.py`
- Create: `services/quant-api/tests/test_research_cli.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`

**Interfaces:**
- Base command:
  `guiyi research subing-calibration --phase {slope,zero-band} --mode {discovery,validation} --frequency {5m,15m,1d} --since YYYY-MM-DD --through YYYY-MM-DD [--symbol X]`.
- Slope validation adds `--slope-threshold-bps DECIMAL`.
- Intraday Zero-Band discovery/validation adds both `--slope-threshold-5m-bps DECIMAL` and `--slope-threshold-15m-bps DECIMAL`; validation additionally adds `--zero-band-bps DECIMAL`.
- 1d Zero-Band discovery uses `--slope-threshold-bps`; validation also uses `--zero-band-bps`.
- stdout JSON only; zero DB/Canonical/Redis/RQData writes.

- [ ] **Step 1: Write parser/command tests for exact mode matrix**

Require:

```text
slope discovery:
  no threshold required; threshold flags rejected

slope validation:
  --slope-threshold-bps required

zero-band discovery 5m/15m:
  --slope-threshold-5m-bps and --slope-threshold-15m-bps required
  --zero-band-bps rejected

zero-band validation 5m/15m:
  both intraday slope thresholds + --zero-band-bps required

zero-band discovery 1d:
  --slope-threshold-bps required

zero-band validation 1d:
  --slope-threshold-bps + --zero-band-bps required
```

`--symbol` optional; omitted means active 60. Invalid frequency, non-finite or negative threshold exits code 2 through existing redacted argument payload.

- [ ] **Step 2: Run CLI tests and confirm `research` missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py
```

Expected: FAIL.

- [ ] **Step 3: Add `research` parser without changing data/runtime semantics**

Implement `add_research_commands()` in `research_parser.py`; parse dates with `date.fromisoformat`, thresholds with `Decimal`, and validate mode matrix before service construction.

- [ ] **Step 4: Add read-only command execution/output**

`research_commands.py` builds `CalibrationResearchRequest`/`SlopeThresholds` and returns `report.as_payload()` containing:

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
candidate_evaluations     # all candidates, never ranked
cohorts                    # zero-band A/B comparison
threshold_evaluation       # validation
```

No `best_threshold`, `approved`, trading instruction or performance claim.

- [ ] **Step 5: Wire `guiyi_cli.main` with injected research-service factory**

Add `research` branch parallel to `data`/`runtime`. Errors always report `readonly=True`. Existing data/runtime behavior must remain unchanged.

- [ ] **Step 6: Run CLI regressions and commit**

Run `test_research_cli.py`, `test_alert_cli.py` and existing data CLI tests. Expected PASS.

```bash
git add services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "feat: add read-only SuBing calibration CLI"
```

---

### Gate A: Human approval of intraday Slope candidates

**Hard stop.**

Run Slope Discovery separately for 5m and 15m on the chosen Discovery window. Review all candidates, sample coverage and outcome stability. Then run later non-overlapping Validation with the exact candidate under review.

Continue only after the user explicitly approves exact Decimal values for both:

```text
5m slope_flat_threshold_bps_per_bar
15m slope_flat_threshold_bps_per_bar
```

Do not create the accepted Calibration artifact yet. Both approved values become immutable inputs to every intraday Zero-Band Discovery/Validation run.

---

### Task 4: Complete full multi-TF Zero-Band research with Gate A Slope thresholds

**Files:**
- Primarily execute the read-only CLI from Task 3.
- Modify code/tests only for a demonstrated correctness bug; do not tune methodology to make results look better.

- [ ] **Step 1: Run 5m Zero-Band Discovery with both exact approved Slope thresholds**

Supply Gate A 5m and 15m slope values. Confirm output contains Cohort A and full companion-aware Cohort B, exact slope inputs and three unranked candidate bands.

- [ ] **Step 2: Run 15m Zero-Band Discovery with the same two exact Slope thresholds**

Confirm 15m primary uses latest confirmed 5m companion.

- [ ] **Step 3: Human-select one 5m and one 15m Zero-Band candidate for Validation**

Stop until the user names exact candidate values. The system does not select.

- [ ] **Step 4: Run later-window Validation for both exact candidates**

Supply both frozen Slope thresholds on every run plus the single zero-band threshold being validated. Do not change Slope during this phase.

- [ ] **Step 5: Present both Cohort A/B validation reports for Gate B**

Do not commit stdout and do not update Runtime state.

---

### Gate B: Human approval of final intraday Calibration

**Hard stop.** Continue only after explicit approval of all four exact Decimal values:

```text
5m slope_flat_threshold_bps_per_bar
15m slope_flat_threshold_bps_per_bar
5m macd_zero_band_bps
15m macd_zero_band_bps
```

If any value changes after Validation, create a new candidate and rerun relevant later-window Validation before approval.

---

### Task 5: Persist accepted intraday Calibration as a minimal Git fact

**Files:**
- Create after Gate B: `data/research_policies/subing_calibration_intraday_v1.json`
- Create: `services/quant-api/tests/fixtures/subing_calibration_test_v1.json`
- Modify: `services/quant-api/app/market_data/subing_calibration.py`
- Modify: `services/quant-api/tests/test_subing_calibration.py`

**Interfaces:**
- Produces: `SubingCalibration`, `load_subing_calibration(path)`, `pending_subing_calibration()`.
- Initial production artifact accepts exactly 5m and 15m; 1d remains pending.

- [ ] **Step 1: Add test-only fixture with explicit non-production values**

```json
{
  "schema_version": 1,
  "calibration_id": "subing_test_intraday_v1",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {"5m": "1.25", "15m": "0.80"},
  "macd_zero_band_bps": {"5m": "12.50", "15m": "8.00"}
}
```

Production code must never load the test fixture.

- [ ] **Step 2: Write failing loader tests**

Cover successful test-fixture load; missing file -> pending; unknown schema -> fail closed; non-finite/negative -> fail; missing value for accepted timeframe -> fail; 1d -> not accepted.

- [ ] **Step 3: Implement immutable Calibration value object/loader**

```python
@dataclass(frozen=True, slots=True)
class SubingCalibration:
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]
    macd_zero_band_bps: Mapping[BarFrequency, Decimal]

    def is_accepted(self, timeframe: BarFrequency) -> bool: ...
```

Use immutable mappings and no environment/runtime override. Missing production file -> pending; malformed existing file -> stable configuration error, never silent pending.

- [ ] **Step 4: Create production artifact with exact Gate B values**

Create `data/research_policies/subing_calibration_intraday_v1.json` containing only:

```text
schema_version = 1
calibration_id = subing_calibration_intraday_v1
accepted_timeframes = 5m, 15m
four exact Gate B Decimal strings
```

No 1d, product overrides, timestamps, research rows or performance claims.

- [ ] **Step 5: Run tests, manually inspect diff and commit**

```bash
git add data/research_policies/subing_calibration_intraday_v1.json \
  services/quant-api/tests/fixtures/subing_calibration_test_v1.json \
  services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: accept SuBing intraday calibration v1"
```

This commit makes the four values a repository fact; it does not authorize Signal Alert or Runtime.

---

### Task 6: Prepare the scoped MACD formal Signal policy evidence

**Files:**
- Modify tests only in this task until Gate C approval:
  - `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`
  - `services/quant-api/tests/test_indicator_registry_v1.py`

**Interfaces:**
- Evidence target: proposed policy ID `subing_macd_sma_window_scale2_v1` with consumer `subing_signal` only.
- Generic MACD registry must remain unpromoted.

- [ ] **Step 1: Add edge/golden evidence tests for the proposed scoped policy math**

Before creating the policy, test the underlying explicit MACD invocation (`fast=12, slow=26, signal=9, sma_window, histogram_scale=2`) for:

```text
first ready DIF/DEA index
equality edge used by Golden/Dead cross
historical and completed-live identical close sequence -> identical points
appending one later confirmed close -> prior points unchanged
```

Also assert generic `get_indicator("macd")` remains `compatibility_validated`, `live_capable=False`, `alert_capable=False`.

- [ ] **Step 2: Run full Indicator tests and present evidence for independent Review**

Run the current commands in `docs/INDICATOR_KERNEL.md`. Do not modify `policy.py` yet.

- [ ] **Step 3: Independent Review checks**

Review must explicitly confirm:

```text
same formula/policy as reviewed Factor observation
confirmed-only/no repaint for appended closed bars
scope only SuBing entry Signal
no generic MACD promotion
no Backtest/Alert capability
```

---

### Gate C: Human approval of scoped MACD Signal capability

**Hard stop.** Only after the independent review evidence is presented and the user explicitly approves the scoped policy may implementation modify `packages/quant-core/guiyi_quant/indicators/policy.py`.

This Gate does not approve Alert V2 or generic MACD live/alert capability.

---

### Task 7: Create the approved scoped MACD policy and deterministic intraday Entry Signal

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`
- Modify: `services/quant-api/app/market_data/subing_research.py`
- Modify: `services/quant-api/tests/test_subing_research.py`

**Interfaces:**
- Formal policy: `subing_macd_sma_window_scale2_v1`, consumer `subing_signal` only.
- Produces: `SubingSignalStatus`, `SubingDirection`, `ConditionState`, `SubingSignalEvaluation`, `ResolvedSubingSignal`.
- Produces: `evaluate_subing_signal(primary, companion, calibration)` and `resolve_subing_signals(five_minute, fifteen_minute)`.

- [ ] **Step 1: Add the approved scoped policy**

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

Keep `get_indicator("macd")` generic registry fields unchanged.

- [ ] **Step 2: Update Indicator canonical**

Document scoped policy and explicitly state it is not generic MACD promotion; Alert V2 requires a separate future capability decision.

- [ ] **Step 3: Write failing Signal tests with the test Calibration fixture**

Require exact LONG/SHORT, hard fail, missing calibration, companion conflict and same-boundary behavior:

```python
result = evaluate_subing_signal(primary_long, companion_long, calibration)
assert result.status is SubingSignalStatus.MATCHED
assert result.direction is SubingDirection.LONG

conflict = evaluate_subing_signal(primary_long, companion_short, calibration)
assert conflict.status is SubingSignalStatus.NOT_MATCHED
assert conflict.direction is SubingDirection.NONE
```

1d must be `RESEARCH_PENDING` because the intraday artifact does not accept 1d.

- [ ] **Step 4: Encode immutable V1 hard conditions**

Primary LONG 5m/15m:

```text
price_side == ABOVE
slope_5 > calibration threshold(primary)
slope_10 > 0
macd_cross == GOLDEN
macd_zero_distance_bps <= calibration zero-band(primary)
volume_ratio_prev >= 3
```

SHORT mirrors signs/cross.

Companion LONG:

```text
price_side == ABOVE
slope_5 > calibration threshold(companion)
slope_10 > 0
```

SHORT mirrors; do not inspect companion MACD/volume.

- [ ] **Step 5: Implement status/direction priority**

```text
Factor insufficient -> INSUFFICIENT_DATA / NONE
calibration not accepted for required timeframe(s) -> RESEARCH_PENDING / candidate direction or NONE
scoped MACD policy missing/not allowed -> RESEARCH_PENDING / candidate direction or NONE
known hard condition FAIL -> NOT_MATCHED / NONE
all pass -> MATCHED / LONG|SHORT
```

Before MATCHED require `require_formal_policy("subing_macd_sma_window_scale2_v1", consumer="subing_signal")`.

- [ ] **Step 6: Implement same-boundary resolver**

5m + 15m both MATCHED, same `bar_end`, same direction -> only 15m with `lower_tf_confirmation=True`, `resolution="higher_timeframe_wins"`.

Same boundary but different directions -> stable fail-closed `SUBING_SIGNAL_DIRECTION_CONFLICT`; never choose one.

Otherwise return whichever timeframe is independently MATCHED.

- [ ] **Step 7: Run Indicator + Signal tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_calibration.py
```

Expected: PASS.

```bash
git add packages/quant-core/guiyi_quant/indicators/policy.py \
  docs/INDICATOR_KERNEL.md \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_research.py
git commit -m "feat: evaluate SuBing entry signals"
```

---

### Task 8: Inject accepted Calibration into read model and expose Signal to Web

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
- Existing `/api/v1/market/research/subing` gains `signal`; Factor fields/identity remain.
- No persistence/event/Alert side effect.

- [ ] **Step 1: Write failing read/API tests for accepted vs pending timeframe**

5m/15m with test artifact can return MATCHED; 1d remains RESEARCH_PENDING. Assert no Alert service use and no DB mutation.

- [ ] **Step 2: Inject Calibration through composition**

`SubingReadService` receives `calibration: SubingCalibration`. `build_subing_read_service()` loads only:

```python
PROJECT_ROOT / "data/research_policies/subing_calibration_intraday_v1.json"
```

No env/localStorage/runtime override.

- [ ] **Step 3: Evaluate Signal at the same primary cutoff**

5m request: evaluate 5m primary vs aligned 15m companion. If primary `bar_end` equals companion 15m `bar_end`, also evaluate the 15m full Signal using the same two snapshots reversed (15m primary / 5m companion) and apply resolver.

15m request: evaluate 15m primary vs aligned 5m companion; if same-boundary 5m full Signal is also computable, resolve the pair.

Do not persist Signal or remember previous signals.

- [ ] **Step 4: Extend HTTP DTOs**

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

Return evaluation for matched/pending/not-matched/insufficient states.

- [ ] **Step 5: Update Web presentation**

```text
MATCHED + LONG  -> 买入信号
MATCHED + SHORT -> 卖出信号
RESEARCH_PENDING -> 研究参数/能力待冻结
INSUFFICIENT_DATA -> 指标 warm-up 中
NOT_MATCHED -> 当前不匹配
```

No position, exit, trade button, new Alert toggle or notification side effect.

- [ ] **Step 6: Extend E2E and run regressions**

Mock MATCHED LONG; assert `买入信号`, current contract and trigger timeframe. Assert existing HTDY Alert behavior remains unchanged and no SuBing Alert rule endpoint is requested/created.

Run all SuBing tests, Alert V1 tests, Web tests, `market-research.spec.mjs`, `alert-v1.spec.mjs`, Web build.

- [ ] **Step 7: Commit Task 8**

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

### Task 9: Keep 1d as a non-blocking Calibration research track

**Files:**
- Reuse Tasks 1-3 code/CLI.
- Modify tests only if 1d-specific correctness is missing.
- Do not modify `subing_calibration_intraday_v1.json`.

- [ ] **Step 1: Run 1d Slope Discovery on the chosen historical window**

Confirm segment-local warm-up and daily outcomes may cross trading days but never rank1 segment.

- [ ] **Step 2: Review 1d independently**

Intraday thresholds are immutable with respect to 1d findings.

- [ ] **Step 3: If the user chooses to continue 1d Calibration, reuse the same human Gate pattern**

Run explicit later-window Validation then 1d Zero-Band with `--slope-threshold-bps`. Do not create accepted 1d artifact/version without separate user approval.

- [ ] **Step 4: Re-run 5m/15m Signal tests after any 1d correctness code change**

Expected identical intraday outputs.

Research-only execution needs no commit; any code fix requires focused test/commit.

---

### Task 10: Close testing/canonical/status boundaries without Alert or Runtime

**Files:**
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md` only after all executable tasks and required checks pass.

- [ ] **Step 1: Add read-only Calibration CLI examples to `TESTING.md`**

Use clearly labeled example research windows. State commands only query existing Canonical/Catalog through MarketDataService and print JSON. Do not copy accepted production thresholds into examples unless already present in tracked artifact.

- [ ] **Step 2: Add SuBing Signal tests to no-side-effect validation**

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

No research DB, Signal persistence or Alert integration.

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

Expected: PASS with no notification, Runtime switch, migration, RQData write or Canonical mutation.

- [ ] **Step 5: Update `STATUS.md` conservatively only after all gates/checks passed**

Record only:

```text
SuBing 5m/15m accepted Calibration exists as tracked Git fact
scoped MACD SuBing Signal policy passed its explicit Gate
5m/15m Entry Signal evaluation available in Product Workspace
1d remains research/pending unless separately accepted
Alert V1 unchanged
SuBing Alert V2 not implemented
no Runtime deployment/switch performed
```

Do not claim profitability, Backtest validity, Alert Ready or Runtime Ready.

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
5m/15m Zero-Band Cohort B includes full latest-confirmed 5m↔15m relationship
5m/15m Zero-Band candidate -> later-window Validation -> human approval
accepted intraday Calibration exists as a Git-tracked versioned artifact
scoped MACD SuBing Signal policy passes independent Review + human Gate
Generic MACD registry remains unpromoted
deterministic MATCHED LONG/SHORT Signal is available in read model/Web
same-boundary 15m wins
1d does not block intraday and remains pending unless independently accepted
no Signal persistence
no Alert V2
no DB/Canonical/Redis schema addition
no Runtime mutation
no automatic parameter promotion
```

Future `Alert V2 — SuBing Entry Signal Integration` remains a separate design/spec/plan after a real Live observation period.