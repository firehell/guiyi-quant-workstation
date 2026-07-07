# 当前任务：LIVE-1M-6A-EXPLICIT-LIVE-MARKET-VIEW

生成时间：2026-07-07
任务性质：显式 live 1m / 聚合多周期 Market 查看入口

## 当前结论

`LIVE-1M-6A-EXPLICIT-LIVE-MARKET-VIEW` 已完成最小代码闭环。

本轮新增独立 live Market 只读入口，Web Market 工作台默认仍为 historical 模式；只有用户显式切换到 live 模式时，前端才请求 `live_minute_bars` / `live_aggregated_bars`。默认 Market / Backtest / Signal 读取仍只读 active standard parquet，不读取 live DB。

## 本轮变更

### 1. 后端 live Market reader

新增：

- `services/quant-api/app/services/live_market_reader.py`

实现：

- `period=1m` 读取 `LiveMinuteBar`。
- `period=5m/15m/30m/60m` 读取 `LiveAggregatedBar`。
- 支持按 `symbol` / `contract` / `period` / `start` / `end` / `provider` / `source_mode` / `limit` 查询。
- chart bars 默认排除 `quality_status="failed"` 或 `bar_status="rejected"` 的 rows。
- response quality summary 仍统计 `failed_count` / `rejected_count`，避免坏行静默消失。
- warning / partial bucket 可见，不伪装为 `passed`。
- coverage 从 live 表聚合，不读取或写入 `market_data_files`。

### 2. 后端 API / schema

更新：

- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`

新增 API：

```text
GET /api/v1/market/live/coverage
GET /api/v1/market/live/bars
```

新增或扩展返回字段：

- `bar_status`
- `quality_status`
- `source_mode`
- `revision`
- `source_bar_count`
- `expected_bar_count`
- `quality_reasons`
- `failed_count`
- `rejected_count`
- `partial_count`

`/api/v1/market/live/bars` 仅允许：

```text
1m / 5m / 15m / 30m / 60m
```

### 3. 前端 Market 显式 live 模式

更新：

- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/index.vue`

实现：

- Market 左侧新增数据模式切换：`historical` / `live`。
- 默认模式仍为 `historical`。
- URL 仅在 live 模式写入 `data_mode=live`。
- historical 模式继续请求 `/api/v1/market/workbench/coverage` 和 `/api/v1/market/bars`。
- live 模式请求 `/api/v1/market/live/coverage` 和 `/api/v1/market/live/bars`。
- live 模式显示 `Live Observation`、`source_mode`、row count、latest coverage。
- 右侧新增 `Live 质量` 摘要，展示 chart rows、raw rows、warning、partial、failed、rejected。
- K 线图继续复用 `KlineChart.vue`。

### 4. 测试

新增：

- `services/quant-api/tests/test_live_market_reader.py`

更新：

- `services/quant-api/tests/test_market_data_api.py`

覆盖：

- 1m 从 `LiveMinuteBar` 读取。
- 5m 聚合周期从 `LiveAggregatedBar` 读取。
- warning bar 可返回且不被标记为 passed。
- partial bucket metadata 可见。
- failed / rejected rows 不进入 chart bars，但进入 quality summary count。
- live coverage 不登记 `market_data_files`。
- 默认 historical API 不读取 live rows。
- live API 只支持 `1m/5m/15m/30m/60m`。

## 本轮没有做

- 没有新增 Alembic migration。
- 没有改 `MarketDataReader` active filter。
- 没有写 `market_data_files`。
- 没有把 live DB 登记为 trusted standard parquet。
- 没有做 historical/live 拼接。
- 没有触发策略扫描。
- 没有写 `StrategySignal`。
- 没有接企业微信。
- 没有运行 scheduler / daemon。
- 没有自动下单或生成订单草稿。

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
- 前端 `npm build`：通过。
- HTTP smoke：`/healthz`、Vite `/market`、前端代理 `/api/health` 均通过。
- Browser smoke：Market 默认 historical 渲染成功；点击 `Live` 后 URL 变为 `data_mode=live`，页面显示 `Live Observation` 和 `Live 质量`，应用 console error 为 0。
- `git diff --check`：通过。

## 风险与未完成项

- 当前真实 live 非 dry-run 数据未必存在；本轮以构造 DB rows 验证 reader/API/UI 类型链路。
- 未做浏览器页面人工验收；已完成前端 build，后续如启动本地服务可补 Browser/Chrome smoke。
- `60m` 在午休、夜盘断点附近可能出现 partial warning；本轮只展示，不做权威交易时段修正。
- live 数据仍不是可信历史回测数据，不进入默认 Market / Backtest / Signal。

## 下一步

建议进入：

```text
LIVE-1M-6B-LIVE-EVALUATOR-READONLY-PLAN
```

下一阶段只规划策略中心 live evaluator 的显式只读接入，必须继续保持：

- 不写正式 `StrategySignal`。
- 不推送企业微信。
- 不自动下单。
- 不改变默认 signal scanner historical 读取路径。

## GPT 同步文件

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
