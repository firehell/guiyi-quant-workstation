# 当前任务：V1-LIVE-RUNTIME-CLOSURE

更新时间：2026-07-10

任务性质：JM-only 实时观察闭环开发收口；真实外部动作继续逐 Gate 授权

当前状态：`CODE_COMPLETE_EXTERNAL_GATES_PENDING`

实施分支：`codex/v1-live-runtime-closure`

隔离工作树：`/Volumes/扩展盘/guiyi-quant-workstation-live-runtime`

## 目标

把 once 级 live 代码收敛为默认关闭、可监督、可恢复、可审计的 JM actual-contract 运行闭环，同时保持：

- live DB 与 historical active Parquet 隔离。
- confirmed bar 后才评估信号。
- 只观察提醒，不自动交易。
- 全品种扩展独立 Gate。
- RQData、真实 DB 写入、企业微信发送、launchd 加载和腾讯云部署均需后续人工授权。

## 本轮完成的开发范围

- [x] T0：在独立干净 worktree/分支开发，未碰原 UI refactor 脏工作区。
- [x] T1-code：runtime health 按 queue 检查 worker；live/scheduler/archive/notification 区分 disabled/degraded/ok；healthcheck 不再把 HTTP 200 当业务 green。
- [x] T2-code：JM-only 单 APScheduler、Redis singleton lock、coalesce/max_instances/misfire、交易时段时钟、默认关闭和零依赖 dry-run。
- [x] T3-code：confirmed 1m 聚合 5m/15m/30m/60m/1d/1w；日/周关闭由交易日历与 session close grace 决定。
- [x] T4-code：盘后 RQData direct 归档 CLI；复用既有质量/manifest/checksum/登记链；live DB 只作 reference；不新增表。
- [x] T5-code：`LiveSignalEventService` 只写 passed、confirmed、actual-contract 5m/15m；preview 永久零写；revision 产生受控 changed event。
- [x] T6-code：独立 `guiyi-notifications` queue/worker；scheduler 只入队 `source_mode=live_confirmed`；historical replay 不自动入队；最多 3 次重试继续复用 Stage 9 delivery。
- [x] T7-code：scheduler/notification/log-rotate launchd 模板；公网脚本增加 HTTPS redirect、401/200、WS 101 和业务端口关闭检查。
- [ ] T1-ops：恢复并验收 API/Web/backtest/signal worker 的实际 launchd 监督。
- [ ] T3-real：JM 单次真实 1m、全周期聚合和重启恢复 smoke。
- [ ] T4-real：至少一个 JM 交易日真实盘后归档 smoke。
- [ ] T6-real：单条 `live_confirmed` event 企业微信 smoke。
- [ ] T7-ops：5 个交易日（含夜盘）长稳、故障注入、Mac 重启和腾讯云真实域名验收。
- [ ] T8-data：全品种 historical active 90/90 和逐品种 realtime allow-list。

## 本轮没有执行

- 未构造真实 RQData client，未消耗 RQData 配额。
- 未向 PostgreSQL 写入 live bar、archive task、signal event 或 notification。
- 未发送企业微信。
- 未加载、卸载或重启 launchd。
- 未访问或变更腾讯云。
- 未修改策略、回测口径、`report_id=14` 或 Stage 13 trust audit。
- 未修复 8 个全品种 pending 数据资产。

## Feature flags

全部默认 `false`：

```text
GUIYI_LIVE_RUNTIME_ENABLED
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED
GUIYI_WECHAT_AUTOSEND_ENABLED
```

开关只解除对应工程 Gate，不代表授权自动交易；项目不存在自动下单路径。

## 已完成验证

```text
backend tests: 361 passed
frontend Node tests: 27 passed
frontend production build: passed (existing chunk-size warning)
ruff: passed
bash -n scripts/*.sh: passed
plutil deploy/launchd/*.plist.template: passed
git diff --check: passed
```

完整命令和最终状态复核见 `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`。

## 下一 Gate（必须人工确认）

下一步只允许 T1-ops：在确认外接卷权限或迁移本机运行副本后，加载 API/Web/backtest/signal 基础服务并做 kill/restart health 验收。不得同时开启 live、archive 或企业微信 autosend。

完整边界、命令和验收见：`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`。
