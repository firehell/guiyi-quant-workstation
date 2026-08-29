# SuBing History Window Isolation and Snapshot Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 向左拖 15m 真实主力时 Canonical 翻页不被苏冰 `/history` 拖死；`through` 与效果快照一致时 `/history` 只过滤快照，不重放 1m。

**Architecture:** 后端在 `history()` 入口只读 `SubingStrategyPerformanceSnapshotQuery.current`；`through` 相同且 `since` 落在覆盖范围内则切片 Episode/Action 并 `cache_state=hit`。前端 prepend 防抖 400ms、Abort 单飞，失败保留已有标签。GET 仍 `publish_cache=False`。

**Tech Stack:** FastAPI sync route, pytest, Vue 3 composable, axios, node:test.

**Spec:** `docs/superpowers/specs/2026-08-29-subing-history-window-cache-design.md`

## Global Constraints

- 不加 worker，不加长 `bars/page` 30s 超时。
- HTTP GET `/history` 保持 `publish_cache=False`。
- 不改策略公式、lifecycle、fill_basis、exit 语义。
- 主图继续只调 `/history`，不改去调 `/performance`。
- 禁止用更新的 `coverage_through` 回答更早的 `through`（防未来平仓泄漏）。
- 不改 Alert、Runtime、Canonical、OpenSpec。
- Commits only when the user explicitly asks; skip commit steps unless authorized in-session.

---

## File map

| File | Role |
|------|------|
| `services/quant-api/app/market_data/subing_strategy/history_snapshot_slice.py` | 纯函数：快照 → 窗口化 HistoricalProjection 或 `None` |
| `services/quant-api/tests/data_foundation/test_subing_strategy_history_snapshot_slice.py` | 切片命中、过滤、through 不匹配不切片 |
| `services/quant-api/app/market_data/subing_strategy/service.py` | `history()` 先切片，失败再 replay；可选 `snapshot_query` |
| `services/quant-api/app/market_data/composition.py` | 只读注入 snapshot query |
| `services/quant-api/tests/data_foundation/test_subing_strategy_service.py` | 切片命中不装载 1m、不 replay |
| `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts` | 400ms prepend 防抖、Abort 单飞、abort 不写黄条 |
| `apps/quant-web/src/api/market.ts` | `getSubingStrategyHistory` 传 `signal` |
| `apps/quant-web/tests/historicalResearchMarkers.test.ts` | 防抖合并、abort 不覆盖 marker |
| `apps/quant-web/tests/marketOverlayConvergence.test.ts` | 合同：timeout 120s + signal |

---

### Task 1: Snapshot slice pure function

**Files:**
- Create: `services/quant-api/app/market_data/subing_strategy/history_snapshot_slice.py`
- Test: `services/quant-api/tests/data_foundation/test_subing_strategy_history_snapshot_slice.py`

**Interfaces:**
- Consumes: `SubingStrategyHistoricalRequest`, `SubingStrategyPerformanceProjection`, `SubingStrategyPolicy`, `_episode_intersects` from `service.py`
- Produces: `try_slice_history_from_snapshot(request, snapshot, *, policy, engine_identity_sha256) -> SubingStrategyHistoricalProjection | None`

- [ ] **Step 1: Write the failing tests**

Create `services/quant-api/tests/data_foundation/test_subing_strategy_history_snapshot_slice.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
)
from app.market_data.subing_strategy.history_snapshot_slice import (
    try_slice_history_from_snapshot,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
    summarize_subing_strategy_episodes,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_strategy.service import SubingStrategyHistoricalRequest

from research.subing_strategy_fixtures import action_fixture


def _closed(entry_day: date, exit_day: date, tag: str) -> SubingStrategyEpisode:
    entry = replace(
        action_fixture(
            kind=SubingStrategyActionKind.OPEN_LONG,
            episode_id=f"subing-episode:{tag}",
        ),
        trading_day=entry_day,
        action_id=f"subing-action:{tag}:entry",
        episode_id=f"subing-episode:{tag}",
        opportunity_id=f"subing-opportunity:{tag}",
    )
    exit_action = replace(
        action_fixture(
            kind=SubingStrategyActionKind.CLOSE_LONG,
            episode_id=entry.episode_id,
        ),
        trading_day=exit_day,
        action_id=f"subing-action:{tag}:exit",
        episode_id=entry.episode_id,
        opportunity_id=entry.opportunity_id,
    )
    return SubingStrategyEpisode(
        episode_id=entry.episode_id,
        direction=SubingDirection.LONG,
        entry_action=entry,
        exit_action=exit_action,
        state=SubingStrategyEpisodeState.CLOSED,
        holding_bar_count=2,
        reference_change_percent=Decimal("1"),
        current_reference_change_percent=None,
        latest_reference_price=None,
        exit_reason_codes=exit_action.reason_codes,
        structure_exit_available=False,
    )


def _snapshot(*, since: date, through: date, episodes: tuple[SubingStrategyEpisode, ...]):
    return SubingStrategyPerformanceProjection(
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M15,
        coverage_since=since,
        coverage_through=through,
        resolved_cutoff=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
        segment_count=2,
        bar_count_15m=20186,
        context_unavailable_count=0,
        cache_state="hit",
        summary=summarize_subing_strategy_episodes(episodes),
        episodes=episodes,
    )


def _request(since: date, through: date) -> SubingStrategyHistoricalRequest:
    return SubingStrategyHistoricalRequest(
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        symbol="jm",
        frequency=BarFrequency.M15,
        since=since,
        through=through,
    )


def test_same_through_earlier_since_filters_actions_and_episodes() -> None:
    june = _closed(date(2026, 6, 4), date(2026, 6, 4), "june")
    july = _closed(date(2026, 7, 10), date(2026, 7, 13), "july")
    snapshot = _snapshot(
        since=date(2024, 1, 1),
        through=date(2026, 8, 28),
        episodes=(june, july),
    )
    policy = load_subing_strategy_policy()

    sliced = try_slice_history_from_snapshot(
        _request(date(2026, 6, 15), date(2026, 8, 28)),
        snapshot,
        policy=policy,
        engine_identity_sha256="a" * 64,
    )

    assert sliced is not None
    assert sliced.cache_state == "hit"
    assert sliced.segment_summaries == ()
    assert sliced.context_unavailable == ()
    assert sliced.resolved_cutoff == snapshot.resolved_cutoff
    assert [episode.episode_id for episode in sliced.episodes] == ["subing-episode:july"]
    assert [action.action_id for action in sliced.actions] == [
        "subing-action:july:entry",
        "subing-action:july:exit",
    ]


def test_since_before_coverage_or_earlier_through_does_not_slice() -> None:
    snapshot = _snapshot(
        since=date(2026, 1, 1),
        through=date(2026, 8, 28),
        episodes=(_closed(date(2026, 6, 4), date(2026, 6, 4), "june"),),
    )
    policy = load_subing_strategy_policy()
    kwargs = {"snapshot": snapshot, "policy": policy, "engine_identity_sha256": None}

    assert try_slice_history_from_snapshot(
        _request(date(2025, 12, 1), date(2026, 8, 28)),
        **kwargs,
    ) is None
    assert try_slice_history_from_snapshot(
        _request(date(2026, 6, 1), date(2026, 8, 11)),
        **kwargs,
    ) is None
```

If `action_fixture` + `replace` rejects duplicate/identity fields, keep the same calendar-day filtering semantics and adjust fixture fields until Episode construction is valid; do not weaken assertions on `cache_state`, empty summaries, or the two `None` cases.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_history_snapshot_slice.py
```

Expected: FAIL with `ModuleNotFoundError` for `history_snapshot_slice`.

- [ ] **Step 3: Implement the slice function**

Create `services/quant-api/app/market_data/subing_strategy/history_snapshot_slice.py`. Import `_episode_intersects` from `service.py` (do not import this module from `service.py` at module top level).

```python
from __future__ import annotations

from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
)
from app.market_data.subing_strategy.policy import SubingStrategyPolicy
from app.market_data.subing_strategy.service import (
    SubingStrategyHistoricalProjection,
    SubingStrategyHistoricalRequest,
    _episode_intersects,
)


def try_slice_history_from_snapshot(
    request: SubingStrategyHistoricalRequest,
    snapshot: SubingStrategyPerformanceProjection,
    *,
    policy: SubingStrategyPolicy,
    engine_identity_sha256: str | None,
) -> SubingStrategyHistoricalProjection | None:
    if (
        snapshot.symbol != request.symbol
        or snapshot.series_kind != request.series_kind
        or snapshot.frequency != request.frequency
        or snapshot.coverage_through != request.through
        or request.since < snapshot.coverage_since
        or snapshot.strategy_id != policy.strategy_id
        or snapshot.formula_version != policy.formula_version
    ):
        return None
    episodes = tuple(
        episode
        for episode in snapshot.episodes
        if _episode_intersects(episode, request=request)
    )
    actions = tuple(
        sorted(
            (
                action
                for episode in episodes
                for action in (episode.entry_action, episode.exit_action)
                if action is not None
                and request.since <= action.trading_day <= request.through
            ),
            key=lambda action: (action.effective_bar_end, action.action_id),
        )
    )
    return SubingStrategyHistoricalProjection(
        request=request,
        policy=policy,
        resolved_cutoff=snapshot.resolved_cutoff,
        segment_summaries=(),
        actions=actions,
        episodes=episodes,
        context_unavailable=(),
        cache_state="hit",
        engine_identity_sha256=engine_identity_sha256,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command as Step 2.

Expected: PASS.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add services/quant-api/app/market_data/subing_strategy/history_snapshot_slice.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_history_snapshot_slice.py
git commit -m "$(cat <<'EOF'
Add SuBing history snapshot window slice.

EOF
)"
```

---

### Task 2: history() uses snapshot before replay

**Files:**
- Modify: `services/quant-api/app/market_data/subing_strategy/service.py` (`SubingStrategyHistoricalProjectionService.__init__` and `history`)
- Modify: `services/quant-api/app/market_data/composition.py` (`build_subing_strategy_historical_service`)
- Test: `services/quant-api/tests/data_foundation/test_subing_strategy_service.py`
- Keep: `services/quant-api/tests/test_market_research_overlays_api.py` (`publish_cache_calls == [False]`)

**Interfaces:**
- Consumes: `try_slice_history_from_snapshot` from Task 1; `SubingStrategyPerformanceSnapshotQuery.current(symbol: str) -> SubingStrategyPerformanceProjection`
- Produces: `history(request, *, publish_cache: bool = False)` returns snapshot slice when eligible, otherwise existing replay. GET still passes `publish_cache=False`.

- [ ] **Step 1: Write the failing service test**

In `services/quant-api/tests/data_foundation/test_subing_strategy_service.py`, add (reuse Task 1 episode/snapshot helpers inline or import them if you extract a shared test fixture; do not call replay):

```python
def test_history_uses_matching_snapshot_without_loading_or_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.market_data.subing_strategy.performance_snapshot import (
        SubingStrategyPerformanceSnapshotError,
    )
    from app.market_data.subing_strategy.history_snapshot_slice import (
        try_slice_history_from_snapshot,
    )
    # Build the same june/july snapshot as Task 1, coverage through 2026-08-28.

    class BoomLoader:
        def load(self, **_kwargs):
            raise AssertionError("snapshot hit must not load 1m/5m/15m")

        def sessions(self, **_kwargs):
            raise AssertionError("snapshot hit must not load sessions")

    class SnapshotQuery:
        def current(self, symbol: str):
            assert symbol == "jm"
            return snapshot

    monkeypatch.setattr(
        "app.market_data.subing_strategy.service.replay_subing_strategy_segment",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not replay")),
    )
    service = SubingStrategyHistoricalProjectionService(
        BoomLoader(),
        products=("jm",),
        direction_context_resolver=FakeDirectionContextResolver({}),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        snapshot_query=SnapshotQuery(),
    )

    result = service.history(
        _request(since=date(2026, 6, 15), through=date(2026, 8, 28)),
        publish_cache=False,
    )
    assert result.cache_state == "hit"
    assert result.actions  # july only


def test_history_replays_when_request_through_is_older_than_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # snapshot.coverage_through = 2026-08-28
    # request.through = 2026-08-11
    # FakeSegmentLoader + replay stub as in existing tests; snapshot_query.current returns snapshot.
    # Assert replay_subing_strategy_segment was called (or loader.load was called).
```

Also add: snapshot `current()` raising `SubingStrategyPerformanceSnapshotError` falls through to existing replay (loader is used).

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  -k "snapshot"
```

Expected: FAIL (`snapshot_query` unexpected keyword, or history still hits BoomLoader).

- [ ] **Step 3: Wire snapshot_query into the service and composition**

In `SubingStrategyHistoricalProjectionService.__init__`, add optional `snapshot_query=None` and `self._snapshot_query = snapshot_query`.

At the start of `history()`, after product/request checks and **before** `self._segment_loader.load`:

```python
        if self._snapshot_query is not None:
            from app.market_data.subing_strategy.history_snapshot_slice import (
                try_slice_history_from_snapshot,
            )
            from app.market_data.subing_strategy.performance_snapshot import (
                SubingStrategyPerformanceSnapshotError,
            )
            try:
                snapshot = self._snapshot_query.current(request.symbol)
            except SubingStrategyPerformanceSnapshotError:
                snapshot = None
            except Exception:
                snapshot = None
            if snapshot is not None:
                sliced = try_slice_history_from_snapshot(
                    request,
                    snapshot,
                    policy=self._strategy_policy,
                    engine_identity_sha256=self._engine_identity_sha256,
                )
                if sliced is not None:
                    return sliced
```

Do **not** catch `Exception` if existing code prefers fail-closed on unexpected errors; then only `SubingStrategyPerformanceSnapshotError` (and `SubingStrategyPerformanceError` if `current` can raise it for invalid product — that should still propagate for unknown symbols). Prefer:

```python
            except SubingStrategyPerformanceSnapshotError:
                snapshot = None
```

Unknown product already raises `SubingStrategyActiveProductError` before this block.

In `build_subing_strategy_historical_service`, pass:

```python
        snapshot_query=build_subing_strategy_performance_snapshot_query(session),
```

`publish_cache` is ignored on the slice path (no write). Replay path unchanged.

- [ ] **Step 4: Run service + HTTP contract tests**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_history_snapshot_slice.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  -k "subing_strategy_history or snapshot"
```

Expected: PASS, including `publish_cache_calls == [False]`.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add services/quant-api/app/market_data/subing_strategy/service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py
git commit -m "$(cat <<'EOF'
Serve windowed SuBing history from the performance snapshot when through matches.

EOF
)"
```

---

### Task 3: Frontend debounce, abort, and history signal

**Files:**
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/src/api/market.ts` (`getSubingStrategyHistory`)
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Modify: `apps/quant-web/tests/marketOverlayConvergence.test.ts`
- Do not change `chart.vue` mutation wiring except if TypeScript requires the two-argument fetch (passing `getSubingStrategyHistory` remains valid).

**Interfaces:**
- Consumes: existing `sync(identity, bars, coverage, mutation)`
- Produces: `Dependencies.fetchSubingStrategy(request, signal?: AbortSignal)`; `debounceMs?: number` default `400`; prepend coalesces; abort/cancel does not set `HISTORICAL_RESEARCH_UNAVAILABLE`.

- [ ] **Step 1: Write the failing frontend tests**

In `historicalResearchMarkers.test.ts`:

1. Pass `{ debounceMs: 0 }` into **every** existing `useHistoricalResearchMarkers({ fetchSubingStrategy })` so current prepend tests stay synchronous.
2. Add:

```ts
test('prepend debounce coalesces to one history request with latest through', async () => {
  const requests: Array<Record<string, string>> = []
  const later = { time: '2026-08-20T01:05:00Z', trading_day: '2026-08-20', physicalContract: 'JM2701', open: 100, high: 101, low: 99, close: 100, volume: 10 }
  const mid = { ...later, time: '2026-07-01T01:05:00Z', trading_day: '2026-07-01' }
  const early = { ...later, time: '2026-06-01T01:05:00Z', trading_day: '2026-06-01' }
  const controller = useHistoricalResearchMarkers({
    debounceMs: 20,
    fetchSubingStrategy: async (request) => {
      requests.push({ ...request })
      return strategyResponse(request.symbol, request.since, request.through)
    },
  })
  const identity = { overlay: 'subing' as const, seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
  await controller.sync(identity, [later], { start: later.time, end: later.time }, 'replace')
  const p1 = controller.sync(identity, [mid, later], { start: mid.time, end: later.time }, 'prepend')
  const p2 = controller.sync(identity, [early, mid, later], { start: early.time, end: later.time }, 'prepend')
  await Promise.all([p1, p2])
  assert.deepEqual(requests, [
    { series_kind: 'actual_dominant', symbol: 'jm', frequency: '15m', since: '2026-08-20', through: '2026-08-20' },
    { series_kind: 'actual_dominant', symbol: 'jm', frequency: '15m', since: '2026-06-01', through: '2026-08-20' },
  ])
})

test('aborted prepend does not set historical unavailable or replace markers', async () => {
  const first = deferred<SubingStrategyHistoricalResponse>()
  const controller = useHistoricalResearchMarkers({
    debounceMs: 0,
    fetchSubingStrategy: async (request, signal) => {
      if (request.since === '2026-08-02') {
        return new Promise((resolve, reject) => {
          const onAbort = () => {
            const err = new Error('aborted')
            err.name = 'AbortError'
            reject(err)
          }
          if (signal?.aborted) onAbort()
          else signal?.addEventListener('abort', onAbort, { once: true })
          first.promise.then(resolve, reject)
        })
      }
      return strategyResponse(request.symbol, request.since, request.through)
    },
  })
  const identity = { overlay: 'subing' as const, seriesKind: 'actual_dominant' as const, symbol: 'jm', frequency: '15m' as const }
  const latest = canonicalBars
  await controller.sync(identity, latest, { start: latest[0].time, end: latest[1].time }, 'replace')
  const previous = [...controller.markers.value]
  const earlier = { ...latest[0], time: '2026-08-02T01:05:00Z', trading_day: '2026-08-02' }
  const hung = controller.sync(identity, [earlier, ...latest], { start: earlier.time, end: latest[1].time }, 'prepend')
  await controller.sync({ ...identity, symbol: 'ag' }, latest, { start: latest[0].time, end: latest[1].time }, 'replace')
  await hung
  assert.match(controller.markers.value[0].id, /ag/)
  assert.equal(controller.error.value, null)
})
```

Keep the existing test `preserves markers after a prepend failure` (still expects yellow bar on a **completed** failed prepend, not abort).

In `marketOverlayConvergence.test.ts`, next to `timeout: 120_000`, assert `getSubingStrategyHistory` passes `signal`:

```ts
assert.match(apiSource, /timeout: 120_000/)
assert.match(apiSource, /signal/)
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run:

```bash
pnpm --dir apps/quant-web exec node --test tests/historicalResearchMarkers.test.ts tests/marketOverlayConvergence.test.ts
```

Expected: FAIL (unknown `debounceMs`, or two prepend fetches, or `signal` missing).

- [ ] **Step 3: Implement debounce, abort, and axios signal**

`getSubingStrategyHistory`:

```ts
export function getSubingStrategyHistory(
  params: SubingStrategyHistoricalRequest,
  signal?: AbortSignal,
) {
  return request.get<never, SubingStrategyHistoricalWireResponse>(
    '/market/research/subing-strategy/history',
    { params, timeout: 120_000, signal },
  ).then(normalizeSubingStrategyHistory) as Promise<SubingStrategyHistoricalResponse>
}
```

In `useHistoricalResearchMarkers`:

- `Dependencies` adds `debounceMs?: number` and `fetchSubingStrategy(request, signal?: AbortSignal)`.
- Default debounce 400ms. `replace` / identity change: `clearTimeout`, `abort()` previous controller, `reset` as now, fetch immediately with a new `AbortController`.
- `prepend`: skip if `range.since >= loadedSince` as now; otherwise `clearTimeout` of the previous debounce and **resolve the previous debounce promise**; start a new timeout. When it fires, abort any in-flight fetch, then `loadSubingStrategy(..., signal)`.
- `loadSubingStrategy` forwards `signal` to `fetchSubingStrategy`.
- `catch`: if abort/cancel (`name === 'AbortError'` or `code === 'ERR_CANCELED'`), do not set `error`. Only the current generation may set `HISTORICAL_RESEARCH_UNAVAILABLE`.
- `dispose` / `reset`: abort + clear debounce timer.

Do not change `bars/page` timeout or `earlierHistoryLoadError`.

- [ ] **Step 4: Run frontend tests**

Run:

```bash
pnpm --dir apps/quant-web exec node --test tests/historicalResearchMarkers.test.ts tests/marketOverlayConvergence.test.ts tests/errorRedaction.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add apps/quant-web/src/composables/useHistoricalResearchMarkers.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/tests/marketOverlayConvergence.test.ts
git commit -m "$(cat <<'EOF'
Debounce and abort SuBing history fetches while paging left.

EOF
)"
```

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| prepend 400ms debounce, one in-flight `/history` | Task 3 |
| through = latest loaded day, since expands | already in composable; Task 3 coalesce test |
| snapshot through match + since in coverage → no 1m/replay | Task 1 + 2 |
| older through does not slice | Task 1 + 2 |
| GET `publish_cache=False` | Task 2 (existing HTTP test) |
| abort does not paint yellow | Task 3 |
| prepend failure keeps markers | existing test, keep in Task 3 |
| no worker / bars timeout change | Global Constraints |
