# Task 7 report — Backtest page and browser acceptance

Status: completed

Base: `920d79392fc62a30e7e1e1fffd6ece93edd939a6`

Commit message: `feat: add RQAlpha research backtest page`

## Scope

- Added `/backtests` as a local-only, research-only RQAlpha workbench page with
  a fixed registered-strategy form, date and future settings, all four declared
  parameter kinds, recent runs, and one selected run detail.
- Added 2000 ms running-state polling through the Task 6 `BacktestPoller`, with
  terminal-state stop, selected-run replacement, and component-unmount disposal.
- Added the fixed summary projection, server-generated `equity.png`, requested
  and effective configuration, stdout/stderr tails, and the six allowlisted
  artifact downloads. Downloads use a sanitized fixed filename, a Blob URL,
  and scheduled `URL.revokeObjectURL` cleanup.
- Kept the menu visible on `localhost|127.0.0.1` even when the sidecar is
  unavailable, with explicit Git-out configuration/start guidance and retry.
  On every other hostname the menu is hidden, the direct route fails closed,
  no form or mutation is available, and no loopback request is made.
- Added one inline `UiIcon` variant and retained the existing Vue 3, Naive UI,
  deep-navy shell, light workspace, accessible labels, and stable test selectors.

No dashboard, comparison surface, trade/position page, interactive equity chart,
main API client/proxy change, port 8011 service, real RQAlpha, external result
root, DB, Redis, Canonical, Alert, notification, Runtime, release, or order path
was added or invoked.

## RED evidence

The first runnable focused command was:

```text
pnpm exec playwright test -c playwright.config.mjs e2e/backtests.spec.mjs
```

Observed result before Task 7 production files existed:

```text
5 failed
- local ready: RQAlpha menu not found
- local ready submit: backtest form not found
- local unavailable: RQAlpha menu not found
- non-loopback direct route: remote-blocked surface not found
- unmount lifecycle: run detail not found
```

All failures were caused by the intended missing route/menu/page behavior. An
earlier sandboxed attempt could not bind the test Web server (`EPERM`); it was
not counted as RED. The runnable RED used only the allowed test Web server on
`127.0.0.1:5182` and route-intercepted the explicit loopback API URL.

## Final GREEN evidence

```text
focused Task 7 Playwright: 5 passed
full Web unit tests: 245 passed, 1 skipped, 0 failed
full Playwright: 84 passed, 0 failed
vue-tsc project build: exit 0
Vite production build: passed
production bundle topology: charting vendor static imports are acyclic
git diff --check: exit 0
```

Exact final commands:

```text
pnpm test
pnpm exec vue-tsc -b --pretty false
pnpm build
pnpm exec playwright test -c playwright.config.mjs
node scripts/checkProductionBundleTopology.mjs dist
git -c core.fsmonitor=false diff --check
```

The Playwright Web server used
`VITE_PROXY_API_TARGET=http://127.0.0.1:1` and bound only
`127.0.0.1:5182`. Task 7 tests intercepted
`http://127.0.0.1:8011/api/v1/backtests/**`; no port 8011 process or real
sidecar was started.

## Self-review

### Standards

- The page is split by responsibility into form, recent-run, detail, and page
  orchestration components; it reuses the Task 6 client, capability validator,
  form validator, DTOs, and poller instead of duplicating their contracts.
- All financial request values remain strings through the existing serializer.
  The page only formats returned summary strings for presentation and never
  recomputes RQAlpha PnL, fees, matching, equity, trades, or positions.
- Download kinds remain the fixed Task 6 allowlist, run ids are URL-encoded by
  that client and filename-sanitized by the page, and Blob URLs are revoked.
- No secret, stack trace, arbitrary path, arbitrary strategy, raw config editor,
  upload, or online code path is exposed.

### Spec

- Local ready, local unavailable/retry, running-to-terminal, terminal detail,
  fixed downloads, remote hidden/direct-blocked/zero-probe, and unmount cleanup
  all have browser behavior coverage against the real Vue page.
- The form contains strategy, dates, frequency, the six future settings, and
  registry-declared integer/decimal/boolean/enum parameters only.
- The detail contains only the requested first-version surfaces. The excluded
  dashboard, comparisons, trade/position pages, and interactive equity chart
  remain absent.

No remaining Critical, Important, or Minor Task 7 finding was identified.

## Gates

Task 7 repository code and automated browser acceptance are complete. Real
RQAlpha execution, sidecar loading on port 8011, external artifact-root writes,
push/PR/merge, release, main, tag, and Runtime remain outside Task 7 and were not
authorized or performed.
