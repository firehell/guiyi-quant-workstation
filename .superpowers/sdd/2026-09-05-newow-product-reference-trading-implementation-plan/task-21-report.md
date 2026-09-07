# Task 21 Report — Newow Product Browser Acceptance

Date: 2026-09-07 Asia/Shanghai

Worktree: `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/newow-product-reference-trading-p6`

Branch: `feature/newow-product-reference-trading-p6`
Starting HEAD: `837ff846b596a3f060a83eb5bc64da74c183e61a`

## Result

`TEST_COMPLETE` for the approved Task 21 repository scope. The new browser harness explicitly intercepts every API or external request, gives every `strategy × frequency` combination a fresh Playwright page/context, starts desktop at `1440 × 900` and mobile at `390 × 844`, and covers chart-first startup, same-Bar action ordering, reference pagination/statistics, exact locate, bounded rebuild/busy/conflict behavior, auxiliary cache/disclosures, explanation/comparator separation, keyboard focus, existing Legacy/Free/HTDY/SuBing/Home regressions, screenshots, and instrumented fixture-backed performance.

No strategy formula, API contract, ReferenceTrade semantics, canonical data, production service, Runtime, notification, database, release, tag, main branch, or external data was changed.

## RED → GREEN and debugging evidence

1. Baseline exact three-file command: exit `1`; `49 passed / 2 failed / 51`, wall `68.04 s`. The absent `newow-product.spec.mjs` was silently unmatched. The two existing failures were independently diagnosed:
   - Free isolation asserted `Newow` was absent from the entire page after the P5 navigation legitimately added a global Newow tab. The assertion is now scoped to the Free workspace.
   - The SuBing mobile snapshot still represented 30 fixture bars/latest `129` and the pre-P5 `趋势策略` navigation. The current test deliberately creates 40 bars/latest `139`, and the product navigation now says `Newow`. The baseline was updated only after comparing expected/actual/diff and visually reviewing the actual drawer, focus, quote, and narrow layout.
2. Focused product RED: chart and reference wire validation succeeded, then `getByTestId('newow-load-earlier')` timed out after 60 s because the visible `加载更早` control lacked the promised stable selector.
3. Minimal product GREEN: one attribute was added to the existing button. The focused test then passed `1/1` in wall `3.40 s`; no behavior or request semantics changed.
4. Harness failures were treated as contract bugs, not hidden with sleeps: frames now list their exact same-Bar hint IDs; older pages do not repeat stable action IDs with different owners; fixture `as_of` follows the request generation; long-history bars remain before that generation; initial/CLOSED chronology remains valid; strict locators are scoped. No fixed delay is used anywhere in the new suite or benchmark.

## Browser scope

- Nine independently initialized combinations: trend, oscillation, main-rise × W1, D1, 60m.
- Chart/reference request isolation and opaque `chart_before` / `history_before` parameters.
- Same-Bar oscillator order `CLEAR(sequence=0) → BUILD(sequence=1)` with both BUILD identities separately locatable.
- OPEN, CLOSED, ROLLOVER_INTERRUPTED, negative mark, initial-before-window, and legal zero-CLOSED rendering.
- Exact unloaded-window locate uses `from`, never performance parameters, and never nearest-marker fallback.
- One unbound rebuild after 409; one request only after 429; mismatched identity clears facts.
- Four auxiliary controls, A→B→A cache reuse, repainting disclosure, and section-local lifecycle.
- Explanation has explicit W1/D1/60m source facts and evidence gaps; comparator remains in-sample, theoretical, and synthetic-terminal-only.
- Existing Legacy, Free, HTDY, SuBing, Home, keyboard, drawer, and mobile journeys remain in the exact three-file gate.

## Visual evidence

Reviewed with the rendered PNGs, then verified without `--update-snapshots` in the final three-file run:

- `apps/quant-web/e2e/newow-product.spec.mjs-snapshots/newow-desktop-reference-chromium-darwin.png`
- `apps/quant-web/e2e/newow-product.spec.mjs-snapshots/newow-mobile-oscillation-reference-chromium-darwin.png`
- `apps/quant-web/e2e/market-detail.spec.mjs-snapshots/market-detail-subing-390x844-chromium-darwin.png` (semantic P5/fixture drift described above)

The desktop baseline proves the reference disclosure, summary, filter, statuses and horizontally bounded table. The mobile baseline proves a genuine initial 390 px viewport, readable controls, chart/action evidence, and a horizontally scrollable reference surface without page-level layout invention.

The required in-app Browser plugin could not expose a visible tab from this delegated subagent (`IAB visibility is not supported in a subagent thread`). This is recorded as a tooling limitation rather than replaced by a claim. Playwright used the installed Chrome channel and both PNG baselines were separately inspected.

## Performance evidence

Source: final successful exact Playwright run, fixture-backed browser path, no fixed sleeps. Environment: macOS local worktree, Node `v26.3.1`, Playwright `1.62.1`, installed Chrome channel, one worker, desktop `1440 × 900`. Values are raw single-run observations, not service SLO claims:

| Metric | Raw value |
|---|---:|
| cold chart visible | 249.524 ms |
| cold chart request dispatch | 216.459 ms |
| warm reference visible | 121.525 ms |
| warm reference request dispatch | 67.483 ms |
| cold auxiliary visible | 55.586 ms |
| cold auxiliary request dispatch | 44.624 ms |
| auxiliary cached reuse visible | 34.632 ms |
| auxiliary cached reuse request delta | 0 |
| long-history prepend, 480 + 360 bars | 134.484 ms |
| long-history request dispatch | 46.898 ms |
| snapshot rebuild visible | 226.098 ms |
| snapshot rebuild request count | 2 |

`REAL_WORKSTATION_MDS_PERFORMANCE = NOT_RUN / PENDING`. This Task 21 worktree had no approved exact-code, read-only real-MDS startup path that could be used without touching or switching the active workstation Runtime. Route fixtures are explicitly browser-contract evidence and are not described as real MDS.

## Verification

| Command | Exit / result | Wall time |
|---|---|---:|
| focused Newow product unit set (`NewowProductChartStage`, primitives, reference, explanation, composable, wire) | `0`; 61/61 | 0.76 s |
| `pnpm test` in `apps/quant-web` | `0`; 421 passed, 1 skipped, 422 total | 2.98 s |
| `pnpm check:alert-rules` | `0`; passed | 1.59 s |
| `pnpm build` | `0`; 3,075 modules; topology passed | 4.86 s |
| exact Task 21 three-file Playwright command | `0`; 71/71 | 74.80 s |
| `git diff --check` plus both new `.mjs` syntax checks | `0` | 1.3 s |

The single skipped Web unit is the pre-existing optional HTDY golden-bundle test and is unrelated to this task.

## Known limits

- Fixture performance isolates Web lifecycle behavior; it is not network, backend compute, canonical I/O, or real MDS evidence.
- Raw timing is one local sample and intentionally has no fabricated percentile or threshold.
- No production/runtime/release gate is opened by these tests.
