# HTDY Forward-Only First-Seen Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change HTDY Alert from current-bar-only evaluation to forward-only first-seen repaint detection while preserving the existing HTDY formula, Rule/Scope, AlertEvent schema, one-shot PushPlus transport, and no-backfill/no-replay boundaries.

**Architecture:** Keep the existing Alert Runtime triggers and persistence domain. Extend the Alert market-read window with per-Bar rank1 contract ownership, add a bounded HTDY prefix-diff evaluator that compares `previous_prefix` with `current_prefix`, freeze first-seen candidates into the existing `alert_events` identity, and expose the already-persisted `detected_at` truth in PushPlus/Web presentation. No migration or new subsystem is introduced.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / NumPy / pytest, Vue 3 / TypeScript / Node test runner, existing `MarketDataService`, `MarketReadService`, Alert Runtime V2, PushPlus transport.

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

Implementation stays within existing boundaries:

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
- Active canonical docs: `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`; `TESTING.md` only if commands genuinely change.

Focused tests:

- Create: `services/quant-api/tests/test_market_read_service.py`
- Modify: `services/quant-api/tests/test_alert_evaluator.py`
- Modify: `services/quant-api/tests/test_alert_service.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_alert_notification.py`
- Modify if constructor fixtures require it: `services/quant-api/tests/test_alert_notification_dispatcher.py`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify when stable contract assertions are appropriate: `tests/engineering/test_canonical_consistency.py`

---

### Task 1: Give Alert windows exact per-Bar contract ownership

**Files:**
- Modify: `services/quant-api/app/market_data/market_read_service.py`
- Create: `services/quant-api/tests/test_market_read_service.py`
- Modify fixture callers as required: `services/quant-api/tests/test_alert_runtime.py`, `services/quant-api/tests/test_alert_evaluator.py`

**Interfaces:**
- Consumes: `MarketSeriesPageResult.resolved_contract_segments`, current Live subscription contract, `CanonicalBar.trading_day`.
- Produces: `MarketReadWindow.bar_contracts: tuple[str, ...]`, aligned 1:1 with `MarketReadWindow.bars`; invariant `bar_contracts[-1] == contract` for the latest Bar.

- [ ] **Step 1: Write the failing historical/Live ownership tests**

Create `services/quant-api/tests/test_market_read_service.py`. Build a fake `MarketPageReader`, phase reader and live store around the real `MarketReadService`. Use an actual-dominant historical page with two resolved contract segments and a current Live Bar.

Assert exact alignment:

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

Add a second test where a historical Bar is owned by `JM2701` while the same `bar_end` arrives from Live under subscription `JM2705`. Expected:

```python
with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
    service.bars_until(...)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py
```

Expected: failure because `MarketReadWindow` has no `bar_contracts` and duplicate ownership disagreement is not yet rejected.

- [ ] **Step 3: Extend `MarketReadWindow` with aligned ownership**

Add:

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

Import `ResolvedContractSegment` into `market_read_service.py` and add a single helper:

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

In `bars_until`:

1. retain the complete `MarketSeriesPageResult` instead of immediately discarding it to `.bars`;
2. derive each Historical Bar owner from `resolved_contract_segments`;
3. assign every accepted Live Bar to the validated current subscription contract;
4. when Historical and Live contain the same `bar_end`, require both Bar value equality under the existing dedupe contract **and** owner equality; ownership disagreement fails closed;
5. sort and truncate bars and owners together;
6. require final lengths to match and final owner to equal the existing singular `window.contract`.

In `latest_canonical_window`, derive `bar_contracts` for every returned canonical Bar from its page `resolved_contract_segments` and keep the existing latest singular `contract` compatibility field.

- [ ] **Step 4: Run Task 1 tests and confirm GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py
```

Update fake `MarketReadWindow` builders in existing tests with a real aligned `bar_contracts` tuple; do not introduce an empty/default ownership value.

- [ ] **Step 5: Commit Task 1**

```bash
git add \
  services/quant-api/app/market_data/market_read_service.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py

git commit -m "feat: preserve alert bar contract ownership"
```

---

### Task 2: Add bounded HTDY prefix-diff first-seen evaluation

**Files:**
- Modify: `services/quant-api/app/alerts/evaluators.py`
- Modify: `services/quant-api/tests/test_alert_evaluator.py`

**Interfaces:**
- Consumes: `MarketReadWindow.bars`, `MarketReadWindow.bar_contracts`, production `CONFIGURED_REPAINT_SCAN_ZONE_BARS`.
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
        self,
        window: MarketReadWindow,
    ) -> tuple[HtdyFirstSeenObservation, ...]: ...
```

Keep `evaluate()` as the current-Bar compatibility primitive.

- [ ] **Step 1: Write RED tests for current-Bar and historical empty→observation**

Monkeypatch `compute_htdy_original` with controlled arrays. Prove a latest-Bar sell returns:

```python
assert evaluator.evaluate_first_seen(window) == (
    HtdyFirstSeenObservation(
        bar_end=window.bars[-1].bar_end,
        trading_day=window.bars[-1].trading_day,
        contract=window.bar_contracts[-1],
        observation_types=("sell",),
    ),
)
```

Then append one Bar and make an old overlapping Bar change from empty to sell. Assert the candidate uses that old Bar's `bar_end`, `trading_day`, and `bar_contracts[index]`, not the trigger Bar's contract.

- [ ] **Step 2: Write RED tests for transition rules**

Test the pure prefix transition behavior:

```text
sell -> empty      => no candidate
buy  -> sell       => no candidate
sell -> buy        => no candidate
buy  -> buy+sell   => no candidate
empty -> buy+sell  => one candidate with ("buy", "sell")
```

Do not add a stateful evaluator ledger. A later `sell -> empty -> sell` prefix can surface again at the evaluator layer; Task 3's immutable Event identity is the authoritative first-seen dedupe.

- [ ] **Step 3: Run evaluator tests and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py
```

Expected: missing `HtDyFirstSeenObservation` / `evaluate_first_seen`.

- [ ] **Step 4: Implement the minimal pure evaluator**

Use:

```python
CURRENT_BAR_CONTEXT_BARS = 32
HTDY_FIRST_SEEN_CONTEXT_BARS = 64
```

Import the production repaint authority rather than duplicating 27:

```python
from guiyi_quant.indicators.htdy_original import (
    CONFIGURED_REPAINT_SCAN_ZONE_BARS,
)
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

    return self._prefix_diff_candidates(
        bars=bars,
        contracts=contracts,
        previous=previous,
        current=current,
        scan_bars=CONFIGURED_REPAINT_SCAN_ZONE_BARS,
    )
```

`_prefix_diff_candidates` must:

- include the current newest Bar when its current observation tuple is non-empty;
- compare only overlapping previous Bars within the last 27 previous-Bar positions;
- emit only prior empty -> current non-empty;
- return candidates sorted by `bar_end`;
- require `len(bars) == len(contracts)` and fail closed otherwise.

- [ ] **Step 5: Prove 64-Bar bounded parity against full history**

Use the real production kernel. Generate a deterministic long series and iterate multiple append cutoffs. For each cutoff:

1. calculate previous/full history and current/full history;
2. derive full-history first-seen candidates restricted to the same last-27 previous-Bar scan plus latest Bar;
3. call production `evaluate_first_seen()` on the last 64 Bars with aligned contracts;
4. compare exact candidate `bar_end` + result tuples.

Assertion:

```python
assert bounded_candidates == full_history_candidates
```

Cover transitions at both edges of the 27-Bar scan zone. If this test fails, stop and increase/reason about context length; do not weaken the test or retain 64 by assumption.

- [ ] **Step 6: Prove 32–63 Bar compatibility**

For each representative length `32`, `40`, `63`, prove:

- a current latest-Bar observation can still be returned;
- an old repaint transition is not scanned before the 64-Bar context threshold.

- [ ] **Step 7: Run evaluator tests and confirm GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py
```

- [ ] **Step 8: Commit Task 2**

```bash
git add \
  services/quant-api/app/alerts/evaluators.py \
  services/quant-api/tests/test_alert_evaluator.py

git commit -m "feat: detect HTDY first-seen repaint observations"
```

---

### Task 3: Freeze HTDY first-seen Event identity without direction drift failures

**Files:**
- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/tests/test_alert_service.py`

**Interfaces:**
- Consumes: existing `AlertEventCreate` and HTDY indicator-observation unique identity.
- Produces:

```python
def create_first_seen_observation_event(
    self,
    request: AlertEventCreate,
) -> AlertEvent | None:
    ...
```

SuBing Strategy Action persistence remains on the existing strict path.

- [ ] **Step 1: Write RED tests for first create and repaint no-op**

Add to `test_alert_service.py`:

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
assert stored is not None
assert stored.result_codes == ["sell"]
assert _utc(stored.detected_at) == FIRST_DETECTED_AT
```

Also assert a later `("buy", "sell")` request for the same HTDY identity is a no-op, not `AlertConsistencyError`.

- [ ] **Step 2: Write a Strategy Action non-regression test**

Using the existing SuBing fixtures, create one Strategy Action Event through `create_event`, then submit the same action identity with changed immutable facts. Keep the existing expected `AlertConsistencyError`.

- [ ] **Step 3: Run service tests and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_service.py
```

- [ ] **Step 4: Implement indicator-only first-seen persistence**

`create_first_seen_observation_event()` must:

1. resolve the Rule and require `AlertRuleKind.INDICATOR_OBSERVATION`;
2. validate symbol, contract, trading day, frequency, aware times and HTDY result codes with the same validation rules as `create_event`;
3. query `(rule_id, symbol, frequency, bar_end)` before insert;
4. if an existing valid indicator Event exists, return `None` without comparing later repaint `result_codes`, `contract`, or detection time for rewrite purposes;
5. if not, insert and commit the immutable initial facts;
6. on an insert race/`IntegrityError`, rollback, read back the same indicator identity, return `None` if it now exists, otherwise raise `AlertEventPersistenceError`;
7. never route Strategy Action Events through this relaxed first-seen method.

Do not loosen the existing `create_event()` Strategy Action consistency contract.

- [ ] **Step 5: Run service tests and confirm GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_service.py
```

- [ ] **Step 6: Commit Task 3**

```bash
git add \
  services/quant-api/app/alerts/service.py \
  services/quant-api/tests/test_alert_service.py

git commit -m "feat: freeze HTDY first-seen alert events"
```

---

### Task 4: Wire zero-or-many first-seen candidates into Alert Runtime

**Files:**
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`

**Interfaces:**
- Consumes: `AlertEvaluator.evaluate_first_seen()`, `AlertService.create_first_seen_observation_event()`.
- Produces: deterministic zero-or-many HTDY Event/messages from one existing trigger.

- [ ] **Step 1: Write RED intraday Runtime tests**

Cover all of these exact outcomes:

```text
Scope OFF                       -> no MarketRead, no evaluator, no Event/send
current Bar first-seen          -> one Event/send
old Bar empty→sell              -> Event.bar_end == old observation time
                                  Event.detected_at == processing_now
                                  Event.contract == old Bar owner
multiple candidates             -> Event/message order by observation bar_end
existing Event after reappearance -> no Event/send and no processing failure
```

- [ ] **Step 2: Write RED startup/drain tests**

Prove current startup semantics stay zero-write:

```python
runtime.process_message(channel, payload, emit_events=False)
assert _event_rows(session) == []
assert sender.messages == []
```

Then process one genuinely new completed Bar. If a historical observation already existed in the previous prefix, it must not be emitted merely because Runtime just restarted.

- [ ] **Step 3: Write RED D1/W1 canonical tests**

Keep `market:state(reason=canonical_updated)` as the only D1/W1 trigger. Provide a 64-Bar canonical `MarketReadWindow` with aligned `bar_contracts`; make one old Bar transition empty→sell and assert one immutable first-seen Event. Also retain tests that D1/W1 live channels are rejected.

- [ ] **Step 4: Run Runtime tests and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 5: Replace HTDY single-result flow with candidate iteration**

Leave SuBing Strategy flow intact. For HTDY:

```python
candidates = self._htdy_evaluator.evaluate_first_seen(window)
for candidate in candidates:
    prepared = _persist_first_seen_htdy_and_prepare_notification(
        service,
        taxonomy=self._taxonomy,
        rule=rule,
        symbol=symbol,
        frequency=event_frequency.value,
        candidate=candidate,
        processing_now=processing_now,
    )
```

The Event request uses the candidate's observation facts:

```python
AlertEventCreate(
    rule_id=rule.id,
    symbol=symbol,
    contract=candidate.contract,
    trading_day=candidate.trading_day,
    frequency=frequency,
    bar_end=candidate.bar_end,
    result_codes=candidate.observation_types,
    action_id=None,
    strategy_payload=None,
    detected_at=processing_now,
    notification_attempted_at=processing_now,
)
```

Call `service.create_first_seen_observation_event()` rather than generic strict indicator persistence.

For D1/W1 use the pair frequency and the candidate's own observation Bar contract/trading day/time. Keep existing per-pair exception isolation.

- [ ] **Step 6: Increase only HTDY Alert windows from 32 to 64**

Change HTDY intraday `bars_until(... limit=64)` and D1/W1 `latest_canonical_window(... limit=64)`. Do not change SuBing reads or strategy warm-up.

- [ ] **Step 7: Preserve Runtime status meaning**

Keep:

- `last_event_at`: processing time when at least one **new Event** was created;
- `last_processed_bar_at`: incoming intraday trigger Bar time;
- `last_transport_attempt_at`: transport attempt processing time;
- `last_provider_accepted_at`: provider acceptance processing time.

Do not replace any of these with historical observation `bar_end`.

- [ ] **Step 8: Run Runtime tests and confirm GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 9: Commit Task 4**

```bash
git add \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/tests/test_alert_runtime.py

git commit -m "feat: emit HTDY first-seen repaint alerts"
```

---

### Task 5: Render observation time and first-seen time in PushPlus

**Files:**
- Modify: `services/quant-api/app/alerts/notification.py`
- Modify: `services/quant-api/tests/test_alert_notification.py`
- Modify if constructor fixtures require it: `services/quant-api/tests/test_alert_notification_dispatcher.py`
- Modify message construction tests/callers only as required by the new mandatory field.

**Interfaces:**
- Consumes: candidate/Event `bar_end` and Runtime processing `detected_at`.
- Produces: `AlertNotificationMessage.detected_at` and exact HTDY copy.

- [ ] **Step 1: Write RED HTDY formatting tests**

Create:

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

Assert exact lines:

```text
观察K线：15m · 09:45
首次识别：10:15
```

Also add a current-Bar case where observation and detection are the same instant.

- [ ] **Step 2: Run notification tests and confirm RED**

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

Every runtime message constructor passes `processing_now`/Event detection time. SuBing must receive the required field but keep its existing rendered copy unchanged.

In `_format_htdy_message`:

```python
observation_time = message.bar_end.astimezone(_SHANGHAI).strftime("%H:%M")
first_seen_time = message.detected_at.astimezone(_SHANGHAI).strftime("%H:%M")
```

Render:

```python
return (
    f"【归一量化】{message.symbol.strip().upper()} {message.product_name.strip()}\n\n"
    f"火天大有 · {observation}\n"
    f"主力：{message.contract.strip().upper()}\n"
    f"观察K线：{message.frequency} · {observation_time}\n"
    f"首次识别：{first_seen_time}\n"
    "研究观察，非交易指令"
)
```

Require both timestamps to be timezone-aware.

- [ ] **Step 4: Run notification tests and confirm GREEN**

Use Step 2 command.

- [ ] **Step 5: Re-run Runtime tests because message construction changed**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 6: Commit Task 5**

```bash
git add \
  services/quant-api/app/alerts/notification.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py \
  services/quant-api/tests/test_alert_runtime.py

git commit -m "feat: show HTDY first-seen notification time"
```

If a listed test file was not modified, omit it from staging.

---

### Task 6: Make the persistent Web marker explicitly first-seen

**Files:**
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts`

**Interfaces:**
- Consumes: existing `HtdyAlertEvent.detected_at`, `bar_end`, `contract`, `result_codes`.
- Produces: unchanged persistent square identity/shape/time with a truthful tooltip.

- [ ] **Step 1: Write RED Web test for observation/detection time distinction**

Build an HTDY Event fixture with different `bar_end` and `detected_at`, call `alertEventsToMarkers()`, and assert:

```ts
const [marker] = alertEventsToMarkers([event])
assert.equal(marker.shape, 'square')
assert.equal(marker.time, event.bar_end)
assert.match(marker.tooltip, /实时首次识别/)
assert.match(marker.tooltip, /观察K线/)
assert.match(marker.tooltip, /首次识别/)
```

Retain a separate test for the retrospective HTDY arrow's existing repaint-risk tooltip and non-Alert identity.

- [ ] **Step 2: Run the exact Node focused test and confirm RED**

```bash
pnpm --dir apps/quant-web exec node --test tests/alerts.test.ts
```

Expected: persistent tooltip lacks first-seen language/times.

- [ ] **Step 3: Update only the persistent marker tooltip**

Keep these fields unchanged:

```ts
id: `alert:${alertEventIdentityKey(event)}`
time: event.bar_end
position: 'aboveBar'
shape: 'square'
```

Use an existing shared formatter if one already fits this UI. Otherwise add a tiny local formatter in `alertMarkers.ts`, for example:

```ts
function shanghaiHm(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}
```

Persistent tooltip semantics:

```text
实时首次识别 · 持久 AlertEvent · JM2701 · 卖出观察 · 观察K线 09:45 · 首次识别 10:15
```

Do not hide a persistent Event because the current retrospective repaint calculation later differs.

- [ ] **Step 4: Run Web focused tests and Alert ownership check**

```bash
pnpm --dir apps/quant-web exec node --test tests/alerts.test.ts
pnpm --dir apps/quant-web run check:alert-rules
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add \
  apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/tests/alerts.test.ts

git commit -m "feat(web): clarify HTDY first-seen alert markers"
```

---

### Task 7: Synchronize active canonical contracts

**Files:**
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify only if validation commands genuinely change: `TESTING.md`
- Modify when stable guard coverage belongs there: `tests/engineering/test_canonical_consistency.py`

**Interfaces:**
- Consumes: implemented behavior from Tasks 1–6.
- Produces: active canonical wording matching code, without transient Runtime claims.

- [ ] **Step 1: Update `AGENTS.md` Alert Runtime boundary**

Record this semantic contract without changing SuBing rules:

```text
HTDY uses forward-only first-seen observation semantics. Existing same-frequency completed Live / canonical_updated triggers compare only previous/current prefixes; historical repaint candidates are limited to the kernel repaint zone. AlertEvent bar_end is the observation Bar and detected_at is first-seen time. Once frozen, repaint disappearance/reappearance/direction changes do not revise or resend the Event. Startup/repair/replay/backfill/EOD recalculation do not create historical HTDY Events or notifications.
```

- [ ] **Step 2: Update `PROJECT_SOURCE.md` HTDY stable product description**

State concisely that persistent HTDY AlertEvent is a forward-only first-seen fact while the retrospective Web overlay can later differ because the indicator repaints.

- [ ] **Step 3: Update `DECISIONS.md` long-term HTDY/Alert identity**

Freeze:

```text
bar_end = observation Bar time

detected_at = first-seen Runtime time

same HTDY Event identity after repaint = immutable no-op
```

Retain the two-table, commit-first, one-shot, no-replay/no-retry decision.

- [ ] **Step 4: Add a narrow canonical-consistency guard only if it protects a durable invariant**

Appropriate checks include:

- Rule code remains `htdy_original_15m`;
- HTDY Scope authority remains `scope_product_frequencies`;
- no new active Alert persistence table is referenced;
- replay/backfill remains forbidden.

Do not snapshot whole documents.

- [ ] **Step 5: Run canonical/document validation**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: all pass, secret scan reports zero findings.

- [ ] **Step 6: Commit Task 7**

```bash
git add AGENTS.md PROJECT_SOURCE.md DECISIONS.md
```

Add `TESTING.md` and/or `tests/engineering/test_canonical_consistency.py` only if they actually changed, then:

```bash
git commit -m "docs: freeze HTDY first-seen alert contract"
```

Do not modify `STATUS.md` in this task.

---

### Task 8: Full verification and Lane 3 review handoff

**Files:**
- No feature expansion.
- Review the complete task-branch diff only.

**Interfaces:**
- Consumes: exact implementation branch head from Tasks 1–7.
- Produces: verified implementation candidate and an explicit human Gate; no release/Runtime actions.

- [ ] **Step 1: Run focused HTDY/Alert backend tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py
```

- [ ] **Step 2: Run the full non-production backend suite**

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

- [ ] **Step 3: Run the full Web suite**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

- [ ] **Step 4: Run engineering/static verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: Perform exact-head self-review against the Spec**

Verify from code/tests, not assumption:

```text
HTDY formula unchanged
indicator/rule identity unchanged
Scope/audience/Topic unchanged
no Alembic migration/new table
27-bar scan uses production kernel constant
64-bar/full-history parity is proven
candidate contract belongs to observation Bar
bar_end and detected_at are distinct facts
first Event freezes later repaint revisions
startup/catch-up do not backfill
transport remains one-shot/no retry/no replay
D1/W1 still canonical_updated only
SuBing behavior unchanged
STATUS.md not prematurely updated
```

- [ ] **Step 6: Push the implementation branch and open a PR to `develop`**

The PR description must state:

- exact implementation head SHA;
- Spec and Plan paths;
- focused/full test results;
- no production DB/Scope/Redis/PushPlus/Runtime/main/tag operation occurred;
- Lane 3 independent Review still required before integration.

Do not enable auto-merge.

- [ ] **Step 7: Open a fresh independent Lane 3 Review session**

Review the exact PR head against:

- `STATUS.md`
- `AGENTS.md`
- `docs/DEVELOPMENT.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- `docs/superpowers/specs/2026-08-31-htdy-first-seen-alert-design.md`
- `docs/superpowers/plans/2026-08-31-htdy-first-seen-alert.md`

Review specifically for centered-XMA future dependency, prefix-diff correctness, 27/64 boundaries, rank1 rollover ownership, Event idempotency, one-shot notification behavior, startup backfill prevention, and accidental Scope/Runtime changes.

- [ ] **Step 8: Stop at the human develop-integration Gate**

Report:

```text
CODE_COMPLETE
TEST_COMPLETE
REVIEW_RESULT=<independent review verdict>
HEAD=<exact SHA>
```

The only successful integration verdict at this stage is:

```text
允许集成 develop
```

Do not merge the PR until the user explicitly gives that approval. After integration, do not merge `main`, create a tag, promote Runtime, mutate real Scope, acknowledge production state, or send real PushPlus without separate explicit Gates.

---

## Implementation Completion Definition

The implementation branch is ready for the project integration Gate only when all of these hold:

```text
formula unchanged
Rule/Scope/audience unchanged
no migration/new persistence domain
forward-only previous/current prefix diff
27-bar repaint scan
64-bar bounded parity proven
per-Bar rank1 contract ownership proven
immutable first-seen AlertEvent/no retraction
no startup backfill/replay/retry
bar_end = observation time
detected_at = first-seen time
Web retrospective arrow and persistent Event square remain distinct
SuBing unchanged
full verification passes
independent Lane 3 Review passes
```

This does not authorize release or Runtime promotion. The first real evidence remains a later separately approved release/Runtime promotion followed by a natural enabled `symbol × frequency` trigger; the production `jm × 15m` Scope must not be changed merely to manufacture evidence.
