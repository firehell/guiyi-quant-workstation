# 当前任务：STAGE-8.5-DATA-CHAIN-GATE

生成时间：2026-07-07
任务性质：Stage 9 企业微信前的数据主链路 Gate、schema 最小实现、元数据只读方案、historical bars 设计冻结与 8.5-6 写入试点代码 dry-run

## 当前结论

`STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 的文档级闭环，完成 8.5-3 的 schema / model / API / tests 最小代码闭环，完成 8.5-4 的 RQData 元数据只读方案冻结，完成 8.5-5 的主连 + 当前真实主力合约 historical bars 设计冻结，并完成 8.5-6 写入试点的代码 + dry-run + fixture 测试闭环。

本轮 8.5-6 只实现受控代码路径、dry-run CLI 和 fake client / SQLite fixture 测试；没有运行真实 RQData `--run-readonly`，没有运行真实 RQData 写入，没有写真实 `data/`、真实 parquet、真实 manifest、checksum 或真实行情 DB rows，没有登记真实 active，没有接企业微信。

阶段顺序保持为：

```text
Stage 8 signal_events 完成
-> Stage 8.5 数据主链路扩展
-> Stage 9 企业微信只读提醒
```

Stage 9 暂停前移。8.5-6 已具备代码级 Gate 和 dry-run 入口；进入企业微信前，仍必须单独授权并完成真实 JM-only 写入试点，确认真实主力合约 historical / live trigger price 来源可复核。

## 本轮完成

### 1. 8.5-0：Stage 8 输出审查

新增审查结论见：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`

核心判断：

- Stage 8 已具备 append-only `signal_events` 事件账本。
- Stage 8.5-3 前缺少企业微信前置所需的显式字段。
- JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，不能直接表达真实主力合约触发价。
- `live_signal_evaluator` 仍是 preview-only，不写正式信号或事件。

结论：

```text
Stage 8 可作为事件账本基础，但不能直接进入 Stage 9。
```

### 2. 8.5-1：数据新口径冻结与文档更新

冻结口径：

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记为 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独通过 quality Gate 后才能进入 historical active。
- Stage 9 企业微信 payload 必须能显示真实合约，且不表达实盘交易指令。

### 3. 8.5-2：schema / model 变更 Plan

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 固化 schema Plan。

推荐最小方向：

- 在 `strategy_signals` 和 `signal_events` 中显式支持 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`、`data_role`、`quality_status`。

不推荐方向：

- 不建议只依赖 JSON payload。
- 不建议 Stage 9 临时解析不同来源 payload。
- 不建议把 live evaluator preview 直接持久化为正式事件。

### 4. 8.5-3：schema / model 最小实现

已完成：

- `strategy_signals` 新增 contract context 显式字段。
- `signal_events` 新增 contract context 显式字段。
- 普通信号扫描和 JM V1-B 扫描会把显式 contract context 写入 `StrategySignal`，再投影到 append-only `SignalEvent`。
- `/api/signals/latest` 与 `/api/signals/events` 输出新增字段，并支持 `product`、`continuous_contract`、`actual_contract`、`provider`、`source`、`data_role` 过滤。
- `jm.MAIN` / `*.MAIN` 仅作为 `continuous_contract`，在没有真实主力映射证据时不写入 `actual_contract`。

### 5. 8.5-4：RQData 元数据与目标品种池只读 Plan

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 冻结：

- V1-B 默认目标品种池先锁定为 `jm`，不扩成全品种。
- metadata 源复用现有模型，不新增数据宇宙表：
  - `FuturesContractUniverse`
  - `MainContractMap`
  - `FuturesContinuousContractMap`
  - `FuturesTradingParameter`
  - `FeeMarginRule`
- `continuous_contract=jm.MAIN` 仍只作为研究主连 / 连续视图。
- `actual_contract` 只能来自 `MainContractMap.rank=1` 的真实主力映射；缺少映射证据时必须保持 `NULL`。
- `dominant_mapping_date` 对应 `MainContractMap.trade_date`。
- trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission；缺任一关键字段时不能进入 Stage 9。
- 真实 `rqdata_realtime_poc.py --run-readonly` 仍需单独授权。

### 6. 8.5-5：主连 + 当前真实主力合约 historical bars 设计冻结

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 冻结：

- `continuous_contract=jm.MAIN` 继续用于研究主连、连续图、日线方向和 historical scan 背景，不作为真实交易合约。
- `actual_contract` 必须从 `MainContractMap` 按 `instrument_symbol=jm`、`rank=1`、目标交易日解析；缺少映射证据时必须保持缺失并阻断 Stage 9。
- 当前真实主力合约 historical bars 后续必须作为独立 canonical bars 资产，不得混入 `jm.MAIN` 文件或复用 `jm.MAIN` 的 `contract` 语义。
- 首批 periods 与 JM v2 对齐：`1m / 5m / 15m / 30m / 60m / 1d`。
- 后续 8.5-6 写入试点建议优先下载真实主力 `1m` 标准 bars，再聚合生成 `5m/15m/30m/60m/1d`；如改用 RQData 直接多周期下载，必须在 8.5-6 代码计划中明确原因并补测试。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close；`jm.MAIN` close 不能宣称为真实合约提醒价。
- 质量 Gate 必须覆盖 duplicate、gap、时间顺序、OHLC、空值、volume/open_interest、min/max datetime、row_count、data_version、checksum、manifest 和 DuckDB 可读性。
- 只有 8.5-6 明确授权写入且质量报告通过后，才允许登记 `market_data_files` 和 `data_role=primary`；8.5-5 不授权任何 active 登记。

### 7. 8.5-6：写入试点代码 + dry-run + fixture 测试闭环

已完成受控代码入口：

- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`

核心行为：

- dry-run 默认不构造 RQData client、不打开 DB session、不写 parquet、不写 manifest、不写 DB、不登记 primary、不触发策略 / 回测 / 企业微信。
- 写入 service 会从 `MainContractMap.rank=1` 解析 `actual_contract`，并阻断缺映射、`.MAIN` 主连伪装真实合约、缺交易参数关键字段的情况。
- 写入路径以真实合约 `1m` bars 为源，支持聚合 `5m / 15m / 30m / 60m / 1d`。
- fake client / SQLite 测试验证只有 `quality_status=passed` 才登记 `data_role=primary`，且 `MarketDataFile.contract_code` 使用真实 `actual_contract`。
- `bar_sample.py` 的频率 helper 已扩展到 `5m / 15m / 30m`，用于 8.5-6 聚合质量检查。

边界：

- 本轮没有运行真实 RQData 写入。
- 本轮没有登记真实 `market_data_files`、`data_quality_reports` 或 active 数据。
- `--run-write` 入口仍需另行明确授权后才能执行。

## 本轮没有做

- 没有运行真实 RQData `--run-readonly`。
- 没有运行真实 RQData 写入。
- 没有写真实 `data/`、真实 parquet、真实 manifest、checksum 或真实行情 DB rows。
- 没有登记真实 `market_data_files`、`data_quality_reports` 或 active 数据。
- 没有接企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单。
- 没有生成订单草稿。
- 没有修改策略核心逻辑。
- 没有修改回测口径。
- 没有把 live DB 登记为 trusted historical active。
- 没有新增 API、schema、ORM 表、migration 或前端页面。
- 没有扩大到全品种或多合约池。

## 验证计划与结果

本轮验证命令包括：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_actual_contract_bars_pilot.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_jm_v2_parquet.py services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py services/quant-api/tests/test_actual_contract_bars_pilot.py scripts/rqdata_actual_contract_bars_pilot.py services/quant-api/app/services/rqdata_ingest/bar_sample.py
python scripts/rqdata_actual_contract_bars_pilot.py --product jm --trade-date 2026-07-07 --start-date 2026-07-06 --end-date 2026-07-07 --dry-run
git diff --check
```

结果：

- 新增 8.5-6 fixture 测试通过。
- JM v2 parquet 与 MarketDataReader 相关回归通过。
- `ruff check` 通过。
- dry-run 输出确认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- `git diff --check` 通过。

## 风险与未完成项

- `actual_contract` 仍依赖真实主力映射证据；没有证据时写入 service 会阻断。
- `JM2609` 只能作为当前样例合约，不能硬编码成长期真实主力。
- 主连 bars 与真实合约 bars 若共用 `contract` 语义，会污染 trigger price、提醒 payload 和复盘口径；8.5-6 已在路径和 `MarketDataFile.contract_code` 上强制使用真实合约。
- 后续若允许 `quality_status=warning` 进入 primary，需要单独说明；Stage 9 前建议优先要求 `quality_status=passed`。
- RQData 只读探测也可能触发外部账号权限或连接错误，输出必须继续脱敏。
- Stage 9 仍不能开工；必须等真实写入试点确认真实主力合约 bars、trigger price 和质量 Gate。
- 真实 historical 扩展和盘后归档必须另开任务并明确授权写入。

## 下一步

建议进入：

```text
Stage 8.5-6B：DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-REAL-WRITE
```

明确授权后再做 JM-only 当前真实主力合约 historical bars 真实最小写入试点；未授权前不得写真实数据、不得登记真实 active、不得接企业微信。

## GPT 同步文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/tasks_current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`
