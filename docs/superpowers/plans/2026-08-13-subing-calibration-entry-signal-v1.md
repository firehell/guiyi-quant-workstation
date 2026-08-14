# SuBing Calibration and Entry Signal V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## 0. 2026-08-14 Gate B-R Amendment（权威执行合同）

本节基于已完成的 Gate A、5m/15m Zero-Band Discovery，以及冻结候选 C 对 NO-BAND 的非重叠 OOS Validation。**本节覆盖下文原 Task 4 Step 3 之后、原 Gate B、原 Task 5 Calibration schema、原 Task 7 zero-band hard condition、Plan Acceptance 中所有与 intraday zero-band hard gate 冲突的内容。**原文保留用于研究/实施轨迹审计，不得在冲突处继续执行。

### 0.1 已完成且冻结的研究事实

Gate A 已人工批准：

```text
5m slope_flat_threshold_bps_per_bar
= 0.688190651160584793944957992

15m slope_flat_threshold_bps_per_bar
= 1.329531078893356968545882036
```

Zero-Band Discovery 已完成；进入 OOS 的唯一冻结 candidate 为：

```text
5m C = 16.01901065112843434322837440 bps
15m C = 27.16954645407146036410753274 bps
```

Validation window 固定为 `2026-05-01..2026-08-11`，并与 NO-BAND baseline 对照。OOS 不支持 zero-band 作为 intraday hard gate：5m C 在 return/failure/正负分布上整体弱于 NO-BAND；15m 只有 5K 局部改善，但三个 horizon failure 均更高、3K/8K 不形成一致增量且样本稀疏。不得回头用 Validation 重新挑 A/B，不得创造新 threshold/product/direction override。

### 0.2 Research-driven simplification

当前 intraday V1 决定：

```text
保留：MACD GOLDEN / DEAD cross
保留：macd_zero_distance_abs / macd_zero_distance_bps Factor
删除：zero_distance_bps <= threshold 作为 5m/15m Signal hard gate
删除：macd_zero_band_bps 作为 accepted intraday Calibration 字段
```

Zero-Band research CLI/service 可以保留为 research-only 能力；不要为“清理”删除历史研究代码。

15m LONG/SHORT OOS asymmetry 记录为 observation risk，不得在本版本中据此拆 LONG/SHORT 参数、禁用方向或改变 Signal 语义。

该决定只覆盖 5m/15m intraday V1；1d 仍是独立、非阻塞 research track。

### Gate B-R: Human approval of slope-only intraday Calibration

**Hard stop.** 在创建 production Calibration artifact 前，必须再次取得用户明确批准以下完整语义：

```text
1. 5m slope = 0.688190651160584793944957992
2. 15m slope = 1.329531078893356968545882036
3. intraday MACD zero-band hard gate rejected by OOS
4. accepted intraday Calibration is slope-only
5. macd_zero_distance_abs/bps remain observation/research-only
6. 15m LONG OOS asymmetry is an observation risk only; no direction-specific rule is introduced
```

当前用户仅批准了“设计收缩”，**尚不得把它解释为 Gate B-R 对 production Calibration artifact 的 promotion 授权**。

### Amended Task 5: Persist slope-only accepted intraday Calibration

**Only after Gate B-R passes.**

Production artifact：

```json
{
  "schema_version": 1,
  "calibration_id": "subing_intraday_v1",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {
    "5m": "0.688190651160584793944957992",
    "15m": "1.329531078893356968545882036"
  }
}
```

Test fixture使用独立 test ID/values，但 schema 同样**不得包含** `macd_zero_band_bps`。

Loader contract：

```python
@dataclass(frozen=True, slots=True)
class SubingCalibration:
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]
```

Requirements：

- missing production file -> pending；
- malformed existing file -> stable fail-closed config error；
- no env/localStorage/runtime override；
- 1d 不进入这个 artifact；
- 不接受/忽略 `macd_zero_band_bps` 等未知 executable threshold 字段；schema 漂移必须 fail-closed；
- artifact commit 只让 Calibration 成为 Git fact，不批准 MACD Gate C、Signal、Alert 或 Runtime。

### Amended Task 7: Deterministic intraday Signal without zero-band hard gate

Gate C 仍按原计划独立执行。Gate C 通过后，Primary LONG hard conditions 为：

```text
price ABOVE
slope5 > threshold(primary)
slope10 > 0
MACD GOLDEN
volume_ratio_prev available and >= 3
latest confirmed companion READY
companion price ABOVE
companion slope5 > threshold(companion)
companion slope10 > 0
```

SHORT 完全镜像。

`macd_zero_distance_abs/bps` 继续出现在 Factor/Web/research，但不进入 executable condition list，不影响 `MATCHED / NOT_MATCHED`。必须新增 regression：在所有其他输入相同的情况下，仅改变 zero-distance 值不能改变 Signal status/direction。

Signal 仍必须执行 scoped MACD FormalPolicy capability/equivalence Gate；删除 zero-band 不代表 generic MACD capability 被提升。

### Amended downstream sequence

```text
Gate B-R（pending）
→ slope-only Calibration artifact
→ Task 6 scoped MACD evidence
→ Gate C
→ amended Task 7 Signal（无 zero-band hard gate）
→ Task 8 read model/Web
→ Live human observation
→ Future Alert V2（独立设计）
```

Task 9 的 1d track 不自动继承 intraday zero-band rejection；若未来继续 1d，必须单独研究/批准。

### Amended Plan Acceptance

```text
5m/15m slope thresholds passed Discovery/Validation + human Gate A
intraday zero-band research completed with frozen-candidate OOS vs NO-BAND
intraday zero-band hard gate rejected; A/B are not re-tested on Validation
accepted intraday Calibration is slope-only and Git-tracked/versioned
macd_zero_distance_abs/bps remain observable/researchable but non-executable
scoped MACD policy passes independent Review + human Gate C
Generic MACD registry remains unpromoted
deterministic MATCHED LONG/SHORT uses price+slope+MACD cross+3x volume+companion alignment
same-boundary 15m wins
15m LONG OOS asymmetry is recorded but does not create direction-specific rules
1d remains non-blocking/pending unless separately accepted
no Signal persistence
no Alert V2
no DB/Canonical/Redis schema addition
no Runtime mutation
no automatic parameter promotion
```

---

**Goal:** 在 Factor Observation 已独立验收后，建立可重复、只读的 5m/15m Calibration Research，经过人工 Gate 将最小 intraday Calibration 固化为 Git 事实，再交付确定性的 `MATCHED LONG/SHORT` 入场 Signal；1d 保持非阻塞研究轨，Alert V2 仍不实现。

**Architecture:** 历史研究只通过 `MarketDataService` 获取 actual-dominant 结果，并按 `resolved_contract_segments` 将 bars 切成互不继承状态的 rank1 segment；每个 segment 单独调用已有 `calculate_subing_factor_series()`，future-label builder 的方向由 Slope/Zero-Band cohort 显式传入，绝不自行猜测。Zero-Band decision cohort 必须重建完整 5m↔15m latest-confirmed relationship。研究 CLI 只输出 stdout JSON；只有人工批准后的最小 Calibration 才写入 `data/research_policies/` 并注入 pure Signal evaluator。

**Tech Stack:** Python 3 / argparse unified `guiyi` CLI / Decimal / SQLAlchemy read session / MarketDataService / quant-core FormalPolicy / FastAPI / Vue 3 / TypeScript / Vitest / Playwright / Git-tracked JSON policy artifact.

## Global Constraints

- 前置条件：`docs/superpowers/plans/2026-08-13-subing-factor-observation-v1.md` 已全部通过并独立 Review。
- 设计事实源：`docs/superpowers/specs/2026-08-13-subing-factor-signal-research-design.md`。
- 5m/15m 是主路径；1d Calibration/Signal Research 不阻塞 intraday Signal。
- 所有历史研究只读 `MarketDataService`；不得直接读 Catalog/Parquet/Redis/RQData 或写 Canonical。
- 每个 rank1 segment 独立计算 EMA/MACD/Slope；不得跨 segment 继承 state，不得取 pre-rank1 数据补 warm-up。
- 5m/15m 3/5/8K labels 不跨 `trading_day` 或 rank1 segment。
- Slope 先于 Zero-Band；禁止联合优化。
- 第一轮阈值都 timeframe-wide；Zero-Band 使用 `zero_distance_bps`，不预建 product×timeframe 矩阵。
- Zero-Band Cohort B 必须满足除 zero-band 外全部 SuBing 条件，包括 latest-confirmed companion alignment。
- Discovery 只给候选；Validation 用人工冻结的精确值；系统不自动选“最优”、不自动晋升。
- Accepted Calibration 必须 Git-tracked/versioned/human-reviewable；聊天、CLI 临时参数、stdout、localStorage 不是正式事实源。
- Generic `macd` registry 保持 `compatibility_validated/live_capable=False/alert_capable=False`。正式 Signal 使用独立 scoped FormalPolicy，且必须证明它与 Factor observation policy 的 seed/histogram/lookback 数学口径等价。
- Formal Signal 唯一条件：`status == MATCHED && direction in {LONG, SHORT}`。
- 不实现持仓、退出、8K、止损止盈、Backtest、Alert V2、WeCom、migration、Runtime switch、订单。
- Alert V1 全部保持原样。

## File Map

**Create**
- `services/quant-api/app/market_data/subing_calibration.py`
- `services/quant-api/app/market_data/subing_calibration_service.py`
- `services/quant-api/tests/test_subing_calibration.py`
- `services/quant-api/tests/data_foundation/test_subing_calibration_service.py`
- `services/quant-api/app/guiyi_cli/research_parser.py`
- `services/quant-api/app/guiyi_cli/research_commands.py`
- `services/quant-api/tests/test_research_cli.py`
- `data/research_policies/subing_calibration_intraday_v1.json` only after Gate B.
- `services/quant-api/tests/fixtures/subing_calibration_test_v1.json` test-only.

**Modify**
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/app/market_data/subing_research.py`
- `packages/quant-core/guiyi_quant/indicators/policy.py`
- `docs/INDICATOR_KERNEL.md`
- `services/quant-api/app/market_data/subing_read_service.py`
- `services/quant-api/app/market_data/composition.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/tests/test_subing_research.py`
- `services/quant-api/tests/data_foundation/test_subing_read_service.py`
- `services/quant-api/tests/test_subing_api.py`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/components/market/SubingStatusStrip.vue`
- `apps/quant-web/src/components/market/SubingResearchSection.vue`
- `apps/quant-web/tests/subingResearch.test.ts`
- `apps/quant-web/e2e/market-research.spec.mjs`
- `README.md`
- `TESTING.md`
- `docs/ARCHITECTURE.md`
- `STATUS.md` only after actual completion.

---

### Task 1: Build segment-local future labels and deterministic Calibration statistics

**Files:** create `subing_calibration.py`, `test_subing_calibration.py`.

**Interfaces:** `DirectionalSide`, `SubingOutcome`, `SubingResearchSample`, `ThresholdEvaluation`, `CalibrationReport`, `build_outcomes_at()`, `build_research_samples(..., direction_selector)`, `evaluate_threshold()`, `candidate_quantiles()`.

- [ ] **Step 1: Write failing exact 3/5/8K tests**

Use local Factor/bar builders. Assert LONG/SHORT formulas, same-day/segment boundary and explicit direction-selector behavior:

```python
samples = build_research_samples(
    factor_results,
    bars,
    horizons=(3, 5, 8),
    direction_selector=lambda index, factor: DirectionalSide.LONG if index == 0 else None,
)
assert samples[0].direction is DirectionalSide.LONG
assert samples[0].outcomes[3].directional_return_bps == Decimal("300")
assert samples[0].outcomes[3].mfe_bps == Decimal("500")
assert samples[0].outcomes[3].mae_bps == Decimal("-200")
```

A selector returning `None` means “not part of this cohort”；label code must never infer LONG/SHORT from price/MACD by itself.

- [ ] **Step 2: Run focused test; confirm missing module**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_subing_calibration.py
```

- [ ] **Step 3: Implement label formulas**

For entry close `C0`, direction sign `s`:

```python
directional_return_bps = s * (future_n.close - C0) / C0 * Decimal(10000)
```

LONG:

```python
mfe_bps = (max(highs) - C0) / C0 * Decimal(10000)
mae_bps = (min(lows) - C0) / C0 * Decimal(10000)
```

SHORT:

```python
mfe_bps = (C0 - min(lows)) / C0 * Decimal(10000)
mae_bps = (C0 - max(highs)) / C0 * Decimal(10000)
```

`ema21_failure=True` if any future READY snapshot closes below EMA21 for LONG or above for SHORT.

5m/15m require all N future bars same trading_day, contract and segment_start; 1d requires same contract/segment. Otherwise that horizon is `None`.

- [ ] **Step 4: Define Slope cohort through an explicit selector**

```text
LONG: price ABOVE, slope5 > 0, slope10 > 0
SHORT: price BELOW, slope5 < 0, slope10 < 0
```

Selector returns LONG/SHORT only for those rows. Studied scalar = `abs(slope5_bps)`; no flat threshold forms the discovery cohort.

- [ ] **Step 5: Implement product-bounded quantiles/evaluation**

Per product use inclusive P10/P20/P30 (`statistics.quantiles(n=100, method="inclusive")`). One value -> same value for all three; zero -> unavailable. `evaluate_threshold` returns counts, median directional return/MFE/MAE, EMA21 failure rate by horizon; no ranking or `best` field.

- [ ] **Step 6: Run tests and commit**

```bash
git add services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: add SuBing calibration research math"
```

---

### Task 2: Build MarketDataService-only historical Calibration and full multi-TF cohort orchestration

**Files:** create `subing_calibration_service.py`, `test_subing_calibration_service.py`; modify `composition.py`.

**Interfaces:** `CalibrationResearchRequest`, `SlopeThresholds`, `SubingCalibrationResearchService.run()`.

- [ ] **Step 1: Write failing segment + companion Cohort B tests**

Fake MarketDataService returns explicit M5/M15 actual-dominant series with two rank1 segments and a large rollover gap. Require separate Factor passes per segment, latest companion `<=T`, no future companion, and Cohort B rejecting a primary if companion price/slope conflicts.

- [ ] **Step 2: Run focused test; confirm service missing**

- [ ] **Step 3: Implement trading-day-safe query and segment factorization**

```python
_SHANGHAI = ZoneInfo("Asia/Shanghai")

def _research_window(since: date, through: date) -> tuple[datetime, datetime]:
    start = datetime.combine(since - timedelta(days=1), time.min, _SHANGHAI).astimezone(UTC)
    end = datetime.combine(through + timedelta(days=1), time.max, _SHANGHAI).astimezone(UTC)
    return start, end
```

Query only:

```python
MarketDataService.query(
    SeriesQuery(SeriesKind.ACTUAL_DOMINANT, symbol, frequency, start, end)
)
```

Filter by trading_day. For each `resolved_contract_segment`, slice its bars and call `calculate_subing_factor_series()` separately with that contract/segment start. No cross-segment Factor state.

- [ ] **Step 4: Implement O(N) latest-confirmed companion alignment**

For one product build M5/M15 Factor streams separately. Companion eligible only when READY, `bar_end<=primary.bar_end`, same contract and same segment start. Use monotonic two-pointer/index, not nested full scans.

- [ ] **Step 5: Implement Slope discovery/validation**

Discovery: one product at a time -> product P10/P20/P30 -> discard rows; global A/B/C = median across each product quantile (equal product weight); second read pass evaluates all three. Validation requires one explicit `slope_threshold_bps` on a later window. Never choose a winner.

- [ ] **Step 6: Implement Zero-Band Cohort A + full SuBing Cohort B**

Intraday request requires both approved thresholds in `SlopeThresholds(m5, m15)`.

Cohort A direction selector:

```text
GOLDEN -> LONG
DEAD   -> SHORT
NONE   -> excluded
```

Cohort B direction selector requires every hard condition except zero-band:

```text
LONG primary:
price ABOVE
slope5 > primary approved threshold
slope10 > 0
MACD GOLDEN
volume_ratio_prev is available and >= 3
latest confirmed companion READY
companion price ABOVE
companion slope5 > companion approved threshold
companion slope10 > 0

SHORT: mirrored signs + MACD DEAD
```

For 1d Cohort B: price side + approved slope + cross; no companion, daily volume not hard.

Discovery candidates come from per-product P20/P40/P60 of **Cohort B** `zero_distance_bps`, median across products. Each candidate reports both Cohort A and Cohort B outcomes. Validation evaluates both cohorts at explicit `distance_bps <= zero_band_bps`. No product overrides.

- [ ] **Step 7: Add builder, run tests, commit**

```python
def build_subing_calibration_research_service(session: Session) -> SubingCalibrationResearchService:
    return SubingCalibrationResearchService(
        market_data=build_market_data_service(session),
        products=load_active_products(),
    )
```

Prove no MarketReadService/Redis/provider construction.

```bash
git add services/quant-api/app/market_data/subing_calibration_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/app/market_data/composition.py
git commit -m "feat: add SuBing calibration research service"
```

---

### Task 3: Expose read-only reproducible Calibration CLI

**Files:** create `research_parser.py`, `research_commands.py`, `test_research_cli.py`; modify `guiyi_cli/main.py`.

**Command:**

```text
guiyi research subing-calibration
  --phase slope|zero-band
  --mode discovery|validation
  --frequency 5m|15m|1d
  --since YYYY-MM-DD
  --through YYYY-MM-DD
  [--symbol X]
```

Additional matrix:

```text
slope discovery: threshold flags forbidden
slope validation: --slope-threshold-bps required
zero-band discovery 5m/15m: --slope-threshold-5m-bps + --slope-threshold-15m-bps required; zero-band threshold forbidden
zero-band validation 5m/15m: both slope thresholds + --zero-band-bps required
zero-band discovery 1d: --slope-threshold-bps required
zero-band validation 1d: --slope-threshold-bps + --zero-band-bps required
```

- [ ] **Step 1: Write failing parser/command mode-matrix tests**

Invalid frequency/non-finite/negative values -> exit 2 through existing redacted argument error. `--symbol` absent -> active 60.

- [ ] **Step 2: Add parser/command execution**

Parse date with `date.fromisoformat`, threshold with Decimal; validate before service construction.

Report payload must be JSON-safe and include:

```text
schema_version = 1
command = research.subing-calibration
status = ok
phase / mode / frequency / since / through
products
sample_count
product_sample_counts
candidate_thresholds as Decimal strings      # discovery
candidate_evaluations                        # discovery
cohorts A/B                                   # zero-band
threshold_evaluation                         # validation
```

No `best_threshold`, `approved`, trade instruction or performance claim.

- [ ] **Step 3: Wire `research` branch in main.py**

Update module/docstring to say CLI domains are `data / research / runtime`. Inject a research-service factory for unit tests. Research execution errors always `readonly=True`. Data/runtime behavior remains unchanged.

- [ ] **Step 4: Run CLI regressions and commit**

Run `test_research_cli.py`, existing data CLI tests and `test_alert_cli.py`.

```bash
git add services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_research_cli.py
git commit -m "feat: add read-only SuBing calibration CLI"
```

---

### Gate A: Human approval of intraday Slope candidates

**Hard stop.** Run 5m and 15m Discovery on the chosen Discovery window, then later non-overlapping Validation for the exact candidates under review. Continue only after explicit approval of exact Decimal values for:

```text
5m slope_flat_threshold_bps_per_bar
15m slope_flat_threshold_bps_per_bar
```

Do not create accepted Calibration artifact yet. These two values are immutable inputs to all subsequent intraday Zero-Band research.

---

### Task 4: Complete full multi-TF Zero-Band research with Gate A thresholds

- [ ] **Step 1: Run 5m Discovery with both frozen 5m/15m slope thresholds**

Verify Cohort A and full companion-aware Cohort B, exact slope inputs and three unranked candidate bands.

- [ ] **Step 2: Run 15m Discovery with the same frozen pair**

Verify 15m primary uses latest confirmed 5m companion.

- [ ] **Step 3: Human-select one 5m and one 15m candidate for validation**

Stop until exact values are named.

- [ ] **Step 4: Run later-window Validation for both candidates**

Every run includes the frozen slope pair plus the one zero-band threshold under validation. Slope values cannot change during this phase.

- [ ] **Step 5: Present Cohort A/B reports; do not commit stdout**

---

### Gate B: Human approval of final intraday Calibration

**Hard stop.** Require explicit approval of all four Decimal values:

```text
5m slope threshold
15m slope threshold
5m zero-band bps
15m zero-band bps
```

Any post-validation change creates a new candidate and requires re-validation.

---

### Task 5: Persist accepted intraday Calibration as minimal Git fact

**Files:** create production artifact only now; create test fixture; modify calibration loader/tests.

- [ ] **Step 1: Create explicit test-only fixture**

```json
{
  "schema_version": 1,
  "calibration_id": "subing_test_intraday_v1",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {"5m": "1.25", "15m": "0.80"},
  "macd_zero_band_bps": {"5m": "12.50", "15m": "8.00"}
}
```

Production code never loads this fixture.

- [ ] **Step 2: Implement/test immutable loader**

```python
@dataclass(frozen=True, slots=True)
class SubingCalibration:
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]
    macd_zero_band_bps: Mapping[BarFrequency, Decimal]
```

Missing production file -> pending; malformed existing file -> stable fail-closed config error; no env/runtime override. Test unknown schema, non-finite/negative, missing values, 1d not accepted.

- [ ] **Step 3: Create production artifact using exact Gate B values**

`data/research_policies/subing_calibration_intraday_v1.json` contains only schema=1, stable ID, accepted 5m/15m and four exact Decimal strings. No 1d, override, timestamp, research rows or claims.

- [ ] **Step 4: Inspect diff, run tests, commit**

```bash
git add data/research_policies/subing_calibration_intraday_v1.json \
  services/quant-api/tests/fixtures/subing_calibration_test_v1.json \
  services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: accept SuBing intraday calibration v1"
```

This commit makes Calibration a repo fact only; it does not authorize Alert/Runtime.

---

### Task 6: Prepare scoped MACD formal Signal policy evidence

**Files:** modify only MACD/registry tests until Gate C.

- [ ] **Step 1: Add evidence tests for explicit MACD math**

Test fast12/slow26/signal9 + sma_window + histogram_scale2 for first ready indexes, equality edges, identical historical/completed-live sequences, and no change to prior points when a later confirmed close is appended. Assert generic registry remains compatibility/live false/alert false.

- [ ] **Step 2: Add a policy-equivalence test target**

Define the exact required equivalence tuple for Factor observation vs proposed Signal policy:

```python
("sma_window", 2, "fast12_slow26_signal9", True)
```

The future scoped policy must match `web_macd_legacy_v1` on `seed_policy`, `histogram_scale`, `lookback`, `confirmed_only` or Signal must fail closed.

- [ ] **Step 3: Run current Indicator tests and independent Review**

Do not modify `policy.py` yet. Review confirms same math, closed-bar causality, scope only SuBing Signal, no generic promotion/backtest/alert.

---

### Gate C: Human approval of scoped MACD Signal capability

**Hard stop.** Only after independent evidence review and explicit user approval may `policy.py` be modified. This does not approve Alert V2 or generic MACD capability.

---

### Task 7: Create approved scoped MACD policy and deterministic intraday Signal

**Files:** modify `policy.py`, `docs/INDICATOR_KERNEL.md`, relevant Indicator tests, `subing_research.py`, `test_subing_research.py`.

- [ ] **Step 1: Add scoped policy**

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

- [ ] **Step 2: Update Indicator canonical without generic promotion**

Document that Alert V2 needs separate future capability decision.

- [ ] **Step 3: Write failing Signal tests**

Cover exact LONG/SHORT, hard failure, missing calibration, required `volume_ratio_prev=None`, companion conflict, 1d pending and same-boundary resolver.

```python
result = evaluate_subing_signal(primary_long, companion_long, calibration)
assert result.status is SubingSignalStatus.MATCHED
assert result.direction is SubingDirection.LONG
```

- [ ] **Step 4: Implement immutable hard conditions**

Primary LONG intraday:

```text
price ABOVE
slope5 > threshold(primary)
slope10 > 0
MACD GOLDEN
zero_distance_bps <= zero-band(primary)
volume_ratio_prev available and >= 3
```

SHORT mirrors. Companion LONG/SHORT checks price side + slope5 threshold(companion) + slope10 sign only.

- [ ] **Step 5: Enforce scoped Signal policy and observation-policy equivalence before MATCHED**

```python
observation_policy = get_formal_policy("web_macd_legacy_v1")
signal_policy = require_formal_policy(
    "subing_macd_sma_window_scale2_v1",
    consumer="subing_signal",
)
```

Compare `seed_policy`, `histogram_scale`, `lookback`, `confirmed_only`. Any difference -> stable `SUBING_MACD_POLICY_MISMATCH`; never MATCHED.

- [ ] **Step 6: Implement status/direction priority**

```text
Factor insufficient or required Factor value unavailable -> INSUFFICIENT_DATA / NONE
calibration not accepted -> RESEARCH_PENDING / candidate direction or NONE
scoped policy unavailable -> RESEARCH_PENDING / candidate direction or NONE
known hard FAIL -> NOT_MATCHED / NONE
all pass -> MATCHED / LONG|SHORT
```

- [ ] **Step 7: Implement same-boundary resolver**

Both matched same bar/direction -> only 15m, `lower_tf_confirmation=True`, `higher_timeframe_wins`. Opposite matched directions same bar -> stable fail-closed `SUBING_SIGNAL_DIRECTION_CONFLICT`. Otherwise return independently matched timeframe.

- [ ] **Step 8: Run tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_calibration.py

git add packages/quant-core/guiyi_quant/indicators/policy.py docs/INDICATOR_KERNEL.md \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_research.py
git commit -m "feat: evaluate SuBing entry signals"
```

---

### Task 8: Inject accepted Calibration and expose Signal to Product Workspace

**Files:** modify `SubingReadService`/composition/API DTOs/tests and existing SuBing Web components/tests/E2E.

- [ ] **Step 1: Write failing read/API tests**

5m/15m test calibration can return MATCHED; 1d remains RESEARCH_PENDING. Assert no AlertService use and no DB mutation.

- [ ] **Step 2: Load only tracked production Calibration in composition**

```python
PROJECT_ROOT / "data/research_policies/subing_calibration_intraday_v1.json"
```

No env/localStorage/runtime override.

- [ ] **Step 3: Evaluate same-cutoff Signal and resolver**

5m request evaluates 5m primary vs aligned 15m. If same `bar_end`, also evaluate 15m full signal by reversing the same two snapshots and resolve. 15m request mirrors. Do not persist/remember Signal.

- [ ] **Step 4: Extend HTTP DTO**

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

- [ ] **Step 5: Update Web wording only**

```text
MATCHED LONG  -> 买入信号
MATCHED SHORT -> 卖出信号
RESEARCH_PENDING -> 研究参数/能力待冻结
INSUFFICIENT_DATA -> 指标 warm-up 中
NOT_MATCHED -> 当前不匹配
```

No trade management, button, Alert toggle or notification.

- [ ] **Step 6: Extend E2E and run all SuBing + Alert V1 regressions**

Assert no SuBing Alert API call. Then commit focused backend/Web files with message `feat: expose SuBing entry signal observation`.

---

### Task 9: Keep 1d as non-blocking research track

- [ ] Run 1d Slope Discovery; verify outcomes may cross trading days but not rank1 segment.
- [ ] Review independently; never change accepted intraday values because of 1d.
- [ ] If user elects to continue, reuse explicit human Gate pattern for 1d Validation/Zero-Band.
- [ ] Do not modify `subing_calibration_intraday_v1.json`; a future accepted 1d version requires separate approval.
- [ ] Any 1d correctness code fix must rerun intraday Signal tests.

---

### Task 10: Close CLI/docs/testing/status boundaries

**Files:** modify `README.md`, `TESTING.md`, `docs/ARCHITECTURE.md`, and `STATUS.md` only after actual completion.

- [ ] **Step 1: Document new read-only research CLI in README and TESTING**

Update README's public CLI surface to include `guiyi research subing-calibration`. TESTING examples use explicitly labeled research windows and state: MarketDataService-only reads, stdout JSON, no provider/DB/Canonical/Redis write. Do not paste accepted production thresholds into generic examples unless sourced from tracked artifact.

- [ ] **Step 2: Add no-side-effect SuBing Calibration/Signal tests to TESTING**

Include all new Calibration service/CLI/Signal tests.

- [ ] **Step 3: Align ARCHITECTURE**

Document `MarketDataService -> read-only Calibration Research`, `Git-tracked accepted Calibration -> pure Signal`, `SubingReadService -> Web`; no research DB/Signal persistence/Alert integration.

- [ ] **Step 4: Run full repository verification**

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

No notification, Runtime switch, migration, RQData write or Canonical mutation.

- [ ] **Step 5: Update STATUS conservatively only after gates/checks pass**

Record accepted 5m/15m Calibration Git fact, scoped MACD Gate, Product Workspace Entry Signal; 1d pending unless separately accepted; Alert V1 unchanged; no Alert V2/Runtime deployment.

- [ ] **Step 6: Commit documentation/status**

```bash
git add README.md TESTING.md docs/ARCHITECTURE.md STATUS.md
git commit -m "docs: record SuBing entry signal boundaries"
```

## Plan Acceptance

```text
5m/15m Slope -> later Validation -> human approval
Zero-Band Cohort B includes full latest-confirmed companion relationship
5m/15m Zero-Band -> later Validation -> human approval
accepted intraday Calibration is a tracked/versioned Git fact
scoped MACD policy passes independent Review + human Gate
scoped policy is mathematically equivalent to Factor observation policy on seed/histogram/lookback/confirmed-only
Generic MACD registry remains unpromoted
deterministic MATCHED LONG/SHORT is available in read model/Web
same-boundary 15m wins
1d remains non-blocking/pending unless separately accepted
no Signal persistence
no Alert V2
no DB/Canonical/Redis schema addition
no Runtime mutation
no automatic parameter promotion
```

Future `Alert V2 — SuBing Entry Signal Integration` remains a separate design/spec/plan after a real Live observation period.