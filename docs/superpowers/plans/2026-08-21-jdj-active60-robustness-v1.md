# Phase 7 — JDJ Active60 Robustness V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改三个冻结 JDJ Candidate 公式、不消费 prospective OOS、不过度扩展架构的前提下，以一次 `symbol + retrospective window` shared-loader 调用复用现有 JDJ causal evaluation，形成 `3 × active60 = 180` 个轻量跨品种事实、年度诊断和 symbol-balanced 板块汇总。

**Architecture:** 复用 `MarketDataService → ActualDominantResearchSegmentLoader → existing JDJ context/reducers → price-only outcomes`。对 `JdjResearchService` 做最小加法式 batch/detail seam，使单 symbol 的 1m/5m 与 context 只计算一次；新增两个 Phase 7 专用业务文件承载 exact protocol/report contract 与只读 orchestration，继续复用现有 `candidate-robustness` CLI，不建立通用 robustness platform、coverage 子系统、rolling engine、score/rank 或持久化状态。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、existing `JdjResearchService`、`ActualDominantResearchSegmentLoader`、`PriceDirectionalOutcome`、existing product taxonomy、argparse CLI、pytest、Ruff、Mypy、Git-tracked exact JSON research contracts。

**Spec:** `docs/superpowers/specs/2026-08-21-jdj-active60-robustness-v1-design.md`

**Task Contract:** `docs/tasks/TASK-JDJ-ACTIVE60-ROBUSTNESS-V1-20260821.md`

## Global Constraints

- 每个 Task 开始前读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、Spec、Plan、Task Contract 与最新 `develop`；冲突时 `BLOCKED_CANONICAL_DRIFT`。
- Exact candidates：`jdj_trend_follow_1m_candidate_v1`、`jdj_trend_reentry_6_1m_candidate_v1`、`jdj_key_level_breakout_1m_candidate_v1`。
- 不修改 `jdj_1m_policy_v1`、Candidate manifests、`jdj_candidate_validation_v1`、EMA20、N Structure V1 或 reducers。
- Historical 唯一入口：`MarketDataService → ActualDominantResearchSegmentLoader`。
- Exact retrospective：`2023-01-01..2026-08-20`；禁止消费 `2026-08-21` embargo 与 `2026-08-24+` prospective OOS。
- 每个 symbol 的 full retrospective 只调用一次 `ActualDominantResearchSegmentLoader.load(... frequencies=(M1,M5) ...)`；loader 内部既有 probe/full MDS 语义不变。
- Yearly 只从 full retrospective event/outcome 分组，不重新读取行情。
- 只做 `available|unavailable`；不建第二 coverage domain。
- 单品种 outcome 只做 ALL；仅另存 `long_event_count/short_event_count`。
- Sector 只做 symbol-balanced；不做 event pooling、active60 pooled performance、score/rank/winner/KEEP/DROP/PROMOTE。
- V1 串行；不加 multiprocessing/async/worker/queue/cache/DB/Web/API/Alert/Runtime/order。
- `auto_order=false`。
- Task→`develop` 只是普通开发集成；不授权 `main`、tag、release、Runtime、DB/Canonical/Redis、通知或其他外部 mutation。

## Frozen active60 snapshot

```text
a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sm sn sr ss ta ur v y zn
```

## Frozen sector snapshot

```text
a=agriculture
ag=precious
al=nonferrous
ao=nonferrous
ap=agriculture
au=precious
b=agriculture
bu=energy
bz=chemical
c=agriculture
cf=agriculture
cj=agriculture
cu=nonferrous
eb=chemical
ec=other
eg=chemical
fg=building
fu=energy
hc=steel
i=black
j=black
jd=agriculture
jm=black
l=chemical
lc=new_energy
lh=agriculture
m=agriculture
ma=chemical
ni=nonferrous
oi=agriculture
p=agriculture
pb=nonferrous
pd=precious
pf=chemical
pg=energy
pk=agriculture
pl=chemical
pp=chemical
pr=chemical
ps=new_energy
pt=precious
px=chemical
rb=steel
rm=agriculture
rs=agriculture
ru=chemical
sa=building
sc=energy
sf=black
sh=chemical
si=new_energy
sm=black
sn=nonferrous
sr=agriculture
ss=steel
ta=chemical
ur=chemical
v=chemical
y=agriculture
zn=nonferrous
```

---

# Task 1 — Exact Protocol and Lightweight Report Contracts

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 `research/jdj-active60-robustness-v1-contracts` task worktree
- 人工 Gate：独立 Review

Worktree：从 `develop` 创建；完成后只允许 task branch → `develop`；Review C0/I0 + tests 后可自动集成并清理；不得触及 `main`、tag、Runtime。

**Files:**
- Create: `data/research_protocols/jdj_active60_robustness_v1.json`
- Create: `services/quant-api/app/market_data/jdj_robustness.py`
- Test: `services/quant-api/tests/test_jdj_robustness.py`

**Interfaces:**
- Produces: `JdjActive60RobustnessProtocolError`, `JdjActive60RobustnessProtocol`, `JdjActive60RobustnessRequest`, `JdjRobustnessStatus`, `JdjRobustnessHorizonSummary`, `JdjRobustnessYearSummary`, `JdjRobustnessSymbolResult`, `JdjRobustnessSectorHorizonSummary`, `JdjRobustnessSectorSummary`, `JdjActive60RobustnessReport`, `load_jdj_active60_robustness_protocol(path: Path | None = None)`.

- [ ] **Step 1: Write RED exact protocol test**

```python
def test_phase7_protocol_is_exact_and_does_not_consume_oos() -> None:
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
```

Also assert `cross_symbol_products` equals the exact 60-symbol tuple above and `sector_groups` equals the exact product/sector mapping above in the same product order.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_robustness.py
```

Expected: import/file failure.

- [ ] **Step 3: Create exact protocol JSON**

The JSON must contain exactly these semantic fields: `schema_version=1`, `protocol_id=jdj_active60_robustness_v1`, `research_only=true`, `readonly=true`, frozen timestamp from the approved Spec, the three candidate ids in order, `source_policy=jdj_1m_policy_v1`, `source_validation_protocol=jdj_candidate_validation_v1`, retrospective/embargo/prospective fields above, `horizons_bars=[3,5,8,20]`, exact `cross_symbol_products`, exact `sector_groups`, `parameter_perturbation=false`, `relationship_analysis=false`, `automatic_ranking=false`, `automatic_promotion=false`. Do not add thresholds, rolling settings, concurrency or weights.

- [ ] **Step 4: Implement strict protocol loader**

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

Use existing exact JSON loader conventions. After loading, read current active products and taxonomy and require exact equality with frozen snapshots. Also load existing JDJ validation protocol and require retrospective `2023-01-01..2026-08-20`, embargo `2026-08-21`, prospective first `2026-08-24`, horizons `(3,5,8,20)` and exact candidate ids.

- [ ] **Step 5: Write report invariants RED tests**

Tests must assert: exact 180 rows; candidate-major/product-order identity; unavailable rows keep identity and typed reason but nullable metrics; available `event_count=0` remains available; `sample_count=0` forces rate/medians null; sector sign counts sum to `symbols_with_samples`; quality flags are only `SOURCE_UNAVAILABLE_PRESENT`, `SYMBOL_WITHOUT_EVENT`, `HORIZON_WITHOUT_SAMPLE`, `SHORT_HISTORY_PRESENT`.

- [ ] **Step 6: Implement report dataclasses only to satisfy those invariants**

Do not add metadata dicts, generic registries, scores, decisions, PnL fields or prospective metric objects.

- [ ] **Step 7: GREEN + static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/market_data/jdj_robustness.py services/quant-api/tests/test_jdj_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app/market_data/jdj_robustness.py
```

- [ ] **Step 8: Review/integrate/clean**

Independent review must confirm old `multi_candidate_robustness_v1` files are untouched and no generic robustness framework appeared. C0/I0 then integrate to `develop`, read back ancestry, clean task worktree/branch.

---

# Task 2 — Shared JDJ Batch/Detail Seam with Exact Parity

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 `research/jdj-batch-detail-seam` task worktree
- 人工 Gate：独立 Review

Worktree：latest `develop` → task → `develop`; C0/I0 + parity tests 后集成并清理；不触及 `main`/tag/Runtime。

**Files:**
- Modify: `services/quant-api/app/market_data/jdj_research.py`
- Modify: `services/quant-api/app/market_data/jdj_research_service.py`
- Test: `services/quant-api/tests/data_foundation/test_jdj_research_service.py`

**Interfaces:**
- Add `JdjEventOutcomeRecord`, `JdjDetailedCandidateResult`, `JdjBatchResearchResult` to `jdj_research.py`.
- Add `JdjResearchService.run_batch(*, symbol: str, since: date, through: date) -> JdjBatchResearchResult`.
- Existing `run(request: JdjResearchRequest) -> JdjResearchResult` behavior must remain exact.

- [ ] **Step 1: Write RED single-load batch test using existing test helpers**

Append to the existing service test file, reusing `_RecordingLoader`, `_loaded_series()` and `_service()` already defined there:

```python
def test_run_batch_loads_once_for_three_exact_candidates() -> None:
    loader = _RecordingLoader(_loaded_series())
    service = _service(loader)
    result = service.run_batch(
        symbol="jm",
        since=_SEGMENT_START,
        through=_DAY,
    )
    assert loader.calls == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.M1, BarFrequency.M5),
            "since": _SEGMENT_START,
            "through": _DAY,
        }
    ]
    assert tuple(item.result.candidate_id for item in result.candidates) == (
        "jdj_trend_follow_1m_candidate_v1",
        "jdj_trend_reentry_6_1m_candidate_v1",
        "jdj_key_level_breakout_1m_candidate_v1",
    )
```

Also assert `observed_since == _SEGMENT_START` and `observed_through == _DAY` for this fixture.

- [ ] **Step 2: Write RED parity test**

For each candidate id above, call existing `service.run(JdjResearchRequest(_SEGMENT_START, _DAY, "jm", candidate_id))`, call `run_batch()` once, select the matching detailed result and assert exact equality of `events`, `trigger_count_long`, `trigger_count_short`, `evaluable_bar_count`, and all four existing `PriceHorizonEvaluation` objects.

- [ ] **Step 3: Add minimal detail records**

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

Validate exact `(3,5,8,20)` horizon keys and preserve event order.

- [ ] **Step 4: Extract one private loaded-series evaluator**

The helper receives one validated `ActualDominantResearchSeries`, the request window and exact candidate ids. Per segment it builds `build_jdj_context_series()` once, runs only requested existing reducers, uses existing `_validate_event_alignment()`, and uses existing `build_price_outcomes_at()`. `run()` loads once and requests one candidate; `run_batch()` loads once and requests all three.

- [ ] **Step 5: GREEN parity; never change old goldens to accept drift**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_research.py services/quant-api/tests/data_foundation/test_jdj_research_service.py
```

Any event/count/outcome difference is blocking.

- [ ] **Step 6: Static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/market_data/jdj_research.py services/quant-api/app/market_data/jdj_research_service.py services/quant-api/tests/data_foundation/test_jdj_research_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app/market_data/jdj_research.py services/quant-api/app/market_data/jdj_research_service.py
```

- [ ] **Step 7: Review/integrate/clean**

Reviewer checks single loader call, shared context, strict-before preservation, no formula copy, old `run()` parity. C0/I0 then integrate `develop` and clean.

---

# Task 3 — Active60 / Year / Sector Robustness Service

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 `research/jdj-active60-robustness-service` task worktree
- 人工 Gate：独立 Review

Worktree：latest `develop` → task → `develop`; C0/I0 + tests 后集成并清理；不触及 `main`/tag/Runtime。

**Files:**
- Create: `services/quant-api/app/market_data/jdj_robustness_service.py`
- Test: `services/quant-api/tests/data_foundation/test_jdj_robustness_service.py`
- Modify only if a pure invariant helper belongs with contracts: `services/quant-api/app/market_data/jdj_robustness.py`

**Interface:** `JdjActive60RobustnessService.run(request: JdjActive60RobustnessRequest) -> JdjActive60RobustnessReport`.

- [ ] **Step 1: RED exact-window/180-row test**

Use a fake batch runner whose `run_batch(symbol, since, through)` records calls and returns deterministic `JdjBatchResearchResult`. Assert exactly 60 calls, each with `since=date(2023,1,1)` and `through=date(2026,8,20)`, and exactly 180 rows in candidate-major/product order.

- [ ] **Step 2: RED metric semantics test**

For four `PriceDirectionalOutcome` values whose directional returns are `-2, 0, 3, 4`, assert `sample_count=4`, `historical_positive_outcome_rate=Decimal("0.5")`, `median_directional_return_bps=Decimal("1.5")`; assert MFE/MAE medians from the same four values. Zero samples must produce `None` for rate and all medians.

- [ ] **Step 3: Implement one pure horizon summarizer**

Use `statistics.median` on Decimal values. Positive rate is `Decimal(count(return > 0)) / Decimal(sample_count)`. Do not add quartiles or thresholds.

- [ ] **Step 4: Implement symbol projection**

For each detailed candidate, derive event/evaluable/long/short from existing result, ALL horizon metrics from detailed event outcomes, `event_rate_per_1000_evaluable`, and sector from the frozen protocol mapping. A typed source/identity failure for a symbol emits three unavailable cells and continues; available + zero events remains available.

- [ ] **Step 5: Implement yearly diagnostics without source reload**

Group the already produced event outcome records by `trading_day.year` for `2023, 2024, 2025, 2026`. Each year stores only `event_count` and per-horizon `sample_count`, positive outcome rate and median directional return. Unit test the fake batch runner call count remains exactly 60 after yearly summaries are built.

- [ ] **Step 6: Implement symbol-balanced sector summary**

For each candidate/sector/horizon, consume at most one symbol-level median from each available symbol. Unit test that duplicating one symbol's individual events while keeping its symbol median unchanged does not change that symbol's sector weight. Store only `symbol_count`, `available_symbol_count`, `symbols_with_events`, sign counts and `median_of_symbol_median_return_bps`.

- [ ] **Step 7: Implement fixed quality flags**

Only fixed ordered subset: `SOURCE_UNAVAILABLE_PRESENT`, `SYMBOL_WITHOUT_EVENT`, `HORIZON_WITHOUT_SAMPLE`, `SHORT_HISTORY_PRESENT`.

- [ ] **Step 8: OOS/global drift RED→GREEN**

Mutated protocol dates/products/sectors/candidate ids or `prospective_consumed=True` must fail before first batch call. The service itself owns no user-supplied dates.

- [ ] **Step 9: Targeted verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_robustness.py services/quant-api/tests/data_foundation/test_jdj_robustness_service.py services/quant-api/tests/data_foundation/test_jdj_research_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/market_data/jdj_robustness.py services/quant-api/app/market_data/jdj_robustness_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app/market_data/jdj_robustness.py services/quant-api/app/market_data/jdj_robustness_service.py
```

- [ ] **Step 10: Review/integrate/clean**

C0/I0 review must explicitly verify: 60 calls, 180 rows, yearly no-reload, symbol-balanced sector, no pooled overall performance, no score/rank/OOS. Then integrate `develop` and clean.

---

# Task 4 — Existing Candidate-Robustness CLI / Composition Wiring

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 `research/jdj-active60-robustness-cli` task worktree
- 人工 Gate：独立 Review

Worktree：latest `develop` → task → `develop`; C0/I0 + tests 后集成并清理；不触及 `main`/tag/Runtime。

**Files:**
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Modify: `TESTING.md`

- [ ] **Step 1: RED parser/request tests**

Assert `guiyi research candidate-robustness --protocol jdj_active60_robustness_v1` builds `JdjActive60RobustnessRequest(protocol_id="jdj_active60_robustness_v1")`. Assert existing `multi_candidate_robustness_v1` still builds its existing request. Assert the command parser exposes no `--since`, `--through`, `--symbols`, `--threshold`, `--score`, `--rank`.

- [ ] **Step 2: Add one concrete composition factory**

Follow the existing robustness factory pattern: load exact Phase 7 protocol, reuse existing JDJ research service, instantiate `JdjActive60RobustnessService`. Do not add protocol registries or generic DI abstractions.

- [ ] **Step 3: Extend concrete request union and dispatch**

Add `JdjActive60RobustnessRequest` to `ResearchRequest`; dispatch by concrete type to the new service. Keep all existing research commands unchanged.

- [ ] **Step 4: Implement exact JSON renderer**

Render Decimal as strings using existing CLI conventions. Include top-level identity/time fields, candidate ids, exact 180 rows including yearly maps, sector summaries and flags. Add a recursive test that the rendered payload contains none of these keys: `score`, `rank`, `winner`, `decision`, `pnl`, `order`, `fill`, `position`.

- [ ] **Step 5: Lock old robustness regression**

Do not modify old protocol/report/evidence. Run existing old robustness parser/report/service tests unchanged.

- [ ] **Step 6: Update TESTING.md minimally**

Add only the exact read-only command and its protocol-fixed/Historical-only meaning. Do not add scheduler/automation instructions.

- [ ] **Step 7: Verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_research_cli.py services/quant-api/tests/test_multi_candidate_robustness.py services/quant-api/tests/test_multi_candidate_robustness_policy.py services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py services/quant-api/tests/test_jdj_robustness.py services/quant-api/tests/data_foundation/test_jdj_robustness_service.py
```

Run applicable Ruff/Mypy after pytest.

- [ ] **Step 8: Review/integrate/clean**

C0/I0; verify old CLI output identity unchanged. Integrate `develop`, read back, clean task worktree/branch.

---

# Task 5 — Real Read-Only Evidence and Canonical Closeout

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 `research/jdj-active60-robustness-evidence` task worktree
- 人工 Gate：独立 Review

Worktree：latest `develop` → task → `develop`; only evidence/docs plus narrowly necessary bugfixes; no `main`/tag/Runtime. The command is read-only against existing Canonical/Catalog and is not an external mutation Gate.

**Files:**
- Create: `reports/research/candidate_robustness/jdj_active60_robustness_v1/active60-retrospective-freeze-2026-08-21.json`
- Modify: `PROJECT_SOURCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Canonical preflight**

Read current canonical docs and exact three existing JDJ `jm` baselines. Require active60/taxonomy readback equals Phase 7 protocol and JDJ prospective first remains `2026-08-24`. Any drift: stop `BLOCKED_CANONICAL_DRIFT`; do not edit protocol to fit current state.

- [ ] **Step 2: Run exact read-only command**

```bash
guiyi research candidate-robustness --protocol jdj_active60_robustness_v1
```

Capture stdout JSON to the exact evidence path. Do not run RQData update/refresh, migration, Redis, Live, Alert or backfill.

- [ ] **Step 3: Machine-check evidence**

Require protocol id and frozen identity, retrospective `2023-01-01..2026-08-20`, `prospective_consumed=false`, exactly 180 rows, exact candidate/product/sector identities, only yearly keys `2023/2024/2025/2026`, and recursively no forbidden score/rank/winner/decision/PnL/order/fill/position keys.

- [ ] **Step 4: Repeat read-only command for deterministic semantic equality**

Re-run unchanged Canonical/Catalog and compare parsed JSON equality. Byte equality may be required only if current renderer already guarantees stable byte order; do not invent hash/receipt architecture.

- [ ] **Step 5: Evidence boundary review**

Check typed unavailable rows, zero-event available rows, zero-sample nulls, short-history flag consistency. Do not classify candidate/sector quality.

- [ ] **Step 6: Minimal canonical doc closeout**

`PROJECT_SOURCE.md`/`docs/ARCHITECTURE.md`: add exact Phase 7 command/protocol and read-only boundaries. `STATUS.md`: record evidence path, exact 180-cell completeness and typed unavailable counts observed in evidence; keep prospective OOS pending; explicitly state no score/rank/KEEP/DROP/PROMOTE, Alert, Runtime or order change.

- [ ] **Step 7: Full affected verification**

Run Phase 7 tests, existing JDJ Candidate Validation, old multi-candidate robustness, research CLI, Ruff, Mypy, secret scan and `git diff --check`; run the broader backend suite if current `TESTING.md` requires it for research semantic changes.

- [ ] **Step 8: Independent final review**

Require Critical=0 / Important=0. Minor fixes may not alter protocol/formulas or enlarge scope.

- [ ] **Step 9: Integrate/clean**

Integrate task → `develop`, confirm ancestry/readback, clean task worktree/branch. Do not release main/tag, switch Runtime, mutate DB/Canonical/Redis, change Alert Scope or send notifications.

---

## Plan Self-Review

- Spec 1–21 covered by Tasks 1–5.
- No literal placeholders (`TBD`, `TODO`, ellipsis placeholders) remain.
- Exact active60 and sector snapshots are written in this plan.
- `run_batch()` is the only new JDJ evaluation seam; existing `run()` parity is hard-gated.
- No active60 rolling rerun, quartile layer, LONG/SHORT outcome matrix, coverage subsystem, generic framework or concurrency layer.
- Phase 7 cannot consume 2026-08-21 or 2026-08-24+.
- Sector is symbol-balanced; no active60 pooled performance.
- Old `multi_candidate_robustness_v1` identity/report/evidence remains immutable.
- No task can conclude profitability, strategy validity, trading readiness or automatic promotion.
