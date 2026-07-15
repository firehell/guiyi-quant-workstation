# WEB-MARKET-UX-001 Result

status: GATE_PASSED
updated_at: 2026-07-14

## Summary

Closed the A01 build blocker and completed browser smoke for the current worktree.

## Changed Files

- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/utils/barTime.ts`
- `apps/quant-web/tests/barTime.test.ts`
- `docs/tasks/web-market-ux/WEB-MARKET-UX-001.md`
- `.ai/results/WEB-MARKET-UX-001/result.md`
- `tasks/current.md`

## Verification

Passed:

```bash
node --test apps/quant-web/tests/mainIndicators.test.ts
node --test apps/quant-web/tests/barTime.test.ts
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
API_BASE_URL=http://127.0.0.1:8010 WEB_BASE_URL=http://127.0.0.1:5174 ./scripts/dev-healthcheck.sh --no-start --allow-degraded
```

Playwright smoke passed on current worktree via:

```text
http://127.0.0.1:5174/market/chart?symbol=jm&contract=JM2609&period=15m
```

Evidence:

- Screenshot directory: `output/playwright/web-market-ux/WEB-MARKET-UX-001/`
- Console: 0 errors, 0 warnings.
- Network: market bars, C2 EMA indicators, MACD, signal latest all returned 200 during smoke.
- Periods covered: `1m`, `15m`, `1d`, `1w`.

## Notes

The default local ports `8000/5173` were occupied by supervised runtime processes under `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` and automatically restarted. Current-worktree smoke therefore used API `8010` and Web `5174`.

No API code, DB schema, Parquet files, RQData download, strategy logic, SignalEvent, Stage 9, notification, or trading runtime logic was changed.

## Gate

```text
WEB-MARKET-UX-001 GATE_PASSED
```

Next allowed step: `WEB-MARKET-UX-002` read-only `1d` duplicate K diagnosis.
