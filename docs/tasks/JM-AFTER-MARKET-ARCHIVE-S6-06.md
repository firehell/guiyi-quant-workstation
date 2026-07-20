# S6-06 JM 单交易日盘后归档 Gate

## 当前状态

```text
CODE_COMPLETE
T3_REAL_PASSED
REAL_ARCHIVE_APPROVAL_PENDING
JM_ARCHIVE_PENDING
```

归档代码只允许 JM，并复用 S6-03 已验证的 immutable baseline、provider normalization、quality、metadata registration 和 Profile compare-and-switch。T3 receipt 已绑定 `2026-07-21 / JM2609`；T4 必须等待该交易日关闭和 provider-final ready 后生成独立审批包，T3 授权不得复用。

## 数据契约

```text
RQData provider-final actual 1m
-> merge immutable active actual 1m baseline
-> local 5m/15m/30m/60m/1d
-> completed-week-only 1w
-> quality passed
-> manifest/checksum + DB registration
-> Profile verify/compare-and-switch
-> live/provider reconciliation
```

live rows 只作 comparison evidence。缺行、revision 或 OHLCV 差异记录为 `differences_observed`，不能覆盖 provider historical，也不能伪装为 reconciliation passed。

T4 provider finality 只要求 `future_minbar.ready=true`，随后按 TradingSession 构造精确分钟 key，并对 actual 1m 连续执行两次稳定性检查；行数、起止时间、分钟 key 或 hash 任一漂移均 fail-closed。`future_daybar` 同时写入 packet 供观察，但不阻断归档，因为 T4 的 1d 明确由 provider-final 1m 本地派生，不把本地派生结果冒充米筐直出日线。

## 审批包

T3 receipt 必须包含 `gate=T3_REAL_PASSED`、trading day、actual contract 和 T3 packet hash。交易日关闭且 provider-final 1m 行数完整后：

```bash
services/quant-api/.venv/bin/python scripts/after_market_archive.py \
  --product jm \
  --trading-day <YYYY-MM-DD> \
  --prepare-packet \
  --provider-stability-checks 2 \
  --provider-stability-interval-seconds 30 \
  --packet-out <approval-packet.json> \
  --t3-receipt <t3-receipt.json>
```

包绑定 commit、脱敏 DB identity、output root、T3 receipt hash、actual/mapping、provider-final row/hash、active binding、live snapshot、预计 create-only 文件和版本。任一事实变化自动失效。

关闭前的 bounded prepare 返回 `TRADING_DAY_NOT_CLOSED`；米筐分钟数据尚未最终化时返回 `PROVIDER_FINAL_PENDING`。两者都不写 packet、数据库、Parquet 或 Profile，也不得记为 Gate passed。

## 真实执行

```bash
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED=true \
services/quant-api/.venv/bin/python scripts/after_market_archive.py \
  --product jm \
  --trading-day <YYYY-MM-DD> \
  --run-write \
  --confirm-after-market-archive \
  --t3-receipt <t3-receipt.json> \
  --approval-packet <approval-packet.json> \
  --approval-hash <approved-hash>
```

quality、provider hash、binding snapshot、旧资产 checksum 或正式 Profile consumer smoke 失败时，DB rollback、旧 binding 保持不变，并只清理本包新建文件。final audit 和 receipt 先 staged、DB commit 后原子发布；若发布中断，重跑根据 `batch_id + packet_hash + registered assets` 恢复 receipt，不重复登记或切换。成功 receipt 存在时重复执行返回 `already_archived`，不创建第二份 active。

当前不代表 EOD automation、SignalEvent、通知、runtime 长稳或自动交易 Ready。

## 验证记录

```text
archive targeted: 71 passed
backend full: 1130 passed, 3 skipped
ruff: passed
dry-run: passed
real archive: not run; trading-day close + independent approval pending
```
