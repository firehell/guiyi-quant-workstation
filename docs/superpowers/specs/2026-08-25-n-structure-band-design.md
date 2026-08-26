# N Structure Historical Range Band Design

## Intent

Expose the existing causal `n_structure_5m_v1` N1-N2 range-band fact as an
optional read-only Market chart aid. The feature is a Historical Canonical
projection, not a fifth Research Overlay, Alert, Runtime evaluator, candidate
promotion, or trading signal.

## Contract

- The chart setting is named `N字区间`, defaults off, persists locally, and is
  independently composable with the four retained Research Overlays.
- It is supported only for `actual_dominant + 5m`. Unsupported identities keep
  the setting visible but disabled and never trigger a request or silently
  change the Market identity.
- Only strictly completed N patterns are projected. The formation region spans
  from `n1_extreme.pivot_time` to `completed_at`; after completion, the same
  exact `NRangeBand.lower/upper` price span continues as a Historical
  observation region until the first strict `N2_ORIGIN_BROKEN` fact, the true
  rank-1 segment boundary, or the requested Canonical boundary.
- Up patterns use the chart up color and support-reference role; down patterns
  use the chart down color and resistance-reference role. Fill is 6% opacity,
  the one-pixel border is approximately 55% opacity, and the band does not
  affect price autoscaling.
- Historical rectangles are retrospective annotations: the solid completion
  point remains the earliest strict completion boundary and separates the
  formation region from the forward observation region. The first post-
  completion range-band re-entry is shown as a hollow point; a strict N2-origin
  break stops the observation region and is shown as an invalidation mark.
  Visible copy says `已完成 N · Canonical 历史 · 仅真实主力 5m` and hover
  detail says `历史确认 · 研究观察`.

## Read-only API

`GET /api/v1/market/research/n-structure/bands` accepts only
`series_kind=actual_dominant`, an active product symbol, `frequency=5m`, and an
ordered `since..through` trading-day window. The response contains exact
request identity, frozen policy lineage, and completed bands:

```text
request: series_kind, symbol, frequency, since, through
policy: policy_id, formula_version, source_timeframe, research_only
bands[]:
  band_id, contract, segment_start_trading_day, completion_trading_day
  direction, role, n1_at, completed_at, completion_level, lower, upper
  first_reentered_at, invalidated_at, expanded_until
```

The projection reuses the shared actual-dominant segment loader and exact N
reducer, including true rank-1 segment warm-up, and links each immutable
Completed N to the reducer's existing `range_band_reentry` and
`N2_ORIGIN_BROKEN` facts. A band is returned when its formation/observation
interval intersects the requested Canonical window, including a band completed
before `since` that remains observable inside the window. It does not duplicate
formulas or connect separate contracts. Unsupported request identity returns 422;
invalid active-universe/policy/source/segment facts remain typed 409 failures.
The retired `/n-structure/history` and raw JDJ route remain absent.

## Frontend data flow

The preference schema advances to v4 with `showNStructureBands`, migrating v3
to `false`. A dedicated composable loads bands only when enabled and supported,
keys state by Market identity, ignores stale generations, merges prepend
windows by `band_id` while retaining the widest/newest lifecycle projection,
and performs no work for Live mutations. Failure clears only the band layer
and leaves the K-line readable.

`KlineChart` owns one Lightweight Charts series primitive attached to the
candlestick series. The primitive receives server facts, clips bands to loaded
bars, redraws on viewport changes, draws only visible rectangles, and exposes
the latest topmost hit for hover detail. The formation region keeps the 6%
fill/solid border; the completion-to-`expanded_until` observation region uses
a lighter 2-3% fill and dashed border. Loading earlier bars extends a clipped
left edge without changing the server fact.

### Dense-overlap interaction

To preserve readability without hiding Historical facts, the primitive groups
only same-direction visible rectangles when at least three members have 60% or
greater screen-space overlap. Group discovery starts from the highest-priority
anchor (active before invalidated, then latest `completed_at`, then stable
`band_id`) and follows at most three adjacency hops; a fourth-hop bridge is not
absorbed into the group. Up and down directions remain independent.

The primary member keeps its complete band and lifecycle events. Suppressed
members retain faint upper/lower rails, so grouping is visual decluttering
rather than fact deletion. An all-invalidated group is dimmed as a whole. A
stable common visible anchor renders an accessible `N↑ ×N` or `N↓ ×N` badge;
hover/focus exposes the group detail and pointer/keyboard activation cycles the
primary member as `2/N`, `3/N`, and so on. Pointer leave, blur, zoom, resize, or
any geometry-coordinate change resets the selection. Hit testing still returns
the visually topmost, latest completed visible fact.

## Boundaries and acceptance

- No database, Redis, Canonical, Alert, notification, Runtime, release, or
  order mutation.
- No forming N preview, strong/medium/weak labels, multi-frequency N, Live
  evaluator, or future projection. The right extension contains only already
  observed Canonical bars and reducer facts.
- Tests freeze service projection, API contract/errors, preference migration,
  lifecycle intersection, loader identity/pagination/live behavior, primitive
  two-stage geometry/hit testing, re-entry/invalidation marks, disabled-setting
  behavior, Overlay coexistence, readable failure states, bounded dense-overlap
  grouping, faint suppressed rails, accessible badge cycling, and reset behavior.
- Browser acceptance uses an isolated local development stack and verifies AU
  actual-dominant 5m without switching production Runtime.
