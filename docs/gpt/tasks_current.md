# 当前任务同步：LIVE-1M-4B-MINIMAL-INGEST

生成时间：2026-07-07

## 最新状态

`LIVE-1M-4B-MINIMAL-INGEST` 已完成最小代码闭环。

本轮新增 live PostgreSQL 独立层、SQLAlchemy models、最小 ingest service、dry-run / once CLI 和单元测试。默认 Market / Backtest / Signal 仍只读取 active standard parquet，不读取 live DB。

## 关键输出

新增：

- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`

更新：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/services/market_data_reader.py`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/LIVE_1M_INGEST_DESIGN.md`

## 实现结论

4B 第一版仍采用：

```text
RqDataClient.contract_bars(contract, start_date, end_date, "1m")
```

作为准实时 confirmed 1m 拉取入口。

新增 live 表：

- `live_minute_bars`
- `live_ingest_checkpoints`

关键规则：

- `live_minute_bars` 唯一键为 `(provider, contract_code, period, bar_datetime)`。
- 每轮从 checkpoint 回看固定窗口，默认 10 分钟。
- 只处理当前分钟之前已经结束的 bar。
- 缺 `trading_day` 标记 `quality_status=warning`，不硬推夜盘交易日。
- OHLC 等硬错误标记 `bar_status=rejected`、`quality_status=failed`。
- 同一分钟 bar 发生数值或状态变化时 `revision += 1`。
- live DB 不登记 `market_data_files`，不进入默认 active 数据读取。
- `MarketDataReader` 仅补充同一 `datetime` 下的确定性 provider 排序，active 过滤条件不变。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api python scripts/rqdata_live_1m_ingest.py --contract JM2609 --symbol jm --exchange DCE --once --dry-run
git diff --check
```

结果：

- `test_live_1m_ingest.py`：`8 passed`。
- `test_market_data_reader.py`：`4 passed`。
- CLI dry-run：通过，确认不构造 RQData client、不打开 DB session、不写 DB、不写 parquet、不触发策略、不发送企业微信。
- `git diff --check`：通过。

Alembic：

- `uv run --project services/quant-api python -m alembic upgrade head` 从仓库根目录执行失败，原因是 cwd 下没有 Alembic `script_location`。
- `cd services/quant-api && uv run python -m alembic upgrade head` 已通过，并将本地 PostgreSQL 升级到 `20260707_0013`。

## 本轮没有做

- 没有执行真实 RQData 非 dry-run 写库。
- 没有接企业微信。
- 没有触发策略扫描或回测。
- 没有自动下单或生成订单草稿。
- 没有做多周期聚合。
- 没有运行长期 scheduler。
- 没有接 websocket / tick 聚合。
- 没有恢复 TqSdk 为 V1 active 主链路。

## 下一步建议

建议新 Codex 会话 + Plan 模式进入：

```text
LIVE-1M-5-MULTI-TF-AGGREGATION-PLAN
```

下一阶段应先定 1m confirmed live rows 聚合为 5m / 15m / 30m / 60m 的口径，再考虑 Web 展示或策略扫描。

## 建议 GPT 上传文件

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
