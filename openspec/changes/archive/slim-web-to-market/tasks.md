## 1. Frontend shell

- [x] 1.1 Narrow `MainLayout.vue` menu to Market only; remove top-bar signal shortcut and SystemPulse
- [x] 1.2 Update `router.ts`: keep `market` + `market-chart`; redirect `/` to `/market`; remove other module routes
- [x] 1.3 Delete retired pages (`dashboard`, `signal`, `strategy`, `review`, `data`, `runtime`) and unused api/stores/types/utils/components/websocket tied only to them

## 2. Market chart slim

- [x] 2.1 Strip `chart.vue` signal layer, markers, signal API usage, and signal/review query restore
- [x] 2.2 Remove right-rail signal/review/runtime tabs (and related components/utils if unused)
- [x] 2.3 Remove FuturesResearch panel; keep bars + EMA10/21/60 + HTDY + MACD and essential chart controls

## 3. Backend unmount

- [x] 3.1 Unregister signals, signal WS, strategies, dashboard, reviews from `main.py`
- [x] 3.2 Unregister futures_research / watchlists if no remaining consumers; delete or stop dead router modules
- [x] 3.3 Stop RQ signal/notification worker entrypoints; leave models and quant-core strategy packages

## 4. Docs and verification

- [x] 4.1 Update `STATUS.md` retained-module wording for Market-only Web and retired executable surfaces
- [x] 4.2 Fix or remove broken frontend/backend tests referencing deleted surfaces
- [x] 4.3 Run directed frontend build and backend pytest for market/data/runtime; confirm old routes unmounted
