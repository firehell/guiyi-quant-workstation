# LIVE-1M-4A-DESIGN：RQData 实时 / 准实时 1m 入库设计

生成时间：2026-07-07
任务编号：LIVE-1M-4A-DESIGN
任务性质：设计文档 / schema 草案 / 后续实现边界

## 1. 目标

本阶段只设计 RQData 实时或准实时 1m bar 入库方案，为后续 `LIVE-1M-4B-MINIMAL-INGEST` 提供可执行边界。

4A 不实现代码，不新增 migration，不运行实时监听，不写 live 数据，不接企业微信，不触发策略，不下单。

## 2. 当前仓库观察

当前正式链路：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

active 数据入口仍保持：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

现有 `MarketDataReader` 只读取 PostgreSQL 中 `market_data_files` 登记的 standard parquet 文件，再通过 DuckDB `read_parquet` 查询 K 线。当前仓库没有 live 1m bar 表、live checkpoint 表，也没有经过验证的安全实时 wrapper。

Stage 1-C 的 RQData PoC 已验证历史 `1m/5m/15m/1d` 等能力，但 `realtime_snapshot_or_bar` 当时明确跳过，不能视为已支持。

## 3. RQData 入口判断

4B 第一版推荐入口：

```text
RqDataClient.contract_bars(contract, start_date, end_date, "1m")
```

理由：

- 已在仓库历史数据链路中使用。
- 与 JM v2 standard parquet 字段口径更接近。
- 可通过 checkpoint 回看最近窗口，筛选 confirmed 1m bar 后 upsert。
- 不要求第一版维护 websocket 长连接。

候选但不作为第一版默认入口：

- `LiveMarketDataClient`：可作为后续 websocket 推送方案，但 4B 不默认接入。
- `get_live_ticks`：可获取当前交易日 tick，后续可用于 tick 聚合 1m，但 4B 不做 tick 聚合。
- `current_snapshot`：可做观察状态或延迟诊断，不作为 confirmed 1m bar 来源。
- `current_minute`：文档口径存在“当前仅支持股票”和期货示例并存的矛盾，4B 不依赖。

## 4. 数据表草案

4B 如进入实现，建议新增 PostgreSQL live 层表，不复用 `market_data_files`。

### live_minute_bars

用途：保存 1m bar 的 live / near-live 记录。

建议唯一键：

```text
(provider, contract_code, period, bar_datetime)
```

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `provider` | 固定从 `rqdata` 起步 |
| `instrument_symbol` | 品种，如 `jm` |
| `contract_code` | 合约，如 `JM2609` 或后续映射后的主力合约 |
| `exchange_code` | 交易所，如 `DCE` |
| `period` | 第一版固定 `1m` |
| `bar_datetime` | bar 自然时间，按 RQData 返回时间保存 |
| `trading_day` | 交易日，优先取 RQData `trading_date` / `trading_day` |
| `open/high/low/close` | OHLC |
| `volume` | 成交量 |
| `open_interest` | 持仓量 |
| `turnover` | 成交额 |
| `bar_status` | `preview` / `confirmed` / `rejected` / `failed` |
| `quality_status` | `unchecked` / `passed` / `warning` / `failed` |
| `source_mode` | `poll_get_price_1m` / 后续 `live_bar_ws` / `tick_aggregate` |
| `first_seen_at` | 首次看到该 bar 的系统时间 |
| `last_seen_at` | 最近一次看到该 bar 的系统时间 |
| `confirmed_at` | 确认该 bar 已收盘的系统时间 |
| `revision` | 同一分钟 confirmed bar 如发生修正则递增 |
| `raw_payload` | RQData 原始字段摘要，不写凭据 |
| `created_at/updated_at` | 审计时间 |

索引建议：

- `(instrument_symbol, contract_code, period, bar_datetime)`
- `(contract_code, bar_status, bar_datetime)`
- `(trading_day, contract_code, period)`

### live_ingest_checkpoints

用途：记录每个 live 入库目标的轮询状态、延迟和错误。

建议唯一键：

```text
(provider, contract_code, period, source_mode)
```

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `provider` | `rqdata` |
| `instrument_symbol` | 品种 |
| `contract_code` | 合约 |
| `period` | `1m` |
| `source_mode` | 第一版 `poll_get_price_1m` |
| `last_confirmed_bar_at` | 最近确认入库的 bar 时间 |
| `last_polled_at` | 最近轮询时间 |
| `last_success_at` | 最近成功时间 |
| `status` | `idle` / `running` / `warning` / `failed` |
| `lag_seconds` | 系统当前时间相对最新 confirmed bar 的延迟 |
| `consecutive_error_count` | 连续失败次数 |
| `last_error_type` | 最近错误类型 |
| `last_error_message` | 最近错误摘要，必须脱敏 |
| `last_result` | 最近一次摘要，如 row_count、min/max datetime |
| `created_at/updated_at` | 审计时间 |

## 5. bar 状态和确认规则

第一版只允许 confirmed bar 进入可选读取拼接。

- `preview`：未确认收盘，只用于观察，不进入策略、不进入 active 读取。
- `confirmed`：已确认收盘，可以在显式请求下参与 Web 展示拼接。
- `rejected`：字段缺失、时间异常、重复冲突无法修复，不参与读取。
- `failed`：入库或质量检查失败，不参与读取。

建议确认策略：

1. 每轮轮询只处理当前时间之前已经完整结束的 1m bar。
2. 对最后 1 根可能仍在变化的 bar 默认保守跳过，除非后续探针证明 RQData 返回的是已确认分钟。
3. 入库前做最小质量检查：OHLC 合法、volume 非负、时间非空、contract 非空、trading_day 非空。
4. `quality_status=failed` 的 bar 不参与任何读取。

## 6. 夜盘 trading_day 原则

夜盘必须同时保存：

```text
bar_datetime = 自然时间
trading_day = 交易日
```

处理原则：

- 优先使用 RQData 返回的 `trading_date`、`trading_day` 或等价字段。
- 不用自然日期硬推夜盘交易日。
- 如果 RQData 没有返回交易日，4B 只能标记 `quality_status=warning`，并在 checkpoint `last_result` 中记录原因。
- 完整 session-aware 缺口检查等 `trading_sessions` 口径确认后再做。

## 7. 补漏、去重和修正

4B 最小策略：

- 每轮从 checkpoint 回看固定窗口，例如 `last_confirmed_bar_at - 10 minutes`。
- 如果没有 checkpoint，则从当前交易日最近窗口开始，第一版不做多日历史补齐。
- 使用唯一键 upsert 同一分钟 bar。
- 如果同一分钟 confirmed bar 的 OHLCV/OI/turnover 发生变化，递增 `revision`，更新 `last_seen_at`，并在 `raw_payload` 或后续审计表中记录 repair 摘要。
- 断线、空返回、延迟超过阈值只更新 checkpoint 状态，不伪装成成功。

## 8. 历史 parquet 与 live DB 拼接

默认行为不变：

```text
Market / Backtest / Signal 默认只读取 active standard parquet。
```

后续如实现显式拼接，应使用新参数，例如：

```text
include_live_confirmed=true
```

拼接规则：

- 只拼 `bar_status = confirmed`。
- 只拼 `quality_status != failed`。
- 只拼 `provider = rqdata`。
- 排除与 historical parquet 已覆盖时间重叠的 live rows。
- 返回 payload 必须标记 `data_origin = historical_parquet` 或 `data_origin = live_db`。
- Backtest 默认不得读取 live DB；信号扫描接入 live 数据必须另开阶段。

## 9. 4B 允许修改范围

后续 `LIVE-1M-4B-MINIMAL-INGEST` 可修改：

- Alembic migration：新增 live 表。
- SQLAlchemy models：新增 live bar / checkpoint 模型。
- RQData ingest service：新增最小轮询、字段归一、upsert、checkpoint 更新。
- CLI script：新增 `scripts/rqdata_live_1m_ingest.py`，支持 `--dry-run`、`--once`。
- 单元测试：新增 live ingest 测试。
- 文档：更新本设计和任务状态。

4B 仍禁止：

- 不接企业微信。
- 不触发策略扫描。
- 不做多周期聚合。
- 不运行长期 scheduler。
- 不接 TqSdk 作为 V1 active 主链路。
- 不把 live DB 直接登记为 trusted standard parquet。

## 10. 4B 测试命令草案

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api python -m alembic upgrade head
uv run --project services/quant-api python scripts/rqdata_live_1m_ingest.py --contract JM2609 --once --dry-run
git diff --check
```

4B dry-run 必须保证：

- 不写数据库。
- 不写 parquet。
- 不打印 RQData 凭据。
- 输出 row_count、min/max datetime、max trading_day、would_upsert_count、would_skip_count。

## 11. 4B 实现结果

`LIVE-1M-4B-MINIMAL-INGEST` 已按本设计完成最小代码闭环。

新增：

- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`

更新：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/services/market_data_reader.py`

已实现边界：

- 新增 `live_minute_bars` 和 `live_ingest_checkpoints`。
- `live_minute_bars` 唯一键为 `(provider, contract_code, period, bar_datetime)`。
- `live_ingest_checkpoints` 唯一键为 `(provider, contract_code, period, source_mode)`。
- ingest service 复用 `RqDataClient.contract_bars(..., frequency="1m")`。
- 只处理当前分钟之前已经结束的 bar。
- 缺 `trading_day` 标记 `quality_status=warning`，不硬推夜盘交易日。
- 非法 OHLC 等硬错误标记 `bar_status=rejected`、`quality_status=failed`。
- 同一分钟 bar 发生数值或状态变化时 `revision += 1`。
- CLI `--dry-run` 不构造 RQData client、不打开 DB session、不写 DB、不写 parquet、不触发策略、不发送企业微信。
- live DB 仍不登记 `market_data_files`，不进入默认 Market / Backtest / Signal 读取。
- `MarketDataReader` 仅补充同一 `datetime` 下的确定性 provider 排序，active 过滤条件不变。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api python scripts/rqdata_live_1m_ingest.py --contract JM2609 --symbol jm --exchange DCE --once --dry-run
git diff --check
```

结果：

- `test_live_1m_ingest.py`：`8 passed`。
- `test_market_data_reader.py`：`4 passed`。
- Alembic：已升级到 `20260707_0013`。
- CLI dry-run：通过。
- `git diff --check`：通过。

4B 仍未做：

- 未执行真实 RQData 非 dry-run 写库。
- 未做 1m 聚合多周期。
- 未接 Web live 展示。
- 未接策略扫描、企业微信、回测或交易。

## 12. Stage 5 多周期聚合实现结果

`LIVE-1M-5-MULTI-TF-AGGREGATION` 已完成最小代码闭环。

新增：

- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`
- `services/quant-api/tests/test_live_multi_tf_aggregation.py`

更新：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`

已实现边界：

- 新增 `live_aggregated_bars` 和 `live_aggregation_checkpoints`。
- `live_aggregated_bars` 唯一键为 `(provider, contract_code, period, bar_datetime, source_mode)`。
- 只聚合 `provider="rqdata"`、`period="1m"`、`bar_status="confirmed"` 且 `quality_status != "failed"` 的 live rows。
- 支持目标周期 `5m/15m/30m/60m`。
- 分桶口径沿用历史聚合思路：`contract + trading_day + session_gap_block + sequential_bucket`；第一版以相邻 1m gap `> 90s` 识别新 session block。
- 聚合 bar 的 `bar_datetime` 使用最后一根纳入的 1m bar 时间，避免未来函数。
- 最新正在形成的 bucket 不输出。
- 闭合但不足目标根数的 bucket 输出 `quality_status="warning"`，不伪装为 passed。
- 源 1m warning 会传导到聚合 warning。
- OHLCV 规则：open=第一根，high=max，low=min，close=最后一根，volume/turnover=sum，open_interest=最后一根。
- CLI `--dry-run` 不打开 DB session、不写 DB、不写 parquet、不登记 `market_data_files`、不触发策略、不运行回测、不发送企业微信。
- live 聚合 DB 仍不登记 `market_data_files`，不进入默认 Market / Backtest / Signal 读取。

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

- `test_live_multi_tf_aggregation.py`：`7 passed`。
- `test_live_1m_ingest.py`：`8 passed`。
- `test_market_data_reader.py`：`4 passed`。
- Alembic：已升级到 `20260707_0014`。
- CLI dry-run：通过。
- `ruff check`：通过。
- `git diff --check`：通过。

Stage 5 仍未做：

- 未执行真实 live 1m 非 dry-run 聚合。
- 未接 Web live 展示。
- 未接策略扫描、企业微信、回测或交易。

## 13. 4A 验收

本设计满足：

- 明确 live 表应新建，且不复用 `market_data_files`。
- 明确唯一键、核心字段、状态字段和 migration 边界。
- 明确 RQData 默认入口、候选入口和未验证缺口。
- 明确 confirmed、preview、延迟、补漏、去重、夜盘 trading_day 原则。
- 明确 4B 允许修改范围、禁止范围和测试命令。

## 14. GPT 同步文件

完成 Stage 5 后建议同步给浏览器 GPT：

- `docs/LIVE_1M_INGEST_DESIGN.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`
- `services/quant-api/tests/test_live_multi_tf_aggregation.py`
