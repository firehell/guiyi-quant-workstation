# WEB-HTDY-ORIGINAL-OBSERVATION-W4501

Date: 2026-07-20

Status: `WEB_HTDY_ORIGINAL_OBSERVATION_READY`

## Goal

Enable `火天大有（原始观察）` as a Web-only historical/browser observation overlay, without promoting HTDY original or strict into formal research, backtest, live, alert, notification, or trading paths.

Allowed mode:

```text
data_mode=historical
access_mode=browser
```

Blocked modes:

```text
research
live
formal backtest evidence
alert/monitor
```

## Implementation Notes

- `apps/quant-web/src/utils/mainIndicators.ts` marks HTDY original as `observation_overlay`, `repaintingRisk=known`, `alertCapable=false`, and restricts it to historical/browser.
- `activeIndicatorCodes()` still emits only standard overlays, so HTDY is never sent to the backend Market indicators API.
- `apps/quant-web/src/pages/market/chart.vue` filters visible indicators by current mode, auto-closes HTDY when switching research/live, and displays the required risk text.
- `apps/quant-web/src/components/kline/KlineChart.vue` uses existing `calculateHuoTianDaYou()` to render ZK1/ZD1/ZD2, observation candles, observation markers, and `unstable` tail readouts.
- No backend source, Parquet, Profile semantics, StrategySignal, SignalEvent, Notification, strict-v1, report 14/15, or Stage 5 conclusion changes.
- Browser console smoke was initially blocked by the Runtime database being behind the API model (`strategy_signals.profile_id` and `market_data_file_id` missing). The existing migrations were applied to the Runtime database up to `20260718_0024 (head)`; no new migration was added.

## Verification

```text
command: node --test tests/mainIndicators.test.ts tests/indicators.test.ts tests/htdyGoldenSample.test.ts
cwd: apps/quant-web
result: 21 passed, 1 skipped
note: HTDY_GOLDEN_BUNDLE was not set, so the optional golden bundle test skipped.
```

```text
command: GUIYI_DATA_ROOT=/Volumes/扩展盘/guiyi-quant-workstation uv run --project services/quant-api python experiments/htdy_indicator/golden_sample.py --export-web-bundle /tmp/htdy_golden_web_bundle_w4501.json
result: GOLDEN_SAMPLE_PASS_VISUAL_ORACLE
row_count: 256
```

```text
command: HTDY_GOLDEN_BUNDLE=/tmp/htdy_golden_web_bundle_w4501.json node --test tests/htdyGoldenSample.test.ts
cwd: apps/quant-web
result: 1 passed, 0 skipped
```

```text
command: node --test tests/*.test.ts
cwd: apps/quant-web
result: 77 passed, 1 skipped
```

```text
command: pnpm build
cwd: apps/quant-web
result: passed
```

```text
command: git -c core.fsmonitor=false diff --check
result: passed
```

Browser smoke on `http://127.0.0.1:5176/market/chart?symbol=jm&contract=JM2609&period=15m`:

- PASS: historical/browser HTDY checkbox enabled.
- PASS: HTDY risk text displayed.
- PASS: HTDY renders SVG observation overlay and markers.
- PASS: hover readout shows ZK1/ZD1/ZD2 with `unstable` tail labels.
- PASS: research mode auto-closes HTDY and disables its row.
- PASS: research/no-profile mode does not emit coverage 422 console errors.
- PASS: live mode auto-closes HTDY and keeps it closed.
- PASS: forced localStorage `["ema_21","htdy"]` does not reopen HTDY in live mode and is filtered back to `["ema_21"]`.
- PASS: Market indicators API request remained `indicator_codes=ema21`; no HTDY backend indicator request.
- PASS: no alert/monitor affordance was introduced for HTDY.
- PASS: browser console final smoke had 0 errors.
- PASS: `/api/signals/latest?...` returned HTTP 200 after Runtime DB migration.

## Gate

Do not claim:

```text
HTDY_WEB_FORMAL_READY
HTDY_LIVE_READY
HTDY_ALERT_READY
```

Claim:

```text
WEB_HTDY_ORIGINAL_OBSERVATION_READY
```
