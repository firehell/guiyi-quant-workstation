# Shared Optional EMA Overlays Design

Date: 2026-08-17
Target release: `v1.4.1`
Status: approved for implementation

## Goal

Let the user independently toggle EMA10 and EMA60 on the Market K-line chart while keeping the existing research overlay selector simple. The two EMA choices are shared across SuBing and HTDY rather than stored separately for each research principle.

## Existing behavior

- The research overlay selector is exclusive: `none`, `subing`, or `htdy`.
- SuBing always renders EMA21.
- HTDY always renders its observation-only chart layer and risk warning.
- EMA10 and EMA60 are already registered, calculated, and rendered by the existing Web indicator path, but the current overlay resolver never selects them.
- Chart preferences use localStorage schema v2 and persist the selected overlay, period, and realtime-follow preference.

## User-visible behavior

The Market toolbar adds two compact toggle buttons, `EMA10` and `EMA60`, next to the existing research overlay selector.

- Both toggles default to off for a new or migrated preference.
- Their state is shared: changing from SuBing to HTDY, or back, preserves and applies the same EMA10/EMA60 selection.
- SuBing renders EMA21 plus any enabled optional EMA lines. EMA21 remains mandatory and has no off switch.
- HTDY renders its existing observation-only layer plus any enabled optional EMA lines. The HTDY layer remains mandatory while HTDY is selected.
- `none` renders no main-chart indicator, regardless of the saved optional EMA selection. The selection is retained and applies again after selecting SuBing or HTDY.
- Reloading the page restores the optional EMA selection.

This changes chart presentation only. It does not change indicator math, SuBing or HTDY semantics, Alert evaluation, notification scope, Runtime subscriptions, Canonical data, or database state.

## Preference contract

Upgrade the main-chart preference schema from v2 to v3. The v3 value retains the existing fields and adds one shared optional-EMA field containing only `ema_10` and `ema_60`.

The persisted value is normalized before use:

- unsupported ids are removed;
- duplicates are removed;
- EMA21 and HTDY cannot enter the optional list;
- invalid or unreadable storage falls back to the v3 default;
- storage read or write failure does not block the chart.

Migration from v2 preserves `selectedOverlay`, `period`, and `realtimeFollow`, and initializes the optional EMA selection to empty. The older v1 compatibility path continues through the same normalized v3 result without reviving its former free-form indicator selection.

## Component and data flow

`mainIndicators.ts` remains the single authority for indicator definitions, preference normalization, migration, and resolving visible indicators. Its resolver accepts the selected research overlay and the shared optional EMA selection, returning a deterministic indicator list:

- `subing` -> optional EMA10, mandatory EMA21, optional EMA60;
- `htdy` -> optional EMA10, optional EMA60, mandatory HTDY;
- `none` -> empty.

`chart.vue` owns the loaded preference state, derives the visible indicator list through that resolver, persists toggle changes, and passes the result to the existing `KlineChart` prop. It does not calculate EMA values.

`ProductWorkspaceToolbar.vue` renders the two controlled buttons and emits one normalized optional-EMA update. It does not access localStorage or derive indicator visibility. The buttons remain visible while `none` is selected so the retained choice is explicit, but no EMA line renders until SuBing or HTDY is selected.

`KlineChart.vue` and `klineViewModel.ts` continue using their existing registered EMA calculation and series lifecycle. No second chart or indicator implementation is introduced.

## Failure handling

- Invalid preference data fails to the safe default: SuBing selected, EMA10 off, EMA60 off.
- localStorage unavailability affects persistence only and never blocks market-data rendering.
- Unsupported SuBing frequencies retain their current fail-closed behavior; enabling an optional EMA does not make SuBing available or bypass segment resolution.
- HTDY keeps its current observation-only warning and repaint-risk boundary.

## Verification

Unit tests will cover:

- v3 defaults and normalization;
- v2 and legacy-v1 migration into v3;
- preference save/load round-trip;
- shared EMA state across SuBing and HTDY;
- mandatory EMA21 for SuBing;
- mandatory HTDY layer for HTDY;
- `none` resolving to no visible indicators while retaining saved optional EMA state.

Component/browser tests will cover:

- both buttons default off;
- toggling EMA10 and EMA60 changes the rendered indicator contract;
- switching between SuBing and HTDY retains both choices;
- selecting `none` hides all main indicators;
- returning to a research overlay restores the optional EMA lines;
- existing SuBing identity/segment behavior and HTDY risk notice remain intact;
- the Web production build succeeds without related console errors.

## Release boundary

Implementation and local verification may proceed on `develop`. Creating or pushing `v1.4.1`, merging a release to `main`, and switching the formal Runtime remain separate controlled external operations requiring a fresh, exact execution intent immediately before each operation. This design does not authorize Runtime promotion.
