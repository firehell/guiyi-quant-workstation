# 当前任务：LIVE-1M-4B-MINIMAL-INGEST

生成时间：2026-07-07
任务性质：RQData 准实时 1m confirmed bar 最小入库实现

## 当前结论

`LIVE-1M-4B-MINIMAL-INGEST` 已完成最小代码闭环。

本轮新增 PostgreSQL live 层 schema、SQLAlchemy models、最小 ingest service、dry-run / once CLI 和单元测试。live 数据仍是独立层，不自动进入默认 Market / Backtest / Signal 读取，不登记为 trusted standard parquet。

## 本轮变更

### 1. live schema

新增 Alembic migration：

- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`

新增两张表：

- `live_minute_bars`
- `live_ingest_checkpoints`

关键约束：

- `live_minute_bars` 唯一键为 `(provider, contract_code, period, bar_datetime)`。
- `live_ingest_checkpoints` 唯一键为 `(provider, contract_code, period, source_mode)`。
- live 表只服务后续显式 live 拼接和观察，不修改 `market_data_files` active 入口。

### 2. SQLAlchemy models

更新：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/services/market_data_reader.py`

新增：

- `LiveMinuteBar`
- `LiveIngestCheckpoint`

### 3. ingest service

新增：

- `services/quant-api/app/services/live_1m_ingest.py`

实现：

- 使用 `RqDataClient.contract_bars(..., frequency="1m")` 作为后续真实拉取入口。
- 每次从 checkpoint 回看固定窗口，默认 10 分钟。
- 只处理当前分钟之前已结束的 bar，保守跳过当前分钟。
- 字段归一：`bar_datetime`、`trading_day`、OHLC、volume、open_interest、turnover。
- 最小质量检查：缺时间、缺合约、缺 trading_day、OHLC 非法、负 volume、负 open_interest。
- 缺 `trading_day` 时标记 `quality_status=warning`，不硬推夜盘交易日。
- OHLC 等硬错误标记 `bar_status=rejected`、`quality_status=failed`。
- 同一分钟重复写入按唯一键 upsert；OHLCV/OI/turnover 或状态变化时 `revision += 1`。
- 成功、warning、failed 均更新 checkpoint 状态和摘要。

### 4. CLI

新增：

- `scripts/rqdata_live_1m_ingest.py`

支持：

```bash
uv run --project services/quant-api python scripts/rqdata_live_1m_ingest.py \
  --contract JM2609 \
  --symbol jm \
  --exchange DCE \
  --once \
  --dry-run
```

4B dry-run 行为：

- 不构造 RQData client。
- 不打开 DB session。
- 不写 PostgreSQL。
- 不写 parquet。
- 不触发策略。
- 不发送企业微信。
- 不打印凭据原文，只输出环境变量 present / missing。

非 dry-run 仅支持 `--once`，不支持长期 scheduler / daemon。

### 5. 单元测试

新增：

- `services/quant-api/tests/test_live_1m_ingest.py`

覆盖：

- confirmed bar 入库。
- 当前分钟保守跳过。
- 唯一键去重。
- 修订后 `revision` 递增。
- 缺 `trading_day` 标记 warning。
- 非法 OHLC 标记 rejected / failed。
- RQData client 异常写入 checkpoint failed。
- service dry-run 不写表。
- CLI dry-run 不构造 client、不打开 session、不泄露敏感值。
- live 表不登记 `market_data_files`。

### 6. MarketDataReader 稳定排序

更新：

- `services/quant-api/app/services/market_data_reader.py`

只补充同一 `datetime` 下的确定性 provider 排序：

- `rqdata` 优先；
- `local_parquet` 其次；
- 其他 provider 最后。

active provider / data_role / quality_status 过滤条件不变。

## 本轮没有做

- 没有接企业微信。
- 没有触发策略扫描。
- 没有运行回测。
- 没有自动下单或生成订单草稿。
- 没有做 5m / 15m / 30m / 60m / 1d 聚合。
- 没有运行长期 scheduler。
- 没有接 websocket / tick 聚合。
- 没有恢复 TqSdk 为 V1 active 主链路。
- 没有把 live DB 数据登记为 trusted standard parquet。
- 没有把 live DB 混入默认 Market / Backtest / Signal 读取。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api python scripts/rqdata_live_1m_ingest.py --contract JM2609 --symbol jm --exchange DCE --once --dry-run
git diff --check
```

结果：

- live ingest 单测：`8 passed`。
- MarketDataReader 回归：`4 passed`。
- CLI dry-run：通过，输出确认不构造 RQData client、不打开 DB session、不写 DB、不写 parquet、不触发策略、不发送企业微信。
- `git diff --check`：通过。

Alembic 验证：

```bash
uv run --project services/quant-api python -m alembic upgrade head
```

从仓库根目录执行时失败：

- 原因：Alembic 从当前目录读取配置，仓库根目录没有 `script_location`。

已改用正确工作目录验证：

```bash
cd services/quant-api
uv run python -m alembic upgrade head
```

结果：

- 通过。
- 已将本地 PostgreSQL 从 `20260628_0012` 升级到 `20260707_0013`。

## 风险与未完成项

- 真实 RQData 非 dry-run 写入尚未执行；需要后续单独确认 PostgreSQL 环境、目标合约和执行窗口。
- `trading_day` 仍优先依赖 RQData 返回字段；如果真实返回缺失，4B 只标记 warning，不做夜盘自然日期推断。
- live DB 目前没有接入 Web 展示、策略扫描或聚合，这些留到后续阶段。
- checkpoint 中异常摘要来自异常字符串，当前 CLI 会脱敏；service 侧被其他调用方使用时仍需避免把凭据放进异常消息。

## 下一步

建议进入：

```text
LIVE-1M-5-MULTI-TF-AGGREGATION-PLAN
```

下一阶段再设计和实现：

- 1m confirmed live rows 聚合为 5m / 15m / 30m / 60m。
- 聚合状态表或物化策略。
- 与历史 standard parquet 的显式拼接边界。
- Web Market 显式查看 live confirmed 数据。

仍不建议直接接策略扫描或企业微信，先把 1m -> 多周期聚合口径定住。

## GPT 同步文件

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
