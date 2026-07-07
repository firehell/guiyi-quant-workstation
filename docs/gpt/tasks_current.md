# 当前任务同步：LIVE-1M-6A-EXPLICIT-LIVE-MARKET-VIEW

生成时间：2026-07-07

## 最新状态

`LIVE-1M-6A-EXPLICIT-LIVE-MARKET-VIEW` 已完成最小代码闭环。

本轮新增独立 live Market 只读入口和 Web Market 显式 live 模式。默认 Market / Backtest / Signal 仍只读取 active standard parquet；只有用户在 Market 工作台切换到 `live` 模式时，才读取 `live_minute_bars` / `live_aggregated_bars`。

## 关键输出

新增：

- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/tests/test_live_market_reader.py`

更新：

- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/tests/test_market_data_api.py`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/index.vue`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/LIVE_1M_INGEST_DESIGN.md`

## 实现结论

新增 API：

```text
GET /api/v1/market/live/coverage
GET /api/v1/market/live/bars
```

关键规则：

- `period=1m` 读取 `LiveMinuteBar`。
- `period=5m/15m/30m/60m` 读取 `LiveAggregatedBar`。
- live API 支持 `provider` / `source_mode` 显式过滤。
- chart bars 默认排除 `quality_status=failed` 或 `bar_status=rejected` rows。
- response quality summary 保留 `failed_count` / `rejected_count` / `partial_count`。
- warning / partial live bar 在 API 和 UI 中可见，不伪装为 `passed`。
- live coverage 不登记 `market_data_files`。
- Web Market 默认 `historical`，只有 `data_mode=live` 或用户切换 live 时才请求 live endpoints。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_market_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py services/quant-api/tests/test_live_multi_tf_aggregation.py
uv run --project services/quant-api ruff check services/quant-api/app/api/market.py services/quant-api/app/services/live_market_reader.py services/quant-api/app/schemas/market.py services/quant-api/app/services/market_workbench.py services/quant-api/tests/test_live_market_reader.py services/quant-api/tests/test_market_data_api.py
npm --prefix apps/quant-web run build
curl -sS http://127.0.0.1:8000/healthz
curl -sS -I http://127.0.0.1:5173/market
curl -sS http://127.0.0.1:5173/api/health
git diff --check
```

结果：

- `test_live_market_reader.py`：`3 passed`。
- `test_market_data_api.py`：`4 passed`。
- `test_market_data_reader.py`：`4 passed`。
- live ingest + aggregation 回归：`15 passed`。
- `ruff check`：通过。
- 前端 build：通过。
- HTTP smoke：`/healthz`、Vite `/market`、前端代理 `/api/health` 均通过。
- Browser smoke：Market 默认 historical 渲染成功；点击 `Live` 后 URL 变为 `data_mode=live`，页面显示 `Live Observation` 和 `Live 质量`，应用 console error 为 0。
- `git diff --check`：通过。

## 本轮没有做

- 没有新增 migration。
- 没有改 `MarketDataReader` active filter。
- 没有做 historical/live 拼接。
- 没有触发策略扫描或回测。
- 没有写 `StrategySignal`。
- 没有接企业微信。
- 没有运行 scheduler / daemon。
- 没有下单或生成订单草稿。

## 下一步建议

建议新 Codex 会话 + Plan 模式进入：

```text
LIVE-1M-6B-LIVE-EVALUATOR-READONLY-PLAN
```

下一阶段只规划策略中心 live evaluator 的显式只读接入；仍不建议直接接企业微信。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/LIVE_1M_INGEST_DESIGN.md`
- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/tests/test_live_market_reader.py`
- `services/quant-api/tests/test_market_data_api.py`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/index.vue`
