# 主力照妖镜·期货 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在完全保留 `main_force_mirror_v0` 的前提下，实现 60m-only、observation-only 的 `main_force_mirror_futures_v1`：以 OHLCV + Open Interest + 真实物理合约分段计算五类期货持仓压力状态、对称“追多小心 / 追空小心”、70/100 风险证据评分、Episode latch/re-arm、Web 三 Tab 观察与只读 Historical Shadow。

**Architecture:** Python Indicator Kernel 是唯一数学与 lifecycle 权威；Web 只保留逐点 golden 对齐的浏览器 mirror。Historical/Live Bar 在 Web 边界先绑定 `physicalContract`，任何换月、OI/input/timestamp invalid 都切断 calculation block 并重新 warm-up；`actual_dominant` 绝不跨真实合约继承 ATR、OI baseline、pressure、caution latch 或 re-arm。实现完成后只形成 Web observation 与 read-only Shadow 入口，不新增 Alert、DB、Canonical、Runtime 或交易能力。

**Tech Stack:** Python 3.13、NumPy、FastAPI CLI composition、MarketDataService、Vue 3、TypeScript 6、Lightweight Charts 5.2、Node test、Playwright、pytest、Ruff、Mypy、Vite。

**Spec:** `docs/superpowers/specs/2026-08-19-main-force-mirror-futures-v1-design.md`

## Global Constraints

- 每个 Task 开始前读取执行时最新 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、本 Spec 和本 Plan；若 active canonical 与本 Plan 冲突，按 canonical fail-closed，不能猜。
- 执行基线必须是当时最新 `develop`，并包含已批准 Spec；不得从旧 v1.6.1 tag 或旧 V0 task branch 开工。
- `main_force_mirror_v0` 的 source、version、formula、golden、Registry、FormalPolicy 与现有 Web 行为零语义变化；V0 只能增加回归断言，不能“顺手优化”。
- V1 精确支持 `60m + contract|actual_dominant`；`continuous`、1m/5m/15m/30m/1d/1w 必须 unavailable/disabled，不自动 fallback V0。
- V1 输入精确包含 `open/high/low/close/volume/open_interest/physical_contract`；OI 是必需输入，不支持 state-only 的 OI 缺失降级。
- `70` 只表示固定风险证据阈值 70/100；代码、UI、CLI、测试、文档不得称为“70% 主力流出”、概率、账户或会员席位事实。
- Python/Web 阈值判断使用未 round binary64；公开数值统一 `half_away_from_zero_binary64`、6 位，不用 Python `round()` 或 JS `toFixed()` 作为数学实现。
- `state_ready` 第一根精确为同 block 第 21 根（index 20）；`caution_ready == ready` 第一根精确为第 31 根（index 30）。
- conflict 精确行为：不输出方向事件、不消耗任一 latch、不执行 re-arm、所有 re-arm counters 暂停；下一根合法 candidate 继续使用 conflict 前 latch 状态。
- re-arm streak 条件中断直接清零到 0；warm-up/derived unavailable/conflict 只暂停，input/OI/identity/timestamp invalid 或换合约重置。
- offending timestamp Bar 自身 invalid，不能成为新 block seed；后续必须严格大于此前历史最大可解析 timestamp。
- caution marker 使用附着 V1 histogram 的 series marker；禁止恢复固定 `+92/-92` 数据点。
- Historical 数据只经 `MarketDataService`；不得直读 Parquet、RQData、Redis 或复制主力 resolver。
- 本 Plan 不授权真实 representative-matrix Shadow、正式 evidence 保存、main/release/tag、Runtime reload/promotion、Alert Rule/Scope、真实通知、DB/Canonical 写入、账户或订单。
- `auto_order=false` 始终成立。
- 任一 Task 的公式实现如需要改变 Spec 中参数、权重、threshold、readiness、conflict、rounding 或 re-arm 语义，输出 `FORMULA_DRIFT_REQUIRES_NEW_VERSION` 并停止；不得在 `futures-research-v1` 下漂移。
- 所有行为修改遵守 TDD：先 RED，确认失败原因命中目标，再最小 GREEN；每个 Task 结束运行定向测试、Ruff/Node check（适用时）、`git diff --check`，并自审 scope。

---

## Codex 调度矩阵

| Task | Lane | Model | 推理 | 会话 | Plan | 工作区 | 集成 Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Exact contracts / readiness / rounding | Lane 3 | Sol | 高 | 新会话 | Plan-then-execute；Spec 已批准 | 最新 develop 新 task worktree | 定向测试 + 独立 Task Review |
| 2 Python kernel / caution / latch | Lane 3 | Sol | 高 | 新会话 | Plan-then-execute | 最新 develop 新 task worktree | Python exact math + V0 regression + Review |
| 3 Web physical-contract identity | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | 最新 develop 新 task worktree | MarketSeries tests + Review |
| 4 Web mirror + Python/Web golden | Lane 3 contract parity | Sol | 高 | 新会话 | Plan-then-execute | 最新 develop 新 task worktree | exact golden parity + Review |
| 5 Three-tab pane / dynamic marker / hover | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | 最新 develop 新 task worktree | Web unit + Playwright + build + Review |
| 6 Historical Shadow service / CLI | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 最新 develop 新 task worktree | read-only service/CLI tests + Review |
| 7 Full regression / docs / final review | Lane 3 review | Sol | 高 | 新独立 Review 会话 | Review-only + bounded fixes | develop review worktree | Critical=0 / Important=0 |

默认执行方式使用 `superpowers:subagent-driven-development`：每个 Task fresh implementer + scoped reviewer；公式/contract Task 1/2/4 与最终 Review 使用 Sol，纯 Web plumbing Task 3/5 可使用 Terra。Terra 任一轮出现公式/identity 不确定、跨模块根因或两轮未解决，立即升级 Sol 新会话。

每个实现 Task 的 branch/worktree 链路：

```text
execution-time latest develop
→ task branch/worktree
→ RED → GREEN → task verification → self-review
→ independent task review
→ task branch → develop
→ read back develop ancestry
→ remove merged task worktree/branch
```

建议分支：

```text
research/mfm-futures-v1-contracts
research/mfm-futures-v1-kernel
feat/mfm-futures-v1-physical-contract
feat/mfm-futures-v1-web-mirror
feat/mfm-futures-v1-web-pane
research/mfm-futures-v1-shadow
docs/mfm-futures-v1-closeout
```

任何 Task 都不得触及 `main`、release worktree、tag 或 production Runtime worktree。

---

## File Structure

### Task 1–2：Python Kernel

- Create `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py` — V1 constants、domain types、rounding、input/block/readiness、exact math、state、caution、latch/re-arm。
- Create `services/quant-api/tests/test_main_force_mirror_futures.py` — V1 exact contract 与 kernel oracle tests。
- Modify `packages/quant-core/guiyi_quant/indicators/__init__.py` — Task 2 完成 kernel 后导出 V1 public symbols。
- Modify `packages/quant-core/guiyi_quant/indicators/registry.py` — Task 2 完成后登记 V1；V0 definition byte/semantic unchanged。
- Modify `packages/quant-core/guiyi_quant/indicators/policy.py` — Task 2 新增 observation-only FormalPolicy。
- Modify `services/quant-api/tests/test_indicator_registry_v1.py` — 从“全指标七周期”改成逐指标 exact set；V1 只 `60m`。
- Test `services/quant-api/tests/test_main_force_mirror.py` — V0 regression。

### Task 3：Web physical identity

- Modify `apps/quant-web/src/types/market.ts` — `BarData.physicalContract?` 与 internal diagnostic `physicalContractReason?`。
- Modify `apps/quant-web/src/composables/useMarketSeries.ts` — page segment mapping、contract identity、snapshot/bar physical identity。
- Modify `apps/quant-web/tests/marketSeries.test.ts` — exact mapping、prepend、conflict/missing、snapshot/bar tests。

`physicalContractReason` 只允许：

```ts
'MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING'
| 'MFM_FUTURES_V1_SEGMENT_CONFLICT'
```

它是 Web 边界诊断字段，不改变 Canonical DTO，也不写回 API/DB。

### Task 4：Web mirror + single golden fixture

- Create `apps/quant-web/src/utils/mainForceMirrorFutures.ts` — Python V1 的 browser mirror。
- Create `apps/quant-web/tests/mainForceMirrorFutures.test.ts`。
- Create `tests/fixtures/main_force_mirror_futures_v1_golden.json` — Python/Web 共用单一 deterministic fixture；禁止两份手工拷贝。
- Modify `services/quant-api/tests/test_main_force_mirror_futures.py` — 读取同一 fixture 并验证 expected output。

### Task 5：Web pane / marker / hover

- Modify `apps/quant-web/src/components/kline/KlineChart.vue`。
- Modify `apps/quant-web/src/components/kline/KlineHoverLegend.vue`。
- Modify `apps/quant-web/src/utils/klineViewModel.ts`。
- Modify `apps/quant-web/src/types/market.ts` — secondary hover DTO。
- Modify `apps/quant-web/src/pages/market/chart.vue` — 将 current `seriesKind` 传入 KlineChart，不创建新行情 request。
- Modify `apps/quant-web/src/styles/chartTheme.ts` 与 `apps/quant-web/src/styles/tokens.css` — V1 状态/marker theme token；数学 util 不硬编码颜色。
- Create `apps/quant-web/e2e/main-force-mirror-futures.spec.mjs`。
- Modify `apps/quant-web/e2e/main-force-mirror.spec.mjs` — V0 改名显示“原型V0”后的回归。
- Modify `apps/quant-web/e2e/market-runtime.spec.mjs` — no-refetch / identity regression only where existing harness already owns it。

### Task 6：Read-only Shadow

- Create `services/quant-api/app/market_data/main_force_mirror_futures_research_service.py`。
- Create `services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py`。
- Modify `services/quant-api/app/market_data/composition.py` — build read-only service。
- Modify `services/quant-api/app/guiyi_cli/research_parser.py`。
- Modify `services/quant-api/app/guiyi_cli/research_commands.py`。
- Modify `services/quant-api/app/guiyi_cli/main.py`。
- Modify `services/quant-api/tests/test_research_cli.py`。

### Task 7：Closeout

- Modify `docs/INDICATOR_KERNEL.md`。
- Modify `TESTING.md`。
- Modify `STATUS.md` **only after all Task 1–6 verification and final independent review pass**。

---

# Task 1: Python Exact Contracts, Readiness and Rounding

**Lane:** Lane 3 — indicator formula contract. Sol/high，新会话。

**Files:**
- Create: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- Create: `services/quant-api/tests/test_main_force_mirror_futures.py`

**Interfaces:**
- Produces exact constants `INDICATOR_CODE`, `INDICATOR_VERSION`, `DEFAULT_PARAMETERS`。
- Produces public type aliases `MainForceMirrorFuturesState` / `MainForceMirrorFuturesCaution`。
- Produces frozen `MainForceMirrorFuturesResult` dataclass shape required by Task 2/4/6。
- Produces `round_public(value: float, digits: int = 6) -> float` with `half_away_from_zero_binary64`。
- Produces stable reason constants and private block/readiness helpers；不登记 Registry，不暴露半完成 indicator consumer。

- [ ] **Step 1: 写 parameter/domain RED tests**

在 `test_main_force_mirror_futures.py` 固定：

```python
from guiyi_quant.indicators.main_force_mirror_futures import (
    DEFAULT_PARAMETERS,
    INDICATOR_CODE,
    INDICATOR_VERSION,
    round_public,
)


def test_identity_and_exact_parameters() -> None:
    assert INDICATOR_CODE == "main_force_mirror_futures_v1"
    assert INDICATOR_VERSION == "futures-research-v1"
    assert DEFAULT_PARAMETERS["liquidation_dominated_oi_threshold"] == 0.5
    assert "closing_dominated_oi_threshold" not in DEFAULT_PARAMETERS
    assert DEFAULT_PARAMETERS["round_digits"] == 6
    assert DEFAULT_PARAMETERS["rounding_policy"] == "half_away_from_zero_binary64"
```

并加入 exact key-set 断言，完整 key-set 必须与 Spec 5.2 一致，不能只抽查几项。

- [ ] **Step 2: 写 rounding RED tests**

```python
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.2345675, 1.234568),
        (-1.2345675, -1.234568),
        (0.0000005, 0.000001),
        (-0.0000005, -0.000001),
        (-0.0, 0.0),
    ],
)
def test_round_public_half_away_from_zero(value: float, expected: float) -> None:
    assert round_public(value) == expected
```

- [ ] **Step 3: 运行 RED**

```bash
PYTHONPATH=packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py
```

Expected: import/module failure，因为新 kernel 尚不存在。

- [ ] **Step 4: 实现 exact constants 与 rounding**

实现方式必须等价于：

```python
from math import floor


def round_public(value: float, digits: int = 6) -> float:
    if not np.isfinite(value):
        return value
    if value == 0.0:
        return 0.0
    scale = float(10**digits)
    result = np.copysign(floor(abs(value) * scale + 0.5) / scale, value)
    return 0.0 if result == 0.0 else float(result)
```

不得使用内建 `round()`。

- [ ] **Step 5: 写 readiness RED tests**

使用 40 根同一 contract、valid 60m synthetic bars，断言：

```python
assert result.state_ready[19] is False
assert result.state_ready[20] is True
assert result.caution_ready[29] is False
assert result.caution_ready[30] is True
assert np.array_equal(result.ready, result.caution_ready)
```

Task 1 可通过 private contract-evaluation helper 暴露这些 boundary facts；完整 state/math 在 Task 2 实现。

- [ ] **Step 6: 写 input/timestamp/OI contract RED tests**

覆盖：OI `None/NaN/inf/-1` → `OPEN_INTEREST_UNAVAILABLE` + invalid；OHLC/volume invalid → `INPUT_INVALID`；duplicate/regression timestamp → `TIMESTAMP_INVALID`；offending Bar 不能 seed 新 block；合约合法 A→B 当前 B Bar 可以成为新 block index 0。

- [ ] **Step 7: 实现 domain/result、input validator、block tracker 与 readiness helper**

`MainForceMirrorFuturesResult` 精确包含 Spec 第 11 节字段；Task 1 只实现结构、valid/block index/readiness/rounding 基础，不实现 state/caution 数学。

- [ ] **Step 8: GREEN + lint + diff check**

```bash
PYTHONPATH=packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_futures.py

git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_futures.py
git commit -m "feat(indicator): define futures mirror v1 contracts"
```

**Task 1 acceptance:** exact identity/parameters、readiness 21/31、OI/timestamp reset、half-away rounding 已被 tests 冻结；indicator 尚未进入 Registry/Web consumer。

---

# Task 2: Python Exact Math, Five States, Caution and Episode Latch

**Lane:** Lane 3 — formula/lifecycle semantics. Sol/high，新会话。

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- Modify: `services/quant-api/tests/test_main_force_mirror_futures.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`
- Test: `services/quant-api/tests/test_main_force_mirror.py`

**Interfaces:**
- Produces `compute_main_force_mirror_futures(...) -> MainForceMirrorFuturesResult`。
- Produces Python business authority used by Web golden and Shadow。
- Registers `main_force_mirror_futures_v1` only after complete GREEN。

- [ ] **Step 1: 写 exact indicator math RED tests**

Tests must independently assert：ATR14 Wilder SMA seed、volume SMA20、OI abs-delta EMA20 SMA seed、price impulse clip、CLV、direction weights、range20、long/short pressure、strength cap 100。

关键 OI seed assertion：第 21 根 Bar（index 20）使用 `abs(delta_oi_1..20)` 的 mean 作为 first baseline；不得以首个 delta 直接 seed。

- [ ] **Step 2: 写 five-state/deadband RED tests**

用 pure classifier helper 或 deterministic input sequence 锁定：

```text
LONG_BUILD
SHORT_BUILD
SHORT_COVER
LONG_LIQUIDATION
TURNOVER
```

并覆盖 exact thresholds `±0.15 / ±0.25`、`TURNOVER + direction==0 → signed_score=0`、TURNOVER cap 15、其他 state sign 与 strength cap 100。

- [ ] **Step 3: 写 caution score RED tests**

分别构造 4 个 long reason 和 4 个 short reason；断言权重精确 `30/30/25/15`，score 69 不 candidate、70 candidate。Pressure divergence 必须只读取当前 Bar 之前同 block 连续 10 个 `state_ready` points。

- [ ] **Step 4: 写 conflict/latch/re-arm RED tests**

至少冻结：

```python
assert conflict.caution is None
assert next_valid_candidate.caution == "long_chase_caution"  # conflict 未消耗 latch
```

以及：long/short 独立 latch、event Bar 不 re-arm、low-score/build streak 中断清零、unavailable pause、invalid/contract reset、re-arm 当前 Bar 末生效。

- [ ] **Step 5: 运行 RED**

```bash
PYTHONPATH=packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py
```

Expected: 新 math/state/caution assertions FAIL。

- [ ] **Step 6: 实现 exact math**

按 Spec 7–10 节逐项实现，内部 raw binary64 先判断 threshold，最后才 `round_public()` 写 public arrays。`state_ready=true && caution_ready=false` 输出 state/features，但 caution scores/caution unavailable；不得 partial score。

- [ ] **Step 7: 实现 reason precedence**

按 Spec 15 精确优先级：unsupported → identity → timestamp → OI → generic input → state warmup → derived invalid → caution warmup → conflict → ready。OI reason 是 input invalid 的专用细分，不再叠加 generic reason。

- [ ] **Step 8: 登记 Registry / FormalPolicy**

新增 definition：

```text
code=main_force_mirror_futures_v1
version=futures-research-v1
supported_intervals=("60m",)
lookback=31
warmup=30
status=observation_only
web=true
backtest/live/alert=false
policy=main_force_mirror_futures_observation_v1
```

FormalPolicy allowed only `Web_manual_observation`；blocked 包含 `formal_backtest/live/alert/notification/auto_order`。

`test_indicator_registry_v1.py` 改为逐 indicator exact supported set；不得放宽其他 indicator。

- [ ] **Step 9: 加 V0 invariance regression**

现有 `test_main_force_mirror.py` 全部必须保持 GREEN，并增加 definition/policy snapshot assertion，证明 V1 注册没有改变 V0 default parameters、version、capability 与 policy。

- [ ] **Step 10: Verify Task 2**

```bash
PYTHONPATH=packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_indicator_registry_v1.py

git diff --check
```

- [ ] **Step 11: Commit**

```bash
git add packages/quant-core/guiyi_quant/indicators services/quant-api/tests/test_main_force_mirror_futures.py services/quant-api/tests/test_main_force_mirror.py services/quant-api/tests/test_indicator_registry_v1.py
git commit -m "feat(indicator): implement futures mirror v1 kernel"
```

**Task 2 acceptance:** Python authority 完整；V1 causal/observation-only；V0 零语义变化。

---

# Task 3: Web Physical Contract Mapping and Segment-Local Identity

**Lane:** Lane 2. Terra/mid，新会话；identity ambiguity 升级 Sol。

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/composables/useMarketSeries.ts`
- Modify: `apps/quant-web/tests/marketSeries.test.ts`

**Interfaces:**
- Produces `BarData.physicalContract?: string`。
- Produces `BarData.physicalContractReason?: 'MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING' | 'MFM_FUTURES_V1_SEGMENT_CONFLICT'`。
- Task 4 mirror consumes only BarData；Task 5 uses seriesKind/frequency to enable Tab。

- [ ] **Step 1: 写 page mapping RED tests**

覆盖：

```text
contract page → every Bar physicalContract=request.contract
actual_dominant → trading_day exact one segment
zero segment → no contract + MISSING reason
multiple segments → no contract + CONFLICT reason
prepend page → page-own segments used, no prior-page guessing
continuous → no physicalContract
```

- [ ] **Step 2: 写 WebSocket identity RED tests**

`snapshot` 精确 `contract` 绑定 incoming completed bars；subsequent `bar` 只能复用已建立 overlay identity。无 overlay identity 的 `bar` 不使用 `marketState.live_contract` 猜测。

- [ ] **Step 3: 运行 RED**

```bash
pnpm --dir apps/quant-web test -- --test-name-pattern="physical contract|resolved segment|overlay identity"
```

若 package runner 不透传 pattern，则运行：

```bash
node --test apps/quant-web/tests/marketSeries.test.ts
```

- [ ] **Step 4: 实现 deterministic page resolver**

新增 pure helper（可位于 `useMarketSeries.ts`）：

```ts
function resolvePagePhysicalContract(
  bar: CanonicalBarDto,
  page: MarketBarsPageResponse,
): { physicalContract?: string; physicalContractReason?: BarData['physicalContractReason'] }
```

`actual_dominant` 用 inclusive trading-day range；exact 1 match 才返回 contract。

- [ ] **Step 5: 实现 live/post-close resolver**

`applyLiveBars` 显式接收 physical contract identity，不从 global dominant 推导。Contract request 如 payload contract 与请求不一致，该 Bar 不获得可用 V1 physical identity。

- [ ] **Step 6: GREEN + full MarketSeries unit**

```bash
node --test apps/quant-web/tests/marketSeries.test.ts
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add apps/quant-web/src/types/market.ts apps/quant-web/src/composables/useMarketSeries.ts apps/quant-web/tests/marketSeries.test.ts
git commit -m "feat(web): bind futures bars to physical contracts"
```

**Task 3 acceptance:** Web 每根可用于 V1 的 Bar 具有可验证 physical identity；分页/Live 都不猜合约。

---

# Task 4: Browser Mirror and Shared Python/Web Golden Parity

**Lane:** Lane 3 contract parity. Sol/high，新会话。

**Files:**
- Create: `apps/quant-web/src/utils/mainForceMirrorFutures.ts`
- Create: `apps/quant-web/tests/mainForceMirrorFutures.test.ts`
- Create: `tests/fixtures/main_force_mirror_futures_v1_golden.json`
- Modify: `services/quant-api/tests/test_main_force_mirror_futures.py`

**Interfaces:**
- Produces `calculateMainForceMirrorFutures(bars: BarData[]): MainForceMirrorFuturesWebResult`。
- Web point fields mirror Python public fields using camelCase only at TS boundary；reason string values remain identical。
- Shared fixture is the parity oracle consumed by both runtimes。

- [ ] **Step 1: 创建 shared input+expected fixture**

Fixture schema 固定：

```json
{
  "schema_version": 1,
  "indicator_code": "main_force_mirror_futures_v1",
  "input": [{"time":"...","physical_contract":"JM2701","open":1,"high":2,"low":1,"close":2,"volume":10,"open_interest":100}],
  "expected": [{"valid":true,"state_ready":false,"caution_ready":false,"ready":false,"reason":"MFM_FUTURES_V1_WARMUP"}]
}
```

实际 fixture 至少包含 Spec 17.7 的：2 contracts、5 states、long/short caution、conflict、re-arm、missing OI、timestamp regression、positive/negative half-tie、readiness 20/30 boundaries。Expected 数值来自已通过 Task 2 exact unit tests 的 Python authority，并 review 后冻结；测试不得运行时动态重写 fixture。

- [ ] **Step 2: Python fixture RED/GREEN**

Python test 读取 fixture，逐点核对所有 public fields 与 expected；任何 expected 缺字段均 FAIL，避免“只比最后几根”。

- [ ] **Step 3: 写 TS RED tests**

锁定 exact `DEFAULTS`、half-away rounding、state/readiness/reason/caution/re-arm semantics；先确认新 util import failure。

- [ ] **Step 4: 实现 TypeScript mirror**

数学运算顺序与 Python 保持一致；不调用 `toFixed()` 决定结果。OI 缺失、timestamp failure、contract switch reset 等完全照 Spec。

- [ ] **Step 5: Web fixture parity**

Node test 读取仓库同一个 `tests/fixtures/main_force_mirror_futures_v1_golden.json`，对每个 point 做 deep equality（数值已 public-round）。禁止在 `apps/quant-web/tests` 再复制一份 golden。

- [ ] **Step 6: Prefix invariance**

Python 与 Web 都对 fixture 每个 prefix 重算，历史 ready/state/caution 输出不得因追加未来 Bar 改变。

- [ ] **Step 7: Verify Task 4**

```bash
PYTHONPATH=packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py

node --test apps/quant-web/tests/mainForceMirrorFutures.test.ts
git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add apps/quant-web/src/utils/mainForceMirrorFutures.ts apps/quant-web/tests/mainForceMirrorFutures.test.ts tests/fixtures/main_force_mirror_futures_v1_golden.json services/quant-api/tests/test_main_force_mirror_futures.py
git commit -m "test(indicator): lock futures mirror python web parity"
```

**Task 4 acceptance:** Python/Web 单一 fixture 逐点一致，包括 user-review 的 9 个边界。

---

# Task 5: Three-Tab Pane, Dynamic Caution Markers and Hover

**Lane:** Lane 2. Terra/mid，新会话。

**Files:**
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/styles/chartTheme.ts`
- Modify: `apps/quant-web/src/styles/tokens.css`
- Create: `apps/quant-web/e2e/main-force-mirror-futures.spec.mjs`
- Modify: `apps/quant-web/e2e/main-force-mirror.spec.mjs`
- Test: `apps/quant-web/tests/kline-view-model.test.ts`

**Interfaces:**
- `SecondaryPanelId = 'macd' | 'main_force_mirror_futures' | 'main_force_mirror_v0'`。
- UI label exact order: `MACD | 主力照妖镜 | 原型V0`。
- `KlineChart` receives current `seriesKind` prop in addition to `period`；不发请求。

- [ ] **Step 1: 写 Tab capability RED tests/E2E**

证明：默认 MACD；60m actual_dominant/contract V1 enabled；15m/continuous V1 disabled；原型V0 保持可打开；点击 Tab 不增加 `/bars/page` request count。

- [ ] **Step 2: 写 render isolation RED tests**

切换三面板时，每次只保留当前 pane series/markers；切 V1 后 MACD/V0 data 清空；切回后 V1 marker/data 清空；pane count 始终 3。

- [ ] **Step 3: 实现三 Tab 与 capability**

不要把 current V0 `main_force_mirror` id 复用成 V1；明确重命名内部 id，避免 local state 误读。

- [ ] **Step 4: 实现 V1 histogram 与 theme tokens**

五状态颜色从 `resolveChartTheme()` 获取；`mainForceMirrorFutures.ts` 不含颜色。V1 right scale 保持 `[-105,+105]` 视觉约束，不用 caution 数值撑 scale。

- [ ] **Step 5: 实现 dynamic series markers**

V1 marker 挂在 V1 histogram series：

```text
long  → aboveBar / arrowDown / 追多小心 {score}
short → belowBar / arrowUp   / 追空小心 {score}
```

不创建 `±92` histogram。Conflict 不画方向 marker。

- [ ] **Step 6: 扩展 hover context**

`HoverKlineContext` 添加 nullable futures-mirror observation，显示：physical contract、state、state/caution readiness、strength、price impulse、volume ratio20、delta OI、OI impulse、range position、long/short scores、caution reasons、availability reason。所有 unavailable 使用既有 `formatKlineHoverValue()` → `—`。

- [ ] **Step 7: 图例与文案**

V1 图例明确：

```text
多头增仓 / 空头增仓 / 空头回补 / 多头减仓 / 换手
70 = 风险证据评分阈值，不是资金流比例或概率
```

V0 图例继续明确原型 HHV5/BARSLAST10，不改 V0 数学。

- [ ] **Step 8: Web unit + Playwright RED→GREEN**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror-futures.spec.mjs \
  e2e/main-force-mirror.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

E2E 额外证明 strength 100 时 marker 不创建固定 price point、换月后 V1 warm-up、OI unavailable 文案与 caution warm-up 文案不同、无 horizontal overflow。

- [ ] **Step 9: Commit**

```bash
git add apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e/main-force-mirror-futures.spec.mjs apps/quant-web/e2e/main-force-mirror.spec.mjs
git commit -m "feat(web): add futures main-force mirror observation"
```

**Task 5 acceptance:** 用户可在同一副图 pane 中选择 MACD/V1/V0；V1 双向 marker 可解释且不污染 scale；切换不 refetch。

---

# Task 6: Read-Only Historical Shadow Service and CLI

**Lane:** Lane 1 research，因涉及 OI/segment/outcome 语义使用 Sol/high，新会话。

**Files:**
- Create: `services/quant-api/app/market_data/main_force_mirror_futures_research_service.py`
- Create: `services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**

新增 immutable request：

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesResearchRequest:
    symbol: str
    series_kind: SeriesKind
    contract: str | None
    frequency: BarFrequency
    since: date
    through: date
```

构造时精确拒绝：frequency 非 60m、continuous、contract 缺 contract、since>through。

Service：

```python
class MainForceMirrorFuturesResearchService:
    def run(
        self,
        request: MainForceMirrorFuturesResearchRequest,
    ) -> MainForceMirrorFuturesResearchResult: ...
```

- [ ] **Step 1: 写 request/read path RED tests**

Fake `MarketDataService` 必须记录 query；actual_dominant 走既有 dominant query/result segments，contract 走既有 physical SeriesQuery；测试显式断言 service 没有 file/parquet/provider/Redis dependency。

- [ ] **Step 2: 写 segment/event/outcome RED tests**

构造 2 segments；只有 `caution != null` 生成 event；conflict 只 `conflict_count += 1`；1/3/5/10 outcome 只在同 physical contract segment 内计算，跨 segment 为 unavailable。

- [ ] **Step 3: 写 summary RED tests**

精确字段：`bars_valid_count`、`bars_state_ready_count`、`bars_caution_ready_count`、long/short event count、conflict count、events per 1000 caution-ready bars、state/reason/score distributions、forward reversal/MFE/MAE、missing OI、segment reset、timestamp invalid。

- [ ] **Step 4: 实现 service**

只消费 Task 2 Python kernel；不复制公式。所有 `Decimal`/float JSON 序列化规则与现有 research CLI 风格一致，result 不包含 promotion/recommendation 字段。

- [ ] **Step 5: CLI parser RED**

新增：

```bash
guiyi research main-force-mirror-futures \
  --symbol jm \
  --series-kind actual_dominant \
  --frequency 60m \
  --since 2025-01-01 \
  --through 2026-08-19
```

`contract` 模式要求 `--contract`。Parser 允许的 frequency 只有 `60m`。

- [ ] **Step 6: CLI composition GREEN**

`main.py` 增加独立 `main_force_mirror_futures_research_service_factory`，只在该 research_command 分支构造。`_execution_is_readonly()` 已对 research 返回 true，保持不变。

stdout schema 至少：

```json
{
  "schema_version": 1,
  "command": "research.main-force-mirror-futures",
  "status": "ok",
  "readonly": true,
  "indicator_code": "main_force_mirror_futures_v1",
  "indicator_version": "futures-research-v1"
}
```

- [ ] **Step 7: 代表矩阵只做合同测试**

在 test 中固定允许 research examples `jm/ag/cu/m/sc`，但本 Task **不得**调用真实 Canonical 执行这五个品种，也不得保存正式 evidence。

- [ ] **Step 8: Verify Task 6**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/main_force_mirror_futures_research_service.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add services/quant-api/app/market_data/main_force_mirror_futures_research_service.py services/quant-api/app/market_data/composition.py services/quant-api/app/guiyi_cli services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py services/quant-api/tests/test_research_cli.py
git commit -m "feat(research): add futures mirror shadow CLI"
```

**Task 6 acceptance:** repo 具备 deterministic read-only Shadow 代码入口；没有真实 Shadow execution/evidence，也无 write side effect。

---

# Task 7: Full Regression, Canonical Documentation and Independent Review

**Lane:** Lane 3 review. Sol/high，新独立 Review 会话。

**Files:**
- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `TESTING.md`
- Modify: `STATUS.md` only after all gates pass
- Review all Task 1–6 changed files

**Interfaces:** Final branch must expose V1 on `develop` only and preserve all production/runtime claims exactly unless separately released later。

- [ ] **Step 1: 更新 Indicator Kernel canonical**

写明 V0 与 V1 双版本：V0 股票式原型保持 frozen；V1 60m/OI/physical-contract、five-state、double caution、70 evidence、rounding、readiness、consumer blocks。不得写“主力资金实测”。

- [ ] **Step 2: 更新 TESTING.md focused commands**

新增 Main Force Mirror Futures V1 无副作用验证节，列出 Task 2/4/5/6 的 exact pytest/node/playwright/build 命令；明确真实 representative Shadow 与 Runtime 不属于测试。

- [ ] **Step 3: 运行 focused V1 suite**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror-futures.spec.mjs \
  e2e/main-force-mirror.spec.mjs \
  e2e/market-runtime.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 4: 运行 repository-native regression**

按执行时最新 `TESTING.md` 运行完整 backend tests、Ruff、Mypy、Web unit、Market browser suite、Web production build、engineering tests（若受影响）。不得删测试来换绿。

最低命令：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

- [ ] **Step 5: 安全与 diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Secret scan 必须 `finding_count=0`；输出不可包含 secret content。

- [ ] **Step 6: 独立 whole-branch Review**

Review 必须逐项检查：Spec 9 项 user findings、V0 invariance、未来函数/prefix invariance、physical segment reset、OI missing semantics、timestamp max rule、Python/Web rounding、conflict latch、re-arm off-by-one、dynamic marker、read-only Shadow、无 Alert/DB/Runtime/order path。

Gate：

```text
Critical = 0
Important = 0
```

Minor 可修则修；任何 load-bearing Minor 未解决不得伪装 clean。

- [ ] **Step 7: Review findings RED→GREEN 修复并 re-review**

任何代码 finding 必须先补 regression test；修复后重跑受影响 full domain tests。若 finding 要改变 approved formula，停止并返回 `FORMULA_DRIFT_REQUIRES_NEW_VERSION`。

- [ ] **Step 8: STATUS develop-only closeout**

只有前述全部 GREEN + Review clean 后，`STATUS.md` 可新增：

```text
main_force_mirror_futures_v1
DEVELOP CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE
```

并明确：

```text
未 release
未 Runtime promotion
未真实 representative Shadow
未保存正式 evidence
未 Alert/notification
observation_only
```

不得修改当前 production release/runtime identity，除非另有真实 Gate 已执行。

- [ ] **Step 9: Final commit**

```bash
git add docs/INDICATOR_KERNEL.md TESTING.md STATUS.md
git commit -m "docs: close futures main-force mirror v1 implementation"
```

- [ ] **Step 10: Integration readback and cleanup**

确认实现 commits 已进入 `develop` ancestry；仅在 merged/readback 成功且 task worktree clean 后移除临时 worktree/branch。不得发布 main/tag，不得 reload Runtime。

**Task 7 acceptance:** 只能宣布 `main_force_mirror_futures_v1 Web observation implementation verified on develop`；不能宣布策略有效、可盈利、Alert-ready、Runtime-ready 或可交易。

---

## Plan Self-Review Checklist

执行前 controller 必须再次确认：

- [ ] Spec 21 节 9 项用户 Review 决议全部有 Task/test 对应：conflict→Task2/4；readiness→Task1/2/4；OI→Task1/2/3；timestamp→Task1/2/4；re-arm reset→Task2；TURNOVER zero→Task2；参数 rename→Task1；dynamic marker→Task5；rounding→Task1/4。
- [ ] V0 invariance 在 Task2、Task5、Task7 都有回归；没有任何 Task 要重写 V0 formula/golden。
- [ ] Python authoritative kernel 在 Task2 完成后才注册 consumer，Task1 不把半实现 indicator 暴露出去。
- [ ] `physicalContractReason` 是 Web internal diagnostic，不改 API DTO/Canonical。
- [ ] 单一 golden fixture 路径只存在 `tests/fixtures/main_force_mirror_futures_v1_golden.json`。
- [ ] Task5 不新增 pane，不新增 bar request；只复用现有 pane 2。
- [ ] Task6 只实现 Shadow 代码；真实 jm/ag/cu/m/sc 运行不是本 Plan 自动执行项。
- [ ] 所有 Task 都有 RED、GREEN、verification、commit 和 reviewer gate。
- [ ] 没有 `TBD`、`TODO`、`implement later` 或“自行决定参数”的执行占位。

## Execution Handoff

推荐采用 **Subagent-Driven Development**：fresh subagent per Task，Task 1/2/4/6 用 Sol，Task 3/5 用 Terra，Task 7 用独立 Sol Review；按 Task 顺序连续执行，不跨 Task 共享未审查代码。

Inline 执行时必须使用 `superpowers:executing-plans`，仍保持相同 Task boundaries、TDD 与 Review Gate。
