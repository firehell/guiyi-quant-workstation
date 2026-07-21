# S6-06 JM 单交易日盘后归档 Gate

## 当前状态

```text
CODE_COMPLETE
T3_REAL_PASSED
REAL_ARCHIVE_COMPLETED
IDEMPOTENT_RERUN_PASSED
JM_ARCHIVE_PASSED
```

归档代码只允许 JM，并复用 S6-03 已验证的 immutable baseline、provider normalization、quality、metadata registration 和 Profile compare-and-switch。T3 receipt 绑定 `2026-07-21 / JM2609`；T4 使用独立 v2 packet 和单独授权完成，未复用 T3 权限。

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

包绑定 commit、脱敏 DB identity、output root、T3 receipt hash、actual/mapping、provider-final row/hash、active binding、live snapshot、预计 create-only 文件和版本。schema v2 额外绑定可执行契约：六个 historical assets 与七个 Profile candidates 分别验收，任一事实变化自动失效。

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
archive targeted and related: 44 passed
backend full: 1143 passed, 3 skipped
ruff: passed
dry-run: passed
real archive: success
idempotent rerun: already_archived / writes_performed=false
gate: JM_ARCHIVE_PASSED
```

### 最终审批与证据

- code/batch：`main@115101e3` / `s606_20260721_115101e3`
- packet：`data/reports/jm_after_market_archive_s6_06/main_115101e3_20260721/approval_packet.json`
- packet hash：`e9e2fc5b6caf9da262026beca3d40a9a0d435994b554af36a386993ca156017a`
- receipt：`data/reports/jm_after_market_archive_s6_06/s606_20260721_115101e3/completion_receipt.json`
- final audit：`data/reports/jm_after_market_archive_s6_06/s606_20260721_115101e3/final_audit.json`
- manifest：`data/manifests/jm_after_market_archive_s606_20260721_115101e3.csv`

provider-final actual 1m 为 345 行，范围 `2026-07-20 21:01:00` 至 `2026-07-21 15:00:00`，两次稳定性 hash 均为 `b38fb1c95f2202997a41019dd0fc6158b03b0fc12ca3ee66b8fcaba075cc3ede`。本交易日不是完成周末，因此只生成 `1m/5m/15m/30m/60m/1d`，六份资产均为 `rqdata / primary / passed`；注册任务为 `116128` 至 `116133`。

Profile consumer smoke 验证七个 active binding：`intraday_research_v1` 与 `live_observation_v1` 各自的 `1m/5m/15m`，以及 `long_horizon_daily_v1 / 1d`。所有 active identity 唯一，旧 active snapshot 的 48 份文件 checksum 不变，无 staged 文件残留。

reconciliation 为 `differences_observed` 且 `live_reference_only=true`：provider/live 均为 345 行，无缺行、额外行、重复或 revision；344 行完全一致，`2026-07-21 15:00:00` 的 volume/open_interest 存在一处差异。该差异未回写 historical canonical。

完全相同命令和 hash 的第二次执行返回 `already_archived / writes_performed=false`。资产文件、checksum、六个成功任务、七个 active binding、active 总数和旧失败任务均保持不变。archive flag 在两次命令退出后均关闭；归档时间窗内 SignalEvent、notification、scan task 和 strategy signal 增量均为 0。

### 失败历史

旧 v1 packets `eea8e0ba...`、`e4dfff9d...` 和 `e4417822...` 永久失效并保留。前两类失败暴露 `output_start` 执行契约缺失与 asset/Profile coverage 混淆；旧任务 `id=116121` 保持 `failed / active_binding_changed=false`，其当前错误为 `consumer_profile_period_coverage_mismatch`。v2 实现改为 packet 发布前契约校验、独立 asset/consumer smoke 和按 packet 追加式失败证据，不覆盖该历史行。

本 Gate 不代表 EOD automation、SignalEvent、通知、Runtime 长稳或自动交易 Ready；这些范围仍需独立 Plan 和授权。
