# P3 — Market 苏冰盯盘状态卡、Candidate 深链与图表复核计划

> **Execution:** Web consumes typed backend facts. It must not duplicate the formal BUY/SELL formula.

状态：`PLAN_READY_FOR_USER_REVIEW`

父计划：`docs/tasks/2026-09-01-alert-reliability-subing-watch-15m-implementation-plan.md`

Issue：`#286`

Lane：Lane 2 Web/API presentation，读取 Lane 3 可信事实。

## Goal

在现有 `/market` 和 `/market/chart` 内展示最近 finalized 15m boundary、候选入口、权威 `MA21 (SMA)`、Watch marker 和固定上下文事实，让用户快速判断“正常静默”“有候选”或“Runtime 边界不完整”。不新增顶级 route，不写 Scope，不发送通知。

## Workspace

```text
base: P2 合入后的最新 origin/develop
branch: feature/subing-watch-web
worktree: 新 task worktree
integration: develop
PR: Draft PR required
review: Web/API independent review
human Gate: 允许集成 develop
```

## File Map

### Backend

```text
services/quant-api/app/api/market_research_overlays.py
services/quant-api/app/schemas/market.py
services/quant-api/tests/test_market_research_overlays_api.py
```

### Web

```text
apps/quant-web/src/api/market.ts
apps/quant-web/src/api/runtime.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/components/market/SubingWatchStatusCard.vue
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/src/pages/market/index.vue
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/src/utils/marketChartEntry.ts
apps/quant-web/src/utils/alertMarkers.ts
apps/quant-web/src/composables/usePersistentAlertMarkers.ts
apps/quant-web/tests/subingWatchStatus.test.ts
apps/quant-web/tests/marketChartEntry.test.ts
apps/quant-web/tests/alertMarkers.test.ts
apps/quant-web/e2e/market-subing-watch.spec.mjs
```

## Task 1 — Bounded Watch projection API

### Endpoint

Add one read-only endpoint under the existing Market API family:

```text
GET /api/v1/market/research/subing-watch
```

Request:

```text
series_kind=actual_dominant
symbol=<active/operational symbol>
frequency=15m
since=<aware ISO bar_end optional>
through=<aware ISO bar_end optional; latest completed when omitted>
```

Response:

```text
formula_version
series_kind
symbol
frequency
contract
segment_start_trading_day
cutoff
source_mode
evaluations[]
  bar_end
  outcome
  observation_types
  close
  ma21
  dif
  dea
  macd_histogram
  context
  candidate_id
  public_reason_codes
```

The handler only validates, calls P1 `SubingWatchCurrentProjectionService`, and serializes. It does not calculate SMA, MACD, CROSS, context or Candidate IDs.

### RED tests

- valid current projection equals direct service serialization;
- non-`actual_dominant` rejected;
- non-15m rejected;
- unknown symbol rejected;
- naive `since/through` rejected;
- `since > through` rejected;
- incomplete current Bar excluded;
- source/segment identity mismatch fails closed;
- response is deterministic and read-only;
- no cache/write/DB Event side effect.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  -k subing_watch

git add \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/tests/test_market_research_overlays_api.py
git commit -m "feat(api): expose SuBing Watch projection"
```

## Task 2 — Compact status card on `/market`

### Files

- Modify: `apps/quant-web/src/api/runtime.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Create: `apps/quant-web/src/components/market/SubingWatchStatusCard.vue`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Create: `apps/quant-web/tests/subingWatchStatus.test.ts`
- Modify: `apps/quant-web/e2e/market-subing-watch.spec.mjs`

### Display fields

```text
盯盘状态：正常 / 降级 / 未观察
边界：HH:MM
应处理：N
已评估：N
候选：N
不可用：N
缺失：N
通知：accepted M / attempted K
```

Exact copy:

```text
normal_silence=true:
  已完整评估，本边界无候选

candidate_count>0 and complete:
  已完整评估，产生 N 个候选

any unavailable/failure/missing:
  本边界不完整，请先检查 Runtime

missing public status:
  尚无可证明的盯盘状态
```

The card must not infer health from the generic Alert heartbeat when Watch boundary is missing or incomplete.

### Stable test attributes

```text
data-testid="subing-watch-status"
data-watch-status="ok|degraded|unobserved"
data-normal-silence="true|false"
data-candidate-count="N"
data-missing-count="N"
```

### Candidate links

Each recent Candidate opens exactly:

```text
/market/chart
?series_kind=actual_dominant
&frequency=15m
&symbol=<symbol>
&entry=subing-watch
&bar_end=<formal-bar-end>
```

The URL keeps formal `bar_end`; it does not subtract 15 minutes.

### Tests

Node tests cover all four status states, count aggregation, timestamp formatting and candidate URL encoding. Playwright intercepts `/api/runtime/health` for normal silence, Candidate, missing trigger and absent Watch status. Assert no POST/PUT/DELETE request occurs.

### Verification and commit

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingWatchStatus.test.ts
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-subing-watch.spec.mjs

git add \
  apps/quant-web/src/api/runtime.ts \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/components/market/SubingWatchStatusCard.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/tests/subingWatchStatus.test.ts \
  apps/quant-web/e2e/market-subing-watch.spec.mjs
git commit -m "feat(web): show SuBing Watch runtime proof"
```

## Task 3 — Deep-link parser and identity coordinator

### Files

- Modify: `apps/quant-web/src/utils/marketChartEntry.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/marketChartEntry.test.ts`

### Contract

```typescript
interface SubingWatchChartEntry {
  entry: 'subing-watch'
  seriesKind: 'actual_dominant'
  frequency: '15m'
  symbol: string
  barEnd: string
  overlay: 'subing'
}
```

`resolveSubingWatchChartEntry` returns `null` when:

- `entry` differs;
- `series_kind` is not `actual_dominant`;
- `frequency` is not `15m`;
- symbol invalid;
- `bar_end` missing, naive or invalid.

On valid entry:

```text
symbol=query symbol
seriesKind=actual_dominant
frequency=15m
selectedOverlay=subing
followLatest=false
focus formal bar_end after bars and Watch projection load
```

Do not reuse Strategy `action_id`; Watch identity is `bar_end + candidate_id`.

### Verification and commit

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketChartEntry.test.ts

git add \
  apps/quant-web/src/utils/marketChartEntry.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/marketChartEntry.test.ts
git commit -m "feat(web): open SuBing Watch candidates"
```

## Task 4 — Render authoritative SMA21 and distinct Watch markers

### Files

- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/tests/alertMarkers.test.ts`
- Modify: `apps/quant-web/e2e/market-subing-watch.spec.mjs`

### Authority boundary

- `getSubingWatchProjection` supplies SMA21, MACD facts, context and Candidate markers.
- Web must not use `calculateEMA(..., 21)` as the Watch line.
- Existing SuBing EMA10/21 ribbon remains unchanged and separately named.
- Watch line label is exactly `MA21 (SMA)`.
- MACD pane may keep its existing display mirror, but focused Candidate facts/tooltip use server values.

### Marker distinction

```text
Watch buy label: 盯盘·多
Watch sell label: 盯盘·空
Watch id prefix: subing-watch:
Watch tooltip: observation trigger + formal 15m bar_end + context facts
Existing Strategy marker: unchanged
```

Watch and Strategy markers must differ in ID prefix, label, tooltip and tone/shape metadata.

### Formal time versus visual coordinate

The API, Event identity and URL retain formal `bar_end`. Current Web draws intraday K lines at interval open. Focus logic must:

```text
find original bar by bar.time == formal bar_end
then convert through existing period-aware opening-time coordinate
```

Tooltip must show the 15m interval and formal close time. Never rewrite the Event/URL time to the visual start.

### RED tests

- source inspection/component props prove no Web Watch CROSS formula;
- `MA21 (SMA)` uses API points;
- Watch marker differs from Strategy action marker;
- buy/sell label symmetry;
- unavailable context displayed, not omitted;
- focused bar uses formal bar_end lookup;
- duplicate markers dedupe by immutable Event identity;
- mobile/narrow width remains usable;
- no hidden Scope mutation.

### Verification and commit

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingWatchStatus.test.ts \
  tests/marketChartEntry.test.ts \
  tests/alertMarkers.test.ts \
  tests/barTime.test.ts \
  tests/kline-view-model.test.ts
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-subing-watch.spec.mjs
pnpm -C apps/quant-web exec vue-tsc -b
pnpm -C apps/quant-web build

git add \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/src/composables/usePersistentAlertMarkers.ts \
  apps/quant-web/tests/alertMarkers.test.ts \
  apps/quant-web/e2e/market-subing-watch.spec.mjs
git commit -m "feat(web): review SuBing Watch facts"
```

## Packet Verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py

pnpm --dir apps/quant-web run check:alert-rules
pnpm -C apps/quant-web exec node --test \
  tests/subingWatchStatus.test.ts \
  tests/marketChartEntry.test.ts \
  tests/alertMarkers.test.ts \
  tests/barTime.test.ts \
  tests/kline-view-model.test.ts
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-subing-watch.spec.mjs
pnpm -C apps/quant-web exec vue-tsc -b
pnpm -C apps/quant-web build
```

## Review Checklist

- no new top-level route or fourth overlay;
- no TypeScript BUY/SELL formula;
- SMA21 is server truth and visually distinct from EMA21;
- status card cannot hide incomplete boundary behind green heartbeat;
- Candidate link retains formal bar_end;
- chart focus uses existing opening-time projection only after identity lookup;
- Watch/Strategy markers remain distinct;
- no hidden write or Scope mutation;
- desktop and narrow viewport pass.

PR stops at `允许集成 develop`. No Runtime switch, Rule change, migration or real send is authorized.
