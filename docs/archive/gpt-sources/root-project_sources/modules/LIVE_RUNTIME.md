# Live Runtime And Deployment

更新时间：2026-07-14

事实来源：`docs/ARCHITECTURE.md`、`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`

当前状态：current，真实运行 Gate pending。

## 已具备

- live 1m ingest 代码。
- live 5m/15m/30m/60m/1d/1w aggregation 代码。
- runtime scheduler 代码和 Redis singleton lock。
- runtime health API。
- after-market archive 受控 CLI。
- launchd 模板、nginx/frp 模板。

## 当前不可宣称

```text
T3_REAL_PASSED
JM_RUNTIME_READY
LONG_RUNNING_READY
FULL_UNIVERSE_READY
```

## Gate

- T3-real：JM 可交易时段 + 用户显式确认 + live 表/checkpoint 写入。
- T6-real：最后才允许 live-confirmed 单条 notification。
- T7：至少 5 个真实交易日、夜盘、kill/recovery、Mac 重启、依赖故障注入。
- 公网：TLS、Basic Auth、未认证 401、端口封闭、FRP/Nginx 恢复。

