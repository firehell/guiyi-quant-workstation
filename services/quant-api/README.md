# quant-api

归一量化 FastAPI 后端与统一 CLI（`guiyi`）。

## Current mounted surface

- `/api/v1/market`：Canonical bars/page、coverage、dominants、Historical/Live state 与 WebSocket。
- `/api/runtime`：DB、Redis、Live 与 after-market 的只读 Runtime 状态。
- CLI：`guiyi data update|refresh|audit|retire-products|after-market`、
  `guiyi runtime status|live`。

## Unmounted / retired

- `/api/signals`、`/ws/signals`、`/api/v1/strategies`、`/api/dashboard`、`/api/reviews`、watchlists、futures_research。
- `/api/backtests/**`、`/ws/backtests/**`、`guiyi-backtests` worker/queue。
- poll Live `/market/live/*`、`guiyi data live`、signal/notification RQ worker/queue 入口。
- `guiyi runtime plan`。

Active PostgreSQL 数据模型只有八表 Market Catalog；Signal/Review/Strategy 表与应用语义已经退役。

## 本地

```bash
uv run --project services/quant-api guiyi --help
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests
```

边界见 `STATUS.md`、`AGENTS.md`、`TESTING.md`。
