# quant-api

归一量化 FastAPI 后端与统一 CLI（`guiyi`）。

## Current mounted surface

- `/api/v1/market`：Canonical 历史分页、dominants、Historical/Live state 与 WebSocket。
- `/api/alerts`：Alert V2 两条 code-defined Rule 的 server-side Scope、Event 与当前视图。
- `/api/execution-review`：苏冰 Event 的人工 Decision、Episode/Execution timeline、Review、reconstruction 与 lightweight stats。
- `/api/runtime`：DB、Redis、Live、after-market 与 Alert 的只读 Runtime 状态。
- CLI：`guiyi data update|refresh|audit|after-market`、
  只读 `guiyi research subing-calibration`、`guiyi research subing-lifecycle`、
  `guiyi research n-structure`、`guiyi research jdj-1m`、
  `guiyi research candidate-validation`、`guiyi research candidate-robustness`、
  `guiyi research candidate-dossier`、`guiyi research candidate-relationships`、
  `guiyi research main-force-mirror-v2`、
  `guiyi runtime status|live|alert`；
  `guiyi runtime alert-canary` 是真实通知 Gate。
- `app.runtime_entry` 是 launchd/运维脚本的内部进程入口，只接受 `live | alert | after-market`；
  普通用户仍使用 `guiyi`，不得手工运行 `runtime_entry` 冒充自然 Runtime 证据。

## Unmounted / retired

- `/api/signals`、`/ws/signals`、`/api/v1/strategies`、`/api/dashboard`、`/api/reviews`、watchlists、futures_research。
- `/api/backtests/**`、`/ws/backtests/**`、`guiyi-backtests` worker/queue。
- poll Live `/market/live/*`、`guiyi data live`、signal/notification RQ worker/queue 入口。
- `guiyi runtime plan`。

Market Data Foundation 精确为八表 Catalog；`alert_rules` / `alert_events` 是独立 Alert Domain 两表，
四张 `trade_*` 表是独立 Execution Review Domain。旧 Signal/Review/Strategy 表与应用语义已退役；
Execution Review 不是旧 Review Center 的兼容入口。

## 本地

```bash
uv sync --project services/quant-api --locked
uv run --project services/quant-api guiyi --help
uv run --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
uv run --project services/quant-api pytest -q services/quant-api/tests/research
uv run --project services/quant-api pytest -q services/quant-api/tests/execution_review
uv run --project services/quant-api pytest -q services/quant-api/tests/test_runtime_entry.py
```

稳定接口边界见 `PROJECT_SOURCE.md`，当前 release/Runtime/Gate 见 `STATUS.md`，工程规则与命令分别见
`AGENTS.md`、`TESTING.md`。
