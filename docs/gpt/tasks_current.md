# 当前任务同步：STAGE-8.5-DATA-CHAIN-GATE

生成时间：2026-07-07

## 最新状态

`STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 文档级闭环。

本轮任务是在 Stage 8 `signal_events` 完成后、Stage 9 企业微信只读提醒前插入数据主链路 Gate。目标是确认提醒事件能明确表达 product、研究主连、真实主力合约、触发价、数据源、质量状态和 confirmed bar 边界。

## 关键输出

新增：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`

更新：

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`

未修改：

- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/signal/jm_v1b.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- Alembic migrations

## 实现结论

### 8.5-0 Stage 8 输出审查

已确认：

- `signal_events` 已具备 append-only 事件账本基础。
- 当前事件字段不足以直接承接 Stage 9。
- 缺少显式 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 为扫描合约，`features.signal_price` 来自主连 bar close。
- `live_signal_evaluator` 当前仍是 preview-only，不写正式信号或事件。

### 8.5-1 数据新口径冻结

已冻结：

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独经过 quality Gate 后才能进入 historical active。
- Stage 9 企业微信 payload 必须能显示真实合约，且只表达观察提醒。

### 8.5-2 schema / model 变更 Plan

推荐最小方向：

- 在 `strategy_signals` 和 `signal_events` 中显式支持真实合约绑定字段。
- 不依赖任意 JSON payload 约定承接 Stage 9。
- 不在 Stage 9 中临时解析合约映射。
- 不把 live evaluator preview 直接持久化为正式事件。

## 验证结果

本轮是文档和审查任务，计划运行：

```bash
git diff --check
```

可选现状回归：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py
```

## 本轮没有做

- 没有修改 `services/` 应用代码。
- 没有创建 Alembic migration。
- 没有修改 ORM / Pydantic schema。
- 没有运行真实 RQData 写入。
- 没有写 `data/`、parquet、manifest、checksum 或 DB rows。
- 没有接企业微信。
- 没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单。
- 没有生成订单草稿。
- 没有把 live DB 登记为 historical active。
- 没有修改策略核心逻辑或回测口径。

## 下一步建议

下一步进入：

```text
Stage 8.5-3：DATA-CHAIN-8_5C-SCHEMA-MINIMAL-IMPLEMENTATION
```

执行前先确认 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 的 schema Plan。实现阶段只做最小 migration / ORM / schema / tests，不写真实行情数据，不接企业微信。

Stage 9 企业微信只读提醒继续 blocked，直到 Stage 8.5 Gate 通过。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/signal/jm_v1b.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/alembic/versions/20260707_0015_signal_events.py`
