# SuBing Calibration and Entry Signal V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Factor Observation 已验收、Slope Gate A 已通过、intraday Zero-Band hard gate 已被 OOS 拒绝的基础上，将 **slope-only intraday Calibration** 固化为 Git 事实，再通过独立 MACD Gate C 交付确定性的 5m/15m `MATCHED LONG/SHORT` 入场观察；不实现 Alert V2、Strategy、订单或 Runtime promotion。

**Architecture:** Historical research 只经 `MarketDataService`，每个 rank1 segment 独立计算 Factor；accepted intraday Calibration 只保存 5m/15m slope threshold。`macd_zero_distance_abs/bps` 继续作为 Factor/Web/research 字段，但不参与 executable Signal。正式 Signal 由 pure `subing_research.py` 消费 slope-only Calibration + scoped MACD policy，再由现有 `SubingReadService` 暴露到 Product Workspace。

**Tech Stack:** Python 3 / Decimal / MarketDataService / quant-core FormalPolicy / FastAPI / Vue 3 / TypeScript / Vitest / Playwright / Git-tracked JSON calibration artifact.

## Global Constraints

- 设计事实源：`docs/superpowers/specs/2026-08-13-subing-factor-signal-research-design.md` 当前 2026-08-14 版本。
- 5m/15m 是 intraday 主路径；1d 是独立、非阻塞 research track。
- Historical 只读 `MarketDataService`；不得直读 Catalog/Parquet/Redis/RQData，不写 Canonical。
- 每个 rank1 segment 独立计算 EMA/MACD/Slope；不得跨 segment state，不得 pre-rank1 warm-up。
- 5m/15m future labels 不跨 `trading_day`、contract 或 rank1 segment。
- Gate A slope pair 已冻结；后续不得修改。
- Intraday zero-band hard gate 已由 frozen-C OOS vs NO-BAND 拒绝；不得回头在同一 Validation window 测 A/B 或新造 threshold。
- `macd_zero_distance_abs/bps` 保留 Factor/Web/research，不进入 accepted intraday Calibration 和 Signal hard conditions。
- 15m LONG OOS asymmetry 只记录风险，不得据此创建方向特例。
- Accepted Calibration 必须 Git-tracked/versioned/human-reviewable；无 env/localStorage/runtime override。
- Generic `macd` registry 保持 `compatibility_validated/live_capable=False/alert_capable=False`；Signal 只允许独立 scoped FormalPolicy。
- Formal Signal 唯一条件：`status == MATCHED && direction in {LONG, SHORT}`。
- 不实现持仓、退出、Backtest、Alert V2、WeCom、migration、Runtime switch、订单。
- Alert V1 与 Data Foundation 保持原样。

---

## Execution Status Before This Plan Continues

已完成：

```text
Task 1  Calibration research math            a1e99335 + d6d6b14a
Task 2  MarketDataService-only research      e384028f + 686026a4
Task 3  read-only Calibration CLI            b2a6dcea
Gate A  slope approval record                b9494dc0
Task 4  Zero-Band Discovery + frozen-C OOS   COMPLETE, no tracked research-output commit
```

Gate A frozen values：

```text
5m = 0.688190651160584793944957992
15m = 1.329531078893356968545882036
```

Zero-Band frozen OOS candidate（research history only）：

```text
5m C  = 16.01901065112843434322837440
15m C = 27.16954645407146036410753274
```

OOS vs NO-BAND 结论：intraday zero-band hard gate **rejected**。不再进入任何 zero-band 参数选择。

---

## Gate B-R: Human Approval of Slope-only Intraday Calibration

**HARD STOP.** 当前下一步不是写 artifact，而是等待用户明确批准以下完整语义：

```text
1. 5m slope = 0.688190651160584793944957992
2. 15m slope = 1.329531078893356968545882036
3. intraday MACD zero-band hard gate rejected by OOS
4. accepted intraday Calibration is slope-only
5. macd_zero_distance_abs/bps remain observation/research-only
6. 15m LONG OOS asymmetry remains observation risk only; no direction-specific rule
```

只有用户明确回复批准 Gate B-R，才允许执行 Task 5。

---

### Task 5: Persist accepted slope-only intraday Calibration as a Git fact

**Files:**
- Create: `data/research_policies/subing_calibration_intraday_v1.json`
- Create: `services/quant-api/tests/fixtures/subing_calibration_test_v1.json`
- Modify: `services/quant-api/app/market_data/subing_calibration.py`
- Modify: `services/quant-api/tests/test_subing_calibration.py`

**Interfaces:**
- Produces: immutable `SubingCalibration` loader contract.
- Later Tasks consume only `slope_flat_threshold_bps_per_bar` for 5m/15m.

- [ ] **Step 1: Write failing schema/loader tests**

Add tests for missing production file, valid slope-only fixture, unknown schema, negative/non-finite values, missing 5m/15m value, 1d acceptance, and executable zero-band field rejection.

Required shape:

```python
@dataclass(frozen=True, slots=True)
class SubingCalibration:
    calibration_id: str | None
    accepted_timeframes: frozenset[BarFrequency]
    slope_flat_threshold_bps_per_bar: Mapping[BarFrequency, Decimal]
```

Test that this payload is rejected rather than silently tolerated:

```json
{
  "schema_version": 1,
  "calibration_id": "bad",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {"5m": "1", "15m": "2"},
  "macd_zero_band_bps": {"5m": "10", "15m": "20"}
}
```

- [ ] **Step 2: Run focused tests and confirm red state**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_calibration.py
```

Expected: FAIL until slope-only loader/schema exists.

- [ ] **Step 3: Implement strict slope-only loader**

Rules:

```text
production file missing      -> pending calibration
valid file                   -> exact Decimal values
unknown/executable extra key -> fail closed
malformed value              -> fail closed
no env/runtime override
```

Do not add an Infinity/null/sentinel representation for zero-band.

- [ ] **Step 4: Create test fixture**

```json
{
  "schema_version": 1,
  "calibration_id": "subing_test_intraday_v1",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {
    "5m": "1.25",
    "15m": "0.80"
  }
}
```

Production code must never load this fixture.

- [ ] **Step 5: Create production artifact with exact Gate A values**

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

No zero-band, 1d, timestamp, research rows, performance claim or override.

- [ ] **Step 6: Run tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_research_cli.py

git add data/research_policies/subing_calibration_intraday_v1.json \
  services/quant-api/tests/fixtures/subing_calibration_test_v1.json \
  services/quant-api/app/market_data/subing_calibration.py \
  services/quant-api/tests/test_subing_calibration.py
git commit -m "feat: accept SuBing slope-only intraday calibration"
```

This commit creates a Calibration fact only; it does not approve MACD Gate C, Signal, Alert or Runtime.

---

### Task 6: Prepare scoped MACD formal Signal policy evidence

**Files:**
- Modify tests only until Gate C; do not modify `policy.py` before approval.

**Interfaces:**
- Evidence tuple must be exactly:

```python
("sma_window", 2, "fast12_slow26_signal9", True)
```

- [ ] **Step 1: Add MACD math evidence tests**

Cover fast12/slow26/signal9 + sma_window + histogram_scale2, first-ready indexes, Golden/Dead equality edges, Historical/completed-Live identical input parity, and append-only confirmed causality.

- [ ] **Step 2: Add policy-equivalence target test**

The proposed scoped policy must match Factor observation policy on:

```text
seed_policy
histogram_scale
lookback
confirmed_only
```

Generic registry must remain compatibility/live/alert false.

- [ ] **Step 3: Run evidence tests and independent Review**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py
```

Stop and present evidence. Do not modify `policy.py`.

---

## Gate C: Human Approval of Scoped MACD Signal Capability

**HARD STOP.** Only after independent evidence review and explicit user approval may Task 7 modify `policy.py`.

Gate C approves only a SuBing entry-Signal consumer; it does not approve generic MACD, formal Backtest, Alert V2 or Runtime.

---

### Task 7: Add scoped MACD policy and deterministic intraday Signal

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: relevant Indicator tests
- Modify: `services/quant-api/app/market_data/subing_research.py`
- Modify: `services/quant-api/tests/test_subing_research.py`

**Interfaces:**
- Produces: `SubingSignalStatus`, `SubingDirection`, condition result types, `evaluate_subing_signal()`, same-boundary resolver.

- [ ] **Step 1: Add scoped policy after Gate C**

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
)
```

- [ ] **Step 2: Write failing Signal tests**

Cover:

```text
exact LONG
exact SHORT
missing slope calibration
Factor unavailable
volume_ratio_prev unavailable
companion direction conflict
same-boundary 15m wins
opposite same-boundary direction conflict
1d remains pending
zero-distance non-executable regression
```

Zero-distance regression must construct two otherwise identical inputs with very different `macd_zero_distance_bps` and assert identical status/direction.

- [ ] **Step 3: Implement intraday hard conditions**

LONG primary:

```text
price ABOVE
slope5 > threshold(primary)
slope10 > 0
MACD GOLDEN
volume_ratio_prev available and >= 3
```

Companion LONG:

```text
price ABOVE
slope5 > threshold(companion)
slope10 > 0
```

SHORT mirrors all signs and uses MACD DEAD.

**Do not read zero-distance to decide Signal.**

- [ ] **Step 4: Enforce scoped policy equivalence**

```python
observation_policy = get_formal_policy("web_macd_legacy_v1")
signal_policy = require_formal_policy(
    "subing_macd_sma_window_scale2_v1",
    consumer="subing_signal",
)
```

Mismatch on seed/histogram/lookback/confirmed-only => stable `SUBING_MACD_POLICY_MISMATCH`, never MATCHED.

- [ ] **Step 5: Implement status priority**

```text
required Factor unavailable -> INSUFFICIENT_DATA / NONE
Calibration absent           -> RESEARCH_PENDING / candidate or NONE
MACD scoped policy pending   -> RESEARCH_PENDING / candidate or NONE
hard condition fail         -> NOT_MATCHED / NONE
all pass                    -> MATCHED / LONG|SHORT
```

`macd_zero_distance_abs/bps` unavailable does not make Signal insufficient.

- [ ] **Step 6: Implement same-boundary resolver**

Same bar + same direction -> one 15m Signal with `lower_tf_confirmation=True` and `HIGHER_TIMEFRAME_WINS`.

Opposite matched directions at same boundary -> fail closed with stable direction-conflict error/state.

- [ ] **Step 7: Update Indicator canonical**

Document scoped SuBing Signal capability only; generic MACD capability remains unchanged. Record zero-distance as observation/research-only for intraday V1.

- [ ] **Step 8: Run tests and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_calibration.py

git add packages/quant-core/guiyi_quant/indicators/policy.py \
  docs/INDICATOR_KERNEL.md \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_research.py
git commit -m "feat: evaluate SuBing slope-only entry signals"
```

---

### Task 8: Inject accepted Calibration and expose Signal to Product Workspace

**Files:**
- Modify: `services/quant-api/app/market_data/subing_read_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: related backend tests
- Modify: existing SuBing Web types/API/components/tests/E2E

- [ ] **Step 1: Write failing read/API tests**

5m/15m test calibration may produce MATCHED; 1d remains RESEARCH_PENDING. Assert no AlertService/DB mutation and no zero-band dependency.

- [ ] **Step 2: Load only tracked production Calibration**

```python
PROJECT_ROOT / "data/research_policies/subing_calibration_intraday_v1.json"
```

No env/localStorage/runtime override.

- [ ] **Step 3: Evaluate primary/companion at same cutoff**

5m evaluates 5m primary + aligned 15m companion; 15m mirrors. At shared boundary, evaluate both complete timeframe opportunities and resolve 15m wins. Do not persist Signal.

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

Do not emit a zero-band pass/fail condition. Zero-distance may remain in Factor DTO.

- [ ] **Step 5: Update Web wording**

```text
MATCHED LONG       -> 买入信号
MATCHED SHORT      -> 卖出信号
RESEARCH_PENDING   -> 研究参数/能力待冻结
INSUFFICIENT_DATA  -> 指标 warm-up 中
NOT_MATCHED        -> 当前不匹配
```

Continue showing zero-distance as descriptive MACD fact if desired, but never as Signal qualification.

- [ ] **Step 6: Extend E2E and commit**

Assert no SuBing Alert API call and no zero-band condition. Run SuBing + Alert V1 regressions, then commit focused backend/Web changes.

---

### Task 9: Keep 1d as non-blocking research track

- [ ] Run 1d Slope research only when explicitly requested.
- [ ] Intraday accepted slopes/zero-band rejection do not automatically alter 1d.
- [ ] A future accepted 1d version needs separate Discovery/Validation/human Gate and separate artifact/versioning decision.
- [ ] Any 1d correctness code fix reruns intraday Signal tests.

---

### Task 10: Close docs/testing/status boundaries

**Files:**
- Modify: `README.md`
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Document read-only research CLI**

README/TESTING must include `guiyi research subing-calibration` as read-only Historical research and state no provider/DB/Canonical/Redis writes.

- [ ] **Step 2: Document final intraday research decision**

Record:

```text
Gate A slope pair accepted
zero-band hard gate rejected by OOS
accepted Calibration slope-only
zero-distance Factor retained research-only
15m LONG asymmetry observation risk
```

- [ ] **Step 3: Align ARCHITECTURE**

Document `MarketDataService -> read-only Calibration Research`, `slope-only Git Calibration -> pure Signal`, `SubingReadService -> Web`; no research DB/Signal persistence/Alert integration.

- [ ] **Step 4: Run full verification**

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

- [ ] **Step 5: Update STATUS only after gates/checks actually pass**

Do not announce Signal/Alert/Runtime Ready prematurely.

- [ ] **Step 6: Commit docs**

```bash
git add README.md TESTING.md docs/ARCHITECTURE.md STATUS.md
git commit -m "docs: record SuBing slope-only signal boundaries"
```

---

## Plan Acceptance

```text
Gate A exact 5m/15m slope pair is preserved
intraday zero-band hard gate is rejected by frozen-candidate OOS vs NO-BAND
A/B are not re-tested on Validation and no new zero-band parameter is invented
accepted intraday Calibration is a slope-only tracked/versioned Git fact
macd_zero_distance_abs/bps remain Factor/Web/research-only
scoped MACD policy passes independent Review + Gate C
Generic MACD registry remains unpromoted
deterministic MATCHED LONG/SHORT uses price+slope+MACD cross+3x volume+companion alignment
zero-distance cannot change Signal status/direction
same-boundary 15m wins
15m LONG OOS asymmetry is recorded without direction-specific rule
1d remains non-blocking/pending unless separately accepted
no Signal persistence
no Alert V2
no DB/Canonical/Redis schema addition
no Runtime mutation
no automatic parameter promotion
```

Future `Alert V2 — SuBing Entry Signal Integration` remains a separate design/spec/plan after a real Live observation period.