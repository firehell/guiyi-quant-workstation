# quant-api

归一量化 FastAPI 后端与统一 CLI（`guiyi`）。

## Current mounted surface

- `/api/v1/market`：Canonical bars、dominants、product/SuBing/Daily Context/Radar 与 Historical overlays。
- `/api/alerts`：两条 code-defined Rule 的 server-side Scope、Event 与当前视图。
- `/api/execution-review`：SuBing Event 的人工 Decision、Episode/Execution timeline、Review、reconstruction 与 stats。
- `/api/runtime`：DB、Redis、Live、after-market 与 Alert 的只读状态。
- CLI：`guiyi data update|refresh|audit|after-market`；只读 `guiyi research subing-calibration`、`guiyi research subing-lifecycle`、`guiyi research n-structure`、`guiyi research jdj-1m`、`guiyi research candidate-validation`、`guiyi research candidate-robustness`；`guiyi runtime status|live|alert`。

`app.runtime_entry` 仅是受监督进程入口，不是用户 CLI，也不构成自然 Runtime evidence。Alert 与 Execution Review 为独立 Application Domain；Market Catalog 仍为八表。

## Unmounted / retired

旧 signal/review/strategy/backtest HTTP、worker/queue、poll Live、`guiyi data live` 与 `guiyi runtime plan` 已退役。RQAlpha 是独立 loopback app，不挂载此 API。

## 本地验证

```bash
uv sync --project services/quant-api --locked
uv run --project services/quant-api guiyi --help
uv run --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
```

稳定边界见 `PROJECT_SOURCE.md`，当前 release/Runtime/Gate 见 `STATUS.md`，完整命令见 `TESTING.md`。
