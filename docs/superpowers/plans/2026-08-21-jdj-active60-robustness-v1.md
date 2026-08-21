# Phase 7 — JDJ Active60 Robustness V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改三个冻结 JDJ Candidate 公式、不消费 prospective OOS、不过度扩展架构的前提下，以一次 `symbol + retrospective window` shared-loader 调用复用现有 JDJ causal evaluation，形成 `3 × active60 = 180` 个轻量跨品种事实、年度诊断和 symbol-balanced 板块汇总。

**Architecture:** 复用 `MarketDataService → ActualDominantResearchSegmentLoader → existing JDJ context/reducers → price-only outcomes`。对 `JdjResearchService` 做最小加法式 batch/detail seam，使单 symbol 的 1m/5m 与 context 只计算一次；新增两个 Phase 7 专用业务文件承载 exact protocol/report contract 与只读 orchestration，继续复用现有 `candidate-robustness` CLI，不建立通用 robustness platform、coverage 子系统、rolling engine、score/rank 或持久化状态。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、existing `JdjResearchService`、`ActualDominantResearchSegmentLoader`、`PriceDirectionalOutcome`、`ProductTaxonomy`、argparse CLI、pytest、Ruff、Mypy、Git-tracked exact JSON research contracts。

**Spec:** `docs/superpowers/specs/2026-08-21-jdj-active60-robustness-v1-design.md`

**Task Contract:** `docs/tasks/TASK-JDJ-ACTIVE60-ROBUSTNESS-V1-20260821.md`

## Global Constraints

- 每个 Task 开始前读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、Spec、Plan、Task Contract 与最新 `develop`；冲突时 `BLOCKED_CANONICAL_DRIFT`。
- 本阶段只消费三个 exact Candidate：`jdj_trend_follow_1m_candidate_v1`、`jdj_trend_reentry_6_1m_candidate_v1`、`jdj_key_level_breakout_1m_candidate_v1`。
- 不修改 `jdj_1m_policy_v1`、三个 Candidate manifest、`jdj_candidate_validation_v1`、EMA20、N Structure V1 或任何 reducer 公式。
- Historical 唯一入口保持 `MarketDataService → ActualDominantResearchSegmentLoader`；禁止 direct Parquet/RQData/Redis Live/glob/自判主力。
- common retrospective 精确为 `2023-01-01..2026-08-20`；`2026-08-21` embargo 与 `2026-08-24+` prospective OOS 不得进入任何 Phase 7 source request、report metric 或 evidence。
- active universe 与 sector taxonomy 必须由 Phase 7 exact protocol 冻结，并与当前 `active_products.txt` / `product_sectors.csv` 精确 readback；漂移时全局 fail-closed。
- 每个 symbol 的 full retrospective 只允许一次 `ActualDominantResearchSegmentLoader.load(... frequencies=(M1,M5) ...)`；loader 内部既有 probe/full MDS 查询语义保持不变。
- 年度统计只从该次 retrospective 已产生 event/outcome 分组，不额外访问行情。
- 只做 `available|unavailable`；不新增 FULL/PARTIAL coverage domain。合法晚上市品种仍 available，并显式记录 `observed_since/observed_through`。
- 单品种 outcome 只保留 ALL 汇总；只另外保存 `long_event_count/short_event_count`，不建立 LONG/SHORT outcome 全矩阵。
- 每 horizon 只保存 `sample_count / historical_positive_outcome_rate / median_directional_return_bps / median_mfe_bps / median_mae_bps`。
- 板块按 symbol-balanced 聚合；禁止 event pooling、active60 pooled performance、score、rank、winner、KEEP/DROP/PROMOTE。
- 不新增 worker/queue/cache/async/multiprocessing/DB 表/Web/API/Alert/PushPlus/Execution Review/order path。
- V1 串行执行；性能问题必须先由真实 evidence 证明，再单独立项有限并发。
- `auto_order=false` 始终成立。
- Task→`develop` 只授权普通源码/测试/文档集成；不授权 `main`、tag、release、Runtime、DB/Canonical/Redis、真实通知或任何外部 mutation。

---

## Planned File Map

### New files

```text
data/research_protocols/jdj_active60_robustness_v1.json
services/quant-api/app/market_data/jdj_robustness.py
services/quant-api/app/market_data/jdj_robustness_service.py
services/quant-api/tests/test_jdj_robustness.py
services/quant-api/tests/data_foundation/test_jdj_robustness_service.py
```

### Existing files modified narrowly

```text
services/quant-api/app/market_data/jdj_research.py
services/quant-api/app/market_data/jdj_research_service.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/tests/test_research_cli.py
TESTING.md
PROJECT_SOURCE.md
docs/ARCHITECTURE.md
STATUS.md                  # only after real read-only evidence exists
```

### Evidence created only in Task 5

```text
reports/research/candidate_robustness/jdj_active60_robustness_v1/active60-retrospective-freeze-2026-08-21.json
```

---

# Task 1 — Freeze Exact Protocol and Lightweight Report Contracts

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建新 task worktree，branch `research/jdj-active60-robustness-v1-contracts`
- 人工 Gate：独立 Review

Worktree：从 `develop` 创建；完成后仅允许 task branch → `develop`；需要 PR 或等价独立 Review 记录；Review C0/I0 且测试通过后可自动集成 `develop` 并清理临时 worktree/branch；不得触及 `main`、tag、Runtime。

**Files:**
- Create: `data/research_protocols/jdj_active60_robustness_v1.json`
- Create: `services/quant-api/app/market_data/jdj_robustness.py`
- Test: `services/quant-api/tests/test_jdj_robustness.py`

**Interfaces:**
- Produces: `JdjActive60RobustnessProtocolError`, `JdjActive60RobustnessProtocol`, `JdjActive60RobustnessRequest`, `JdjRobustnessStatus`, `JdjRobustnessHorizonSummary`, `JdjRobustnessYearSummary`, `JdjRobustnessSymbolResult`, `JdjRobustnessSectorHorizonSummary`, `JdjRobustnessSectorSummary`, `JdjActive60RobustnessReport`, `load_jdj_active60_robustness_protocol(path: Path | None = None) -> JdjActive60RobustnessProtocol`.
- Consumes: existing `load_jdj_candidate_validation_protocol()`, `load_jdj_candidate_manifest()`, active universe and product taxonomy loaders only for drift validation, not as alternate protocol values.

- [ ] **Step 1: Write RED tests for exact protocol identity**

```python
def test_phase7_protocol_is_exact_and_oos_is_not_consumed() -> None:
    protocol = load_jdj_active60_robustness_protocol()
    assert protocol.protocol_id == "jdj_active60_robustness_v1"
    assert protocol.research_only is True
    assert protocol.readonly is True
    assert protocol.common_since == date(2023, 1, 1)
    assert protocol.common_through == date(2026, 8, 20)
    assert protocol.embargo_trading_days == (date(2026, 8, 21),)
    assert protocol.prospective_first_trading_day == date(2026, 8, 24)
    assert protocol.prospective_consumed is False
    assert protocol.horizons_bars == (3, 5, 8, 20)
    assert protocol.candidate_ids == (
        "jdj_trend_follow_1m_candidate_v1",
        "jdj_trend_reentry_6_1m_candidate_v1",
        "jdj_key_level_breakout_1m_candidate_v1",
    )
    assert protocol.parameter_perturbation is False
    assert protocol.relationship_analysis is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False
```

Parameterize missing/extra/wrong-type/wrong-value mutations for every top-level field plus frozen product/sector mapping; every mutation raises `JDJ_ACTIVE60_ROBUSTNESS_PROTOCOL_INVALID`.

- [ ] **Step 2: Run the exact protocol tests and confirm RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_robustness.py
```

Expected: import/file failure because Phase 7 protocol/contracts do not exist.

- [ ] **Step 3: Create the exact protocol JSON**

Use exact ordered `cross_symbol_products` equal to the current active60 snapshot and exact ordered `sector_groups` entries of `{product, sector}` derived from the current frozen taxonomy; include only the fields required by the Spec. Do not add thresholds, scores, weighting parameters, concurrency settings or rolling configuration.

- [ ] **Step 4: Implement strict loader and protocol drift checks**

```python
class JdjActive60RobustnessProtocolError(ValueError):
    code = "JDJ_ACTIVE60_ROBUSTNESS_PROTOCOL_INVALID"

@dataclass(frozen=True, slots=True)
class JdjActive60RobustnessRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != "jdj_active60_robustness_v1":
            raise JdjActive60RobustnessProtocolError()
```

`load_jdj_active60_robustness_protocol()` must use the existing exact JSON loader pattern, then verify current active products and taxonomy equal the frozen protocol snapshot. It must also verify the existing JDJ validation protocol still has retrospective `2023-01-01..2026-08-20`, embargo `2026-08-21`, prospective first `2026-08-24`, horizons `(3,5,8,20)` and the same three candidate ids.

- [ ] **Step 5: Write report invariant tests**

Cover exactly: 180 rows required; unavailable rows have nullable observed/metric fields and a typed reason; available zero-event rows remain available; sample_count=0 forces rate/medians null; sector sign counts sum to `symbols_with_samples`; report rejects forbidden candidate ids and duplicate cells; report quality flags allow only `SOURCE_UNAVAILABLE_PRESENT`, `SYMBOL_WITHOUT_EVENT`, `HORIZON_WITHOUT_SAMPLE`, `SHORT_HISTORY_PRESENT`.

- [ ] **Step 6: Implement immutable report dataclasses minimally**

`JdjRobustnessSymbolResult` contains exactly the Spec fields plus a yearly mapping keyed by `2023|2024|2025|2026`; do not add generic metadata bags. `JdjActive60RobustnessReport` validates exact candidate-major then product-order rows, exact sector order from the protocol, `research_only=True`, `readonly=True`, and no prospective metric field.

- [ ] **Step 7: Run GREEN, Ruff and Mypy for the new contract module**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/market_data/jdj_robustness.py services/quant-api/tests/test_jdj_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app/market_data/jdj_robustness.py
```

Expected: PASS.

- [ ] **Step 8: Independent review and integrate**

Review must confirm no generic robustness framework and no modification to `multi_candidate_robustness_v1`. After C0/I0 and tests pass, integrate to `develop`, read back ancestry, then clean the task worktree/merged branch.

---

# Task 2 — Add the Shared JDJ Batch/Detail Seam with Exact Parity

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建新 task worktree，branch `research/jdj-batch-detail-seam`
- 人工 Gate：独立 Review

Worktree：从 latest `develop`；完成后只集成 `develop`；必须独立 Review；C0/I0 + parity/tests 后可自动集成并清理；不得触及 `main`/tag/Runtime。

**Files:**
- Modify: `services/quant-api/app/market_data/jdj_research.py`
- Modify: `services/quant-api/app/market_data/jdj_research_service.py`
- Test: existing JDJ service tests plus focused new tests in `services/quant-api/tests/data_foundation/test_jdj_research_service.py`

**Interfaces:**
- Produces in `jdj_research.py`: `JdjEventOutcomeRecord`, `JdjDetailedCandidateResult`, `JdjBatchResearchResult`.
- Produces in `JdjResearchService`: `run_batch(*, symbol: str, since: date, through: date) -> JdjBatchResearchResult`.
- Existing `run(request: JdjResearchRequest) -> JdjResearchResult` remains byte-for-behavior compatible.

- [ ] **Step 1: Write RED single-load and three-candidate batch tests**

```python
def test_run_batch_loads_symbol_once_and_returns_three_candidates() -> None:
    loader = RecordingLoader(...)
    service = make_jdj_service(loader)
    result = service.run_batch(
        symbol="jm",
        since=date(2023, 1, 1),
        through=date(2026, 8, 20),
    )
    assert loader.calls == [("jm", (BarFrequency.M1, BarFrequency.M5), date(2023,1,1), date(2026,8,20))]
    assert tuple(item.result.candidate_id for item in result.candidates) == EXPECTED_JDJ_IDS
```

Also assert `observed_since/observed_through` are min/max trading days from validated 1m bars intersecting the request window, not loader warm-up bars.

- [ ] **Step 2: Write RED parity tests before refactor**

For each exact candidate, run the existing `run()` path and the future `run_batch()` projection on the same deterministic fixture and assert exact equality for event ids/order, long/short counts, evaluable count, horizon sample counts and all three medians.

- [ ] **Step 3: Introduce minimal detail records**

```python
@dataclass(frozen=True, slots=True)
class JdjEventOutcomeRecord:
    event_id: str
    trading_day: date
    outcomes: Mapping[int, PriceDirectionalOutcome | None]

@dataclass(frozen=True, slots=True)
class JdjDetailedCandidateResult:
    result: JdjResearchResult
    event_outcomes: tuple[JdjEventOutcomeRecord, ...]

@dataclass(frozen=True, slots=True)
class JdjBatchResearchResult:
    symbol: str
    observed_since: date
    observed_through: date
    candidates: tuple[JdjDetailedCandidateResult, ...]
```

The event outcome mapping is exact horizons `(3,5,8,20)` and uses the existing `build_price_outcomes_at()` result; do not copy directional-return arithmetic.

- [ ] **Step 4: Refactor one private loaded-series evaluator**

Extract a private helper in `jdj_research_service.py` that receives one validated loaded `ActualDominantResearchSeries` and a tuple of candidate ids, builds each segment's JDJ context once, runs only the requested reducers, validates events through the existing alignment function, and returns detailed results. `run()` calls the helper with one candidate; `run_batch()` loads once and calls it with the three exact ids.

- [ ] **Step 5: Make the old public run() parity GREEN**

Run the existing JDJ research/service suites plus the new parity tests. Any changed event id/order/count/median is a blocker; do not update golden expectations to accept drift.

- [ ] **Step 6: Verify no OOS widening in the seam**

Add a test that the Phase 7 caller can request only through `2026-08-20`; the generic `JdjResearchService.run_batch()` itself remains a historical research primitive and does not own Phase 7 dates, while Task 3's robustness service enforces the exact protocol window. Confirm batch does not introduce Live or prospective logic.

- [ ] **Step 7: Run targeted tests and static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/market_data/jdj_research.py services/quant-api/app/market_data/jdj_research_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app/market_data/jdj_research.py services/quant-api/app/market_data/jdj_research_service.py
```

- [ ] **Step 8: Independent parity review and integrate**

Reviewer explicitly checks strict-before context, same-contract/rank1 segmentation, no formula copy, one loader call, old `run()` parity. C0/I0 then integrate `develop` and clean worktree/branch.

---

# Task 3 — Build the Lightweight Active60/Year/Sector Robustness Service

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建新 task worktree，branch `research/jdj-active60-robustness-service`
- 人工 Gate：独立 Review

Worktree：latest `develop` → task worktree → `develop`; C0/I0 + tests 后允许自动集成并清理；无 `main`/tag/Runtime。

**Files:**
- Create: `services/quant-api/app/market_data/jdj_robustness_service.py`
- Test: `services/quant-api/tests/data_foundation/test_jdj_robustness_service.py`
- Modify only if needed for shared pure helpers: `services/quant-api/app/market_data/jdj_robustness.py`

**Interfaces:**
- Consumes: `JdjResearchService.run_batch`, `JdjActive60RobustnessProtocol`, `JdjActive60RobustnessRequest`, frozen taxonomy.
- Produces: `JdjActive60RobustnessService.run(request: JdjActive60RobustnessRequest) -> JdjActive60RobustnessReport`.

- [ ] **Step 1: Write RED test for exact 60 single-load calls and 180 rows**

Use a fake batch runner returning deterministic three-candidate detailed results per symbol. Assert the service calls exactly one batch run per frozen product with exact `2023-01-01..2026-08-20`, and report row count is 180 in candidate-major/product order.

- [ ] **Step 2: Write RED metric tests**

For a hand-built event outcome sample, assert:

```python
assert summary.sample_count == 4
assert summary.historical_positive_outcome_rate == Decimal("0.5")
assert summary.median_directional_return_bps == Decimal("1.5")
assert summary.median_mfe_bps == expected_mfe_median
assert summary.median_mae_bps == expected_mae_median
```

When sample_count is zero, all four metric fields except count are `None`. Event rate is `event_count * 1000 / evaluable_bar_count`, or `None` if evaluable count is zero.

- [ ] **Step 3: Implement one small pure horizon summarizer**

It accepts `Sequence[PriceDirectionalOutcome]` and returns `JdjRobustnessHorizonSummary`. Use Python `statistics.median` on Decimal values and exact `Decimal(positive_count) / Decimal(sample_count)`; do not add quartiles or thresholds.

- [ ] **Step 4: Implement single-symbol projection**

For each detailed candidate: derive event_count from the existing result, long/short from result, observed range from batch result, ALL horizon metrics from `event_outcomes`, and sector from frozen protocol taxonomy. If batch source raises the existing typed JDJ source/identity error, emit three unavailable cells for that symbol with one stable Phase 7 reason code and continue.

- [ ] **Step 5: Implement yearly diagnostics without reload**

Group existing `JdjEventOutcomeRecord` by `trading_day.year` for exact years `2023, 2024, 2025, 2026`; for each year compute event_count and per-horizon `sample_count / historical_positive_outcome_rate / median_directional_return_bps`. Do not call the batch runner from yearly code.

- [ ] **Step 6: Write and implement symbol-balanced sector tests**

Create two symbols in one sector, duplicate one symbol's individual events 100× while holding its symbol-level median sign/value constant, and assert sector counts/`median_of_symbol_median_return_bps` still use one value per symbol. Sector horizon sign counts classify each available symbol's own median as positive/zero/negative. No event pooling.

- [ ] **Step 7: Implement report quality flags**

Add only: source unavailable present; available zero-event symbol; zero-sample horizon; short-history present when an available symbol's observed_since > 2023-01-01. Preserve fixed flag order; do not derive PASS/FAIL.

- [ ] **Step 8: Test OOS contamination and protocol drift fail-closed**

The service must construct every batch call from protocol dates, not caller dates. A mutated protocol with common_through after 2026-08-20, changed candidate ids/products/sectors or prospective_consumed=True must fail at loading/contract construction before any batch source call.

- [ ] **Step 9: Run targeted tests/static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_robustness.py \
  services/quant-api/tests/data_foundation/test_jdj_robustness_service.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/market_data/jdj_robustness.py services/quant-api/app/market_data/jdj_robustness_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app/market_data/jdj_robustness.py services/quant-api/app/market_data/jdj_robustness_service.py
```

- [ ] **Step 10: Independent review and integrate**

Reviewer checks 60 batch calls/180 rows, no per-year reload, symbol-balanced sector, no pooled overall aggregate, no score/rank and no OOS. C0/I0 then integrate `develop` and clean.

---

# Task 4 — Wire the Existing Candidate-Robustness CLI and Composition

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 new task worktree，branch `research/jdj-active60-robustness-cli`
- 人工 Gate：独立 Review

Worktree：latest `develop`; integrate only to `develop`; C0/I0 + CLI tests; clean after readback; no `main`/tag/Runtime.

**Files:**
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Modify: `TESTING.md`

**Interfaces:**
- Existing command remains `guiyi research candidate-robustness --protocol ...`.
- Add protocol choice `jdj_active60_robustness_v1`; existing `multi_candidate_robustness_v1` path and payload stay unchanged.

- [ ] **Step 1: Write RED parser/request tests**

Assert:

```text
guiyi research candidate-robustness --protocol jdj_active60_robustness_v1
```

builds `JdjActive60RobustnessRequest("jdj_active60_robustness_v1")`, while the old protocol still builds `MultiCandidateRobustnessRequest`. Assert no `--since/--through/--symbols/--score/--rank` are accepted for this command.

- [ ] **Step 2: Add composition factory minimally**

Follow the existing `multi_candidate_robustness_v1` factory pattern: load exact Phase 7 protocol, reuse the existing shared JDJ research service/composition, instantiate `JdjActive60RobustnessService`. Do not introduce protocol registries or generic DI containers.

- [ ] **Step 3: Extend request union/dispatch by concrete type**

Add `JdjActive60RobustnessRequest` to `ResearchRequest`, dispatch to the Phase 7 service before the existing multi-candidate path if needed for unambiguous typing, and keep existing candidate-validation/JDJ/main-force behavior unchanged.

- [ ] **Step 4: Implement exact JSON renderer**

Render Decimal values as strings following existing CLI conventions. Top-level keys follow the Spec. Each symbol row includes yearly summaries; sector summaries are rendered without any score/rank/winner fields. Add an explicit test recursively rejecting keys named `score`, `rank`, `winner`, `decision`, `pnl`, `order`, `fill`, `position`.

- [ ] **Step 5: Lock old robustness immutable regression**

Run and preserve existing `multi_candidate_robustness_v1` parser, payload and service tests unchanged. Do not modify old protocol JSON, old report dataclasses or existing frozen evidence file.

- [ ] **Step 6: Update TESTING.md with one read-only command**

Document only the exact Phase 7 command and state that it is Historical/read-only and protocol-fixed; do not add operational automation instructions.

- [ ] **Step 7: Run CLI/robustness/full focused regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_jdj_robustness.py \
  services/quant-api/tests/data_foundation/test_jdj_robustness_service.py
```

Then run applicable Ruff/Mypy and CLI help/read-only smoke.

- [ ] **Step 8: Independent review and integrate**

Review C0/I0; verify old command output identity unchanged; integrate to `develop` and clean task worktree/branch.

---

# Task 5 — Generate the Real Read-Only Evidence and Close Phase 7

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从 latest `develop` 创建 new task worktree，branch `research/jdj-active60-robustness-evidence`
- 人工 Gate：独立 Review

Worktree：latest `develop`; only report/docs changes plus any narrowly required bugfix found by evidence review; integrate only to `develop`; no release/tag/Runtime. Real command is read-only against existing Historical Canonical and is not an external mutation Gate.

**Files:**
- Create: `reports/research/candidate_robustness/jdj_active60_robustness_v1/active60-retrospective-freeze-2026-08-21.json`
- Modify: `PROJECT_SOURCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md`
- Test/verify: all Phase 7 and affected research suites

**Interfaces:**
- Consumes the exact CLI from Task 4.
- Produces one immutable Git-tracked research evidence file and canonical status text; no DB/Canonical/Redis write.

- [ ] **Step 1: Run preflight on clean latest develop lineage**

Read canonical docs, verify current active60/taxonomy exactly match protocol, verify existing JDJ three `jm` baselines remain present and prospective first day is still 2026-08-24. If canonical drift exists, stop `BLOCKED_CANONICAL_DRIFT` rather than editing the protocol opportunistically.

- [ ] **Step 2: Run the exact read-only Phase 7 command once**

```bash
guiyi research candidate-robustness --protocol jdj_active60_robustness_v1
```

Capture stdout JSON to the exact evidence path. Do not invoke RQData update/refresh, DB migration, Redis, Live, Alert or any backfill command.

- [ ] **Step 3: Machine-validate the evidence invariants**

Assert protocol id/frozen identity; retrospective `2023-01-01..2026-08-20`; `prospective_consumed=false`; exactly 180 cross-symbol rows; exact 3 candidates × frozen 60 products; no forbidden keys recursively; every yearly key is one of 2023/2024/2025/2026; sector summaries use only frozen sectors; no overall pooled performance field.

- [ ] **Step 4: Re-run the command and compare deterministic identity**

The second read-only run must produce the same schema, protocol/candidate/product/sector identities and same research facts for unchanged Canonical/Catalog. If byte ordering is deterministic by contract, require byte equality; otherwise canonical JSON semantic equality. Do not add hashes/receipts as a new architecture requirement.

- [ ] **Step 5: Review evidence for typed availability, not strategy quality**

Check unavailable symbols are typed, zero-event available symbols remain available, short-history flag matches observed_since facts, and sample-zero null semantics hold. Do not classify candidates or sectors as winners/losers.

- [ ] **Step 6: Update canonical docs minimally**

`PROJECT_SOURCE.md`/`docs/ARCHITECTURE.md`: add Phase 7 read-only command/protocol and boundaries. `STATUS.md`: record exact evidence path, 180-cell completeness/typed unavailable counts and that it is retrospective research-only; keep JDJ prospective OOS pending and explicitly state no rank/winner/KEEP/DROP/PROMOTE, Alert, Runtime or order change.

- [ ] **Step 7: Run full affected verification**

Run Phase 7 tests, existing JDJ Candidate Validation, old multi-candidate robustness, research CLI, Ruff, Mypy, secret scan and `git diff --check`. Run broader backend suite if required by current `TESTING.md` for research semantic changes.

- [ ] **Step 8: Independent final review**

Review spec coverage and evidence boundaries: Critical 0 / Important 0 required. Minor findings may be fixed only if they do not alter protocol/formulas or enlarge scope.

- [ ] **Step 9: Integrate develop and clean**

After final review, integrate task branch → `develop`, confirm commit ancestry/readback, then clean the temporary task worktree and merged branch. Do not release `main`, create tag, switch Runtime, change Alert Scope, send notifications or perform any real data/DB mutation.

---

## Plan Self-Review Checklist

Before implementation begins, verify:

- Spec sections 1–21 map to Tasks 1–5.
- No Task adds generic registry/DSL/queue/cache/parallel execution.
- `run_batch()` is the only new JDJ evaluation seam and old `run()` parity is mandatory.
- Phase 7 dates are protocol-owned and cannot consume 2026-08-21 or 2026-08-24+.
- No active60 10-fold rerun; yearly diagnostics use existing retrospective event outcomes only.
- No P25/P75 or LONG/SHORT outcome matrix.
- Sector aggregation is symbol-balanced and no pooled overall metric exists.
- Old `multi_candidate_robustness_v1` protocol/report/evidence remains unchanged.
- No task creates strategy effectiveness, profitability, trading-readiness or promotion claims.
