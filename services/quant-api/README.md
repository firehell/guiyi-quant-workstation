# Quant API

FastAPI 后端的 active surface：

- `/api/v1/market/*`：Canonical/Live bars、dominants 与通用市场视图。
- `/api/alerts/*`：HTDY Rule、symbol × frequency Scope 与 immutable Event。
- `/api/runtime/*`：只读 Runtime 状态。
- CLI：`guiyi data ...` 与 `guiyi runtime ...`。

EMA21 10K slope 位于 `packages/quant-core`，是无周期和策略语义的纯函数。已退役策略的 API、CLI、Runtime、Rule、Scope 和 payload 不属于 active surface。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

测试不授权生产 PostgreSQL、Redis、Scope、通知或 Runtime mutation。
