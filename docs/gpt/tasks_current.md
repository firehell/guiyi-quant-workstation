# 当前任务同步：STAGE-8.5-DATA-CHAIN-GATE

生成时间：2026-07-07

## 最新状态

`STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 文档级闭环、8.5-3 schema 最小代码闭环、8.5-4 RQData 元数据只读方案冻结、8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结，以及 8.5-6 写入试点代码 + dry-run + fixture 测试闭环。

本轮 8.5-6 只实现受控代码路径、dry-run CLI 和 fake client / SQLite fixture 测试，不运行真实 RQData `--run-readonly`，不运行真实 RQData 写入，不写真实 `data/`、真实 parquet、真实 manifest、checksum 或真实行情 DB rows，不登记真实 active，不接企业微信。

Stage 9 企业微信只读提醒继续 blocked。8.5-6 已具备 dry-run / fake fixture Gate；进入 Stage 9 前仍需另行授权并完成真实主力合约 historical bars 写入试点、trigger price、bar_end 和质量 Gate。

## 关键输出

更新：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`

本轮新增后端 service、CLI 和测试；没有新增 migration、API 或前端页面。

## 已完成结论

### 8.5-0 Stage 8 输出审查

- `signal_events` 已具备 append-only 事件账本基础。
- Stage 8 输出不足以直接承接 Stage 9。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 为扫描合约。
- `live_signal_evaluator` 仍是 preview-only，不写正式信号或事件。

### 8.5-1 数据新口径冻结

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独经过 quality Gate 后才能进入 historical active。

### 8.5-2 schema / model 变更 Plan

- 推荐在 `strategy_signals` 和 `signal_events` 中显式支持真实合约绑定字段。
- 不依赖任意 JSON payload 约定承接 Stage 9。
- 不在 Stage 9 中临时解析合约映射。

### 8.5-3 schema / model 最小实现

- `strategy_signals` 和 `signal_events` 已新增显式 contract context 字段。
- 普通信号扫描和 JM V1-B 扫描会写入 `product`、`continuous_contract`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`、`data_role`。
- `.MAIN` 主连只写入 `continuous_contract`，不伪装为 `actual_contract`。
- `/api/signals/latest` 和 `/api/signals/events` 输出新增字段并支持新增过滤参数。

### 8.5-4 RQData 元数据只读 Plan

已冻结：

- V1-B 默认目标品种池先锁定为 `jm`，不扩成全品种。
- metadata 源复用现有模型：
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

### 8.5-5 historical bars 设计冻结

已冻结：

- `continuous_contract=jm.MAIN` 继续用于研究主连、连续图、日线方向和 historical scan 背景。
- `actual_contract` 必须来自 `MainContractMap.rank=1`；缺少映射证据时不能用样例合约替代。
- 当前真实主力合约 historical bars 后续必须作为独立 canonical bars 资产，不混入 `jm.MAIN` 文件，不复用 `jm.MAIN` 的 `contract` 语义。
- 首批 periods 与 JM v2 对齐：`1m / 5m / 15m / 30m / 60m / 1d`。
- 8.5-6 写入试点建议优先下载真实主力 `1m` 标准 bars，再聚合生成更高周期；如改用 RQData 直接多周期下载，必须说明取舍并补测试。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close。
- 8.5-5 不授权写 parquet、manifest、checksum、DB rows 或 active 登记。

### 8.5-6 写入试点代码 + dry-run

已完成：

- 新增 `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`。
- 新增 `scripts/rqdata_actual_contract_bars_pilot.py`。
- 新增 `services/quant-api/tests/test_actual_contract_bars_pilot.py`。
- dry-run 默认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- fake client / SQLite 测试覆盖缺主力映射、`.MAIN` 误用、缺交易参数、quality failed 不登记 primary、quality passed 登记真实 `actual_contract`。
- 真实 `--run-write` 仍需另行明确授权。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_actual_contract_bars_pilot.py
python scripts/rqdata_actual_contract_bars_pilot.py --product jm --trade-date 2026-07-07 --start-date 2026-07-06 --end-date 2026-07-07 --dry-run
git diff --check
```

结果：

- 8.5-6 fixture 测试通过。
- dry-run 输出确认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- `git diff --check` 通过。

## 本轮没有做

- 没有运行真实 RQData `--run-readonly`。
- 没有运行真实 RQData 写入。
- 没有写真实 `data/`、真实 parquet、真实 manifest、checksum 或真实行情 DB rows。
- 没有登记真实 `market_data_files`、`data_quality_reports` 或 active 数据。
- 没有接企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单或生成订单草稿。
- 没有把 live DB 登记为 historical active。
- 没有修改策略核心逻辑或回测口径。

## 下一步建议

下一步进入：

```text
Stage 8.5-6B：DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-REAL-WRITE
```

明确授权后做 JM-only 当前真实主力合约 historical bars 真实最小写入试点；未授权前不得写真实数据、不得登记 active、不得接企业微信。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`
