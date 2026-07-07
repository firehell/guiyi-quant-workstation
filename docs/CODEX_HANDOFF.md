# CODEX_HANDOFF.md

生成时间：2026-07-07

## 1. 接手结论

当前分支应为 `codex/project-summary-doc-cleanup`。工作区已有较多未提交改动，接手时必须先运行 `git status --short --branch`，不要覆盖非本轮任务文件。

Stage 2C / 2D / 2E 已完成，Stage 3A / 3B 已完成代码级闭环，Stage 4A `LIVE-1M-4A-DESIGN` 已完成设计落地，Stage 4B `LIVE-1M-4B-MINIMAL-INGEST` 已完成代码级闭环。

下一步建议进入独立新会话：

```text
LIVE-1M-5-MULTI-TF-AGGREGATION-PLAN
```

下一阶段先设计 1m confirmed live rows 聚合为 5m / 15m / 30m / 60m 的口径，不要直接接策略扫描或企业微信。

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

JM v2 数据已完成：

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

默认 Market / Backtest / Signal 读取仍只读取 active standard parquet，不读取 live DB。

## 5. Stage 4A 设计结论

设计文档：

- `docs/LIVE_1M_INGEST_DESIGN.md`

核心结论：

- 4B 第一版使用 `RqDataClient.contract_bars(..., frequency="1m")` 做准实时 confirmed 1m 拉取。
- `LiveMarketDataClient`、`get_live_ticks`、`current_snapshot` 仅作为后续候选入口。
- `current_minute` 因文档口径存在矛盾，不作为第一版默认依赖。
- live 数据先进入 PostgreSQL 独立 live 层，不复用 `market_data_files`。
- live 数据不自动混入默认 Market / Backtest / Signal 读取。
- 夜盘必须同时保存自然时间 `bar_datetime` 和交易日 `trading_day`。

## 6. Stage 4B 实现结论

新增代码：

- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`

更新代码：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/services/market_data_reader.py`

核心行为：

- 新增 `live_minute_bars` 和 `live_ingest_checkpoints`。
- `live_minute_bars` 唯一键为 `(provider, contract_code, period, bar_datetime)`。
- 使用 `RqDataClient.contract_bars(..., frequency="1m")` 作为后续真实拉取入口。
- 每轮从 checkpoint 回看固定窗口，默认 10 分钟。
- 只处理当前分钟之前已经结束的 bar。
- 缺 `trading_day` 时标记 `quality_status=warning`，不硬推夜盘交易日。
- OHLC 等硬错误标记 `bar_status=rejected`、`quality_status=failed`。
- 同一分钟重复写入按唯一键 upsert；数值或状态变化时 `revision += 1`。
- live DB 不登记 `market_data_files`，不进入默认 active 数据读取。
- `MarketDataReader` 只补充同一 `datetime` 下的确定性 provider 排序，active 过滤条件不变。

已验证：


```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api python scripts/rqdata_live_1m_ingest.py --contract JM2609 --symbol jm --exchange DCE --once --dry-run
git diff --check
```

结果：

- live ingest 单测：`8 passed`。
- MarketDataReader 回归：`4 passed`。
- Alembic：已将本地 PostgreSQL 升级到 `20260707_0013`。
- CLI dry-run：通过，确认不构造 RQData client、不打开 DB session、不写 DB、不写 parquet、不触发策略、不发企业微信。

## 7. 禁止事项

- 不接企业微信，不读取或打印 `QYWX_WEBHOOK_URL`。
- 不触发策略扫描。
- 不运行回测。
- 不自动下单，不生成订单草稿。
- 不做多周期聚合。
- 不运行长期 scheduler。
- 不把 live DB 数据登记成 trusted standard parquet。
- 不恢复 TqSdk 为 V1 active 主链路。
- 不把 validation、legacy_reference、candidate、failed 数据作为正式默认读取。
- 不提交 `.env`、账号、密码、API Key、webhook、token、license。

## 8. GPT 同步文件

- `docs/LIVE_1M_INGEST_DESIGN.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/services/market_data_reader.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`
