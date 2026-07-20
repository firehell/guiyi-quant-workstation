# S6-05 JM T3 单次真实 live Gate

## 当前状态

```text
CODE_COMPLETE
REAL_WRITE_APPROVAL_PENDING
T3_REAL_PENDING
```

代码已实现 JM-only `--once` 的历史 freshness、禁用开关和 hash-bound 审批边界。真实运行必须使用最终干净主干生成的审批包；任何 Git、数据库、active binding、actual contract、mapping、historical coverage、live baseline 或执行开关漂移都会使审批失效。

收盘后 historical freshness 不再通过“是否已经查询到直出日线”猜测。S6-03 preflight 使用 RQData `is_data_ready`，要求目标日 `future_minbar` 和 `future_daybar` 均 ready，并逐项校验 JM continuous/actual 的目标日行数和 hash。若 provider 仍在更新，可用 `--wait-provider-ready` 做 60 秒轮询、最长 4 小时的有界等待；超时保持 pending 且不写数据。

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

两次 stdout 分别保存为 JSON 后，运行最终只读审计：

```bash
services/quant-api/.venv/bin/python scripts/jm_live_t3_gate.py \
  --audit-packet <packet> \
  --run-result <run-1.json> \
  --run-result <run-2.json> \
  --audit-output <t3-receipt.json>
```

审计要求 live 1m 和 checkpoint 前进、六个聚合 checkpoint 状态合法、第二次存在 unchanged bar、historical metadata/quality/Profile 及 signal/notification 表计数无增量、active binding hash 不变、项目四个开关恢复为 false。只有该 receipt 输出 `gate=T3_REAL_PASSED` 才能进入 T4。

## 验证记录

```text
provider readiness targeted: 54 passed
merged-main backend full: 1110 passed, 3 skipped
ruff: passed
RQData 3.5.6.1 + pandas 3.0.3 smoke: passed
real live: not run
```

本状态不代表 T4、SignalEvent、企业微信、runtime 长稳或自动交易 Ready。
