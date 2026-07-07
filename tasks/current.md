# 当前任务：LIVE-1M-5-MULTI-TF-AGGREGATION

生成时间：2026-07-07
任务性质：RQData live 1m confirmed bar 多周期聚合实现

## 当前结论

`LIVE-1M-5-MULTI-TF-AGGREGATION` 已完成最小代码闭环。

本轮新增 PostgreSQL live 聚合层 schema、SQLAlchemy models、1m -> 5m / 15m / 30m / 60m 聚合 service、dry-run / once CLI 和单元测试。聚合结果仍是独立 live 层，不登记为 trusted standard parquet，不自动进入默认 Market / Backtest / Signal 读取。

## 本轮变更

### 1. live aggregation schema

新增 Alembic migration：

- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`

新增两张表：

- `live_aggregated_bars`
- `live_aggregation_checkpoints`

关键约束：

- `live_aggregated_bars` 唯一键为 `(provider, contract_code, period, bar_datetime, source_mode)`。
- `live_aggregation_checkpoints` 唯一键为 `(provider, contract_code, period, source_mode)`。
- live 聚合表只服务后续显式 live 观察、Web 展示或策略评估接入，不修改 `market_data_files` active 入口。

### 2. SQLAlchemy models

更新：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`

新增：

- `LiveAggregatedBar`
- `LiveAggregationCheckpoint`

### 3. aggregation service

新增：

- `services/quant-api/app/services/live_multi_tf_aggregation.py`

实现：

- 只读取 `provider="rqdata"`、`period="1m"` 的 live rows。
- 只聚合 `bar_status="confirmed"` 且 `quality_status != "failed"` 的 1m rows。
- `failed` / `rejected` 1m rows 不参与聚合，并计入 `excluded_row_count`。
- 支持目标周期：`5m`、`15m`、`30m`、`60m`。
- 分桶口径：按 `contract + trading_day + session_gap_block + sequential_bucket` 思路，当前最小实现以相邻 1m `bar_datetime` gap `> 90s` 识别新 session block。
- 聚合 bar 的 `bar_datetime` 使用最后一根纳入的 1m bar 时间，避免使用未来 bar。
- 最新正在形成的 bucket 不输出；只有被后续 1m row 或 session gap 证明闭合的 bucket 才输出。
- 闭合但不足目标根数的 bucket 写入 `quality_status="warning"`，`raw_payload.quality_reasons` 包含 `incomplete_source_bucket`。
- 源 1m 存在 warning 时聚合结果传导为 `quality_status="warning"`，`raw_payload.quality_reasons` 包含 `source_quality_warning`。
- OHLCV 规则：open=第一根，high=max，low=min，close=最后一根，volume/turnover=sum，open_interest=最后一根。
- 重复聚合按唯一键 upsert；聚合值或状态变化时 `revision += 1`。
- 每个目标周期单独更新 checkpoint 状态和摘要。

### 4. CLI

新增：

- `scripts/rqdata_live_multi_tf_aggregate.py`

支持：

```bash
uv run --project services/quant-api python scripts/rqdata_live_multi_tf_aggregate.py \
  --contract JM2609 \
  --symbol jm \
  --exchange DCE \
  --periods 5m,15m,30m,60m \
  --once \
  --dry-run
```

Stage 5 dry-run 行为：

- 不打开 DB session。
- 不写 PostgreSQL。
- 不写 parquet。
- 不登记 `market_data_files`。
- 不触发策略。
- 不运行回测。
- 不发送企业微信。
- 不打印凭据原文，只输出环境变量 present / missing。

非 dry-run 仅支持 `--once`，不支持长期 scheduler / daemon。

### 5. 单元测试

新增：

- `services/quant-api/tests/test_live_multi_tf_aggregation.py`

覆盖：

- 1m -> 5m / 15m 完整聚合。
- 当前未收盘 bucket 不输出。
- session gap 后不足根数的闭合 bucket 标记 warning。
- `rejected` / `failed` 1m rows 不参与聚合。
- 源 1m warning 传导到聚合 warning。
- 重复执行不重复插入。
- 源数据修订后聚合 `revision` 递增。
- service dry-run 不写聚合表或 checkpoint。
- CLI dry-run 不打开 DB、不泄露 webhook、不发送企业微信。
- 聚合表不登记 `market_data_files`。

## 本轮没有做

- 没有接企业微信。
- 没有触发策略扫描。
- 没有运行回测。
- 没有自动下单或生成订单草稿。
- 没有接 Web live 展示。
- 没有运行长期 scheduler。
- 没有接 websocket / tick 聚合。
- 没有恢复 TqSdk 为 V1 active 主链路。
- 没有把 live DB 或 live 聚合 DB 数据登记为 trusted standard parquet。
- 没有把 live DB 混入默认 Market / Backtest / Signal 读取。

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

- live multi-tf aggregation 单测：`7 passed`。
- live ingest 回归：`8 passed`。
- MarketDataReader 回归：`4 passed`。
- CLI dry-run：通过，输出确认不打开 DB session、不写 DB、不写 parquet、不登记 `market_data_files`、不触发策略、不运行回测、不发送企业微信。
- Alembic：已将本地 PostgreSQL 从 `20260707_0013` 升级到 `20260707_0014`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 风险与未完成项

- Stage 5 真实非 dry-run 聚合尚未对真实 live 1m 数据执行；当前验证以构造的 1m live rows 为主。
- 当前没有交易所 session calendar，第一版以相邻 1m gap `> 90s` 识别 session block；这是最小可解释口径，不是最终权威交易时段日历。
- 60m 在午休、夜盘断点附近可能生成 warning partial bar；这是刻意保守处理，避免把缺根数 bucket 伪装为 passed。
- live 聚合结果仍不是可信历史回测数据；后续如果给策略扫描使用，必须显式接入并单独做风险提示和回归测试。

## 下一步

建议进入：

```text
LIVE-1M-6-EXPLICIT-LIVE-VIEW-OR-EVALUATOR-PLAN
```

下一阶段可二选一先规划：

- Web Market 显式查看 live 1m / 聚合多周期数据；
- 或策略中心 live evaluator 的显式只读接入。

仍不建议直接接企业微信，先让 live 数据可观察、可解释、可回放。

## GPT 同步文件

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
