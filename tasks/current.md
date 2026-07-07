# 当前任务：STAGE-8.5-DATA-CHAIN-GATE

生成时间：2026-07-07
任务性质：Stage 9 企业微信前的数据主链路 Gate、schema 最小实现与文档冻结

## 当前结论

`STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 的文档级闭环，并完成 8.5-3 的 schema / model / API / tests 最小代码闭环。

本轮创建了 Alembic migration，更新了 `strategy_signals` / `signal_events` ORM 与信号 API 输出字段；没有运行真实 RQData 写入，没有写 `data/`、parquet、manifest、checksum 或真实行情 DB rows。

阶段顺序已调整为：

```text
Stage 8 signal_events 完成
-> Stage 8.5 数据主链路扩展
-> Stage 9 企业微信只读提醒
```

Stage 9 暂停前移。进入企业微信前，必须先解决 `signal_events` 与 `StrategySignal` 对真实主力合约、触发价和 confirmed bar 边界的显式绑定问题。

## 本轮完成

### 1. 8.5-0：Stage 8 输出审查

新增审查结论见：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`

核心判断：

- Stage 8 已具备 append-only `signal_events` 事件账本。
- 当前 `signal_events` 有 `symbol`、`contract`、`exchange`、`period`、`signal_time`、`data_role`、`quality_status` 和 `payload`。
- 当前缺少企业微信前置所需的显式字段：`product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`。
- 当前 JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，`features.signal_price` 来自主连 bar close，不足以表达真实主力合约触发价。
- `live_signal_evaluator` 仍是 preview-only，不写正式信号或事件。

结论：

```text
Stage 8 可作为事件账本基础，但不能直接进入 Stage 9。
```

### 2. 8.5-1：数据新口径冻结与文档更新

新增 / 更新：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/CURRENT_STATE.md`

冻结口径：

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记为 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独通过 quality Gate 后才能进入 historical active。
- Stage 9 企业微信 payload 必须能显示真实合约，且不表达实盘交易指令。

### 3. 8.5-2：schema / model 变更 Plan

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 固化 schema Plan。

推荐最小方向：

- 在 `strategy_signals` 和 `signal_events` 中显式支持：
  - `product`
  - `continuous_contract`
  - `actual_contract`
  - `dominant_mapping_date`
  - `bar_start`
  - `bar_end`
  - `trigger_price`
  - `provider`
  - `source`
  - `data_role`
  - `quality_status`

不推荐方向：

- 不建议只依赖 JSON payload。
- 不建议 Stage 9 临时解析不同来源 payload。
- 不建议把 live evaluator preview 直接持久化为正式事件。

### 4. 8.5-3：schema / model 最小实现

新增 / 更新代码：

- `services/quant-api/alembic/versions/20260707_0016_signal_contract_context.py`
- `services/quant-api/app/signal/contract_context.py`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/signal/jm_v1b.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_signal_contract_context.py`
- `services/quant-api/tests/test_signal_events.py`
- `services/quant-api/tests/test_signal_scanner_api.py`

核心实现：

- `strategy_signals` 新增 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`、`data_role`。
- `signal_events` 新增 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`。
- 普通信号扫描和 JM V1-B 扫描都会把显式 contract context 写入 `StrategySignal`，再投影到 append-only `SignalEvent`。
- `/api/signals/latest` 与 `/api/signals/events` 输出新增字段，并支持 `product`、`continuous_contract`、`actual_contract`、`provider`、`source`、`data_role` 过滤。
- `jm.MAIN` / `*.MAIN` 仅作为 `continuous_contract`，在没有真实主力映射证据时不写入 `actual_contract`。

## 本轮没有做

- 没有运行真实 RQData 写入。
- 没有写 `data/`、parquet、manifest、checksum 或 DB rows。
- 没有接企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单。
- 没有生成订单草稿。
- 没有修改策略核心逻辑。
- 没有修改回测口径。
- 没有把 live DB 登记为 trusted historical active。

## 验证计划与结果

本轮验证命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_contract_context.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py
```

后续完成前还需跑：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py
uv run --project services/quant-api ruff check services/quant-api/app/models/signal.py services/quant-api/app/signal/events.py services/quant-api/app/signal/scanner.py services/quant-api/app/signal/jm_v1b.py services/quant-api/app/services/signal_scanner.py services/quant-api/app/signal/contract_context.py services/quant-api/app/schemas/signal.py services/quant-api/app/api/signals.py services/quant-api/tests/test_signal_contract_context.py services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py
cd services/quant-api && uv run python -m alembic upgrade head
git diff --check
```

## 风险与未完成项

- Stage 8.5-3 已实现最小字段和投影，但 `actual_contract` 在缺少真实主力映射证据时仍会保持 `NULL`。
- Stage 9 仍不能开工；必须等 8.5-4 / 8.5-5 明确真实主力映射、真实合约 historical / live 触发价来源后再设计企业微信。
- `StrategySignal.contract` 当前语义仍偏兼容旧字段，后续 migration 需明确它与 `continuous_contract` / `actual_contract` 的关系。
- 真实 historical 扩展和盘后归档必须另开任务并明确授权写入。

## 下一步

建议进入：

```text
Stage 8.5-4：DATA-UNIVERSE-8_5D-METADATA-READONLY-PLAN
```

只读确认 RQData 目标品种池、主力映射和交易参数；不写真实行情数据，不接企业微信。

## GPT 同步文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/CURRENT_STATE.md`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/signal/contract_context.py`
- `services/quant-api/app/signal/jm_v1b.py`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/alembic/versions/20260707_0015_signal_events.py`
- `services/quant-api/alembic/versions/20260707_0016_signal_contract_context.py`
