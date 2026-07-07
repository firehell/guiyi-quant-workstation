# GPT handoff package

生成时间：2026-07-07

本目录是浏览器 GPT 的当前项目事实包。这里保留的是当前可继续讨论和拆任务的文件，不再保留旧阶段 PoC 原始报告。

## 推荐阅读顺序

1. `CURRENT_STATE.md`
2. `PROJECT_SNAPSHOT.md`
3. `NEXT_STEPS.md`
4. `ROADMAP.md`
5. `tasks_current.md`
6. `../DATA_UNIVERSE_AND_ARCHIVE.md`

## 当前结论

- Stage 2C / 2D / 2E 已完成。
- JM v2 六周期 `1m/5m/15m/30m/60m/1d` 已写入 raw / standard parquet。
- 当前 JM v2 data_version 为全窗口 `20230103_20260707_v2`。
- 六周期 DB 登记均为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- coverage audit 结论为 `can_enter_stage3=true`。
- Stage 8 `signal_events` 已完成代码级闭环。
- Stage 8.5 已完成数据主链路 Gate 的审查、口径冻结、schema Plan 和 schema 最小实现。

## 下一步

1. `DATA-UNIVERSE-8_5D-METADATA-READONLY-PLAN`
2. `DATA-UNIVERSE-8_5E-HISTORICAL-BARS-PLAN`
3. `DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-WRITE`

当前默认读取仍严格使用：

```text
rqdata / local_parquet + primary + quality_status != failed
```

Stage 9 企业微信只读提醒必须等 Stage 8.5 Gate 通过后再启动。

## 仍需注意

- `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因仍待后续确认。
- 当前 `signal_events` 已具备显式 contract context 字段，但真实主力合约、真实合约 trigger price 和完整 Stage 9 Gate 仍需后续阶段确认。
- 企业微信只读提醒、长期 worker/scheduler、Cloudflare Access 验收未完成。
- V1 不做自动下单，不接实盘交易。

## GPT 同步文件

- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/ROADMAP.md`
- `docs/gpt/tasks_current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/PROJECT_INVENTORY.md`
