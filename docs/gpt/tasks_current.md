# 当前任务同步：LIVE-1M-4A-DESIGN

生成时间：2026-07-07

## 最新状态

`LIVE-1M-4A-DESIGN` 已完成。

本轮只做设计文档和阶段状态同步，没有新增 migration，没有实现 collector，没有运行实时监听，没有写 live 数据，没有接企业微信，没有触发策略或下单。

## 关键输出

新增：

- `docs/LIVE_1M_INGEST_DESIGN.md`

同步：

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

## 设计结论

4B 第一版推荐采用：

```text
RqDataClient.contract_bars(contract, start_date, end_date, "1m")
```

作为准实时 confirmed 1m 拉取入口。

候选入口边界：

- `LiveMarketDataClient`：后续 websocket 推送候选，不作为 4B 默认入口。
- `get_live_ticks`：后续 tick 聚合候选，4B 不做 tick 聚合。
- `current_snapshot`：后续观察状态或延迟诊断候选，不作为 confirmed 1m bar 来源。
- `current_minute`：文档口径存在矛盾，4B 不依赖。

## live 表草案

后续 4B 可新增 PostgreSQL live 层，不复用 `market_data_files`：

- `live_minute_bars`
- `live_ingest_checkpoints`

关键规则：

- `live_minute_bars` 唯一键建议为 `(provider, contract_code, period, bar_datetime)`。
- `preview` 不进入策略、不进入 active 读取。
- `confirmed` 才可在显式参数下参与 Web 展示拼接。
- `rejected` / `failed` 保留错误原因，不参与读取。
- 夜盘同时保存自然时间 `bar_datetime` 和交易日 `trading_day`。

## 本轮没有做

- 没有写数据库。
- 没有写 parquet。
- 没有生成 manifest、checksum 或质量报告。
- 没有新增 Alembic migration。
- 没有新增 SQLAlchemy model。
- 没有实现 ingest service / CLI。
- 没有运行 RQData。
- 没有接企业微信。
- 没有触发策略扫描、回测或交易。

## 下一步建议

建议新 Codex 会话 + Plan 模式进入：

```text
LIVE-1M-4B-MINIMAL-INGEST
```

4B 最小允许范围：

- 新增 live 相关 migration。
- 新增 live 相关 SQLAlchemy models。
- 新增最小 ingest service。
- 新增 `scripts/rqdata_live_1m_ingest.py`，必须支持 `--dry-run` 和 `--once`。
- 新增 `services/quant-api/tests/test_live_1m_ingest.py`。

4B 禁止范围：

- 不接企业微信。
- 不触发策略扫描。
- 不做多周期聚合。
- 不运行长期 scheduler。
- 不恢复 TqSdk 为 V1 active 主链路。
- 不把 live DB 数据直接登记为 trusted standard parquet。

## 建议 GPT 上传文件

- `docs/LIVE_1M_INGEST_DESIGN.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
