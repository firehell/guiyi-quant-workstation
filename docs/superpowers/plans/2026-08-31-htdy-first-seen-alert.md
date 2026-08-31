# HTDY Forward-Only First-Seen Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change HTDY Alert from current-bar-only evaluation to forward-only first-seen repaint detection while preserving the existing HTDY formula, Rule/Scope, AlertEvent schema, one-shot PushPlus transport, and no-backfill/no-replay boundaries.

**Architecture:** Keep the existing Alert Runtime triggers and persistence domain. Extend the Alert market-read window with per-Bar rank1 contract ownership, add a bounded HTDY prefix-diff evaluator that compares `previous_prefix` with `current_prefix`, freeze first-seen candidates into the existing `alert_events` identity, and expose the already-persisted `detected_at` truth in PushPlus/Web presentation. No migration or new subsystem is introduced.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / NumPy / pytest, Vue 3 / TypeScript / Vitest, existing `MarketDataService`, `MarketReadService`, Alert Runtime V2, PushPlus transport.

**Spec:** `docs/superpowers/specs/2026-08-31-htdy-first-seen-alert-design.md`

## Global Constraints

- Lane 3 trusted Alert semantics. Use Sol/high reasoning and a fresh implementation session/worktree.
- Start the implementation branch/worktree from the latest `develop`, not from this documentation branch.
- HTDY formula, indicator code/version, Rule code `htdy_original_15m`, Scope authority, current real `jm × 15m` Scope, audience and Topic remain unchanged.
- No Alembic migration and no new table/domain.
- No production PostgreSQL/Redis/Scope writes, no real PushPlus send, no Runtime switch/promotion, no `main` merge/tag/release.
- Intraday trigger remains same-frequency completed Live Bar; D1/W1 remain `canonical_updated` only.
- Event stays commit-first then at most one transport attempt; no retry/replay/backfill/fallback.
- Existing SuBing behavior and tests must remain unchanged.
- `STATUS.md` must not be updated merely because code/tests pass.
- TDD: every behavior change begins with a failing focused test.

---

## File Structure

The implementation should stay within existing boundaries:

- `services/quant-api/app/market_data/market_read_service.py`
  - Extend `MarketReadWindow` so every returned Bar has an authoritative aligned rank1 contract owner.
- `services/quant-api/app/alerts/evaluators.py`
  - Own pure HTDY current/prefix first-seen detection and candidate construction.
- `services/quant-api/app/alerts/service.py`
  - Own immutable indicator first-seen persistence/idempotency only; keep Strategy Action consistency unchanged.
- `services/quant-api/app/alerts/runtime.py`
  - Wire multiple first-seen candidates into the existing Event/message/transport loop for intraday and D1/W1.
- `services/quant-api/app/alerts/notification.py`
  - Render observation time separately from first-seen detection time.
- `apps/quant-web/src/utils/alertMarkers.ts`
  - Keep persistent square markers but make the tooltip explicitly show first-seen timing.
- Active canonical docs: `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`; `TESTING.md` only if commands change.

Tests remain in the existing suites:

- `services/quant-api/tests/test_alert_evaluator.py`
- `services/quant-api/tests/test_alert_runtime.py`
- `services/quant-api/tests/test_alert_notification.py`
- `services/quant-api/tests/test_alert_notification_dispatcher.py` when the dispatcher fixture requires the new message field
- existing MarketReadService tests discovered by repository search; if no dedicated file exists, place focused ownership tests in `services/quant-api/tests/test_alert_runtime.py` only if they exercise the real `MarketReadService`, otherwise create `services/quant-api/tests/test_market_read_service.py`
- `apps/quant-web/tests/alerts.test.ts`
- `tests/engineering/test_canonical_consistency.py`

---

### Task 1: Give Alert windows exact per-Bar contract ownership

**Files:**
- Modify: `services/quant-api/app/market_data/market_read_service.py`
- Test: existing MarketReadService test file discovered in the repository; create `services/quant-api/tests/test_market_read_service.py` only if no focused file exists

**Interfaces:**
- Consumes: `MarketSeriesPageResult.resolved_contract_segments`, current Live subscription contract, `CanonicalBar.trading_day`.
- Produces: `MarketReadWindow.bar_contracts: tuple[str, ...]`, aligned 1:1 with `MarketReadWindow.bars`; invariant `bar_contracts[-1] == contract` for the latest Bar.

- [ ] **Step 1: Write failing tests for historical and Live ownership alignment**

Add tests that construct an actual-dominant page spanning two `ResolvedContractSegment`s plus one Live Bar. Assert exact alignment:

```python
window = service.bars_until(
    SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, "jm", BarFrequency.M15),
    trading_day=DAY_2,
    end=LIVE_END,
    limit=64,
)

assert len(window.bar_contracts) == len(window.bars)
assert tuple(zip((bar.trading_day for bar in window.bars), window.bar_contracts)) == (
    (DAY_1, "JM2701"),
    (DAY_2, "JM2705"),
    (DAY_2, "JM2705"),
)
assert window.bar_contracts[-1] == window.contract == "JM2705"
```

Also add a test where the Historical segment says `JM2701` for the same Bar while a duplicate Live Bar claims current subscription `JM2705`; expected result is `MarketReadWindowError`, not silent preference.

- [ ] **Step 2: Run the focused tests and verify RED**

Run the exact test file with:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q <market-read-test-file>
```

Expected: failure because `MarketReadWindow` has no `bar_contracts` and/or ownership conflict is not checked.

- [ ] **Step 3: Extend `MarketReadWindow` and add one ownership resolver**

Use an aligned field, not a second lookup service:

```python
@dataclass(frozen=True, slots=True)
class MarketReadWindow:
    symbol: str
    series_kind: str
    frequency: str
    trading_day: date
    contract: str
    cutoff: datetime
    bars: tuple[CanonicalBar, ...]
    bar_contracts: tuple[str, ...]
```

Add a focused helper that maps each historical Bar by `resolved_contract_segments` and validates exactly one owner:

```python
def _resolved_contract_for_bar(
    symbol: str,
    bar: CanonicalBar,
    segments: tuple[ResolvedContractSegment, ...],
) -> str:
    owners = tuple(
        segment.contract
        for segment in segments
        if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
    )
    if len(owners) != 1:
        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
    contract = normalize_contract_for_symbol(symbol, owners[0])
    if contract is None:
        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
    return contract
```

In `bars_until`, keep the `MarketSeriesPageResult` object rather than discarding it to `.bars`, derive ownership before merging Live, and reject duplicate Bar ownership disagreement. In `latest_canonical_window`, derive aligned ownership from its page segments. Preserve the existing singular `window.contract` for current/latest compatibility.

- [ ] **Step 4: Run focused tests and verify GREEN**

Use the same command from Step 2. Expected: PASS.

- [ ] **Step 5: Run current Alert Runtime tests to catch fixture breakage**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_runtime.py
```

Update fake `MarketReadWindow` builders to provide aligned `bar_contracts`; do not use an empty default that lets production first-seen evaluation bypass contract identity.

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/market_data/market_read_service.py services/quant-api/tests

git commit -m "feat: preserve alert bar contract ownership"
```

---

### Task 2: Add bounded HTDY prefix-diff first-seen evaluation

**Files:**
- Modify: `services/quant-api/app/alerts/evaluators.py`
- Test: `services/quant-api/tests/test_alert_evaluator.py`

**Interfaces:**
- Consumes: `MarketReadWindow.bars`, `MarketReadWindow.bar_contracts`, production `CONFIGURED_REPAINT_SCAN_ZONE_BARS` from the HTDY kernel.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class HtdyFirstSeenObservation:
    bar_end: datetime
    trading_day: date
    contract: str
    observation_types: tuple[str, ...]
```

and:

```python
class AlertEvaluator(Protocol):
    indicator_code: str
    def evaluate(self, window: MarketReadWindow) -> AlertEvaluation: ...
    def evaluate_first_seen(
        self, window: MarketReadWindow
    ) -> tuple[HtdyFirstSeenObservation, ...]: ...
```

Keep `evaluate()` as the current-Bar compatibility primitive.

- [ ] **Step 1: Write RED tests for current Bar and historical False→True**

Use a monkeypatched `compute_htdy_original` returning controlled arrays. Cover:

```python
assert evaluator.evaluate_first_seen(window)[0] == HtdyFirstSeenObservation(
    bar_end=window.bars[-1].bar_end,
    trading_day=window.bars[-1].trading_day,
    contract=window.bar_contracts[-1],
    observation_types=("sell",),
)
```

Then simulate an append where a prior Bar changes from no observation to sell and assert the candidate uses that old Bar's `bar_end`, `trading_day` and `bar_contracts[index]`, not the latest trigger's contract.

- [ ] **Step 2: Write RED tests for no-retraction/no-direction-revision candidate rules**

Test the prefix detector itself:

```text
sell -> empty      => no new first-seen candidate
buy  -> sell       => no new first-seen candidate
sell -> buy        => no new first-seen candidate
buy  -> buy+sell   => no new first-seen candidate
empty -> buy+sell  => one candidate with ("buy", "sell")
```

The reappearance case `sell -> empty -> sell` may again produce a prefix transition on the third prefix; persistence in Task 3 is the authoritative first-seen dedupe. Do not add a stateful evaluator ledger.

- [ ] **Step 3: Run the focused evaluator tests and verify RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_evaluator.py
```

Expected: missing `evaluate_first_seen` / candidate type.

- [ ] **Step 4: Implement the minimal pure evaluator**

Add constants:

```python
CURRENT_BAR_CONTEXT_BARS = 32
HTDY_FIRST_SEEN_CONTEXT_BARS = 64
```

Import the production repaint constant rather than copying 27 into a second business authority:

```python
from guiyi_quant.indicators.htdy_original import CONFIGURED_REPAINT_SCAN_ZONE_BARS
```

Implementation shape:

```python
def evaluate_first_seen(
    self,
    window: MarketReadWindow,
) -> tuple[HtdyFirstSeenObservation, ...]:
    self._validate_window(window, minimum=CURRENT_BAR_CONTEXT_BARS)
    if len(window.bars) < HTDY_FIRST_SEEN_CONTEXT_BARS:
        current = self.evaluate(window)
        return self._latest_candidate(window, current.observation_types)

    bars = window.bars[-HTDY_FIRST_SEEN_CONTEXT_BARS:]
    contracts = window.bar_contracts[-HTDY_FIRST_SEEN_CONTEXT_BARS:]
    previous = self._compute(bars[:-1])
    current = self._compute(bars)

    candidates = self._prefix_diff_candidates(
        bars=bars,
        contracts=contracts,
        previous=previous,
        current=current,
        scan_bars=CONFIGURED_REPAINT_SCAN_ZONE_BARS,
    )
    return tuple(sorted(candidates, key=lambda item: item.bar_end))
```

`_prefix_diff_candidates` must include the current latest Bar when it has an observation, plus only overlapping previous bars whose prior observation tuple was empty and current tuple is non-empty.

- [ ] **Step 5: Add and prove the 64-Bar/full-history parity test**

Use real `compute_htdy_original`, not a monkeypatch. Generate a sufficiently long deterministic series, append one Bar at a time, and compare the prefix-diff candidates from full history against the bounded 64-Bar window for the overlapping last 27 previous Bars plus current Bar.

Core assertion:

```python
assert bounded_candidates == full_history_candidates
```

Run across enough cutoffs to cover changes near both edges of the repaint zone. If this fails, stop and revise the context length; do not weaken the assertion.

- [ ] **Step 6: Verify 32–63 Bar compatibility**

Add a test proving that a 32–63 Bar window can still emit a current-Bar observation but does not scan historical repaint candidates.

- [ ] **Step 7: Run evaluator tests and verify GREEN**

Use the Step 3 command. Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add services/quant-api/app/alerts/evaluators.py services/quant-api/tests/test_alert_evaluator.py

git commit -m "feat: detect HTDY first-seen repaint observations"
```

---

### Task 3: Freeze HTDY first-seen Event identity without direction drift failures

**Files:**
- Modify: `services/quant-api/app/alerts/service.py`
- Test: existing AlertService tests discovered by repository search, primarily `services/quant-api/tests/test_alert_registry.py` only if service persistence is already covered there; otherwise use the existing service-focused test file found by `AlertService.create_event` search

**Interfaces:**
- Consumes: existing `AlertEventCreate` and HTDY indicator-observation unique identity.
- Produces: an explicit first-seen persistence method for indicator observations, for example:

```python
def create_first_seen_observation_event(
    self, request: AlertEventCreate
) -> AlertEvent | None:
    ...
```

Do not change SuBing Strategy Action persistence semantics.

- [ ] **Step 1: Write RED tests for first create and repaint no-op**

Test sequence:

```python
first = service.create_first_seen_observation_event(
    _htdy_request(bar_end=OBS_END, result_codes=("sell",))
)
assert first is not None

again = service.create_first_seen_observation_event(
    _htdy_request(bar_end=OBS_END, result_codes=("buy",))
)
assert again is None

stored = session.scalar(select(AlertEvent).where(AlertEvent.id == first.id))
assert stored.result_codes == ["sell"]
assert stored.detected_at == FIRST_DETECTED_AT
```

Also assert same identity with `buy+sell` after first create is a no-op, not `AlertConsistencyError`.

- [ ] **Step 2: Write RED test that Strategy Action consistency remains strict**

Create a SuBing Event with the existing path, then try the same Strategy identity with mismatched immutable facts. Expected: existing `AlertConsistencyError`. This protects the rule-kind boundary.

- [ ] **Step 3: Run focused persistence tests and verify RED**

Run the exact discovered service test file with the repository-standard pytest command.

- [ ] **Step 4: Implement an indicator-only first-seen wrapper**

The wrapper must:

1. resolve the Rule and require `AlertRuleKind.INDICATOR_OBSERVATION`;
2. normalize symbol/frequency/time/contract using the same validation as `create_event`;
3. query existing identity `(rule_id, symbol, frequency, bar_end)`;
4. if an existing valid indicator Event is found, return `None` without comparing future repaint `result_codes`;
5. otherwise create through the same commit/error handling path;
6. on `IntegrityError`, read back the same indicator identity and return `None` if it now exists;
7. never apply this relaxed first-seen no-op to Strategy Action Events.

Prefer extracting shared validation from `create_event` only if it reduces duplication without widening the task. Do not redesign AlertService.

- [ ] **Step 5: Run focused tests and verify GREEN**

Expected: first-seen tests pass and existing Strategy Action mismatch tests still pass.

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/alerts/service.py services/quant-api/tests

git commit -m "feat: freeze HTDY first-seen alert events"
```

---

### Task 4: Wire multiple first-seen candidates into Alert Runtime

**Files:**
- Modify: `services/quant-api/app/alerts/runtime.py`
- Test: `services/quant-api/tests/test_alert_runtime.py`

**Interfaces:**
- Consumes: `AlertEvaluator.evaluate_first_seen()`, `AlertService.create_first_seen_observation_event()`.
- Produces: deterministic zero-or-many HTDY Event/messages from one existing trigger.

- [ ] **Step 1: Write RED intraday Runtime tests**

Add tests proving:

```text
Scope OFF                       -> no market read, no evaluator, no Event/send
current Bar first-seen          -> one Event/send
old Bar False→sell              -> Event.bar_end == old observation time
                                  Event.detected_at == processing_now
                                  Event.contract == old Bar owner
multiple candidates             -> chronological Event/message order
existing Event, repaint reentry -> no Event/send and no processing failure
```

- [ ] **Step 2: Write RED startup/restart tests**

Use the current startup drain path:

```python
runtime.process_message(channel, payload, emit_events=False)
assert _event_rows(session) == []
assert sender.messages == []
```

Then process the first genuine new completed Bar and ensure only False→True transitions caused by that Bar are considered. Existing observations already present in `previous_prefix` are not emitted.

- [ ] **Step 3: Write RED D1/W1 canonical tests**

Keep `market:state(reason=canonical_updated)` as the only trigger. Provide a 64-Bar canonical window with aligned contracts and verify old-Bar False→True can create a first-seen Event. Assert no new scheduler or live D1/W1 path is used.

- [ ] **Step 4: Run Runtime tests and verify RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 5: Replace single `_RuleResult` HTDY flow with candidate iteration**

Do not alter SuBing Strategy flow. For HTDY, change the evaluation boundary so Runtime receives zero-or-many first-seen candidates:

```python
candidates = self._htdy_evaluator.evaluate_first_seen(window)
for candidate in candidates:
    prepared = _persist_first_seen_htdy_and_prepare_notification(
        service,
        taxonomy=self._taxonomy,
        rule=rule,
        symbol=symbol,
        candidate=candidate,
        processing_now=processing_now,
    )
    ...
```

The prepared Event uses candidate facts:

```python
AlertEventCreate(
    rule_id=rule.id,
    symbol=symbol,
    contract=candidate.contract,
    trading_day=candidate.trading_day,
    frequency=event_frequency.value,
    bar_end=candidate.bar_end,
    result_codes=candidate.observation_types,
    action_id=None,
    strategy_payload=None,
    detected_at=processing_now,
    notification_attempted_at=processing_now,
)
```

For D1/W1 use `frequency.value` from the canonical pair and the candidate's own observation facts. Keep existing per-pair exception isolation.

- [ ] **Step 6: Increase HTDY MarketRead limits only where required**

Change HTDY intraday and D1/W1 window requests from `limit=32` to `limit=64`. Do not change unrelated SuBing reads.

- [ ] **Step 7: Keep Runtime status semantics truthful**

`last_event_at` is updated when at least one Event is newly created. `last_processed_bar_at` remains the incoming trigger Bar for intraday. `last_transport_attempt_at` / `last_provider_accepted_at` remain processing/transport facts. Do not reinterpret them as observation `bar_end`.

- [ ] **Step 8: Run Runtime tests and verify GREEN**

Use Step 4 command. Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add services/quant-api/app/alerts/runtime.py services/quant-api/tests/test_alert_runtime.py

git commit -m "feat: emit HTDY first-seen repaint alerts"
```

---

### Task 5: Render observation time and first-seen time in PushPlus

**Files:**
- Modify: `services/quant-api/app/alerts/notification.py`
- Test: `services/quant-api/tests/test_alert_notification.py`
- Test if required by constructor coverage: `services/quant-api/tests/test_alert_notification_dispatcher.py`

**Interfaces:**
- Consumes: candidate/Event `bar_end` and Runtime `detected_at`.
- Produces: `AlertNotificationMessage.detected_at` and the frozen HTDY copy.

- [ ] **Step 1: Write RED formatting test**

Construct a HTDY message where observation and detection differ:

```python
message = AlertNotificationMessage(
    rule_code="htdy_original_15m",
    symbol="jm",
    product_name="焦煤",
    contract="JM2701",
    frequency="15m",
    bar_end=datetime(2026, 8, 31, 1, 45, tzinfo=UTC),
    detected_at=datetime(2026, 8, 31, 2, 15, tzinfo=UTC),
    result_codes=("sell",),
)
```

Assert the exact rendered lines contain:

```text
观察K线：15m · 09:45
首次识别：10:15
```

Also test current-Bar first-seen where both times are equal.

- [ ] **Step 2: Run notification tests and verify RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py
```

- [ ] **Step 3: Add `detected_at` as a provider-independent message fact**

Use a required aware datetime:

```python
@dataclass(frozen=True, slots=True)
class AlertNotificationMessage:
    rule_code: str
    symbol: str
    product_name: str
    contract: str
    frequency: str
    bar_end: datetime
    detected_at: datetime
    result_codes: tuple[str, ...]
    strategy_payload: SubingStrategyActionPayload | None = None
```

Update both HTDY and SuBing message construction call sites to pass the real processing/Event detection time. Do not change SuBing rendered text.

In `_format_htdy_message`, require timezone-aware `detected_at`, convert both times to Asia/Shanghai and render the exact two-line distinction.

- [ ] **Step 4: Run notification tests and verify GREEN**

Use Step 2 command. Expected: PASS.

- [ ] **Step 5: Run Runtime tests once because message construction changed**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/alerts/notification.py services/quant-api/tests

git commit -m "feat: show HTDY first-seen notification time"
```

---

### Task 6: Make the persistent Web marker explicitly first-seen

**Files:**
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Test: `apps/quant-web/tests/alerts.test.ts`

**Interfaces:**
- Consumes: existing `HtdyAlertEvent.detected_at`, `bar_end`, `contract`, `result_codes`.
- Produces: unchanged square marker identity/shape with a truthful tooltip.

- [ ] **Step 1: Write RED Web test for the two times**

Build an HTDY Event fixture with different `bar_end` and `detected_at`, call `alertEventsToMarkers`, and assert:

```ts
expect(marker.shape).toBe('square')
expect(marker.time).toBe(event.bar_end)
expect(marker.tooltip).toContain('实时首次识别')
expect(marker.tooltip).toContain('观察K线')
expect(marker.tooltip).toContain('首次识别')
```

Also preserve the retrospective marker test showing its existing repaint-risk tooltip and non-Alert identity.

- [ ] **Step 2: Run Web unit test and verify RED**

```bash
pnpm --dir apps/quant-web test -- alerts.test.ts
```

If the project test runner does not accept a filename after `--`, use the existing Vitest invocation from `package.json`; do not change package scripts just for this task.

- [ ] **Step 3: Update only the persistent marker tooltip**

Keep:

```ts
id: `alert:${alertEventIdentityKey(event)}`
position: 'aboveBar'
shape: 'square'
time: event.bar_end
```

Format observation and detection timestamps through an existing shared date/time formatter if one already exists. If none exists in the Alert utilities, add a small local formatter in `alertMarkers.ts`; do not create a new date formatting subsystem.

Suggested semantic text:

```text
实时首次识别 · 持久 AlertEvent · JM2701 · 卖出观察 · 观察K线 09:45 · 首次识别 10:15
```

- [ ] **Step 4: Run Web test and verify GREEN**

Use Step 2 command, then:

```bash
pnpm --dir apps/quant-web run check:alert-rules
```

- [ ] **Step 5: Commit**

```bash
git add apps/quant-web/src/utils/alertMarkers.ts apps/quant-web/tests/alerts.test.ts

git commit -m "feat(web): clarify HTDY first-seen alert markers"
```

---

### Task 7: Synchronize active canonical contracts

**Files:**
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify only if commands change: `TESTING.md`
- Test: `tests/engineering/test_canonical_consistency.py`

**Interfaces:**
- Consumes: implemented code behavior from Tasks 1–6.
- Produces: active canonical language matching the code; no transient Runtime claims.

- [ ] **Step 1: Update `AGENTS.md` Alert Runtime boundary**

State exactly:

```text
HTDY uses forward-only first-seen observation semantics. Existing same-frequency completed Live / canonical_updated triggers compare only previous/current prefixes; historical repaint candidates are limited to the kernel repaint zone. AlertEvent bar_end is the observation Bar, detected_at is first-seen time. Once frozen, repaint disappearance/reappearance/direction changes do not revise or resend the Event. Startup/repair/replay/backfill/EOD recalculation do not create historical HTDY Events or notifications.
```

Do not modify SuBing continuation rules.

- [ ] **Step 2: Update `PROJECT_SOURCE.md` stable HTDY product description**

Add the same product-level fact concisely: HTDY persistent AlertEvent is forward-only first-seen; retrospective overlay may later differ because the indicator repaints.

- [ ] **Step 3: Update `DECISIONS.md` HTDY/Alert long-term decision**

Freeze these identities:

```text
bar_end = observation Bar time

detected_at = first-seen Runtime time

same identity after repaint = immutable no-op
```

Preserve the two-table / one-shot / no replay decision.

- [ ] **Step 4: Add/adjust canonical consistency assertions only for stable text/behavior contracts already covered by that test**

Do not create brittle whole-document snapshots. Prefer checks for stable Rule/Scope names and forbidden reintroduction of replay/new persistence surfaces.

- [ ] **Step 5: Run canonical and document checks**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: all pass, secret scan 0 findings.

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md PROJECT_SOURCE.md DECISIONS.md TESTING.md tests/engineering/test_canonical_consistency.py

git commit -m "docs: freeze HTDY first-seen alert contract"
```

If `TESTING.md` or the engineering test did not need changes, do not stage them.

---

### Task 8: Full verification and Lane 3 review handoff

**Files:**
- No feature expansion.
- Review the complete task-branch diff only.

**Interfaces:**
- Consumes: exact task branch head from Tasks 1–7.
- Produces: verified implementation candidate and an explicit human Gate; no release/Runtime actions.

- [ ] **Step 1: Run focused HTDY/Alert backend tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py
```

Add the MarketReadService focused test file to this command if Task 1 created or modified one.

- [ ] **Step 2: Run full non-production backend verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

- [ ] **Step 3: Run full Web verification**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

- [ ] **Step 4: Run engineering/static verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: Perform exact-head self-review against the Spec**

Verify all of the following from code/tests, not assumption:

```text
formula unchanged
Rule/Scope/audience unchanged
no migration/new table
27-bar scan uses production constant
64-bar/full-history parity proven
candidate contract belongs to observation Bar
bar_end/detected_at are distinct facts
first Event freezes later repaint revision
startup/catch-up no backfill
transport remains one-shot/no retry
D1/W1 still canonical_updated only
SuBing unchanged
STATUS.md not prematurely updated
```

- [ ] **Step 6: Open an independent Lane 3 Review session**

Review the exact branch head against:

- `STATUS.md`
- `AGENTS.md`
- `docs/DEVELOPMENT.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- this Spec and Plan

Review specifically for future-leak semantics, prefix comparison, rollover contract ownership, Event idempotency, notification one-shot behavior, and accidental Scope/Runtime changes.

- [ ] **Step 7: Stop at the develop-integration Gate**

Report:

```text
CODE_COMPLETE / TEST_COMPLETE / REVIEW_RESULT
```

and the exact commit SHA. Do not merge to `develop` until the user explicitly gives the project-required integration approval. Even after develop integration, do not merge `main`, create a tag, promote Runtime, mutate real Scope, or send a real PushPlus notification without their separate Gates.

---

## Implementation Completion Definition

The implementation task is complete only when all tests and independent Review support:

```text
允许集成 develop
```

That verdict is not release approval and not Runtime promotion approval. The first real proof remains a later, separately authorized Runtime release/promotion followed by a natural enabled `symbol × frequency` trigger; the current production `jm × 15m` Scope must not be changed just to manufacture evidence.
