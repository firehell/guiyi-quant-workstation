# quant-api

归一量化 FastAPI 后端与统一 CLI（`guiyi`）。

## Current mounted surface

- `/api/v1/market`：Canonical bars、coverage、dominants、indicators（只读历史）。
- `/api/v1/data`：数据治理 API。
- `/api/runtime`：只读 Runtime 状态。
- CLI：`guiyi data update|audit`、`guiyi runtime status`。

## Unmounted / retired

- `/api/signals`、`/ws/signals`、`/api/v1/strategies`、`/api/dashboard`、`/api/reviews`、watchlists、futures_research。
- `/api/backtests/**`、`/ws/backtests/**`、`guiyi-backtests` worker/queue。
- poll Live `/market/live/*`、`guiyi data live`、signal/notification RQ worker 入口。
- `guiyi runtime plan`。

DB 中 signal/review 等表可能仍存在（未 drop）；不得当作 mounted API。

## 本地

```bash
uv run --project services/quant-api guiyi --help
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests
```

边界见 `STATUS.md`、`AGENTS.md`、`TESTING.md`。
