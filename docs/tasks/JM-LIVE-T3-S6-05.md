# S6-05 JM T3 单次真实 live Gate

## 当前状态

```text
CODE_COMPLETE
REAL_WRITE_APPROVAL_PENDING
T3_REAL_PENDING
```

代码已实现 JM-only `--once` 的历史 freshness、禁用开关和 hash-bound 审批边界。真实运行必须使用最终干净主干生成的审批包；任何 Git、数据库、active binding、actual contract、mapping、historical coverage、live baseline 或执行开关漂移都会使审批失效。

## 审批包

在仓库根目录运行只读 prepare：

```bash
services/quant-api/.venv/bin/python scripts/jm_live_t3_gate.py \
  --output data/reports/jm_live_t3_s6_05/<packet-id>/approval_packet.json
```

包内不保存连接密码或 RQData 凭据，只记录脱敏 DB identity 和凭据 present/missing 状态。packet hash 获用户单独批准后，才允许两次紧邻的 bounded `--once` 调用：第一次采集，第二次验证幂等。

## 真实执行

必须从 `services/quant-api` 目录执行：

```bash
GUIYI_LIVE_RUNTIME_ENABLED=true \
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false \
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=false \
GUIYI_WECHAT_AUTOSEND_ENABLED=false \
uv run python -m app.runtime_scheduler \
  --once --confirm-live-write --product jm \
  --approval-packet <packet> \
  --approval-hash <approved-hash>
```

只允许写 `live_minute_bars`、`live_ingest_checkpoints`、`live_aggregated_bars`、`live_aggregation_checkpoints` 和 scheduler heartbeat。已有 StrategySignal、SignalEvent、SignalNotification 不要求清空，但执行前后增量必须为 0。

非交易时段、无 confirmed 1m、锁冲突或 freshness/packet 漂移均不得写 `T3_REAL_PASSED`。

## 验证记录

```text
targeted: 46 passed
backend full: 1093 passed, 5 skipped
ruff: passed
real live: not run
```

本状态不代表 T4、SignalEvent、企业微信、runtime 长稳或自动交易 Ready。
