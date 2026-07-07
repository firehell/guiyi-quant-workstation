# 当前任务同步：LIVE-1M-5-MULTI-TF-AGGREGATION

生成时间：2026-07-07

## 最新状态

`LIVE-1M-5-MULTI-TF-AGGREGATION` 已完成最小代码闭环。

本轮新增 live 多周期聚合 PostgreSQL 独立层、SQLAlchemy models、aggregation service、dry-run / once CLI 和单元测试。默认 Market / Backtest / Signal 仍只读取 active standard parquet，不读取 live DB 或 live 聚合 DB。

## 关键输出

新增：

- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`
- `services/quant-api/tests/test_live_multi_tf_aggregation.py`

更新：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/LIVE_1M_INGEST_DESIGN.md`

## 实现结论

新增 live 聚合表：

- `live_aggregated_bars`
- `live_aggregation_checkpoints`

关键规则：

- `live_aggregated_bars` 唯一键为 `(provider, contract_code, period, bar_datetime, source_mode)`。
- 只聚合 `provider="rqdata"`、`period="1m"`、`bar_status="confirmed"` 且 `quality_status != "failed"` 的 live rows。
- 支持目标周期：`5m`、`15m`、`30m`、`60m`。
- `failed` / `rejected` 1m rows 不参与聚合。
- 分桶口径为 `contract + trading_day + session_gap_block + sequential_bucket`；当前以相邻 1m gap `> 90s` 识别新 session block。
- 聚合 bar 的 `bar_datetime` 使用最后一根纳入的 1m bar 时间。
- 最新正在形成的 bucket 不输出。
- 闭合但不足根数的 bucket 输出 `quality_status="warning"`，并记录 `incomplete_source_bucket`。
- 源 1m warning 会传导到聚合 warning，并记录 `source_quality_warning`。
- OHLCV 规则：open=第一根，high=max，low=min，close=最后一根，volume/turnover=sum，open_interest=最后一根。
- 重复聚合按唯一键 upsert；聚合值或状态变化时 `revision += 1`。
- live 聚合 DB 不登记 `market_data_files`，不进入默认 active 数据读取。

## 验证结果

已运行：

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

- `test_live_multi_tf_aggregation.py`：`7 passed`。
- `test_live_1m_ingest.py`：`8 passed`。
- `test_market_data_reader.py`：`4 passed`。
- CLI dry-run：通过，确认不打开 DB session、不写 DB、不写 parquet、不登记 `market_data_files`、不触发策略、不运行回测、不发送企业微信。
- Alembic：已升级到 `20260707_0014`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 本轮没有做

- 没有执行真实 live 1m 非 dry-run 聚合。
- 没有接企业微信。
- 没有触发策略扫描或回测。
- 没有自动下单或生成订单草稿。
- 没有接 Web live 展示。
- 没有运行长期 scheduler。
- 没有接 websocket / tick 聚合。
- 没有恢复 TqSdk 为 V1 active 主链路。
- 没有把 live 聚合 DB 登记为 trusted standard parquet。

## 下一步建议

建议新 Codex 会话 + Plan 模式进入：

```text
LIVE-1M-6-EXPLICIT-LIVE-VIEW-OR-EVALUATOR-PLAN
```

下一阶段建议先规划 Web Market 显式查看 live 1m / 聚合多周期数据，或策略中心 live evaluator 的显式只读接入。仍不建议直接接企业微信。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/LIVE_1M_INGEST_DESIGN.md`
- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`
- `services/quant-api/tests/test_live_multi_tf_aggregation.py`
