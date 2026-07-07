# 当前任务：LIVE-1M-4A-DESIGN

生成时间：2026-07-07
任务性质：实时 1m 入库设计 / schema 草案 / 后续实现边界

## 当前结论

`LIVE-1M-4A-DESIGN` 已完成设计落地。

本轮只新增和同步设计文档，不新增 migration，不实现 collector，不运行实时监听，不写 live 数据，不接企业微信，不触发策略，不下单。

## 本轮变更

### 4A RQData 实时 / 准实时 1m 入库设计

新增设计文档：

- `docs/LIVE_1M_INGEST_DESIGN.md`

设计明确：

- 4B 第一版推荐使用 `RqDataClient.contract_bars(..., frequency="1m")` 做准实时 confirmed 1m 拉取。
- `LiveMarketDataClient`、`get_live_ticks`、`current_snapshot` 仅作为后续候选入口。
- `current_minute` 因文档口径存在矛盾，不作为第一版默认依赖。
- live 数据先进入 PostgreSQL 独立 live 层，不复用 `market_data_files`，也不自动混入默认 Market / Backtest / Signal 读取。
- 默认 active 数据入口仍保持 `rqdata/local_parquet + primary + quality_status != failed`。

### 4B schema 草案

设计了两张后续候选表：

- `live_minute_bars`：保存 1m live / near-live bar。
- `live_ingest_checkpoints`：保存每个合约、周期和 source_mode 的轮询 checkpoint、延迟和错误状态。

关键口径：

- `live_minute_bars` 唯一键建议为 `(provider, contract_code, period, bar_datetime)`。
- `preview` 不进入策略、不进入 active 读取。
- `confirmed` 才允许后续显式拼接展示。
- `rejected` / `failed` 保留错误原因，不参与读取。
- 夜盘同时保存 `bar_datetime` 和 `trading_day`，优先使用 RQData 返回字段，不用自然日期硬推。

### 状态文档同步

同步更新：

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

## 本轮没有做

- 没有新增 Alembic migration。
- 没有新增 SQLAlchemy model。
- 没有实现 collector / service / CLI。
- 没有运行 RQData 实时或准实时拉取。
- 没有写 PostgreSQL live 表。
- 没有写 parquet、manifest、checksum 或质量报告。
- 没有接企业微信。
- 没有触发策略扫描或回测。
- 没有自动下单或生成订单草稿。
- 没有恢复 TqSdk 为 V1 active 主链路。

## 验证结果

已运行：

```bash
git diff --check
```

结果：

- `git diff --check`：通过。

未运行：

- 未运行后端 pytest；本轮未改业务代码。
- 未运行 Alembic；本轮未新增 migration。
- 未运行 RQData；本轮不执行实时或准实时拉取。

## 当前项目状态

Stage 2C / 2D / 2E 仍保持已完成：

- JM v2 六周期 raw / standard parquet 已写入。
- data_version 为全窗口 `20230103_20260707_v2`。
- manifest、checksum、quality report 已生成。
- PostgreSQL `market_data_files` / `data_quality_reports` 已登记。
- coverage audit 结论为 `can_enter_stage3=true`。

Stage 3A / 3B 已完成代码级闭环：

- active 数据读取边界测试已补强。
- Web Data 页面已有数据文件覆盖表，方便人工检查 JM v2 六周期质量状态。

Stage 4A 已完成设计闭环：

- live 表、checkpoint、bar 状态、补漏去重、夜盘 trading_day、历史 parquet 与 live DB 拼接边界已设计。

## 下一步

建议进入独立新会话：

```text
LIVE-1M-4B-MINIMAL-INGEST
```

下一阶段才允许最小实现：

- 新增 migration 和 SQLAlchemy models。
- 新增 live 1m ingest service。
- 新增 `scripts/rqdata_live_1m_ingest.py` dry-run / once CLI。
- 新增 `services/quant-api/tests/test_live_1m_ingest.py`。

4B 仍禁止接企业微信、触发策略、自动下单、多周期聚合和长期 scheduler。

## GPT 同步文件

- `docs/LIVE_1M_INGEST_DESIGN.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
