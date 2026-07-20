# S6-06 JM 单交易日盘后归档 Gate

## 当前状态

```text
CODE_COMPLETE
T3_PREREQUISITE_PENDING
REAL_ARCHIVE_APPROVAL_PENDING
JM_ARCHIVE_PENDING
```

归档代码只允许 JM，并复用 S6-03 已验证的 immutable baseline、provider normalization、quality、metadata registration 和 Profile compare-and-switch。T3 未真实通过前不得生成正式 T4 审批包或执行写入。

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

## 审批包

T3 receipt 必须包含 `gate=T3_REAL_PASSED`、trading day、actual contract 和 T3 packet hash。交易日关闭且 provider-final 1m 行数完整后：

```bash
services/quant-api/.venv/bin/python scripts/after_market_archive.py \
  --product jm \
  --trading-day <YYYY-MM-DD> \
  --prepare-packet \
  --packet-out <approval-packet.json> \
  --t3-receipt <t3-receipt.json>
```

包绑定 commit、脱敏 DB identity、output root、T3 receipt hash、actual/mapping、provider-final row/hash、active binding、live snapshot、预计 create-only 文件和版本。任一事实变化自动失效。

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

quality、provider hash、binding snapshot 或 consumer target 失败时，DB rollback、旧 binding 保持不变，并只清理本包新建文件。成功 receipt 存在时重复执行返回 `already_archived`，不创建第二份 active。

当前不代表 EOD automation、SignalEvent、通知、runtime 长稳或自动交易 Ready。

## 验证记录

```text
targeted: 58 passed
backend full: 1097 passed, 5 skipped
ruff: passed
dry-run: passed
real archive: not run; T3 prerequisite pending
```
