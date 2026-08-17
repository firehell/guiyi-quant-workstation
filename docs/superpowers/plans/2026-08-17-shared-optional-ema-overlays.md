# Shared Optional EMA Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one persisted pair of EMA10/EMA60 display switches that applies unchanged when the Market K-line research overlay switches between SuBing and HTDY, then prepare and publish release `v1.4.1` behind the repository's release Gate.

**Architecture:** Keep `mainIndicators.ts` as the preference and visibility authority, upgrade its localStorage contract from v2 to v3, and pass one shared optional-EMA selection through `chart.vue` into the existing `KlineChart`. The toolbar remains controlled and presentation-only; no indicator formula, API, database, Alert, Canonical, or Runtime behavior changes.

**Tech Stack:** Vue 3, TypeScript, Naive UI, Lightweight Charts, Node test runner, Playwright, Vite, FastAPI version identity, Git/GitHub release flow.

## Global Constraints

- New and migrated preferences default EMA10 and EMA60 to off.
- One shared optional-EMA selection applies to both SuBing and HTDY; there is no per-overlay preference map.
- SuBing always includes EMA21 and HTDY always includes its observation-only layer while selected.
- `none` resolves to no visible main indicators but retains the saved optional-EMA selection.
- Existing EMA calculations and `KlineChart` series lifecycle must be reused without a second indicator implementation.
- HTDY keeps its future-reference/repainting warning and observation-only boundary.
- No backend DTO, database, Alert Scope, notification, Canonical, Runtime, or order behavior changes.
- Release/tag and Runtime promotion remain separate controlled external operations; this plan publishes `v1.4.1` but does not promote Runtime.

---

## File Structure

- Modify `apps/quant-web/src/types/market.ts`: define the narrow optional-EMA UI type.
- Modify `apps/quant-web/src/utils/mainIndicators.ts`: own v3 preferences, migration, normalization, and visibility resolution.
- Modify `apps/quant-web/tests/mainIndicators.test.ts`: prove the pure preference and resolver contract.
- Modify `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`: render controlled switches.
- Modify `apps/quant-web/src/pages/market/chart.vue`: own shared state and persistence.
- Modify `apps/quant-web/e2e/market-research.spec.mjs`: prove real toolbar-to-chart behavior.
- Modify version identity files, `README.md`, and `CHANGELOG.md`: prepare `v1.4.1` consistently.
- Modify `STATUS.md` only after remote release readback: record release without claiming Runtime promotion.

---

### Task 1: Preference V3 and Indicator Resolver

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Test: `apps/quant-web/tests/mainIndicators.test.ts`

**Interfaces:**
- Produces: `OptionalEmaIndicatorId = 'ema_10' | 'ema_60'`.
- Produces: `MainChartPreferences` with `version: 3` and `optionalEmaIndicators: OptionalEmaIndicatorId[]`.
- Produces: `normalizeOptionalEmaIndicators(value: unknown): OptionalEmaIndicatorId[]`.
- Produces: `visibleMainIndicatorsForOverlay(overlay, optionalEmaIndicators): MainIndicatorId[]`.

- [ ] **Step 1: Write the failing tests**

Add exact v3 default, normalization, resolver, migration, and save/load assertions:

```ts
assert.deepEqual(defaultMainChartPreferences(), {
  version: 3,
  selectedOverlay: 'subing',
  optionalEmaIndicators: [],
  period: null,
  realtimeFollow: false,
})
assert.deepEqual(
  normalizeOptionalEmaIndicators(['ema_60', 'ema_21', 'ema_10', 'ema_60', 'htdy']),
  ['ema_10', 'ema_60'],
)
assert.deepEqual(visibleMainIndicatorsForOverlay('subing', []), ['ema_21'])
assert.deepEqual(visibleMainIndicatorsForOverlay('subing', ['ema_10', 'ema_60']), ['ema_10', 'ema_21', 'ema_60'])
assert.deepEqual(visibleMainIndicatorsForOverlay('htdy', ['ema_10', 'ema_60']), ['ema_10', 'ema_60', 'htdy'])
assert.deepEqual(visibleMainIndicatorsForOverlay('none', ['ema_10', 'ema_60']), [])
```

Use literal legacy keys in fixtures and prove v2 preserves overlay/period/follow while adding an empty optional list:

```ts
values.set('guiyi.market.chart.preferences.v2', JSON.stringify({
  version: 2,
  selectedOverlay: 'htdy',
  period: '15m',
  realtimeFollow: true,
}))
assert.deepEqual(loadMainChartPreferences(storage), {
  version: 3,
  selectedOverlay: 'htdy',
  optionalEmaIndicators: [],
  period: '15m',
  realtimeFollow: true,
})
```

Also prove v3 save/load round-trips both optional EMAs and invalid JSON returns the complete v3 default.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
pnpm --dir apps/quant-web exec node --test tests/mainIndicators.test.ts
```

Expected: FAIL because v3 fields and `normalizeOptionalEmaIndicators` do not exist.

- [ ] **Step 3: Implement the narrow v3 contract**

Add to `market.ts`:

```ts
export type OptionalEmaIndicatorId = 'ema_10' | 'ema_60'
```

In `mainIndicators.ts`, use these exact keys and type:

```ts
export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v3'
export const MAIN_CHART_PREFERENCES_VERSION = 3
const LEGACY_V2_MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v2'
const LEGACY_V1_MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v1'

export interface MainChartPreferences {
  version: 3
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  period?: string | null
  realtimeFollow?: boolean
}
```

Normalize into fixed order and merge mandatory layers only in the resolver:

```ts
const OPTIONAL_EMA_INDICATORS: OptionalEmaIndicatorId[] = ['ema_10', 'ema_60']

export function normalizeOptionalEmaIndicators(value: unknown): OptionalEmaIndicatorId[] {
  if (!Array.isArray(value)) return []
  return OPTIONAL_EMA_INDICATORS.filter((id) => value.includes(id))
}

export function visibleMainIndicatorsForOverlay(
  overlay: ResearchOverlayId,
  optionalEmaIndicators: OptionalEmaIndicatorId[],
): MainIndicatorId[] {
  const optional = normalizeOptionalEmaIndicators(optionalEmaIndicators)
  if (overlay === 'subing') return [
    ...(optional.includes('ema_10') ? ['ema_10' as const] : []),
    'ema_21',
    ...(optional.includes('ema_60') ? ['ema_60' as const] : []),
  ]
  if (overlay === 'htdy') return [...optional, 'htdy']
  return []
}
```

Load v3 first, then migrate v2 and v1. Both legacy paths preserve overlay/period/follow and set `optionalEmaIndicators: []`; they must not revive v1's free-form EMA list.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
pnpm --dir apps/quant-web exec node --test tests/mainIndicators.test.ts
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit the preference contract**

```bash
git add apps/quant-web/src/types/market.ts apps/quant-web/src/utils/mainIndicators.ts apps/quant-web/tests/mainIndicators.test.ts
git commit -m "feat(web): persist shared optional EMA overlays"
```

---

### Task 2: Controlled Toolbar Switches and Chart Wiring

**Files:**
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Test: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Consumes: `OptionalEmaIndicatorId` and v3 functions from Task 1.
- Produces: toolbar prop `optionalEmaIndicators: OptionalEmaIndicatorId[]`.
- Produces: toolbar event `'update:optional-ema-indicators': [value: OptionalEmaIndicatorId[]]`.
- Produces: existing `data-visible-main-indicators` as the browser contract.

- [ ] **Step 1: Write the failing browser test**

Add `shared EMA switches persist across SuBing and HTDY while none hides every overlay` using `mockWorkspace`:

```js
await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
const ema = page.getByRole('group', { name: 'EMA' })
const ema10 = ema.getByRole('button', { name: 'EMA10', exact: true })
const ema60 = ema.getByRole('button', { name: 'EMA60', exact: true })
const kline = page.locator('.product-workspace__kline')
const overlay = page.getByRole('group', { name: 'Overlay' })

await expect(ema10).toHaveAttribute('aria-pressed', 'false')
await expect(ema60).toHaveAttribute('aria-pressed', 'false')
await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_21')
await ema10.click()
await ema60.click()
await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
await overlay.getByRole('button', { name: '火天大有', exact: true }).click()
await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_60,htdy')
await overlay.getByRole('button', { name: '无', exact: true }).click()
await expect(kline).toHaveAttribute('data-visible-main-indicators', '')
await expect(ema10).toHaveAttribute('aria-pressed', 'true')
await expect(ema60).toHaveAttribute('aria-pressed', 'true')
await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
await page.reload()
await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
```

- [ ] **Step 2: Run isolated E2E and verify RED**

```bash
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs --grep "shared EMA switches"
```

Expected: FAIL because the `EMA` group does not exist.

- [ ] **Step 3: Add the controlled toolbar UI**

Define the two fixed options and emit a normalized ordered array:

```ts
const optionalEmaOptions: Array<{ label: string; value: OptionalEmaIndicatorId }> = [
  { label: 'EMA10', value: 'ema_10' },
  { label: 'EMA60', value: 'ema_60' },
]

function toggleOptionalEma(value: OptionalEmaIndicatorId) {
  const selected = new Set(props.optionalEmaIndicators)
  if (selected.has(value)) selected.delete(value)
  else selected.add(value)
  emit('update:optional-ema-indicators', optionalEmaOptions.map((item) => item.value).filter((id) => selected.has(id)))
}
```

Render after the Overlay group:

```vue
<NButtonGroup size="small" class="toolbar__ema" aria-label="EMA">
  <NButton
    v-for="item in optionalEmaOptions"
    :key="item.value"
    :type="optionalEmaIndicators.includes(item.value) ? 'primary' : 'default'"
    :aria-pressed="optionalEmaIndicators.includes(item.value)"
    @click="toggleOptionalEma(item.value)"
  >{{ item.label }}</NButton>
</NButtonGroup>
```

- [ ] **Step 4: Wire shared page state and persistence**

Initialize one ref, pass it to the resolver, and persist normalized updates:

```ts
const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([
  ...initialMainChartPreferences.optionalEmaIndicators,
])

const visibleMainIndicators = computed(() => {
  if (selectedOverlay.value === 'subing' && !subingSupported.value) return []
  return visibleMainIndicatorsForOverlay(selectedOverlay.value, optionalEmaIndicators.value)
})

function updateOptionalEmaIndicators(value: OptionalEmaIndicatorId[]) {
  optionalEmaIndicators.value = normalizeOptionalEmaIndicators(value)
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, optionalEmaIndicators: optionalEmaIndicators.value })
}
```

Pass the prop/event through `ProductWorkspaceToolbar`. Selecting `none` must not clear the ref.

- [ ] **Step 5: Run focused checks**

```bash
pnpm --dir apps/quant-web exec node --test tests/mainIndicators.test.ts tests/kline-view-model.test.ts
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: tests pass and production build succeeds.

- [ ] **Step 6: Commit the user-visible feature**

```bash
git add apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue apps/quant-web/src/pages/market/chart.vue apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): add shared EMA display switches"
```

---

### Task 3: Prepare the V1.4.1 Release Candidate

**Files:**
- Modify: `apps/quant-web/package.json`
- Modify: `services/quant-api/pyproject.toml`
- Modify: `services/quant-api/uv.lock`
- Modify: `services/quant-api/app/version.py`
- Modify: `services/quant-api/tests/test_health.py`
- Modify: `tests/engineering/test_canonical_consistency.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: consistent code identity `1.4.1` in API, Web, package metadata, lockfile, health tests, and engineering tests.
- Does not produce: a tag, main merge, release claim, or Runtime promotion.

- [ ] **Step 1: Change version assertions first and verify RED**

Update health assertions to `1.4.1`. Rename the engineering test to `test_release_versions_are_consistently_1_4_1` and change all expected literals to `1.4.1`.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_health.py \
  tests/engineering/test_canonical_consistency.py::test_release_versions_are_consistently_1_4_1
```

Expected: FAIL because product metadata still reports `1.4.0`.

- [ ] **Step 2: Update product metadata and lock identity**

Set exact version `1.4.1` in `apps/quant-web/package.json`, `services/quant-api/pyproject.toml`, `services/quant-api/app/version.py`, and the README code-version sentence.

Refresh the project entry without dependency upgrades:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv lock --offline --project services/quant-api
```

Add `CHANGELOG.md` section `## [1.4.1] - 2026-08-17` describing only the shared EMA switches, v3 local preference migration, unchanged indicator math, and unchanged backend/Alert/Runtime/data boundaries.

- [ ] **Step 3: Run release identity tests and verify GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_health.py \
  tests/engineering/test_canonical_consistency.py::test_release_versions_are_consistently_1_4_1
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit the release candidate identity**

```bash
git add apps/quant-web/package.json services/quant-api/pyproject.toml services/quant-api/uv.lock \
  services/quant-api/app/version.py services/quant-api/tests/test_health.py \
  tests/engineering/test_canonical_consistency.py README.md CHANGELOG.md
git commit -m "chore(release): prepare v1.4.1"
```

---

### Task 4: Complete Verification and Review

**Files:**
- Review: all files changed since `a55680ad2`
- Verify: repository and Web checks only; no Runtime or external mutation

**Interfaces:**
- Consumes: Tasks 1-3 complete on clean `develop`.
- Produces: exact candidate SHA and evidence sufficient to request the separate release Gate.

- [ ] **Step 1: Run the complete relevant Web suite once**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: all Web unit tests and both E2E files pass, and the production build succeeds.

- [ ] **Step 2: Run repository and release checks once**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_health.py tests/engineering
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: tests pass, secret scan reports zero findings, diff check is clean, and status is empty.

- [ ] **Step 3: Review the complete candidate diff**

```bash
git diff --stat a55680ad2..HEAD
git diff --check a55680ad2..HEAD
git diff a55680ad2..HEAD -- \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
```

Confirm no per-overlay preference map, no optional removal of EMA21/HTDY, no second calculation path, and no backend/Alert/Runtime/data changes.

- [ ] **Step 4: Record exact candidate identity**

```bash
git status --short
git rev-parse HEAD
git log -1 --oneline
git merge-base --is-ancestor main HEAD
```

Expected: clean worktree, exact candidate SHA printed, and candidate descends from `main`.

---

### Task 5: Publish V1.4.1 Behind Gate A

**Files:**
- Modify after release: `STATUS.md`
- External refs: `origin/develop`, release PR `develop -> main`, `origin/main`, annotated tag `v1.4.1`

**Interfaces:**
- Consumes: exact clean candidate SHA from Task 4 and fresh user intent identifying this repository and `v1.4.1`.
- Produces: remote main merge and annotated tag `v1.4.1` pointing to the release merge commit.
- Does not produce: Runtime promotion, service reload, DB migration, Scope mutation, notification, or Canonical write.

- [ ] **Step 1: Push the verified candidate to develop**

```bash
git push origin develop
git ls-remote origin refs/heads/develop
```

Expected: remote `develop` equals the verified candidate SHA. This ordinary integration push is not release authorization.

- [ ] **Step 2: STOP for the exact release Gate**

Ask for one fresh execution intent identifying:

```text
repository: firehell/guiyi-quant-workstation
operation: merge verified develop release candidate to main and create/push annotated tag
version: v1.4.1
candidate: exact SHA from Task 4
excluded: Runtime promotion, service reload, DB/Canonical write, Alert Scope, WeCom
```

Do not create or merge the PR and do not create/push the tag before the response arrives.

- [ ] **Step 3: Execute the single approved release attempt**

After approval, create and merge the release PR, then tag the read-back remote main merge commit:

```bash
gh pr create --repo firehell/guiyi-quant-workstation --base main --head develop \
  --title "release: v1.4.1" \
  --body "Publish the shared EMA10/EMA60 display switches. No Runtime, database, Canonical, Alert Scope, notification, or order changes."
gh pr merge --repo firehell/guiyi-quant-workstation --merge --delete-branch=false
git fetch origin main develop --tags
git tag -a v1.4.1 origin/main -m "v1.4.1"
git push origin refs/tags/v1.4.1
```

If any mutation command fails, stop. Do not retry without a new execution intent.

- [ ] **Step 4: Read back remote release truth**

```bash
git ls-remote origin refs/heads/main refs/heads/develop refs/tags/v1.4.1 refs/tags/v1.4.1^{}
git rev-parse origin/main
git rev-parse 'v1.4.1^{}'
git merge-base --is-ancestor origin/develop origin/main
gh pr view --repo firehell/guiyi-quant-workstation --json number,state,mergeCommit,url
```

Expected: PR is merged, peeled tag equals `origin/main`, and remote refs are explicit. A local tag alone is insufficient.

- [ ] **Step 5: Record release status without claiming deployment**

Update `STATUS.md` with the release PR and peeled commit from readback, describe only the shared EMA UI, and retain formal Runtime at `v1.4.0` until a separate promotion request.

```bash
git diff --check
git add STATUS.md
git commit -m "docs(status): record v1.4.1 release"
git push origin develop
```

Do not reload Web or switch Runtime. Report `RELEASED / RUNTIME_GATE_PENDING` if publication succeeds.
