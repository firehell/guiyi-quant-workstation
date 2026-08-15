# Live Channel Grace Teardown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain an existing RQData Live channel through its 60-second session-final arrival grace, then unsubscribe it exactly once and converge heartbeat state without creating idle providers.

**Architecture:** `LiveMarketService` will derive desired channels from currently `TRADING` products plus already-subscribed channels still inside a known Session's arrival grace. One private diff applicator will perform provider subscribe/unsubscribe operations atomically with respect to `_channels`; idle polling will drain and finalize Bars before applying teardown. Provider unsubscribe failures remain visible and distinct from Redis failures.

**Tech Stack:** Python 3.13, pytest, existing `LiveMarketService`, `RQDataLiveProvider`, `ProductMarketPhase`, `SessionWindow`, and Redis heartbeat contracts.

## Global Constraints

- Do not modify Canonical, `MainContractMap`, daily rank1 snapshots, after-market cleanup, Runtime health payloads, configuration, or dependencies.
- Do not create or subscribe a provider while no product is `TRADING`.
- Keep the Session arrival boundary inclusive at exactly 60 seconds; teardown starts only after it.
- Update `_channels` only after provider operations succeed.
- Do not reload or switch Runtime as part of this implementation.
- Preserve unrelated Alert V2 working-tree and index state.

---

### Task 1: Specify channel grace and teardown behavior

**Files:**
- Modify: `services/quant-api/tests/data_foundation/test_live_market.py`

**Interfaces:**
- Consumes: existing `LiveMarketService.poll(now: datetime) -> str | None`, `FakeLiveClient`, `FakePhases`, `RedisLiveStore`.
- Produces: regression tests defining inclusive grace retention, exact teardown, mixed-phase independence, and idle no-create behavior.

- [ ] **Step 1: Add an unsubscribe failure switch to the existing provider fake**

Add `fail_unsubscribe = False` in `FakeLiveClient.__init__` and make `unsubscribe()` raise `ConnectionError("provider unavailable")` before recording channels when enabled.

- [ ] **Step 2: Write the all-idle grace and exact teardown tests**

Add tests that start a one-product service in `TRADING`, change it to `CLOSED`, and assert:

```python
assert service.poll(window.end + timedelta(seconds=60)) is None
assert client.unsubscribed == []
assert heartbeat["subscribed_count"] == 1

assert service.poll(window.end + timedelta(seconds=61)) is None
assert client.unsubscribed == ["bar_J2505"]
assert heartbeat["subscribed_count"] == 0

service.poll(window.end + timedelta(seconds=62))
assert client.unsubscribed == ["bar_J2505"]
```

In the same grace setup, emit the Session-final payload before the +60-second poll and assert it is stored exactly once.

- [ ] **Step 3: Write the mixed-phase independent grace test**

Start `j` and `ag` together, close `j` while `ag` remains `TRADING`, and assert `j` stays subscribed at `j_session.end + 10 seconds`, then is the only removed channel after `j_session.end + 61 seconds`.

- [ ] **Step 4: Write the idle no-provider-creation test**

Construct `LiveMarketService` with all phases `CLOSED` and a factory that records calls. Poll once and assert the factory was never called, no channel was subscribed, and heartbeat count is zero.

- [ ] **Step 5: Write the idle unsubscribe failure and recovery test**

Start a subscribed service, close its product, enable `client.fail_unsubscribe`, poll after +61 seconds, and assert:

```python
assert service.poll(window.end + timedelta(seconds=61)) == "LIVE_PROVIDER_UNAVAILABLE"
assert service._channels == {"bar_J2505"}
assert heartbeat["subscribed_count"] == 1
assert heartbeat["available"] is False
```

Disable the failure, poll again, and assert unsubscribe succeeds, `_channels` becomes empty,
heartbeat count becomes zero, and availability returns true.

- [ ] **Step 6: Run the new behavior tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q -p no:cacheprovider \
services/quant-api/tests/data_foundation/test_live_market.py \
-k 'all_idle or mixed_phase_keeps_closed_channel_through_grace or idle_poll_does_not_create_provider or idle_unsubscribe_failure'
```

Expected: the teardown, mixed grace, and provider-specific failure assertions fail because current early returns retain or prematurely remove channels and have no idle provider-error classification; the no-provider test may already pass and serves as a guard.

---

### Task 2: Implement one grace-aware channel lifecycle

**Files:**
- Modify: `services/quant-api/app/market_data/live_market.py`
- Test: `services/quant-api/tests/data_foundation/test_live_market.py`

**Interfaces:**
- Consumes: `_channels`, `_contracts`, `_known_sessions`, `_SESSION_END_ARRIVAL_GRACE`, provider `subscribe()` and `unsubscribe()`.
- Produces: `_channels_in_session_grace(now: datetime) -> set[str]` and `_sync_provider_channels(desired: set[str], *, create_if_missing: bool) -> None`.

- [ ] **Step 1: Add grace-channel derivation**

Implement `_channels_in_session_grace()` so it returns only channels already present in `_channels` whose symbol has a known Session satisfying:

```python
window.end <= now <= window.end + _SESSION_END_ARRIVAL_GRACE
```

It must scan known Sessions by symbol and never infer a new contract or channel.

- [ ] **Step 2: Extract atomic provider channel synchronization**

Implement `_sync_provider_channels()` with these exact rules:

```python
removed = tuple(sorted(self._channels - desired))
added = tuple(sorted(desired - self._channels))
if not removed and not added:
    return
if self._provider is None and not create_if_missing:
    return
provider = self._provider_or_create()
if removed:
    provider.unsubscribe(removed)
if added:
    provider.subscribe(added)
self._channels = desired
self._provider_available = True
```

Wrap provider exceptions as `_ProviderUnavailable`; never update `_channels` on failure.

- [ ] **Step 3: Apply the rule in active reconciliation**

Keep existing rank1/trading-day resolution. Replace its inline diff with:

```python
desired = {
    f"bar_{self._contracts[symbol]}"
    for symbol in active_symbols
} | self._channels_in_session_grace(now)
self._sync_provider_channels(desired, create_if_missing=True)
```

This retains a just-closed product while another product remains active.

- [ ] **Step 4: Apply teardown after idle drain and flush**

In the all-idle `poll()` branch, preserve this ordering:

```python
self._drain_session_grace(now)
self.flush_due(now)
self._sync_provider_channels(
    self._channels_in_session_grace(now),
    create_if_missing=False,
)
self._publish_heartbeat(now, phases)
```

Catch `_ProviderUnavailable` separately, mark `_provider_available = False`, publish the unchanged channel count, and return `LIVE_PROVIDER_UNAVAILABLE`. Keep Redis exceptions classified as `LIVE_REDIS_UNAVAILABLE`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Task 1 command again. Expected: all selected tests pass.

- [ ] **Step 6: Run the complete Live Market module**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q -p no:cacheprovider \
services/quant-api/tests/data_foundation/test_live_market.py
```

Expected: all tests pass with no warnings or errors.

---

### Task 3: Full validation and self-review

**Files:**
- Verify: `services/quant-api/app/market_data/live_market.py`
- Verify: `services/quant-api/tests/data_foundation/test_live_market.py`

**Interfaces:**
- Consumes: completed Tasks 1-2.
- Produces: repository-level evidence for the scoped repair.

- [ ] **Step 1: Run the complete data-foundation test directory**

Run the current backend command from `TESTING.md`, narrowed to the affected domain:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q -p no:cacheprovider \
services/quant-api/tests/data_foundation
```

Expected: all tests pass.

- [ ] **Step 2: Run scoped Ruff and Mypy**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
services/quant-api/app/market_data/live_market.py \
services/quant-api/tests/data_foundation/test_live_market.py
```

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
services/quant-api/app/market_data/live_market.py
```

Expected: both commands exit zero.

- [ ] **Step 3: Run repository safety checks**

Run:

```bash
git diff --check
python3 scripts/engineering/secret_scan.py --json
```

Expected: diff check exits zero and secret scan reports zero findings.

- [ ] **Step 4: Review the final diff against the design**

Confirm the diff changes only the two scoped implementation/test files, except for the already-approved design and plan documents. Confirm no Runtime, launchd, Canonical, DB, Alert, or notification behavior was changed by this task.

- [ ] **Step 5: Commit only scoped files**

Stage only:

```bash
git add \
docs/superpowers/specs/2026-08-14-live-channel-grace-teardown-design.md \
docs/superpowers/plans/2026-08-14-live-channel-grace-teardown.md \
services/quant-api/app/market_data/live_market.py \
services/quant-api/tests/data_foundation/test_live_market.py
git commit -m "fix: teardown idle live channels after grace"
```

Before committing, inspect `git diff --cached --name-only`; if unrelated files are staged, use an exact pathspec commit rather than altering the other task's index.
