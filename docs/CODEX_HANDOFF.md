# CODEX_HANDOFF.md

生成时间：2026-07-07

## 1. 接手结论

当前分支应为 `codex/project-summary-doc-cleanup`。接手时必须先运行 `git status --short --branch`，不要覆盖非本轮任务文件。

Stage 2C / 2D / 2E 已完成，Stage 3A / 3B 已完成代码级闭环，Stage 4A `LIVE-1M-4A-DESIGN` 已完成设计落地，Stage 4B `LIVE-1M-4B-MINIMAL-INGEST` 已完成代码级闭环，Stage 5 `LIVE-1M-5-MULTI-TF-AGGREGATION` 已完成代码级闭环，Stage 6A `LIVE-1M-6A-EXPLICIT-LIVE-MARKET-VIEW` 已完成代码级闭环。

下一步建议进入独立新会话：

```text
LIVE-1M-6B-LIVE-EVALUATOR-READONLY-PLAN
```

下一阶段建议先在 Plan 模式下规划策略中心 live evaluator 的显式只读接入。不要直接写正式 `StrategySignal`，不要接企业微信或策略推送，不要改变默认 signal scanner historical 读取路径。

## 2. 必读文件

1. `AGENTS.md`
2. `README.md`
3. `tasks/current.md`
4. `docs/LIVE_1M_INGEST_DESIGN.md`
5. `docs/gpt/CURRENT_STATE.md`
6. `docs/gpt/PROJECT_SNAPSHOT.md`
7. `docs/gpt/NEXT_STEPS.md`
8. `docs/ARCHITECTURE.md`
9. `docs/DATA_CENTER.md`
10. `docs/BACKTEST_ENGINE.md`
11. `docs/STRATEGY_CURRENT_STATE.md`

## 3. 当前数据事实

JM v2 历史数据已完成：

```text
1m / 5m / 15m / 30m / 60m / 1d
20230103_20260707_v2
provider = rqdata
data_role = primary
quality_status = passed
```

关键证据：

- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

## 4. 当前主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

active 数据入口：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

默认 Market / Backtest / Signal 读取仍只读取 active standard parquet，不读取 live DB 或 live 聚合 DB。

## 5. Stage 4B 实现结论

新增代码：

- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`

核心行为：

- 新增 `live_minute_bars` 和 `live_ingest_checkpoints`。
- `live_minute_bars` 唯一键为 `(provider, contract_code, period, bar_datetime)`。
- 使用 `RqDataClient.contract_bars(..., frequency="1m")` 作为后续真实拉取入口。
- 只处理当前分钟之前已经结束的 bar。
- 缺 `trading_day` 时标记 `quality_status=warning`，不硬推夜盘交易日。
- OHLC 等硬错误标记 `bar_status=rejected`、`quality_status=failed`。
- live DB 不登记 `market_data_files`，不进入默认 active 数据读取。

## 6. Stage 5 实现结论

新增代码：

- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`
- `services/quant-api/tests/test_live_multi_tf_aggregation.py`

更新代码：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`

核心行为：

- 新增 `live_aggregated_bars` 和 `live_aggregation_checkpoints`。
- `live_aggregated_bars` 唯一键为 `(provider, contract_code, period, bar_datetime, source_mode)`。
- 只聚合 `bar_status=confirmed` 且 `quality_status != failed` 的 live 1m rows。
- 支持 `5m/15m/30m/60m`。
- `failed` / `rejected` 1m rows 不参与聚合。
- 最新正在形成的 bucket 不输出。
- closed partial bucket 输出 `quality_status=warning`，不伪装为 passed。
- 源 1m warning 会传导到聚合 warning。
- live 聚合 DB 不登记 `market_data_files`，不进入默认 active 数据读取。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_multi_tf_aggregation.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api python scripts/rqdata_live_multi_tf_aggregate.py --contract JM2609 --symbol jm --exchange DCE --periods 5m,15m,30m,60m --once --dry-run
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api ruff check services/quant-api/app/services/live_multi_tf_aggregation.py services/quant-api/tests/test_live_multi_tf_aggregation.py scripts/rqdata_live_multi_tf_aggregate.py services/quant-api/app/models/data_center.py services/quant-api/app/models/__init__.py
git diff --check
```

结果：

- live aggregation 单测：`7 passed`。
- live ingest 回归：`8 passed`。
- MarketDataReader 回归：`4 passed`。
- CLI dry-run：通过，确认不打开 DB session、不写 DB、不写 parquet、不登记 `market_data_files`、不触发策略、不运行回测、不发企业微信。
- Alembic：已升级到 `20260707_0014`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 7. 禁止事项

- 不接企业微信，不读取或打印 `QYWX_WEBHOOK_URL`。
- 不触发策略扫描。
- 不运行回测。
- 不自动下单，不生成订单草稿。
- 不运行长期 scheduler。
- 不把 live DB 或 live 聚合 DB 数据登记成 trusted standard parquet。
- 不恢复 TqSdk 为 V1 active 主链路。
- 不把 validation、legacy_reference、candidate、failed 数据作为正式默认读取。
- 不提交 `.env`、账号、密码、API Key、webhook、token、license。

## 8. Stage 6A 实现结论

新增代码：

- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/tests/test_live_market_reader.py`

更新代码：

- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/tests/test_market_data_api.py`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/index.vue`

核心行为：

- 新增 `GET /api/v1/market/live/coverage` 和 `GET /api/v1/market/live/bars`。
- `period=1m` 读取 `live_minute_bars`。
- `period=5m/15m/30m/60m` 读取 `live_aggregated_bars`。
- chart bars 默认排除 `quality_status=failed` 或 `bar_status=rejected` rows。
- response quality summary 保留 `failed_count` / `rejected_count` / `partial_count`。
- Market 工作台新增 `historical` / `live` 模式；默认仍为 `historical`。
- live 模式显示 `Live Observation`、`source_mode` 和 Live 质量摘要。
- 默认 Market / Backtest / Signal 读取仍不读取 live DB。

已验证：

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

## 9. GPT 同步文件

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
